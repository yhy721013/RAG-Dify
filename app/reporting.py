import html
import re
from uuid import uuid4

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.repository import now
from app.settings import ROOT
from app.validation import validate_findings


def safe_text(value):
    # 禁止输入生成链接、图片、HTML 或 Markdown 控制结构；JSON 保留逐字原文。
    escaped = html.escape(str(value), quote=True)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", escaped)


def finalize(draft, repo, owner):
    context = repo.context(draft.context_id, owner)
    validation = validate_findings(draft, context)
    evidence = {item["evidence_id"]: item for item in context["evidence"]}
    report = {"report_id": "rpt_" + uuid4().hex, "context_id": draft.context_id,
              "created_at": now(), "snapshot_id": context["snapshot_id"],
              "request": context["request"], "checks": context["checks"],
              "validation_passed": True, "review_status": "pending_review", "validation": validation,
              "findings": [{**item.model_dump(), "citations": [evidence[uid] for uid in item.evidence_ids]}
                           for item in draft.findings]}
    if context.get("knowledge_review_status"):
        report["knowledge_review_status"] = context["knowledge_review_status"]
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), undefined=StrictUndefined,
                      autoescape=False, keep_trailing_newline=True)
    env.filters["safe_text"] = safe_text
    report["markdown"] = env.get_template("report.md.j2").render(report=report)
    return repo.save_report(draft.model_dump(), report, owner)
