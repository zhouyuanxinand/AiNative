"""Keep imported evidence readable inside the target template's sections."""
import re

from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from ..template_scanner import heading_level
from .table_style_engine import normalize_imported_table_typography, set_run_typography


_CAPTION_RE = re.compile(r"^\s*(?:图|表)\s*\d+(?=\D|$)")
_VML_IMAGE = "{urn:schemas-microsoft-com:vml}imagedata"


def has_image(element) -> bool:
    return (element.find(f".//{qn('w:drawing')}") is not None
            or element.find(f".//{_VML_IMAGE}") is not None)


def normalize_image_paragraph(paragraph) -> bool:
    """Let inline media grow its line and row, including inherited exact lines.

    Keep image bytes, drawing geometry, anchors and crop settings untouched.
    Only fixed text layout constraints that clip visible pictures are relaxed.
    """
    if not has_image(paragraph):
        return False
    properties = paragraph.find(qn("w:pPr"))
    if properties is None:
        properties = OxmlElement("w:pPr")
        paragraph.insert(0, properties)
    spacing = properties.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        properties.append(spacing)
    if spacing.get(qn("w:lineRule")) == "exact":
        spacing.set(qn("w:lineRule"), "atLeast")
    elif not spacing.get(qn("w:lineRule")):
        # Explicit single line also overrides a source paragraph style's
        # exact spacing when there is no direct spacing on the paragraph.
        spacing.set(qn("w:lineRule"), "auto")
        spacing.set(qn("w:line"), "240")
    for row in paragraph.iterancestors(qn("w:tr")):
        for height in row.findall(f"{qn('w:trPr')}/{qn('w:trHeight')}"):
            if height.get(qn("w:hRule")) == "exact":
                height.set(qn("w:hRule"), "atLeast")
    return True


def normalize_copied_body_paragraph(element, document) -> None:
    """Normalize source presentation without changing its text or media.

    The source heading is content inside an already selected template slot.
    Keeping its Heading 1/2 style would end that slot and misplace everything
    that follows. Only the controlled template creates actual target headings.
    """
    if element.tag == qn("w:tbl"):
        normalize_imported_table_typography(element)
        for paragraph in element.findall(f".//{qn('w:p')}"):
            normalize_image_paragraph(paragraph)
        return
    if element.tag != qn("w:p"):
        return
    normalize_image_paragraph(element)
    paragraph = Paragraph(element, document._body)
    if _CAPTION_RE.match(paragraph.text):
        # This function is called only for imported source elements. Template
        # captions keep their own size and style in the final postprocess pass.
        paragraph.style = document.styles.default(WD_STYLE_TYPE.PARAGRAPH)
        paragraph.paragraph_format.page_break_before = False
        paragraph.paragraph_format.keep_with_next = False
        paragraph.paragraph_format.keep_together = True
        for tag in ("outlineLvl", "numPr"):
            for node in list(element.get_or_add_pPr().findall(qn(f"w:{tag}"))):
                element.get_or_add_pPr().remove(node)
        for run in element.findall(f".//{qn('w:r')}"):
            if run.find(qn("w:t")) is not None:
                set_run_typography(run, "宋体", 21)
        return
    if not heading_level(paragraph):
        return
    inherited_bold = paragraph.style.font.bold if paragraph.style is not None else None
    paragraph.style = document.styles.default(WD_STYLE_TYPE.PARAGRAPH)
    properties = element.find(qn("w:pPr"))
    if properties is not None:
        for tag in ("outlineLvl", "numPr"):
            for node in list(properties.findall(qn(f"w:{tag}"))):
                properties.remove(node)
    if inherited_bold:
        for run in paragraph.runs:
            if run.bold is None:
                run.bold = True
