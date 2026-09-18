"""实际 Dify Cloud 响应的离线结构回归；不会发起真实 API 调用。"""
import json
import re
from dataclasses import replace
from pathlib import Path

import httpx

from app.dify_client import DifyClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures/dify_cloud"


def test_captured_service_api_contracts(settings):
    captured = {path.stem.removesuffix(".real"): json.loads(path.read_text(encoding="utf-8"))
                for path in FIXTURES.glob("*.real.json")}
    dataset_id = captured["dataset"]["response"]["id"]
    settings = replace(settings, dataset_id=dataset_id, dify_base_url="https://fixture.invalid/v1",
                       dify_api_key="synthetic-fixture-key")
    requested_pages = []

    def respond(request):
        path = request.url.path.removeprefix("/v1/")
        for name, record in captured.items():
            if record["path"] != path or record["method"] != request.method:
                continue
            parameters = record["request"].get("params", {})
            if "page" in parameters and int(request.url.params["page"]) != parameters["page"]:
                continue
            if name.startswith("segments_page_"):
                assert request.url.params["limit"] == "3"
                requested_pages.append(parameters["page"])
            return httpx.Response(record["status"], json=record["response"])
        raise AssertionError(f"未捕获的请求：{request.method} {path}")

    with DifyClient(settings, httpx.MockTransport(respond)) as client:
        dataset = client.dataset()
        created = client.create_document(captured["create"]["request"]["json"])
        document_id = created["document_id"]
        client.wait_index(document_id, created["batch"])
        assert [doc["id"] for doc in client.documents()] == [document_id]
        segments = client.segments(document_id, page_size=3)
        assert requested_pages == [1, 2, 3, 4] and len(segments) == 10
        hits = client.retrieve("脱敏契约回放问题", client.retrieval_model(dataset))
        assert len(hits) == 5
        assert all(hit["document_id"] == document_id for hit in hits)
        assert {hit["segment_id"] for hit in hits} <= {segment["id"] for segment in segments}


def test_live_fixtures_remove_business_text_and_personal_identifiers():
    for path in FIXTURES.glob("*.real.json"):
        content = path.read_text(encoding="utf-8")
        assert "GB/T 8196" not in content and "pilot_20260918_01" not in content
        assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", content)
        record = json.loads(content)
        assert record["provenance"] == "live_service_api"
        assert record["status"] == 200
