import secrets
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import DomainError
from app.evidence import prepare
from app.reporting import finalize
from app.repository import Repository
from app.schemas import FinalizeRequest, PrepareRequest
from app.settings import Settings, configured


def create_app(settings: Settings | None = None, repository: Repository | None = None):
    config = settings or Settings.from_env()
    repo = repository or Repository(config.db_path)

    @asynccontextmanager
    async def lifespan(app):
        repo.initialize()
        yield

    app = FastAPI(title="evidence-api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.repository = repo
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not configured(config.api_token):
            raise DomainError("configuration_error", "服务密钥未配置", "EVIDENCE_API_TOKEN", 503)
        if credentials is None or not secrets.compare_digest(credentials.credentials.encode(), config.api_token.encode()):
            raise DomainError("unauthorized", "需要有效的服务级 Bearer 密钥", status=401)
        # 首版只有一个可信服务主体；不采用调用者可伪造的用户 ID。
        return "trusted-workflow"

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse(status_code=error.status, content={"error": error.detail()})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse(status_code=422, content={"error": {"code": "schema_validation_error",
            "fields": [{"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
                       for item in error.errors()]}})

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, error):
        return JSONResponse(status_code=503, content={"error": {"code": "infrastructure_error", "message": "数据库暂不可用"}})

    @app.get("/health")
    def health():
        database = False
        try:
            with repo.connect() as conn:
                database = conn.execute("PRAGMA user_version").fetchone()[0] == 1
            if config.published_snapshots:
                with repo.connect() as conn:
                    snapshots = [row[0] for row in conn.execute("SELECT DISTINCT snapshot_id FROM standard_versions")]
                snapshot = any(repo.snapshot_active(uid) for uid in snapshots)
            else:
                snapshot = repo.snapshot_active(config.active_snapshot_id)
        except sqlite3.Error:
            snapshot = False
        ready = database and snapshot and configured(config.api_token) and configured(config.dataset_id)
        return JSONResponse(status_code=200 if ready else 503, content={"status": "ok" if ready else "not_ready",
            "database": database, "snapshot_available": snapshot, "authentication_configured": configured(config.api_token)})

    @app.post("/evidence/prepare")
    def prepare_route(body: PrepareRequest, owner=Depends(authenticate)):
        return prepare(body, repo, config, owner)

    @app.post("/reports/finalize")
    def finalize_route(body: FinalizeRequest, owner=Depends(authenticate)):
        return finalize(body, repo, owner)

    @app.get("/reports/{report_id}")
    def get_report(report_id: str, owner=Depends(authenticate)):
        return repo.report(report_id, owner)

    return app


app = create_app()
