import io
import json
import zipfile
from copy import deepcopy
from dataclasses import replace

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.errors import DomainError
from app.portal import review
from app.portal.main import create_app
from app.portal.repository import PortalRepository
from app.portal.settings import PortalSettings
from app.portal.worker import parse_document
from app.repository import Repository, digest
from ingestion.import_reviewed import import_reviewed
from test_portal import pdf_bytes


@pytest.fixture
def parsed(tmp_path):
    config = PortalSettings(data_root=tmp_path, app_env="test", mineru_executable=tmp_path / "mineru-kit.exe")
    config.mineru_executable.touch()
    store = PortalRepository(config.db_path)
    store.initialize()
    source = tmp_path / "raw_pdf/synthetic.pdf"
    source.parent.mkdir()
    source.write_bytes(pdf_bytes())
    doc, _ = store.register_document("a" * 64, "synthetic.pdf", "raw_pdf/synthetic.pdf", 2)
    job = store.claim()
    def parser(command, log_path, timeout, tick):
        assert command[-8:] == ["--pages", "all", "--format", "zip", "--tier", "standard", "--ocr-mode", "auto"]
        raw = {"schema": "docvortex.middle", "schema_version": "2.0", "metadata": {"producer": {"name": "mineru", "version": "4.0.2"}},
            "is_full_document": True, "pages": [{"page_idx": i, "blocks": [{"index": 0, "type": "text",
                "content": [{"type": "text", "content": f"{i+1} 【合成测试】不得自动批准。"}]}]} for i in range(2)]}
        with zipfile.ZipFile(log_path.parent / "export.zip", "w") as archive:
            archive.writestr("middle_json.json", json.dumps(raw, ensure_ascii=False))
            archive.writestr("structured_content.json", "{}")
            archive.writestr("markdown.md", "【合成测试】")
    result = parse_document(job, store, config, parser)
    assert result["candidate_count"] == 2
    return config, store, store.document(doc["id"])


def metadata():
    return dict(standard_code="SYNTHETIC", standard_name="合成测试标准", edition="v1", scope="仅用于软件测试",
                standard_status="synthetic", status_verified_at="2026-09-20", status_source="synthetic fixture")


def test_machine_output_never_approved_and_edits_revoke(parsed):
    config, store, doc = parsed
    payload = doc["payload"]
    uid = payload["candidates"][0]["id"]
    assert all(row["record"]["content_review_status"] == "pending" for row in payload["candidates"])
    with pytest.raises(DomainError):
        review.approve(payload, uid, "test-reviewer", ["text"], config.data_root)
    payload = review.update_metadata(payload, metadata())
    payload = review.approve(payload, uid, "test-reviewer", ["text", "boundary", "context", "assets", "scope"], config.data_root)
    approved = review.item_for(payload, uid)["record"]
    assert approved["content_review_status"] == "approved"
    changed = review.edit_candidate(payload, uid, {"text_verbatim": "【合成测试】修改后须复核。"}, ["p0_b0"], config.data_root)
    assert review.item_for(changed, uid)["record"]["content_review_status"] == "pending"
    assert approved["text_verbatim"] != review.item_for(changed, uid)["record"]["text_verbatim"]
    with pytest.raises(DomainError):
        review.edit_candidate(payload, uid, {}, ["p999_b0"], config.data_root)


@pytest.mark.parametrize("fault", ["missing_page", "missing_asset", "unconfirmed_asset", "unknown_boundary", "duplicate_number"])
def test_non_overridable_review_blocks(parsed, fault):
    config, _, doc = parsed
    payload = review.update_metadata(doc["payload"], metadata())
    item = payload["candidates"][0]
    if fault == "missing_page":
        payload["normalized"]["full_document_covered"] = False
    elif fault == "missing_asset":
        payload["normalized"]["pages"][0]["blocks"][0]["review_issues"] = ["missing_asset:lost.png"]
    elif fault == "unconfirmed_asset":
        payload["normalized"]["pages"][0]["blocks"][0]["review_issues"] = ["visual_asset_unconfirmed"]
    elif fault == "unknown_boundary":
        item["record"]["clause_no"] = "unassigned_1"
    else:
        payload["candidates"][1]["record"]["clause_path"] = item["record"]["clause_path"]
    with pytest.raises(DomainError):
        review.approve(payload, item["id"], "test-reviewer", ["text", "boundary", "context", "assets", "scope"], config.data_root)


def test_split_merge_keep_provenance_and_require_new_review(parsed):
    config, _, doc = parsed
    payload = review.update_metadata(doc["payload"], metadata())
    uid = payload["candidates"][0]["id"]
    split = review.split_candidate(payload, uid, 5)
    assert len(split["candidates"]) == 3
    assert split["candidates"][0]["record"]["source_spans"] == split["candidates"][1]["record"]["source_spans"]
    merged = review.merge_candidates(split, [row["id"] for row in split["candidates"][:2]], config.data_root)
    assert len(merged["candidates"]) == 2
    assert merged["candidates"][0]["record"]["content_review_status"] == "pending"


def test_approved_subset_still_rejects_missing_dependency(parsed, tmp_path):
    config, store, doc = parsed
    payload = review.update_metadata(doc["payload"], metadata())
    uid = payload["candidates"][0]["id"]
    payload["candidates"][0]["record"]["context_clause_uids"] = [payload["candidates"][1]["record"]["clause_uid"]]
    payload = review.approve(payload, uid, "test-reviewer", ["text", "boundary", "context", "assets", "scope"], config.data_root)
    store.save_document(doc["id"], doc["revision"], payload, "pending_review", "test", "test-reviewer")
    repo = Repository(config.evidence_settings().db_path)
    repo.initialize()
    preview = review.release_preview(store, repo, [doc["id"]])
    assert preview["pending_count"] == 1 and preview["clause_count"] == 1
    approved = tmp_path / "subset.jsonl"
    approved.write_text(json.dumps(preview["records"][0], ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DomainError, match="必要上下文"):
        import_reviewed(approved, "version1", repo, config.evidence_settings())


def test_image_content_validation():
    # 合成图片只用于上传边界测试，不是业务联调样本。
    from app.portal.files import validate_image
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "image.png"
        Image.new("RGB", (32, 32), "white").save(path)
        assert validate_image(path)["mime_type"] == "image/png"
        path.write_bytes(b"not-an-image")
        with pytest.raises(DomainError):
            validate_image(path)


def test_changing_dependency_invalidates_approved_dependents(parsed):
    config, _, doc = parsed
    payload = review.update_metadata(doc["payload"], metadata())
    first, second = payload["candidates"]
    second["record"]["context_clause_uids"] = [first["record"]["clause_uid"]]
    for item in (first, second):
        payload = review.approve(payload, item["id"], "test-reviewer", ["text", "boundary", "context", "assets", "scope"], config.data_root)
    changed = review.edit_candidate(payload, first["id"], {"text_verbatim": "【合成测试】依赖条件已修改"}, ["p0_b0"], config.data_root)
    assert all(item["record"]["content_review_status"] == "pending" for item in changed["candidates"])
