import json
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from app.errors import DomainError
from app.repository import digest, json_text, sha256
from app.schemas import ClauseRecord, ID
from ingestion.mineru_adapter import file_sha256, local_path
from pydantic import TypeAdapter

STANDARD_FIELDS = ("standard_uid", "standard_code", "standard_name", "edition", "scope", "standard_status",
                   "status_verified_at", "status_source", "source_file_sha256", "source_archive_path",
                   "source_page_count", "parser_version", "full_document_covered", "is_test_fixture")


def standard_identity(code: str, edition: str):
    return "std_" + digest([code, edition])[:32]


def clause_identity(standard_uid: str, edition: str, clause_path: list[str]):
    return "cl_" + digest([standard_uid, edition, clause_path])[:32]


def read_records(input_file: Path):
    return [ClauseRecord.model_validate_json(line) for line in input_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def import_reviewed(input_file, snapshot_id, repo, settings, *, mode="manual"):
    if mode not in {"manual", "automated"}:
        raise DomainError("input_error", "未知入库模式")
    TypeAdapter(ID).validate_python(snapshot_id)
    records = read_records(input_file)
    if not records:
        raise DomainError("review_required", "批准文件为空", "input")
    documents, standards, clauses = {}, {}, {}
    for record in records:
        if record.is_test_fixture and settings.app_env != "test":
            raise DomainError("test_fixture_forbidden", "真实知识库不接收测试数据")
        machine = mode == "automated" and record.content_review_status == "machine_checked"
        required = ("standard_code", "standard_name", "edition", "scope") if machine else ("standard_code", "standard_name", "edition", "scope", "reviewed_by", "reviewed_at",
                    "status_verified_at", "status_source")
        if any(not getattr(record, key).strip() for key in required) or (not machine and record.standard_status == "unknown"):
            raise DomainError("review_required", "需填写标准元数据、状态来源和人工复核记录")
        for stamp in (() if machine else (record.reviewed_at, record.status_verified_at)):
            try:
                datetime.fromisoformat(stamp)
            except ValueError as error:
                raise DomainError("review_required", "复核日期必须为 ISO 8601") from error
        if machine:
            from app.portal.automated import validate_machine_record
            validate_machine_record(record.model_dump())
        elif (record.content_review_status != "approved" or not record.evidence_complete or
            record.boundary_status != "confirmed" or record.review_issues or not record.full_document_covered):
            raise DomainError("review_required", "仅接受完整页覆盖、边界明确且无未解决问题的人工批准条款")
        if record.clause_no != record.clause_path[-1]:
            raise DomainError("clause_boundary_error", "条款号必须等于完整路径最后一项")
        if record.snapshot_id and record.snapshot_id != snapshot_id:
            raise DomainError("snapshot_conflict", "文件快照 ID 与命令不一致")
        if any(span.pdf_page_index >= record.source_page_count for span in record.source_spans):
            raise DomainError("parse_error", "原文件页位置越界")
        sid = standard_identity(record.standard_code, record.edition)
        cid = clause_identity(sid, record.edition, record.clause_path)
        if (record.standard_uid and record.standard_uid != sid) or (record.clause_uid and record.clause_uid != cid):
            raise DomainError("identity_mismatch", "标准或条款 UID 不符合确定性身份规则")
        text_hash = sha256(record.text_verbatim)
        if record.content_sha256 and record.content_sha256 != text_hash:
            raise DomainError("content_hash_mismatch", "批准原文与提供的哈希不一致")
        if not record.is_test_fixture:
            source = local_path(settings.data_root, record.source_archive_path)
            if source not in documents:
                documents[source] = (file_sha256(source), len(PdfReader(source).pages))
            if documents[source] != (record.source_file_sha256, record.source_page_count):
                raise DomainError("source_hash_mismatch", "归档 PDF 哈希或页数不一致")
            if set(record.asset_refs) != set(record.asset_sha256):
                raise DomainError("parse_error", "图表资产哈希不完整")
            for ref in record.asset_refs:
                if file_sha256(local_path(settings.data_root, ref)) != record.asset_sha256[ref]:
                    raise DomainError("parse_error", "图表资产已变化：" + ref)
        value = record.model_dump()
        value.update(snapshot_id=snapshot_id, standard_uid=sid, clause_uid=cid, content_sha256=text_hash)
        if cid in clauses:
            raise DomainError("clause_boundary_error", "批准文件包含重复条款身份")
        clauses[cid] = value
        metadata = {key: value[key] for key in STANDARD_FIELDS}
        if sid in standards and standards[sid] != metadata:
            raise DomainError("standard_metadata_conflict", "同一标准版本的元数据不一致")
        standards[sid] = metadata

    def check_context(uid, ancestors):
        if uid in ancestors:
            raise DomainError("incomplete_evidence", "必要上下文关系存在循环")
        for dependency in clauses[uid]["context_clause_uids"]:
            if dependency not in clauses:
                raise DomainError("incomplete_evidence", "必要上下文条款未纳入本快照")
            check_context(dependency, ancestors | {uid})
    for uid in clauses:
        check_context(uid, set())
    with repo.connect(write=True) as conn:
        existing = conn.execute("SELECT clause_uid, record_json FROM clauses WHERE snapshot_id=?", (snapshot_id,)).fetchall()
        if existing:
            if {row[0]: json.loads(row[1]) for row in existing} != clauses:
                raise DomainError("snapshot_immutable", "既有快照不可修改；请创建新快照", "snapshot", 409)
            return {"snapshot_id": snapshot_id, "status": "unchanged", "clauses": len(clauses)}
        for uid, metadata in standards.items():
            conn.execute("INSERT INTO standard_versions(snapshot_id, standard_uid, metadata_json) VALUES (?, ?, ?)",
                         (snapshot_id, uid, json_text(metadata)))
        for uid, record in clauses.items():
            conn.execute("INSERT INTO clauses VALUES (?, ?, ?, ?, ?)",
                         (snapshot_id, uid, record["standard_uid"], record["content_sha256"], json_text(record)))
    return {"snapshot_id": snapshot_id, "status": "candidate", "clauses": len(clauses), "standards": len(standards)}
