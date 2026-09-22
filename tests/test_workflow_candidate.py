import json
from pathlib import Path

import pytest

from conftest import draft_for
from workflows.build_candidate import build_candidate, code_text

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("model", ["Qwen/Qwen3.5-27B", "Qwen/Qwen3.6-27B"])
def test_current_siliconflow_vision_model_contract(settings, model):
    checklist = json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))
    document = build_candidate(settings, checklist, "langgenius/siliconflow/siliconflow", model, "https://example.test")
    llms = [node["data"] for node in document["workflow"]["graph"]["nodes"] if node["data"]["type"] == "llm"]
    assert len(llms) == 2
    for node in llms:
        params = node["model"]["completion_params"]
        assert params["enable_thinking"] is False
        assert params["response_format"] == "json_schema"
        native = json.loads(params["json_schema"])
        assert native["strict"] is True
        assert native["schema"] == node["structured_output"]["schema"]
        assert native["name"] in {"mechanical_safety_vision", "mechanical_safety_assessment"}
    assert all(node["vision"]["configs"]["variable_selector"] == ["start", "images"] for node in llms)
    assert all(node["structured_output_enabled"] for node in llms)


def test_delivered_dsl_keeps_current_gates_and_server_report_path():
    document = json.loads((ROOT / "workflows/safety-assessment.yml").read_text(encoding="utf-8"))
    graph = document["workflow"]["graph"]
    nodes = {node["id"]: node["data"] for node in graph["nodes"]}
    for node_id, function in {"validate_input": "validate_input", "checks": "build_checks",
                              "finalize_body": "finalize_payload", "unpack_report": "unpack_report"}.items():
        assert nodes[node_id]["code"] == code_text(function)
    assert nodes["assessment"]["prompt_template"][0]["text"] == (ROOT / "prompts/risk_assessment.md").read_text(encoding="utf-8")
    for target, source in {"end": "unpack_report", "unpack_report": "finalize_http", "finalize_http": "finalize_body"}.items():
        assert [edge["source"] for edge in graph["edges"] if edge["target"] == target] == [source]
    environment = {item["name"]: item["value"] for item in document["workflow"]["environment_variables"]}
    assert environment["EVIDENCE_API_TOKEN"] == ""
    assert environment["EVIDENCE_API_BASE_URL"] == "https://REPLACE_EVIDENCE_HOST.invalid"
    assert environment["SNAPSHOT_ID"] == "REPLACE_SNAPSHOT_ID"
    assert environment["DATASET_ID"] == "REPLACE_DATASET_ID"
    assert nodes["retrieval"]["dataset_ids"] == [environment["DATASET_ID"]]
    assert ".trycloudflare.com" not in json.dumps(document)
    assert json.loads(environment["CHECKLIST_JSON"]) == json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))
    assert nodes["vision"]["vision"]["configs"]["variable_selector"] == nodes["assessment"]["vision"]["configs"]["variable_selector"] == ["start", "images"]


@pytest.mark.parametrize("mode", ["fixed", "vision"])
def test_candidate_code_and_bindings_execute_to_saved_report(client, settings, mode):
    checklist = json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))
    checklist.update(equipment_type="合成测试设备", review_status="approved", reviewed_by="synthetic", reviewed_at="2026-09-18")
    document = build_candidate(settings, checklist, "synthetic-provider", "synthetic-vision", "http://evidence-api:8000", mode)
    fixture = json.loads((ROOT / "fixtures/workflow_input.synthetic.json").read_text(encoding="utf-8"))
    graph = document["workflow"]["graph"]
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert len(nodes) == len(graph["nodes"])
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in graph["edges"])
    environment = {item["name"]: item["value"] for item in document["workflow"]["environment_variables"]}
    assert environment["EVIDENCE_API_TOKEN"] == ""
    state = {"env": environment, "sys": {"workflow_run_id": "candidate_test_001"}, "start": {
        "images": fixture["images"], "equipment_type": checklist["equipment_type"], "equipment_description": "合成测试",
        "operating_state": "未知", "work_context": "合成场景", "same_equipment_confirmed": True}}

    def run_code(node_id):
        data = nodes[node_id]["data"]
        arguments = {item["variable"]: state[item["value_selector"][0]][item["value_selector"][1]] for item in data["variables"]}
        namespace = {}
        exec(compile(data["code"], node_id, "exec"), namespace)
        result = namespace["main"](**arguments)
        assert set(result) == set(data["outputs"])
        state[node_id] = result
        return result

    health = client.get("/health")
    state["health"] = {"status_code": health.status_code, "body": health.text}
    run_code("health_gate")
    if mode == "vision":
        run_code("validate_input")
        state["vision"] = {"structured_output": fixture["vision"]}
        assert nodes["vision"]["data"]["vision"]["configs"]["variable_selector"] == ["start", "images"]
        assert nodes["assessment"]["data"]["vision"] == nodes["vision"]["data"]["vision"]
    run_code("checks")
    outputs = []
    for value in state["checks"]["checks"]:
        state["iteration"] = {"item": value}
        run_code("query")
        state["retrieval"] = {"result": [{"metadata": {"dataset_id": settings.dataset_id,
            "document_id": "demo_document", "segment_id": "demo_segment_1", "score": 0.8}}]}
        outputs.append(run_code("adapt_hits")["check_result_json"])
    state["iteration"]["output"] = outputs
    assert nodes["iteration"]["data"]["is_parallel"] is False
    assert nodes["iteration"]["data"]["error_handle_mode"] == "terminated"
    run_code("prepare_body")
    prepared = client.post("/evidence/prepare", json=json.loads(state["prepare_body"]["body"]))
    assert prepared.status_code == 200, prepared.text
    state["prepare_http"] = {"status_code": prepared.status_code, "body": prepared.text}
    run_code("unpack_evidence")
    if mode == "vision":
        state["assessment"] = {"structured_output": {"findings": draft_for(prepared.json())["findings"]}}
    else:
        run_code("assessment")
    run_code("finalize_body")
    finalized = client.post("/reports/finalize", json=json.loads(state["finalize_body"]["body"]))
    assert finalized.status_code == 200, finalized.text
    state["finalize_http"] = {"status_code": finalized.status_code, "body": finalized.text}
    output = run_code("unpack_report")
    assert output["markdown"] == client.get("/reports/" + output["report_id"]).json()["markdown"]
    assert all(item["value_selector"][0] == "unpack_report" for item in nodes["end"]["data"]["outputs"])
    assert "untested" in document["app"]["description"]
