"""Source copy preserves evidence while making it readable in a taskbook."""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from PIL import Image, ImageDraw

from jonhon_taskbook.postprocess import postprocess
from jonhon_taskbook.semantic_orchestrator import (
    apply_semantic_plan, extract_source_blocks, extract_template_slots,
)


def _picture(paragraph):
    picture = Image.new("RGB", (360, 216), "#e9f1ff")
    drawing = ImageDraw.Draw(picture)
    drawing.rectangle((4, 4, 355, 211), outline="#15264b", width=8)
    for left, color in ((35, "#cf3737"), (145, "#198568"), (255, "#3054c5")):
        drawing.rectangle((left, 25, left + 70, 190), fill=color)
    # Distinct top/bottom bands make a cropped line visibly different from the
    # complete image in Word and LibreOffice, even in a small table cell.
    drawing.line((20, 45, 339, 45), fill="#ffcf33", width=12)
    drawing.line((20, 170, 339, 170), fill="#15264b", width=12)
    png = BytesIO()
    picture.save(png, format="PNG")
    png.seek(0)
    return paragraph.add_run().add_picture(png, width=Inches(1), height=Inches(0.6))


def _route(source, tmp_path, title):
    source_path, output_path = tmp_path / "source.docx", tmp_path / "output.docx"
    source.save(source_path)
    target = Document()
    target.add_heading(title, 1)
    # An untouched controlled-template caption is deliberately a different size.
    target.add_paragraph("图9 模板原有图题")
    target.paragraphs[-1].runs[0].font.size = Pt(12)
    target.save(output_path)
    blocks = extract_source_blocks(str(source_path), "tech")
    slots = extract_template_slots(str(output_path))
    evidence = apply_semantic_plan(str(output_path), {
        "slots": slots, "source_blocks": blocks, "decisions": [{
            "target_slot": slots[0]["id"], "source_ids": [b["id"] for b in blocks],
            "operation": "copy_exact", "edit_action": "append", "confidence": 0.99,
        }],
    })
    assert evidence["passed"]
    postprocess(output_path, preserve_template_guidance=True)
    return Document(output_path), source_path, output_path


def test_copied_table_clears_source_theme_fonts_and_sizes(tmp_path):
    source = Document()
    source.add_heading("环境适应性要求", 1)
    table = source.add_table(rows=3, cols=2)
    for cell, text in zip([c for row in table.rows for c in row.cells],
                          ["项目", "指标", "工作温度", "0℃～40℃", "工作介质", "PG25 丙二醇水溶液"]):
        cell.text = text
        run = cell.paragraphs[0].runs[0]
        run.font.name = "Times New Roman"
        run.font.size = Pt(16 if "温度" in text else 12)
        fonts = run._r.rPr.rFonts
        fonts.set(qn("w:eastAsia"), "华文行楷")
        fonts.set(qn("w:eastAsiaTheme"), "majorEastAsia")
        fonts.set(qn("w:asciiTheme"), "majorAscii")

    result, _, _ = _route(source, tmp_path, "环境适应性要求")

    assert [c.text for row in result.tables[0].rows for c in row.cells] == [
        "项目", "指标", "工作温度", "0℃～40℃", "工作介质", "PG25 丙二醇水溶液",
    ]
    for row in result.tables[0].rows:
        for cell in row.cells:
            for run in cell.paragraphs[0].runs:
                assert run.font.size.pt == 10.5
                fonts = run._r.rPr.rFonts
                assert fonts.get(qn("w:eastAsia")) == "仿宋_GB2312"
                assert not any(key.endswith("Theme") for key in fonts.attrib)


@pytest.mark.parametrize("inherited", [False, True])
@pytest.mark.parametrize("image_format", ["drawingml", "vml"])
def test_copied_table_image_is_not_clipped_by_exact_line_spacing(tmp_path, inherited, image_format):
    source = Document()
    source.add_heading("产品组成", 1)
    table = source.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "配件名称", "图样或照片"
    table.cell(1, 0).text = "冷板"
    paragraph = table.cell(1, 1).paragraphs[0]
    if inherited:
        style = source.styles.add_style("SourceImageParagraph", WD_STYLE_TYPE.PARAGRAPH)
        style.paragraph_format.line_spacing = Pt(8)
        paragraph.style = style
    else:
        paragraph.paragraph_format.line_spacing = Pt(8)
    table.rows[1].height = Pt(12)
    table.rows[1].height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
    _picture(paragraph)
    if image_format == "vml":
        from lxml import etree
        run = paragraph.runs[-1]._r
        drawing = run.find(qn("w:drawing"))
        relationship = drawing.find(f".//{qn('a:blip')}").get(qn("r:embed"))
        run.remove(drawing)
        pict = OxmlElement("w:pict")
        shape = etree.SubElement(pict, "{urn:schemas-microsoft-com:vml}shape")
        shape.set("id", "SourcePicture")
        shape.set("style", "width:72pt;height:43.2pt")
        image_data = etree.SubElement(shape, "{urn:schemas-microsoft-com:vml}imagedata")
        image_data.set(qn("r:id"), relationship)
        run.append(pict)

    result, source_path, output_path = _route(source, tmp_path, "产品组成")

    row = result.tables[0].rows[1]
    spacing = row.cells[1].paragraphs[0]._p.pPr.find(qn("w:spacing"))
    assert spacing is not None and spacing.get(qn("w:lineRule")) in {"auto", "atLeast"}
    assert row.height_rule != WD_ROW_HEIGHT_RULE.EXACTLY
    if image_format == "drawingml":
        assert len(result.inline_shapes) == 1
    else:
        assert len(result.element.findall(".//{urn:schemas-microsoft-com:vml}imagedata")) == 1
    with ZipFile(source_path) as source_zip, ZipFile(output_path) as output_zip:
        source_media = {source_zip.read(n) for n in source_zip.namelist() if n.startswith("word/media/")}
        output_media = {output_zip.read(n) for n in output_zip.namelist() if n.startswith("word/media/")}
    assert source_media == output_media


def test_imported_caption_uses_controlled_size_and_stays_with_its_image(tmp_path):
    source = Document()
    source.add_heading("产品组成", 1)
    image = source.add_paragraph()
    _picture(image)
    caption = source.add_paragraph("图1 外螺纹插座接口规格")
    caption.runs[0].font.name = "华文行楷"
    caption.runs[0].font.size = Pt(28)
    caption.paragraph_format.page_break_before = True
    caption.paragraph_format.keep_with_next = True

    result, _, _ = _route(source, tmp_path, "产品组成")

    caption = next(p for p in result.paragraphs if "外螺纹插座接口规格" in p.text)
    assert caption.runs[0].font.size.pt == 10.5
    assert caption.paragraph_format.page_break_before is False
    assert caption.paragraph_format.keep_with_next is False
    preceding = caption._p.getprevious()
    assert preceding.find(qn("w:pPr")).find(qn("w:keepNext")).get(qn("w:val")) in {"1", "true"}
    template_caption = next(p for p in result.paragraphs if "模板原有图题" in p.text)
    assert template_caption.runs[0].font.size.pt == 12


def test_body_explicit_font_cannot_be_overridden_by_source_theme(tmp_path):
    document = Document()
    document.add_heading("使用环境", 1)
    run = document.add_paragraph("工作温度：0℃～40℃").runs[0]
    run.font.name = "Times New Roman"
    run._r.rPr.rFonts.set(qn("w:eastAsiaTheme"), "majorEastAsia")
    run._r.rPr.rFonts.set(qn("w:asciiTheme"), "majorAscii")
    output = tmp_path / "body.docx"
    document.save(output)

    postprocess(output)

    run = Document(output).paragraphs[-1].runs[0]
    assert run.font.name == "宋体"
    assert run.font.size.pt == 10.5
    assert not any(key.endswith("Theme") for key in run._r.rPr.rFonts.attrib)


@pytest.mark.parametrize("italic_tag", ["i", "iCs"])
def test_imported_table_preserves_italic_evidence_for_manual_fill_rule(tmp_path, italic_tag):
    source = Document()
    source.add_heading("工艺要求", 1)
    table = source.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "项目", "要求"
    table.cell(1, 0).text = "清洁度"
    table.cell(1, 1).text = "冷板清洗后进行目视检查。"
    run = table.cell(1, 1).paragraphs[0].runs[0]
    run.font.name = "华文行楷"
    run.font.size = Pt(14)
    italic = OxmlElement(f"w:{italic_tag}")
    italic.set(qn("w:val"), "1")
    run._r.get_or_add_rPr().append(italic)

    result, _, output = _route(source, tmp_path, "工艺要求")

    assert result.paragraphs[0].text == "工艺要求【人工填写】"
    rendered = result.tables[0].cell(1, 1).paragraphs[0].runs[0]
    assert rendered._r.rPr.find(qn(f"w:{italic_tag}")).get(qn("w:val")) == "1"
    assert rendered.font.size.pt == 10.5
    assert rendered.font.name == "仿宋_GB2312"
    assert result.tables[0].cell(1, 1).text == "冷板清洗后进行目视检查。"
    postprocess(output)
    assert Document(output).paragraphs[0].text == "工艺要求【人工填写】"


def test_consecutive_images_keep_chain_when_caption_shares_last_image_paragraph(tmp_path):
    document = Document()
    document.add_heading("产品组成", 1)
    _picture(document.add_paragraph())
    caption = document.add_paragraph()
    _picture(caption)
    caption.add_run("图1 外螺纹插座接口规格")
    document.add_heading("适用的法律法规要求", 1)
    output = tmp_path / "same-paragraph-caption.docx"
    document.save(output)

    postprocess(output)

    result = Document(output)
    assert len(result.inline_shapes) == 2
    assert result.paragraphs[1].paragraph_format.keep_with_next is True
    assert result.paragraphs[2].text == "图1 外螺纹插座接口规格"
    assert result.paragraphs[2].paragraph_format.keep_with_next is not True
