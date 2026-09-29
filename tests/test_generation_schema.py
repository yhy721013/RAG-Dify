import json
import re

import pytest
from pydantic import ValidationError

from app.portal.settings import PortalSettings
from app.settings import ROOT
from workflows.build_portal import build_portal
from workflows.schemas import DynamicVisionResult, generation_schema
from test_dynamic_assessment import vision


def test_prose_schema_does_not_constrain_sentences_to_one_character():
    original = DynamicVisionResult.model_json_schema()
    clean = generation_schema(original)
    old = original["$defs"]["DynamicObservation"]["properties"]["visible_fact"]
    new = clean["$defs"]["DynamicObservation"]["properties"]["visible_fact"]
    assert re.fullmatch(old["pattern"], "图")
    assert not re.fullmatch(old["pattern"], "图片中按钮周围有黄色保护结构。")
    assert "pattern" not in new and new["minLength"] == 8
    assert clean["$defs"]["DynamicObservation"]["properties"]["image_ids"] == original["$defs"]["DynamicObservation"]["properties"]["image_ids"]
    DynamicVisionResult.model_validate(vision())
    for text in ("图", " " * 10):
        bad = vision()
        bad["observations"][0]["visible_fact"] = text
        with pytest.raises(ValidationError):
            DynamicVisionResult.model_validate(bad)


@pytest.mark.parametrize("provider,model", [
    ("langgenius/openai_api_compatible/openai_api_compatible", "qwen3-vl-flash"),
    ("langgenius/siliconflow/siliconflow", "Qwen/Qwen3.5-27B"),
])
def test_both_model_nodes_and_native_schemas_have_no_prose_pattern(provider, model):
    checklist = json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))
    doc = build_portal(PortalSettings(dataset_id="test", evidence_public_url="https://example.invalid"), checklist, provider, model)
    for node in doc["workflow"]["graph"]["nodes"]:
        data = node["data"]
        if data["type"] != "llm":
            continue
        schema = data["structured_output"]["schema"]
        def inspect(value):
            if isinstance(value, dict):
                assert value.get("pattern") != r"\S"
                for child in value.values(): inspect(child)
            elif isinstance(value, list):
                for child in value: inspect(child)
        inspect(schema)
        params = data["model"]["completion_params"]
        if "json_schema" in params:
            assert json.loads(params["json_schema"])["schema"] == schema
