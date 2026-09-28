PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS standard_versions (
    snapshot_id TEXT NOT NULL,
    standard_uid TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    snapshot_state TEXT NOT NULL DEFAULT 'candidate' CHECK(snapshot_state IN ('candidate', 'active')),
    PRIMARY KEY (snapshot_id, standard_uid)
);
CREATE TABLE IF NOT EXISTS clauses (
    snapshot_id TEXT NOT NULL,
    clause_uid TEXT NOT NULL,
    standard_uid TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, clause_uid),
    FOREIGN KEY (snapshot_id, standard_uid) REFERENCES standard_versions(snapshot_id, standard_uid)
);
CREATE TABLE IF NOT EXISTS dify_segments (
    snapshot_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    chunk_uid TEXT NOT NULL,
    clause_uid TEXT NOT NULL,
    index_text_sha256 TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, dataset_id, document_id, segment_id),
    UNIQUE (snapshot_id, dataset_id, chunk_uid),
    FOREIGN KEY (snapshot_id, clause_uid) REFERENCES clauses(snapshot_id, clause_uid)
);
CREATE TABLE IF NOT EXISTS evidence_contexts (
    context_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    request_sha256 TEXT NOT NULL,
    owner TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    context_id TEXT NOT NULL UNIQUE REFERENCES evidence_contexts(context_id),
    draft_sha256 TEXT NOT NULL,
    owner TEXT NOT NULL,
    report_json TEXT NOT NULL,
    markdown TEXT NOT NULL,
    validation_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
PRAGMA user_version = 1;
