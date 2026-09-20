"""可显示的诊断信息：先脱敏再截断，不转发请求头或模型输入输出。"""
import re
import traceback
from urllib.parse import urlsplit, urlunsplit

from app.errors import DomainError

PRIVATE_KEYS = {"authorization", "api_key", "access_token", "refresh_token", "secret", "password",
                "headers", "inputs", "outputs", "prompt", "prompts", "reasoning", "reasoning_content"}


def scrub(value, secrets=(), limit=6000):
    if isinstance(value, dict):
        return {str(key): ("[已隐藏]" if str(key).lower() in PRIVATE_KEYS else scrub(item, secrets, limit))
                for key, item in list(value.items())[:100]}
    if isinstance(value, (list, tuple)):
        return [scrub(item, secrets, limit) for item in value[:100]]
    if not isinstance(value, str):
        return value
    text = value
    for secret in sorted({str(s) for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, "[已隐藏]")
    text = re.sub(r"\b(?:app-|dataset-|sk-)[A-Za-z0-9_-]{16,}", "[已隐藏密钥]", text)
    text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [已隐藏]", text)
    text = re.sub(r'''(?i)([\w]*(?:api_key|api_token|password|secret|authorization)[\w]*["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}]+)''', r"\1[已隐藏]", text)
    def safe_url(match):
        try:
            url = urlsplit(match.group())
            netloc = url.hostname or ""
            if url.port:
                netloc += ":" + str(url.port)
            return urlunsplit((url.scheme, netloc, url.path, "", ""))
        except ValueError:
            return "[无效 URL]"
    text = re.sub(r'''https?://[^\s<>"']+''', safe_url, text)
    return text if len(text) <= limit else text[:limit] + "\n…（详情已截断）"


def upstream_details(response, secrets=()):
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return scrub({"upstream_status": response.status_code, "upstream_code": payload.get("code"),
                  "upstream_message": payload.get("message") or payload.get("error"),
                  "retry_after": response.headers.get("retry-after")}, secrets)


def advice(code, details=None):
    details = details or {}
    remote_code = str(details.get("upstream_code", "")).lower()
    status = details.get("upstream_status")
    if code in {"connection_failed", "connection_timeout"}:
        return "检查 HTTPS 地址、网络与隧道进程；地址变化后同步 Dify 并重新发布。不关闭 TLS 证书验证。"
    if status == 429 or "rate_limit" in remote_code:
        return "服务限流。按 Retry-After 或稍后恢复原任务，不要连续新建评估。"
    if status == 401:
        return "在首次配置中核对对应密钥。Knowledge 与 Workflow 密钥不能互换，保存后应用配置并重新诊断。"
    if status == 403:
        return "核对密钥是否授权当前知识库、应用 API 是否启用，以及提供方额度和模型权限。"
    if code in {"ambiguous_run", "ambiguous_creation", "sync_locked"}:
        return "先根据运行/文档 ID 和阶段记录人工对账；结果不明时不会自动再次创建。"
    if code in {"review_required", "incomplete_evidence", "clause_boundary_error", "invalid_source"}:
        return "返回条款复核，修正原文、来源、边界及必要上下文；只发布已批准且依赖完整的条款。"
    if code in {"retrieval_gate_failed", "mapping_error", "metadata_error", "activation_blocked"}:
        return "查看检索自检明细和知识版本；检查目标条款、版本过滤、远端分块及本地映射，不跳过发布门禁。"
    if code in {"configuration_error", "configuration_changed", "configuration_conflict"}:
        return "打开首次配置，核对实际生效值与环境变量覆盖；先保存草稿，空闲时应用，再运行诊断。"
    if code in {"equipment_scope_error", "workflow_failed"}:
        return "查看失败节点与脱敏错误；核对是否为同一台普通卧式金属车床、图片可辨认、模型可用及 Dify Secret 绑定。"
    if "parse" in code:
        return "查看本任务解析日志。确认 MinerU 4.0.2 独立环境、模型资源及完整 PDF；修复后恢复原任务。"
    if code == "revision_conflict":
        return "此页面版本已过期。保留尚未保存的内容，重新打开文件后对照保存。"
    if code in {"workflow_network_error", "workflow_disconnected", "dify_timeout", "infrastructure_error"}:
        return "检查系统诊断及任务日志；存在 Dify 运行 ID 时恢复原运行，避免重复上传或调用模型。"
    return "核对标出的字段和阶段详情；修复后恢复任务，或下载脱敏诊断包交给开发者排查。"


def public_error(error, secrets=(), *, stage="", request_id=""):
    if isinstance(error, DomainError):
        result = error.detail()
    else:
        frames = traceback.extract_tb(error.__traceback__)[-8:]
        result = {"code": "infrastructure_error", "message": "处理失败：" + type(error).__name__, "field": "",
                  "details": {"exception": str(error), "frames": [
                      {"file": frame.filename.replace("\\", "/").split("/")[-1], "line": frame.lineno, "function": frame.name}
                      for frame in frames]}}
    result.update(stage=stage, request_id=request_id, suggestion=advice(result["code"], result.get("details")))
    return scrub(result, secrets)
