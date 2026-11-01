"""Quality-report image counts must survive Word 2007 VML compatibility output."""
import zipfile
from pathlib import Path

import pytest

from jonhon_taskbook.html_reporter import _qa_scan, generate_report
from jonhon_taskbook.image_stats import document_image_stats


DRAWING = '<w:drawing><a:blip r:embed="rId1"/></w:drawing>'
VML = '<w:pict><v:shape><v:imagedata r:id="rId1"/></v:shape></w:pict>'
ALTERNATE = f'''<mc:AlternateContent>
    <mc:Choice Requires="a">{DRAWING}</mc:Choice>
    <mc:Choice Requires="v">{VML}</mc:Choice>
    <mc:Fallback>{VML}</mc:Fallback>
</mc:AlternateContent>'''


def image_document(tmp_path, body):
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:v="urn:schemas-microsoft-com:vml"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">
 <w:body><w:p><w:r>{body}</w:r></w:p></w:body>
</w:document>'''
    path = tmp_path / 'images.docx'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', xml)
        archive.writestr('word/media/image1.png', b'fixture-image-one')
        archive.writestr('word/media/image2.png', b'unused-fixture-image')
    return path


@pytest.mark.parametrize('body, expected', [
    (VML, 1),
    (DRAWING, 1),
    (ALTERNATE, 1),
    (f'<mc:AlternateContent><mc:Fallback>{VML}</mc:Fallback></mc:AlternateContent>', 1),
    (DRAWING + VML + ALTERNATE, 3),
    ('<w:drawing/><w:pict><v:shape/></w:pict>', 0),
])
def test_report_counts_image_occurrences_without_counting_compatibility_alternatives(tmp_path, body, expected):
    path = image_document(tmp_path, body)
    original = path.read_bytes()
    assert document_image_stats(path) == {'drawing_count': expected, 'media_count': 2}
    assert _qa_scan(str(path))['img_count'] == expected
    report = Path(generate_report(str(path))).read_text(encoding='utf-8')
    assert f'<div class="num" style="color:#fa8c16">{expected}</div>' in report
    assert path.read_bytes() == original
