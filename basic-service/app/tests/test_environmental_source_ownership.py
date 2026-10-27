"""Source packaging and figure captions cannot become environmental prose."""
import base64
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from docx import Document

from jonhon_taskbook.environmental_prose import environmental_source_rejection, project_environmental_evidence
from jonhon_taskbook.fill import _merge_classified_content
from jonhon_taskbook.semantic_integrity_gate import run_semantic_integrity_gate
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks, extract_template_slots


PACKAGING = "两块冷板均装配冷板防尘盖对导热硅脂进行防护，如图23所示。防尘盖材质PET防爆透明片材，厚度1.0mm。"
CAPTION = "图23 冷板防尘盖示意图"
TEMPERATURES = ["环境温度：5℃~42℃。", "工作温度：5℃~70℃。"]
MAPPING = Path(__file__).resolve().parents[1] / "src/service/config/liquid_cooling_pipeline_requirement_categories.yaml"


@pytest.fixture
def packaging_source(tmp_path):
    source = Document()
    source.add_heading("技术指标", 1)
    table = source.add_table(rows=3, cols=2)
    for row, values in zip(table.rows, [("项目", "指标"), ("环境温度", "5℃~42℃"), ("工作温度", "5℃~70℃")]):
        for cell, value in zip(row.cells, values):
            cell.text = value
    source.add_heading("产品包装方案", 1)
    source.add_paragraph(PACKAGING)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=")
    source.add_picture(BytesIO(png))
    source.add_paragraph(CAPTION)
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    blocks = extract_source_blocks(str(source_path), "tech")
    assert len(blocks) == 4
    classification = {"source_blocks": blocks, "classifications": [
        {"source_id": block["id"], "category": "performance_indicator" if block["type"] == "table" else "technical_support"}
        for block in blocks
    ]}
    return source, classification


def test_fill_keeps_packaging_group_out_of_environment_but_projects_mixed_technical_table(packaging_source):
    source, classification = packaging_source
    content = {}
    _merge_classified_content(content, classification, str(MAPPING), source)
    environment = content["role:environmental_adaptability"]
    assert [item["text"] for item in environment["ordered_elements"]] == TEMPERATURES
    support = content["role:technical_support"]["ordered_elements"]
    assert {item["source_id"] for item in support} == {
        block["id"] for block in classification["source_blocks"] if block["type"] != "table"
    }


@pytest.mark.parametrize("text", [PACKAGING, CAPTION, "图6 防尘试验装置", "Figure 6 Dust test setup"])
def test_packaging_components_and_captions_are_not_environmental_requirements(text):
    assert project_environmental_evidence({"id": "packaging", "type": "paragraph", "text": text,
                                           "heading_text": "产品包装方案"}) == []


@pytest.mark.parametrize("text", [
    "防尘试验：沙尘浓度10 g/m³，持续6 h；考核标准：试验后功能正常。",
    "运输温度：-40℃～70℃；持续时间：48 h。",
    "盐雾试验：中性盐雾192 h；考核标准：接触电阻增量≤5 mΩ。",
])
def test_real_environment_requirements_are_retained_even_in_support_sections(text):
    projected = project_environmental_evidence({"id": "support-environment", "type": "paragraph", "text": text,
                                                "heading_text": "包装运输要求"})
    assert [item["text"] for item in projected] == [text]


def test_packaging_is_rejected_even_under_an_environment_heading():
    block = {"id": "packaging", "type": "paragraph", "text": PACKAGING, "heading_text": "环境适应性要求"}
    assert environmental_source_rejection(block)
    assert project_environmental_evidence(block, categories={"environmental_adaptability"}) == []


def test_environmental_acceptance_for_a_protective_cap_is_not_lost():
    text = "防尘试验：沙尘浓度10 g/m³，持续6 h。防尘盖不得开裂。"
    assert [item["text"] for item in project_environmental_evidence({"id": "cap-test", "text": text})] == [text]


def test_packaging_design_does_not_continue_a_temperature_requirement():
    text = TEMPERATURES[0] + PACKAGING
    assert [item["text"] for item in project_environmental_evidence({"id": "mixed", "text": text})] == TEMPERATURES[:1]


def test_category_ownership_does_not_activate_unlabelled_support_text():
    block = {"id": "support", "text": "按运输包装方案装箱。", "heading_text": "环境适应性要求"}
    assert project_environmental_evidence(block, categories={"technical_support"}) == []


def test_media_group_caption_is_not_prose_when_its_display_number_is_absent():
    block = {"id": "caption", "type": "paragraph", "text": "防尘试验装置", "has_drawing": False,
             "media_group_id": "source-figure", "media_group_members": ["image", "caption"]}
    assert project_environmental_evidence(block) == []


@pytest.mark.parametrize("contamination", ["packaging", "caption", "missing", "changed", "clean"])
def test_gate_audits_actual_environment_without_an_environment_decision(tmp_path, packaging_source, contamination):
    source, classification = packaging_source
    output = Document()
    output.add_heading("环境适应性要求", 1)
    for text in TEMPERATURES[:1] if contamination == "missing" else TEMPERATURES:
        output.add_paragraph(text.replace("5℃~70℃", "5℃~71℃") if contamination == "changed" else text)
    if contamination == "packaging":
        output.add_paragraph(PACKAGING)
    elif contamination == "caption":
        output.add_paragraph("图28 冷板防尘盖示意图")
    output.add_heading("条件保障要求", 1)
    output.add_paragraph(PACKAGING)
    # The clean destination must contain the referenced figure as well as its
    # paragraph; the combined gate now verifies figure targets independently.
    image_part = next(rel.target_part for rel in source.part.rels.values()
                      if rel.reltype.endswith("/image"))
    output.add_picture(BytesIO(image_part.blob))
    output.add_paragraph(CAPTION)
    path = tmp_path / "output.docx"
    output.save(path)
    plan = {"slots": extract_template_slots(str(path)), "source_blocks": classification["source_blocks"], "decisions": []}
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(yaml.safe_dump({"categories": {
        "environmental_adaptability": {"target_heading_keywords": ["环境适应性"], "target_integrity": "exact"},
        "performance_indicator": {"target_heading_keywords": ["技术指标"]},
        "technical_support": {"target_heading_keywords": ["条件保障"]},
    }}, allow_unicode=True), encoding="utf-8")
    report = run_semantic_integrity_gate(path, plan, classification, mapping)
    assert report["passed"] is (contamination == "clean"), report["violations"]
    assert len([item for item in report["checked"] if item.get("projection_policy") == "environmental_prose"]) == 2
    if contamination in {"packaging", "caption"}:
        assert "ENVIRONMENTAL_UNEXPECTED_CONTENT" in {item["code"] for item in report["violations"]}
    elif contamination in {"missing", "changed"}:
        assert "SOURCE_EVIDENCE_MISSING_FROM_TARGET" in {item["code"] for item in report["violations"]}
