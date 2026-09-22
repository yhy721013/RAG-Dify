from typing import Annotated, Literal

from pydantic import Field, StringConstraints, TypeAdapter

from app.schemas import Finding, ID, StrictModel, Text

ImageID = Annotated[str, StringConstraints(pattern=r"^image_00[1-4]$")]
EvidenceID = Annotated[str, StringConstraints(pattern=r"^ev_[0-9a-f]{32}$")]


class VisionObservation(StrictModel):
    image_ids: list[ImageID] = Field(min_length=1, max_length=4,
        description="只复制本次图片清单的 image_id；不能填写文件UUID、文件名或字段名。")
    part: Text = Field(max_length=200)
    visible_fact: Text = Field(max_length=3500)
    unknowns: list[Text] = Field(max_length=20)
    check_ids: list[ID] = Field(max_length=6,
        description="只选择固定清单中的 check_id；无关联时填写 []，禁止把 check_ids 字段名当作值。")


class VisionResult(StrictModel):
    scope_status: Literal["same_equipment", "different_equipment", "uncertain", "unreadable"]
    scope_reason: Text
    observations: list[VisionObservation] = Field(max_length=18)


class AssessmentFinding(Finding):
    status: Literal["evidence_supported_risk", "needs_confirmation"]
    evidence_ids: list[EvidenceID] = Field(min_length=1, max_length=3,
        description="只逐字复制当前检查项 allowed_evidence_ids 中的编号；状态词、字段名和条款UID均不是证据编号。")


class InsufficientFinding(AssessmentFinding):
    status: Literal["insufficient_evidence"]
    evidence_ids: list[EvidenceID] = Field(max_length=3,
        description="确实缺少可引用依据时允许空数组，但不得把没有依据的判断写成标准要求。")


class AssessmentDraft(StrictModel):
    # context_id 来自 HTTP prepare 响应，由代码绑定，不让模型生成。
    findings: list[AssessmentFinding | InsufficientFinding] = Field(min_length=1, max_length=6)


def output_schema(model, checklist):
    """将当前已配置清单编入生成约束，运行时仍按本次请求逐项检查。"""
    ids = [TypeAdapter(ID).validate_python(item["check_id"]) for item in checklist["checks"]]
    if not 1 <= len(ids) <= 6 or len(set(ids)) != len(ids):
        raise ValueError("生成Schema需要1～6个不同的检查项编号")
    schema = model.model_json_schema()
    if model is VisionResult:
        properties = schema["$defs"]["VisionObservation"]["properties"]
        properties["check_ids"]["items"]["enum"] = ids
        properties["image_ids"]["items"]["enum"] = [f"image_{n:03d}" for n in range(1, 5)]
    elif model is AssessmentDraft:
        for name in ("AssessmentFinding", "InsufficientFinding"):
            schema["$defs"][name]["properties"]["check_id"]["enum"] = ids
    else:
        raise ValueError("未知的模型输出Schema")
    return schema
