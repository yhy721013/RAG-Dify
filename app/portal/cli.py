import argparse
import json
import secrets
from pathlib import Path

from app.portal.repository import PortalRepository
from app.portal.settings import PortalSettings
from app.repository import Repository
from app.settings import ROOT


def main():
    parser = argparse.ArgumentParser(description="本地测试台初始化和诊断")
    parser.add_argument("command", choices=["init", "doctor", "configure-empty-dataset"])
    parser.add_argument("--embedding-model", default="Qwen/Qwen3-Embedding-4B")
    parser.add_argument("--embedding-provider", default="langgenius/siliconflow/siliconflow")
    args = parser.parse_args()
    env = ROOT / ".env.portal"
    if args.command == "init" and not env.exists():
        template = (ROOT / "config/portal.env.example").read_text(encoding="utf-8")
        template = template.replace("PORTAL_EVIDENCE_API_TOKEN=\n", "PORTAL_EVIDENCE_API_TOKEN=" + secrets.token_urlsafe(48) + "\n")
        with env.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(template)
    config = PortalSettings.from_env()
    if args.command == "init":
        PortalRepository(config.db_path).initialize()
        Repository(config.evidence_settings().db_path).initialize()
    if args.command == "configure-empty-dataset":
        from app.dify_client import DifyClient
        from app.errors import DomainError
        with DifyClient(config.evidence_settings()) as client:
            detail = client.request("GET", client.path())
            if detail.get("document_count") != 0:
                raise DomainError("dataset_not_empty", "此命令只配置空白专用知识库")
            embedding = {"embedding_model": args.embedding_model, "embedding_model_provider": args.embedding_provider}
            client.request("PATCH", client.path(), json={"indexing_technique": "high_quality", **embedding,
                "retrieval_model": client.retrieval_model(embedding)})
            client.dataset()
            client.snapshot_metadata()
    print(json.dumps({"configuration_file_exists": env.is_file(), "configured": config.readiness(),
        "data_root": str(config.data_root), "portal_url": config.origin,
        "note": "这里只检查配置是否齐备；真实连接和业务结果见验收记录。"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
