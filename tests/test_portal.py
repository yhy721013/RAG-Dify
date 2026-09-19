import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.errors import DomainError
from app.portal.main import create_app
from app.portal.repository import PortalRepository
from app.portal.settings import PortalSettings


@pytest.fixture
def portal(tmp_path):
    config = PortalSettings(data_root=tmp_path, app_env="test", max_pdf_pages=3)
    app = create_app(config)
    with TestClient(app, base_url=config.origin) as client:
        token = client.get("/api/status").json()["csrf_token"]
        client.headers.update({"Origin": config.origin, "X-CSRF-Token": token})
        yield client, app.state.store, config


def pdf_bytes(pages=2, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if encrypted:
        writer.encrypt("synthetic-password")
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_upload_duplicate_reuses_task_and_survives_restart(portal):
    client, store, config = portal
    data = pdf_bytes()
    first = client.post("/api/documents", files={"file": ("test.pdf", data, "application/pdf")})
    assert first.status_code == 200 and not first.json()["reused"]
    second = client.post("/api/documents", files={"file": ("renamed.pdf", data, "application/pdf")})
    assert second.json()["reused"] and second.json()["document_id"] == first.json()["document_id"]
    fresh = PortalRepository(config.db_path)
    fresh.initialize()
    assert len(fresh.jobs()) == 1
    assert fresh.document(first.json()["document_id"])["page_count"] == 2
    assert client.get("/api/jobs").json()[0].get("payload") is None


@pytest.mark.parametrize("name,content,code", [
    ("not.pdf", b"invalid pdf", "invalid_pdf"),
    ("wrong.txt", b"%PDF-1.7", "invalid_pdf"),
    ("locked.pdf", pdf_bytes(encrypted=True), "encrypted_pdf"),
    ("long.pdf", pdf_bytes(4), "page_limit"),
], ids=["corrupt", "extension", "encrypted", "pages"])
def test_invalid_upload_not_queued(portal, name, content, code):
    client, store, _ = portal
    response = client.post("/api/documents", files={"file": (name, content, "application/pdf")})
    assert response.status_code == 422 and response.json()["error"]["code"] == code
    assert store.jobs() == []


def test_local_csrf_and_configuration_boundary(portal):
    client, store, _ = portal
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    assert client.post("/api/documents", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/documents", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    status = client.get("/api/status").json()
    assert not status["configured"]["workflow"]
    assert "knowledge_api_key" not in status
    assert "Content-Security-Policy" in client.get("/").headers


def test_restart_and_ambiguous_assessment_never_resubmit(portal):
    _, store, _ = portal
    item = store.enqueue("assessment", {"snapshot_id": "snapshot_1"}, "submission_1")
    assert store.enqueue("assessment", {"snapshot_id": "snapshot_1"}, "submission_1")["id"] == item["id"]
    with pytest.raises(DomainError, match="不同内容"):
        store.enqueue("assessment", {"snapshot_id": "snapshot_2"}, "submission_1")
    store.claim()
    store.progress(item["id"], "workflow", {"submitted": True})
    store.recover()
    with pytest.raises(DomainError, match="禁止自动重发"):
        store.retry(item["id"])
    store.progress(item["id"], "workflow", {"submitted": True, "run_id": "run_1"}, status="interrupted")
    assert store.retry(item["id"])["status"] == "queued"


def test_revision_conflicts_and_atomic_release_pointer(portal):
    _, store, _ = portal
    doc, _ = store.register_document("a" * 64, "synthetic.pdf", "raw_pdf/synthetic.pdf", 1)
    store.save_document(doc["id"], 0, {}, "pending_review", "edit", "synthetic")
    with pytest.raises(DomainError):
        store.save_document(doc["id"], 0, {}, "pending_review", "edit", "synthetic")
    store.publish("job_1", "snapshot_1", 1, 1, "")
    with pytest.raises(DomainError):
        store.publish("job_2", "snapshot_2", 2, 2, "")
    assert store.state("current_snapshot") == "snapshot_1"
    store.publish("job_2", "snapshot_2", 2, 2, "snapshot_1")
    assert len(store.releases()) == 2
