"""生成无密钥的独立测试台 Workflow，复用阶段 D v3 节点和提示词。"""
import argparse
import json
from dataclasses import replace

from app.portal.settings import PortalSettings
from app.settings import ROOT
from workflows.build_candidate import build_candidate, input_field, ref


def build_portal(config, checklist, provider="langgenius/siliconflow/siliconflow", model="Qwen/Qwen3.5-27B",
                 embedding_provider="langgenius/siliconflow/siliconflow", embedding_model="Qwen/Qwen3-Embedding-4B"):
    settings = replace(config.evidence_settings(), active_snapshot_id="from_portal_backend")
    candidate = build_candidate(settings, checklist, provider, model, config.evidence_public_url)
    candidate["app"].update(name="机械设备安全评估（本地测试台）", description="本机开发者测试台专用；API 发布后关闭公开 Web App")
    workflow = candidate["workflow"]
    workflow["environment_variables"] = [v for v in workflow["environment_variables"] if v["name"] != "SNAPSHOT_ID"]
    for value in workflow["environment_variables"]:
        if value["name"] == "WORKFLOW_VERSION":
            value["value"] = "portal-v1"
    nodes = {node["id"]: node["data"] for node in workflow["graph"]["nodes"]}
    nodes["start"]["variables"].append(input_field("snapshot_id", "后端固定的已发布知识版本", max_length=160))
    for var in nodes["validate_input"]["variables"]:
        if var["variable"] == "snapshot_id":
            var["value_selector"] = ["start", "snapshot_id"]
    nodes["retrieval"].update(metadata_filtering_mode="manual", metadata_filtering_conditions={
        "logical_operator": "and", "conditions": [{"name": "rag_snapshot_id", "comparison_operator": "is", "value": ref("start", "snapshot_id")}]})
    vector = nodes["retrieval"]["multiple_retrieval_config"]["weights"]["vector_setting"]
    vector.update(embedding_provider_name=embedding_provider, embedding_model_name=embedding_model)
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
