from uuid import uuid4

from app.errors import DomainError
from app.repository import sha256
from app.schemas import PrepareRequest


def prepare(request: PrepareRequest, repo, settings, owner):
    # 新增可选追溯字段不能改变既有 A～C 请求的幂等哈希。
    request_data = request.model_dump(exclude_none=True)
    existing = repo.cached_context(request_data, owner)
    if existing:
        return existing
    if ((not settings.published_snapshots and request.snapshot_id != settings.active_snapshot_id)
        or not repo.snapshot_active(request.snapshot_id)):
        raise DomainError("snapshot_not_allowed", "请求的快照未激活或不在允许集合", "snapshot_id", 409)
    if len(request.image_manifest) > settings.max_images or len(request.checks) > settings.max_checks:
        raise DomainError("limit_exceeded", "超过管理员配置的输入上限", "checks")

    def verified(clause):
        if clause["is_test_fixture"] and settings.app_env != "test":
            raise DomainError("test_fixture_forbidden", "真实评估禁止使用测试条款", "snapshot_id", 409)
        if clause["content_review_status"] != "approved" or sha256(clause["text_verbatim"]) != clause["content_sha256"]:
            raise DomainError("mapping_error", "条款未复核或原文哈希异常", "hits", 502)

    def bundle(clause):
        verified(clause)
        dependencies, issues, visited = [], [], {clause["clause_uid"]}

        def visit(item, ancestors):
            for uid in item["context_clause_uids"]:
                if uid in ancestors:
                    issues.append("context_cycle:" + uid)
                    continue
                if uid in visited:
                    continue
                visited.add(uid)
                context = repo.clause(request.snapshot_id, uid)
                if context is None:
                    issues.append("missing_context:" + uid)
                    continue
                verified(context)
                dependencies.append(context)
                visit(context, ancestors | {uid})

        visit(clause, {clause["clause_uid"]})
        complete = not issues and all(item["evidence_complete"] for item in [clause, *dependencies])
        return {**clause, "evidence_id": "ev_" + uuid4().hex, "context_clauses": dependencies,
                "evidence_complete": complete, "completeness_issues": issues,
                "applicability_context": clause["scope"]}

    payload = {"context_id": "ctx_" + uuid4().hex, "request": request_data,
               "snapshot_id": request.snapshot_id, "checks": [], "evidence": []}
    by_clause, used_chars = {}, 0
    for check in request.checks:
        allowed, excluded, seen = [], [], set()
        for hit in check.hits:
            if hit.dataset_id != settings.dataset_id or not settings.dataset_id:
                raise DomainError("dataset_not_allowed", "检索来源不在管理员允许集合", "hits.dataset_id", 403)
            clause = repo.mapped_clause(request.snapshot_id, hit.model_dump())
            verified(clause)
            uid = clause["clause_uid"]
            if uid in seen:
                continue
            seen.add(uid)
            if len(allowed) >= settings.max_evidence_per_check:
                excluded.append({"clause_uid": uid, "reason": "max_evidence_per_check"})
                continue
            evidence = by_clause.get(uid) or bundle(clause)
            size = len(evidence["text_verbatim"]) + sum(len(item["text_verbatim"]) for item in evidence["context_clauses"])
            if uid not in by_clause and used_chars + size > settings.max_evidence_text_chars:
                excluded.append({"clause_uid": uid, "reason": "text_budget_exceeded"})
                continue
            if uid not in by_clause:
                by_clause[uid] = evidence
                payload["evidence"].append(evidence)
                used_chars += size
            allowed.append(evidence["evidence_id"])
        payload["checks"].append({"check_id": check.check_id,
                                  "retrieval_status": "matched" if check.hits else "no_match",
                                  "allowed_evidence_ids": allowed, "excluded_evidence": excluded})
    return repo.save_context(request_data, payload, owner)
