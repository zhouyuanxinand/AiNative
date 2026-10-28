"""Historical failure evidence fits each controlled template's actual fields."""
from tests.support.paths import APP_ROOT
import io
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.table import _Cell

from jonhon_taskbook.fill import _fill_failure_mode_table, _find_failure_mode_table
from jonhon_taskbook.delivery_gate import scan_document_completeness
from jonhon_taskbook.failure_table_schema import has_independent_failure_cells


TEMPLATE_ROOT = APP_ROOT / "src/service/jonhon_taskbook/resources/templates"
RECORD = {
    "product_name": "设备柜", "product_series": "CAB-01", "failure_location": "连接部位",
    "failure_mode": "连接松脱\n信号中断", "failure_analysis": "原因原文第一行\n原因原文第二行",
    "reliability_design_method": "增加限位\n验证后固化工艺",
}


def roundtrip(document):
    output = io.BytesIO()
    document.save(output)
    return Document(io.BytesIO(output.getvalue()))


def test_real_system_template_keeps_five_columns_and_complete_failure_causes():
    document = Document(TEMPLATE_ROOT / "system_integration_taskbook.docx")
    table = _find_failure_mode_table(document)
    assert table is not None
    header = [cell.text for cell in table.rows[0].cells]
    assert len(header) == 5
    assert _fill_failure_mode_table(document, [RECORD]) == 1
    actual = _find_failure_mode_table(roundtrip(document))
    assert [cell.text for cell in actual.rows[0].cells] == header
    assert len(actual._tbl.tblGrid.findall(qn("w:gridCol"))) == 5
    assert len(actual.rows) == 2 and len(actual.rows[1].cells) == 5
    assert [cell.text for cell in actual.rows[1].cells] == [
        RECORD["product_name"], RECORD["failure_location"], RECORD["failure_mode"],
        RECORD["failure_analysis"], RECORD["reliability_design_method"],
    ]


@pytest.mark.parametrize("headers,keys", [
    (["型号", "失效部位", "失效模式", "失效机理", "预防措施"],
     ["product_series", "failure_location", "failure_mode", "failure_analysis", "reliability_design_method"]),
    (["故障原因", "故障模式", "产品名称", "改进措施", "故障部位"],
     ["failure_analysis", "failure_mode", "product_name", "reliability_design_method", "failure_location"]),
    (["产品型号", "失效部位", "故障现象", "失效模式机理", "设计改进措施"],
     ["product_series", "failure_location", "failure_mode", "failure_analysis", "reliability_design_method"]),
])
def test_historical_table_is_filled_by_header_not_position(headers, keys):
    document = Document()
    table = document.add_table(rows=2, cols=5)
    for cell, value in zip(table.rows[0].cells, headers):
        cell.text = value
    assert _fill_failure_mode_table(document, [RECORD]) == 1
    actual = roundtrip(document).tables[0]
    assert [cell.text for cell in actual.rows[0].cells] == headers
    assert [cell.text for cell in actual.rows[1].cells] == [RECORD[key] for key in keys]
    assert len(actual.rows[1]._tr.findall(qn("w:tc"))) == 5


def test_model_identity_table_has_visible_no_match_message():
    document = Document()
    table = document.add_table(rows=2, cols=5)
    for cell, value in zip(table.rows[0].cells, ["产品型号", "失效部位", "失效模式", "失效机理", "预防措施"]):
        cell.text = value
    assert _fill_failure_mode_table(document, [], no_match_message="未查询到历史故障信息") == 1
    assert [cell.text for cell in roundtrip(document).tables[0].rows[1].cells] == ["未查询到历史故障信息", "", "", "", ""]


def test_legacy_merged_analysis_column_remains_five_distinct_fields():
    document = Document()
    table = document.add_table(rows=2, cols=6)
    table.cell(0, 3).merge(table.cell(0, 4))
    table.cell(1, 3).merge(table.cell(1, 4))
    headers = ["数据所属产品", "失效部位", "失效模式", "失效分析", "可靠性设计方法"]
    for cell, value in zip(table.rows[0]._tr.findall(qn("w:tc")), headers):
        _Cell(cell, table).text = value
    assert _fill_failure_mode_table(document, [RECORD]) == 1
    actual = roundtrip(document).tables[0]
    assert len(actual.rows[0].cells) == len(actual.rows[1].cells) == 6
    assert has_independent_failure_cells(actual._tbl)
    assert [_Cell(cell, actual).text for cell in actual.rows[1]._tr.tc_lst] == [
        RECORD["product_name"], RECORD["failure_location"], RECORD["failure_mode"],
        RECORD["failure_analysis"], RECORD["reliability_design_method"],
    ]


@pytest.mark.parametrize("no_match", [False, True])
def test_real_optical_cable_table_preserves_analysis_span_and_passes_schema(tmp_path, no_match):
    document = Document(TEMPLATE_ROOT / "optical_cable_assembly_taskbook.docx")
    table = _find_failure_mode_table(document)
    assert table is not None
    headers = [_Cell(cell, table).text for cell in table.rows[0]._tr.tc_lst]
    grid_xml = table._tbl.tblGrid.xml
    assert len(table.rows[0]._tr.tc_lst) == 5 and len(table.rows[0].cells) == 6
    assert _fill_failure_mode_table(document, [] if no_match else [RECORD, RECORD],
                                   no_match_message="未查询到历史故障信息") == (1 if no_match else 2)
    output = tmp_path / "optical-cable-history.docx"
    document.save(output)
    actual = _find_failure_mode_table(Document(output))
    assert [_Cell(cell, actual).text for cell in actual.rows[0]._tr.tc_lst] == headers
    assert actual._tbl.tblGrid.xml == grid_xml
    assert has_independent_failure_cells(actual._tbl)
    expected = (["未查询到历史故障信息", "", "", "", ""] if no_match else [
        RECORD["product_name"], RECORD["failure_location"], RECORD["failure_mode"],
        RECORD["failure_analysis"], RECORD["reliability_design_method"],
    ])
    for row in actual.rows[1:]:
        assert [_Cell(cell, actual).text for cell in row._tr.tc_lst] == expected
    defects = scan_document_completeness(str(output), [])["defects"]
    assert not any(defect["code"] == "FAILURE_TABLE_SCHEMA" for defect in defects)


@pytest.mark.parametrize("mutation", ["cross_field", "shifted_span", "vertical_merge"])
def test_optical_cable_history_does_not_accept_merges_across_semantic_fields(tmp_path, mutation):
    from docx.oxml import OxmlElement
    document = Document(TEMPLATE_ROOT / "optical_cable_assembly_taskbook.docx")
    table = _find_failure_mode_table(document)
    if mutation == "cross_field":
        table.cell(1, 3).merge(table.cell(1, 5))
    elif mutation == "shifted_span":
        cells = table.rows[1]._tr.tc_lst
        span = cells[3].tcPr.find(qn("w:gridSpan"))
        cells[3].tcPr.remove(span)
        cells[4].get_or_add_tcPr().append(span)
    else:
        table.rows[1]._tr.tc_lst[0].get_or_add_tcPr().append(OxmlElement("w:vMerge"))
    output = tmp_path / "invalid-optical-cable-history.docx"
    document.save(output)
    assert not has_independent_failure_cells(table._tbl)
    defects = scan_document_completeness(str(output), [])["defects"]
    assert any(defect["code"] == "FAILURE_TABLE_SCHEMA" for defect in defects)


def test_potential_fmea_table_is_not_populated_with_historical_records():
    document = Document()
    table = document.add_table(rows=2, cols=5)
    for cell, value in zip(table.rows[0].cells, ["序号", "可能发生的失效模式", "失效模式机理", "失效模式后果/影响", "可考虑的解决办法"]):
        cell.text = value
    before = table._tbl.xml
    assert _fill_failure_mode_table(document, [RECORD]) == 0
    assert table._tbl.xml == before
