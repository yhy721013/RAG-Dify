"""Dify 官方 Workflow Service API；服务密钥和原始 SSE 不进入浏览器。"""
import json
import time
from urllib.parse import quote, urlsplit

import httpx

from app.dify_client import contract_error
from app.errors import DomainError


class WorkflowClient:
    def __init__(self, base_url, api_key, transport=None):
        url = urlsplit(base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise DomainError("configuration_error", "Workflow Service API 地址无效")
        self.client = httpx.Client(base_url=base_url.rstrip("/") + "/", headers={"Authorization": "Bearer " + api_key},
            timeout=httpx.Timeout(90, connect=15), transport=transport, follow_redirects=False)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise DomainError("workflow_network_error", "Dify Workflow 网络调用失败；可查询已有运行状态", status=502) from error
        if not response.is_success:
            raise DomainError("workflow_http_error", f"Workflow API 返回 HTTP {response.status_code}", status=502)
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except ValueError as error:
            raise contract_error("workflow.response") from error

    def upload(self, path, mime_type, user):
        with path.open("rb") as stream:
            result = self.request("POST", "files/upload", files={"file": (path.name, stream, mime_type)}, data={"user": user})
        if not isinstance(result.get("id"), str) or not result["id"]:
            raise contract_error("file.id")
        return {"type": "image", "transfer_method": "local_file", "upload_file_id": result["id"]}

    def run(self, inputs, user, started):
        """创建仅调用一次。started 在拿到运行 ID 时立即持久化，断流后调用方只读对账。"""
        try:
            with self.client.stream("POST", "workflows/run", json={"inputs": inputs, "user": user, "response_mode": "streaming"}) as response:
                if not response.is_success:
                    code = "workflow_rejected" if response.status_code in {400, 401, 403, 404, 422, 429} else "ambiguous_run"
                    raise DomainError(code, f"Workflow API 返回 HTTP {response.status_code}，未获得完成结果", status=502)
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raise contract_error("workflow.content_type")
                data_lines = []
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    elif not line and data_lines:
                        try:
                            event = json.loads("\n".join(data_lines))
                        except ValueError as error:
                            raise contract_error("workflow.sse") from error
                        data_lines = []
                        kind, data = event.get("event"), event.get("data") or {}
                        run_id = event.get("workflow_run_id") or (data.get("id") if kind in {"workflow_started", "workflow_finished"} else None)
                        if run_id:
                            started({"run_id": run_id, "task_id": event.get("task_id"), "workflow_id": data.get("workflow_id")})
                        if kind == "workflow_finished":
                            return data
                        if kind == "error":
                            raise DomainError("workflow_failed", "工作流返回错误，详细节点原因请在 Dify 运行记录中核对", status=502)
        except httpx.HTTPError as error:
            raise DomainError("workflow_disconnected", "工作流连接中断，需要按已保存运行 ID 对账", status=502) from error
        raise DomainError("workflow_disconnected", "工作流流结束但未收到完成事件", status=502)

    def detail(self, run_id):
        result = self.request("GET", "workflows/run/" + quote(run_id, safe=""))
        if result.get("id") != run_id or not isinstance(result.get("status"), str):
            raise contract_error("workflow_run.id/status")
        return result

    def reconcile(self, run_id, tick, timeout=900, interval=5):
        deadline = time.monotonic() + timeout
        while True:
            tick()
            result = self.detail(run_id)
            if result["status"] in {"succeeded", "failed", "stopped", "partial-succeeded"}:
                return result
            if result["status"] not in {"running", "paused"}:
                raise contract_error("workflow_run.status")
            if time.monotonic() >= deadline:
                raise DomainError("workflow_pending", "远程工作流尚未完成；恢复任务会继续查询同一运行", status=504)
            time.sleep(interval)
