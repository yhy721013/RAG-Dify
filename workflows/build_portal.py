"""生成无密钥的独立测试台 Workflow，复用阶段 D v3 节点和提示词。"""
import argparse
import json
from dataclasses import replace

from app.portal.settings import PortalSettings
from app.settings import ROOT
from workflows.schemas import DynamicVisionResult, dynamic_assessment_schema, generation_schema
from workflows.build_candidate import build_candidate, input_field, ref, code_text


def build_portal(config, checklist, provider="langgenius/siliconflow/siliconflow", model="Qwen/Qwen3.5-27B",
                 embedding_provider="langgenius/siliconflow/siliconflow", embedding_model="Qwen/Qwen3-Embedding-4B"):
    settings = replace(config.evidence_settings(), active_snapshot_id="from_portal_backend")
    candidate = build_candidate(settings, checklist, provider, model, config.evidence_public_url)
    candidate["app"].update(name="机械设备安全评估（本地测试台）", description="本机开发者测试台专用；API 发布后关闭公开 Web App")
    # Dependency pinned from the user's 2026-09-28 Dify export; no instance data.
    if "langgenius/openai_api_compatible/openai_api_compatible" in (provider, embedding_provider):
        candidate["dependencies"] = [{"current_identifier": None, "type": "marketplace", "value": {
            "marketplace_plugin_unique_identifier": "langgenius/openai_api_compatible:0.0.68@ba61c5eccb814be7364117c0bec3710a51e09b20f31e37243e747a00f9377969",
            "version": None}}]
    workflow = candidate["workflow"]
    workflow["environment_variables"] = [v for v in workflow["environment_variables"] if v["name"] != "SNAPSHOT_ID"]
    for value in workflow["environment_variables"]:
        if value["name"] == "WORKFLOW_VERSION":
            value["value"] = "portal-v3-dynamic"
    nodes = {node["id"]: node["data"] for node in workflow["graph"]["nodes"]}
    nodes["start"]["variables"].append(input_field("snapshot_id", "后端固定的已发布知识版本", max_length=160))
    for var in nodes["validate_input"]["variables"]:
        if var["variable"] == "snapshot_id":
            var["value_selector"] = ["start", "snapshot_id"]
    nodes["retrieval"].update(metadata_filtering_mode="manual", metadata_filtering_conditions={
        "logical_operator": "and", "conditions": [{"name": "rag_snapshot_id", "comparison_operator": "is", "value": ref("start", "snapshot_id")}]})
    vector = nodes["retrieval"]["multiple_retrieval_config"]["weights"]["vector_setting"]
    vector.update(embedding_provider_name=embedding_provider, embedding_model_name=embedding_model)
    # Portal-specific dynamic vision/query contract; legacy build_candidate stays compatible.
    workflow["environment_variables"] = [v for v in workflow["environment_variables"] if v["name"] != "CHECKLIST_JSON"]
    fields = nodes["start"]["variables"]
    for index, field in enumerate(fields):
        if field["variable"] == "equipment_type":
            fields[index] = input_field("equipment_type", "设备类别（用户提供）", max_length=100)
    fields.append(input_field("user_question", "希望核查的问题", "paragraph", max_length=4000))
    inputs = nodes["validate_input"]
    inputs["code"] = code_text("validate_dynamic_input")
    inputs["variables"] = [v for v in inputs["variables"] if v["variable"] != "checklist_json"]
    inputs["variables"].append({"variable": "user_question", "value_selector": ["start", "user_question"]})
    inputs["outputs"].pop("checklist_json", None)
    vision = nodes["vision"]
    vision["title"] = "图片事实与动态检索计划"
    vision["structured_output"] = {"schema": generation_schema(DynamicVisionResult.model_json_schema())}
    vision["prompt_template"] = [
        {"role": "system", "text": (ROOT / "prompts/dynamic_vision.md").read_text(encoding="utf-8")},
        {"role": "user", "text": "设备、工况与用户问题：" + ref("validate_input", "equipment_context_json") +
         "\n本次图片清单：" + ref("validate_input", "image_manifest_json")}]
    checks = nodes["checks"]
    checks["title"] = "校验动态计划与图片关联"
    checks["code"] = code_text("build_dynamic_checks")
    checks["variables"] = [v for v in checks["variables"] if v["variable"] != "checklist_json"]
    nodes["assessment"]["structured_output"] = {"schema": dynamic_assessment_schema()}
    nodes["assessment"]["prompt_template"][0]["text"] = (ROOT / "prompts/dynamic_assessment.md").read_text(encoding="utf-8")
    nodes["retrieval"]["title"] = "按图片事实与问题检索标准"
    # Update any provider-native JSON schema too; otherwise it would retain legacy enums.
    for name in ("vision", "assessment"):
        params = nodes[name]["model"]["completion_params"]
        if params.get("response_format") == "json_schema":
            params["json_schema"] = json.dumps({"name": "dynamic_" + name, "strict": True,
                "schema": nodes[name]["structured_output"]["schema"]}, ensure_ascii=False)
    for node in nodes.values():
        node["desc"] = "本地测试台专用；保持证据校验与报告保存链路"
    return candidate


def main():
    parser = argparse.ArgumentParser(description="生成不含密钥的门户 Workflow 模板")
    parser.add_argument("--output", default="data/portal/workflows/portal.candidate.yml")
    parser.add_argument("--model-provider")
    parser.add_argument("--model")
    parser.add_argument("--embedding-provider")
    parser.add_argument("--embedding-model")
    args = parser.parse_args()
    from pathlib import Path
    config = PortalSettings.from_env()
    if not config.dataset_id or not config.evidence_public_url:
        parser.error("请先填写 .env.portal 中专用知识库 ID 和证据服务 HTTPS 地址")
    value = build_portal(config, json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8")),
                         args.model_provider or config.vision_provider, args.model or config.vision_model,
                         args.embedding_provider or config.embedding_provider, args.embedding_model or config.embedding_model)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(path), "status": "requires_live_import_and_validation", "secrets_included": False}))


if __name__ == "__main__":
    main()
