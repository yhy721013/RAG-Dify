from copy import deepcopy
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


def generation_schema(schema):
    r"""Keep backend validation separate from provider constrained decoding.

    Text's unanchored \S means 'contains non-whitespace' in Pydantic/JSON
    Schema. Some constrained decoders may instead treat it as the entire
    generated string. Do not send this prose-only predicate to the model;
    keep length constraints and all identifier patterns, and validate content
    at the existing code/API boundaries.
    """
    result = deepcopy(schema)

    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "string" and value.get("pattern") == r"\S":
                value.pop("pattern")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result)
    return result


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
    return generation_schema(schema)


class DynamicObservation(StrictModel):
    image_ids: list[ImageID] = Field(min_length=1, max_length=4)
    part: Text = Field(max_length=200)
    visible_fact: Annotated[str, StringConstraints(min_length=8, max_length=3500, pattern=r"\S")]
    unknowns: list[Text] = Field(max_length=20, description="图像不能确认的事实；局部特写应注明无法核实的整机归属与相关功能、尺寸或操作条件，不以scope_status代替此处记录。")


class RetrievalDirection(StrictModel):
    observation_indices: list[Annotated[int, Field(ge=1, le=18)]] = Field(min_length=1, max_length=18,
        description="关联本次 observations 数组中的序号，从1开始，不是图片序号。")
    query: Annotated[str, StringConstraints(min_length=8, max_length=250, pattern=r"\S")] = Field(
        description="根据本次问题与可见事实生成中性技术检索问题；此阶段尚未检索，不填任何标准号、条款号、引用或违规结论。")


class DynamicVisionResult(StrictModel):
    scope_status: Literal["same_equipment", "different_equipment", "uncertain", "unreadable"] = Field(
        description="判断图片是否可作为同一分析对象，不认证整机型号。单张可辨认且无实质冲突的部件特写选same_equipment；缺少整机信息记入unknowns。多图明确不同设备选different_equipment；对应关系不明或对象冲突选uncertain；有关部件完全不可辨认选unreadable。")
    scope_reason: Text = Field(description="解释图片归属及可分析的边界；局部图片注明整机类别仅由用户提供，不能仅因未展示整机而拒绝分析。")
    observations: list[DynamicObservation] = Field(min_length=1, max_length=18)
    checks: list[RetrievalDirection] = Field(min_length=1, max_length=6)


def dynamic_assessment_schema():
    schema = AssessmentDraft.model_json_schema()
    for name in ("AssessmentFinding", "InsufficientFinding"):
        props = schema["$defs"][name]["properties"]
        props["check_id"]["enum"] = [f"check_{n:03d}" for n in range(1, 7)]
        for field in ("risk_description", "applicability_reason", "recommendation"):
            props[field]["minLength"] = 8
    return generation_schema(schema)
