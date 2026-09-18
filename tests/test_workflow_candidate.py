import json
from pathlib import Path

import pytest

from conftest import draft_for
from workflows.build_candidate import build_candidate

ROOT = Path(__file__).resolve().parent.parent


def test_current_siliconflow_vision_model_contract(settings):
    checklist = json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))
    document = build_candidate(settings, checklist, "langgenius/siliconflow/siliconflow", "Qwen/Qwen3.5-27B", "https://example.test")
    llms = [node["data"] for node in document["workflow"]["graph"]["nodes"] if node["data"]["type"] == "llm"]
    assert len(llms) == 2
    assert all(node["model"]["completion_params"] == {"enable_thinking": False} for node in llms)
    assert all(node["vision"]["configs"]["variable_selector"] == ["start", "images"] for node in llms)
    assert all(node["structured_output_enabled"] for node in llms)


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
