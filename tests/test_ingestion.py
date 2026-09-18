import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.errors import DomainError
from app.repository import Repository, json_text
from ingestion.build_clauses import candidates
from ingestion.import_reviewed import import_reviewed
from ingestion.mineru_adapter import adapt, unpack
from conftest import synthetic_clause


@pytest.fixture
def export(tmp_path, monkeypatch):
    root = tmp_path / "parsed"
    root.mkdir()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic-source-only")
    monkeypatch.setattr("ingestion.mineru_adapter.PdfReader", lambda path: SimpleNamespace(pages=[None, None, None]))
    raw = {"schema": "docvortex.middle", "schema_version": "2.0", "metadata": {"producer": {"name": "mineru", "version": "4.0.2"}},
           "is_full_document": True, "pages": [
               {"page_idx": 0, "blocks": [{"index": 0, "type": "index", "content": [{"type": "text", "content": "1 目录项……1"}]}]},
               {"page_idx": 1, "blocks": [{"index": 0, "type": "paragraph_title", "content": [{"type": "text", "content": "1 测试条款"}]},
                                           {"index": 1, "type": "text", "content": [{"type": "text", "content": "不得删除否定词。"}]}]},
               {"page_idx": 2, "blocks": [{"index": 0, "type": "text", "content": [{"type": "text", "content": "跨页条件。"}]},
                                           {"index": 1, "type": "table", "content": [{"type": "table_body", "image_path": "images/missing.png", "content": "<table>测试</table>"}]}]}]}
    (root / "markdown.md").write_text("合成测试", encoding="utf-8")
    (root / "structured_content.json").write_text("{}", encoding="utf-8")
    (root / "middle_json.json").write_text(json_text(raw), encoding="utf-8")
    return root, source, raw


def test_native_contract_full_coverage_toc_cross_page_and_assets(export, tmp_path):
    root, source, _ = export
    result = adapt(root, source, tmp_path)
    items = candidates(result, tmp_path)
    assert result["full_document_covered"] and len(result["coverage"]) == 3
    assert len(items) == 1 and items[0]["clause_no"] == "1"
    assert "跨页条件" in items[0]["text_verbatim"] and "不得删除" in items[0]["text_verbatim"]
    assert "cross_page_review_required" in items[0]["review_issues"]
    assert any(issue.startswith("missing_asset:") for issue in items[0]["review_issues"])
    assert not items[0]["evidence_complete"] and items[0]["content_review_status"] == "pending"
    assert items[0]["source_spans"][0]["printed_page_label"] is None


@pytest.mark.parametrize("mutation", ["missing_page", "duplicate_page", "old_contract", "wrong_version", "missing_file"])
def test_bad_export(export, tmp_path, mutation):
    root, source, raw = export
    if mutation == "missing_page":
        raw["pages"].pop(0)
    elif mutation == "duplicate_page":
        raw["pages"].append(raw["pages"][0])
    elif mutation == "old_contract":
        raw["schema"] = "project.internal"
    elif mutation == "wrong_version":
        raw["metadata"]["producer"]["version"] = "3.0.0"
    else:
        (root / "markdown.md").unlink()
    (root / "middle_json.json").write_text(json_text(raw), encoding="utf-8")
    if mutation == "missing_page":
        result = adapt(root, source, tmp_path)
        assert not result["full_document_covered"] and result["missing_pages"] == [0]
    else:
        with pytest.raises(DomainError):
            adapt(root, source, tmp_path)


def test_real_blank_page_omits_blocks(export, tmp_path):
    root, source, raw = export
    raw["pages"][0] = {"page_idx": 0}
    (root / "middle_json.json").write_text(json_text(raw), encoding="utf-8")
    document = adapt(root, source, tmp_path)
    assert document["full_document_covered"]
    assert document["coverage"][0]["status"] == "empty_page_requires_review"


def test_zip_path_traversal(tmp_path):
    import zipfile
    package = tmp_path / "bad.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("../outside.txt", "bad")
    with pytest.raises(DomainError):
        unpack(package, tmp_path / "unpack")
    assert not (tmp_path / "outside.txt").exists()


def approved_record():
    return synthetic_clause(standard_uid="", clause_uid="", standard_status="synthetic",
                            status_verified_at="2026-09-18", status_source="synthetic-fixture")


def write_approved(tmp_path, records):
    path = tmp_path / "approved.jsonl"
    path.write_text("".join(json_text(row) + "\n" for row in records), encoding="utf-8")
    return path


def test_import_idempotent_immutable_snapshot(settings, tmp_path):
    repo = Repository(settings.db_path)
    repo.initialize()
    record = approved_record()
    path = write_approved(tmp_path, [record])
    assert import_reviewed(path, "pilot", repo, settings)["status"] == "candidate"
    assert import_reviewed(path, "pilot", repo, settings)["status"] == "unchanged"
    record["text_verbatim"] = "已改动"
    record["content_sha256"] = ""
    write_approved(tmp_path, [record])
    with pytest.raises(DomainError, match="不可修改"):
        import_reviewed(path, "pilot", repo, settings)
    assert import_reviewed(path, "new_pilot", repo, settings)["status"] == "candidate"


@pytest.mark.parametrize("field,value", [("content_review_status", "pending"), ("reviewed_by", ""),
    ("review_issues", ["missing_asset"]), ("boundary_status", "unknown"), ("full_document_covered", False),
    ("context_clause_uids", ["missing"]), ("content_sha256", "wrong"), ("clause_uid", "forged")])
def test_review_gate(settings, tmp_path, field, value):
    repo = Repository(settings.db_path)
    repo.initialize()
    record = approved_record()
    record[field] = value
    with pytest.raises(DomainError):
        import_reviewed(write_approved(tmp_path, [record]), "pilot", repo, settings)
    assert repo.all_clauses("pilot") == []
