PRAGMA user_version = 1;
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
    source_path TEXT NOT NULL, page_count INTEGER NOT NULL,
    status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, dedupe_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL, stage TEXT NOT NULL, payload_json TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '{}', error_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS releases (
    snapshot_id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE,
    published_at TEXT NOT NULL, clause_count INTEGER NOT NULL, standard_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_audit (
    id INTEGER PRIMARY KEY, document_id TEXT NOT NULL, revision INTEGER NOT NULL,
    action TEXT NOT NULL, actor TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
