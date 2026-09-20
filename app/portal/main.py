import json
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import Field, ValidationError

from app.errors import DomainError
from app.portal import review
from app.portal import assistance
from app.portal.files import save_upload, validate_image, validate_pdf
from app.portal.repository import PortalRepository
from app.portal.settings import PortalSettings, bootstrap_settings
from app.portal.setup import SetupManager, fingerprint
from app.portal.setup_api import install_setup_routes, latest_diagnostics, diagnostic_task, tunnel_task
from app.portal.support import diagnostic_zip, task_diagnostics
from app.safe_diagnostics import public_error, scrub
from app.repository import Repository, digest, now
from app.schemas import StrictModel
from app.settings import ROOT
from evals.evaluate_retrieval import RetrievalCase
from ingestion.mineru_adapter import local_path, file_sha256


class ReviewAction(StrictModel):
    revision: int = Field(ge=0)
    actor: str = Field(min_length=1, max_length=100, pattern=r"\S")
    metadata: dict[str, str] = Field(default_factory=dict)
    changes: dict = Field(default_factory=dict)
    block_ids: list[str] = Field(default_factory=list)
    acknowledgements: list[str] = Field(default_factory=list)
    offset: int = 0
    candidate_ids: list[str] = Field(default_factory=list)
    review_hash: str = ""
    baseline_id: str = ""


class ReleaseAction(StrictModel):
    document_ids: list[str] = Field(min_length=1, max_length=100)
    preview_hash: str = ""
    confirm_replacements: bool = False
    cases: list[dict] = Field(default_factory=list, max_length=100)
    actor: str = Field(default="", max_length=100)
    case_draft_id: str = ""
    confirmed_case_ids: list[str] = Field(default_factory=list, max_length=100)


def public_job(job):
    return {key: value for key, value in job.items() if key not in {"payload", "dedupe_key"}}


def create_app(config=None, project_root=ROOT):
    settings, configuration_error = (config, "") if config else bootstrap_settings()
    store = PortalRepository(settings.db_path)
    evidence = Repository(settings.evidence_settings().db_path)
    csrf = secrets.token_urlsafe(32)
    render_lock = threading.Lock()
    templates = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape())
    manager = SetupManager(settings, store, project_root)
    error_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        evidence.initialize()
        store.interrupt_controls()
        yield

    app = FastAPI(title="本地标准复核与设备评估", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.settings, app.state.setup = store, settings, manager
    install_setup_routes(app, manager)

    @app.middleware("http")
    async def local_boundary(request, call_next):
        nonlocal settings, configuration_error
        request.state.trace_id = "req_" + uuid4().hex
        if config is None and manager.apply_path.exists():
            apply_state = json.loads(manager.apply_path.read_text(encoding="utf-8"))
            if apply_state.get("status") == "succeeded" and (configuration_error or apply_state.get("fingerprint") != fingerprint(settings)):
                candidate, problem = bootstrap_settings()
                if not problem and fingerprint(candidate) == apply_state["fingerprint"]:
                    settings, configuration_error = candidate, ""
                    manager.config = settings
                    app.state.settings = settings
        allowed = {"127.0.0.1:8001", "localhost:8001"}
        peer = request.client.host if request.client else ""
        if request.headers.get("host") not in allowed or (peer not in {"127.0.0.1", "::1"} and settings.app_env != "test"):
            return JSONResponse({"error": {"code": "local_only", "message": "测试台仅供本机使用"}}, status_code=403)
        if request.method not in {"GET", "HEAD"}:
            if (request.headers.get("origin") != settings.origin or
                not secrets.compare_digest(request.headers.get("x-csrf-token", "").encode(), csrf.encode()) or
                not secrets.compare_digest(request.cookies.get("portal_session", "").encode(), csrf.encode())):
                return JSONResponse({"error": {"code": "csrf_rejected", "message": "页面会话已过期，请刷新"}}, status_code=403)
            try:
                length = int(request.headers.get("content-length", "-1"))
            except ValueError:
                length = -1
            # 浏览器上传有 Content-Length；拒绝无限长流，限制解析 multipart 前的体积。
            if length < 0 or length > max(settings.max_pdf_bytes, 20 * 1024 * 1024) + 1024 * 1024:
                return JSONResponse({"error": {"code": "file_too_large", "message": "请求过大或缺少长度"}}, status_code=413)
            if not request.url.path.startswith(("/api/setup", "/api/diagnostics")):
                if configuration_error or store.state("maintenance"):
                    return JSONResponse({"error": {"code": "configuration_applying", "message": configuration_error or "正在应用配置，请等待服务恢复"}}, status_code=409)
        response = await call_next(request)
        response.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store", "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; frame-src 'self'; object-src 'self'; base-uri 'none'; frame-ancestors 'self'; form-action 'self'"})
        response.headers["X-Request-ID"] = request.state.trace_id
        return response

    def error_response(request, error, status_code):
        detail = public_error(error, settings.secret_values(), stage=request.url.path,
                              request_id=getattr(request.state, "trace_id", ""))
        with error_lock:
            log = settings.data_root / "logs/portal-errors.jsonl"
            try:
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"created_at": now(), **detail}, ensure_ascii=False) + "\n")
            except OSError:
                detail["logging_unavailable"] = True
        return JSONResponse({"error": detail}, status_code=status_code)

    def require_diagnostic_gate(stage):
        result = latest_diagnostics(manager)
        if result and not result["stale"] and not result["gates"].get(stage, True):
            blockers = [{"id": row["id"], "title": row["title"], "message": row["message"]}
                        for row in result["checks"] if row["status"] == "fail" and stage in row["gates"]]
            raise DomainError("environment_not_ready", "请先修复当前配置的诊断阻塞项并重新检查", status=409, details={"blockers": blockers})

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return error_response(request, error, error.status)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(request, error):
        fields = [{"field": ".".join(map(str, row["loc"])), "message": row["msg"]} for row in error.errors()]
        return error_response(request, DomainError("input_error", "输入格式不正确，请修正标出的字段", details={"fields": fields}), 422)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, error):
        return error_response(request, error, 503)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return error_response(request, error, 500)

    app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return templates.get_template("portal.html").render()

    @app.get("/api/status")
    def status():
        response = JSONResponse({"configured": settings.readiness(), "csrf_token": csrf,
            "current_snapshot": store.state("current_snapshot"), "worker_heartbeat": store.state("worker_heartbeat"),
            "max_pdf_bytes": settings.max_pdf_bytes, "max_pdf_pages": settings.max_pdf_pages,
            "equipment_type": json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))["equipment_type"],
            "checklist": json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))["checks"],
            "configuration_error": configuration_error, "configuration_fingerprint": fingerprint(settings),
            "portal_origin": settings.origin, "diagnostics": latest_diagnostics(manager),
            "maintenance": bool(store.state("maintenance"))})
        response.set_cookie("portal_session", csrf, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/documents")
    def documents():
        parsing = store.parse_jobs()
        return [scrub({key: value for key, value in row.items() if key != "payload"} | {
            "approved_count": sum(item["record"]["content_review_status"] == "approved" for item in row["payload"].get("candidates", [])),
            "candidate_count": len(row["payload"].get("candidates", [])),
            "full_document_covered": row["payload"].get("normalized", {}).get("full_document_covered"),
            "parse_job": parsing.get(row["id"])}, settings.secret_values()) for row in store.list_documents()]

    @app.post("/api/documents")
    async def upload_pdf(file: UploadFile = File(...)):
        name = Path((file.filename or "").replace("\\", "/")).name[:200]
        path, checksum, size = await save_upload(file, settings.data_root / "uploads", settings.max_pdf_bytes)
        try:
            pages = validate_pdf(path, name, settings.max_pdf_pages)
            target = settings.data_root / "raw_pdf" / (checksum + ".pdf")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if file_sha256(target) != checksum:
                    raise DomainError("source_archive_changed", "同名归档PDF已发生变化，请先核对并恢复原始归档", status=409)
                path.unlink()
            else:
                path.replace(target)
            doc, created = store.register_document(checksum, name, target.relative_to(settings.data_root).as_posix(), pages)
            if not created:
                archived = local_path(settings.data_root, doc["source_path"])
                if not archived.is_file() or file_sha256(archived) != checksum:
                    raise DomainError("source_archive_changed", "已有文件的归档不再匹配，未沿用批准记录", status=409)
            return scrub({"document_id": doc["id"], "reused": not created, "status": doc["status"], "bytes": size, "pages": pages,
                          "parse_job": store.parse_jobs(doc["id"]).get(doc["id"])}, settings.secret_values())
        finally:
            path.unlink(missing_ok=True)

    @app.get("/api/documents/{document_id}")
    def document(document_id: str, baseline_id: str = ""):
        doc = store.document(document_id)
        refs = {ref for page in doc["payload"].get("normalized", {}).get("pages", []) for block in page["blocks"] for ref in block["asset_refs"]}
        return {**doc, "asset_links": {ref: f"/api/documents/{document_id}/assets/{digest(ref)}" for ref in refs},
                "assistance": assistance.analyze(doc, settings.data_root, store.list_documents(), store.review_baseline(doc), baseline_id)}

    @app.get("/api/review/options")
    def review_options(document_id: str):
        store.document(document_id)
        rows, seen = [], set()
        docs = sorted(store.list_documents(), key=lambda d: d["id"] != document_id)
        for doc in docs:
            for item in doc["payload"].get("candidates", []):
                record = item["record"]
                uid = record.get("clause_uid")
                if uid and uid not in seen:
                    rows.append({"clause_uid": uid, "clause_no": record["clause_no"], "standard_code": record["standard_code"],
                        "text": record["text_verbatim"][:180], "status": record["content_review_status"],
                        "document_id": doc["id"], "candidate_id": item["id"], "filename": doc["filename"]})
                    seen.add(uid)
        return rows

    @app.get("/api/documents/{document_id}/pdf")
    def pdf(document_id: str):
        doc = store.document(document_id)
        return FileResponse(local_path(settings.data_root, doc["source_path"]), media_type="application/pdf")

    @app.get("/api/documents/{document_id}/pages/{page_number}")
    def pdf_page(document_id: str, page_number: int):
        import pypdfium2 as pdfium
        doc = store.document(document_id)
        if not 1 <= page_number <= doc["page_count"]:
            raise DomainError("not_found", "PDF 页码越界", status=404)
        target = settings.data_root / "previews" / doc["sha256"] / f"{page_number}.png"
        # PDFium 非线程安全；单进程内串行渲染并缓存原页图像。
        with render_lock:
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with pdfium.PdfDocument(local_path(settings.data_root, doc["source_path"])) as pdf:
                    page = pdf[page_number - 1]
                    width, height = page.get_size()
                    scale = min(2, 1800 / max(width, height))
                    bitmap = page.render(scale=scale)
                    bitmap.to_pil().save(target)
                    bitmap.close()
                    page.close()
        return FileResponse(target, media_type="image/png")

    @app.get("/api/documents/{document_id}/assets/{asset_id}")
    def asset(document_id: str, asset_id: str):
        payload = store.document(document_id)["payload"]
        refs = {ref for _, block in review.blocks_for(payload).values() for ref in block["asset_refs"]}
        ref = next((ref for ref in refs if digest(ref) == asset_id), None)
        if not ref:
            raise DomainError("not_found", "没有此图表资产", status=404)
        path = local_path(settings.data_root, ref)
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            return FileResponse(path, filename=path.name, media_type="application/octet-stream")
        return FileResponse(path)

    @app.post("/api/documents/{document_id}/metadata")
    def metadata(document_id: str, body: ReviewAction):
        doc = store.document(document_id)
        payload = review.update_metadata(doc["payload"], body.metadata)
        store.save_document(document_id, body.revision, payload, "pending_review", "metadata", body.actor)
        return document(document_id)

    @app.post("/api/documents/{document_id}/review/{action}")
    def batch(document_id: str, action: str, body: ReviewAction):
        doc = store.document(document_id)
        analysis = assistance.analyze(doc, settings.data_root, store.list_documents(), store.review_baseline(doc), body.baseline_id)
        if body.review_hash != analysis["review_hash"]:
            raise DomainError("revision_conflict", "批量对照已过期，请重新查看并确认", status=409)
        payload = review.batch_review(doc["payload"], body.candidate_ids, body.actor, body.acknowledgements, settings.data_root, analysis, action)
        store.save_document(document_id, body.revision, payload, "pending_review", action, body.actor)
        return document(document_id, body.baseline_id)

    @app.post("/api/documents/{document_id}/candidates/{candidate_id}/{action}")
    def candidate(document_id: str, candidate_id: str, action: str, body: ReviewAction):
        doc = store.document(document_id)
        if body.baseline_id:
            assistance.choose_baseline(doc, store.list_documents(), baseline_id=body.baseline_id)
        if action == "edit":
            payload = review.edit_candidate(doc["payload"], candidate_id, body.changes, body.block_ids, settings.data_root)
        elif action == "approve":
            review.item_for(doc["payload"], candidate_id)
            analysis = assistance.analyze(doc, settings.data_root)
            row = next(row for row in analysis["rows"] if row["candidate_id"] == candidate_id)
            if row["hard_blocked"]:
                raise DomainError("review_required", "来源、编号或页覆盖存在阻塞，不能批准", details={"issues": row["issues"], "document_checks": analysis["document_checks"]})
            payload = review.approve(doc["payload"], candidate_id, body.actor, body.acknowledgements, settings.data_root)
        elif action == "split":
            payload = review.split_candidate(doc["payload"], candidate_id, body.offset)
        elif action == "merge":
            payload = review.merge_candidates(doc["payload"], [candidate_id, *body.candidate_ids], settings.data_root)
        elif action == "organize":
            analysis = assistance.analyze(doc, settings.data_root, store.list_documents(), store.review_baseline(doc), body.baseline_id)
            if body.review_hash != analysis["review_hash"]:
                raise DomainError("revision_conflict", "结构建议已过期，请重新查看", status=409)
            row = next((r for r in analysis["rows"] if r["candidate_id"] == candidate_id), None)
            if not row or row["structure_blocked"]:
                raise DomainError("review_required", "先处理来源、归档或页覆盖阻塞，再应用结构建议")
            payload = review.reorganize_candidate(doc["payload"], candidate_id, row["structure_proposal"])
        else:
            raise DomainError("not_found", "未知复核操作", status=404)
        store.save_document(document_id, body.revision, payload, "pending_review", action, body.actor)
        return document(document_id, body.baseline_id)

    @app.get("/api/jobs")
    def jobs():
        rows = []
        for job in store.jobs():
            row = public_job(job)
            if job["payload"].get("document_id"):
                doc = store.document(job["payload"]["document_id"])
                row["document_id"], row["title"] = doc["id"], doc["filename"]
            elif job["kind"] == "assessment":
                row["title"] = f'{len(job["payload"].get("images", []))} 张设备图片'
            else:
                row["title"] = job["payload"].get("snapshot_id", "")
            rows.append(scrub(row, settings.secret_values()))
        return rows

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return {**public_job(store.job(job_id)), "events": store.events(job_id)}

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: str, tasks: BackgroundTasks):
        if store.job(job_id)["kind"] == "diagnostics":
            raise DomainError("diagnostic_retry", "请从首次配置重新发起诊断，使用当前配置")
        result = store.retry(job_id)
        if result["kind"] == "tunnel":
            tasks.add_task(tunnel_task, result, manager)
        return public_job(result)

    @app.get("/api/jobs/{job_id}/diagnostics")
    def job_diagnostics(job_id: str):
        return task_diagnostics(store.job(job_id), store, settings)

    @app.get("/api/jobs/{job_id}/diagnostics.zip")
    def download_diagnostics(job_id: str):
        data = task_diagnostics(store.job(job_id), store, settings)
        return Response(diagnostic_zip(data), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{store.job(job_id)["id"]}-diagnostics.zip"'})

    @app.get("/api/releases")
    def releases():
        return {"current_snapshot": store.state("current_snapshot"), "releases": store.releases()}

    @app.post("/api/releases/preview")
    def preview(body: ReleaseAction):
        value = review.release_preview(store, evidence, body.document_ids)
        return {**value, "case_draft": assistance.retrieval_drafts(value)}

    @app.post("/api/releases")
    def release(body: ReleaseAction):
        settings.evidence_settings().require_dify()
        require_diagnostic_gate("publish")
        candidate = review.release_preview(store, evidence, body.document_ids)
        if candidate.get("blockers"):
            raise DomainError("review_required", "请先修复发布预检中的问题", details={"blockers": candidate["blockers"]})
        if candidate["preview_hash"] != body.preview_hash:
            raise DomainError("revision_conflict", "预览已过期，请重新预览", status=409)
        if candidate["unchanged"]:
            raise DomainError("unchanged_snapshot", "已批准内容与当前版本完全一致，无需重复建立索引", status=409)
        if candidate["replacements"] and not body.confirm_replacements:
            raise DomainError("replacement_confirmation", "本次将替换同标准版本的条款集合，请确认预览", status=409)
        if not body.actor.strip() or not body.cases:
            raise DomainError("review_required", "请填写人工标注的检索问题、目标条款与复核人")
        if not body.case_draft_id and any(str(row.get("case_id", "")).startswith("draft_") for row in body.cases):
            raise DomainError("review_required", "自动问题草稿缺少来源与逐题确认，请重新预览并核对", "cases")
        if body.case_draft_id:
            draft = assistance.retrieval_drafts(candidate)
            if body.case_draft_id != draft["id"] or set(body.confirmed_case_ids) != {r.get("case_id") for r in body.cases}:
                raise DomainError("review_required", "问题草稿或预期答案尚未逐题人工确认，或批准范围已变化", "cases")
        snapshot_id = "portal_" + digest([body.preview_hash, body.cases, body.actor])[:24]
        cases = [RetrievalCase.model_validate({**row, "snapshot_id": snapshot_id, "annotated_by": body.actor,
                    "annotated_at": now()}).model_dump() for row in body.cases]
        allowed = {row["clause_uid"] for row in candidate["records"]}
        if (not any(row["answerable"] for row in cases) or len({row["case_id"] for row in cases}) != len(cases)
            or any(not row["query"].strip() or not set(row["expected_clause_uids"]) <= allowed for row in cases)):
            raise DomainError("evaluation_input_error", "至少填写一道可回答题；目标条款须属于本次批准范围，问题 ID 不得重复", "cases")
        # 日期固定在首次入队；重复提交复用相同知识版本，不生成第二次远程创建。
        existing = next((row for row in store.jobs() if row["kind"] == "publish" and row["payload"].get("snapshot_id") == snapshot_id), None)
        if existing:
            return public_job(existing)
        candidate.update(snapshot_id=snapshot_id, cases=cases, case_review={
            "source": "rule_draft_confirmed" if body.case_draft_id else "manual_annotation",
            "draft_id": body.case_draft_id, "confirmed_case_ids": body.confirmed_case_ids,
            "reviewed_by": body.actor, "reviewed_at": cases[0]["annotated_at"]})
        return public_job(store.enqueue("publish", candidate, "publish:" + snapshot_id))

    @app.post("/api/assessments")
    async def assessment(images: list[UploadFile] = File(...), equipment_description: str = Form(""),
                         operating_state: str = Form("未知"), work_context: str = Form(...),
                         same_equipment_confirmed: bool = Form(False), submission_id: str = Form(...)):
        settings.require_assessment()
        require_diagnostic_gate("assess")
        snapshot = store.state("current_snapshot")
        if not snapshot or not evidence.snapshot_active(snapshot):
            raise DomainError("snapshot_not_allowed", "请先发布一个通过检索自检的知识版本", status=409)
        if not 1 <= len(images) <= 4 or not same_equipment_confirmed:
            raise DomainError("input_error", "需上传 1～4 张图片并确认属于同一设备")
        if operating_state not in {"运行", "停机", "检修", "未知"} or not work_context.strip() or max(len(work_context), len(equipment_description)) > 4000:
            raise DomainError("input_error", "请完整填写工况，说明不超过 4000 字")
        if not 1 <= len(submission_id) <= 100:
            raise DomainError("input_error", "提交标识无效")
        saved = []
        for upload in images:
            path, checksum, size = await save_upload(upload, settings.data_root / "uploads", 5 * 1024 * 1024)
            try:
                info = validate_image(path)
                target = settings.data_root / "images" / (checksum + info["extension"])
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    path.unlink()
                else:
                    path.replace(target)
                saved.append({"path": target.relative_to(settings.data_root).as_posix(), "sha256": checksum,
                              "size": size, **info})
            finally:
                path.unlink(missing_ok=True)
        if len({row["sha256"] for row in saved}) != len(saved):
            raise DomainError("input_error", "图片重复，请选择不同角度")
        checklist = json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))
        payload = {"snapshot_id": snapshot, "images": saved, "inputs": {"equipment_type": checklist["equipment_type"],
            "equipment_description": equipment_description, "operating_state": operating_state,
            "work_context": work_context, "same_equipment_confirmed": True}}
        payload["configuration_fingerprint"] = fingerprint(settings)
        return public_job(store.enqueue("assessment", payload, "assessment:" + submission_id))

    def saved_report(job_id):
        job = store.job(job_id)
        if job["kind"] != "assessment" or job["status"] != "succeeded" or not job["result"].get("report_id"):
            raise DomainError("report_not_ready", "此任务尚无已校验保存的报告", status=409)
        return evidence.report(job["result"]["report_id"], "trusted-workflow")

    @app.get("/api/jobs/{job_id}/report")
    def report(job_id: str):
        return saved_report(job_id)

    @app.get("/api/jobs/{job_id}/report/{format}")
    def download(job_id: str, format: str):
        report = saved_report(job_id)
        if format not in {"json", "md"}:
            raise DomainError("not_found", "只支持 JSON 和 Markdown", status=404)
        content = json.dumps(report, ensure_ascii=False, indent=2) if format == "json" else report["markdown"]
        return Response(content, media_type="application/json" if format == "json" else "text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{report["report_id"]}.{format}"'})

    return app


app = create_app()
