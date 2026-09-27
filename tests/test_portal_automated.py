"""合成 PDF/MockTransport 离线验收，不代表真实业务联调。"""
import json
from copy import deepcopy
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.errors import DomainError
from app.portal import automated, review, worker
from app.portal.main import create_app
from app.repository import Repository, json_text
from app.dify_client import DifyClient
from app.evidence import prepare
from app.reporting import finalize
from app.schemas import PrepareRequest, FinalizeRequest
from ingestion.import_reviewed import import_reviewed
from evals.evaluate_retrieval import evaluation_path
from conftest import draft_for
from test_portal_review import parsed, metadata
from test_snapshot_partitions import PartitionDify


def setup(parsed):
    config, store, doc = parsed
    config = replace(config, dataset_id="demo_dataset", knowledge_api_key="synthetic",
                     dify_base_url="https://dify.invalid/v1")
    supplied = {doc["id"]: {k: v for k, v in metadata().items() if k in automated.IDENTITY}}
    repo = Repository(config.evidence_settings().db_path)
    repo.initialize()
    return config, store, doc, supplied, repo


def test_auto_preview_deterministic_and_never_changes_review(parsed, tmp_path):
    config, store, doc, supplied, repo = setup(parsed)
    value = automated.preview(store, repo, [doc["id"]], config.data_root, supplied)
    assert value == automated.preview(store, repo, [doc["id"]], config.data_root, supplied)
    assert not value["blockers"] and len(value["records"]) == 2
    assert store.document(doc["id"]) == doc
    assert all(r["content_review_status"] == "machine_checked" and not r["reviewed_by"]
               and not r["evidence_complete"] for r in value["records"])
    path = tmp_path / "machine.jsonl"
    path.write_text("\n".join(json_text(r) for r in value["records"]), encoding="utf-8")
    with pytest.raises(DomainError):
        import_reviewed(path, "auto1", repo, config.evidence_settings())
    import_reviewed(path, "auto1", repo, config.evidence_settings(), mode="automated")
    assert import_reviewed(path, "auto1", repo, config.evidence_settings(), mode="automated")["status"] == "unchanged"


@pytest.mark.parametrize("fault", ["pages", "source", "asset", "boundary", "rejected", "split", "empty_page"])
def test_machine_hard_blocks_and_dependency_closure(parsed, fault):
    config, store, doc, supplied, repo = setup(parsed)
    payload = deepcopy(doc["payload"])
    if fault == "pages": payload["normalized"]["full_document_covered"] = False
    elif fault == "source": (config.data_root / doc["source_path"]).write_bytes(b"damaged synthetic")
    elif fault == "empty_page": payload["normalized"]["coverage"][0]["status"] = "empty_page_requires_review"
    else:
        record = payload["candidates"][0]["record"]
        if fault == "boundary": record["boundary_status"] = "unknown"
        elif fault == "rejected": record["content_review_status"] = "rejected"
        elif fault == "split": record["review_issues"].append("split_boundary_and_source_review_required")
        else: record["asset_refs"] = ["missing.png"]
    store.save_document(doc["id"], doc["revision"], payload, "parsed", "test", "synthetic")
    try:
        result = automated.preview(store, repo, [doc["id"]], config.data_root, supplied)
    except DomainError as error:
        assert error.code == "machine_check_required"
    else:
        assert result["excluded"] and result["blockers"]  # 第2条依赖已排除的第1条


def test_auto_api_worker_publish_evidence_report_and_second_batch(parsed, monkeypatch, request_body):
    config, store, doc, supplied, repo = setup(parsed)
    fake = PartitionDify()
    monkeypatch.setattr(worker, "DifyClient", lambda settings: DifyClient(settings, httpx.MockTransport(fake.handle)))
    real_evaluate = worker.evaluate
    monkeypatch.setattr(worker, "evaluate", lambda *args, **kwargs: real_evaluate(*args, **{**kwargs, "interval_seconds": 0}))
    app = create_app(config)
    with TestClient(app, base_url=config.origin) as api:
        token = api.get("/api/status").json()["csrf_token"]
        api.headers.update({"Origin": config.origin, "X-CSRF-Token": token})
        body = {"document_ids": [doc["id"]], "mode": "automated", "metadata": supplied}
        preview = api.post("/api/releases/preview", json=body)
        assert preview.status_code == 200, preview.text
        body["preview_hash"] = preview.json()["preview_hash"]
        first = api.post("/api/releases", json=body)
        assert first.status_code == 200, first.text
        assert api.post("/api/releases", json=body).json()["id"] == first.json()["id"]
        job = store.job(first.json()["id"])
        worker.execute(job, store, config)
        assert store.job(job["id"])["status"] == "succeeded", store.job(job["id"])
        snapshot = store.state("current_snapshot")
        old = repo.all_clauses(snapshot)
        metric = json.loads(evaluation_path(config.evidence_settings(), snapshot).read_text(encoding="utf-8"))
        assert metric["evaluation_kind"] == "automated_smoke" and not metric["human_annotated"]
        assert "annotated_by" not in job["payload"]["cases"][0]
        client = DifyClient(config.evidence_settings(), httpx.MockTransport(fake.handle))
        hits = client.retrieve("合成文本", {"metadata_filtering_conditions": client.snapshot_filter(snapshot)})
        body2 = deepcopy(request_body)
        body2["snapshot_id"] = snapshot
        for check in body2["checks"]: check["hits"] = hits
        context = prepare(PrepareRequest.model_validate(body2), repo, config.evidence_settings(), "synthetic")
        assert context["knowledge_review_status"] == "human_review_required"
        assert all(not e["evidence_complete"] and e["completeness_issues"] for e in context["evidence"])
        report = finalize(FinalizeRequest.model_validate(draft_for(context)), repo, "synthetic")
        assert "未经人工复核" in report["markdown"]
        with pytest.raises(DomainError):
            finalize(FinalizeRequest.model_validate(draft_for(context, "evidence_supported_risk")), repo, "synthetic")
        # 第二批为不同标准，同库累计，旧快照与旧报告不变。
        second, _ = store.register_document("b" * 64, "second.pdf", doc["source_path"], 2)
        store.save_document(second["id"], second["revision"], doc["payload"], "parsed", "test", "synthetic")
        extra = {second["id"]: {**supplied[doc["id"]], "standard_code": "SYNTHETIC-2"}}
        body = {"document_ids": [second["id"]], "mode": "automated", "metadata": extra}
        value = api.post("/api/releases/preview", json=body).json()
        assert value["standard_count"] == 2 and value["clause_count"] == 4 and not value["replacements"]
        body["preview_hash"] = value["preview_hash"]
        second_job = api.post("/api/releases", json=body).json()
        worker.execute(store.job(second_job["id"]), store, config)
        assert store.job(second_job["id"])["status"] == "succeeded", store.job(second_job["id"])
        assert repo.all_clauses(snapshot) == old
        assert len(repo.all_clauses(store.state("current_snapshot"))) == 4
        assert automated.preview(store, repo, [second["id"]], config.data_root, extra)["unchanged"]
        assert report["snapshot_id"] == snapshot


def test_failed_evaluation_archive_and_same_job_recovery(parsed, monkeypatch):
    config, store, doc, supplied, repo = setup(parsed)
    fake = PartitionDify()
    unavailable = [True]

    def handle(request):
        if unavailable[0] and request.url.path.endswith("/retrieve"):
            return httpx.Response(503, json={"code": "unavailable", "message": "synthetic"})
        return fake.handle(request)

    monkeypatch.setattr(worker, "DifyClient", lambda settings: DifyClient(settings, httpx.MockTransport(handle)))
    monkeypatch.setattr("evals.evaluate_retrieval.time.sleep", lambda seconds: None)
    with TestClient(create_app(config), base_url=config.origin) as api:
        api.headers.update({"Origin": config.origin, "X-CSRF-Token": api.get("/api/status").json()["csrf_token"]})
        body = {"document_ids": [doc["id"]], "mode": "automated", "metadata": supplied}
        body["preview_hash"] = api.post("/api/releases/preview", json=body).json()["preview_hash"]
        job = api.post("/api/releases", json=body).json()
        worker.execute(store.job(job["id"]), store, config)
        failed = store.job(job["id"])
        assert failed["status"] == "failed" and not store.state("current_snapshot")
        assert failed["result"]["completed"] == failed["result"]["total"]
        snapshot = failed["result"]["snapshot_id"]
        path = evaluation_path(config.evidence_settings(), snapshot)
        prior = json.loads(path.read_text(encoding="utf-8"))
        assert not prior["passed"] and all(len(row["attempt_errors"]) == 3 for row in prior["cases"])
        documents = deepcopy(fake.docs)
        unavailable[0] = False
        api.post(f'/api/jobs/{job["id"]}/retry').raise_for_status()
        worker.execute(store.job(job["id"]), store, config)
        assert store.job(job["id"])["status"] == "succeeded" and fake.docs == documents
        archive = list(path.parent.glob(path.stem + "_attempt_*.json"))
        assert len(archive) == 1 and json.loads(archive[0].read_text(encoding="utf-8")) == prior
        assert json.loads(path.read_text(encoding="utf-8"))["passed"]


def test_stale_preview_and_replacement_and_stale_worker(parsed):
    config, store, doc, supplied, repo = setup(parsed)
    value = automated.preview(store, repo, [doc["id"]], config.data_root, supplied)
    value.update(snapshot_id="candidate_test", cases=automated.smoke_cases(value, "candidate_test"))
    job = store.enqueue("publish", value)
    store.save_document(doc["id"], doc["revision"], doc["payload"], "parsed", "test", "synthetic")
    worker.execute(job, store, config)
    assert store.job(job["id"])["error"]["code"] == "revision_conflict"
    assert not repo.all_clauses("candidate_test")


def test_api_rejects_stale_hash_fake_reviewer_and_unconfirmed_replacement(parsed, tmp_path):
    config, store, doc, supplied, repo = setup(parsed)
    value = automated.preview(store, repo, [doc["id"]], config.data_root, supplied)
    path = tmp_path / "records.jsonl"
    path.write_text("\n".join(json_text(r) for r in value["records"]), encoding="utf-8")
    import_reviewed(path, "baseline", repo, config.evidence_settings(), mode="automated")
    store.publish("synthetic", "baseline", 2, 1, "")
    payload = deepcopy(doc["payload"])
    payload["candidates"][1]["record"]["text_verbatim"] += "合成修订。"
    store.save_document(doc["id"], doc["revision"], payload, "parsed", "test", "synthetic")
    with TestClient(create_app(config), base_url=config.origin) as api:
        api.headers.update({"Origin": config.origin, "X-CSRF-Token": api.get("/api/status").json()["csrf_token"]})
        body = {"document_ids": [doc["id"]], "mode": "automated", "metadata": supplied}
        value = api.post("/api/releases/preview", json=body).json()
        assert value["replacements"]
        body["preview_hash"] = "stale"
        assert api.post("/api/releases", json=body).json()["error"]["code"] == "revision_conflict"
        body["preview_hash"] = value["preview_hash"]
        assert api.post("/api/releases", json=body).json()["error"]["code"] == "replacement_confirmation"
        body.update(confirm_replacements=True, actor="invented reviewer")
        assert api.post("/api/releases", json=body).json()["error"]["code"] == "input_error"


@pytest.mark.parametrize("field,value", [("reviewed_by", "fake"), ("evidence_complete", True),
    ("boundary_status", "unknown"), ("review_issues", ["human_review_required", "missing_asset:x"])])
def test_machine_record_cannot_claim_review_or_drop_hard_blocks(parsed, field, value):
    config, store, doc, supplied, repo = setup(parsed)
    record = automated.preview(store, repo, [doc["id"]], config.data_root, supplied)["records"][0]
    record[field] = value
    with pytest.raises(DomainError): automated.validate_machine_record(record)


def test_exact_blank_page_requires_no_paint_no_annotations_and_no_parsed_blocks(parsed):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject
    config, _, doc, _, _ = setup(parsed)
    doc = deepcopy(doc)
    doc["payload"]["normalized"]["pages"][0]["blocks"] = []
    checks = [{"code": "empty_pages", "pages": [1]}]
    assert automated.verified_blank_pages(doc, config.data_root, checks) == [1]
    assert automated.verified_blank_pages(doc, config.data_root, checks + [{"code": "missing_pages"}]) == []
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    content = DecodedStreamObject()
    content.set_data(b"0 0 10 10 re f")
    page[NameObject("/Contents")] = writer._add_object(content)
    with (config.data_root / doc["source_path"]).open("wb") as stream:
        writer.write(stream)
    assert automated.verified_blank_pages(doc, config.data_root, checks) == []


def test_bad_dependent_is_excluded_without_dropping_its_dependency_edge(parsed):
    config, store, doc, supplied, repo = setup(parsed)
    payload = deepcopy(doc["payload"])
    payload["candidates"][1]["record"]["context_clause_uids"] = ["missing_clause"]
    store.save_document(doc["id"], doc["revision"], payload, "parsed", "test", "synthetic")
    value = automated.preview(store, repo, [doc["id"]], config.data_root, supplied)
    assert [r["clause_no"] for r in value["records"]] == ["1"]
    assert value["excluded"][0]["reasons"] == ["dependency_not_publishable"]
    assert not value["blockers"]
    assert store.document(doc["id"])["payload"]["candidates"][1]["record"]["context_clause_uids"] == ["missing_clause"]


def test_list_labels_are_not_missing_parentheses_but_broken_prose_still_is():
    from app.portal.assistance import unbalanced_parentheses
    assert not unbalanced_parentheses("本标准（合成）不适用：\na) 项目一；\nb) 项目二。")
    assert unbalanced_parentheses("本标准（合成不适用：\na) 项目一；\nb) 项目二。")
    assert unbalanced_parentheses("正文缺失了起始括号）。")
    assert unbalanced_parentheses("a) 孤立编号仍需检查。")
    assert unbalanced_parentheses("a) 项目一；\nc) 跳号仍需检查。")
