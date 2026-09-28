import re

import httpx

from app.dify_client import contract_error
from app.errors import DomainError
from app.repository import Repository, sha256
from app.safe_diagnostics import scrub
from app.workflow_client import WorkflowClient
from ingestion.mineru_adapter import file_sha256, local_path


def verify_report(report, payload, run_id, uploaded):
    if (report.get("validation_passed") is not True or report.get("review_status") != "pending_review"
        or report.get("snapshot_id") != payload["snapshot_id"] or report.get("request", {}).get("request_id") != run_id):
        raise DomainError("report_identity_error", "保存报告的知识版本、请求或校验状态与任务不符", status=502)
    request = report["request"]
    for key, value in payload["inputs"].items():
        if request.get(key) != value:
            raise DomainError("report_identity_error", "报告设备与工况输入不一致", status=502)
    expected = [row["upload_file_id"] for row in uploaded]
    actual = [row["file_ref"] for row in request.get("image_manifest", [])]
    if actual != expected:
        raise DomainError("report_identity_error", "报告图片绑定与上传顺序不一致", status=502)
    if not isinstance(report.get("markdown"), str) or not report["markdown"]:
        raise contract_error("report.markdown")


def assess(job, store, config, client_factory=WorkflowClient):
    config.require_assessment()
    payload, result = job["payload"], dict(job["result"])
    user = "local-" + job["id"]
    if not any(row["snapshot_id"] == payload["snapshot_id"] for row in store.releases()):
        raise DomainError("snapshot_not_allowed", "本次固定的知识版本尚未发布")
    with client_factory(config.dify_base_url, config.workflow_api_key) as client:
        client.on_event = lambda event: store.note_event(job["id"], "workflow_node", scrub(event, config.secret_values()))
        if result.get("run_id"):
            store.progress(job["id"], "reconciling", result)
            finished = client.reconcile(result["run_id"], store.heartbeat)
        elif result.get("submitted"):
            raise DomainError("ambiguous_run", "已提交但没有运行 ID，须到 Dify 对账后处理；禁止自动再次运行")
        else:
            uploaded = result.setdefault("uploaded", [])
            store.progress(job["id"], "uploading", result)
            for info in payload["images"][len(uploaded):]:
                path = local_path(config.data_root, info["path"])
                if file_sha256(path) != info["sha256"]:
                    raise DomainError("image_changed", "归档设备图片发生变化")
                uploaded.append(client.upload(path, info["mime_type"], user))
                store.progress(job["id"], "uploading", result)
            result["submitted"] = True
            store.progress(job["id"], "workflow", result)

            def started(ids):
                if result.get("run_id") and ids["run_id"] != result["run_id"]:
                    raise DomainError("workflow_identity_error", "同一流出现不同运行 ID")
                result.update({key: value for key, value in ids.items() if value})
                store.progress(job["id"], "workflow", result)

            try:
                finished = client.run({**payload["inputs"], "snapshot_id": payload["snapshot_id"], "images": uploaded}, user, started)
            except DomainError as error:
                if error.code == "workflow_rejected":
                    result["submitted"] = False
                    store.progress(job["id"], "workflow", result)
                    raise
                if not result.get("run_id"):
                    raise DomainError("ambiguous_run", "未取得运行 ID，需在 Dify 对账；页面不会自动重发评估") from error
                store.progress(job["id"], "reconciling", result)
                finished = client.reconcile(result["run_id"], store.heartbeat)
        if finished.get("status") != "succeeded":
            message = str(finished.get("error") or "远端未提供失败详情")
            scope_error = "图片无法确认同一设备" in message
            raise DomainError("equipment_scope_error" if scope_error else "workflow_failed",
                "图片不属于同一设备或无法辨认，请重新核对图片" if scope_error else "Dify 工作流未成功完成",
                status=502, details=scrub({"run_id": result["run_id"], "remote_status": finished.get("status"),
                    "upstream_message": message}, config.secret_values()))
        if finished.get("id") != result.get("run_id"):
            raise DomainError("workflow_identity_error", "工作流完成事件的运行身份不一致")
        report_id = finished.get("outputs", {}).get("report_id")
        if not isinstance(report_id, str) or not re.fullmatch(r"rpt_[a-f0-9]{32}", report_id):
            raise contract_error("outputs.report_id")
        store.progress(job["id"], "report", result)
        try:
            response = httpx.get(config.evidence_local_url + "/reports/" + report_id,
                headers={"Authorization": "Bearer " + config.evidence_api_token}, timeout=30, follow_redirects=False)
            response.raise_for_status()
            report = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise DomainError("report_fetch_failed", "未能读取证据服务保存的报告，可恢复任务重查", status=502) from error
        verify_report(report, payload, result["run_id"], result["uploaded"])
        # 同一服务的 SQLite 和 HTTP 结果需完全一致；禁止使用模型中间输出冒充报告。
        saved = Repository(config.evidence_settings().db_path).report(report_id, "trusted-workflow")
        if saved != report or report.get("report_id") != report_id:
            raise DomainError("report_identity_error", "报告持久化回读不一致", status=502)
        return {**result, "report_id": report_id, "snapshot_id": payload["snapshot_id"],
                "markdown_sha256": sha256(report["markdown"]), "review_status": "pending_review"}
