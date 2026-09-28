import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.errors import DomainError


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def digest(value) -> str:
    return sha256(json_text(value))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self, write=False):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise DomainError("schema_version_error", "数据库 schema_version 不受支持", status=503)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    def snapshot_active(self, snapshot_id: str) -> bool:
        with self.connect() as conn:
            rows = conn.execute("SELECT snapshot_state FROM standard_versions WHERE snapshot_id=?", (snapshot_id,)).fetchall()
        return bool(rows) and all(row[0] == "active" for row in rows)

    def all_clauses(self, snapshot_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT record_json FROM clauses WHERE snapshot_id=? ORDER BY clause_uid", (snapshot_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def clause(self, snapshot_id, clause_uid):
        with self.connect() as conn:
            row = conn.execute("SELECT record_json FROM clauses WHERE snapshot_id=? AND clause_uid=?", (snapshot_id, clause_uid)).fetchone()
        return json.loads(row[0]) if row else None

    def mapped_clause(self, snapshot_id, hit):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT clause_uid FROM dify_segments WHERE snapshot_id=? AND dataset_id=? AND document_id=? AND segment_id=?",
                (snapshot_id, hit["dataset_id"], hit["document_id"], hit["segment_id"]),
            ).fetchone()
        if not row:
            raise DomainError("mapping_error", "检索分块不存在已验证的条款映射", "hits", 502)
        result = self.clause(snapshot_id, row[0])
        if result is None:
            raise DomainError("mapping_error", "映射指向不存在的条款", "hits", 502)
        return result

    def save_context(self, request, payload, owner):
        request_hash = digest(request)
        with self.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM evidence_contexts WHERE request_id=?", (request["request_id"],)).fetchone()
            if row:
                if row["request_sha256"] != request_hash or row["owner"] != owner:
                    raise DomainError("idempotency_conflict", "相同 request_id 对应不同内容或调用方", "request_id", 409)
                return json.loads(row["payload_json"])
            conn.execute("INSERT INTO evidence_contexts VALUES (?, ?, ?, ?, ?, ?)",
                         (payload["context_id"], request["request_id"], request_hash, owner, json_text(payload), now()))
        return payload

    def cached_context(self, request, owner):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM evidence_contexts WHERE request_id=?", (request["request_id"],)).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != digest(request) or row["owner"] != owner:
            raise DomainError("idempotency_conflict", "相同 request_id 对应不同内容或调用方", "request_id", 409)
        return json.loads(row["payload_json"])

    def context(self, context_id, owner):
        with self.connect() as conn:
            row = conn.execute("SELECT payload_json FROM evidence_contexts WHERE context_id=? AND owner=?", (context_id, owner)).fetchone()
        if not row:
            raise DomainError("context_not_found", "当前调用方无此证据上下文", "context_id", 404)
        return json.loads(row[0])

    def save_report(self, draft, report, owner):
        draft_hash = digest(draft)
        with self.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM reports WHERE context_id=?", (draft["context_id"],)).fetchone()
            if row:
                if row["draft_sha256"] != draft_hash or row["owner"] != owner:
                    raise DomainError("idempotency_conflict", "修改草稿需要创建新评估请求", "context_id", 409)
                return json.loads(row["report_json"])
            conn.execute("INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (report["report_id"], draft["context_id"], draft_hash, owner, json_text(report),
                          report["markdown"], json_text(report["validation"]), report["created_at"]))
        return report

    def report(self, report_id, owner):
        with self.connect() as conn:
            row = conn.execute("SELECT report_json FROM reports WHERE report_id=? AND owner=?", (report_id, owner)).fetchone()
        if not row:
            raise DomainError("report_not_found", "当前调用方无此报告", "report_id", 404)
        return json.loads(row[0])
