import io
import json
import zipfile

from app.portal.setup import fingerprint
from app.repository import now
from app.safe_diagnostics import public_error, scrub
from ingestion.mineru_adapter import local_path


def tail(path, limit=24000, secrets=()):
    if not path.is_file():
        return "日志文件尚未产生。"
    with path.open("rb") as stream:
        overlap = max((len(value.encode("utf-8")) for value in secrets if value), default=0) + 256
        stream.seek(max(0, path.stat().st_size - limit - overlap))
        content = stream.read(limit + overlap).decode("utf-8", errors="replace")
    return scrub(content, secrets, limit=len(content) + 1)[-limit:]


def task_diagnostics(job, store, config):
    secrets = config.secret_values()
    result = {"job_id": job["id"], "kind": job["kind"], "status": job["status"], "stage": job["stage"],
        "created_at": job["created_at"], "updated_at": job["updated_at"], "error": job["error"],
        "references": {k: job["result"].get(k) for k in ("run_id", "task_id", "workflow_id", "report_id", "snapshot_id") if job["result"].get(k)},
        "events": store.events(job["id"])[-100:], "logs": {}, "generated_at": now(), "config_fingerprint": fingerprint(config)}
    parse_directory = job["result"].get("parse_directory")
    if job["kind"] == "parse" and parse_directory:
        try:
            result["logs"]["parser.log"] = tail(local_path(config.data_root, parse_directory) / "parser.log", secrets=secrets)
        except Exception as error:
            result["logs"]["parser.log"] = public_error(error, secrets)
    if job["kind"] == "publish" and job["payload"].get("snapshot_id"):
        from evals.evaluate_retrieval import evaluation_path
        path = evaluation_path(config.evidence_settings(), job["payload"]["snapshot_id"])
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            # 不收录条款原文或问题全文，只返回得分、目标 ID 和错误。
            result["retrieval_evaluation"] = {k: data.get(k) for k in ("passed", "hit_at_5_rate", "error_count", "answerable_count", "cases")}
    return scrub(result, secrets, limit=24000)


def diagnostic_zip(data):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(data, ensure_ascii=False, indent=2))
        archive.writestr("README.txt", "此包只包含脱敏任务信息与有限日志，不含配置密钥、PDF、图片、数据库和报告正文。\n")
    return output.getvalue()
