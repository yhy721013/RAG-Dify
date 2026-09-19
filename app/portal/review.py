from copy import deepcopy
from datetime import datetime
from uuid import uuid4

from app.errors import DomainError
from app.repository import digest, now, sha256
from app.schemas import ClauseRecord
from ingestion.import_reviewed import clause_identity, standard_identity
from ingestion.mineru_adapter import file_sha256, local_path

METADATA = ("standard_code", "standard_name", "edition", "scope", "standard_status", "status_verified_at", "status_source")
EDITABLE = ("text_verbatim", "clause_no", "clause_path", "context_clause_uids", "review_notes")


def pending(record):
    record.update(content_review_status="pending", evidence_complete=False, reviewed_by="", reviewed_at="",
                  content_sha256="", boundary_status="pending")


def identify(record):
    sid = standard_identity(record["standard_code"], record["edition"])
    record.update(standard_uid=sid, clause_uid=clause_identity(sid, record["edition"], record["clause_path"]))


def invalidate_dependents(payload, changed_uid):
    affected = {changed_uid}
    while True:
        found = {item["record"]["clause_uid"] for item in payload["candidates"]
                 if set(item["record"]["context_clause_uids"]) & affected}
        if found <= affected:
            break
        affected |= found
    for item in payload["candidates"]:
        if item["record"]["clause_uid"] in affected:
            pending(item["record"])


def item_for(payload, candidate_id):
    for item in payload.get("candidates", []):
        if item["id"] == candidate_id:
            return item
    raise DomainError("not_found", "找不到此候选条款", status=404)


def blocks_for(payload):
    return {block["block_id"]: (page, block) for page in payload["normalized"]["pages"] for block in page["blocks"]}


def set_sources(payload, record, block_ids, root):
    blocks = blocks_for(payload)
    if not block_ids or len(set(block_ids)) != len(block_ids) or not set(block_ids) <= set(blocks):
        raise DomainError("invalid_source", "必须选择此 PDF 中真实存在且不重复的来源块")
    record["source_spans"], record["asset_refs"] = [], []
    for bid in block_ids:
        page, block = blocks[bid]
        record["source_spans"].append({"pdf_page_index": page["pdf_page_index"],
            "printed_page_label": page["printed_page_label"], "block_ids": [bid], "bbox": block["bbox"]})
        record["asset_refs"].extend(block["asset_refs"])
    record["asset_refs"] = sorted(set(record["asset_refs"]))
    record["asset_sha256"] = {ref: file_sha256(local_path(root, ref)) for ref in record["asset_refs"]
                              if local_path(root, ref).is_file()}


def update_metadata(payload, metadata):
    result = deepcopy(payload)
    if set(metadata) != set(METADATA) or any(not isinstance(v, str) or not v.strip() for v in metadata.values()):
        raise DomainError("review_required", "请完整填写标准身份、范围、状态与状态来源")
    if metadata["standard_status"] == "unknown":
        raise DomainError("review_required", "标准状态尚未核验")
    try:
        datetime.fromisoformat(metadata["status_verified_at"])
    except ValueError as error:
        raise DomainError("review_required", "状态核验时间须使用 ISO 日期") from error
    result["metadata"] = metadata
    for item in result["candidates"]:
        record = item["record"]
        if any(record.get(key) != val for key, val in metadata.items()):
            record.update(metadata)
            pending(record)
            identify(record)
    return result


def edit_candidate(payload, candidate_id, changes, block_ids, root):
    result = deepcopy(payload)
    record = item_for(result, candidate_id)["record"]
    previous_uid = record["clause_uid"]
    if set(changes) - set(EDITABLE):
        raise DomainError("invalid_edit", "禁止通过编辑接口改变批准状态或原始来源")
    record.update(changes)
    ClauseRecord.model_validate(record)
    if record["clause_no"] != record["clause_path"][-1]:
        raise DomainError("invalid_edit", "条款号须等于完整路径最后一级")
    set_sources(result, record, block_ids, root)
    pending(record)
    identify(record)
    invalidate_dependents(result, previous_uid)
    ClauseRecord.model_validate(record)
    return result


def approve(payload, candidate_id, actor, acknowledgements, root):
    result = deepcopy(payload)
    record = item_for(result, candidate_id)["record"]
    needed = {"text", "boundary", "context", "assets", "scope"}
    if not needed <= set(acknowledgements) or not actor.strip():
        raise DomainError("review_required", "请确认原文、边界、依赖、图表与标准范围，并填写复核人")
    if not result["normalized"]["full_document_covered"]:
        raise DomainError("incomplete_evidence", "原 PDF 页覆盖不完整，不能批准")
    blocks = blocks_for(result)
    selected = [bid for span in record["source_spans"] for bid in span["block_ids"]]
    structural = [issue for bid in selected for issue in blocks[bid][1]["review_issues"]
                  if issue == "visual_asset_unconfirmed" or issue.startswith(("missing_asset:", "unsafe_asset:", "unsupported_block_type:"))]
    if structural:
        raise DomainError("incomplete_evidence", "来源资产或解析结构不完整：" + "、".join(structural))
    if any(not record.get(key, "").strip() for key in METADATA) or record["standard_status"] == "unknown":
        raise DomainError("review_required", "请先保存标准元数据")
    if record["clause_no"].startswith("unassigned"):
        raise DomainError("clause_boundary_error", "请先明确条款号和边界")
    duplicates = [item for item in result["candidates"] if item["record"]["clause_path"] == record["clause_path"]]
    if len(duplicates) != 1:
        raise DomainError("clause_boundary_error", "候选中存在重复条款路径，请合并或修正编号")
    for ref in record["asset_refs"]:
        if not local_path(root, ref).is_file() or file_sha256(local_path(root, ref)) != record["asset_sha256"].get(ref):
            raise DomainError("incomplete_evidence", "图表缺失或内容变化")
    identify(record)
    record.update(content_review_status="approved", evidence_complete=True, boundary_status="confirmed",
                  review_issues=[], reviewed_by=actor.strip(), reviewed_at=now(), content_sha256=sha256(record["text_verbatim"]))
    ClauseRecord.model_validate(record)
    return result


def split_candidate(payload, candidate_id, offset):
    result = deepcopy(payload)
    item = item_for(result, candidate_id)
    invalidate_dependents(result, item["record"]["clause_uid"])
    text = item["record"]["text_verbatim"]
    if not 0 < offset < len(text) or not text[:offset].strip() or not text[offset:].strip():
        raise DomainError("invalid_edit", "拆分位置须在正文中间")
    other = deepcopy(item)
    other["id"] = "candidate_" + uuid4().hex
    item["record"]["text_verbatim"], other["record"]["text_verbatim"] = text[:offset], text[offset:]
    for row in (item, other):
        pending(row["record"])
        row["record"]["review_issues"] = ["split_boundary_and_source_review_required"]
    result["candidates"].insert(result["candidates"].index(item) + 1, other)
    return result


def merge_candidates(payload, candidate_ids, root):
    if len(set(candidate_ids)) != len(candidate_ids) or len(candidate_ids) < 2:
        raise DomainError("invalid_edit", "请至少选择两个不同候选")
    result = deepcopy(payload)
    items = [item_for(result, uid) for uid in candidate_ids]
    for item in items:
        invalidate_dependents(result, item["record"]["clause_uid"])
    first = items[0]["record"]
    first["text_verbatim"] = "\n".join(item["record"]["text_verbatim"] for item in items)
    bids = list(dict.fromkeys(bid for item in items for span in item["record"]["source_spans"] for bid in span["block_ids"]))
    set_sources(result, first, bids, root)
    first["context_clause_uids"] = list(dict.fromkeys(uid for item in items for uid in item["record"]["context_clause_uids"]))
    pending(first)
    first["review_issues"] = ["merged_boundary_and_context_review_required"]
    result["candidates"] = [item for item in result["candidates"] if item["id"] not in candidate_ids[1:]]
    return result


def release_preview(store, evidence_repo, document_ids):
    parent = store.state("current_snapshot")
    baseline = evidence_repo.all_clauses(parent) if parent else []
    records, pending_count, revisions = [], 0, {}
    for uid in sorted(set(document_ids)):
        doc = store.document(uid)
        revisions[uid] = doc["revision"]
        for item in doc["payload"].get("candidates", []):
            record = item["record"]
            if record["content_review_status"] == "approved":
                records.append(deepcopy(record))
            else:
                pending_count += 1
    if not records:
        raise DomainError("review_required", "所选标准尚无人工批准条款")
    incoming = {row["standard_uid"] for row in records}
    old = {row["standard_uid"] for row in baseline}
    replacements = sorted(incoming & old)
    combined = [*deepcopy([row for row in baseline if row["standard_uid"] not in incoming]), *records]
    for row in combined:
        row["snapshot_id"] = ""
    combined.sort(key=lambda row: row["clause_uid"])
    preview = {"parent": parent, "document_revisions": revisions, "records": combined,
               "pending_count": pending_count, "replacements": replacements,
               "clause_count": len(combined), "standard_count": len({row["standard_uid"] for row in combined})}
    preview["preview_hash"] = digest(preview)
    return preview
