import os
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from app.errors import DomainError
from app.settings import ROOT, Settings, configured


@dataclass(frozen=True)
class PortalSettings:
    data_root: Path = ROOT / "data/portal"
    origin: str = "http://127.0.0.1:8001"
    mineru_executable: Path = ROOT / ".venv-mineru/Scripts/mineru-kit.exe"
    max_pdf_bytes: int = 50 * 1024 * 1024
    max_pdf_pages: int = 300
    parse_timeout_seconds: int = 7200
    dify_base_url: str = "https://api.dify.ai/v1"
    knowledge_api_key: str = ""
    dataset_id: str = ""
    workflow_api_key: str = ""
    evidence_api_token: str = ""
    evidence_local_url: str = "http://127.0.0.1:8002"
    evidence_public_url: str = ""
    app_env: str = "development"
    vision_provider: str = "langgenius/siliconflow/siliconflow"
    vision_model: str = "Qwen/Qwen3.5-27B"
    embedding_provider: str = "langgenius/siliconflow/siliconflow"
    embedding_model: str = "Qwen/Qwen3-Embedding-4B"
    workflow_app_id: str = ""
    cloudflared_executable: Path = ROOT / "data/tools/cloudflared/2026.9.1/cloudflared.exe"

    def __post_init__(self):
        if self.origin not in {"http://127.0.0.1:8001", "http://localhost:8001"}:
            raise DomainError("configuration_error", "测试台只允许本机 8001 端口")
        if not 1 <= self.max_pdf_bytes <= 500 * 1024 * 1024 or not 1 <= self.max_pdf_pages <= 3000:
            raise DomainError("configuration_error", "PDF 限额超出支持范围")
        if not 1 <= self.parse_timeout_seconds <= 86400:
            raise DomainError("configuration_error", "解析超时须为 1～86400 秒")
        if self.evidence_local_url != "http://127.0.0.1:8002":
            raise DomainError("configuration_error", "本机证据服务固定为 127.0.0.1:8002")
        if self.data_root.resolve() == (ROOT / "data").resolve():
            raise DomainError("configuration_error", "测试台须使用独立数据子目录")

    @classmethod
    def from_env(cls):
        # 不读旧试点 .env；所有门户配置都有独立名称。
        values = {**dotenv_values(ROOT / ".env.portal"), **os.environ}
        return cls.from_values(values)

    @classmethod
    def from_values(cls, values):
        def value(name, default=""):
            return values.get("PORTAL_" + name) or default

        def path(name, default):
            item = Path(value(name, default))
            return item if item.is_absolute() else ROOT / item

        return cls(data_root=path("DATA_ROOT", "data/portal"),
            origin=value("ORIGIN", "http://127.0.0.1:8001"),
            mineru_executable=path("MINERU_EXECUTABLE", ".venv-mineru/Scripts/mineru-kit.exe"),
            max_pdf_bytes=int(value("MAX_PDF_BYTES", str(50 * 1024 * 1024))),
            max_pdf_pages=int(value("MAX_PDF_PAGES", "300")),
            parse_timeout_seconds=int(value("PARSE_TIMEOUT_SECONDS", "7200")),
            dify_base_url=value("DIFY_BASE_URL", "https://api.dify.ai/v1"),
            knowledge_api_key=value("KNOWLEDGE_API_KEY"), dataset_id=value("DATASET_ID"),
            workflow_api_key=value("WORKFLOW_API_KEY"), evidence_api_token=value("EVIDENCE_API_TOKEN"),
            evidence_public_url=value("EVIDENCE_PUBLIC_URL"),
            vision_provider=value("VISION_PROVIDER", "langgenius/siliconflow/siliconflow"),
            vision_model=value("VISION_MODEL", "Qwen/Qwen3.5-27B"),
            embedding_provider=value("EMBEDDING_PROVIDER", "langgenius/siliconflow/siliconflow"),
            embedding_model=value("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-4B"),
            workflow_app_id=value("WORKFLOW_APP_ID"),
            cloudflared_executable=path("CLOUDFLARED_EXECUTABLE", "data/tools/cloudflared/2026.9.1/cloudflared.exe"))

    def secret_values(self):
        return (self.knowledge_api_key, self.workflow_api_key, self.evidence_api_token)

    @property
    def db_path(self):
        return self.data_root / "portal.db"

    def evidence_settings(self):
        return Settings(app_env=self.app_env, data_root=self.data_root, db_path=self.data_root / "evidence.db",
            dify_base_url=self.dify_base_url, dify_api_key=self.knowledge_api_key, dataset_id=self.dataset_id,
            api_token=self.evidence_api_token, published_snapshots=True, partitioned_dataset=True)

    def readiness(self):
        public_url = urlsplit(self.evidence_public_url)
        return {"mineru": self.mineru_executable.is_file(),
            "knowledge": configured(self.knowledge_api_key) and configured(self.dataset_id),
            "workflow": configured(self.workflow_api_key), "evidence_token": configured(self.evidence_api_token),
            "evidence_https": public_url.scheme == "https" and bool(public_url.hostname)
                and not any((public_url.username, public_url.password, public_url.query, public_url.fragment))
                and "REPLACE_" not in self.evidence_public_url.upper()}

    def require_assessment(self):
        missing = [key for key, ok in self.readiness().items() if key != "mineru" and not ok]
        if missing:
            raise DomainError("configuration_error", "请先完成配置：" + "、".join(missing), status=503)


def bootstrap_settings():
    """数值配置错误时仍提供修复页面；不猜测或切换资料目录。"""
    try:
        return PortalSettings.from_env(), ""
    except (ValueError, DomainError):
        values = {**dotenv_values(ROOT / ".env.portal"), **os.environ}
        data_root = Path(values.get("PORTAL_DATA_ROOT") or "data/portal")
        if not data_root.is_absolute():
            data_root = ROOT / data_root
        # 路径本身不合法时由启动诊断页处理，不能悄悄换库。
        defaults = PortalSettings(data_root=data_root)
        for key, default in (("MAX_PDF_BYTES", defaults.max_pdf_bytes), ("MAX_PDF_PAGES", defaults.max_pdf_pages),
                             ("PARSE_TIMEOUT_SECONDS", defaults.parse_timeout_seconds)):
            values["PORTAL_" + key] = str(default)
        if values.get("PORTAL_ORIGIN") not in {"http://127.0.0.1:8001", "http://localhost:8001"}:
            values["PORTAL_ORIGIN"] = defaults.origin
        safe = PortalSettings.from_values(values)
        return safe, "配置数值或本机访问地址无效，请在首次配置中修正并应用。"
