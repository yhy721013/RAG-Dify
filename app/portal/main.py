import json
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import Field, ValidationError

from app.errors import DomainError
from app.portal import review
from app.portal.files import save_upload, validate_image, validate_pdf
from app.portal.repository import PortalRepository
from app.portal.settings import PortalSettings
from app.repository import Repository, digest, now
from app.schemas import StrictModel
from app.settings import ROOT
from evals.evaluate_retrieval import RetrievalCase
from ingestion.mineru_adapter import local_path


class ReviewAction(StrictModel):
    revision: int = Field(ge=0)
    actor: str = Field(min_length=1, max_length=100, pattern=r"\S")
    metadata: dict[str, str] = Field(default_factory=dict)
    changes: dict = Field(default_factory=dict)
    block_ids: list[str] = Field(default_factory=list)
    acknowledgements: list[str] = Field(default_factory=list)
    offset: int = 0
    candidate_ids: list[str] = Field(default_factory=list)


class ReleaseAction(StrictModel):
    document_ids: list[str] = Field(min_length=1, max_length=100)
    preview_hash: str = ""
    confirm_replacements: bool = False
    cases: list[dict] = Field(default_factory=list, max_length=100)
    actor: str = Field(default="", max_length=100)


def public_job(job):
    return {key: value for key, value in job.items() if key not in {"payload", "dedupe_key"}}


def create_app(config=None):
    settings = config or PortalSettings.from_env()
    store = PortalRepository(settings.db_path)
    evidence = Repository(settings.evidence_settings().db_path)
    csrf = secrets.token_urlsafe(32)
    render_lock = threading.Lock()
    templates = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape())

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        evidence.initialize()
        yield

    app = FastAPI(title="本地标准复核与设备评估", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.settings = store, settings

    @app.middleware("http")
    async def local_boundary(request, call_next):
        allowed = {"127.0.0.1:8001", "localhost:8001"}
        peer = request.client.host if request.client else ""
        if request.headers.get("host") not in allowed or (peer not in {"127.0.0.1", "::1"} and settings.app_env != "test"):
            return JSONResponse({"error": {"code": "local_only", "message": "测试台仅供本机使用"}}, status_code=403)
        if request.method not in {"GET", "HEAD"}:
            if (request.headers.get("origin") != settings.origin or
                not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf) or
                not secrets.compare_digest(request.cookies.get("portal_session", ""), csrf)):
                return JSONResponse({"error": {"code": "csrf_rejected", "message": "页面会话已过期，请刷新"}}, status_code=403)
            try:
                length = int(request.headers.get("content-length", "-1"))
            except ValueError:
                length = -1
            # 浏览器上传有 Content-Length；拒绝无限长流，限制解析 multipart 前的体积。
            if length < 0 or length > max(settings.max_pdf_bytes, 20 * 1024 * 1024) + 1024 * 1024:
                return JSONResponse({"error": {"code": "file_too_large", "message": "请求过大或缺少长度"}}, status_code=413)
        response = await call_next(request)
        response.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store", "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; frame-src 'self'; object-src 'self'; base-uri 'none'; frame-ancestors 'self'; form-action 'self'"})
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse({"error": error.detail()}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(request, error):
        return JSONResponse({"error": {"code": "input_error", "message": "输入格式不正确",
            "fields": [{"field": ".".join(map(str, row["loc"])), "message": row["msg"]} for row in error.errors()]}}, status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, error):
        return JSONResponse({"error": {"code": "infrastructure_error", "message": "任务库暂不可用"}}, status_code=503)

    app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return templates.get_template("portal.html").render()

    @app.get("/api/status")
    def status():
        response = JSONResponse({"configured": settings.readiness(), "csrf_token": csrf,
            "current_snapshot": store.state("current_snapshot"), "worker_heartbeat": store.state("worker_heartbeat"),
            "max_pdf_bytes": settings.max_pdf_bytes, "max_pdf_pages": settings.max_pdf_pages,
            "equipment_type": json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))["equipment_type"]})
        response.set_cookie("portal_session", csrf, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/documents")
    def documents():
        return [{key: value for key, value in row.items() if key != "payload"} | {
            "approved_count": sum(item["record"]["content_review_status"] == "approved" for item in row["payload"].get("candidates", [])),
            "candidate_count": len(row["payload"].get("candidates", []))} for row in store.list_documents()]

    @app.post("/api/documents")
    async def upload_pdf(file: UploadFile = File(...)):
        name = Path((file.filename or "").replace("\\", "/")).name[:200]
        path, checksum, size = await save_upload(file, settings.data_root / "uploads", settings.max_pdf_bytes)
        try:
            pages = validate_pdf(path, name, settings.max_pdf_pages)
            target = settings.data_root / "raw_pdf" / (checksum + ".pdf")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                path.unlink()
            else:
                path.replace(target)
            doc, created = store.register_document(checksum, name, target.relative_to(settings.data_root).as_posix(), pages)
            return {"document_id": doc["id"], "reused": not created, "status": doc["status"], "bytes": size, "pages": pages}
        finally:
            path.unlink(missing_ok=True)

    @app.get("/api/documents/{document_id}")
    def document(document_id: str):
        doc = store.document(document_id)
        refs = {ref for page in doc["payload"].get("normalized", {}).get("pages", []) for block in page["blocks"] for ref in block["asset_refs"]}
        return {**doc, "asset_links": {ref: f"/api/documents/{document_id}/assets/{digest(ref)}" for ref in refs}}

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
        return store.save_document(document_id, body.revision, payload, "pending_review", "metadata", body.actor)

    @app.post("/api/documents/{document_id}/candidates/{candidate_id}/{action}")
    def candidate(document_id: str, candidate_id: str, action: str, body: ReviewAction):
        doc = store.document(document_id)
        if action == "edit":
            payload = review.edit_candidate(doc["payload"], candidate_id, body.changes, body.block_ids, settings.data_root)
        elif action == "approve":
            payload = review.approve(doc["payload"], candidate_id, body.actor, body.acknowledgements, settings.data_root)
        elif action == "split":
            payload = review.split_candidate(doc["payload"], candidate_id, body.offset)
        elif action == "merge":
            payload = review.merge_candidates(doc["payload"], [candidate_id, *body.candidate_ids], settings.data_root)
        else:
            raise DomainError("not_found", "未知复核操作", status=404)
        return store.save_document(document_id, body.revision, payload, "pending_review", action, body.actor)

    @app.get("/api/jobs")
    def jobs():
        return [public_job(row) for row in store.jobs()]

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return {**public_job(store.job(job_id)), "events": store.events(job_id)}

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: str):
        return public_job(store.retry(job_id))

    @app.get("/api/releases")
    def releases():
        return {"current_snapshot": store.state("current_snapshot"), "releases": store.releases()}

    @app.post("/api/releases/preview")
    def preview(body: ReleaseAction):
        return review.release_preview(store, evidence, body.document_ids)

    @app.post("/api/releases")
    def release(body: ReleaseAction):
        settings.evidence_settings().require_dify()
        candidate = review.release_preview(store, evidence, body.document_ids)
        if candidate["preview_hash"] != body.preview_hash:
            raise DomainError("revision_conflict", "预览已过期，请重新预览", status=409)
        if candidate["unchanged"]:
            raise DomainError("unchanged_snapshot", "已批准内容与当前版本完全一致，无需重复建立索引", status=409)
        if candidate["replacements"] and not body.confirm_replacements:
            raise DomainError("replacement_confirmation", "本次将替换同标准版本的条款集合，请确认预览", status=409)
        if not body.actor.strip() or not body.cases:
            raise DomainError("review_required", "请填写人工标注的检索问题、目标条款与复核人")
        snapshot_id = "portal_" + digest([body.preview_hash, body.cases, body.actor])[:24]
        cases = [RetrievalCase.model_validate({**row, "snapshot_id": snapshot_id, "annotated_by": body.actor,
                    "annotated_at": now()}).model_dump() for row in body.cases]
        # 日期固定在首次入队；重复提交复用相同知识版本，不生成第二次远程创建。
        existing = next((row for row in store.jobs() if row["kind"] == "publish" and row["payload"].get("snapshot_id") == snapshot_id), None)
        if existing:
            return public_job(existing)
        candidate.update(snapshot_id=snapshot_id, cases=cases)
        return public_job(store.enqueue("publish", candidate, "publish:" + snapshot_id))

    @app.post("/api/assessments")
    async def assessment(images: list[UploadFile] = File(...), equipment_description: str = Form(""),
                         operating_state: str = Form("未知"), work_context: str = Form(...),
                         same_equipment_confirmed: bool = Form(False), submission_id: str = Form(...)):
        settings.require_assessment()
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
