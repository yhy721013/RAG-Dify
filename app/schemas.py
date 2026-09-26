from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ID = Annotated[str, StringConstraints(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")]
Text = Annotated[str, StringConstraints(min_length=1, max_length=4000, pattern=r"\S")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ImageRef(StrictModel):
    image_id: ID
    position: int = Field(ge=1, le=4)
    file_ref: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class Observation(StrictModel):
    observation_id: ID
    image_ids: list[ID] = Field(min_length=1, max_length=4)
    visible_fact: Text
    unknowns: list[Text] = Field(default_factory=list, max_length=20)


class Hit(StrictModel):
    dataset_id: ID
    document_id: ID
    segment_id: ID
    score: float = Field(ge=0, le=1)


class Check(StrictModel):
    check_id: ID
    observation_ids: list[ID] = Field(min_length=1, max_length=24)
    query: Text
    hits: list[Hit] = Field(max_length=50)


class PrepareRequest(StrictModel):
    request_id: ID
    snapshot_id: ID
    equipment_id: ID
    image_manifest: list[ImageRef] = Field(min_length=1, max_length=4)
    observations: list[Observation] = Field(min_length=1, max_length=24)
    checks: list[Check] = Field(min_length=1, max_length=6)
    # 阶段 D 的输入与运行追溯字段；可选以兼容阶段 A～C 请求。
    equipment_type: str | None = Field(default=None, max_length=100)
    equipment_description: str | None = Field(default=None, max_length=4000)
    operating_state: Literal["运行", "停机", "检修", "未知"] | None = None
    work_context: str | None = Field(default=None, max_length=4000)
    same_equipment_confirmed: bool | None = None
    workflow_version: str | None = Field(default=None, max_length=200)
    model_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def references(self):
        if self.same_equipment_confirmed is False:
            raise ValueError("未确认同一设备，禁止继续评估")
        def unique(values, label):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} 不能重复")
        images = {item.image_id for item in self.image_manifest}
        observations = {item.observation_id for item in self.observations}
        unique([item.image_id for item in self.image_manifest], "image_id")
        unique([item.file_ref for item in self.image_manifest], "file_ref")
        if sorted(item.position for item in self.image_manifest) != list(range(1, len(images) + 1)):
            raise ValueError("图片 position 必须连续且唯一")
        unique([item.observation_id for item in self.observations], "observation_id")
        unique([item.check_id for item in self.checks], "check_id")
        for item in self.observations:
            unique(item.image_ids, "image_ids")
            if not set(item.image_ids) <= images:
                raise ValueError("观察引用未知图片")
        for item in self.checks:
            unique(item.observation_ids, "observation_ids")
            if not set(item.observation_ids) <= observations:
                raise ValueError("检查项引用未知观察")
        return self


class Finding(StrictModel):
    check_id: ID
    observation_ids: list[ID] = Field(min_length=1, max_length=24)
    status: Literal["evidence_supported_risk", "needs_confirmation", "insufficient_evidence"]
    risk_description: Text
    applicability_reason: Text
    evidence_ids: list[ID] = Field(max_length=3)
    recommendation: Text
    verification_required: list[Text] = Field(max_length=20)


class FinalizeRequest(StrictModel):
    context_id: ID
    findings: list[Finding] = Field(min_length=1, max_length=6)


class SourceSpan(StrictModel):
    pdf_page_index: int = Field(ge=0)
    printed_page_label: str | None = Field(default=None, max_length=80)
    block_ids: list[ID] = Field(min_length=1)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)


class ClauseRecord(StrictModel):
    snapshot_id: str = ""
    standard_uid: str = ""
    standard_code: str = ""
    standard_name: str = ""
    edition: str = ""
    scope: str = ""
    standard_status: str = "unknown"
    status_verified_at: str = ""
    status_source: str = ""
    source_file_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_archive_path: str
    source_page_count: int = Field(ge=1)
    parser_version: str
    full_document_covered: bool
    clause_uid: str = ""
    clause_no: str
    clause_path: list[str] = Field(min_length=1)
    text_verbatim: str = Field(min_length=1, max_length=100000)
    content_sha256: str = ""
    source_spans: list[SourceSpan] = Field(min_length=1)
    asset_refs: list[str] = Field(default_factory=list)
    asset_sha256: dict[str, str] = Field(default_factory=dict)
    context_clause_uids: list[str] = Field(default_factory=list)
    content_review_status: Literal["pending", "approved", "rejected", "machine_checked"] = "pending"
    evidence_complete: bool = False
    is_test_fixture: bool = False
    boundary_status: Literal["pending", "confirmed", "unknown", "machine_checked"] = "pending"
    review_issues: list[str] = Field(default_factory=list)
    reviewed_by: str = ""
    reviewed_at: str = ""
    review_notes: str = ""
