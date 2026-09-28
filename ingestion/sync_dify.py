import json
import os
import re
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from app.errors import DomainError
from app.repository import digest, json_text, now, sha256

BOUNDARY = "__RAG_CHUNK_BOUNDARY__"
MARKER = re.compile(r"^CHUNK_UID: ([A-Za-z0-9_]+)$", re.MULTILINE)


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextmanager
def sync_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as lock:
            lock.write(json_text({"pid": os.getpid(), "created_at": now()}))
    except FileExistsError as error:
        raise DomainError("sync_locked", "同步锁已存在；确认原进程退出后再人工清理锁文件", status=409) from error
    try:
        yield
    finally:
        path.unlink()


def manifest_path(settings, snapshot_id):
    # 不把用户输入拼接成文件系统路径。
    return settings.data_root / "manifests" / ("sync_" + digest([snapshot_id, settings.dataset_id]) + ".json")


def split_text(text, limit=500):
    text = text.strip()
    while text:
        end = min(limit, len(text))
        if end < len(text):
            positions = [match.end() for match in re.finditer(r"[\n。；]", text[:end])]
            if positions and positions[-1] >= limit // 2:
                end = positions[-1]
        yield text[:end]
        text = text[end:]


def chunks_for(clauses, *, allow_machine=False):
    chunks = {}
    for clause in sorted(clauses, key=lambda item: item["clause_path"]):
        machine = allow_machine and clause["content_review_status"] == "machine_checked"
        if machine:
            from app.portal.automated import validate_machine_record
            validate_machine_record(clause)
        if (not machine and (clause["content_review_status"] != "approved" or not clause["evidence_complete"])) or sha256(clause["text_verbatim"]) != clause["content_sha256"]:
            raise DomainError("review_required", "同步只允许未篡改的批准条款")
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>", "", clause["text_verbatim"], flags=re.IGNORECASE)
        if not text.strip():
            raise DomainError("mapping_error", "批准条款没有可索引文本：" + clause["clause_uid"], "text_verbatim")
        if BOUNDARY in text or re.search(r"^(CHUNK_UID|CLAUSE_UID):", text, re.MULTILINE):
            raise DomainError("mapping_error", "原文包含保留分隔符或标识行，需人工处理索引格式")
        for index, fragment in enumerate(split_text(text)):
            uid = "chunk_" + digest([clause["clause_uid"], index, fragment])[:32]
            content = (f"CHUNK_UID: {uid}\nCLAUSE_UID: {clause['clause_uid']}\n"
                       f"STANDARD: {clause['standard_code']} {clause['standard_name']}\n"
                       f"CLAUSE_PATH: {' / '.join(clause['clause_path'])}\nCONTENT:\n{fragment}")
            chunks[uid] = {"chunk_uid": uid, "clause_uid": clause["clause_uid"], "content": content,
                           "index_text_sha256": sha256(content)}
    if not chunks:
        raise DomainError("mapping_error", "没有可索引条款文本")
    return chunks


def verify_segments(segments, chunks, snapshot_id, dataset_id, document_id):
    seen, mappings = set(), []
    for segment in segments:
        content = segment.get("content")
        if (not isinstance(content, str) or segment.get("document_id") != document_id or
            segment.get("enabled") is not True or segment.get("status") != "completed"):
            raise DomainError("mapping_error", "分块不可用或文档身份不一致", status=502)
        normalized_content = content.replace("\r\n", "\n").strip()
        identifiers = MARKER.findall(normalized_content)
        if len(identifiers) != 1 or identifiers[0] not in chunks or identifiers[0] in seen:
            raise DomainError("mapping_error", "分块合并、重复、缺少标识或出现未知标识", status=502)
        uid = identifiers[0]
        # 只容忍首尾空白与 CRLF 差异，条款正文变化必须阻止发布。
        expected = chunks[uid]["content"].replace("\r\n", "\n").strip()
        if normalized_content != expected:
            raise DomainError("mapping_error", "实际分块内容与预期片段不一致", status=502)
        seen.add(uid)
        mappings.append({"snapshot_id": snapshot_id, "dataset_id": dataset_id, "document_id": document_id,
                         "segment_id": segment["id"], "chunk_uid": uid, "clause_uid": chunks[uid]["clause_uid"],
                         "index_text_sha256": sha256(content)})
    if seen != set(chunks):
        raise DomainError("mapping_error", "预期片段未被全部覆盖", status=502)
    return mappings


def mapping_digest(repo, snapshot_id, dataset_id):
    with repo.connect() as conn:
        rows = conn.execute("SELECT * FROM dify_segments WHERE snapshot_id=? AND dataset_id=? ORDER BY chunk_uid",
                            (snapshot_id, dataset_id)).fetchall()
    return digest([dict(row) for row in rows])


def sync_snapshot(snapshot_id, repo, settings, client):
    clauses = repo.all_clauses(snapshot_id)
    if not clauses:
        raise DomainError("snapshot_not_found", "不存在已批准候选快照", "snapshot", 404)
    if settings.app_env != "test" and any(item["is_test_fixture"] for item in clauses):
        raise DomainError("test_fixture_forbidden", "真实 Dify 不接收测试条款")
    path = manifest_path(settings, snapshot_id)
    lock = settings.data_root / "manifests" / ("dataset_" + digest([settings.dify_base_url, settings.dataset_id]) + ".lock")
    with sync_lock(lock):
        with repo.connect() as conn:
            collision = conn.execute("SELECT 1 FROM dify_segments WHERE dataset_id=? AND snapshot_id<>? LIMIT 1",
                                     (settings.dataset_id, snapshot_id)).fetchone()
        if collision and not settings.partitioned_dataset:
            raise DomainError("dataset_snapshot_conflict", "每个候选快照必须使用独立知识库", status=409)
        dataset = client.dataset()
        origin = {"base_url": settings.dify_base_url.rstrip("/"), "dataset_id": settings.dataset_id,
                  "snapshot_id": snapshot_id, "snapshot_sha256": digest(clauses), "provenance": client.provenance}
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"origin": origin, "documents": {}}
        if state["origin"] != origin:
            raise DomainError("sync_conflict", "同步清单的来源或快照内容已变化", status=409)
        field = client.snapshot_metadata() if settings.partitioned_dataset else None
        if state.get("metadata_field") and state["metadata_field"] != field:
            raise DomainError("metadata_error", "已登记的知识版本字段已变化", status=409)
        if field:
            state["metadata_field"] = field
        groups = defaultdict(list)
        for clause in clauses:
            groups[clause["standard_uid"]].append(clause)
        all_mappings = []
        for standard_uid, group in sorted(groups.items()):
            chunks = chunks_for(group, allow_machine=settings.partitioned_dataset)
            text = ("\n" + BOUNDARY + "\n").join(item["content"] for item in chunks.values())
            content_hash = sha256(text)
            name = f"{snapshot_id}_{standard_uid}_{content_hash[:16]}"
            document = state["documents"].get(standard_uid)
            if document and document["import_sha256"] != content_hash:
                raise DomainError("sync_conflict", "已记录文档的导入内容发生变化", status=409)
            if not document or not document.get("document_id"):
                matches = [row for row in client.documents() if row["name"] == name]
                if len(matches) > 1:
                    raise DomainError("ambiguous_creation", "发现重复同名文档，需人工对账", status=409)
                if matches:
                    document = {"name": name, "import_sha256": content_hash, "document_id": matches[0]["id"], "status": "reconciled"}
                elif document:
                    raise DomainError("ambiguous_creation", "上次创建结果不明，禁止自动重新创建；请核查同步清单", status=409)
                else:
                    document = {"name": name, "import_sha256": content_hash, "status": "creation_pending"}
                    state["documents"][standard_uid] = document
                    atomic_json(path, state)  # 发出创建请求前持久化意图。
                    payload = {"name": name, "text": text, "doc_form": "text_model", "doc_language": "Chinese",
                               "indexing_technique": "high_quality", "retrieval_model": client.retrieval_model(dataset),
                               "process_rule": {"mode": "custom", "rules": {"pre_processing_rules": [],
                                   "segmentation": {"separator": BOUNDARY, "max_tokens": 1000, "chunk_overlap": 0}}}}
                    document.update(client.create_document(payload))
                    document["status"] = "indexing"
                state["documents"][standard_uid] = document
                atomic_json(path, state)
            client.wait_index(document["document_id"], document.get("batch"))
            if field:
                client.bind_document_snapshot(document["document_id"], snapshot_id, field,
                                              allow_initial=document["status"] != "verified")
            mappings = verify_segments(client.segments(document["document_id"]), chunks, snapshot_id,
                                       settings.dataset_id, document["document_id"])
            all_mappings.extend(mappings)
            document.update(status="verified", chunk_count=len(chunks))
            atomic_json(path, state)
        # 禁止无关文档污染当前快照专用知识库。
        actual_docs = {item["id"] for item in client.documents()}
        expected_docs = {item["document_id"] for item in state["documents"].values()}
        if field:
            expected_docs |= verify_historical_partitions(snapshot_id, repo, settings, client, field)
        if actual_docs != expected_docs:
            raise DomainError("mapping_error", "知识库包含未纳入快照的文档或缺少预期文档", status=409)
        with repo.connect(write=True) as conn:
            existing = conn.execute("SELECT * FROM dify_segments WHERE snapshot_id=? AND dataset_id=? ORDER BY chunk_uid",
                                    (snapshot_id, settings.dataset_id)).fetchall()
            expected = sorted(all_mappings, key=lambda row: row["chunk_uid"])
            if existing and [dict(row) for row in existing] != expected:
                raise DomainError("mapping_error", "已保存的映射发生漂移，需要新快照", status=409)
            if not existing:
                conn.executemany("INSERT INTO dify_segments VALUES (:snapshot_id, :dataset_id, :document_id, :segment_id, :chunk_uid, :clause_uid, :index_text_sha256)", expected)
        state.update(status="verified", verified_at=now(), mapping_sha256=mapping_digest(repo, snapshot_id, settings.dataset_id),
                     retrieval_model=client.retrieval_model(dataset))
        if field:
            state["retrieval_model"]["metadata_filtering_conditions"] = client.snapshot_filter(snapshot_id)
        atomic_json(path, state)
        return {"snapshot_id": snapshot_id, "status": "verified", "documents": len(groups), "chunks": len(all_mappings),
                "provenance": client.provenance}


def verify_historical_partitions(snapshot_id, repo, settings, client, field):
    """只接纳在本地登记且逐块可验证的历史分区；不忽略外来文档。"""
    with repo.connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM dify_segments WHERE dataset_id=? AND snapshot_id<>? ORDER BY snapshot_id,document_id,chunk_uid",
                (settings.dataset_id, snapshot_id))]
    groups = defaultdict(list)
    for row in rows:
        groups[(row["snapshot_id"], row["document_id"])].append(row)
    for (historical_id, document_id), mappings in groups.items():
        client.bind_document_snapshot(document_id, historical_id, field)
        clauses = [repo.clause(historical_id, uid) for uid in sorted({row["clause_uid"] for row in mappings})]
        if any(row is None for row in clauses):
            raise DomainError("mapping_error", "历史分区缺少已登记条款")
        actual = verify_segments(client.segments(document_id), chunks_for(clauses, allow_machine=settings.partitioned_dataset), historical_id, settings.dataset_id, document_id)
        if sorted(actual, key=lambda row: row["chunk_uid"]) != sorted(mappings, key=lambda row: row["chunk_uid"]):
            raise DomainError("mapping_error", "历史分区的条款映射发生漂移", status=409)
    return {document_id for _, document_id in groups}


def activate_snapshot(snapshot_id, repo, settings, client):
    from evals.evaluate_retrieval import evaluation_path
    path = evaluation_path(settings, snapshot_id)
    if not path.is_file():
        raise DomainError("activation_blocked", "缺少本快照的检索评测记录", status=409)
    evaluation = json.loads(path.read_text(encoding="utf-8"))
    if any(r["content_review_status"] == "machine_checked" for r in repo.all_clauses(snapshot_id)):
        if not settings.partitioned_dataset or evaluation.get("evaluation_kind") != "automated_smoke":
            raise DomainError("activation_blocked", "机器条款只能由门户自动模式及自动检索检查发布", status=409)
    if not evaluation.get("passed") or (settings.app_env != "test" and evaluation.get("provenance") != "live_service_api"):
        raise DomainError("activation_blocked", "真实检索评测未通过；模拟结果不得用于业务发布", status=409)
    if settings.partitioned_dataset and evaluation.get("snapshot_filter") != client.snapshot_filter(snapshot_id):
        raise DomainError("activation_blocked", "缺少本知识版本的过滤检索验收记录", status=409)
    sync_snapshot(snapshot_id, repo, settings, client)  # 发布前重新回读真实分块。
    if (evaluation.get("snapshot_sha256") != digest(repo.all_clauses(snapshot_id)) or
        evaluation.get("mapping_sha256") != mapping_digest(repo, snapshot_id, settings.dataset_id) or
        evaluation.get("dataset_id") != settings.dataset_id or
        evaluation.get("base_url") != settings.dify_base_url.rstrip("/")):
        raise DomainError("activation_blocked", "检索评测已经过期或不属于当前数据源", status=409)
    with repo.connect(write=True) as conn:
        conn.execute("UPDATE standard_versions SET snapshot_state='active' WHERE snapshot_id=?", (snapshot_id,))
    return {"snapshot_id": snapshot_id, "status": "active", "next_step": "设置 ACTIVE_SNAPSHOT_ID 并重启 evidence-api"}
