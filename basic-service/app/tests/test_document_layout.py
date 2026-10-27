"""Final pagination must preserve content while keeping table evidence readable."""
import hashlib
import io
import zipfile

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Twips
from PIL import Image
import pytest

from jonhon_taskbook.postprocess import postprocess


def _finish(document, tmp_path):
    path = tmp_path / "layout.docx"
    document.save(path)
    postprocess(str(path), preserve_template_guidance=True)
    return Document(path), path


def _flag(element, parent, name):
    node = element.find(f"{qn('w:' + parent)}/{qn('w:' + name)}")
    return None if node is None else node.get(qn("w:val"), "on")


def _table(document):
    table = document.add_table(rows=3, cols=2)
    for cell, text in zip(table.rows[0].cells, ("项目", "要求")):
        cell.text = text
    table.cell(1, 0).text = "快接头选型"
    table.cell(1, 1).text = "红色插座/原型号；蓝色插座/原型号"
    table.cell(2, 0).text = "长试验要求"
    table.cell(2, 1).text = "每一项试验条件必须保留。\n" * 160
    return table


def test_final_pass_keeps_rows_and_header_without_joining_entire_table(tmp_path):
    document = Document()
    document.add_heading("技术要求", 1)
    table = _table(document)
    expected = [[cell.text for cell in row.cells] for row in table.rows]
    result, _ = _finish(document, tmp_path)
    table = result.tables[0]
    assert [[cell.text for cell in row.cells] for row in table.rows] == expected
    assert all(_flag(row._tr, "trPr", "cantSplit") == "on" for row in table.rows[:2])
    assert _flag(table.rows[2]._tr, "trPr", "cantSplit") == "off"
    assert _flag(table.rows[0]._tr, "trPr", "tblHeader") == "on"
    assert all(p.paragraph_format.keep_with_next for c in table.rows[0].cells for p in c.paragraphs)
    assert all(p.paragraph_format.keep_with_next is False for row in table.rows[1:]
               for cell in row.cells for p in cell.paragraphs)
    # Native Word can clip an over-page cantSplit row. Explicitly allow long
    # rows to flow, without fixed row height or paragraph keepLines clipping.
    long_row = table.rows[2]
    assert long_row._tr.find(f"{qn('w:trPr')}/{qn('w:trHeight')}") is None
    assert all(p.paragraph_format.keep_together is not True for c in long_row.cells for p in c.paragraphs)


def test_heading_keeps_following_content_but_front_matter_is_untouched(tmp_path):
    document = Document()
    front = document.add_table(rows=2, cols=2)
    front.cell(0, 0).text = "签名"
    heading = document.add_heading("工艺要求", 1)
    heading.paragraph_format.keep_with_next = False
    document.add_paragraph()
    document.add_paragraph("快拧螺母处需缠绕一层胶带。")
    result, _ = _finish(document, tmp_path)
    assert _flag(result.tables[0].rows[0]._tr, "trPr", "cantSplit") is None
    assert result.paragraphs[0].paragraph_format.keep_with_next is True
    assert result.paragraphs[1].paragraph_format.keep_with_next is True
    assert result.paragraphs[2].paragraph_format.keep_with_next is not True


def test_sampling_frequency_headers_repeat_without_changing_sample_counts(tmp_path):
    document = Document()
    document.add_heading("测试性要求", 1)
    table = document.add_table(rows=3, cols=2)
    values = [("批次数量", "抽样数"), ("1～50", "2"), ("51～100", "3")]
    for row, labels in zip(table.rows, values):
        for cell, value in zip(row.cells, labels):
            cell.text = value
    result, _ = _finish(document, tmp_path)
    assert _flag(result.tables[0].rows[0]._tr, "trPr", "tblHeader") == "on"
    assert [tuple(c.text for c in row.cells) for row in result.tables[0].rows] == values


def test_imported_exact_height_is_a_minimum_so_long_source_rows_do_not_clip(tmp_path):
    from docx.enum.table import WD_ROW_HEIGHT_RULE
    document = Document()
    document.add_heading("技术要求", 1)
    table = _table(document)
    table.rows[2].height = Twips(360)
    table.rows[2].height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
    expected = table.cell(2, 1).text
    result, _ = _finish(document, tmp_path)
    assert result.tables[0].rows[2].height_rule == WD_ROW_HEIGHT_RULE.AT_LEAST
    assert result.tables[0].rows[2].height.twips == 360
    assert result.tables[0].cell(2, 1).text == expected


@pytest.mark.parametrize("layout", ["large_indent", "triple_line_spacing"])
def test_retained_paragraph_layout_cannot_lock_an_over_page_row(tmp_path, layout):
    document = Document()
    document.add_heading("测试性要求", 1)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "项目", "要求"
    table.cell(1, 0).text = "长试验条件"
    paragraph = table.cell(1, 1).paragraphs[0]
    paragraph.text = "条" * 450
    if layout == "large_indent":
        paragraph.paragraph_format.left_indent = Twips(3900)
    else:
        paragraph.paragraph_format.line_spacing = 3
    result, _ = _finish(document, tmp_path)
    assert _flag(result.tables[0].rows[1]._tr, "trPr", "cantSplit") == "off"
    assert result.tables[0].cell(1, 1).text == "条" * 450


def test_only_real_column_headers_repeat_not_the_first_key_value_row(tmp_path):
    document = Document()
    document.add_heading("产品组成", 1)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "部件名称"
    table.cell(0, 1).text = "液冷组件"
    table.cell(1, 0).text = "制造商"
    table.cell(1, 1).text = "原文制造商"
    result, _ = _finish(document, tmp_path)
    assert _flag(result.tables[0].rows[0]._tr, "trPr", "tblHeader") is None


@pytest.mark.parametrize("centered", [True, False])
def test_centered_short_table_title_stays_with_table_without_joining_prose(tmp_path, centered):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    document = Document()
    document.add_heading("测试性要求", 1)
    caption = document.add_paragraph("58psi 氮气保压测试频率")
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER if centered else WD_ALIGN_PARAGRAPH.LEFT
    _table(document)
    result, _ = _finish(document, tmp_path)
    assert (result.paragraphs[1].paragraph_format.keep_with_next is True) == centered


def test_images_fit_cell_content_width_preserving_ratio_and_media_bytes(tmp_path):
    document = Document()
    document.sections[0].page_width = Twips(7200)
    document.sections[0].left_margin = document.sections[0].right_margin = Twips(1440)
    document.add_heading("产品组成", 1)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "项目", "图样或照片"
    table.cell(1, 0).text = "原文图片"
    stream = io.BytesIO()
    Image.new("RGB", (600, 200), "#579AC8").save(stream, "PNG")
    stream.seek(0)
    table.cell(1, 1).paragraphs[0].add_run().add_picture(stream, width=Inches(4.5))
    original_media_hash = hashlib.sha256(stream.getvalue()).hexdigest()
    result, path = _finish(document, tmp_path)
    cell = result.tables[0].cell(1, 1)
    inline = cell._tc.find(f".//{qn('wp:inline')}")
    extent = inline.find(qn("wp:extent"))
    width, height = int(extent.get("cx")), int(extent.get("cy"))
    assert width <= (cell.width.twips - 216) * 635
    assert abs(width / height - 3) < 0.001
    picture_extent = inline.find(f".//{qn('a:xfrm')}/{qn('a:ext')}")
    assert (picture_extent.get("cx"), picture_extent.get("cy")) == (str(width), str(height))
    with zipfile.ZipFile(path) as archive:
        media_hashes = [hashlib.sha256(archive.read(name)).hexdigest()
                        for name in archive.namelist() if name.startswith("word/media/")]
    assert media_hashes == [original_media_hash]


def test_vml_image_fits_cell_and_keeps_its_relationship(tmp_path):
    document = Document()
    document.add_heading("产品组成", 1)
    table = _table(document)
    cell = table.cell(1, 1)
    pict = OxmlElement("w:pict")
    from lxml import etree
    shape = etree.SubElement(pict, "{urn:schemas-microsoft-com:vml}shape")
    shape.set("style", "width:600pt;height:200pt;rotation:0")
    data = etree.SubElement(shape, "{urn:schemas-microsoft-com:vml}imagedata")
    data.set(qn("r:id"), "original-image-reference")
    cell.paragraphs[0].add_run()._r.append(pict)
    result, _ = _finish(document, tmp_path)
    final_shape = result.tables[0].cell(1, 1)._tc.find(".//{urn:schemas-microsoft-com:vml}shape")
    values = dict(part.split(":", 1) for part in final_shape.get("style").split(";"))
    assert float(values["width"].removesuffix("pt")) < 300
    assert abs(float(values["width"].removesuffix("pt")) / float(values["height"].removesuffix("pt")) - 3) < 0.001
    assert values["rotation"] == "0"
    assert final_shape.find("{urn:schemas-microsoft-com:vml}imagedata").get(qn("r:id")) == "original-image-reference"
