import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from conftest import draft_for
from workflows import nodes
from workflows.schemas import AssessmentDraft, VisionResult, output_schema

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def source():
    return json.loads((ROOT / "fixtures/workflow_input.synthetic.json").read_text(encoding="utf-8"))


@pytest.fixture
def checklist():
    return json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))


@pytest.fixture
def initial(source, checklist):
    return nodes.validate_input(source["images"], checklist["equipment_type"], "合成测试", "未知", "未知", True,
        "synthetic_identifier_test", json.dumps(checklist, ensure_ascii=False), "demo_snapshot", "demo_dataset", "test", "synthetic")


@pytest.fixture
def failures():
    return json.loads((ROOT / "fixtures/workflow_identifier_errors.redacted.json").read_text(encoding="utf-8"))["cases"]


def test_observed_upload_id_confusion_has_exact_request_local_mapping(source, checklist, initial, failures):
    vision = source["vision"]
    vision["observations"][0].update(failures["upload_id_as_image_id"])
    before = deepcopy(vision)
    output = nodes.build_checks(vision, initial["request_json"], json.dumps(checklist, ensure_ascii=False))
    assert json.loads(output["observations_json"])[0]["image_ids"] == ["image_001"]
    assert vision == before
    assert "synthetic-file-1" not in initial["image_manifest_json"]
    assert json.loads(output["request_json"])["image_manifest"][0]["file_ref"] == "synthetic-file-1"


@pytest.mark.parametrize("values,expected", [
    (["synthetic-file-2", "image_001"], ["image_002", "image_001"]),
    (["image_001", "image_002"], ["image_001", "image_002"]),
])
def test_multi_image_normalization_preserves_the_selected_images_and_order(source, checklist, initial, values, expected):
    source["vision"]["observations"][0]["image_ids"] = values
    output = nodes.build_checks(source["vision"], initial["request_json"], json.dumps(checklist, ensure_ascii=False))
    assert json.loads(output["observations_json"])[0]["image_ids"] == expected


@pytest.mark.parametrize("values", [["foreign-upload"], ["image_003"], ["image_1"],
                                    ["synthetic-file-1", "image_001"]])
def test_unknown_or_duplicate_image_aliases_still_fail(source, checklist, initial, values):
    source["vision"]["observations"][0]["image_ids"] = values
    with pytest.raises(ValueError):
        nodes.build_checks(source["vision"], initial["request_json"], json.dumps(checklist, ensure_ascii=False))


def test_ambiguous_image_aliases_fail(source, checklist, initial):
    request = json.loads(initial["request_json"])
    request["image_manifest"][0]["file_ref"] = "image_002"
    with pytest.raises(ValueError, match="歧义"):
        nodes.build_checks(source["vision"], json.dumps(request), json.dumps(checklist, ensure_ascii=False))


def test_observed_field_name_is_never_silently_removed(source, checklist, initial, failures):
    source["vision"]["observations"][0].update(failures["field_name_as_check_id"])
    with pytest.raises(ValueError, match=r"obs_001.*check_ids"):
        nodes.build_checks(source["vision"], initial["request_json"], json.dumps(checklist, ensure_ascii=False))


def test_unrelated_observation_can_explicitly_select_no_checks(source, checklist, initial):
    source["vision"]["observations"][0]["check_ids"] = []
    output = nodes.build_checks(source["vision"], initial["request_json"], json.dumps(checklist, ensure_ascii=False))
    assert len(output["checks"]) == 6
    observations = json.loads(output["observations_json"])
    assert len(observations) == 7
    assert all("不足以确认" in row["visible_fact"] for row in observations[1:])


def test_schema_uses_configured_checklist_choices_and_specific_identifier_types(source, checklist):
    custom = deepcopy(checklist)
    custom["checks"][0]["check_id"] = "synthetic_custom_check"
    vision = output_schema(VisionResult, custom)["$defs"]["VisionObservation"]["properties"]
    assessment = output_schema(AssessmentDraft, custom)["$defs"]["AssessmentFinding"]["properties"]
    ids = [row["check_id"] for row in custom["checks"]]
    assert vision["check_ids"]["items"]["enum"] == ids
    assert assessment["check_id"]["enum"] == ids
    assert "check_ids" not in ids
    assert vision["image_ids"]["items"]["enum"] == ["image_001", "image_002", "image_003", "image_004"]
    assert assessment["evidence_ids"]["items"]["pattern"] == r"^ev_[0-9a-f]{32}$"
    source["vision"]["observations"][0]["image_ids"] = ["synthetic-file-1"]
    with pytest.raises(ValidationError):
        VisionResult.model_validate(source["vision"])


@pytest.mark.parametrize("mutation", ["empty", "duplicate", "invalid"])
def test_unusable_checklists_cannot_generate_output_schema(checklist, mutation):
    if mutation == "empty":
        checklist["checks"] = []
    elif mutation == "duplicate":
        checklist["checks"][1]["check_id"] = checklist["checks"][0]["check_id"]
    else:
        checklist["checks"][0]["check_id"] = "not a check id"
    with pytest.raises((ValueError, ValidationError)):
        output_schema(VisionResult, checklist)


def test_observed_status_is_rejected_as_evidence_without_repair(client, request_body, failures):
    context = client.post("/evidence/prepare", json=request_body).json()
    finding = draft_for(context)["findings"][0]
    finding.update(failures["status_as_evidence_id"])
    original = deepcopy(finding)
    with pytest.raises(ValidationError):
        AssessmentDraft.model_validate({"findings": [finding]})
    with pytest.raises(ValueError, match="insufficient_evidence"):
        nodes.finalize_payload(json.dumps(context), {"findings": [finding]})
    assert finding == original


@pytest.mark.parametrize("mode", ["empty_structured", "partial_text", "extra_context"])
def test_incomplete_or_wrapped_model_output_never_becomes_a_report(failures, mode):
    case = failures["truncated_generation"]
    model_output = case["structured_output"] if mode == "empty_structured" else case["model_text"]
    if mode == "extra_context":
        model_output = {"findings": [], "context_id": "ctx_model_must_not_supply"}
    context = {"context_id": "ctx_authoritative", "checks": [{"check_id": "guard_hazards", "allowed_evidence_ids": []}]}
    with pytest.raises(ValueError):
        nodes.finalize_payload(json.dumps(context), model_output)


def test_model_evidence_retains_full_text_dependencies_and_immutable_context(client, request_body):
    context = client.post("/evidence/prepare", json=request_body).json()
    output = nodes.unpack_evidence(200, json.dumps(context), json.dumps(request_body))
    public = json.loads(output["evidence_json"])
    assert json.loads(output["context_json"]) == context
    assert len(public["evidence"]) == len(context["evidence"])
    for projected, original in zip(public["evidence"], context["evidence"], strict=True):
        assert projected["text_verbatim"] == original["text_verbatim"]
        assert projected["evidence_id"] == original["evidence_id"]
        assert projected["evidence_complete"] == original["evidence_complete"]
        assert projected["applicability_context"] == original["applicability_context"]
        assert projected["scope"] == original["scope"]
        assert projected["standard_status"] == original["standard_status"]
        assert projected["completeness_issues"] == original["completeness_issues"]
        assert [c["text_verbatim"] for c in projected["context_clauses"]] == [c["text_verbatim"] for c in original["context_clauses"]]
        assert not {"clause_uid", "source_spans", "content_sha256", "source_archive_path", "review_notes"} & projected.keys()
    for projected, original in zip(public["checks"], context["checks"], strict=True):
        assert projected["allowed_evidence_ids"] == original["allowed_evidence_ids"]
        assert "excluded_evidence" not in projected
    valid = {"findings": draft_for(context)["findings"]}
    final = json.loads(nodes.finalize_payload(output["context_json"], valid)["body"])
    saved = client.post("/reports/finalize", json=final)
    assert saved.status_code == 200 and saved.json()["validation_passed"] is True


def test_incomplete_dependency_and_its_scope_are_not_hidden_from_the_model(client, request_body):
    context = client.post("/evidence/prepare", json=request_body).json()
    evidence = context["evidence"][0]
    dependency = deepcopy(evidence)
    dependency.update(scope="合成限制：只有前提成立时适用", evidence_complete=False,
                      text_verbatim="【合成测试】如果条件未知，不得作确定判断。")
    dependency.pop("context_clauses", None)
    evidence.update(context_clauses=[dependency], evidence_complete=False,
                    completeness_issues=["synthetic_context_incomplete"])
    before = deepcopy(context)
    projected = nodes._model_evidence(context)["evidence"][0]
    assert projected["evidence_complete"] is False
    assert projected["completeness_issues"] == ["synthetic_context_incomplete"]
    assert projected["context_clauses"][0]["scope"] == dependency["scope"]
    assert projected["context_clauses"][0]["text_verbatim"] == dependency["text_verbatim"]
    assert projected["context_clauses"][0]["evidence_complete"] is False
    assert context == before


def test_real_evidence_from_another_check_still_cannot_be_borrowed():
    first, second = "ev_" + "a" * 32, "ev_" + "b" * 32
    context = {"context_id": "ctx_synthetic", "checks": [
        {"check_id": "guard_hazards", "allowed_evidence_ids": [first]},
        {"check_id": "guard_joints", "allowed_evidence_ids": [second]}]}
    findings = [{"check_id": row["check_id"], "observation_ids": ["obs_001"], "status": "needs_confirmation",
        "risk_description": "合成测试", "applicability_reason": "合成测试", "evidence_ids": [second],
        "recommendation": "待核查", "verification_required": []} for row in context["checks"]]
    with pytest.raises(ValueError, match="guard_hazards"):
        nodes.finalize_payload(json.dumps(context), {"findings": findings})


@pytest.mark.parametrize("status", ["needs_confirmation", "evidence_supported_risk"])
def test_status_requiring_evidence_cannot_have_an_empty_list(client, request_body, status):
    context = client.post("/evidence/prepare", json=request_body).json()
    finding = draft_for(context)["findings"][0]
    finding.update(status=status, evidence_ids=[])
    with pytest.raises(ValidationError):
        AssessmentDraft.model_validate({"findings": [finding]})
    with pytest.raises(ValueError, match="evidence_ids为空"):
        nodes.finalize_payload(json.dumps(context), {"findings": [finding]})


def test_insufficient_evidence_can_explicitly_have_no_citations(client, request_body):
    context = client.post("/evidence/prepare", json=request_body).json()
    draft = {"findings": draft_for(context)["findings"]}
    for finding in draft["findings"]:
        finding.update(status="insufficient_evidence", evidence_ids=[])
    AssessmentDraft.model_validate(draft)
    assert json.loads(nodes.finalize_payload(json.dumps(context), draft)["body"])["findings"] == draft["findings"]


def test_schema_binds_status_to_required_evidence(checklist):
    schema = output_schema(AssessmentDraft, checklist)
    assert len(schema["properties"]["findings"]["items"]["anyOf"]) == 2
    supported = schema["$defs"]["AssessmentFinding"]["properties"]
    insufficient = schema["$defs"]["InsufficientFinding"]["properties"]
    assert supported["status"]["enum"] == ["evidence_supported_risk", "needs_confirmation"]
    assert supported["evidence_ids"]["minItems"] == 1
    assert insufficient["status"]["const"] == "insufficient_evidence"
    assert insufficient["evidence_ids"].get("minItems", 0) == 0


def test_finalize_error_exposes_the_service_code_and_field_without_a_report():
    body = json.dumps({"error": {"code": "missing_evidence", "field": "findings.guard_hazards.status",
                                "message": "无标准证据时必须标记insufficient_evidence"}})
    with pytest.raises(ValueError, match=r"missing_evidence.*findings.guard_hazards.status"):
        nodes.unpack_report(422, body, "ctx_test")
    with pytest.raises(ValueError, match="HTTP 502"):
        nodes.unpack_report(502, "<html>upstream unavailable</html>", "ctx_test")
