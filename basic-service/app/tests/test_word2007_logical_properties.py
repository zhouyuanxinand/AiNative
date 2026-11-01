"""Office 2010 logical layout values must not leak into Word 2007 output."""
from copy import deepcopy
from zipfile import ZipFile

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from lxml import etree
import pytest

from jonhon_taskbook.auto_repair import run_auto_repair
from jonhon_taskbook.ooxml_properties import normalize_properties
from jonhon_taskbook.postprocess import postprocess
from jonhon_taskbook.source_composer import SourceDocumentComposer

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def xml(body):
    return etree.fromstring((f'<w:root xmlns:w="{W[1:-1]}" xmlns:x="urn:other">{body}</w:root>').encode())


def test_imported_footer_alignment_is_converted_by_final_package_writer(tmp_path):
    source, target = Document(), Document()
    style = source.styles.add_style("Source Footer", WD_STYLE_TYPE.PARAGRAPH)
    style.base_style = source.styles["Normal"]
    alignment = OxmlElement("w:jc")
    alignment.set(W + "val", "start")
    style.element.get_or_add_pPr().append(alignment)
    paragraph = source.add_paragraph("原文技术指标 0.3MPa", style=style)
    composer = SourceDocumentComposer(target)
    copied = deepcopy(paragraph._p)
    composer.add_styles(source, copied)
    target._element.body.insert(0, copied)
    path = tmp_path / "source-styles.docx"
    target.save(path)
    with ZipFile(path) as package:
        before = etree.fromstring(package.read("word/styles.xml"))
        assert before.xpath(".//w:jc[@w:val='start']", namespaces={"w": W[1:-1]})

    postprocess(path)

    with ZipFile(path) as package:
        styles = etree.fromstring(package.read("word/styles.xml"))
        imported = next(s for s in styles.iter(W + "style") if s.find(W + "name").get(W + "val") == "Source Footer")
        assert imported.find(W + "pPr/" + W + "jc").get(W + "val") == "left"
        document = etree.fromstring(package.read("word/document.xml"))
        assert "原文技术指标 0.3MPa" in "".join(document.itertext())


def test_style_direction_and_paragraph_override_keep_logical_alignment_meaning():
    styles = etree.fromstring((f'<w:styles xmlns:w="{W[1:-1]}">'
        '<w:style w:type="paragraph" w:styleId="Base"><w:pPr><w:bidi/><w:jc w:val="start"/></w:pPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Child"><w:basedOn w:val="Base"/></w:style>'
        '</w:styles>').encode())
    root = xml('<w:p><w:pPr><w:pStyle w:val="Child"/><w:bidi w:val="0"/></w:pPr><w:r><w:t>保留</w:t></w:r></w:p>'
               '<w:p><w:pPr><w:pStyle w:val="Child"/><w:jc w:val="end"/></w:pPr></w:p>')

    normalize_properties(root, styles_root=styles)
    normalize_properties(styles)

    assert root[0].find(W + "pPr/" + W + "jc").get(W + "val") == "left"
    assert root[1].find(W + "pPr/" + W + "jc").get(W + "val") == "left"
    assert styles[0].find(W + "pPr/" + W + "jc").get(W + "val") == "right"
    assert root[0].find(".//" + W + "t").text == "保留"


def test_logical_edges_and_indents_preserve_width_color_and_numbering_counters():
    root = xml('''<w:tbl><w:tblPr><w:tblCellMar><w:start w:w="108" w:type="dxa"/><w:end w:w="96" w:type="dxa"/></w:tblCellMar></w:tblPr>
      <w:tr><w:tc><w:tcPr><w:tcBorders><w:left w:val="nil"/><w:start w:val="single" w:sz="4" w:color="112233"/><w:end w:val="double" w:sz="8"/></w:tcBorders></w:tcPr>
      <w:p><w:pPr><w:ind w:start="360" w:end="120" w:firstLine="60"/></w:pPr></w:p></w:tc></w:tr></w:tbl>
      <w:abstractNum w:abstractNumId="9"><w:lvl w:ilvl="0"><w:lvlText w:val="%1."/><w:start w:val="3"/><w:numFmt w:val="decimal"/><w:lvlJc w:val="start"/>
      <w:pPr><w:ind w:start="100" w:hanging="50"/></w:pPr></w:lvl></w:abstractNum>
      <w:pgNumType w:start="2"/><x:jc x:val="start"/>''')

    normalize_properties(root)

    margin = root.find(".//" + W + "tblCellMar")
    assert [(etree.QName(n).localname, n.get(W + "w")) for n in margin] == [("left", "108"), ("right", "96")]
    border = root.find(".//" + W + "tcBorders")
    assert len(border) == 2
    assert dict(border.find(W + "left").attrib) == {W + "val": "single", W + "sz": "4", W + "color": "112233"}
    assert border.find(W + "right").get(W + "val") == "double"
    indent = root.find(".//" + W + "ind")
    assert dict(indent.attrib) == {W + "left": "360", W + "right": "120", W + "firstLine": "60"}
    level = root.find(".//" + W + "lvl")
    assert [etree.QName(n).localname for n in level] == ["start", "numFmt", "lvlText", "lvlJc", "pPr"]
    assert level.find(W + "start").get(W + "val") == "3"
    assert level.find(W + "lvlJc").get(W + "val") == "left"
    assert root.find(W + "pgNumType").get(W + "start") == "2"
    assert root.find("{urn:other}jc").get("{urn:other}val") == "start"
    snapshot = etree.tostring(root)
    assert not any(normalize_properties(root).values())
    assert etree.tostring(root) == snapshot


def test_explicit_rtl_table_and_paragraph_sides_are_mapped_in_their_own_context():
    root = xml('''<w:tbl><w:tblPr><w:bidiVisual/><w:tblBorders><w:start w:val="single"/><w:end w:val="double"/></w:tblBorders></w:tblPr>
      <w:tr><w:tc><w:tcPr><w:tcMar><w:start w:w="75" w:type="dxa"/></w:tcMar></w:tcPr>
      <w:p><w:pPr><w:bidi w:val="0"/><w:jc w:val="start"/><w:ind w:startChars="100" w:endChars="20"/></w:pPr></w:p>
      </w:tc></w:tr></w:tbl>''')

    normalize_properties(root)

    borders = root.find(".//" + W + "tblBorders")
    assert borders.find(W + "right").get(W + "val") == "single"
    assert borders.find(W + "left").get(W + "val") == "double"
    assert root.find(".//" + W + "tcMar/" + W + "right").get(W + "w") == "75"
    assert root.find(".//" + W + "jc").get(W + "val") == "left"
    assert dict(root.find(".//" + W + "ind").attrib) == {W + "leftChars": "100", W + "rightChars": "20"}


def test_unknown_direction_is_preserved_for_diagnosis():
    root = xml('<w:p><w:pPr><w:bidi w:val="unrecognized"/><w:jc w:val="start"/><w:ind w:start="100"/></w:pPr></w:p>')
    normalize_properties(root)
    assert root.find(".//" + W + "jc").get(W + "val") == "start"
    assert root.find(".//" + W + "ind").get(W + "start") == "100"


@pytest.mark.parametrize("writer", ["postprocess", "auto_repair"])
def test_final_writers_resolve_body_and_header_alignment_from_original_styles(tmp_path, writer):
    document = Document()
    style = document.styles.add_style("RTL evidence", WD_STYLE_TYPE.PARAGRAPH)
    properties = style.element.get_or_add_pPr()
    properties.append(OxmlElement("w:bidi"))
    alignment = OxmlElement("w:jc")
    alignment.set(W + "val", "start")
    properties.append(alignment)
    body = document.add_paragraph("原始正文", style=style)
    header = document.sections[0].header.paragraphs[0]
    header.style = style
    header.text = "原始页眉"
    for paragraph in (body, header):
        direction = OxmlElement("w:bidi")
        direction.set(W + "val", "0")
        paragraph._p.get_or_add_pPr().append(direction)
    path = tmp_path / f"{writer}.docx"
    document.save(path)

    if writer == "postprocess":
        postprocess(path)
    else:
        report = run_auto_repair(path, None, None, cb=lambda _: None, evaluate=lambda _: {
            "qa_ok": True, "delivery_gate_ok": False, "blocking_keys": ["SOURCE_REVIEW_REQUIRED"],
            "covered_source_ids": [], "semantic_integrity": {"violations": []},
        })
        assert report["accepted_rounds"] == 1
        assert not report["snapshot"]["delivery_gate_ok"]

    with ZipFile(path) as package:
        for part, text in (("word/document.xml", "原始正文"), ("word/header1.xml", "原始页眉")):
            root = etree.fromstring(package.read(part))
            paragraph = next(p for p in root.iter(W + "p") if text in "".join(p.itertext()))
            assert paragraph.find(W + "pPr/" + W + "jc").get(W + "val") == "left"
        styles = etree.fromstring(package.read("word/styles.xml"))
        imported = next(s for s in styles.iter(W + "style") if s.find(W + "name").get(W + "val") == "RTL evidence")
        assert imported.find(W + "pPr/" + W + "jc").get(W + "val") == "right"
