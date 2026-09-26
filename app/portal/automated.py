"""显式自动模式：规则检查不是人工批准，不修改原文档或复核记录。"""
from copy import deepcopy

from app.errors import DomainError
from app.repository import digest, sha256
from app.schemas import ClauseRecord
from app.portal import assistance, review

VERSION = "automated-rules-v1"
NOTICE = "未经人工复核；机器检查不确认原文正确性、标准现行状态或业务适用性。"
IDENTITY = {"standard_code", "standard_name", "edition", "scope"}
PENDING_FLAGS = {"text_review_required", "standard_metadata_required", "boundary_review_required",
                 "context_review_required", "human_review_required"}


def validate_machine_record(record):
    if (record["content_review_status"] != "machine_checked"
        or record["boundary_status"] != "machine_checked" or record["evidence_complete"]
        or record["reviewed_by"] or record["reviewed_at"] or not record["full_document_covered"]
        or not record["review_notes"].startswith(VERSION + ":")
        or "human_review_required" not in record["review_issues"]
        or set(record["review_issues"]) - PENDING_FLAGS
        or not assistance.NUMBER.fullmatch(record["clause_no"])):
        raise DomainError("machine_check_required", "机器条款缺少有效检查记录，或含未解决的来源/边界问题")


def preview(store, evidence, document_ids, root, metadata=None):
    metadata = metadata or {}
    if set(metadata) - set(document_ids):
        raise DomainError("input_error", "metadata 只能包含本次 document_ids")
    records, excluded, provenance = [], [], {}
    for uid in sorted(set(document_ids)):
        doc = deepcopy(store.document(uid))
        payload = doc["payload"]
        if not payload.get("candidates") or not payload.get("normalized"):
            raise DomainError("parse_required", "文档尚未完成解析", details={"document_id": uid})
        supplied = metadata.get(uid, {})
        if set(supplied) - IDENTITY or any(not isinstance(v, str) or not v.strip() for v in supplied.values()):
            raise DomainError("input_error", "自动元数据只接受非空 standard_code/standard_name/edition/scope")
        draft = assistance.metadata_draft(payload)
        values = {**draft["values"], **{k: v for k, v in payload.get("metadata", {}).items() if v}, **supplied}
        missing = sorted(k for k in IDENTITY if not values.get(k, "").strip())
        if missing:
            raise DomainError("metadata_required", "无法从解析结果确定标准身份/范围，请通过 metadata 文件补充", details={"document_id": uid, "missing": missing})
        provenance[uid] = {"rule": draft, "supplied": supplied, "revision": doc["revision"]}
        for item in payload["candidates"]:
            r = item["record"]
            # 已人工批准的内容保持原审核字段；不允许以自动元数据改写其身份。
            if r["content_review_status"] != "approved":
                r.update({k: values[k] for k in IDENTITY})
                review.identify(r)
            elif any(r[k] != v for k, v in supplied.items()):
                raise DomainError("review_required", "自动模式不能改写已有人工批准条款的元数据")
        analysis = assistance.analyze(doc, root)
        rows = {r["candidate_id"]: r for r in analysis["rows"]}
        for item in payload["candidates"]:
            r, row = item["record"], rows[item["id"]]
            reasons = [v["code"] for v in analysis["document_checks"] + row["issues"]]
            if r["boundary_status"] == "unknown": reasons.append("unknown_boundary")
            if r["content_review_status"] == "rejected": reasons.append("rejected")
            if r["content_review_status"] != "approved":
                reasons.extend(sorted(set(r["review_issues"]) - PENDING_FLAGS))
            if reasons:
                excluded.append({"document_id": uid, "candidate_id": item["id"], "reasons": sorted(set(reasons))})
                continue
            if r["content_review_status"] != "approved":
                r["context_clause_uids"] = sorted(set(r["context_clause_uids"]) | {v["clause_uid"] for v in row["suggested_context"]})
                r.update(content_review_status="machine_checked", boundary_status="machine_checked",
                         evidence_complete=False, reviewed_by="", reviewed_at="",
                         content_sha256=sha256(r["text_verbatim"]),
                         review_issues=sorted(set(r["review_issues"]) | {"human_review_required"}),
                         review_notes=VERSION + ": " + NOTICE + " " + r.get("review_notes", ""))
                validate_machine_record(r)
            records.append(ClauseRecord.model_validate(r).model_dump())
    if not records:
        raise DomainError("machine_check_required", "无可自动发布条款，未绕过疑点", details={"excluded": excluded})
    value = review.release_preview(store, evidence, document_ids, machine_records=records)
    value.pop("preview_hash")
    value.update(mode="automated", machine_check_version=VERSION, metadata_provenance=provenance,
                 excluded=excluded, notice=NOTICE)
    value["preview_hash"] = digest(value)
    return value


def smoke_cases(preview, snapshot):
    # 原文片段回查只验证索引和映射，不冒充人工标注的业务评测。
    selected, seen = [], set()
    for record in preview["records"]:
        if record["standard_uid"] not in seen:
            selected.append(record)
            seen.add(record["standard_uid"])
    if len(selected) > 100:
        raise DomainError("evaluation_input_error", "累计超过100个标准，请扩展自动检索采样预算后再发布")
    selected_uids = {r["clause_uid"] for r in selected}
    selected.extend(r for r in preview["records"] if r["clause_uid"] not in selected_uids)
    return [{"case_id": "smoke_" + digest(r["clause_uid"])[:16], "snapshot_id": snapshot,
             "query": r["text_verbatim"][:250], "expected_clause_uids": [r["clause_uid"]],
             "answerable": True, "generated_by": VERSION}
            for r in selected[:100]]
