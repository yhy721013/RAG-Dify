import os
from dataclasses import dataclass
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

    def __post_init__(self):
        if self.origin not in {"http://127.0.0.1:8001", "http://localhost:8001"}:
            raise DomainError("configuration_error", "测试台只允许本机 8001 端口")
        if not 1 <= self.max_pdf_bytes <= 500 * 1024 * 1024 or not 1 <= self.max_pdf_pages <= 3000:
            raise DomainError("configuration_error", "PDF 限额超出支持范围")
        if self.evidence_local_url != "http://127.0.0.1:8002":
            raise DomainError("configuration_error", "本机证据服务固定为 127.0.0.1:8002")
        if self.data_root.resolve() == (ROOT / "data").resolve():
            raise DomainError("configuration_error", "测试台须使用独立数据子目录")

    @classmethod
    def from_env(cls):
        # 不读旧试点 .env；所有门户配置都有独立名称。
        values = {**dotenv_values(ROOT / ".env.portal"), **os.environ}
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
            evidence_public_url=value("EVIDENCE_PUBLIC_URL"))

    @property
    def db_path(self):
        return self.data_root / "portal.db"

    def evidence_settings(self):
        return Settings(app_env=self.app_env, data_root=self.data_root, db_path=self.data_root / "evidence.db",
            dify_base_url=self.dify_base_url, dify_api_key=self.knowledge_api_key, dataset_id=self.dataset_id,
            api_token=self.evidence_api_token, published_snapshots=True, partitioned_dataset=True)

    def readiness(self):
        return {"mineru": self.mineru_executable.is_file(),
            "knowledge": configured(self.knowledge_api_key) and configured(self.dataset_id),
            "workflow": configured(self.workflow_api_key), "evidence_token": configured(self.evidence_api_token),
            "evidence_https": urlsplit(self.evidence_public_url).scheme == "https"}

    def require_assessment(self):
        missing = [key for key, ok in self.readiness().items() if key != "mineru" and not ok]
        if missing:
            raise DomainError("configuration_error", "请先完成配置：" + "、".join(missing), status=503)
