import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.dify_client import DifyClient
from app.errors import DomainError
from app.repository import Repository, json_text
from conftest import synthetic_clause
from ingestion.import_reviewed import import_reviewed
from ingestion.sync_dify import BOUNDARY, manifest_path, sync_snapshot


class PartitionDify:
    """按官方 Service API 契约模拟两版语料，非线上验收。"""
    def __init__(self):
        self.docs, self.segments, self.tags = {}, {}, {}
        self.field = None
        self.cross_version = False

    def handle(self, request):
        path = request.url.path
        data = json.loads(request.content) if request.content else {}
        if path.endswith("/datasets/demo_dataset"):
            return httpx.Response(200, json={"id": "demo_dataset", "indexing_technique": "high_quality",
                "embedding_model": "synthetic", "embedding_model_provider": "synthetic"})
        if path.endswith("/documents/metadata"):
            for row in data["operation_data"]:
                self.tags[row["document_id"]] = row["metadata_list"]
            return httpx.Response(200, json={"result": "success"})
        if path.endswith("/metadata"):
            if request.method == "POST":
                assert data["type"] == "string"
                self.field = {"id": "field1", **data}
                return httpx.Response(201, json=self.field)
            return httpx.Response(200, json={"doc_metadata": [self.field] if self.field else []})
        if path.endswith("/document/create-by-text"):
            uid = "doc" + str(len(self.docs) + 1)
            self.docs[uid] = {"id": uid, "name": data["name"]}
            self.segments[uid] = [{"id": uid + "_" + str(i), "document_id": uid, "content": text.strip(),
                "status": "completed", "enabled": True} for i, text in enumerate(data["text"].split(BOUNDARY))]
            return httpx.Response(200, json={"document": {"id": uid}, "batch": uid})
        if path.endswith("/indexing-status"):
            return httpx.Response(200, json={"data": [{"id": path.split("/")[-2], "indexing_status": "completed"}]})
        if path.endswith("/retrieve"):
            target = data["retrieval_model"]["metadata_filtering_conditions"]["conditions"][0]["value"]
            records = [row for uid, rows in self.segments.items() if self.cross_version or self.tags[uid][0]["value"] == target for row in rows]
            return httpx.Response(200, json={"records": [{"score": .8, "segment": row} for row in records]})
        if path.endswith("/documents") or path.endswith("/segments"):
            rows = list(self.docs.values()) if path.endswith("/documents") else self.segments[path.split("/")[-2]]
            return httpx.Response(200, json={"data": rows, "has_more": False, "page": 1, "total": len(rows)})
        uid = path.split("/")[-1]
        return httpx.Response(200, json={"id": uid, "doc_metadata": self.tags.get(uid, []), "indexing_status": "completed"})


def test_real_null_metadata_requires_binding_and_never_passes_verification(settings):
    data = json.loads((Path(__file__).resolve().parents[1] / "fixtures/dify_portal/document_without_metadata.real.json").read_text(encoding="utf-8"))
    settings = replace(settings, dify_base_url="https://dify.invalid/v1", dify_api_key="synthetic")
    with DifyClient(settings, httpx.MockTransport(lambda request: httpx.Response(200, json=data))) as client:
        field = {"id": "field1", "name": "rag_snapshot_id", "type": "string"}
        assert client.document_snapshot("document_redacted", field) is None
        with pytest.raises(DomainError, match="缺失或漂移"):
            client.bind_document_snapshot("document_redacted", "v1", field)


def test_two_versions_metadata_filter_idempotency_and_unknown_document(settings, tmp_path):
    settings = replace(settings, partitioned_dataset=True, dify_base_url="https://dify.invalid/v1", dify_api_key="synthetic")
    repo = Repository(settings.db_path)
    repo.initialize()
    fake = PartitionDify()
    with DifyClient(settings, httpx.MockTransport(fake.handle)) as client:
        for version in ("v1", "v2"):
            record = synthetic_clause("1", standard_uid="", clause_uid="", standard_status="synthetic",
                status_verified_at="2026-09-20", status_source="synthetic", text_verbatim="【合成测试】" + version)
            path = tmp_path / "approved.jsonl"
            path.write_text(json_text(record), encoding="utf-8")
            import_reviewed(path, version, repo, settings)
            sync_snapshot(version, repo, settings, client)
            sync_snapshot(version, repo, settings, client)
        assert len(fake.docs) == 2
        for version in ("v1", "v2"):
            manifest = json.loads(manifest_path(settings, version).read_text(encoding="utf-8"))
            hits = client.retrieve("合成问题", manifest["retrieval_model"])
            assert len(hits) == 1
            assert repo.mapped_clause(version, hits[0])["text_verbatim"].endswith(version)
        fake.cross_version = True
        cross = client.retrieve("合成问题", manifest["retrieval_model"])
        with pytest.raises(DomainError):
            for hit in cross:
                repo.mapped_clause("v2", hit)
        fake.tags["doc1"][0]["value"] = "v2"
        with pytest.raises(DomainError, match="元数据"):
            sync_snapshot("v2", repo, settings, client)
        fake.tags["doc1"][0]["value"] = "v1"
        fake.docs["foreign"] = {"id": "foreign", "name": "not-registered"}
        with pytest.raises(DomainError, match="未纳入快照"):
            sync_snapshot("v2", repo, settings, client)
