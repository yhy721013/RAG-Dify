import re

from app.errors import DomainError
from app.schemas import FinalizeRequest


def validate_findings(draft: FinalizeRequest, context: dict):
    checks = {item["check_id"]: item for item in context["checks"]}
    source_checks = {item["check_id"]: item for item in context["request"]["checks"]}
    evidence = {item["evidence_id"]: item for item in context["evidence"]}
    ids = [item.check_id for item in draft.findings]
    if len(ids) != len(set(ids)) or set(ids) != set(checks):
        raise DomainError("check_coverage_error", "结果必须恰好覆盖本次全部检查项", "findings.check_id")
    for item in draft.findings:
        field = "findings." + item.check_id
        if (context["request"].get("workflow_version") or "").startswith("portal-v3-dynamic"):
            for name in ("risk_description", "applicability_reason", "recommendation"):
                text = getattr(item, name)
                if len(re.sub(r"\s", "", text)) < 8 or len(set(text.strip())) < 4:
                    raise DomainError("model_output_incomplete", "模型正文残缺，不能保存为成功报告", field + "." + name)

        if len(set(item.observation_ids)) != len(item.observation_ids) or not set(item.observation_ids) <= set(source_checks[item.check_id]["observation_ids"]):
            raise DomainError("observation_out_of_scope", "观察不属于该检查项", field + ".observation_ids")
        if len(set(item.evidence_ids)) != len(item.evidence_ids) or not set(item.evidence_ids) <= set(checks[item.check_id]["allowed_evidence_ids"]):
            raise DomainError("evidence_out_of_scope", "证据不属于该检查项的允许集合", field + ".evidence_ids")
        if not item.evidence_ids and item.status != "insufficient_evidence":
            raise DomainError("missing_evidence", "无标准证据时必须标记 insufficient_evidence", field + ".status")
        if item.status == "evidence_supported_risk" and any(not evidence[uid]["evidence_complete"] for uid in item.evidence_ids):
            raise DomainError("incomplete_evidence", "不完整证据不能支持确定风险状态", field + ".status")
    return {"validation_passed": True, "checked_findings": len(ids), "review_status": "pending_review"}
