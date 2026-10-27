"""Environmental prose retains selected source evidence and plain structure."""
import copy
from pathlib import Path

import pytest
import yaml
from docx import Document
from docx.oxml.ns import qn

from jonhon_taskbook.semantic_integrity_gate import run_semantic_integrity_gate
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks, extract_template_slots


@pytest.fixture
def environmental_case(tmp_path):
    source = Document()
    table = source.add_table(rows=4, cols=2)
    for row, values in zip(table.rows, [
        ("项目", "指标"), ("工作电压", "60 V DC"),
        ("工作温度", "-40℃～+85℃"), ("盐雾", "持续48 h，试验后无腐蚀"),
    ]):
        for cell, value in zip(row.cells, values):
            cell.text = value
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    block = extract_source_blocks(str(source_path), "tech")[0]
    output = Document()
    output.add_heading("环境适应性要求", 1)
    output.add_paragraph("工作温度：-40℃～+85℃。")
    output.add_paragraph("盐雾：持续48 h，试验后无腐蚀。")
    path = tmp_path / "output.docx"
    output.save(path)
    slots = extract_template_slots(str(path))
    plan = {"slots": slots, "source_blocks": [block], "decisions": [{
        "operation": "copy_exact", "source_ids": [block["id"]], "target_slot": slots[0]["id"],
    }]}
    classification = {"source_blocks": [block], "classifications": [{
        "source_id": block["id"], "category": "environmental_adaptability",
    }]}
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(yaml.safe_dump({"categories": {
        "environmental_adaptability": {"target_heading_keywords": ["环境适应性"],
                                      "target_integrity": "exact"},
        "performance_indicator": {"target_heading_keywords": ["技术指标"]},
        "insulation": {"target_heading_keywords": ["绝缘电阻"], "target_integrity": "exact"},
    }}, allow_unicode=True), encoding="utf-8")
    return path, plan, classification, mapping


def _gate(case):
    return run_semantic_integrity_gate(*case, require_complete_source_checks=True)


@pytest.mark.parametrize("category", ["environmental_adaptability", "performance_indicator"])
def test_environmental_gate_checks_projected_source_rows_without_electrical_rows(environmental_case, category):
    path, plan, classification, _ = environmental_case
    classification["classifications"][0]["category"] = category
    result = _gate(environmental_case)
    assert result["passed"], result["violations"]
    assert len(result["checked"]) == 2
    assert all(check["projection_policy"] == "environmental_prose" for check in result["checked"])
    assert [check["source_coordinates"]["table_row"] for check in result["checked"]] == [2, 3]
    assert all(check["source_fragments"] for check in result["checked"])


@pytest.mark.parametrize("category", ["environmental_adaptability", "performance_indicator"])
@pytest.mark.parametrize("change", ["omit", "change_value"])
def test_environmental_gate_requires_every_projected_value(environmental_case, category, change):
    path, _, classification, _ = environmental_case
    classification["classifications"][0]["category"] = category
    output = Document(path)
    output.paragraphs[-1].text = "" if change == "omit" else "盐雾：持续24 h，试验后无腐蚀。"
    output.save(path)
    result = _gate(environmental_case)
    assert not result["passed"]
    assert "SOURCE_EVIDENCE_MISSING_FROM_TARGET" in {item["code"] for item in result["violations"]}


@pytest.mark.parametrize("structure", ["table", "numbered", "bullet_text"])
def test_environmental_gate_rejects_tables_and_lists_even_when_evidence_is_present(environmental_case, structure):
    path, plan, _, _ = environmental_case
    output = Document(path)
    if structure == "table":
        source = Document(plan["source_blocks"][0]["source_path"])
        output.element.body.insert(-1, copy.deepcopy(source.tables[0]._tbl))
    elif structure == "numbered":
        output.paragraphs[1].style = "List Number"
    else:
        output.paragraphs[1].text = "a) " + output.paragraphs[1].text
    output.save(path)
    result = _gate(environmental_case)
    assert not result["passed"]
    assert "ENVIRONMENTAL_PROSE_REQUIRED" in {item["code"] for item in result["violations"]}


def test_empty_projection_does_not_mark_source_block_checked(environmental_case):
    path, plan, classification, _ = environmental_case
    block = plan["source_blocks"][0]
    source = Document()
    source.add_paragraph("工作电压：60 V DC。")
    source.save(block["source_path"])
    replacement = extract_source_blocks(block["source_path"], "tech")[0]
    replacement["id"] = block["id"]
    block.clear()
    block.update(replacement)
    output = Document()
    output.add_heading("环境适应性要求", 1)
    output.save(path)
    result = _gate(environmental_case)
    assert not result["passed"]
    assert result["checked"] == []
    assert "SOURCE_SEMANTIC_ROUTE_NOT_CHECKED" in {item["code"] for item in result["violations"]}


def test_environmental_projection_keeps_internal_decimal_points(environmental_case):
    path, plan, _, _ = environmental_case
    block = plan["source_blocks"][0]
    source = Document(block["source_path"])
    source.tables[0].cell(3, 1).text = "持续4.8 h，试验后无腐蚀"
    source.save(block["source_path"])
    output = Document(path)
    output.paragraphs[-1].text = "盐雾：持续48 h，试验后无腐蚀。"
    output.save(path)
    result = _gate(environmental_case)
    assert not result["passed"]
    assert "SOURCE_EVIDENCE_MISSING_FROM_TARGET" in {item["code"] for item in result["violations"]}


def test_environmental_gate_accepts_a_multiline_source_condition_in_one_paragraph(environmental_case):
    path, plan, _, _ = environmental_case
    block = plan["source_blocks"][0]
    source = Document(block["source_path"])
    source.tables[0].cell(3, 1).text = "持续48 h\n试验后无腐蚀"
    source.save(block["source_path"])
    output = Document(path)
    output.paragraphs[-1].runs[0]._r.find(qn("w:t")).text = "盐雾：持续48 h\n试验后无腐蚀。"
    output.save(path)
    result = _gate(environmental_case)
    assert result["passed"], result["violations"]


def test_non_environmental_category_keeps_exact_whole_block_validation(environmental_case):
    path, plan, classification, _ = environmental_case
    block = plan["source_blocks"][0]
    block.update(type="paragraph", text="工作温度：-40℃～+85℃。绝缘电阻不小于100 MΩ。")
    classification["classifications"][0]["category"] = "insulation"
    output = Document()
    output.add_heading("绝缘电阻", 1)
    output.add_paragraph("工作温度：-40℃～+85℃。")
    output.save(path)
    plan["slots"] = extract_template_slots(str(path))
    plan["decisions"][0]["target_slot"] = plan["slots"][0]["id"]
    result = _gate(environmental_case)
    assert not result["passed"]
    assert "SOURCE_EVIDENCE_MISSING_FROM_TARGET" in {item["code"] for item in result["violations"]}


def test_unfilled_controlled_environment_guidance_is_preserved_without_environment_source(environmental_case):
    path, plan, classification, mapping = environmental_case
    template = Path(__file__).resolve().parents[1] / "src/service/jonhon_taskbook/resources/templates/connector_taskbook.docx"
    output = Document(template)
    output.add_heading("绝缘电阻", 1)
    output.add_paragraph("绝缘电阻不小于100 MΩ。")
    output.save(path)
    block = {"id": "insulation-only", "type": "paragraph", "text": "绝缘电阻不小于100 MΩ。"}
    slots = extract_template_slots(str(path))
    target = next(slot for slot in slots if slot["title"] == "绝缘电阻")
    plan.update(slots=slots, source_blocks=[block], decisions=[{
        "operation": "copy_exact", "target_slot": target["id"], "source_ids": [block["id"]],
    }])
    classification.update(source_blocks=[block], classifications=[{
        "source_id": block["id"], "category": "insulation",
    }])
    result = _gate(environmental_case)
    assert result["passed"], result["violations"]


def test_populated_environment_section_cannot_retain_template_list_guidance(environmental_case):
    path, _, _, _ = environmental_case
    output = Document(path)
    output.add_paragraph("a) 寿命期间可能遇到的环境及其要求；")
    output.save(path)
    result = _gate(environmental_case)
    assert not result["passed"]
    assert "ENVIRONMENTAL_PROSE_REQUIRED" in {item["code"] for item in result["violations"]}
