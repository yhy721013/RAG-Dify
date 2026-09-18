import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.dify_client import DifyClient, retrieval_hits, workflow_hits
from app.errors import DomainError
from app.repository import Repository, json_text
from conftest import synthetic_clause
from evals.evaluate_retrieval import evaluate
from ingestion.import_reviewed import import_reviewed
from ingestion.sync_dify import BOUNDARY, activate_snapshot, chunks_for, manifest_path, sync_snapshot, verify_segments


class FakeDify:
    """依照已核查官方结构的合成服务；绝不是实际 Dify 验收。"""
    def __init__(self):
        self.docs, self.segments, self.requests = [], [], []
        self.create_count = 0
        self.status = "completed"
        self.create_timeout = False
        self.create_persist = True
        self.damage = None
        self.retrieve_unknown = False

    def handle(self, request):
        self.requests.append(request)
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        path = request.url.path
        if path.endswith("/datasets/demo_dataset"):
            return httpx.Response(200, json={"id": "demo_dataset", "indexing_technique": "high_quality",
                "embedding_model": "synthetic-embedding", "embedding_model_provider": "synthetic-provider"})
        if path.endswith("/document/create-by-text"):
            self.create_count += 1
            data = json.loads(request.content)
            assert data["process_rule"]["rules"]["segmentation"]["separator"] == BOUNDARY
            assert data["retrieval_model"]["search_method"] == "hybrid_search"
            if self.create_persist:
                self.docs.append({"id": "document_1", "name": data["name"], "indexing_status": "completed"})
                self.segments = [{"id": f"segment_{i}", "document_id": "document_1", "content": text.strip(),
                                  "status": "completed", "enabled": True} for i, text in enumerate(data["text"].split(BOUNDARY))]
            if self.create_timeout:
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            return httpx.Response(200, json={"document": {"id": "document_1"}, "batch": "batch_1"})
        if path.endswith("/indexing-status"):
            return httpx.Response(200, json={"data": [{"id": "document_1", "indexing_status": self.status}]})
        if path.endswith("/documents/document_1"):
            return httpx.Response(200, json={"id": "document_1", "indexing_status": self.status})
        if path.endswith("/retrieve"):
            data = json.loads(request.content)
            segments = self.segments[:5] if data["query"] != "无答案" else []
            records = [{"score": 0.8, "segment": deepcopy(row)} for row in segments]
            if self.retrieve_unknown and records:
                records[0]["segment"]["id"] = "unknown_segment"
            return httpx.Response(200, json={"records": records})
        if path.endswith("/segments") or path.endswith("/documents"):
            rows = deepcopy(self.segments if path.endswith("/segments") else self.docs)
            if path.endswith("/segments") and self.damage:
                if self.damage == "tail":
                    rows[-1]["content"] = "无标识尾块"
                elif self.damage == "missing":
                    rows.pop()
                elif self.damage == "merged":
                    rows[0]["content"] += "\n" + rows[-1]["content"]
                elif self.damage == "changed":
                    rows[0]["content"] += "篡改"
                elif self.damage == "duplicate":
                    rows.append(deepcopy(rows[0]))
            page = int(request.url.params["page"])
            return httpx.Response(200, json={"data": rows[page - 1:page], "has_more": page < len(rows),
                "page": page, "limit": 1, "total": len(rows)})
        raise AssertionError(f"unexpected endpoint {request.method} {path}")


@pytest.fixture
def sync_env(settings, tmp_path):
    settings = replace(settings, dify_base_url="https://dify.invalid/v1", dify_api_key="synthetic-key", dify_poll_seconds=0)
    repo = Repository(settings.db_path)
    repo.initialize()
    records = [synthetic_clause(str(i), standard_uid="", clause_uid="", standard_status="synthetic",
                                status_verified_at="2026-09-18", status_source="synthetic") for i in (1, 2)]
    path = tmp_path / "approved.jsonl"
    path.write_text("\n".join(json_text(row) for row in records), encoding="utf-8")
    import_reviewed(path, "pilot", repo, settings)
    fake = FakeDify()
    with DifyClient(settings, httpx.MockTransport(fake.handle)) as client:
        yield settings, repo, fake, client


def test_sync_realistic_mock_idempotent_paginated_mapping(sync_env):
    settings, repo, fake, client = sync_env
    first = sync_snapshot("pilot", repo, settings, client)
    second = sync_snapshot("pilot", repo, settings, client)
    assert first == second and first["chunks"] == 2 and fake.create_count == 1
    assert any(r.url.params.get("page") == "2" and r.url.path.endswith("segments") for r in fake.requests)
    hit = client.retrieve("合成问题", client.retrieval_model(client.dataset()))[0]
    assert repo.mapped_clause("pilot", hit)["content_review_status"] == "approved"
    for capture in client.capture_dir.glob("*.json"):
        text = capture.read_text(encoding="utf-8")
        assert "synthetic-key" not in text and '"Authorization"' not in text
        assert json.loads(text)["provenance"] == "synthetic_transport"


@pytest.mark.parametrize("persist", [True, False])
def test_ambiguous_create_reconciles_without_duplicate(sync_env, persist):
    settings, repo, fake, client = sync_env
    fake.create_timeout, fake.create_persist = True, persist
    with pytest.raises(DomainError) as error:
        sync_snapshot("pilot", repo, settings, client)
    assert error.value.code == "dify_timeout"
    fake.create_timeout = False
    if persist:
        assert sync_snapshot("pilot", repo, settings, client)["status"] == "verified"
    else:
        with pytest.raises(DomainError) as error:
            sync_snapshot("pilot", repo, settings, client)
        assert error.value.code == "ambiguous_creation"
    assert fake.create_count == 1


@pytest.mark.parametrize("damage", ["tail", "missing", "merged", "changed", "duplicate"])
def test_bad_segments_never_publish(sync_env, damage):
    settings, repo, fake, client = sync_env
    fake.damage = damage
    with pytest.raises(DomainError):
        sync_snapshot("pilot", repo, settings, client)
    with repo.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM dify_segments").fetchone()[0] == 0
    assert not repo.snapshot_active("pilot")


@pytest.mark.parametrize("status", ["error", "indexing", "alien_state"])
def test_index_errors_and_timeout(sync_env, status):
    settings, repo, fake, client = sync_env
    fake.status = status
    client.settings = replace(settings, dify_index_timeout_seconds=0)
    with pytest.raises(DomainError) as error:
        sync_snapshot("pilot", repo, settings, client)
    assert error.value.code in {"indexing_failed", "indexing_timeout", "dify_contract_error"}
    assert fake.create_count == 1


@pytest.mark.parametrize("failure", ["timeout", "http", "malformed", "missing_field"])
def test_retrieval_technical_failures_are_not_empty(sync_env, failure):
    settings, repo, fake, _ = sync_env
    def handle(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("failed", request=request)
        if failure == "http":
            return httpx.Response(503, json={"error": "failed"})
        if failure == "malformed":
            return httpx.Response(200, text="not-json")
        return httpx.Response(200, json={})
    with DifyClient(settings, httpx.MockTransport(handle)) as client:
        with pytest.raises(DomainError):
            client.retrieve("问题", {})


def test_two_separate_retrieval_shapes():
    root = Path(__file__).resolve().parent.parent / "fixtures"
    api = json.loads((root / "dify_knowledge_retrieval.synthetic.json").read_text(encoding="utf-8"))
    workflow = json.loads((root / "dify_workflow_retrieval.synthetic.json").read_text(encoding="utf-8"))
    assert retrieval_hits(api, "dataset_1") == workflow_hits(workflow["result"])
    with pytest.raises(DomainError):
        workflow_hits(api["records"])
    with pytest.raises(DomainError):
        retrieval_hits(workflow, "dataset_1")


def test_clause_unit_evaluation_and_activation(sync_env, tmp_path):
    settings, repo, fake, client = sync_env
    sync_snapshot("pilot", repo, settings, client)
    uids = [row["clause_uid"] for row in repo.all_clauses("pilot")]
    cases = [{"case_id": "case_1", "snapshot_id": "pilot", "query": "合成问题", "expected_clause_uids": uids,
              "answerable": True, "annotated_by": "synthetic", "annotated_at": "2026-09-18"},
             {"case_id": "case_2", "snapshot_id": "pilot", "query": "无答案", "expected_clause_uids": [],
              "answerable": False, "annotated_by": "synthetic", "annotated_at": "2026-09-18"}]
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json_text(row) for row in cases), encoding="utf-8")
    result = evaluate(path, repo, settings, client)
    assert result["passed"] and result["hit_at_5_rate"] == 1 and result["all_targets_recalled_rate"] == 1
    assert result["no_answer_candidate_rate"] == 0
    with pytest.raises(DomainError):
        activate_snapshot("pilot", repo, replace(settings, app_env="development"), client)
    assert activate_snapshot("pilot", repo, settings, client)["status"] == "active"
    fake.retrieve_unknown = True
    result = evaluate(path, repo, settings, client)
    assert not result["passed"] and result["error_count"] == 1


def test_activation_without_evaluation_blocked(sync_env):
    settings, repo, _, client = sync_env
    sync_snapshot("pilot", repo, settings, client)
    with pytest.raises(DomainError):
        activate_snapshot("pilot", repo, settings, client)


def test_long_clause_fragments_share_full_clause():
    clause = synthetic_clause(text_verbatim="【合成测试】长条款含条件与否定词。\n" * 120)
    chunks = chunks_for([clause])
    assert len(chunks) > 1
    assert {chunk["clause_uid"] for chunk in chunks.values()} == {clause["clause_uid"]}
    combined = "".join(chunk["content"].split("CONTENT:\n", 1)[1] for chunk in chunks.values())
    assert combined == clause["text_verbatim"].strip()


def test_segment_crlf_preserves_identity_and_actual_content_hash():
    from app.repository import sha256
    chunks = chunks_for([synthetic_clause()])
    chunk = next(iter(chunks.values()))
    content = chunk["content"].replace("\n", "\r\n")
    segment = {"id": "segment_1", "document_id": "document_1", "enabled": True,
               "status": "completed", "content": content}
    mappings = verify_segments([segment], chunks, "snapshot_1", "dataset_1", "document_1")
    assert mappings[0]["clause_uid"] == chunk["clause_uid"]
    assert mappings[0]["index_text_sha256"] == sha256(content)


@pytest.mark.parametrize("text", [" \n\t", "![图表](images/chart.png)"])
def test_no_approved_clause_silently_lost_from_index(text):
    with pytest.raises(DomainError, match="没有可索引文本"):
        chunks_for([synthetic_clause("1"), synthetic_clause("2", text_verbatim=text)])


def test_placeholder_config_rejected(settings):
    with pytest.raises(DomainError):
        DifyClient(replace(settings, dify_base_url="REPLACE_WITH_ACTUAL_SERVICE_API_BASE"))
