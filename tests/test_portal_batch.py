"""批处理离线契约测试；不调用真实 Dify，不批准业务条款。"""
import json

import httpx
import pytest

from app.portal.batch import BatchClient, automated, ingest, publish
from app.repository import sha256
from ingestion.mineru_adapter import file_sha256


def test_auto_upload_publish_and_resume_without_resubmission(tmp_path):
    source = tmp_path / "pdfs"
    source.mkdir()
    (source / "one.pdf").write_bytes(b"synthetic")
    checksum = file_sha256(source / "one.pdf")
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/documents":
            return httpx.Response(200, json={"document_id": "pdf_test", "reused": False, "parse_job": {"id": "parse"}})
        if request.url.path == "/api/documents/pdf_test":
            return httpx.Response(200, json={"sha256": checksum, "payload": {"candidates": [{}], "normalized": {"full_document_covered": True}}})
        if request.url.path == "/api/releases/preview":
            assert json.loads(request.content)["mode"] == "automated"
            return httpx.Response(200, json={"preview_hash": "h", "blockers": [], "unchanged": False, "replacements": [], "excluded": []})
        if request.url.path == "/api/releases":
            body = json.loads(request.content)
            assert "actor" not in body and "cases" not in body
            return httpx.Response(200, json={"id": "publish", "status": "queued"})
        return httpx.Response(200, json={"id": request.url.path.rsplit("/", 1)[1], "status": "succeeded"})
    api = BatchClient(client=httpx.Client(base_url="http://127.0.0.1:8001", transport=httpx.MockTransport(handle)))
    manifest = tmp_path / "batch/manifest.json"
    assert automated(api, source, manifest, 1)["status"] == "succeeded"
    assert automated(api, source, manifest, 1)["status"] == "succeeded"
    assert calls.count(("POST", "/api/releases")) == 1
    assert calls.count(("POST", "/api/documents")) == 1
    state = json.loads(manifest.read_text(encoding="utf-8"))
    del state["publish_intent"]["job_id"]
    manifest.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="结果未知"):
        automated(api, source, manifest, 1)
    assert calls.count(("POST", "/api/releases")) == 1
    api.close()


def test_local_session_and_no_remote_endpoint():
    with pytest.raises(ValueError):
        BatchClient("https://example.com")
    with pytest.raises(ValueError):
        BatchClient("http://user:pass@localhost:8001")
    def handle(request):
        if request.url.path == "/api/status":
            return httpx.Response(200, json={"csrf_token": "synthetic-token"},
                                  headers={"set-cookie": "portal_session=synthetic-token; Path=/; HttpOnly"})
        assert request.headers["origin"] == "http://127.0.0.1:8001"
        assert request.headers["x-csrf-token"] == "synthetic-token"
        assert "portal_session=synthetic-token" in request.headers["cookie"]
        return httpx.Response(200, json={"ok": True})
    api = BatchClient(client=httpx.Client(base_url="http://127.0.0.1:8001", transport=httpx.MockTransport(handle)))
    api.connect()
    assert api.request("POST", "/api/test", json={}) == {"ok": True}
    api.close()


def test_ingest_resume_dedup_and_preserve_pending(tmp_path):
    source = tmp_path / "pdfs"
    source.mkdir()
    (source / "one.pdf").write_bytes(b"synthetic PDF stand-in, not a real parsing test")
    (source / "copy.PDF").write_bytes((source / "one.pdf").read_bytes())
    calls = []
    doc = {"sha256": file_sha256(source / "one.pdf"), "payload": {
        "candidates": [{"record": {"content_review_status": "pending"}}],
        "normalized": {"full_document_covered": True}}}
    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/documents":
            return httpx.Response(200, json={"document_id": "pdf_test", "reused": False,
                                             "parse_job": {"id": "job_test"}})
        if request.url.path == "/api/jobs/job_test":
            return httpx.Response(200, json={"status": "succeeded"})
        return httpx.Response(200, json=doc)
    api = BatchClient(client=httpx.Client(base_url="http://127.0.0.1:8001", transport=httpx.MockTransport(handle)))
    manifest = tmp_path / "batch/manifest.json"
    result = ingest(api, source, manifest, 1)
    ingest(api, source, manifest, 1)
    assert len(result["files"]) == 1
    assert result["files"][0]["status"] == "parsed"
    assert calls.count(("POST", "/api/documents")) == 1
    exported = json.loads((manifest.parent / "pdf_test.review.json").read_text(encoding="utf-8"))
    assert exported["payload"]["candidates"][0]["record"]["content_review_status"] == "pending"
    api.close()


def test_publish_lost_response_keeps_intent_and_refuses_resubmit(tmp_path):
    pre, cases, manifest = tmp_path / "preview.json", tmp_path / "cases.json", tmp_path / "manifest.json"
    pre.write_text(json.dumps({"origin": "http://127.0.0.1:8001", "document_ids": ["pdf_test"],
                               "preview": {"preview_hash": "synthetic"}}), encoding="utf-8")
    cases.write_text('[{"case_id":"manual_1"}]', encoding="utf-8")
    def handle(request):
        raise httpx.ReadTimeout("synthetic lost response", request=request)
    api = BatchClient(client=httpx.Client(base_url="http://127.0.0.1:8001", transport=httpx.MockTransport(handle)))
    with pytest.raises(httpx.ReadTimeout):
        publish(api, pre, cases, "synthetic reviewer", False, manifest, 1)
    assert json.loads(manifest.read_text())["publish_intent"]["status"] == "submitting"
    with pytest.raises(ValueError, match="已有发布意图"):
        publish(api, pre, cases, "synthetic reviewer", False, manifest, 1)
    api.close()


def test_failed_parse_continues_other_files(tmp_path):
    source = tmp_path / "pdfs"
    source.mkdir()
    for name in ("one", "two"):
        (source / (name + ".pdf")).write_bytes(name.encode())
    class Fake:
        origin = "http://127.0.0.1:8001"
        def request(self, method, path, **kwargs):
            if method == "POST":
                data = kwargs["files"]["file"][1].read().decode()
                return {"document_id": data, "reused": False, "parse_job": {"id": data}}
            return {"sha256": sha256(path.rsplit("/", 1)[-1]), "payload": {}}
        def wait(self, job_id, timeout):
            return {"status": "failed", "error": {"code": "synthetic_parse_error"}}
    result = ingest(Fake(), source, tmp_path / "manifest.json", 1)
    assert len(result["files"]) == 2
    assert all(row["status"] == "failed" for row in result["files"])
