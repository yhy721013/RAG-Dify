import io
import json
import zipfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.errors import DomainError
from app.portal.diagnostics import input_contract, run_diagnostics
from app.portal.main import create_app
from app.portal.repository import PortalRepository
from app.portal.settings import PortalSettings
from app.portal.setup import SetupManager, fingerprint
from app.portal.support import diagnostic_zip, tail, task_diagnostics
from app.repository import Repository
from app.safe_diagnostics import public_error, scrub
from app.workflow_client import WorkflowClient

ROOT = Path(__file__).resolve().parents[1]
DATASET = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def environment(tmp_path):
    config = PortalSettings(data_root=tmp_path / "data/portal", app_env="test", dataset_id=DATASET,
        dify_base_url="https://dify.invalid/v1", knowledge_api_key="dataset-synthetic-credential-12345",
        workflow_api_key="app-synthetic-credential-12345", evidence_api_token="synthetic-evidence-secret-12345",
        evidence_public_url="https://evidence.invalid", mineru_executable=tmp_path / "mineru-kit.exe")
    config.mineru_executable.touch()
    store = PortalRepository(config.db_path)
    store.initialize()
    Repository(config.evidence_settings().db_path).initialize()
    store.heartbeat()
    text = "\n".join("PORTAL_" + key + "=" + value for key, value in {
        "DATA_ROOT": str(config.data_root), "DIFY_BASE_URL": config.dify_base_url, "DATASET_ID": DATASET,
        "KNOWLEDGE_API_KEY": config.knowledge_api_key, "WORKFLOW_API_KEY": config.workflow_api_key,
        "EVIDENCE_API_TOKEN": config.evidence_api_token, "EVIDENCE_PUBLIC_URL": config.evidence_public_url}.items()) + "\n"
    (tmp_path / ".env.portal").write_text(text, encoding="utf-8")
    return config, store, SetupManager(config, store, tmp_path)


def contract():
    return json.loads((ROOT / "fixtures/dify_portal/workflow_parameters.real.json").read_text(encoding="utf-8"))


def test_draft_is_write_only_preserves_blank_keys_and_active_file(environment):
    config, store, manager = environment
    original = manager.env.read_bytes()
    meta = manager.save({"max_pdf_pages": "120", "workflow_api_key": ""}, manager.file_revision())
    assert manager.env.read_bytes() == original
    saved, loaded = manager.read_draft(meta["id"])
    assert saved.workflow_api_key == config.workflow_api_key and saved.max_pdf_pages == 120
    assert loaded == meta
    serialized = json.dumps(manager.public())
    assert not any(value in serialized for value in config.secret_values())
    assert "workflow_api_key" in serialized
    manager.env.write_text(manager.env.read_text(encoding="utf-8") + "# external change\n", encoding="utf-8")
    with pytest.raises(DomainError, match="其他操作"):
        manager.read_draft(meta["id"])


def test_url_extraction_and_environment_override(environment, monkeypatch):
    config, _, manager = environment
    meta = manager.save({"dataset_id": f"https://cloud.dify.ai/datasets/{DATASET}/documents"}, manager.file_revision())
    assert manager.read_draft(meta["id"])[0].dataset_id == DATASET
    monkeypatch.setenv("PORTAL_WORKFLOW_API_KEY", "fixed-external-secret")
    with pytest.raises(DomainError, match="环境变量覆盖"):
        manager.save({"workflow_api_key": "new-value"}, manager.file_revision())
    row = next(f for f in manager.public()["fields"] if f["name"] == "workflow_api_key")
    assert row["environment_override"] and row["value"] == ""


def test_config_cannot_switch_existing_library_or_interrupt_jobs(environment):
    config, store, manager = environment
    store.publish("publish1", "version1", 1, 1, "")
    with pytest.raises(DomainError, match="不能换库"):
        manager.save({"dataset_id": "00000000-0000-4000-8000-000000000002"}, manager.file_revision())
    meta = manager.save({"max_pdf_pages": "120"}, manager.file_revision())
    job = store.enqueue("parse", {"document_id": "synthetic"})
    with pytest.raises(DomainError, match="排队或运行"):
        manager.begin_apply(meta["id"])
    assert store.state("maintenance") == ""
    store.progress(job["id"], "complete", status="succeeded")
    manager.begin_apply(meta["id"])
    with pytest.raises(DomainError, match="正在应用"):
        store.enqueue("parse", {"document_id": "another"})
    assert store.claim() is None


@pytest.mark.parametrize("mutation", ["missing", "wrong_type", "extra_required", "limit", "enum"])
def test_contract_blocks_incompatible_inputs(mutation):
    data = contract()
    if mutation == "missing":
        data["user_input_form"].pop()
    elif mutation == "wrong_type":
        field = data["user_input_form"][0].pop("file-list")
        data["user_input_form"][0]["text-input"] = field
    elif mutation == "extra_required":
        data["user_input_form"].append({"text-input": {"variable": "unexpected", "required": True}})
    elif mutation == "limit":
        data["user_input_form"][0]["file-list"]["max_length"] = 1
    else:
        data["user_input_form"][1]["select"]["options"] = []
    errors, _ = input_contract(data, "普通卧式金属车床")
    assert errors


def test_real_input_contract_and_optional_extra_are_compatible():
    errors, warnings = input_contract(contract(), "普通卧式金属车床")
    assert errors == [] and warnings == []
    data = contract()
    data["user_input_form"].append({"text-input": {"variable": "extra", "required": False}})
    errors, warnings = input_contract(data, "普通卧式金属车床")
    assert errors == [] and warnings


def mock_services(config, *, forbidden=False):
    calls = []
    def handle(request):
        calls.append(request)
        assert request.method == "GET"  # 诊断不产生索引、模型或报告。
        path = request.url.path
        if "/datasets/" in path:
            assert request.headers["Authorization"] == "Bearer " + config.knowledge_api_key
            if forbidden:
                return httpx.Response(403, json={"code": "rate_limit_exceeded", "message": config.knowledge_api_key}, headers={"Retry-After": "20"})
            if path.endswith("/metadata"):
                return httpx.Response(200, json={"doc_metadata": [{"id": "field1", "name": "rag_snapshot_id", "type": "string"}]})
            if path.endswith("/documents"):
                return httpx.Response(200, json={"data": [], "page": 1, "total": 0, "has_more": False})
            return httpx.Response(200, json={"id": config.dataset_id, "name": "synthetic", "document_count": 0,
                "indexing_technique": "high_quality", "embedding_model": config.embedding_model,
                "embedding_model_provider": config.embedding_provider, "retrieval_model_dict": {"search_method": "hybrid_search"}})
        if path.endswith("/info"):
            assert request.headers["Authorization"] == "Bearer " + config.workflow_api_key
            return httpx.Response(200, json={"name": "synthetic-app", "mode": "workflow"})
        if path.endswith("/parameters"):
            return httpx.Response(200, json=dynamic_contract())
        if path.endswith("/health"):
            assert "Authorization" not in request.headers
            return httpx.Response(503, json={"status": "not_ready", "database": True, "snapshot_available": False})
        assert path.endswith("/reports/portal-connectivity-probe")
        assert request.headers["Authorization"] == "Bearer " + config.evidence_api_token
        return httpx.Response(404, json={"error": {"code": "report_not_found"}})
    return calls, httpx.MockTransport(handle)


def test_diagnosis_empty_library_is_connected_but_model_is_not_claimed_tested(environment):
    config, store, _ = environment
    calls, transport = mock_services(config)
    result = run_diagnostics(config, store, transport=transport, version_probe=lambda _: {"mineru_version": "4.0.2"})
    assert result["all_connections_passed"] and result["model_invoked"] is False
    assert next(c for c in result["checks"] if c["id"] == "workflow.end_to_end")["status"] == "pending"
    assert next(c for c in result["checks"] if c["id"] == "evidence.https")["status"] == "pass"
    assert not any(secret in json.dumps(result) for secret in config.secret_values())
    assert len(calls) == 9


def test_draft_token_change_waits_for_application_before_authentication(environment):
    config, store, _ = environment
    calls, transport = mock_services(config)
    draft = replace(config, evidence_api_token="synthetic-new-evidence-key")
    result = run_diagnostics(draft, store, active_config=config, transport=transport,
        version_probe=lambda _: {"mineru_version": "4.0.2"})
    checks = [row for row in result["checks"] if row["id"] in {"evidence.local", "evidence.https"}]
    assert len(checks) == 2 and all(row["status"] == "pending" for row in checks)
    assert result["gates"]["assess"] is False
    assert not any("/reports/" in str(request.url) for request in calls)


def test_diagnostic_rejects_foreign_documents_in_existing_library(environment):
    config, store, _ = environment
    _, normal = mock_services(config)
    def handle(request):
        if request.url.path.endswith("/documents"):
            return httpx.Response(200, json={"data": [{"id":"foreign","name":"unregistered"}],"page":1,"total":1,"has_more":False})
        return normal.handle_request(request)
    result = run_diagnostics(config, store, transport=httpx.MockTransport(handle), version_probe=lambda _: {"mineru_version":"4.0.2"})
    assert result["gates"]["publish"] is False and result["gates"]["assess"] is False
    check = next(row for row in result["checks"] if row["id"]=="knowledge.ownership")
    assert check["details"]["unknown_document_ids"] == ["foreign"]


def test_diagnostics_distinguishes_forbidden_rate_limit_and_preserves_reason(environment):
    config, store, _ = environment
    _, transport = mock_services(config, forbidden=True)
    result = run_diagnostics(config, store, transport=transport, version_probe=lambda _: {"mineru_version": "4.0.2"})
    assert not result["gates"]["publish"]
    failed = next(c for c in result["checks"] if c["id"] == "knowledge.connection")
    assert failed["details"]["upstream_status"] == 403
    assert "限流" in failed["suggestion"] and "20" == failed["details"]["retry_after"]
    assert config.knowledge_api_key not in json.dumps(result)


def test_redaction_before_truncation_and_diagnostic_archive(environment, tmp_path):
    config, store, _ = environment
    secret = config.evidence_api_token
    path = tmp_path / "parser.log"
    path.write_text("a" * 200 + secret + "b" * 99, encoding="utf-8")
    output = tail(path, limit=110, secrets=[secret])
    assert secret[-10:] not in output
    error = DomainError("workflow_failed", "failed " + secret, details={"upstream_message": "Authorization: Bearer " + secret,
        "inputs": {"prompt": "private"}, "url": "https://user:password@example.test/file?signature=private"})
    safe = public_error(error, [secret])
    assert secret not in json.dumps(safe) and "signature" not in json.dumps(safe) and "private" not in json.dumps(safe)
    job = store.enqueue("assessment", {"inputs": {"private": "business text"}})
    store.progress(job["id"], "workflow", status="failed", error=safe)
    data = task_diagnostics(store.job(job["id"]), store, config)
    with zipfile.ZipFile(io.BytesIO(diagnostic_zip(data))) as archive:
        assert set(archive.namelist()) == {"diagnostics.json", "README.txt"}
        text = archive.read("diagnostics.json").decode()
        assert "business text" not in text and secret not in text


def test_sse_node_events_keep_only_diagnostic_fields():
    captured = []
    events = [{"event":"node_finished", "workflow_run_id":"run1", "data":{"node_id":"vision","node_type":"llm","title":"视觉观察","status":"failed",
        "error":"model disabled", "inputs":{"secret":"do-not-log"},"outputs":{"text":"do-not-log"}}},
        {"event":"workflow_finished","workflow_run_id":"run1","data":{"id":"run1","status":"failed","error":"model disabled"}}]
    content = "".join("data: " + json.dumps(row) + "\n\n" for row in events)
    with WorkflowClient("https://dify.invalid/v1", "synthetic", httpx.MockTransport(lambda _: httpx.Response(200, text=content, headers={"Content-Type":"text/event-stream"}))) as client:
        client.on_event = captured.append
        result = client.run({}, "local", lambda _:None)
    assert result["status"] == "failed" and captured[0]["title"] == "视觉观察"
    assert "do-not-log" not in json.dumps(captured)


def test_setup_api_does_not_expose_secrets_or_allow_csrf(environment):
    config, store, manager = environment
    app = create_app(config, project_root=manager.root)
    with TestClient(app, base_url=config.origin) as client:
        token = client.get("/api/status").json()["csrf_token"]
        response = client.get("/api/setup")
        assert not any(secret in response.text for secret in config.secret_values())
        assert client.post("/api/setup/draft", json={"values":{},"file_revision":manager.file_revision()}).status_code == 403
        client.headers.update({"Origin":config.origin,"X-CSRF-Token":token})
        response = client.post("/api/setup/draft", json={"values":{"max_pdf_pages":"99"},"file_revision":manager.file_revision()})
        assert response.status_code == 200
        dsl = client.get("/api/setup/workflow.yml?source=draft&draft_id=" + response.json()["id"])
        assert dsl.status_code == 200 and not any(secret in dsl.text for secret in config.secret_values())
        assert "portal-v3-dynamic" in dsl.text and "diagnostic_mode" not in dsl.text


def test_worker_does_not_own_portal_control_processes(environment):
    _, store, _ = environment
    tunnel = store.enqueue("tunnel", {"action": "start"})
    diagnostic = store.enqueue("diagnostics", {"source": "active"})
    parse = store.enqueue("parse", {"document_id": "synthetic"})
    assert store.claim()["id"] == parse["id"]
    assert store.claim() is None
    store.progress(tunnel["id"], "tunnel")
    store.progress(diagnostic["id"], "diagnosing")
    store.recover(include_controls=False)
    assert store.job(tunnel["id"])["status"] == "running"
    assert store.job(diagnostic["id"])["status"] == "running"


@pytest.mark.parametrize("change_during", ["stop", "launch", "none"])
def test_apply_preserves_concurrent_edits_and_rolls_back_own_changes(environment, monkeypatch, change_during):
    from app.portal import services
    config, store, manager = environment
    original = manager.env.read_text(encoding="utf-8")
    meta = manager.save({"max_pdf_pages": "120"}, manager.file_revision())
    manager.begin_apply(meta["id"])
    processes = {"processes": [{"role": role, "id": index} for index, role in enumerate(("portal", "evidence", "worker"))]}
    (manager.runtime / "processes.json").write_text(json.dumps(processes), encoding="utf-8")
    monkeypatch.setattr(services, "bootstrap_settings", lambda: (config, ""))
    monkeypatch.setattr(services, "SetupManager", lambda *_: manager)
    external = original + "# concurrent external edit\n"
    def stop(entry):
        if change_during == "stop":
            manager.env.write_text(external, encoding="utf-8")
    launched = []
    def launch(role, *_):
        launched.append(role)
        if len(launched) == 1:
            if change_during == "launch":
                manager.env.write_text(external, encoding="utf-8")
            raise RuntimeError("synthetic launch failure")
        return {"role": role, "id": len(launched) + 100}
    monkeypatch.setattr(services, "stop_owned", stop)
    monkeypatch.setattr(services, "launch_role", launch)
    services.apply_configuration(meta["id"])
    result = json.loads(manager.apply_path.read_text(encoding="utf-8"))
    assert result["status"] == "failed" and store.state("maintenance") == ""
    assert manager.env.read_text(encoding="utf-8") == (original if change_during == "none" else external)
    assert result["configuration_restored"] is (change_during == "none")
    assert manager.draft.exists()  # 可重新保存，失败不会悄悄删除草稿。
    assert len(launched) == {"stop": 0, "launch": 1, "none": 3}[change_during]


def test_bootstrap_retains_identity_when_numeric_config_is_invalid(environment, monkeypatch):
    from app.portal import settings
    config, _, manager = environment
    manager.env.write_text(manager.env.read_text(encoding="utf-8") + "PORTAL_MAX_PDF_PAGES=invalid\n", encoding="utf-8")
    monkeypatch.setattr(settings, "ROOT", manager.root)
    recovered, issue = settings.bootstrap_settings()
    assert issue and recovered.data_root == config.data_root
    assert recovered.dataset_id == config.dataset_id and recovered.secret_values() == config.secret_values()
    assert recovered.max_pdf_pages == 300


def test_repair_to_fallback_value_clears_startup_error(environment, monkeypatch):
    from app.portal import main
    config, _, manager = environment
    manager.env.write_text(manager.env.read_text(encoding="utf-8") + "PORTAL_MAX_PDF_PAGES=invalid\n", encoding="utf-8")
    meta = manager.save({"max_pdf_pages": "300"}, manager.file_revision())
    assert "max_pdf_pages" in meta["changed_fields"]
    monkeypatch.setattr(main, "bootstrap_settings", lambda: (config, "numeric configuration invalid"))
    with TestClient(create_app(project_root=manager.root), base_url=config.origin) as client:
        assert client.get("/api/status").json()["configuration_error"]
        manager.apply_path.write_text(json.dumps({"status":"succeeded", "fingerprint": fingerprint(config)}), encoding="utf-8")
        monkeypatch.setattr(main, "bootstrap_settings", lambda: (config, ""))
        assert client.get("/api/status").json()["configuration_error"] == ""


def dynamic_contract():
    # Synthetic v3 parameters; keep the captured v2 fixture immutable.
    from workflows.build_portal import build_portal
    value = build_portal(PortalSettings(dataset_id="synthetic", evidence_public_url="https://example.invalid"),
        json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8")))
    fields = next(n["data"]["variables"] for n in value["workflow"]["graph"]["nodes"] if n["id"] == "start")
    return {"user_input_form": [{f["type"]: f} for f in fields]}
