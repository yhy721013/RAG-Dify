"""Dify 1.17.1 Service API 适配；真实实例验收状态见 docs/acceptance.md。"""
import json
import time
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from pydantic import ValidationError

from app.errors import DomainError
from app.repository import now
from app.schemas import Hit


def contract_error(field="response"):
    return DomainError("dify_contract_error", "Dify 响应不符合已核查契约，需保留脱敏响应核对", field, 502)


def redact(value):
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if key.lower() in {"authorization", "api_key", "access_token", "secret", "created_by", "updated_by", "disabled_by", "tenant_id", "user_id", "email", "author_name"}
                      else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def retrieval_hits(response: dict, dataset_id: str) -> list[dict]:
    try:
        records = response["records"]
        if not isinstance(records, list):
            raise TypeError
        result = []
        for record in records:
            segment = record["segment"]
            if segment.get("enabled") is not True or segment.get("status") != "completed":
                raise contract_error("records.segment.status")
            result.append(Hit(dataset_id=dataset_id, document_id=segment["document_id"],
                              segment_id=segment["id"], score=record["score"]).model_dump())
        return result
    except (KeyError, TypeError, ValidationError) as error:
        raise contract_error("records") from error


def workflow_hits(result: list) -> list[dict]:
    """Workflow 的 result[].metadata 与 Service API records[].segment 分开适配。"""
    try:
        if not isinstance(result, list):
            raise TypeError
        return [Hit(**{key: item["metadata"][key] for key in ("dataset_id", "document_id", "segment_id", "score")}).model_dump()
                for item in result]
    except (KeyError, TypeError, ValidationError) as error:
        raise contract_error("result.metadata") from error


class DifyClient:
    def __init__(self, settings, transport=None):
        settings.require_dify()
        url = urlsplit(settings.dify_base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise DomainError("configuration_error", "Dify 基地址必须为无内嵌凭据的 HTTP(S) Service API URL")
        self.settings = settings
        self.provenance = "synthetic_transport" if transport else "live_service_api"
        self.client = httpx.Client(base_url=settings.dify_base_url.rstrip("/") + "/",
            headers={"Authorization": "Bearer " + settings.dify_api_key},
            timeout=settings.dify_timeout_seconds, transport=transport, follow_redirects=False)
        self.capture_dir = settings.data_root / "manifests/dify_responses"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def path(self, suffix=""):
        return "datasets/" + quote(self.settings.dataset_id, safe="") + suffix

    def request(self, method, path, **kwargs):
        # 不自动重试创建，超时会交给同步清单对账；不记录 Authorization。
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.TimeoutException as error:
            raise DomainError("dify_timeout", "Dify 请求超时，技术失败不能当作无命中", status=504) from error
        except httpx.HTTPError as error:
            raise DomainError("infrastructure_error", "Dify 网络调用失败", status=502) from error
        is_json = True
        try:
            payload = response.json()
        except ValueError:
            is_json = False
            payload = {"non_json_response": response.text[:1000]}
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        capture = {"provenance": self.provenance, "created_at": now(), "method": method, "path": path,
                   "request": kwargs, "status": response.status_code, "response": payload,
                   "retry_after": response.headers.get("retry-after")}
        serialized = json.dumps(redact(capture), ensure_ascii=False, indent=2)
        serialized = serialized.replace(self.settings.dify_api_key, "[REDACTED_API_KEY]")
        (self.capture_dir / (uuid4().hex + ".json")).write_text(
            serialized, encoding="utf-8")
        if not response.is_success:
            raise DomainError("dify_http_error", f"Dify 返回 HTTP {response.status_code}；详情见脱敏请求记录", status=502)
        if not is_json or not isinstance(payload, dict):
            raise contract_error()
        return payload

    def dataset(self):
        result = self.request("GET", self.path())
        if result.get("id") != self.settings.dataset_id or result.get("indexing_technique") != "high_quality":
            raise DomainError("configuration_error", "需要当前快照专用的 High Quality 知识库")
        if not result.get("embedding_model") or not result.get("embedding_model_provider"):
            raise DomainError("configuration_error", "知识库未配置嵌入模型")
        return result

    @staticmethod
    def retrieval_model(dataset):
        return {"search_method": "hybrid_search", "reranking_enable": True, "reranking_mode": "weighted_score",
                "top_k": 5, "score_threshold_enabled": False,
                "weights": {"weight_type": "customized", "vector_setting": {
                    "vector_weight": 0.5, "embedding_provider_name": dataset["embedding_model_provider"],
                    "embedding_model_name": dataset["embedding_model"]}, "keyword_setting": {"keyword_weight": 0.5}}}

    def create_document(self, payload):
        response = self.request("POST", self.path("/document/create-by-text"), json=payload)
        try:
            document_id, batch = response["document"]["id"], response["batch"]
            if not isinstance(document_id, str) or not document_id or not isinstance(batch, str) or not batch:
                raise TypeError
            return {"document_id": document_id, "batch": batch}
        except (KeyError, TypeError) as error:
            raise contract_error("document.id/batch") from error

    def wait_index(self, document_id, batch=None):
        deadline = time.monotonic() + self.settings.dify_index_timeout_seconds
        while True:
            if batch:
                payload = self.request("GET", self.path("/documents/" + quote(batch, safe="") + "/indexing-status"))
                rows = payload.get("data")
                if not isinstance(rows, list):
                    raise contract_error("data")
                matches = [row for row in rows if isinstance(row, dict) and row.get("id") == document_id]
                if len(matches) != 1:
                    raise contract_error("data.id")
                document = matches[0]
            else:
                document = self.request("GET", self.path("/documents/" + quote(document_id, safe="")))
                if document.get("id") != document_id:
                    raise contract_error("document.id")
            status = document.get("indexing_status")
            if status == "completed":
                return
            if status in {"error", "paused", "stopped"} or document.get("error") or document.get("paused_at"):
                raise DomainError("indexing_failed", "Dify 索引失败或暂停", "indexing_status", 502)
            if status not in {"waiting", "parsing", "cleaning", "splitting", "indexing"}:
                raise contract_error("indexing_status")
            if time.monotonic() >= deadline:
                raise DomainError("indexing_timeout", "等待索引完成超时；可重跑恢复，不重复创建", status=504)
            time.sleep(min(self.settings.dify_poll_seconds, max(0, deadline - time.monotonic())))

    def paginated(self, suffix, page_size=100):
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise DomainError("input_error", "分页大小必须为 1～100", "page_size")
        page, result, seen = 1, [], set()
        while page <= 10000:
            payload = self.request("GET", self.path(suffix), params={"page": page, "limit": page_size})
            rows = payload.get("data")
            if (not isinstance(rows, list) or type(payload.get("has_more")) is not bool or
                payload.get("page") != page):
                raise contract_error("pagination")
            for item in rows:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"] or item["id"] in seen:
                    raise contract_error("data.id")
                seen.add(item["id"])
                result.append(item)
            if not payload["has_more"]:
                if type(payload.get("total")) is not int or payload["total"] != len(result):
                    raise contract_error("total")
                return result
            if not rows:
                raise contract_error("has_more")
            page += 1
        raise contract_error("pagination_limit")

    def documents(self):
        return self.paginated("/documents")

    def snapshot_metadata(self):
        fields = self.request("GET", self.path("/metadata")).get("doc_metadata")
        if not isinstance(fields, list):
            raise contract_error("doc_metadata")
        matches = [row for row in fields if row.get("name") == "rag_snapshot_id"]
        if not matches:
            # 字段名在 Dify 中唯一；若响应丢失，恢复时先 GET 对账。
            field = self.request("POST", self.path("/metadata"), json={"name": "rag_snapshot_id", "type": "string"})
        elif len(matches) == 1:
            field = matches[0]
        else:
            raise contract_error("doc_metadata.name")
        if field.get("type") != "string" or not field.get("id") or field.get("name") != "rag_snapshot_id":
            raise DomainError("metadata_error", "rag_snapshot_id 必须是唯一字符串元数据字段")
        return {key: field[key] for key in ("id", "name", "type")}

    def document_snapshot(self, document_id, field):
        detail = self.request("GET", self.path("/documents/" + quote(document_id, safe="")), params={"metadata": "only"})
        if detail.get("id") != document_id or "doc_metadata" not in detail:
            raise contract_error("document.doc_metadata")
        # Dify Cloud 实测：尚未设置任何元数据的新文档返回 null。
        if detail["doc_metadata"] is None:
            return None
        if not isinstance(detail["doc_metadata"], list):
            raise contract_error("document.doc_metadata")
        matches = [row for row in detail["doc_metadata"] if row.get("name") == field["name"]]
        if not matches:
            return None
        if len(matches) != 1 or matches[0].get("id") != field["id"] or not isinstance(matches[0].get("value"), str):
            raise contract_error("document.doc_metadata.value")
        return matches[0]["value"]

    def bind_document_snapshot(self, document_id, snapshot_id, field, allow_initial=False):
        actual = self.document_snapshot(document_id, field)
        if actual is None and allow_initial:
            self.request("POST", self.path("/documents/metadata"), json={"operation_data": [{
                "document_id": document_id, "metadata_list": [{"id": field["id"], "name": field["name"], "value": snapshot_id}],
                "partial_update": True}]})
            actual = self.document_snapshot(document_id, field)
        if actual != snapshot_id:
            raise DomainError("metadata_error", "文档知识版本元数据缺失或漂移，禁止发布", status=409)

    @staticmethod
    def snapshot_filter(snapshot_id):
        return {"logical_operator": "and", "conditions": [{"name": "rag_snapshot_id", "comparison_operator": "is", "value": snapshot_id}]}

    def segments(self, document_id, page_size=100):
        return self.paginated("/documents/" + quote(document_id, safe="") + "/segments", page_size)

    def retrieve(self, query, retrieval_model):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 250:
            raise DomainError("input_error", "Dify 检索问题须为 1～250 字符", "query")
        return retrieval_hits(self.request("POST", self.path("/retrieve"),
            json={"query": query, "retrieval_model": retrieval_model}), self.settings.dataset_id)
