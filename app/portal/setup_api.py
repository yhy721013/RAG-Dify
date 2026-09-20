import json
from dataclasses import replace
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import Response
from pydantic import Field

from app.errors import DomainError
from app.portal.diagnostics import run_diagnostics
from app.portal.setup import fingerprint
from app.portal.support import tail
from app.repository import now
from app.safe_diagnostics import public_error, scrub
from app.schemas import StrictModel
from app.settings import ROOT
from workflows.build_portal import build_portal


class DraftRequest(StrictModel):
    values: dict[str, str]
    file_revision: str


class IdentityRequest(StrictModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")


class DiagnosticRequest(StrictModel):
    source: str = "active"
    draft_id: str = ""


class ConfirmationRequest(StrictModel):
    checks: list[str] = Field(default_factory=list)


def diagnostic_task(job, manager):
    store = manager.store
    config = manager.config
    try:
        if job["payload"].get("source") == "draft":
            config, _ = manager.read_draft(job["payload"]["draft_id"])
        if fingerprint(config) != job["payload"]["fingerprint"]:
            raise DomainError("configuration_changed", "配置已变化，请重新运行诊断", status=409)
        store.progress(job["id"], "diagnosing")
        result = run_diagnostics(config, store, active_config=manager.config,
            emit=lambda row: store.note_event(job["id"], "diagnostic_check", row))
        store.progress(job["id"], "complete", result, status="succeeded")
        store.set_state("diagnostics_" + job["payload"]["source"], json.dumps({**result, "job_id": job["id"]}, ensure_ascii=False))
    except Exception as error:
        store.progress(job["id"], "diagnosing", status="failed", error=public_error(error, config.secret_values(), stage="diagnosing", request_id=job["id"]))


def latest_diagnostics(manager, source="active"):
    raw = manager.store.state("diagnostics_" + source)
    result = json.loads(raw) if raw else None
    if result:
        expected = fingerprint(manager.config)
        if source == "draft":
            try:
                expected = fingerprint(manager.read_draft()[0])
            except DomainError:
                expected = ""
        result["stale"] = result["fingerprint"] != expected
    return result


def tunnel_task(job, manager):
    from app.portal.tunnel import operate
    store, config = manager.store, manager.config
    try:
        store.progress(job["id"], "tunnel")
        result = operate(config, job["payload"]["action"])
        store.progress(job["id"], "complete", result, status="succeeded")
    except Exception as error:
        store.progress(job["id"], "tunnel", status="failed", error=public_error(error, config.secret_values(), stage="tunnel", request_id=job["id"]))


def install_setup_routes(app, manager):
    router = APIRouter()

    @router.get("/api/setup")
    def setup():
        return manager.public()

    @router.post("/api/setup/draft")
    def save_draft(body: DraftRequest):
        return manager.save(body.values, body.file_revision)

    @router.post("/api/setup/apply")
    def apply(body: IdentityRequest):
        from app.portal.services import launch_apply
        state = manager.begin_apply(body.id)
        try:
            launch_apply(body.id)
        except Exception:
            manager.store.set_state("maintenance", "")
            raise DomainError("startup_failed", "无法启动配置应用进程，请查看本机启动诊断")
        return state

    @router.post("/api/setup/confirmations")
    def confirm(body: ConfirmationRequest):
        return manager.confirm(body.checks)

    @router.get("/api/setup/workflow.yml")
    def workflow(source: str = "active", draft_id: str = ""):
        config = manager.read_draft(draft_id)[0] if source == "draft" else manager.config
        if not config.dataset_id or not config.evidence_public_url:
            raise DomainError("configuration_error", "先保存知识库 ID 和 HTTPS 地址，再生成工作流配置")
        checklist = json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))
        value = build_portal(config, checklist, config.vision_provider, config.vision_model, config.embedding_provider, config.embedding_model)
        return Response(json.dumps(value, ensure_ascii=False, indent=2), media_type="application/yaml",
            headers={"Content-Disposition": 'attachment; filename="portal.configured.yml"'})

    @router.post("/api/setup/initialize-dataset")
    def initialize_dataset():
        manager.config.evidence_settings().require_dify()
        return manager.store.enqueue("configure_dataset", {"fingerprint": fingerprint(manager.config)})

    @router.get("/api/diagnostics")
    def diagnostics(source: str = "active"):
        if source not in {"active", "draft"}:
            raise DomainError("input_error", "诊断来源不正确")
        return {"result": latest_diagnostics(manager, source)}

    @router.post("/api/diagnostics")
    def diagnose(body: DiagnosticRequest, tasks: BackgroundTasks):
        if body.source not in {"active", "draft"}:
            raise DomainError("input_error", "诊断来源不正确")
        config = manager.read_draft(body.draft_id)[0] if body.source == "draft" else manager.config
        with manager.store.connect(write=True) as conn:
            existing = conn.execute("SELECT id FROM jobs WHERE kind='diagnostics' AND status IN ('queued','running') LIMIT 1").fetchone()
            if existing:
                current = manager.store.job(existing[0])
                if current["payload"].get("source") != body.source or current["payload"].get("fingerprint") != fingerprint(config) or current["payload"].get("draft_id") != body.draft_id:
                    raise DomainError("diagnostic_busy", "另一份配置正在诊断，请完成后再检查此配置", status=409)
                return {"id": existing[0], "status": "running"}
            job = manager.store._enqueue(conn, "diagnostics", {"source": body.source, "draft_id": body.draft_id, "fingerprint": fingerprint(config)}, "diagnostics:" + uuid4().hex)
        # 诊断只有有界只读请求；不依赖被诊断的 worker 已正常启动。
        tasks.add_task(diagnostic_task, job, manager)
        return {"id": job["id"], "status": job["status"]}

    @router.get("/api/setup/tunnel")
    def tunnel_status():
        from app.portal.tunnel import status
        return status(manager.config)

    @router.post("/api/setup/tunnel/{action}")
    def tunnel_action(action: str, tasks: BackgroundTasks):
        if action not in {"start", "stop", "check"}:
            raise DomainError("input_error", "只允许启动、停止或检查本实例隧道")
        job = manager.store.enqueue("tunnel", {"action": action}, "tunnel:" + uuid4().hex)
        # 隧道属于门户进程；配置应用只重启 worker/证据服务，不带走隧道。
        tasks.add_task(tunnel_task, job, manager)
        return {"id": job["id"], "status": job["status"]}

    @router.get("/api/setup/service-logs")
    def logs():
        path = manager.runtime / "processes.json"
        state = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        result = {}
        for entry in state.get("processes", []):
            for key in ("stdout", "stderr"):
                from pathlib import Path
                value = entry.get(key)
                if value and Path(value).resolve().is_relative_to(manager.runtime.resolve()):
                    result[entry["role"] + "." + key] = tail(Path(value), secrets=manager.config.secret_values())
        return {"logs": scrub(result, manager.config.secret_values())}

    app.include_router(router)
