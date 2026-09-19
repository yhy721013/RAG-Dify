import json
from copy import deepcopy
from dataclasses import replace

import httpx
import pytest

from app.errors import DomainError
from app.portal.assessment import verify_report
from app.portal.settings import PortalSettings
from app.settings import ROOT
from app.workflow_client import WorkflowClient
from workflows.build_portal import build_portal


def test_upload_and_workflow_share_user_sse_does_not_forward_raw_data(tmp_path):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"synthetic-image-bytes")
    called = []
    def handle(request):
        called.append(request.url.path)
        if request.url.path.endswith("files/upload"):
            assert b"local-job_1" in request.content
            return httpx.Response(201, json={"id": "upload_1"})
        data = json.loads(request.content)
        assert data["user"] == "local-job_1" and data["inputs"]["images"][0]["upload_file_id"] == "upload_1"
        events = [{"event": "workflow_started", "workflow_run_id": "run_1", "task_id": "task_1",
                   "data": {"id": "run_1", "workflow_id": "workflow_1", "inputs": {"secret": "must-not-forward"}}},
                  {"event": "node_finished", "data": {"outputs": {"private_model_text": "not-a-report"}}},
                  {"event": "workflow_finished", "workflow_run_id": "run_1", "data": {"id": "run_1", "status": "succeeded", "outputs": {"report_id": "rpt_"+"a"*32}}}]
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text="".join("data: "+json.dumps(event)+"\n\n" for event in events))
    started = []
    with WorkflowClient("https://dify.invalid/v1", "synthetic", httpx.MockTransport(handle)) as client:
        file = client.upload(path, "image/jpeg", "local-job_1")
        result = client.run({"images": [file], "snapshot_id": "version1"}, "local-job_1", started.append)
    assert result["status"] == "succeeded" and len(called) == 2
    assert started[0] == {"run_id": "run_1", "task_id": "task_1", "workflow_id": "workflow_1"}
    assert "must-not-forward" not in json.dumps(started)


def test_disconnected_stream_persists_run_identity_and_reconcile_is_read_only():
    methods = []
    def handle(request):
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text='data: {"event":"workflow_started","workflow_run_id":"run1","data":{"id":"run1"}}\n\n')
        return httpx.Response(200, json={"id": "run1", "status": "succeeded", "outputs": {"report_id": "rpt_"+"a"*32}})
    ids = []
    with WorkflowClient("https://dify.invalid/v1", "synthetic", httpx.MockTransport(handle)) as client:
        with pytest.raises(DomainError, match="未收到完成事件"):
            client.run({}, "local-job", ids.append)
        assert ids[0]["run_id"] == "run1"
        assert client.reconcile(ids[0]["run_id"], lambda: None)["status"] == "succeeded"
    assert methods == ["POST", "GET"]


@pytest.mark.parametrize("change", ["snapshot", "run", "image", "status", "context"])
def test_foreign_or_unvalidated_report_is_rejected(change):
    payload = {"snapshot_id": "v1", "inputs": {"work_context": "未知"}}
    report = {"snapshot_id": "v1", "validation_passed": True, "review_status": "pending_review", "markdown": "saved-report",
        "request": {"request_id": "run1", "work_context": "未知", "image_manifest": [{"file_ref": "upload1"}]}}
    if change == "snapshot":
        report["snapshot_id"] = "v2"
    elif change == "run":
        report["request"]["request_id"] = "run2"
    elif change == "image":
        report["request"]["image_manifest"][0]["file_ref"] = "foreign"
    elif change == "status":
        report["validation_passed"] = False
    else:
        report["request"]["work_context"] = "foreign"
    with pytest.raises(DomainError):
        verify_report(report, payload, "run1", [{"upload_file_id": "upload1"}])


def test_portal_dsl_pins_metadata_filter_and_keeps_v3_evidence_gates(tmp_path):
    config = PortalSettings(data_root=tmp_path, dataset_id="dedicated", evidence_public_url="https://evidence.invalid", evidence_api_token="must-not-export")
    checklist = json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))
    value = build_portal(config, checklist)
    graph = {node["id"]: node["data"] for node in value["workflow"]["graph"]["nodes"]}
    assert graph["retrieval"]["metadata_filtering_mode"] == "manual"
    assert graph["retrieval"]["metadata_filtering_conditions"]["conditions"][0]["value"] == "{{#start.snapshot_id#}}"
    assert next(v for v in graph["validate_input"]["variables"] if v["variable"] == "snapshot_id")["value_selector"] == ["start", "snapshot_id"]
    assert graph["end"]["outputs"][0]["value_selector"] == ["unpack_report", "report_id"]
    assert "must-not-export" not in json.dumps(value)


def test_delivered_portal_template_matches_generator():
    config = PortalSettings(dataset_id="REPLACE_WITH_DEDICATED_DATASET_ID",
                            evidence_public_url="https://REPLACE_WITH_EVIDENCE_HOST")
    checklist = json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))
    actual = json.loads((ROOT / "workflows/portal.template.yml").read_text(encoding="utf-8"))
    assert actual == build_portal(config, checklist)
