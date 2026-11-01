"""Regression excerpts from the YLZJ source: exact text must stay meaningful."""
from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from jonhon_taskbook.requirement_classifier import (
    _partition_mixed_blocks_with_llm,
    build_requirement_classification,
    load_category_mapping,
)
from jonhon_taskbook.semantic_orchestrator import (
    _backfill_classified_routes,
    _configured_category_slots,
    extract_template_slots,
)
from jonhon_taskbook.source_scope import review_reference_source_ids


SERVICE = Path(__file__).resolve().parents[1] / "src/service"
MAPPING = SERVICE / "config/liquid_cooling_pipeline_requirement_categories.yaml"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5Wk3kAAAAASUVORK5CYII="
)
PACKAGING = "两块冷板均装配冷板防尘盖对导热硅脂进行防护，如图23所示。防尘盖材质PET防爆透明片材，厚度1.0mm。"
BOX = "单套液冷组件使用吸塑盒进行防护包装，如图24所示。每5套液冷组件放入一个纸箱包装。"
EQUIPMENT = "8、泄漏测试：真空箱氦检设备"
PRESSURE = "测试内容：58psi氮气，保压30min，泄漏值＜3%。"


def _partition(text, fragments, *, return_partition=True):
    mapping = load_category_mapping(str(MAPPING))
    block = {"id": "original", "type": "paragraph", "text": text,
             "heading_text": "综合要求", "parent_headings": [], "has_drawing": False}
    assignment = {"source_id": "original", "category": "other", "confidence": .95}

    def respond(_system, user):
        payload = json.loads(user)
        if payload["node"] == "requirement_exact_fragment_routing":
            return {"partitions": [{"source_id": "original", "fragments": [
                {"text": value, "category": category, "confidence": .94}
                for value, category in fragments
            ]}] if return_partition else []}
        assert payload["node"] == "requirement_classification"
        return {"classifications": [
            {"source_id": member["source_id"], "confidence": .94,
             "category": next((category for value, category in fragments
                               if value == member["text"]), "other")}
            for member in payload["blocks"]
        ]}

    return _partition_mixed_blocks_with_llm(
        [block], [assignment], mapping["categories"],
        {**mapping["exact_fragment_routing"], "min_text_length": 8}, respond)


@pytest.mark.parametrize("return_partition", [True, False])
def test_model_or_comma_fallback_cannot_separate_material_from_its_thickness(return_partition):
    text = "防尘盖材质PET防爆透明片材，厚度1.0mm。"
    blocks, assignments, audit = _partition(text, [
        ("防尘盖材质PET防爆透明片材，", "process_requirement"),
        ("厚度1.0mm。", "outline_dimension"),
    ], return_partition=return_partition)
    assert [block["text"] for block in blocks] == [text]
    assert [item["category"] for item in assignments] == ["other"]
    assert not audit


def test_a_figure_reference_is_not_an_independent_other_requirement():
    text = "防护罩应保护导热界面。如图23所示。"
    blocks, _, audit = _partition(text, [
        ("防护罩应保护导热界面。", "technical_support"),
        ("如图23所示。", "other"),
    ])
    assert [block["text"] for block in blocks] == [text]
    assert not audit


@pytest.mark.parametrize("separator", ["。", "；"])
def test_independent_complete_requirements_can_still_route_without_rewriting(separator):
    fragments = [("壳体采用黄铜" + separator, "process_requirement"),
                 ("产品外形长20mm、宽10mm。", "outline_dimension")]
    text = "".join(value for value, _ in fragments)
    blocks, assignments, audit = _partition(text, fragments)
    assert [block["text"] for block in blocks] == [value for value, _ in fragments]
    assert [item["category"] for item in assignments] == [category for _, category in fragments]
    assert "".join(block["text"] for block in blocks) == text
    assert audit[0]["reconstructed_exactly"]


def test_packaging_and_test_modules_keep_context_and_raw_results_remain_review_only(tmp_path):
    source = Document()
    source.add_heading("产品规格书", 1)
    source.add_heading("产品包装方案", 1)
    source.add_paragraph(PACKAGING)
    source.add_picture(BytesIO(PNG))
    source.add_paragraph("图23 冷板防尘盖示意图")
    source.add_paragraph(BOX)
    source.add_picture(BytesIO(PNG))
    source.add_paragraph("图24 吸塑盒包装示意图")
    source.add_heading("出厂测试项目", 1)
    table = source.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "项目", "判定标准"
    table.cell(1, 0).text, table.cell(1, 1).text = "氮气保压", "58psi保压30min，泄漏值＜3%"
    criterion_text = "".join(cell.text for row in table.rows for cell in row.cells)
    source.add_heading("测试设备及测试结果", 1)
    source.add_heading(EQUIPMENT, 2)
    source.add_picture(BytesIO(PNG))
    source.add_paragraph("泄漏测试结果：")
    table = source.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "样品编号", "实测泄漏值/(Pa.m3/s)"
    table.cell(1, 0).text, table.cell(1, 1).text = "1", "2.4×10-6"
    result_text = "".join(cell.text for row in table.rows for cell in row.cells)
    source.add_heading("保压测试-58psi", 2)
    source.add_paragraph(PRESSURE)
    path = tmp_path / "ylzj-excerpts.docx"
    source.save(path)
    calls = []

    def respond(_system, user):
        payload = json.loads(user)
        calls.append(payload)
        if payload["node"] == "source_structure":
            return {"headings": []}
        if payload["node"] == "requirement_exact_fragment_routing":
            return {"partitions": []}
        assert payload["node"] == "requirement_classification"
        return {"classifications": [
            {"source_id": member["source_id"], "category": "other", "confidence": .90}
            for member in payload["blocks"]
        ]}

    report = build_requirement_classification(str(path), str(MAPPING), chat_json_fn=respond)
    categories = {item["source_id"]: item["category"] for item in report["classifications"]}
    by_text = {block["text"]: block for block in report["source_blocks"]}
    for text in (PACKAGING, BOX, "图23 冷板防尘盖示意图", "图24 吸塑盒包装示意图"):
        assert categories[by_text[text]["id"]] == "technical_support"
    for text in (EQUIPMENT, PRESSURE, criterion_text):
        assert categories[by_text[text]["id"]] == "testability", by_text[text]
    offered = {block["text"] for call in calls if call["node"] == "requirement_exact_fragment_routing"
               for block in call["blocks"]}
    assert not {PACKAGING, BOX, PRESSURE}.intersection(offered)

    slots = extract_template_slots(str(SERVICE / "jonhon_taskbook/resources/templates/liquid_cooling_pipeline_taskbook.docx"))
    routes, _ = _backfill_classified_routes([], slots, report["source_blocks"], report, str(MAPPING))
    target_by_category = _configured_category_slots(slots, str(MAPPING))
    routed = {source_id: decision["target_slot"] for decision in routes for source_id in decision["source_ids"]}
    assert routed[by_text[PACKAGING]["id"]] == target_by_category["technical_support"]
    for text in (EQUIPMENT, PRESSURE, criterion_text):
        assert routed[by_text[text]["id"]] == target_by_category["testability"]
    assert by_text[result_text]["id"] in review_reference_source_ids(report)
    assert by_text[result_text]["id"] not in routed


@pytest.mark.parametrize("heading,expected,text", [
    ("产品包装方案", "technical_support", PACKAGING),
    ("包装要求", "technical_support", BOX),
    ("出厂测试项目", "testability", PRESSURE),
    ("出厂检验项目", "testability", PRESSURE),
])
def test_nested_modules_inherit_the_owner_but_not_the_next_sibling(tmp_path, heading, expected, text):
    document = Document()
    document.add_heading(heading, 1)
    document.add_heading("冷板防护" if expected == "technical_support" else "气密检测", 2)
    document.add_heading("实施说明", 3)
    document.add_paragraph(text)
    document.add_picture(BytesIO(PNG))
    document.add_heading("独立设计说明", 1)
    unrelated = "另一零件按其独立技术规范执行。"
    document.add_paragraph(unrelated)
    path = tmp_path / "nested-source-modules.docx"
    document.save(path)
    offered = []

    def respond(_system, user):
        payload = json.loads(user)
        if payload["node"] == "source_structure":
            return {"headings": []}
        if payload["node"] == "requirement_exact_fragment_routing":
            offered.extend(item["text"] for item in payload["blocks"])
            # These are complete sentences, so the general punctuation guard
            # cannot protect their shared packaging object. The module must.
            return {"partitions": [
                {"source_id": item["source_id"], "fragments": [
                    {"text": item["text"].split("。", 1)[0] + "。", "category": "safety", "confidence": .9},
                    {"text": item["text"].split("。", 1)[1], "category": "process_requirement", "confidence": .9},
                ]} for item in payload["blocks"]
                if "。" in item["text"] and item["text"].split("。", 1)[1]
            ]}
        assert payload["node"] == "requirement_classification"
        return {"classifications": [
            {"source_id": item["source_id"], "category": "other", "confidence": .94}
            for item in payload["blocks"]
        ]}

    report = build_requirement_classification(str(path), str(MAPPING), chat_json_fn=respond)
    assignments = {item["source_id"]: item["category"] for item in report["classifications"]}
    members = [item for item in report["source_blocks"] if heading in item["parent_headings"]]
    assert len(members) == 2  # One complete paragraph and its image.
    assert {assignments[item["id"]] for item in members} == {expected}
    assert any(item["text"] == text and not item.get("is_fragment") for item in members)
    assert text not in offered
    sibling = next(item for item in report["source_blocks"] if item["text"] == unrelated)
    assert assignments[sibling["id"]] == "other"
    assert not report["fragment_partitions"]


@pytest.mark.parametrize("parent,child,expected,outside_category,text", [
    ("产品包装方案", "外形尺寸", "technical_support", "outline_dimension", PACKAGING),
    ("出厂测试项目", "安全性定性要求", "testability", "safety", PRESSURE),
])
def test_explicit_atomic_parent_keeps_typed_children_without_affecting_other_modules(
    tmp_path, parent, child, expected, outside_category, text,
):
    document = Document()
    document.add_heading(parent, 1)
    document.add_heading(child, 2)
    document.add_paragraph(text)
    document.add_heading("独立设计要求", 1)
    document.add_heading(child, 2)
    outside = "独立产品的设计要求按此条执行。"
    document.add_paragraph(outside)
    path = tmp_path / "typed-child-heading.docx"
    document.save(path)

    def respond(_system, user):
        payload = json.loads(user)
        if payload["node"] == "source_structure":
            return {"headings": []}
        if payload["node"] == "requirement_exact_fragment_routing":
            return {"partitions": []}
        return {"classifications": [
            {"source_id": item["source_id"], "category": "other", "confidence": .94}
            for item in payload["blocks"]
        ]}

    report = build_requirement_classification(str(path), str(MAPPING), chat_json_fn=respond)
    assignments = {item["source_id"]: item["category"] for item in report["classifications"]}
    by_text = {item["text"]: item for item in report["source_blocks"]}
    assert assignments[by_text[text]["id"]] == expected
    assert assignments[by_text[outside]["id"]] == outside_category
