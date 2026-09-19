import json
import math
import time
from pathlib import Path
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from app.errors import DomainError
from app.repository import digest, now
from app.schemas import ID, StrictModel
from ingestion.sync_dify import atomic_json, manifest_path, mapping_digest


class RetrievalCase(StrictModel):
    case_id: ID
    snapshot_id: ID
    query: Annotated[str, StringConstraints(min_length=1, max_length=250)]
    expected_clause_uids: list[ID] = Field(max_length=20)
    answerable: bool
    annotated_by: Annotated[str, StringConstraints(min_length=1)]
    annotated_at: Annotated[str, StringConstraints(min_length=1)]

    @model_validator(mode="after")
    def labels(self):
        if self.answerable != bool(self.expected_clause_uids):
            raise ValueError("可回答问题必须有目标条款；无答案问题不能指定目标条款")
        return self


def evaluation_path(settings, snapshot_id):
    return settings.data_root / "manifests" / ("retrieval_" + digest([snapshot_id, settings.dataset_id]) + ".json")


def evaluate(cases_path: Path, repo, settings, client, interval_seconds=0):
    if not math.isfinite(interval_seconds) or not 0 <= interval_seconds <= 60:
        raise DomainError("evaluation_input_error", "请求间隔须为 0～60 秒", "interval_seconds")
    cases = [RetrievalCase.model_validate_json(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cases or len({item.case_id for item in cases}) != len(cases) or len({item.snapshot_id for item in cases}) != 1:
        raise DomainError("evaluation_input_error", "需要同一快照的非空、无重复人工标注问题集")
    snapshot_id = cases[0].snapshot_id
    path = manifest_path(settings, snapshot_id)
    if not path.is_file():
        raise DomainError("snapshot_not_synced", "先执行 sync-dify")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    clauses = repo.all_clauses(snapshot_id)
    uids = {item["clause_uid"] for item in clauses}
    if manifest.get("status") != "verified" or manifest["origin"]["snapshot_sha256"] != digest(clauses):
        raise DomainError("snapshot_not_synced", "快照同步清单未通过或与当前内容不一致")
    if settings.partitioned_dataset and manifest["retrieval_model"].get("metadata_filtering_conditions") != client.snapshot_filter(snapshot_id):
        raise DomainError("metadata_error", "检索自检必须使用当前知识版本的固定过滤条件")
    mapping_hash = mapping_digest(repo, snapshot_id, settings.dataset_id)
    if manifest.get("mapping_sha256") != mapping_hash:
        raise DomainError("mapping_error", "映射与同步清单不一致")
    if any(not set(item.expected_clause_uids) <= uids for item in cases):
        raise DomainError("evaluation_input_error", "标注目标不属于本快照")
    rows = []
    for index, case in enumerate(cases):
        if index and interval_seconds:
            time.sleep(interval_seconds)
        try:
            hits = client.retrieve(case.query, manifest["retrieval_model"])
            mapped = [repo.mapped_clause(snapshot_id, hit)["clause_uid"] for hit in hits]
            found = list(dict.fromkeys(mapped[:5]))
            targets = set(case.expected_clause_uids)
            rows.append({"case_id": case.case_id, "answerable": case.answerable, "clause_uids": found,
                         "hit": bool(targets & set(found)), "all_targets_found": bool(targets) and targets <= set(found),
                         "no_answer_has_candidates": not case.answerable and bool(found)})
        except DomainError as error:
            rows.append({"case_id": case.case_id, "answerable": case.answerable, "error": error.detail()})
    answerable = [item for item in rows if item["answerable"]]
    unanswerable = [item for item in rows if not item["answerable"]]
    answerable_complete = bool(answerable) and all("error" not in item for item in answerable)
    unanswerable_complete = bool(unanswerable) and all("error" not in item for item in unanswerable)
    rate = sum(item["hit"] for item in answerable) / len(answerable) if answerable_complete else None
    complete_rate = sum(item["all_targets_found"] for item in answerable) / len(answerable) if answerable_complete else None
    errors = sum("error" in row for row in rows)
    result = {"snapshot_id": snapshot_id, "dataset_id": settings.dataset_id, "created_at": now(),
              "provenance": client.provenance, "base_url": settings.dify_base_url.rstrip("/"),
              "cases_sha256": digest([item.model_dump() for item in cases]), "snapshot_sha256": digest(clauses),
              "mapping_sha256": mapping_hash, "answerable_count": len(answerable), "error_count": errors,
              "request_interval_seconds": interval_seconds,
              "hit_at_5_rate": rate, "all_targets_recalled_rate": complete_rate,
              "unanswerable_count": len(unanswerable),
              "no_answer_candidate_rate": (sum(item["no_answer_has_candidates"] for item in unanswerable) / len(unanswerable)) if unanswerable_complete else None,
              "passed": bool(answerable) and errors == 0 and rate >= 0.9, "cases": rows,
              "limitation": "Top-5 命中率是检索排错指标；无答案的候选召回不等同报告误引，适用性和业务判断仍需人工复核。"}
    if settings.partitioned_dataset:
        result["snapshot_filter"] = client.snapshot_filter(snapshot_id)
    atomic_json(evaluation_path(settings, snapshot_id), result)
    return result
