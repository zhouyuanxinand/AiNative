"""Every delivered table uses the same font, including retained appendices."""
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from lxml import etree

from jonhon_taskbook.postprocess import postprocess
from jonhon_taskbook.docx_io import fill_cell_with_manual_marker
from jonhon_taskbook.placeholder_cleanup import final_placeholder_sweep_docx
from jonhon_taskbook.renderer.table_style_engine import normalize_imported_table_typography


def _large_cell(cell, text):
    cell.text = text
    run = cell.paragraphs[0].runs[0]
    run.font.name = "Arial"
    run.font.size = Pt(16)
    run._r.rPr.rFonts.set(qn("w:eastAsiaTheme"), "majorEastAsia")
    return run


def _assert_typography(properties):
    assert properties is not None
    fonts = properties.find(qn("w:rFonts"))
    assert fonts is not None
    for family in ("ascii", "hAnsi", "eastAsia", "cs"):
        assert fonts.get(qn(f"w:{family}")) == "仿宋"
    assert not any(key.lower().endswith("theme") for key in fonts.attrib)
    for tag in ("sz", "szCs"):
        size = properties.find(qn(f"w:{tag}"))
        assert size is not None and size.get(qn("w:val")) == "21"


def _assert_table_typography(table):
    for run in table.iter(qn("w:r")):
        _assert_typography(run.find(qn("w:rPr")))
    for paragraph in table.iter(qn("w:p")):
        _assert_typography(paragraph.find(f"{qn('w:pPr')}/{qn('w:rPr')}"))


@pytest.mark.parametrize("headers", [
    ("序号", "任务场景描述"),
    ("项目", "用户要求指标", "拟采用指标", "拟采用指标和试验的依据"),
])
def test_postprocess_applies_five_point_typography_to_retained_tables(tmp_path, headers):
    document = Document()
    cover = document.add_paragraph("封面")
    cover.runs[0].font.name, cover.runs[0].font.size = "Arial", Pt(18)
    table = document.add_table(rows=2, cols=len(headers))
    for cell, text in zip(table.rows[0].cells, headers):
        _large_cell(cell, text).bold = True
    run = _large_cell(table.cell(1, 0), "连接器场景")
    run.font.superscript = True
    run.underline = True
    table.cell(1, 1).add_table(rows=1, cols=1).cell(0, 0).text = "嵌套表内容"
    # Even a cell with no text must receive the correct typing/paragraph font.
    empty = table.cell(1, 1).paragraphs[0]
    rpr = OxmlElement("w:rPr")
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), "32")
    rpr.append(size)
    empty._p.get_or_add_pPr().append(rpr)
    output = tmp_path / "retained-table.docx"
    document.save(output)

    postprocess(output)

    result = Document(output)
    _assert_table_typography(result.tables[0]._tbl)
    assert result.paragraphs[0].runs[0].font.size.pt == 18
    assert result.paragraphs[0].runs[0].font.name == "Arial"
    assert all(c.paragraphs[0].runs[0].bold for c in result.tables[0].rows[0].cells)
    technical = result.tables[0].cell(1, 0).paragraphs[0].runs[0]
    assert technical.text == "连接器场景"
    assert technical.font.superscript is True and technical.underline is True
    assert result.tables[0].cell(1, 1).tables[0].cell(0, 0).text == "嵌套表内容"


def test_imported_table_defaults_preserve_field_and_emphasis():
    document = Document()
    table = document.add_table(rows=1, cols=2)
    run = _large_cell(table.cell(0, 0), "H")
    run.italic = True
    subscript = table.cell(0, 0).paragraphs[0].add_run("2")
    subscript.font.subscript = True
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    field_run = OxmlElement("w:r")
    field_text = OxmlElement("w:t")
    field_text.text = "1"
    field_run.append(field_text)
    field.append(field_run)
    table.cell(0, 0).paragraphs[0]._p.append(field)
    equation = OxmlElement("m:oMath")
    math_run = OxmlElement("m:r")
    math_text = OxmlElement("m:t")
    math_text.text = "x²"
    math_run.append(math_text)
    equation.append(math_run)
    table.cell(0, 0).paragraphs[0]._p.append(equation)
    equation_xml = etree.tostring(equation)

    normalize_imported_table_typography(table)

    _assert_table_typography(table._tbl)
    assert run.italic is True and subscript.font.subscript is True
    assert field.get(qn("w:instr")) == "PAGE" and field_text.text == "1"
    assert etree.tostring(equation) == equation_xml


def test_header_and_footer_tables_use_same_typography(tmp_path):
    document = Document()
    for story in (document.sections[0].header, document.sections[0].footer):
        table = story.add_table(rows=1, cols=1, width=Inches(3))
        _large_cell(table.cell(0, 0), "版本记录")
    output = tmp_path / "story-tables.docx"
    document.save(output)

    postprocess(output)

    with ZipFile(output) as archive:
        for name in ("word/header1.xml", "word/footer1.xml"):
            root = etree.fromstring(archive.read(name))
            _assert_table_typography(root.find(f".//{qn('w:tbl')}"))


def test_final_placeholder_sweep_preserves_table_typography(tmp_path):
    document = Document()
    document.add_heading("任务进度要求", 1)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "任务内容"
    table.cell(0, 1).text = "进度要求"
    table.cell(1, 0).text = "设计输入评审"
    table.cell(1, 1).text = "20xx年X月"
    output = tmp_path / "schedule.docx"
    document.save(output)

    # Production performs this content cleanup after the formatting pass.
    postprocess(output)
    assert final_placeholder_sweep_docx(output) == 1

    result = Document(output)
    assert result.tables[0].cell(1, 1).text == "—"
    _assert_table_typography(result.tables[0]._tbl)


def test_font_table_declares_installed_fangsong_name(tmp_path):
    document = Document()
    document.add_table(rows=1, cols=1).cell(0, 0).text = "任务场景"
    output = tmp_path / "fonts.docx"
    document.save(output)

    postprocess(output)

    with ZipFile(output) as archive:
        root = etree.fromstring(archive.read("word/fontTable.xml"))
    font = next((font for font in root if font.get(qn("w:name")) == "仿宋"), None)
    assert font is not None
    assert font.find(qn("w:altName")).get(qn("w:val")) == "FangSong"


def test_manual_table_marker_uses_installed_table_font():
    document = Document()
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    fill_cell_with_manual_marker(cell._tc)
    _assert_typography(cell.paragraphs[0].runs[0]._r.rPr)
