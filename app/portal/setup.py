"""本机配置草稿；密钥只写后端文件，读取接口不返回其值。"""
import json
import os
import re
import tempfile
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from dotenv import dotenv_values, set_key

from app.errors import DomainError
from app.portal.settings import PortalSettings
from app.repository import digest, now
from app.safe_diagnostics import scrub
from app.settings import ROOT
from ingestion.sync_dify import atomic_json

FIELDS = {
    "dify_base_url": ("DIFY_BASE_URL", "Dify Service API 地址", "url", "knowledge"),
    "dataset_id": ("DATASET_ID", "专用知识库 ID 或网址", "text", "knowledge"),
    "knowledge_api_key": ("KNOWLEDGE_API_KEY", "Knowledge API 密钥（仅限该库）", "password", "knowledge"),
    "embedding_provider": ("EMBEDDING_PROVIDER", "嵌入模型提供方", "text", "knowledge"),
    "embedding_model": ("EMBEDDING_MODEL", "嵌入模型 ID", "text", "knowledge"),
    "evidence_public_url": ("EVIDENCE_PUBLIC_URL", "证据服务 HTTPS 地址", "url", "https"),
    "evidence_api_token": ("EVIDENCE_API_TOKEN", "证据服务密钥（同值填入 Dify Secret）", "password", "https"),
    "workflow_app_id": ("WORKFLOW_APP_ID", "Dify 应用 ID 或编排页面网址", "text", "workflow"),
    "workflow_api_key": ("WORKFLOW_API_KEY", "Workflow API 密钥", "password", "workflow"),
    "vision_provider": ("VISION_PROVIDER", "视觉模型提供方", "text", "workflow"),
    "vision_model": ("VISION_MODEL", "视觉与评估模型 ID", "text", "workflow"),
    "mineru_executable": ("MINERU_EXECUTABLE", "MinerU 可执行文件", "text", "environment"),
    "cloudflared_executable": ("CLOUDFLARED_EXECUTABLE", "cloudflared 可执行文件", "text", "environment"),
    "max_pdf_bytes": ("MAX_PDF_BYTES", "PDF 文件上限（字节）", "number", "environment"),
    "max_pdf_pages": ("MAX_PDF_PAGES", "PDF 页数上限", "number", "environment"),
    "parse_timeout_seconds": ("PARSE_TIMEOUT_SECONDS", "解析超时（秒）", "number", "environment"),
    "origin": ("ORIGIN", "本机页面地址", "url", "environment"),
}
CONFIRMATIONS = {"dataset_created", "workflow_imported", "secret_bound", "workflow_published", "webapp_disabled"}


def fingerprint(config):
    return digest({key: str(value) for key, value in asdict(config).items()})


def atomic_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class SetupManager:
    def __init__(self, config, store, root=ROOT):
        self.config, self.store, self.root = config, store, Path(root)
        self.env = self.root / ".env.portal"
        self.draft = self.root / ".env.portal.draft"
        self.runtime = self.root / "data/portal-runtime"
        self.meta = self.runtime / "setup-draft.json"
        self.apply_path = self.runtime / "apply.json"

    def file_revision(self):
        return digest(self.env.read_text(encoding="utf-8-sig") if self.env.exists() else "")

    def values(self, path):
        values = dict(dotenv_values(path)) if path.is_file() else {}
        for attr, (name, *_rest) in FIELDS.items():
            values.setdefault("PORTAL_" + name, str(getattr(self.config, attr)))
        values.setdefault("PORTAL_DATA_ROOT", str(self.config.data_root))
        return values

    def read_meta(self):
        return json.loads(self.meta.read_text(encoding="utf-8")) if self.meta.exists() else None

    def read_draft(self, identity=None):
        meta = self.read_meta()
        if not meta or not self.draft.is_file() or (identity and meta["id"] != identity):
            raise DomainError("draft_changed", "配置草稿不存在或已更新，请重新保存/诊断", status=409)
        if meta["base_revision"] != self.file_revision():
            raise DomainError("configuration_conflict", "配置文件已被其他操作修改，请重新载入并保存草稿", status=409)
        config = PortalSettings.from_values({**self.values(self.draft), **os.environ})
        if fingerprint(config) != meta["fingerprint"]:
            raise DomainError("configuration_conflict", "草稿或环境变量已变化，请重新保存", status=409)
        return config, meta

    def public(self):
        values = self.values(self.env)
        meta = self.read_meta()
        draft_available = bool(meta and self.draft.exists() and meta["base_revision"] == self.file_revision())
        if draft_available:
            values = self.values(self.draft)
        fields = []
        for attr, (suffix, label, kind, group) in FIELDS.items():
            key = "PORTAL_" + suffix
            value = os.environ.get(key, values.get(key, "")) or ""
            fields.append({"name": attr, "label": label, "type": kind, "group": group,
                "value": "" if kind == "password" else value, "configured": bool(value),
                "environment_override": key in os.environ})
        apply = json.loads(self.apply_path.read_text(encoding="utf-8")) if self.apply_path.exists() else {}
        secret_values = [os.environ.get("PORTAL_" + spec[0], values.get("PORTAL_" + spec[0], "")) for spec in FIELDS.values() if spec[2] == "password"]
        return scrub({"fields": fields, "file_revision": self.file_revision(), "active_fingerprint": fingerprint(self.config),
                "draft": meta if draft_available else None, "apply": apply,
                "data_root": str(self.config.data_root), "manual_checks": self.manual_checks()}, secret_values)

    def manual_checks(self):
        if not self.store:
            return {}
        raw = self.store.state("setup_confirmations")
        state = json.loads(raw) if raw else {}
        return state if state.get("fingerprint") == fingerprint(self.config) else {}

    def confirm(self, checks):
        if not set(checks) <= CONFIRMATIONS:
            raise DomainError("input_error", "未知配置确认项目")
        value = {"fingerprint": fingerprint(self.config), "checks": sorted(set(checks)), "confirmed_at": now(),
                 "provenance": "manual_confirmation"}
        self.store.set_state("setup_confirmations", json.dumps(value))
        return value

    def save(self, changes, expected_revision):
        if expected_revision != self.file_revision():
            raise DomainError("configuration_conflict", "配置已变化，请重新载入；未覆盖其他修改", status=409)
        if self.store and self.store.state("maintenance"):
            raise DomainError("configuration_applying", "正在应用配置，请稍后再保存", status=409)
        if set(changes) - FIELDS.keys():
            raise DomainError("input_error", "只允许修改向导列出的字段")
        values = self.values(self.env)
        original_values = dict(values)
        for attr, value in changes.items():
            suffix, _, kind, _ = FIELDS[attr]
            key = "PORTAL_" + suffix
            if not isinstance(value, str) or any(char in value for char in ("\n", "\r", "\0")) or "${" in value or len(value) > 2000:
                raise DomainError("input_error", "配置值必须为单行文本", attr)
            value = value.strip()
            if kind == "password" and not value:
                continue  # 空密码框保留已有密钥，不通过掩码回传。
            if kind == "number":
                ranges = {"max_pdf_bytes": (1, 500 * 1024 * 1024), "max_pdf_pages": (1, 3000), "parse_timeout_seconds": (1, 86400)}
                low, high = ranges[attr]
                if not value.isdigit() or not low <= int(value) <= high:
                    raise DomainError("input_error", f"{FIELDS[attr][1]}须为 {low}～{high} 的整数", attr)
            if key in os.environ and value != os.environ[key]:
                raise DomainError("configuration_conflict", "此项被环境变量覆盖，请先在启动环境中调整", attr, 409)
            if attr in {"dataset_id", "workflow_app_id"} and value:
                if "://" in value:
                    pattern = r"/datasets/([a-fA-F0-9-]{36})(?:/|$)" if attr == "dataset_id" else r"/app/([a-fA-F0-9-]{36})(?:/|$)"
                    match = re.search(pattern, urlsplit(value).path)
                    if not match:
                        raise DomainError("input_error", "请粘贴对应 Dify 控制台网址或 UUID", attr)
                    value = match[1]
                try:
                    value = str(UUID(value))
                except ValueError as error:
                    raise DomainError("input_error", "ID 必须是有效 UUID", attr) from error
            if attr in {"dify_base_url", "evidence_public_url"} and value:
                url = urlsplit(value)
                if not url.hostname or url.scheme not in ({"https"} if attr == "evidence_public_url" else {"http", "https"}) or any((url.username, url.password, url.query, url.fragment)):
                    raise DomainError("input_error", "地址须为无内嵌凭据/查询参数的服务 URL", attr)
                value = value.rstrip("/")
            values[key] = value
        try:
            candidate = PortalSettings.from_values({**values, **os.environ})
        except (ValueError, DomainError) as error:
            raise DomainError("configuration_error", "配置数值或本机路径不合法，请核对环境设置") from error
        if self.store and self.store.releases() and (
            candidate.dataset_id != self.config.dataset_id or candidate.dify_base_url.rstrip("/") != self.config.dify_base_url.rstrip("/")):
            raise DomainError("configuration_conflict", "此目录已有知识版本，不能换库或换 Dify 服务混用数据；请在独立项目副本初始化", status=409)
        identity = uuid4().hex
        self.runtime.mkdir(parents=True, exist_ok=True)
        # 在忽略目录内构造完整文件再原子替换，保留已有注释及其他配置。
        fd, temporary = tempfile.mkstemp(prefix="config-", suffix=".env", dir=self.runtime)
        os.close(fd)
        path = Path(temporary)
        try:
            path.write_text(self.env.read_text(encoding="utf-8-sig") if self.env.exists() else "", encoding="utf-8")
            for key, value in values.items():
                if key.startswith("PORTAL_") and value is not None:
                    set_key(str(path), key, str(value), quote_mode="always")
            path.replace(self.draft)
        finally:
            path.unlink(missing_ok=True)
        changed = [name for name in FIELDS if str(getattr(candidate, name)) != str(getattr(self.config, name))
                   or values.get("PORTAL_" + FIELDS[name][0]) != original_values.get("PORTAL_" + FIELDS[name][0])]
        meta = {"id": identity, "base_revision": expected_revision, "fingerprint": fingerprint(candidate),
                "changed_fields": changed, "saved_at": now()}
        atomic_json(self.meta, meta)
        return meta

    def begin_apply(self, identity):
        candidate, meta = self.read_draft(identity)
        if candidate.data_root != self.config.data_root:
            raise DomainError("configuration_conflict", "不能通过运行中的向导切换资料目录", status=409)
        if not self.store:
            raise DomainError("configuration_error", "资料目录尚不可用，请先修正本机目录配置")
        self.store.begin_maintenance(identity)
        state = {"id": identity, "status": "queued", "started_at": now(), "fingerprint": meta["fingerprint"]}
        atomic_json(self.apply_path, state)
        return state
