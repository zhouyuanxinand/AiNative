"""QA distinguishes source notation from unresolved document placeholders."""

from docx import Document
import pytest
from jonhon_taskbook.delivery_gate import scan_document_completeness
from jonhon_taskbook.document_zone_detector import scan_document_zones

SERIAL_CODE_RULE = "-E-最后三码(XXX)为流水码，使用Base-36系统(0-9, A-Z)，从001到ZZZ。"


def test_delivery_accepts_explanatory_serial_code_notation(tmp_path):
    output = tmp_path / "taskbook.docx"
    document = Document()
    document.add_paragraph(SERIAL_CODE_RULE)
    document.save(output)

    result = scan_document_completeness(str(output), [])

    assert not any(defect["code"] == "INCOMPLETE" for defect in result["defects"])


def test_fill_zone_accepts_explanatory_serial_code_notation(tmp_path):
    output = tmp_path / "taskbook.docx"
    document = Document()
    document.add_paragraph(SERIAL_CODE_RULE)
    document.save(output)

    result = scan_document_zones(str(output))

    assert not any(zone["zone_type"] == "PLACEHOLDER" for zone in result["zones"])


def test_separate_xxx_in_same_paragraph_still_blocks_delivery(tmp_path):
    output = tmp_path / "taskbook.docx"
    document = Document()
    document.add_paragraph(SERIAL_CODE_RULE + " 审批人：XXX")
    document.save(output)

    completeness = scan_document_completeness(str(output), [])
    zones = scan_document_zones(str(output))

    assert any(defect["label"] == "xxx占位符" for defect in completeness["defects"])
    assert any(zone["zone_type"] == "PLACEHOLDER" for zone in zones["zones"])


@pytest.mark.parametrize('values,literal', [
    (('34', '35', '...'), True),
    (('00Y', '00Z', '...'), True),
    (('34', '40', '...'), False),
    (('项目', '要求', '...'), False),
])
def test_sequential_table_notation_is_not_a_missing_value(tmp_path, values, literal):
    output = tmp_path / 'sequence.docx'
    document = Document()
    table = document.add_table(rows=1, cols=3)
    for cell, text in zip(table.rows[0].cells, values):
        cell.text = text
    document.save(output)

    completeness = scan_document_completeness(str(output), [])
    zones = scan_document_zones(str(output))
    assert any(defect['label'] == '省略号占位符' for defect in completeness['defects']) is not literal
    assert any(zone['zone_type'] == 'PLACEHOLDER' for zone in zones['zones']) is not literal
