"""A source figure may support two distinct taskbook sections."""

import base64
from io import BytesIO

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from jonhon_taskbook.qa_gate import QAGate

_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+X2WQAAAAASUVORK5CYII="
)


def _add_source_figure(document):
    document.add_paragraph("漏液检测线缠绕轨迹如图18轨迹所示。", style="NarrativeShort")
    document.add_picture(BytesIO(_PIXEL))


def test_same_picture_is_allowed_in_distinct_semantic_sections():
    document = Document()
    document.styles.add_style("NarrativeShort", WD_STYLE_TYPE.PARAGRAPH)
    document.add_heading("安装形式和方法", level=2)
    _add_source_figure(document)
    document.add_heading("接口尺寸要求", level=2)
    _add_source_figure(document)

    result = QAGate(
        {"block_if": {"duplicate_body_image_relationship": True}}, {},
    ).check(document.element)

    assert not any("重复图片引用" in reason for reason in result["block_reasons"])


def test_same_picture_repeated_within_one_section_remains_blocked():
    document = Document()
    document.styles.add_style("NarrativeShort", WD_STYLE_TYPE.PARAGRAPH)
    document.add_heading("安装形式和方法", level=2)
    _add_source_figure(document)
    _add_source_figure(document)

    result = QAGate(
        {"block_if": {"duplicate_body_image_relationship": True}}, {},
    ).check(document.element)

    assert any("重复图片引用" in reason for reason in result["block_reasons"])
