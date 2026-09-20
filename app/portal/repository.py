import json
from pathlib import Path
from uuid import uuid4

from app.errors import DomainError
from app.repository import Repository, digest, json_text, now


def decode(row):
    result = dict(row)
    for name in ("payload", "result", "error"):
        if name + "_json" in result:
            result[name] = json.loads(result.pop(name + "_json"))
    return result


class PortalRepository(Repository):
    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            if conn.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise DomainError("schema_version_error", "不支持此任务库版本")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    def list_documents(self):
        with self.connect() as conn:
            return [decode(row) for row in conn.execute("SELECT * FROM documents ORDER BY created_at DESC")]

    def document(self, document_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if not row:
            raise DomainError("not_found", "找不到此标准文件", status=404)
        return decode(row)

    def register_document(self, file_hash, filename, source_path, page_count):
        with self.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM documents WHERE sha256=?", (file_hash,)).fetchone()
            if row:
                return decode(row), False
            uid = "pdf_" + uuid4().hex
            conn.execute("INSERT INTO documents(id,sha256,filename,source_path,page_count,status,created_at) VALUES(?,?,?,?,?,'queued',?)",
                (uid, file_hash, filename, source_path, page_count, now()))
            self._enqueue(conn, "parse", {"document_id": uid}, "parse:" + uid)
        return self.document(uid), True

    def parse_jobs(self, document_id=None):
        query = "SELECT id,dedupe_key,status,stage,error_json,updated_at FROM jobs WHERE kind='parse'"
        args = ()
        if document_id is not None:
            query += " AND dedupe_key=?"
            args = ("parse:" + document_id,)
        with self.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return {row["dedupe_key"][6:]: {"id": row["id"], "status": row["status"], "stage": row["stage"],
                "error": json.loads(row["error_json"]), "updated_at": row["updated_at"]}
                for row in rows if row["dedupe_key"].startswith("parse:")}

    def review_baseline(self, document):
        with self.connect() as conn:
            row = conn.execute("SELECT revision,payload_json FROM review_audit WHERE document_id=? AND revision<? AND action IN ('approve','approve_batch') ORDER BY revision DESC LIMIT 1",
                               (document["id"], document["revision"])).fetchone()
        if not row:
            return None
        return {**document, "revision": row["revision"], "payload": json.loads(row["payload_json"]),
                "filename": document["filename"] + "（本文件历史批准记录）"}

    def save_document(self, document_id, revision, payload, status, action, actor):
        with self.connect(write=True) as conn:
            changed = conn.execute("UPDATE documents SET payload_json=?,status=?,revision=revision+1 WHERE id=? AND revision=?",
                (json_text(payload), status, document_id, revision)).rowcount
            if changed != 1:
                raise DomainError("revision_conflict", "此标准已被修改，请刷新后重试", status=409)
            conn.execute("INSERT INTO review_audit(document_id,revision,action,actor,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (document_id, revision + 1, action, actor, json_text(payload), now()))
        return self.document(document_id)

    def _enqueue(self, conn, kind, payload, key):
        if conn.execute("SELECT 1 FROM state WHERE key='maintenance' AND value<>''").fetchone():
            raise DomainError("configuration_applying", "正在应用配置，暂不接受新任务", status=409)
        row = conn.execute("SELECT * FROM jobs WHERE dedupe_key=?", (key,)).fetchone()
        if row:
            if decode(row)["payload"] != payload:
                raise DomainError("idempotency_conflict", "重复请求标识对应不同内容", status=409)
            return decode(row)
        uid, stamp = "job_" + uuid4().hex, now()
        conn.execute("INSERT INTO jobs(id,kind,dedupe_key,status,stage,payload_json,created_at,updated_at) VALUES(?,?,?,'queued','queued',?,?,?)",
            (uid, kind, key, json_text(payload), stamp, stamp))
        return decode(conn.execute("SELECT * FROM jobs WHERE id=?", (uid,)).fetchone())

    def enqueue(self, kind, payload, key=None):
        with self.connect(write=True) as conn:
            return self._enqueue(conn, kind, payload, key or kind + ":" + digest(payload))

    def job(self, job_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise DomainError("not_found", "找不到此任务", status=404)
        return decode(row)

    def jobs(self):
        with self.connect() as conn:
            return [decode(row) for row in conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100")]

    def claim(self):
        with self.connect(write=True) as conn:
            if conn.execute("SELECT 1 FROM state WHERE key='maintenance' AND value<>''").fetchone():
                return None
            row = conn.execute("SELECT * FROM jobs WHERE status='queued' AND kind NOT IN ('diagnostics','tunnel') ORDER BY created_at,id LIMIT 1").fetchone()
            if not row:
                return None
            conn.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=?", (now(), row["id"]))
        return self.job(row["id"])

    def progress(self, job_id, stage, result=None, status="running", error=None):
        with self.connect(write=True) as conn:
            previous = conn.execute("SELECT stage,status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not previous:
                raise DomainError("not_found", "找不到此任务", status=404)
            if previous["stage"] != stage or previous["status"] != status or error:
                conn.execute("INSERT INTO job_events(job_id,stage,status,error_json,created_at) VALUES(?,?,?,?,?)",
                    (job_id, stage, status, json_text(error or {}), now()))
            conn.execute("UPDATE jobs SET stage=?,status=?,updated_at=?,error_json=? WHERE id=?",
                (stage, status, now(), json_text(error or {}), job_id))
            if result is not None:
                conn.execute("UPDATE jobs SET result_json=? WHERE id=?", (json_text(result), job_id))

    def events(self, job_id):
        self.job(job_id)
        with self.connect() as conn:
            return [decode(row) for row in conn.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY id", (job_id,))]

    def note_event(self, job_id, stage, detail):
        with self.connect(write=True) as conn:
            conn.execute("INSERT INTO job_events(job_id,stage,status,error_json,created_at) VALUES(?,?,'info',?,?)",
                         (job_id, stage, json_text(detail), now()))

    def set_state(self, key, value):
        with self.connect(write=True) as conn:
            conn.execute("INSERT OR REPLACE INTO state VALUES(?,?)", (key, value))

    def begin_maintenance(self, identity):
        with self.connect(write=True) as conn:
            if conn.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') LIMIT 1").fetchone():
                raise DomainError("jobs_busy", "有排队或运行中的任务，请待完成后应用配置", status=409)
            if conn.execute("SELECT 1 FROM state WHERE key='maintenance' AND value<>''").fetchone():
                raise DomainError("configuration_applying", "已有配置应用操作进行中", status=409)
            conn.execute("INSERT OR REPLACE INTO state VALUES('maintenance',?)", (identity,))

    def recover(self, include_controls=True):
        # 仅在取得操作系统独占 worker 锁后调用。
        with self.connect(write=True) as conn:
            condition = "status='running'" + ("" if include_controls else " AND kind NOT IN ('diagnostics','tunnel')")
            conn.execute("INSERT INTO job_events(job_id,stage,status,error_json,created_at) SELECT id,stage,'interrupted','{}',? FROM jobs WHERE " + condition, (now(),))
            conn.execute("UPDATE jobs SET status='interrupted',updated_at=? WHERE " + condition, (now(),))

    def interrupt_controls(self):
        with self.connect(write=True) as conn:
            conn.execute("UPDATE jobs SET status='interrupted',updated_at=? WHERE kind IN ('diagnostics','tunnel') AND status IN ('queued','running')", (now(),))

    def retry(self, job_id):
        job = self.job(job_id)
        if job["status"] not in {"failed", "interrupted", "needs_attention"}:
            raise DomainError("job_conflict", "此任务无需恢复", status=409)
        if job["kind"] == "assessment" and job["result"].get("submitted") and not job["result"].get("run_id"):
            raise DomainError("ambiguous_run", "已发起工作流但未取得运行 ID，须在 Dify 对账；禁止自动重发", status=409)
        self.progress(job_id, job["stage"], status="queued")
        return self.job(job_id)

    def state(self, key, default=""):
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def heartbeat(self):
        with self.connect(write=True) as conn:
            conn.execute("INSERT OR REPLACE INTO state VALUES('worker_heartbeat',?)", (now(),))

    def releases(self):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM releases ORDER BY published_at DESC")]

    def publish(self, job_id, snapshot_id, clause_count, standard_count, parent):
        with self.connect(write=True) as conn:
            if conn.execute("SELECT 1 FROM releases WHERE snapshot_id=?", (snapshot_id,)).fetchone():
                return
            row = conn.execute("SELECT value FROM state WHERE key='current_snapshot'").fetchone()
            if (row[0] if row else "") != parent:
                raise DomainError("release_conflict", "基础知识版本已变化，请重新预览累积版本", status=409)
            conn.execute("INSERT INTO releases VALUES(?,?,?,?,?)", (snapshot_id, job_id, now(), clause_count, standard_count))
            conn.execute("INSERT OR REPLACE INTO state VALUES('current_snapshot',?)", (snapshot_id,))
