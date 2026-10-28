"""Cover values keep their column and do not push the publication date away."""
from tests.support.paths import APP_ROOT

from datetime import date
from pathlib import Path

import pytest
from docx import Document
from docx.enum.text import WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Twips

from jonhon_taskbook.cover_fields import fill_cover_fields


TODAY = date(2026, 10, 8)
TEMPLATES = APP_ROOT / "src/service/jonhon_taskbook/resources/templates"


def field(document, label, *, runs=3, indent=2100):
    p = document.add_paragraph()
    p.paragraph_format.first_line_indent = Twips(indent)
    p.paragraph_format.line_spacing = Pt(22)
    p.paragraph_format.space_after = Pt(0)
    values = [label + "：     "] if runs == 1 else ([label + "：", "     "] if runs == 2 else [label, "：", "     "])
    for value in values:
        run = p.add_run(value)
        run.font.name, run.font.size = "黑体", Pt(15)
    p.runs[-1].underline = True
    return p


def make_cover(*, runs=3, indent=2100):
    d = Document()
    d.add_paragraph("研 制 任 务 书")
    name = field(d, "名    称", runs=runs, indent=indent)
    unit = field(d, "使用单位", runs=2, indent=indent)
    blanks = []
    for _ in range(4):
        p = d.add_paragraph()
        p.paragraph_format.line_spacing = Pt(22)
        p.paragraph_format.space_after = Pt(0)
        blanks.append(p)
    company = d.add_paragraph("某科技股份有限公司")
    dated = d.add_paragraph("20   年   月")
    dated.runs[0].font.size = Pt(16)
    d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    body = d.add_paragraph("名称：正文原文不可变")
    return d, name, unit, blanks, company, dated, body


@pytest.mark.parametrize("runs", [1, 2, 3])
def test_multiline_product_preserves_value_styles_and_uses_value_column(runs):
    d, name, unit, _, _, _, body = make_cover(runs=runs)
    before_body = body._p.xml
    result = fill_cover_fields(d, "MODEL-A\nMODEL-B", "用户单位", TODAY)
    assert name.text == "名    称：MODEL-A\nMODEL-B"
    assert unit.text == "使用单位：用户单位"
    assert name.runs[-1].underline
    assert name.runs[-1].font.size.pt == 15
    assert name.runs[-1].font.name == "黑体"
    ind = name._p.pPr.find(qn("w:ind"))
    assert ind.get(qn("w:left")) == "3600"
    assert ind.get(qn("w:hanging")) == "1500"
    assert ind.get(qn("w:firstLine")) is None
    assert ind.get(qn("w:firstLineChars")) == "0"
    assert result["continuation_lines"] == 1
    assert body._p.xml == before_body


def test_extra_name_and_unit_lines_reclaim_only_cover_spacing_and_are_idempotent():
    d, name, unit, blanks, company, dated, _ = make_cover()
    result = fill_cover_fields(d, "MODEL-A\nMODEL-B", "用户甲\n用户乙", TODAY)
    assert result["removed_spacers"] == 2
    assert len([p for p in blanks if p._p.getparent() is not None]) == 2
    assert company.paragraph_format.keep_with_next
    assert dated.paragraph_format.keep_together
    assert dated.text == "2026年10月8日"
    before = d.element.xml
    second = fill_cover_fields(d, "MODEL-A\nMODEL-B", "用户甲\n用户乙", TODAY)
    assert second["removed_spacers"] == 0
    assert d.element.xml == before


def test_filter_indent_and_single_line_do_not_move_label_or_remove_spacing():
    d, name, _, blanks, _, _, _ = make_cover(indent=480)
    result = fill_cover_fields(d, "MODEL-A", "用户", TODAY)
    ind = name._p.pPr.find(qn("w:ind"))
    assert int(ind.get(qn("w:left"))) - int(ind.get(qn("w:hanging"))) == 480
    assert result["removed_spacers"] == 0
    assert all(p._p.getparent() is not None for p in blanks)


def test_multiple_new_lines_reclaim_grid_height_rather_than_spacer_count():
    d, name, _, blanks, _, _, _ = make_cover()
    name.paragraph_format.line_spacing_rule = WD_LINE_SPACING.AT_LEAST
    grid = OxmlElement("w:docGrid")
    grid.set(qn("w:type"), "linesAndChars")
    grid.set(qn("w:linePitch"), "312")
    old_grid = d.sections[0]._sectPr.find(qn("w:docGrid"))
    if old_grid is not None:
        d.sections[0]._sectPr.remove(old_grid)
    d.sections[0]._sectPr.append(grid)
    # Two added 31.2 pt lines need 62.4 pt, not two 22 pt spacer paragraphs.
    result = fill_cover_fields(d, "A\nB\nC", "用户", TODAY)
    assert result["removed_spacers"] == 2
    surviving = [p for p in blanks if p._p.getparent() is not None]
    assert sum(p.paragraph_format.line_spacing.twips for p in surviving) == 4 * 440 - 2 * 624
    assert surviving[-1].paragraph_format.line_spacing_rule == WD_LINE_SPACING.EXACTLY
    before = d.element.xml
    fill_cover_fields(d, "A\nB\nC", "用户", TODAY)
    assert d.element.xml == before


def test_cover_date_section_break_and_protected_empty_content_are_preserved():
    d, _, _, blanks, _, dated, _ = make_cover()
    protected = blanks[-1]
    run = protected.add_run()
    fld = OxmlElement("w:fldChar")
    fld.set(qn("w:fldCharType"), "begin")
    run._r.append(fld)
    protected_xml = protected._p.xml
    sect = OxmlElement("w:sectPr")
    sect.append(OxmlElement("w:pgSz"))
    dated._p.get_or_add_pPr().append(sect)
    original_sect = sect.xml
    fill_cover_fields(d, "MODEL-A\nMODEL-B", "用户", TODAY)
    assert protected._p.xml == protected_xml
    assert dated._p.pPr.find(qn("w:sectPr")).xml == original_sect
    assert dated.text == "2026年10月8日"


def test_body_fields_after_heading_or_change_record_are_not_filled():
    for boundary in ["变更记录", "产品的功能用途"]:
        d = Document()
        name = field(d, "产品名称")
        d.add_paragraph(boundary, style="Heading 1" if boundary != "变更记录" else None)
        body = field(d, "产品名称")
        before = body._p.xml
        fill_cover_fields(d, "X\nY", "用户", TODAY)
        assert name.text == "产品名称：X\nY"
        assert body._p.xml == before


@pytest.mark.parametrize("template", sorted(TEMPLATES.rglob("*.docx")), ids=lambda p: p.stem)
def test_all_controlled_templates_fill_cover_and_preserve_next_section(template):
    d = Document(template)
    company = next(p for p in d.paragraphs if "中航光电科技股份有限公司" in p.text)
    company_index = next(i for i, p in enumerate(d.paragraphs) if p._p is company._p)
    dated = d.paragraphs[company_index + 1]
    date_boundaries = [node.xml for node in dated._p.xpath("./w:pPr/w:sectPr | .//w:br")]
    subsequent_xml = [p._p.xml for p in d.paragraphs[company_index + 2:]]
    result = fill_cover_fields(d, "TEST-MODEL-A\nTEST-MODEL-B", "测试使用单位", TODAY)
    assert result["filled_fields"]
    assert dated.text == "2026年10月8日"
    assert company.paragraph_format.keep_with_next
    assert dated.paragraph_format.keep_together
    assert [node.xml for node in dated._p.xpath("./w:pPr/w:sectPr | .//w:br")] == date_boundaries
    current_index = next(i for i, p in enumerate(d.paragraphs) if p._p is dated._p)
    assert [p._p.xml for p in d.paragraphs[current_index + 1:]] == subsequent_xml
