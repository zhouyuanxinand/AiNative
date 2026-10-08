"""Domain selection also applies to explicitly conditional schedule tables."""

from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from jonhon_taskbook.domain_sections import apply_domain_sections
from jonhon_taskbook.qa_gate import QAGate


TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src/service/jonhon_taskbook/resources/templates/connector_taskbook.docx"
)


def _text(node):
    return "".join(item.text or "" for item in node.iter(qn("w:t")))


def _schedule_tables(doc):
    active = False
    tables = []
    for node in doc.element.body:
        text = _text(node)
        if node.tag == qn("w:p") and "任务进度要求" in text and "下表" not in text:
            active = True
        elif node.tag == qn("w:p") and "研制经费预算" in text:
            active = False
        if active and node.tag == qn("w:tbl"):
            tables.append(node)
    return tables


@pytest.mark.parametrize("domain", ["military", "airworthiness", "as9100"])
def test_real_template_removes_only_inapplicable_civil_schedule_table(domain):
    doc = Document(TEMPLATE_PATH)
    original = _schedule_tables(doc)
    assert len(original) == 3
    applicable_xml = [table.xml for table in original[:2]]

    audit = apply_domain_sections(doc, domain)

    selected = _schedule_tables(doc)
    assert [table.xml for table in selected] == applicable_xml
    assert not any("对于民机产品" in paragraph.text for paragraph in doc.paragraphs)
    assert len(audit["deleted_table_branches"]) == 1
    assert audit["deleted_table_branches"][0]["removed_nodes"] == 2
    gate = QAGate({"block_if": {"civil_aircraft_table_exists": True}}, {})
    assert "民机进度表残留（项目不适用）" not in gate.check(doc.element)["block_reasons"]


def test_civil_domain_preserves_all_manual_schedule_template_content():
    doc = Document(TEMPLATE_PATH)
    tables = [table.xml for table in _schedule_tables(doc)]
    audit = apply_domain_sections(doc, "civil_aviation")
    assert [table.xml for table in _schedule_tables(doc)] == tables
    assert any("对于民机产品" in paragraph.text for paragraph in doc.paragraphs)
    assert audit["deleted_table_branches"] == []


def test_conditional_schedule_note_does_not_remove_other_sections_or_generic_tables():
    doc = Document()
    doc.add_heading("技术要求", 1)
    outside = doc.add_paragraph("（对于民机产品，任务进度要求按下表格式填写）")
    outside_table = doc.add_table(rows=1, cols=1)
    outside_table.cell(0, 0).text = "其他章节的源表格"
    doc.add_heading("任务进度要求", 1)
    shared = doc.add_paragraph("本章节引用民机标准，通用进度由设计员填写。")
    shared_table = doc.add_table(rows=2, cols=2)
    shared_table.cell(0, 0).text = "任务阶段"
    shared_table.cell(1, 0).text = "方案阶段"
    doc.add_paragraph("（对于民机产品，任务进度要求按下表格式填写）")
    doc.add_paragraph()
    doc.add_table(rows=2, cols=1).cell(0, 0).text = "民机专用阶段"
    doc.add_heading("后续章节", 1)
    following = doc.add_paragraph("后续内容必须保留")

    apply_domain_sections(doc, "military")

    assert outside._p.getparent() is not None
    assert outside_table._tbl.getparent() is not None
    assert shared._p.getparent() is not None
    assert shared_table._tbl.getparent() is not None
    assert following._p.getparent() is not None
    assert len(doc.tables) == 2
