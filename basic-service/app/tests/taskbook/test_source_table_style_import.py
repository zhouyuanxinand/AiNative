"""Copied tables keep their source style graph instead of inheriting captions."""
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from jonhon_taskbook.semantic_orchestrator import (
    apply_semantic_plan, extract_source_blocks, extract_template_slots,
)


def _copy_source(source, target, tmp_path):
    sources = source if isinstance(source, list) else [source]
    output_path = tmp_path / "output.docx"
    blocks = []
    for index, document in enumerate(sources):
        source_path = tmp_path / f"source-{index}.docx"
        heading = document.add_heading("工艺要求", 1)
        document.element.body.insert(0, heading._p)
        document.save(source_path)
        blocks.extend(extract_source_blocks(str(source_path), "tech"))
    target.add_heading("工艺要求", 1)
    target.save(output_path)
    slots = extract_template_slots(str(output_path))
    evidence = apply_semantic_plan(str(output_path), {
        "slots": slots, "source_blocks": blocks,
        "decisions": [{"target_slot": slots[0]["id"],
                       "source_ids": [block["id"] for block in blocks],
                       "operation": "copy_exact", "edit_action": "append",
                       "confidence": 0.99}],
    })
    assert evidence["passed"]
    assert evidence["inserted"]
    return Document(output_path)


def _numbering_style(document, style, text):
    numbering = document.part.numbering_part.element
    abstract_id = max(int(n.get(qn("w:abstractNumId")))
                      for n in numbering.findall(qn("w:abstractNum"))) + 1
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    level = OxmlElement("w:lvl")
    level.set(qn("w:ilvl"), "0")
    for tag, value in (("start", "1"), ("numFmt", "decimal"), ("lvlText", text)):
        child = OxmlElement("w:" + tag)
        child.set(qn("w:val"), value)
        level.append(child)
    abstract.append(level)
    numbering.append(abstract)
    num = numbering.add_num(abstract_id)
    style.element.get_or_add_pPr().get_or_add_numPr().get_or_add_numId().val = num.numId
    return num.numId


def _inherited_numbering(paragraph):
    style = paragraph.style
    seen = set()
    while style is not None and style.style_id not in seen:
        seen.add(style.style_id)
        num_ids = style.element.xpath("./w:pPr/w:numPr/w:numId/@w:val")
        if num_ids:
            return num_ids[0]
        style = style.base_style
    return None


def test_table_base_style_id_collision_does_not_add_figure_numbers(tmp_path):
    source, target = Document(), Document()
    # Word-converted DOC files use local IDs: source 'a' is Normal while the
    # taskbook template uses that same ID for a numbered figure caption.
    source.styles["Normal"].element.set(qn("w:styleId"), "a")
    table_style = source.styles.add_style("TableParagraph", WD_STYLE_TYPE.PARAGRAPH)
    table_style.base_style = source.styles["Normal"]
    caption = target.styles.add_style("FigureCaption", WD_STYLE_TYPE.PARAGRAPH)
    caption.element.set(qn("w:styleId"), "a")
    _numbering_style(target, caption, "图%1")
    table = source.add_table(rows=2, cols=2)
    for cell, text in zip([cell for row in table.rows for cell in row.cells],
                          ["序号", "测试项目", "1", "单冷板密封性"]):
        cell.text = text
        cell.paragraphs[0].style = table_style

    result = _copy_source(source, target, tmp_path)

    assert [cell.text for row in result.tables[0].rows for cell in row.cells] == [
        "序号", "测试项目", "1", "单冷板密封性",
    ]
    for row in result.tables[0].rows:
        for cell in row.cells:
            assert _inherited_numbering(cell.paragraphs[0]) is None
            assert cell.paragraphs[0].runs[0].font.size.pt == 10.5
    assert result.styles.element.get_by_id("a").xpath("./w:pPr/w:numPr/w:numId")


def test_table_keeps_separate_paragraph_character_and_table_styles(tmp_path):
    source, target = Document(), Document()
    source.styles["Table Grid"].font.size = Pt(16)
    source.styles["Body Text"].paragraph_format.left_indent = Pt(0)
    source.styles["Emphasis"].font.bold = True
    table = source.add_table(rows=2, cols=2)
    table.style = "Table Grid"
    table.cell(0, 0).merge(table.cell(0, 1)).text = "测试项目"
    for cell in (table.cell(0, 0), table.cell(1, 0), table.cell(1, 1)):
        paragraph = cell.paragraphs[0]
        paragraph.style = "Body Text"
        paragraph.add_run("原始表格内容").style = "Emphasis"
    result = _copy_source(source, target, tmp_path)
    copied = result.tables[0]

    assert copied.style.type == WD_STYLE_TYPE.TABLE
    assert len(copied.rows) == 2 and len(copied.columns) == 2
    assert copied.cell(0, 0)._tc is copied.cell(0, 1)._tc
    assert [node.get(qn("w:w")) for node in copied._tbl.tblGrid] == [
        node.get(qn("w:w")) for node in table._tbl.tblGrid
    ]
    for paragraph in (cell.paragraphs[0] for row in copied.rows for cell in row.cells):
        assert paragraph.style.type == WD_STYLE_TYPE.PARAGRAPH
        assert paragraph.style.name.startswith("Body Text")
        assert paragraph.runs[-1].style.type == WD_STYLE_TYPE.CHARACTER
        assert paragraph.runs[-1].style.name.startswith("Emphasis")


def test_multiple_source_lists_keep_distinct_numbering_definitions(tmp_path):
    source, target = Document(), Document()
    first = source.styles.add_style("StepList", WD_STYLE_TYPE.PARAGRAPH)
    second = source.styles.add_style("CaseList", WD_STYLE_TYPE.PARAGRAPH)
    first_num = _numbering_style(source, first, "%1.")
    second_num = _numbering_style(source, second, "Case %1")
    table = source.add_table(rows=1, cols=2)
    for cell, num, text in ((table.cell(0, 0), first_num, "步骤"),
                            (table.cell(0, 1), second_num, "试验")):
        cell.text = text
        cell.paragraphs[0]._p.get_or_add_pPr().get_or_add_numPr().get_or_add_numId().val = num

    result = _copy_source(source, target, tmp_path)
    numbering = result.part.numbering_part.element
    labels = []
    for cell in result.tables[0].rows[0].cells:
        num_id = cell.paragraphs[0]._p.pPr.numPr.numId.val
        abstract_id = numbering.xpath(f'./w:num[@w:numId="{num_id}"]/w:abstractNumId/@w:val')
        assert len(abstract_id) == 1
        labels.append(numbering.xpath(
            f'./w:abstractNum[@w:abstractNumId="{abstract_id[0]}"]/w:lvl/w:lvlText/@w:val'))
    assert labels == [["%1."], ["Case %1"]]


def test_cells_without_explicit_style_keep_source_default_format(tmp_path):
    source, target = Document(), Document()
    source.styles["Normal"].paragraph_format.left_indent = Pt(0)
    target.styles["Normal"].paragraph_format.left_indent = Pt(36)
    table = source.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "序号和指标不应继承模板正文缩进"

    result = _copy_source(source, target, tmp_path)

    assert result.tables[0].cell(0, 0).paragraphs[0].style.paragraph_format.left_indent.pt == 0
    assert result.styles["Normal"].paragraph_format.left_indent.pt == 36


def test_numbered_list_continues_between_copied_tables(tmp_path):
    source, target = Document(), Document()
    style = source.styles.add_style("StepList", WD_STYLE_TYPE.PARAGRAPH)
    number_id = _numbering_style(source, style, "%1.")
    for text in ("第一项", "第二项"):
        table = source.add_table(rows=1, cols=1)
        table.cell(0, 0).text = text
        table.cell(0, 0).paragraphs[0]._p.get_or_add_pPr().get_or_add_numPr().get_or_add_numId().val = number_id

    result = _copy_source(source, target, tmp_path)

    assert len(result.tables) == 2
    assert result.tables[0].cell(0, 0).paragraphs[0]._p.pPr.numPr.numId.val == (
        result.tables[1].cell(0, 0).paragraphs[0]._p.pPr.numPr.numId.val
    )


def test_two_sources_with_same_style_and_number_ids_stay_independent(tmp_path):
    sources = []
    for label, indent in (("Step %1", 0), ("Test %1", 24)):
        source = Document()
        style = source.styles.add_style("ImportedList", WD_STYLE_TYPE.PARAGRAPH)
        style.paragraph_format.left_indent = Pt(indent)
        _numbering_style(source, style, label)
        table = source.add_table(rows=1, cols=1)
        table.cell(0, 0).text = label
        table.cell(0, 0).paragraphs[0].style = style
        sources.append(source)

    result = _copy_source(sources, Document(), tmp_path)

    assert len(result.tables) == 2
    paragraphs = [table.cell(0, 0).paragraphs[0] for table in result.tables]
    assert [paragraph.style.paragraph_format.left_indent.pt for paragraph in paragraphs] == [0, 24]
    numbers = [_inherited_numbering(paragraph) for paragraph in paragraphs]
    assert len(set(numbers)) == 2
    labels = []
    numbering = result.part.numbering_part.element
    for number in numbers:
        abstract = numbering.xpath(f'./w:num[@w:numId="{number}"]/w:abstractNumId/@w:val')
        assert len(abstract) == 1
        labels.append(numbering.xpath(f'./w:abstractNum[@w:abstractNumId="{abstract[0]}"]/w:lvl/w:lvlText/@w:val'))
    assert labels == [["Step %1"], ["Test %1"]]


def test_text_only_source_can_import_footnote_styles_without_prior_table():
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from jonhon_taskbook.source_composer import SourceDocumentComposer

    source, target = Document(), Document()
    source.add_paragraph("只有正文，无表格或图片")
    style = source.styles.add_style("SourceFootnote", WD_STYLE_TYPE.PARAGRAPH)
    style.base_style = source.styles["Normal"]
    footnote = Part(PackURI("/word/footnotes.xml"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
                    b'<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    b'<w:footnote w:id="1"><w:p><w:pPr><w:pStyle w:val="SourceFootnote"/></w:pPr>'
                    b'<w:r><w:t>Note</w:t></w:r></w:p></w:footnote></w:footnotes>')
    source.part.relate_to(footnote, RT.FOOTNOTES)

    SourceDocumentComposer(target).add_styles_from_other_parts(source)

    imported = target.styles["SourceFootnote"]
    assert imported.type == WD_STYLE_TYPE.PARAGRAPH
    assert imported.base_style is not None


def test_copied_footnote_uses_its_source_style_instead_of_template_collision(tmp_path):
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from docx.oxml import parse_xml

    source, target = Document(), Document()
    source_style = source.styles.add_style("NoteText", WD_STYLE_TYPE.PARAGRAPH)
    source_style.font.italic = True
    target_style = target.styles.add_style("NoteText", WD_STYLE_TYPE.PARAGRAPH)
    target_style.font.italic = False
    table = source.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "含脚注的原表"
    reference = OxmlElement("w:footnoteReference")
    reference.set(qn("w:id"), "1")
    table.cell(0, 0).paragraphs[0].runs[0]._r.append(reference)
    footnote = Part(PackURI("/word/footnotes.xml"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
                    b'<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    b'<w:footnote w:id="1"><w:p><w:pPr><w:pStyle w:val="NoteText"/></w:pPr>'
                    b'<w:r><w:t>Source note</w:t></w:r></w:p></w:footnote></w:footnotes>')
    source.part.relate_to(footnote, RT.FOOTNOTES)

    result = _copy_source(source, target, tmp_path)

    footnotes = parse_xml(result.part.rels.part_with_reltype(RT.FOOTNOTES).blob)
    copied_id = result.tables[0]._tbl.xpath('.//w:footnoteReference/@w:id')[0]
    note = footnotes.find(f'{qn("w:footnote")}[@{qn("w:id")}="{copied_id}"]')
    style_id = note.find(f'.//{qn("w:pStyle")}').get(qn("w:val"))
    assert style_id != "NoteText"
    assert result.styles.get_by_id(style_id, WD_STYLE_TYPE.PARAGRAPH).font.italic is True
    assert result.styles["NoteText"].font.italic is False


def test_copied_vml_images_get_unique_ids_and_keep_local_object_references(tmp_path):
    from copy import deepcopy
    from io import BytesIO
    from hashlib import sha256
    from lxml import etree
    from PIL import Image
    from jonhon_taskbook.source_composer import SourceDocumentComposer

    vml = "{urn:schemas-microsoft-com:vml}"
    office = "{urn:schemas-microsoft-com:office:office}"
    sources = []
    png = BytesIO()
    Image.new("RGB", (12, 8), "#2060a0").save(png, format="PNG")
    image_bytes = png.getvalue()
    for text in ("第一份需求图", "第二份需求图"):
        source = Document()
        table = source.add_table(rows=1, cols=1)
        table.cell(0, 0).text = text
        run = table.cell(0, 0).paragraphs[0].add_run()
        run.add_picture(BytesIO(image_bytes))
        drawing = run._r.find(qn("w:drawing"))
        image_id = drawing.find(f'.//{qn("a:blip")}').get(qn("r:embed"))
        run._r.remove(drawing)
        obj = OxmlElement("w:object")
        shape = etree.SubElement(obj, vml + "shape")
        shape.set("id", "Picture 2")
        shape.set(office + "spid", "_x0000_i1026")
        shape.set("style", "width:72pt;height:48pt")
        image = etree.SubElement(shape, vml + "imagedata")
        image.set(qn("r:id"), image_id)
        image.set("croptop", "1234f")
        ole = etree.SubElement(obj, office + "OLEObject")
        ole.set("ShapeID", "_x0000_i1026")
        control = etree.SubElement(obj, qn("w:control"))
        control.set(qn("w:shapeid"), "Picture 2")
        run._r.append(obj)
        sources.append(source)

    # Replay the import seam used by both fill and semantic copy. The same
    # source image is allowed in separate target sections; semantic same-slot
    # image deduplication would deliberately suppress it in a single slot.
    target = Document()
    composer = SourceDocumentComposer(target)
    for source in (sources[0], sources[0], sources[1]):
        copied = deepcopy(source.tables[0]._tbl)
        composer.reset_reference_mapping()
        composer._create_style_id_mapping(source)
        composer.add_referenced_parts(source.part, target.part, copied)
        composer.add_styles(source, copied)
        composer.add_numberings(source, copied)
        composer.add_images(source, copied)
        composer.add_shapes(source, copied)
        target.element.body.insert_element_before(copied, "w:sectPr")
    output_path = tmp_path / "copied-vml.docx"
    target.save(output_path)
    result = Document(output_path)

    shapes = list(result.element.iter(vml + "shape"))
    assert len(shapes) == 3
    assert len({shape.get("id") for shape in shapes}) == 3
    assert len({shape.get(office + "spid") for shape in shapes}) == 3
    assert next(sources[0].element.iter(vml + "shape")).get("id") == "Picture 2"
    for shape in shapes:
        obj = shape.getparent()
        assert obj.find(office + "OLEObject").get("ShapeID") == shape.get(office + "spid")
        assert obj.find(qn("w:control")).get(qn("w:shapeid")) == shape.get("id")
        assert shape.get("style") == "width:72pt;height:48pt"
        image = shape.find(vml + "imagedata")
        assert image.get("croptop") == "1234f"
        part = result.part.rels[image.get(qn("r:id"))].target_part
        assert sha256(part.blob).digest() == sha256(image_bytes).digest()
