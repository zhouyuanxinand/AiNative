"""Preserve formatting when encoding newer flags in legacy Word bitmasks."""

from lxml import etree
import pytest

from jonhon_taskbook.ooxml_properties import normalize_properties_xml


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@pytest.mark.parametrize("tag, attributes, expected", [
    ("tblLook", 'w:firstRow="1" w:lastRow="true" w:noHBand="on" w:noVBand="1"', "0660"),
    ("tblLook", 'w:val="04A0" w:firstRow="off" w:lastRow="true"', "04C0"),
    ("tblLook", 'w:val="0480" w:firstRow="false"', "0480"),
    ("stylePaneFormatFilter", 'w:customStyles="true" w:top3HeadingStyles="1"', "2002"),
    ("stylePaneFormatFilter", 'w:val="000C" w:stylesInUse="0" w:allStyles="on"', "0005"),
    ("stylePaneFormatFilter", 'w:directFormattingOnRuns="1"', "0100"),
    ("stylePaneFormatFilter", 'w:directFormattingOnParagraphs="1"', "0200"),
    ("stylePaneFormatFilter", 'w:directFormattingOnNumbering="1"', "0400"),
    ("stylePaneFormatFilter", 'w:directFormattingOnTables="1"', "0800"),
    ("stylePaneFormatFilter", 'w:clearFormatting="1" w:visibleStyles="1"', "5000"),
    ("stylePaneFormatFilter", 'w:numberingStyles="1" w:tableStyles="1" w:alternateStyleNames="1"', "80C0"),
])
def test_named_flags_encode_legacy_values_without_losing_other_bits(tag, attributes, expected):
    original = f'<w:{tag} xmlns:w="{W}" {attributes}/>'.encode()
    output, stats = normalize_properties_xml(original)
    root = etree.fromstring(output)
    assert root.attrib == {f"{{{W}}}val": expected}
    assert stats["ooxml_word2007_flag_sets_normalized"] == 1
    assert normalize_properties_xml(output)[0] == output
    assert not any(normalize_properties_xml(output)[1].values())


def test_legacy_encoding_preserves_unknown_extensions_and_does_not_guess_invalid_flags():
    original = f'''<w:document xmlns:w="{W}" xmlns:x="urn:example:extension"
      xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
      mc:Ignorable="x"><w:body><w:tbl><w:tblPr>
      <w:tblLook w:val="04A0" w:firstRow="0" x:custom="retained"/>
      </w:tblPr></w:tbl><x:note>preserved</x:note></w:body></w:document>'''.encode()
    output, _ = normalize_properties_xml(original)
    root = etree.fromstring(output)
    look = root.find(f".//{{{W}}}tblLook")
    assert look.get(f"{{{W}}}val") == "0480"
    assert look.get("{urn:example:extension}custom") == "retained"
    assert root.find(".//{urn:example:extension}note").text == "preserved"
    assert root.get("{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable") == "x"
    for attributes in ('w:val="invalid" w:firstRow="1"', 'w:val="04A0" w:firstRow="invalid"'):
        invalid = f'<w:tblLook xmlns:w="{W}" {attributes}/>'.encode()
        assert normalize_properties_xml(invalid)[0] == invalid
