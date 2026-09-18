"""依据 Dify 1.17.1 / DSL 0.7.0 结构生成待导入验证的候选文件。

输出使用 JSON（YAML 1.2 子集），不增加 YAML 运行时依赖。
此工具不调用 Dify，不读取或写入任何服务密钥，不声称候选已经验收。
"""
import argparse
import inspect
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.settings import ROOT, Settings
from workflows import nodes as steps
from workflows.schemas import AssessmentDraft, VisionResult


def ref(node, variable):
    return "{{#" + node + "." + variable + "#}}"


def code_text(function):
    source = Path(steps.__file__).read_text(encoding="utf-8")
    parameters = ", ".join(inspect.signature(getattr(steps, function)).parameters)
    return source + f"\n\ndef main({parameters}):\n    return {function}({parameters})\n"


def variable(name, value, secret=False):
    return {"id": str(uuid5(NAMESPACE_URL, "mechanical-safety-rag/" + name)), "name": name,
            "description": "由管理员绑定；不接受用户或模型覆盖", "selector": ["env", name],
            "value_type": "secret" if secret else "string", "value": "" if secret else value}


def input_field(name, label, kind="text-input", required=True, **options):
    return {"variable": name, "label": label, "type": kind, "required": required, "options": [], **options}


def build_candidate(settings, checklist, model_provider, model_name, evidence_url, mode="vision"):
    if mode not in {"vision", "fixed"}:
        raise ValueError("候选模式只允许vision或fixed")
    if not settings.dataset_id or not settings.active_snapshot_id:
        raise ValueError("先完成并激活阶段C知识快照")
    graph_nodes, edges = [], []
    environment = [variable("EVIDENCE_API_BASE_URL", evidence_url.rstrip("/")),
        variable("EVIDENCE_API_TOKEN", "", True), variable("SNAPSHOT_ID", settings.active_snapshot_id),
        variable("DATASET_ID", settings.dataset_id), variable("CHECKLIST_JSON", json.dumps(checklist, ensure_ascii=False)),
        variable("WORKFLOW_VERSION", "stage-d-v1-untested"), variable("MODEL_ID", model_name)]

    def add(node_id, node_type, title, extra=None, parent=None):
        number = len(graph_nodes)
        position = {"x": 80 + number * 310, "y": 220}
        node = {"id": node_id, "type": "custom", "position": position, "positionAbsolute": dict(position),
                "sourcePosition": "right", "targetPosition": "left", "width": 244, "height": 100,
                "data": {"type": node_type, "title": title, "desc": "阶段D候选；实际运行验收前不发布", "selected": False, **(extra or {})}}
        if node_type == "iteration":
            node.update(width=extra["width"], height=extra["height"])
        if parent:
            node.update(parentId=parent, zIndex=1002)
            node["data"].update(isInIteration=True, iteration_id=parent)
            child_index = sum(item.get("parentId") == parent for item in graph_nodes)
            node["position"] = {"x": 40 + child_index * 280, "y": 90}
            parent_position = next(item["position"] for item in graph_nodes if item["id"] == parent)
            node["positionAbsolute"] = {key: parent_position[key] + node["position"][key] for key in ("x", "y")}
        graph_nodes.append(node)
        return node

    def connect(source, target, parent=None):
        by_id = {item["id"]: item for item in graph_nodes}
        data = {"sourceType": by_id[source]["data"]["type"], "targetType": by_id[target]["data"]["type"],
                "isInIteration": bool(parent), "isInLoop": False}
        if parent:
            data["iteration_id"] = parent
        edges.append({"id": source + "-source-" + target + "-target", "source": source, "sourceHandle": "source",
                      "target": target, "targetHandle": "target", "type": "custom", "data": data, "zIndex": 1002 if parent else 0})

    def code(node_id, title, function, inputs, outputs, parent=None, source=None):
        return add(node_id, "code", title, {"code_language": "python3", "code": source or code_text(function),
            "variables": [{"variable": key, "value_selector": list(selector)} for key, selector in inputs.items()],
            "outputs": {key: {"type": kind, "children": None} for key, kind in outputs.items()},
            "retry_config": {"retry_enabled": False, "max_retries": 0, "retry_interval": 1000}}, parent)

    def http(node_id, title, suffix, body_node=None):
        add(node_id, "http-request", title, {"method": "POST" if body_node else "GET",
            "url": ref("env", "EVIDENCE_API_BASE_URL") + suffix,
            "authorization": {"type": "api-key", "config": {"type": "bearer", "api_key": ref("env", "EVIDENCE_API_TOKEN")}} if body_node else {"type": "no-auth"},
            "headers": "Content-Type:application/json" if body_node else "", "params": "",
            "body": {"type": "json", "data": [{"type": "text", "key": "", "value": ref(body_node, "body")}]} if body_node else {"type": "none", "data": []},
            "timeout": {"connect": 10, "read": 30, "write": 30},
            "retry_config": {"retry_enabled": False, "max_retries": 0, "retry_interval": 1000}})

    def llm(node_id, title, prompt_file, schema, user_prompt):
        add(node_id, "llm", title, {"model": {"provider": model_provider, "name": model_name, "mode": "chat", "completion_params": {"temperature": 0.1}},
            "prompt_template": [{"role": "system", "text": (ROOT / prompt_file).read_text(encoding="utf-8")},
                                {"role": "user", "text": user_prompt}],
            "context": {"enabled": False, "variable_selector": []},
            "vision": {"enabled": True, "configs": {"variable_selector": ["start", "images"], "detail": "high"}},
            "structured_output_enabled": True, "structured_output": {"schema": schema.model_json_schema()},
            "retry_config": {"retry_enabled": False, "max_retries": 0, "retry_interval": 1000}})

    selected_type = checklist.get("equipment_type") or "待业务确认的设备类别"
    fields = [input_field("images", "同一设备的图片（1～4张）", "file-list", max_length=4,
                         allowed_file_types=["image"], allowed_file_extensions=[".jpg", ".jpeg", ".png"], allowed_file_upload_methods=["local_file"]),
              input_field("equipment_type", "设备类别", "select", options=[selected_type], default=selected_type),
              input_field("equipment_description", "设备用途与结构说明", "paragraph", False, max_length=4000, default=""),
              input_field("operating_state", "运行状态", "select", options=["运行", "停机", "检修", "未知"], default="未知"),
              input_field("work_context", "人员接近与作业背景", "paragraph", max_length=4000, default="未知"),
              input_field("same_equipment_confirmed", "确认全部图片属于同一台设备", "checkbox", default=False)]
    add("start", "start", "用户输入" if mode == "vision" else "固定观察联通测试", {"variables": fields if mode == "vision" else []})
    http("health", "检查证据服务", "/health")
    connect("start", "health")
    health_code = ('import json\ndef main(status_code, body):\n'
        '    data = json.loads(body)\n'
        '    if status_code != 200 or data.get("status") != "ok":\n'
        '        raise ValueError("证据服务未就绪，禁止继续")\n'
        '    return {"ready": True}\n')
    code("health_gate", "确认服务就绪", None, {"status_code": ("health", "status_code"), "body": ("health", "body")}, {"ready": "boolean"}, source=health_code)
    connect("health", "health_gate")
    if mode == "vision":
        inputs = {name: ("start", name) for name in ("images", "equipment_type", "equipment_description", "operating_state", "work_context", "same_equipment_confirmed")}
        inputs.update({"workflow_run_id": ("sys", "workflow_run_id"), "checklist_json": ("env", "CHECKLIST_JSON"),
                       "snapshot_id": ("env", "SNAPSHOT_ID"), "dataset_id": ("env", "DATASET_ID"),
                       "workflow_version": ("env", "WORKFLOW_VERSION"), "model_id": ("env", "MODEL_ID")})
        code("validate_input", "校验图片与设备范围", "validate_input", inputs,
             {key: "string" for key in ("request_json", "image_manifest_json", "equipment_context_json", "checklist_json")})
        connect("health_gate", "validate_input")
        llm("vision", "记录可见事实", "prompts/vision_observation.md", VisionResult,
            "按附件顺序对应图片标识：" + ref("validate_input", "image_manifest_json") + "\n设备与工况：" + ref("validate_input", "equipment_context_json") +
            "\n固定检查清单：" + ref("validate_input", "checklist_json"))
        connect("validate_input", "vision")
        code("checks", "整理全部检查项", "build_checks", {"vision_json": ("vision", "structured_output"),
            "request_json": ("validate_input", "request_json"), "checklist_json": ("env", "CHECKLIST_JSON")},
            {"request_json": "string", "observations_json": "string", "checks": "array[string]", "checks_json": "string"})
        connect("vision", "checks")
    else:
        fixed = {"equipment_id": "fixed_observation_software_smoke", "image_manifest": [{"image_id": "image_001", "position": 1, "file_ref": "fixed-observation-no-real-photo"}],
                 "observations": [{"observation_id": "obs_001", "image_ids": ["image_001"], "visible_fact": "【软件联通用固定观察，非实拍评估】防护罩局部可见", "unknowns": ["未使用真实照片，不作设备判断"]}],
                 "checks": [{"check_id": "fixed_guard_check", "observation_ids": ["obs_001"], "query": "防护装置暴露锐边和尖角有什么要求？"}],
                 "workflow_version": "stage-d-fixed-smoke-v1", "model_id": "fixed-response-no-model"}
        fixed_code = ("import json\ndef main(workflow_run_id, snapshot_id):\n    request = " + repr(fixed) +
            '\n    request.update(request_id=workflow_run_id, snapshot_id=snapshot_id)\n    return {"request_json": json.dumps(request,ensure_ascii=False), "checks": [json.dumps(item,ensure_ascii=False) for item in request["checks"]]}\n')
        code("checks", "固定观察（非实拍评估）", None, {"workflow_run_id": ("sys", "workflow_run_id"), "snapshot_id": ("env", "SNAPSHOT_ID")},
             {"request_json": "string", "checks": "array[string]"}, source=fixed_code)
        connect("health_gate", "checks")

    add("iteration", "iteration", "逐项串行检索", {"iterator_selector": ["checks", "checks"], "iterator_input_type": "array[string]",
        "output_selector": ["adapt_hits", "check_result_json"], "output_type": "array[string]", "start_node_id": "iteration_start",
        "is_parallel": False, "parallel_nums": 1, "error_handle_mode": "terminated", "flatten_output": False, "height": 240, "width": 1200})
    connect("checks", "iteration")
    start = add("iteration_start", "iteration-start", "", parent="iteration")
    start.update(type="custom-iteration-start", draggable=False, selectable=False, width=44, height=48)
    code("query", "读取当前检索问题", "iteration_query", {"check_json": ("iteration", "item")}, {"query": "string"}, parent="iteration")
    connect("iteration_start", "query", "iteration")
    add("retrieval", "knowledge-retrieval", "试点知识库检索", {"dataset_ids": [settings.dataset_id],
        "query_variable_selector": ["query", "query"], "retrieval_mode": "multiple", "metadata_filtering_mode": "disabled",
        "multiple_retrieval_config": {"top_k": 5, "score_threshold": None, "reranking_mode": "weighted_score", "reranking_enable": True,
            "weights": {"weight_type": "customized", "vector_setting": {"vector_weight": 0.5,
                "embedding_provider_name": "langgenius/siliconflow/siliconflow", "embedding_model_name": "Qwen/Qwen3-Embedding-4B"},
                "keyword_setting": {"keyword_weight": 0.5}}}}, parent="iteration")
    connect("query", "retrieval", "iteration")
    code("adapt_hits", "保留真实命中标识", "adapt_retrieval", {"check_json": ("iteration", "item"),
        "result": ("retrieval", "result"), "dataset_id": ("env", "DATASET_ID")}, {"check_result_json": "string"}, parent="iteration")
    connect("retrieval", "adapt_hits", "iteration")
    code("prepare_body", "汇总检索并固定关联", "prepare_payload", {"request_json": ("checks", "request_json"), "retrieval_results": ("iteration", "output")}, {"body": "string"})
    connect("iteration", "prepare_body")
    http("prepare_http", "保存完整证据", "/evidence/prepare", "prepare_body")
    connect("prepare_body", "prepare_http")
    code("unpack_evidence", "检查证据服务响应", "unpack_evidence", {"status_code": ("prepare_http", "status_code"),
        "body": ("prepare_http", "body"), "request_json": ("prepare_body", "body")},
        {"context_id": "string", "evidence_json": "string", "context_json": "string"})
    connect("prepare_http", "unpack_evidence")
    if mode == "vision":
        llm("assessment", "生成待复核评估", "prompts/risk_assessment.md", AssessmentDraft,
            "设备与工况：" + ref("validate_input", "equipment_context_json") + "\n图片对应清单：" + ref("validate_input", "image_manifest_json") +
            "\n观察：" + ref("checks", "observations_json") + "\n全部检查项：" + ref("checks", "checks_json") + "\n本次允许证据：" + ref("unpack_evidence", "evidence_json"))
        connect("unpack_evidence", "assessment")
        assessment_selector = ("assessment", "structured_output")
    else:
        fixed_assessment = ('import json\ndef main(context_json):\n    context=json.loads(context_json)\n    findings=[]\n'
            '    for item in context["checks"]:\n        findings.append({"check_id":item["check_id"],"observation_ids":["obs_001"],'
            '"status":"needs_confirmation" if item["allowed_evidence_ids"] else "insufficient_evidence",'
            '"risk_description":"【软件联通测试】非真实设备风险判断", "applicability_reason":"需真实图片与现场条件",'
            '"evidence_ids":item["allowed_evidence_ids"], "recommendation":"待真实材料和专业人员复核",'
            '"verification_required":["未使用真实图片或模型判断"]})\n'
            '    return {"assessment_json":json.dumps({"findings":findings},ensure_ascii=False)}\n')
        code("assessment", "固定测试结果（非模型判断）", None, {"context_json": ("unpack_evidence", "context_json")}, {"assessment_json": "string"}, source=fixed_assessment)
        connect("unpack_evidence", "assessment")
        assessment_selector = ("assessment", "assessment_json")
    code("finalize_body", "绑定上下文与草稿", "finalize_payload", {"context_json": ("unpack_evidence", "context_json"), "assessment_json": assessment_selector}, {"body": "string"})
    connect("assessment", "finalize_body")
    http("finalize_http", "校验并保存报告", "/reports/finalize", "finalize_body")
    connect("finalize_body", "finalize_http")
    code("unpack_report", "只输出服务端报告", "unpack_report", {"status_code": ("finalize_http", "status_code"),
        "body": ("finalize_http", "body"), "context_id": ("unpack_evidence", "context_id")},
        {"report_id": "string", "markdown": "string", "validation_json": "string"})
    connect("finalize_http", "unpack_report")
    add("end", "end", "待专业人员复核", {"outputs": [{"variable": key, "value_type": "string", "value_selector": ["unpack_report", key]}
                                                        for key in ("report_id", "markdown", "validation_json")]})
    connect("unpack_report", "end")
    return {"version": "0.7.0", "kind": "app", "dependencies": [],
        "app": {"name": "机械设备安全评估（阶段D）", "mode": "workflow", "description": "阶段D候选：" + mode + "；untested，未通过真实验收前不发布", "icon": "⚙️", "icon_background": "#E4FBCC", "use_icon_as_answer_icon": False},
        "workflow": {"environment_variables": environment, "conversation_variables": [],
            "features": {"file_upload": {"enabled": False, "allowed_file_types": ["image"], "allowed_file_extensions": [".jpg", ".jpeg", ".png"],
                "allowed_file_upload_methods": ["local_file"], "number_limits": 4, "fileUploadConfig": {"image_file_size_limit": 5}}},
            "graph": {"nodes": graph_nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.5}}}}


def main():
    parser = argparse.ArgumentParser(description="生成待实际导入验证的Dify候选DSL，不含服务密钥")
    parser.add_argument("--mode", choices=["fixed", "vision"], default="vision")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-provider", default="langgenius/siliconflow/siliconflow")
    parser.add_argument("--model", default="Qwen/Qwen2.5-VL-32B-Instruct")
    parser.add_argument("--evidence-url", default="http://evidence-api:8000")
    args = parser.parse_args()
    if args.output.name == "safety-assessment.yml":
        parser.error("此工具仅生成候选；最终safety-assessment.yml须在实际导入和运行验收后交付")
    settings = Settings.from_env()
    checklist = json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))
    candidate = build_candidate(settings, checklist, args.model_provider, args.model, args.evidence_url, args.mode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(args.output), "status": "untested", "mode": args.mode, "nodes": len(candidate["workflow"]["graph"]["nodes"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
