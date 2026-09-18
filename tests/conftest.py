import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import json_text, sha256
from app.schemas import ClauseRecord
from app.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
AUTH = {"Authorization": "Bearer synthetic-test-token"}


def synthetic_clause(number="1", **changes):
    value = dict(standard_uid="demo_standard", standard_code="DEMO-STD-001",
                 standard_name="演示标准，仅用于软件测试", edition="demo-v1", scope="合成测试设备",
                 source_file_sha256="a" * 64, source_archive_path="synthetic.pdf", source_page_count=2,
                 parser_version="synthetic", full_document_covered=True,
                 clause_uid="demo_clause_" + number, clause_no=number, clause_path=[number],
                 text_verbatim="【测试占位文本，不得用于真实风险评估】" + number,
                 source_spans=[{"pdf_page_index": 0, "block_ids": ["p0_b0"]}],
                 content_review_status="approved", evidence_complete=True, is_test_fixture=True,
                 boundary_status="confirmed", reviewed_by="synthetic", reviewed_at="2026-09-18T00:00:00Z")
    value.update(changes)
    value["content_sha256"] = sha256(value["text_verbatim"])
    return ClauseRecord.model_validate(value).model_dump()


def seed(repo):
    with repo.connect(write=True) as conn:
        conn.execute("INSERT INTO standard_versions VALUES (?, ?, ?, ?)",
                     ("demo_snapshot", "demo_standard", "{}", "active"))
        for number in ("1", "2", "3", "4"):
            clause = synthetic_clause(number)
            conn.execute("INSERT INTO clauses VALUES (?, ?, ?, ?, ?)",
                         ("demo_snapshot", clause["clause_uid"], "demo_standard", clause["content_sha256"], json_text(clause)))
            conn.execute("INSERT INTO dify_segments VALUES (?, ?, ?, ?, ?, ?, ?)",
                         ("demo_snapshot", "demo_dataset", "demo_document", "demo_segment_" + number,
                          "demo_chunk_" + number, clause["clause_uid"], "b" * 64))


@pytest.fixture
def settings(tmp_path):
    return Settings(app_env="test", db_path=tmp_path / "app.db", data_root=tmp_path,
                    active_snapshot_id="demo_snapshot", dataset_id="demo_dataset", api_token="synthetic-test-token")


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app, headers=AUTH) as instance:
        seed(app.state.repository)
        yield instance


@pytest.fixture
def request_body():
    return json.loads((ROOT / "fixtures/prepare.synthetic.json").read_text(encoding="utf-8"))


def draft_for(context, status="needs_confirmation"):
    return {"context_id": context["context_id"], "findings": [
        {"check_id": check["check_id"], "observation_ids": source["observation_ids"],
         "status": status if check["allowed_evidence_ids"] else "insufficient_evidence",
         "risk_description": "【合成测试】待复核风险", "applicability_reason": "【合成测试】待确认条件",
         "evidence_ids": check["allowed_evidence_ids"], "recommendation": "【合成测试】现场检查",
         "verification_required": ["确认运行状态"]}
        for check, source in zip(context["checks"], context["request"]["checks"], strict=True)]}
