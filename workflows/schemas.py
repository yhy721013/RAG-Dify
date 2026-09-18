from typing import Literal

from pydantic import Field

from app.schemas import Finding, ID, StrictModel, Text


class VisionObservation(StrictModel):
    image_ids: list[ID] = Field(min_length=1, max_length=4)
    part: Text = Field(max_length=200)
    visible_fact: Text = Field(max_length=3500)
    unknowns: list[Text] = Field(max_length=20)
    check_ids: list[ID] = Field(max_length=6)


class VisionResult(StrictModel):
    scope_status: Literal["same_equipment", "different_equipment", "uncertain", "unreadable"]
    scope_reason: Text
    observations: list[VisionObservation] = Field(max_length=18)


class AssessmentDraft(StrictModel):
    # context_id 来自 HTTP prepare 响应，由代码绑定，不让模型生成。
    findings: list[Finding] = Field(min_length=1, max_length=6)
