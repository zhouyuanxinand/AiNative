"""Postprocessing emits WordprocessingML property sequences that Word can read."""

from copy import deepcopy
from zipfile import ZipFile

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from jonhon_taskbook.postprocess import postprocess
from jonhon_taskbook.renderer.table_style_engine import apply_table_style, set_run_typography


def _tags(element):
    return [etree.QName(child).localname for child in element]


def test_generated_table_header_uses_repeat_header_schema_value():
    document = Document()
    table = document.add_table(rows=3, cols=2)
    apply_table_style(table, "indicator")
    # tblHeader is CT_OnOffOnly (on/off), unlike w:b's CT_OnOff boolean.
    header = table.rows[0]._tr.find(".//" + qn("w:tblHeader"))
    assert header is not None
    assert header.get(qn("w:val")) in {None, "on"}
    assert all(row._tr.find(".//" + qn("w:tblHeader")) is None for row in table.rows[1:])


def test_final_writer_orders_properties_added_by_font_border_and_header_renderers(tmp_path):
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "指标"
    table.cell(1, 0).text = "工作温度"
    table.cell(1, 1).text = "5℃～42℃"
    run = table.cell(1, 1).paragraphs[0].runs[0]
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "zh-CN")
    run._r.get_or_add_rPr().append(lang)
    # Imported runs often already have language properties. Adding our font
    # and size afterwards must not leave w:sz after w:lang in the final XML.
    set_run_typography(run._r, "仿宋", 21)

    header = doc.sections[0].header.paragraphs[0]
    header.text = "编号："
    header._p.get_or_add_pPr().append(OxmlElement("w:rPr"))
    path = tmp_path / "rendered.docx"
    doc.save(path)
    postprocess(path)

    with ZipFile(path) as package:
        body = etree.fromstring(package.read("word/document.xml"))
        heading = etree.fromstring(package.read("word/header1.xml"))
    ns = {"w": qn("w:document").split("}")[0][1:]}
    emitted = body.xpath('//w:r[w:t="5℃～42℃"]/w:rPr', namespaces=ns)[0]
    names = _tags(emitted)
    assert names.index("rFonts") < names.index("sz") < names.index("szCs") < names.index("lang")
    assert emitted.find(qn("w:sz")).get(qn("w:val")) == "21"
    assert heading.find(".//" + qn("w:pPr")) is not None
    header_names = _tags(heading.find(".//" + qn("w:pPr")))
    assert header_names.index("jc") < header_names.index("rPr")
    assert "".join(body.itertext()).count("5℃～42℃") == 1


def test_property_ordering_retains_table_geometry_relationships_and_extensions():
    from jonhon_taskbook.ooxml_properties import normalize_property_order

    root = etree.fromstring(b'''<w:tbl
        xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xmlns:x="urn:customer:extension">
      <w:tblPr><w:tblLook w:val="04A0"/><w:tblLayout w:type="fixed"/>
        <w:tblW w:w="6000" w:type="dxa"/><x:custom x:mode="keep"/>
        <w:jc w:val="left"/></w:tblPr>
      <w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="4000"/></w:tblGrid>
      <w:tr><w:tc><w:tcPr><w:vAlign w:val="center"/>
        <w:tcBorders><w:right w:val="single"/><w:top w:val="single"/>
          <w:left w:val="single"/><w:bottom w:val="single"/></w:tcBorders>
        <w:tcW w:w="6000" w:type="dxa"/><w:gridSpan w:val="2"/>
        </w:tcPr><w:p><w:r><w:t>preserved content</w:t></w:r></w:p>
      </w:tc></w:tr></w:tbl>''')
    before = deepcopy(root)
    changed = normalize_property_order(root)
    assert changed == 3
    assert _tags(root.find(qn("w:tblPr"))) == ["tblW", "jc", "tblLayout", "custom", "tblLook"]
    cell = root.find(".//" + qn("w:tcPr"))
    assert _tags(cell) == ["tcW", "gridSpan", "tcBorders", "vAlign"]
    assert _tags(cell.find(qn("w:tcBorders"))) == ["top", "left", "bottom", "right"]
    for tag in ("tblGrid", "gridSpan", "t"):
        assert etree.tostring(root.find(".//" + qn("w:" + tag))) == etree.tostring(before.find(".//" + qn("w:" + tag)))
    assert root.find(".//{urn:customer:extension}custom").attrib == before.find(".//{urn:customer:extension}custom").attrib
    unchanged = etree.tostring(root)
    assert normalize_property_order(root) == 0
    assert etree.tostring(root) == unchanged


def test_final_writer_recovers_zero_scale_and_complex_size_without_removing_space(tmp_path):
    document = Document()
    run = document.add_paragraph().add_run(" ")
    properties = run._r.get_or_add_rPr()
    for tag, value in (("w", "0"), ("sz", "16"), ("szCs", "0")):
        prop = OxmlElement("w:" + tag)
        prop.set(qn("w:val"), value)
        properties.append(prop)
    path = tmp_path / "zero-source-formatting.docx"
    document.save(path)

    stats = postprocess(path)

    with ZipFile(path) as package:
        root = etree.fromstring(package.read("word/document.xml"))
    emitted = root.find(".//" + qn("w:r"))
    assert emitted.find(qn("w:t")).text == " "
    properties = emitted.find(qn("w:rPr"))
    assert properties.find(qn("w:w")).get(qn("w:val")) == "100"
    assert properties.find(qn("w:sz")).get(qn("w:val")) == "16"
    assert properties.find(qn("w:szCs")).get(qn("w:val")) == "16"
    assert stats["ooxml_zero_character_scales_normalized"] == 1
    assert stats["ooxml_zero_font_sizes_normalized"] == 1


def test_zero_font_sizes_inherit_when_neither_script_has_a_usable_size():
    from jonhon_taskbook.ooxml_properties import normalize_properties_xml

    data = b'''<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:rPr><w:w w:val="80"/><w:sz w:val="0"/><w:szCs w:val="0"/></w:rPr>
      <w:t xml:space="preserve"> preserved </w:t></w:r>'''
    result, stats = normalize_properties_xml(data)
    root = etree.fromstring(result)
    assert root.find(qn("w:t")).text == " preserved "
    assert root.find(".//" + qn("w:sz")) is None
    assert root.find(".//" + qn("w:szCs")) is None
    assert root.find(".//" + qn("w:w")).get(qn("w:val")) == "80"
    assert stats["ooxml_zero_font_sizes_normalized"] == 2
    assert stats["ooxml_zero_character_scales_normalized"] == 0


def test_final_property_serializer_preserves_nonzero_font_sizes_and_scale():
    from jonhon_taskbook.ooxml_properties import normalize_properties_xml

    for size, scale in (("2", "1"), ("16", "80"), ("21", "100"), ("1638", "600")):
        data = (
            '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:rPr><w:w w:val="{scale}"/><w:sz w:val="{size}"/>'
            f'<w:szCs w:val="{size}"/></w:rPr><w:t>unaltered</w:t></w:r>'
        ).encode()
        result, stats = normalize_properties_xml(data)
        assert result == data
        assert not any(stats.values())
