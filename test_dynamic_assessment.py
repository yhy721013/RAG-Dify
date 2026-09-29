"""Synthetic dynamic workflow tests; no cloud calls or real-standard claims."""
import json
from copy import deepcopy

import pytest

from app.portal.diagnostics import input_contract
from app.portal.settings import PortalSettings
from app.settings import ROOT
from workflows import nodes
from workflows.build_portal import build_portal
from workflows.schemas import DynamicVisionResult
from conftest import draft_for


def initial(question="这个急停按钮周围结构是否妨碍操作？"):
    files = json.loads((ROOT / "fixtures/workflow_input.synthetic.json").read_text(encoding="utf-8"))["images"]
    return nodes.validate_dynamic_input(files, "剪板机", "用户提供的设备类别，局部按钮图", "未知", "合成测试",
        True, "dynamic_run", "demo_snapshot", "demo_dataset", "portal-v3-dynamic", "synthetic", question)


def vision(query="急停按钮周围的保护结构对操作和触及有哪些要求？"):
    return {"scope_status": "same_equipment", "scope_reason": "合成测试，单台设备部件图片",
        "observations": [{"image_ids": ["image_001"], "part": "按钮周边", "visible_fact": "合成图中按钮周围存在环绕结构。",
                          "unknowns": ["不能从图片确认按钮实际功能"]}],
        "checks": [{"observation_indices": [1], "query": query}]}


def test_questions_change_retrieval_without_fixed_checks():
    first = nodes.build_dynamic_checks(vision(), initial()["request_json"])
    second = nodes.build_dynamic_checks(vision("急停按钮的致动机构与背景颜色应满足哪些条件？"),
                                        initial("按钮颜色有什么要求？")["request_json"])
    assert len(first["checks"]) == len(second["checks"]) == 1
    assert nodes.iteration_query(first["checks"][0]) != nodes.iteration_query(second["checks"][0])
    request = json.loads(first["request_json"])
    assert request["equipment_type"] == "剪板机" and request["user_question"]
    assert len(request["observations"]) == 1  # No invented missing observations.
    assert "guard_" not in first["checks_json"]


@pytest.mark.parametrize("bad", ["image", "index", "bool_index", "short", "duplicate", "extra", "scope"])
def test_invalid_model_plans_are_rejected(bad):
    value = vision()
    if bad == "image": value["observations"][0]["image_ids"] = ["image_004"]
    if bad == "index": value["checks"][0]["observation_indices"] = [2]
    if bad == "bool_index": value["checks"][0]["observation_indices"] = [True]
    if bad == "short": value["observations"][0]["visible_fact"] = "急"
    if bad == "duplicate": value["checks"].append(deepcopy(value["checks"][0]))
    if bad == "extra": value["checks"][0]["dataset_id"] = "foreign"
    if bad == "scope": value["scope_status"] = "different_equipment"
    with pytest.raises(ValueError): nodes.build_dynamic_checks(value, initial()["request_json"])


def test_new_contract_rejects_legacy_published_workflow():
    old = json.loads((ROOT / "fixtures/dify_portal/workflow_parameters.real.json").read_text(encoding="utf-8"))
    errors, _ = input_contract(old, "", dynamic=True)
    assert any("user_question" in e for e in errors)
    assert any("equipment_type" in e for e in errors)
    with pytest.raises(ValueError): initial(" ")


def test_generated_dynamic_workflow_executes_through_authoritative_report(client):
    config = PortalSettings(dataset_id="demo_dataset", evidence_public_url="https://evidence.invalid", evidence_api_token="never-export")
    checklist = json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))
    dsl = build_portal(config, checklist)
    graph = {n["id"]: n["data"] for n in dsl["workflow"]["graph"]["nodes"]}
    env = {v["name"]: v["value"] for v in dsl["workflow"]["environment_variables"]}
    assert "CHECKLIST_JSON" not in env and "never-export" not in json.dumps(dsl)
    forms = {"user_input_form": [{v["type"]: v} for v in graph["start"]["variables"]]}
    assert input_contract(forms, "", dynamic=True) == ([], [])
    assert graph["retrieval"]["metadata_filtering_conditions"]["conditions"][0]["value"] == "{{#start.snapshot_id#}}"
    for name in ("vision", "assessment"):
        assert graph[name]["vision"]["configs"]["variable_selector"] == ["start", "images"]
        native = json.loads(graph[name]["model"]["completion_params"]["json_schema"])
        assert native["schema"] == graph[name]["structured_output"]["schema"]
    files = json.loads((ROOT / "fixtures/workflow_input.synthetic.json").read_text(encoding="utf-8"))["images"]
    state = {"env": env, "sys": {"workflow_run_id": "dynamic_run"}, "start": {
        "images": files, "equipment_type": "剪板机", "equipment_description": "合成测试",
        "operating_state": "未知", "work_context": "合成测试", "same_equipment_confirmed": True,
        "snapshot_id": "demo_snapshot", "user_question": "按钮周围结构是否妨碍操作？"}}
    def run(name):
        node = graph[name]
        args = {v["variable"]: state[v["value_selector"][0]][v["value_selector"][1]] for v in node["variables"]}
        ns = {}
        exec(compile(node["code"], name, "exec"), ns)
        state[name] = ns["main"](**args)
        assert set(state[name]) == set(node["outputs"])
        return state[name]
    run("validate_input")
    DynamicVisionResult.model_validate(vision())
    state["vision"] = {"structured_output": vision()}
    run("checks")
    results = []
    for check in state["checks"]["checks"]:
        state["iteration"] = {"item": check}
        run("query")
        state["retrieval"] = {"result": [{"metadata": {"dataset_id": "demo_dataset", "document_id": "demo_document",
            "segment_id": "demo_segment_1", "score": 0.9}}]}
        results.append(run("adapt_hits")["check_result_json"])
    state["iteration"]["output"] = results
    payload = run("prepare_body")["body"]
    response = client.post("/evidence/prepare", json=json.loads(payload))
    assert response.status_code == 200, response.text
    state["prepare_http"] = {"status_code": response.status_code, "body": response.text}
    context = json.loads(run("unpack_evidence")["context_json"])
    state["assessment"] = {"structured_output": {"findings": draft_for(context)["findings"]}}
    body = json.loads(run("finalize_body")["body"])
    broken = deepcopy(body)
    broken["findings"][0]["risk_description"] = "急"
    rejected = client.post("/reports/finalize", json=broken)
    assert rejected.status_code == 422 and rejected.json()["error"]["code"] == "model_output_incomplete"
    with pytest.raises(ValueError, match="残缺"):
        nodes.finalize_payload(json.dumps(context), {"findings": broken["findings"]})
    response = client.post("/reports/finalize", json=body)
    assert response.status_code == 200, response.text
    state["finalize_http"] = {"status_code": response.status_code, "body": response.text}
    output = run("unpack_report")
    assert "对本次问题的回答" in output["markdown"] and "剪板机" in output["markdown"]
    assert r"DEMO\-STD\-001" in output["markdown"] and "PDF 第 1 页" in output["markdown"]
    assert "guard_hazards" not in output["markdown"]
    assert output["markdown"] == client.get("/reports/" + output["report_id"]).json()["markdown"]
