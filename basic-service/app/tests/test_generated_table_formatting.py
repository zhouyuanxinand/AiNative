"""Imported requirement tables share the taskbook's visible table geometry."""
from copy import deepcopy
from pathlib import Path
import re

import pytest
from docx import Document
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Twips

from jonhon_taskbook.postprocess import postprocess


TEMPLATES = Path(__file__).resolve().parents[1] / "src/service/jonhon_taskbook/resources/templates"
INDICATOR_HEADERS = ["项目", "用户要求指标", "拟采用指标", "拟采用指标和试验的依据"]


def _add_table(document, headers, widths):
    table = document.add_table(rows=3, cols=len(headers))
    for cell, text in zip(table.rows[0].cells, headers):
        cell.text = text
        cell.paragraphs[0].runs[0].bold = False
    for column, width in zip(table.columns, widths):
        column.width = Twips(width)
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = Twips(width)
    table._tbl.tblPr.find(qn("w:tblW")).set(qn("w:w"), str(sum(widths)))
    table._tbl.tblPr.find(qn("w:tblW")).set(qn("w:type"), "dxa")
    return table


def _grid_widths(table):
    return [column.w.twips for column in table._tbl.tblGrid.gridCol_lst]


def _table_xml_without_typography(table):
    """Compare content/layout, fonts aside, using equivalent legacy look flags."""
    root = deepcopy(table._tbl)
    # ECMA-376 table-look bits, independent of the production normalizer.
    # These fixtures carry both encodings. Only discard a named flag after
    # proving it agrees with w:val, which remains in the XML comparison.
    look_bits = {"firstRow": 0x0020, "lastRow": 0x0040,
                 "firstColumn": 0x0080, "lastColumn": 0x0100,
                 "noHBand": 0x0200, "noVBand": 0x0400}
    for look in root.iter(qn("w:tblLook")):
        mask = int(look.get(qn("w:val")), 16)
        for name, bit in look_bits.items():
            value = look.get(qn("w:" + name))
            if value is not None:
                assert value in {"0", "1", "false", "true", "off", "on"}
                assert bool(mask & bit) == (value in {"1", "true", "on"})
                del look.attrib[qn("w:" + name)]
    for properties in root.iter(qn("w:rPr")):
        for tag in ("rFonts", "sz", "szCs"):
            for node in list(properties.findall(qn(f"w:{tag}"))):
                properties.remove(node)
    for tag in ("rPr", "pPr"):
        for node in list(root.iter(qn(f"w:{tag}"))):
            if not len(node) and not node.attrib:
                node.getparent().remove(node)
    return root.xml


def _assert_legacy_table_looks(table):
    for look in table._tbl.iter(qn("w:tblLook")):
        assert set(look.attrib) == {qn("w:val")}
        assert re.fullmatch(r"[0-9A-Fa-f]{4}", look.get(qn("w:val")))


def _save_and_process(document, tmp_path):
    output = tmp_path / "taskbook.docx"
    document.save(output)
    postprocess(str(output), preserve_template_guidance=True)
    return Document(output)


@pytest.mark.parametrize("indicator_widths", [(1000, 2000, 1500, 1500), (1000, 1000, 2000, 1000, 1000)])
def test_imported_table_and_indicator_keep_column_ratios_at_same_body_width(tmp_path, indicator_widths):
    document = Document()
    section = document.sections[0]
    section.page_width = Twips(12000)
    section.left_margin = section.right_margin = Twips(2400)
    cover = _add_table(document, ["签名", "日期"], (2000, 2000))
    cover_xml = _table_xml_without_typography(cover)
    document.add_heading("技术要求", 1)
    headers = INDICATOR_HEADERS if len(indicator_widths) == 4 else [*INDICATOR_HEADERS, "补充说明"]
    _add_table(document, headers, indicator_widths)
    document.add_heading("安装方式", 2)
    imported = _add_table(document, ["项目", "要求"], (1000, 3000))
    floating = OxmlElement("w:tblpPr")
    floating.set(qn("w:tblpX"), "0")
    imported._tbl.tblPr.append(floating)
    imported.cell(1, 0).text = "安装固定方式"
    imported.cell(1, 1).text = "印制板焊接（通孔波峰焊）"
    imported.cell(2, 0).merge(imported.cell(2, 1)).text = "合并备注：保留原始技术要求。"
    imported.rows[1].height = Twips(420)
    # A source document can combine a DXA grid with percentage cell widths.
    for cell in imported.rows[0].cells:
        cell._tc.tcPr.find(qn("w:tcW")).set(qn("w:type"), "pct")
    nested = imported.cell(1, 1).add_table(rows=2, cols=2)
    nested.columns[0].width = nested.columns[1].width = Twips(300)
    nested_xml = _table_xml_without_typography(nested)
    texts = [[cell.text for cell in row.cells] for row in imported.rows]

    result = _save_and_process(document, tmp_path)

    _assert_legacy_table_looks(result.tables[0])
    assert _table_xml_without_typography(result.tables[0]) == cover_xml
    indicator, imported = result.tables[1:]
    expected = ([1200, 2400, 1800, 1800] if len(indicator_widths) == 4
                else [1200, 1200, 2400, 1200, 1200])
    assert _grid_widths(indicator) == expected
    assert _grid_widths(imported) == [1800, 5400]
    for table in (indicator, imported):
        width = table._tbl.tblPr.find(qn("w:tblW"))
        assert (width.get(qn("w:type")), width.get(qn("w:w"))) == ("dxa", "7200")
        assert table._tbl.tblPr.find(qn("w:jc")).get(qn("w:val")) == "left"
    assert [[cell.text for cell in row.cells] for row in imported.rows] == texts
    assert imported.cell(2, 0)._tc.tcPr.find(qn("w:gridSpan")).get(qn("w:val")) == "2"
    assert imported.cell(2, 0).width.twips == 7200
    assert imported.rows[1].height.twips == 420
    nested = imported.cell(1, 1).tables[0]
    _assert_legacy_table_looks(nested)
    assert _table_xml_without_typography(nested) == nested_xml
    assert imported._tbl.tblPr.find(qn("w:tblpPr")) is None


def test_all_header_runs_and_entire_header_bottom_rule_are_emphasized(tmp_path):
    document = Document()
    document.add_heading("技术要求", 1)
    indicator = _add_table(document, INDICATOR_HEADERS, (1000, 2000, 1500, 1500))
    imported = _add_table(document, ["项目", "要求"], (1000, 3000))
    for table in (indicator, imported):
        table.cell(0, 1).paragraphs[0].add_run("（补充）").bold = False
        table.cell(1, 0).text = "安装固定方式"
        table.cell(1, 0).paragraphs[0].runs[0].bold = False
        for cell in table.rows[0].cells:
            borders = OxmlElement("w:tcBorders")
            bottom = OxmlElement("w:bottom")
            bottom.set(qn("w:val"), "nil")
            borders.append(bottom)
            cell._tc.get_or_add_tcPr().append(borders)

    result = _save_and_process(document, tmp_path)

    for table in result.tables:
        for cell in table.rows[0].cells:
            assert all(run.bold is True for paragraph in cell.paragraphs for run in paragraph.runs)
            bottom = cell._tc.tcPr.find(f"{qn('w:tcBorders')}/{qn('w:bottom')}")
            assert (bottom.get(qn("w:val")), bottom.get(qn("w:sz"))) == ("single", "12")
        assert table.cell(1, 0).paragraphs[0].runs[0].bold is False
        body_rule = table.cell(1, 0)._tc.tcPr.find(f"{qn('w:tcBorders')}/{qn('w:bottom')}")
        assert body_rule.get(qn("w:sz")) == "4"


def test_table_width_uses_its_own_section_instead_of_cover_section(tmp_path):
    document = Document()
    first = document.sections[0]
    first.page_width = Twips(12000)
    first.left_margin = first.right_margin = Twips(2400)
    document.add_heading("第一节", 1)
    _add_table(document, ["项目", "要求"], (1000, 3000))
    second = document.add_section(WD_SECTION.NEW_PAGE)
    second.page_width = Twips(12000)
    second.left_margin = second.right_margin = Twips(1800)
    document.add_heading("第二节", 1)
    _add_table(document, ["项目", "要求"], (1000, 3000))

    result = _save_and_process(document, tmp_path)

    assert _grid_widths(result.tables[0]) == [1800, 5400]
    assert _grid_widths(result.tables[1]) == [2100, 6300]


def test_real_filter_template_indicator_and_copied_interface_table_match(tmp_path):
    document = Document(TEMPLATES / "filter_connector_taskbook.docx")
    indicator = next(table for table in document.tables if "用户要求指标" in table.rows[0].cells[1].text)
    imported = _add_table(document, ["项目", "要求"], (1000, 3000))
    imported.cell(1, 0).text = "插座安装固定方式"
    imported.cell(1, 1).text = "印制板焊接（通孔波峰焊）"
    indicator._tbl.addnext(imported._tbl)

    result = _save_and_process(document, tmp_path)

    indicator = next(table for table in result.tables if "用户要求指标" in table.rows[0].cells[1].text)
    imported = next(table for table in result.tables if table.cell(1, 0).text == "插座安装固定方式")
    assert sum(_grid_widths(indicator)) == sum(_grid_widths(imported)) == 9355
    assert _grid_widths(imported) == [2338, 7017]
    assert all(run.bold for table in (indicator, imported) for cell in table.rows[0].cells
               for paragraph in cell.paragraphs for run in paragraph.runs if run.text)
