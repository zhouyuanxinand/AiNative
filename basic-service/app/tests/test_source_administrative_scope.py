"""Source approval/history tables are evidence records, not design clauses."""
from copy import deepcopy
import base64
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from lxml import etree

from jonhon_taskbook.coverage_ledger import exclude_review_reference_sources, parse_docx_to_ledger
from jonhon_taskbook.html_reporter import generate_report
from jonhon_taskbook.semantic_orchestrator import apply_semantic_plan, extract_source_blocks, extract_template_slots
from jonhon_taskbook.source_scope import review_reference_source_details, review_reference_source_ids


# Headers and administrative wording from the actual YLZJ normalized input.
APPROVAL = [
    ["部件名称\nDatasheet Name", "液冷组件"],
    ["制造商\nManufacturer", "中航光电（JONHON）"],
    ["制造商料号\nMPN", "YLZJ-BG-469"],
    ["IEC料号", "6043B0394102"],
    ["规  格\nSpecification", "参见正文"],
    ["版本", "A1"],
    ["最终判定\nFinal Approval", "1、该部件规格经双方确认无误，达成一致，自双方签字或盖章之日起生效。\n2、该部件的规格认定以此规格承认书为准。"],
]
HISTORY = [
    ["Revision History", "", ""],
    ["Date", "Revision No.", "Description"],
    ["2025-12-23", "A1", "初始版本"],
    ["2026-06-03", "A1", "标签由\n更新为"],
    ["", "", ""],
]
REQUIREMENT = "产品工作压力应为0.3MPa。"


def _table(document, rows):
    table = document.add_table(rows=len(rows), cols=len(rows[0]))
    for target, values in zip(table.rows, rows):
        for cell, value in zip(target.cells, values):
            cell.text = value
    if rows[0][0] == "Revision History":
        table.cell(0, 0).merge(table.cell(0, 2))
    return table


def _source(tmp_path, approval=None, history=None):
    document = Document()
    document.add_heading("Specification for Approval", 1)
    _table(document, approval or APPROVAL)
    _table(document, history or HISTORY)
    document.add_heading("技术要求", 1)
    document.add_paragraph(REQUIREMENT)
    path = tmp_path / "source-records.docx"
    document.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    return path, {"source_blocks": blocks, "classifications": [
        {"source_id": block["id"], "category": "other"} for block in blocks
    ]}


def test_real_approval_and_revision_excerpts_are_archived_with_positions(tmp_path):
    path, classification = _source(tmp_path)
    original = path.read_bytes()
    details = review_reference_source_details(classification)
    assert {item["body_index"] for item in details.values()} == {1, 2}
    assert {item["reason"] for item in details.values()} == {
        "source_approval_metadata", "source_revision_metadata"}
    assert all(item["policy"] == "source_administrative_metadata_review_only" for item in details.values())
    ledger = parse_docx_to_ledger(str(path))
    references = exclude_review_reference_sources(ledger, classification)
    assert len(references) == 2
    assert all(item["semantic_source_ids"] and item["raw_text"] for item in references)
    assert all(item["rule_ref"] == "source_administrative_metadata_review_only" for item in references)
    assert [block.raw_text for block in ledger.blocks] == [REQUIREMENT]
    assert path.read_bytes() == original
    output = tmp_path / "report.docx"
    Document().save(output)
    ledger.save(output.with_suffix(".coverage_ledger.json"))
    report = Path(generate_report(str(output))).read_text(encoding="utf-8")
    assert "来源签批与修订记录" in report
    assert "Final Approval" in report and "Revision History" in report


@pytest.mark.parametrize("location,text", [
    ("spec", "工作压力应为0.3MPa"),
    ("approval", "产品必须满足耐盐雾要求，经双方确认后生效。"),
    ("revision", "工作温度由5℃~70℃调整为5℃~80℃。"),
    ("revision", "新增绝缘耐压测试要求，按技术协议执行。"),
    ("revision", "标签材料由PET改为PC。"),
    ("revision", "The operating pressure shall be at least 0.3MPa."),
])
def test_technical_or_unknown_changes_are_not_suppressed(tmp_path, location, text):
    approval, history = deepcopy(APPROVAL), deepcopy(HISTORY)
    if location == "spec":
        approval[4][1] = text
    elif location == "approval":
        approval[-1][1] = text
    else:
        history[3][2] = text
    _, classification = _source(tmp_path, approval, history)
    review_ids = review_reference_source_ids(classification)
    block = next(item for item in classification["source_blocks"] if text in item["text"])
    assert block["id"] not in review_ids


@pytest.mark.parametrize("change", [
    "工作温度应满足-40℃~85℃，不得降低考核要求。",
    "表面颜色由白色改为灰色。",
    "Material changed from PET to PC.",
])
def test_chinese_revision_table_with_technical_change_is_not_discarded_at_extraction(tmp_path, change):
    document = Document()
    document.add_heading("技术变更说明", 1)
    _table(document, [["版本", "章条编号", "改后内容"],
                      ["B", "4.1", change]])
    path = tmp_path / "technical-change.docx"
    document.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    assert len(blocks) == 1 and change in blocks[0]["text"]
    assert not review_reference_source_ids({"source_blocks": blocks})
    assert len(parse_docx_to_ledger(str(path)).blocks) == 1


@pytest.mark.parametrize("media", ["drawing", "vml", "object"])
def test_approval_specification_cell_with_media_is_not_treated_as_empty(tmp_path, media):
    document = Document()
    document.add_heading("Specification for Approval", 1)
    table = _table(document, APPROVAL)
    specification = table.cell(4, 1)
    specification.text = ""
    run = specification.paragraphs[0].add_run()
    if media == "drawing":
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5Wk3kAAAAASUVORK5CYII=")
        run.add_picture(BytesIO(png))
    elif media == "vml":
        run._r.append(etree.fromstring(b'<w:pict xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:v="urn:schemas-microsoft-com:vml"><v:shape><v:imagedata/></v:shape></w:pict>'))
    else:
        run._r.append(etree.fromstring(b'<w:object xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'))
    path = tmp_path / "approval-with-technical-media.docx"
    document.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    assert blocks and blocks[0]["has_drawing"]
    assert not review_reference_source_ids({"source_blocks": blocks})


def test_empty_chinese_revision_record_is_archived_after_structural_inspection(tmp_path):
    document = Document()
    document.add_heading("源文修订说明", 1)
    _table(document, [["序号", "版本", "章条编号", "改前内容", "改后内容"],
                      ["1", "A", "", "", "新发"]])
    path = tmp_path / "source-revision-metadata.docx"
    document.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    assert len(blocks) == 1  # Keep source evidence available for the audit.
    details = review_reference_source_details({"source_blocks": blocks})
    assert details[blocks[0]["id"]]["reason"] == "source_revision_metadata"


def test_metadata_waiver_requires_matching_source_file_and_physical_table(tmp_path):
    _, classification = _source(tmp_path)
    stale = deepcopy(classification)
    for block in stale["source_blocks"]:
        block["text"] += " 文件内容已经变化"
    assert not review_reference_source_ids(stale)
    for block in stale["source_blocks"]:
        block["source_path"] = str(tmp_path / "missing.docx")
    assert not review_reference_source_ids(stale)
    template = deepcopy(classification)
    for block in template["source_blocks"]:
        block["source"] = "template"
    assert not review_reference_source_ids(template)


def test_saved_plan_does_not_copy_metadata_and_leaves_template_revision_table_intact(tmp_path):
    _, classification = _source(tmp_path)
    output = tmp_path / "output.docx"
    target = Document()
    original_table = _table(target, [["版本", "章条编号", "改后内容"], ["A", "", "新发"]])
    original_xml = etree.tostring(original_table._tbl)
    target.add_heading("其他要求", 1)
    target.save(output)
    slots = extract_template_slots(str(output))
    plan = {"schema_version": "1.0", "policy": {"llm_may_generate_text": False,
            "allowed_operations": ["copy_exact"], "delete_requires_explicit_rule": True},
            "roles": {}, "scope": {}, "section_mappings": [], "route_audit": {},
            "slots": slots, "source_blocks": classification["source_blocks"],
            "decisions": [{"target_slot": slots[0]["id"], "operation": "copy_exact",
                           "edit_action": "append", "confidence": .99,
                           "source_ids": [item["id"] for item in classification["source_blocks"]]}]}
    evidence = apply_semantic_plan(str(output), plan)
    document = Document(output)
    assert len(document.tables) == 1
    assert etree.tostring(document.tables[0]._tbl) == original_xml
    assert REQUIREMENT in "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert len(evidence["review_only_sources"]) == 2
