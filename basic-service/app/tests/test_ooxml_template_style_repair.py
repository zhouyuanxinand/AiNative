"""Repair proven template schema defects without changing table content."""
from pathlib import Path
from zipfile import ZipFile

from lxml import etree


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEMPLATES = Path(__file__).resolve().parents[1] / "src/service/jonhon_taskbook/resources/templates"


def _xml(body):
    return etree.fromstring(
        ('<w:styles xmlns:w="' + W[1:-1] + '" xmlns:x="urn:extension">'
         + body + '</w:styles>').encode()
    )


def test_style_child_order_preserves_properties_dependencies_and_extensions():
    from jonhon_taskbook.ooxml_style_repair import normalize_template_styles

    root = _xml('''<w:style w:type="paragraph" w:styleId="HeadingA">
      <w:name w:val="Heading A"/><w:semiHidden/><x:preserved x:mode="yes"/>
      <w:qFormat/><w:pPr><w:keepNext/></w:pPr><w:uiPriority w:val="1"/>
      <w:rPr><w:b/></w:rPr><w:basedOn w:val="Normal"/>
    </w:style>''')
    style = root[0]
    contents = {child.tag: etree.tostring(child) for child in style}

    stats = normalize_template_styles(root)

    assert [etree.QName(child).localname for child in style] == [
        "name", "basedOn", "preserved", "uiPriority", "semiHidden", "qFormat", "pPr", "rPr"
    ]
    assert {child.tag: etree.tostring(child) for child in style} == contents
    assert stats["ooxml_style_order_normalized"] == 1
    snapshot = etree.tostring(root)
    assert not any(normalize_template_styles(root).values())
    assert etree.tostring(root) == snapshot


def test_only_redundant_table_style_definition_references_are_removed():
    from jonhon_taskbook.ooxml_style_repair import normalize_template_styles

    root = _xml('''
      <w:style w:type="table" w:styleId="29"><w:name w:val="Normal Table"/>
        <w:tblPr><w:tblStyle w:val="29"/><w:tblInd w:w="0" w:type="dxa"/></w:tblPr></w:style>
      <w:style w:type="table" w:styleId="30"><w:name w:val="Grid"/><w:basedOn w:val="29"/>
        <w:tblPr><w:tblStyle w:val="29"/><w:tblBorders><w:bottom w:val="single"/></w:tblBorders></w:tblPr></w:style>
      <w:style w:type="table" w:styleId="Other"><w:name w:val="Other"/><w:basedOn w:val="29"/>
        <w:tblPr><w:tblStyle w:val="Unknown"/></w:tblPr></w:style>
      <w:style w:type="paragraph" w:styleId="Body"><w:name w:val="Body"/>
        <w:tblPr><w:tblStyle w:val="Body"/></w:tblPr></w:style>
    ''')
    document = etree.fromstring(('<w:document xmlns:w="' + W[1:-1] + '"><w:body>'
                                '<w:tbl><w:tblPr><w:tblStyle w:val="29"/></w:tblPr>'
                                '</w:tbl></w:body></w:document>').encode())
    document_before = etree.tostring(document)

    stats = normalize_template_styles(root)

    assert root[0].find(W + 'tblPr/' + W + 'tblStyle') is None
    assert root[1].find(W + 'tblPr/' + W + 'tblStyle') is None
    assert root[1].find(W + 'basedOn').get(W + 'val') == '29'
    assert root[1].find(W + 'tblPr/' + W + 'tblBorders/' + W + 'bottom') is not None
    assert root[2].find(W + 'tblPr/' + W + 'tblStyle').get(W + 'val') == 'Unknown'
    assert root[3].find(W + 'tblPr/' + W + 'tblStyle').get(W + 'val') == 'Body'
    assert stats['ooxml_redundant_style_references_removed'] == 2
    assert not any(normalize_template_styles(document).values())
    assert etree.tostring(document) == document_before


def test_on_off_only_values_keep_their_boolean_meaning_and_other_flags():
    from jonhon_taskbook.ooxml_style_repair import normalize_template_styles

    root = _xml('''<w:noWrap w:val="0"/><w:noWrap w:val="false"/>
      <w:noWrap w:val="1"/><w:noWrap w:val="true"/><w:noWrap w:val="off"/>
      <w:noWrap w:val="on"/><w:noWrap/><w:noWrap w:val="unknown"/>
      <w:tblHeader w:val="true"/><w:tblHeader w:val="0"/>
      <w:b w:val="0"/><w:smartTag w:uri="urn:example" w:element="tag"/>
    ''')
    preserved = etree.tostring(root[-1])

    stats = normalize_template_styles(root)

    assert [node.get(W + 'val') for node in root] == [
        'off', 'off', 'on', 'on', 'off', 'on', None, 'unknown', 'on', 'off', '0', None
    ]
    assert etree.tostring(root[-1]) == preserved
    assert stats['ooxml_on_off_only_values_normalized'] == 6


def test_connector_template_styles_are_repaired_without_changing_properties():
    from jonhon_taskbook.ooxml_style_repair import normalize_template_styles

    with ZipFile(TEMPLATES / 'connector_taskbook.docx') as package:
        styles = etree.fromstring(package.read('word/styles.xml'))
        document = etree.fromstring(package.read('word/document.xml'))
    text_before = [node.text for node in document.iter(W + 't')]
    no_wrap_before = len([node for node in document.iter(W + 'noWrap') if node.get(W + 'val') == '0'])

    style_stats = normalize_template_styles(styles)
    document_stats = normalize_template_styles(document)

    assert style_stats['ooxml_style_order_normalized'] > 0
    assert style_stats['ooxml_redundant_style_references_removed'] == 2
    assert no_wrap_before > 0
    assert document_stats['ooxml_on_off_only_values_normalized'] == no_wrap_before
    assert all(node.get(W + 'val') != '0' for node in document.iter(W + 'noWrap'))
    assert [node.text for node in document.iter(W + 't')] == text_before
    assert not any(normalize_template_styles(styles).values())
    assert not any(normalize_template_styles(document).values())
