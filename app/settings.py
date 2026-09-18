import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from app.errors import DomainError

ROOT = Path(__file__).resolve().parent.parent


def configured(value: str) -> bool:
    return bool(value.strip()) and not value.strip().upper().startswith("REPLACE_")


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    db_path: Path = ROOT / "data/app.db"
    data_root: Path = ROOT / "data"
    active_snapshot_id: str = ""
    dify_base_url: str = ""
    dify_api_key: str = ""
    dataset_id: str = ""
    api_token: str = ""
    max_images: int = 4
    max_checks: int = 6
    max_evidence_per_check: int = 3
    max_evidence_text_chars: int = 16000
    dify_timeout_seconds: float = 30
    dify_index_timeout_seconds: float = 600
    dify_poll_seconds: float = 2

    def __post_init__(self):
        if self.app_env not in {"development", "production", "test"}:
            raise DomainError("configuration_error", "APP_ENV 只允许 development、production、test")
        for name, maximum in (("max_images", 4), ("max_checks", 6), ("max_evidence_per_check", 3),
                              ("max_evidence_text_chars", 100000)):
            if not 1 <= getattr(self, name) <= maximum:
                raise DomainError("configuration_error", f"{name} 必须在 1～{maximum} 之间", name)
        for name in ("dify_timeout_seconds", "dify_index_timeout_seconds", "dify_poll_seconds"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise DomainError("configuration_error", "时间配置必须为有限非负数", name)

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        def path(name, default):
            value = Path(os.getenv(name, default))
            return value if value.is_absolute() else ROOT / value

        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            db_path=path("APP_DB_PATH", "data/app.db"),
            data_root=path("APP_DATA_ROOT", "data"),
            active_snapshot_id=os.getenv("ACTIVE_SNAPSHOT_ID", ""),
            dify_base_url=os.getenv("DIFY_KNOWLEDGE_BASE_URL", ""),
            dify_api_key=os.getenv("DIFY_KNOWLEDGE_API_KEY", ""),
            dataset_id=os.getenv("DIFY_DATASET_ID", ""),
            api_token=os.getenv("EVIDENCE_API_TOKEN", ""),
            **{name: int(os.getenv(name.upper(), str(default))) for name, default in (
                ("max_images", 4), ("max_checks", 6), ("max_evidence_per_check", 3),
                ("max_evidence_text_chars", 16000))},
            **{name: float(os.getenv(name.upper(), str(default))) for name, default in (
                ("dify_timeout_seconds", 30), ("dify_index_timeout_seconds", 600),
                ("dify_poll_seconds", 2))},
        )

    def require_dify(self):
        for name, value in (("DIFY_KNOWLEDGE_BASE_URL", self.dify_base_url),
                            ("DIFY_KNOWLEDGE_API_KEY", self.dify_api_key),
                            ("DIFY_DATASET_ID", self.dataset_id)):
            if not configured(value):
                raise DomainError("configuration_error", "尚未配置真实 Dify 连接", name, 503)
