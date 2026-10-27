"""Controlled cover fields for taskbook generation."""

from __future__ import annotations

import re
import math
import unicodedata
from copy import deepcopy
from datetime import date as CalendarDate

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Twips
from docx.text.paragraph import Paragraph


ALLOWED_COVER_PHASES = ("F", "C", "S", "D")

_COVER_FIELD = re.compile(
    r"^(?P<label>\s*(?:名\s*称|产品\s*名\s*称|产品\s*型\s*号|使用\s*单\s*位)\s*[:：])(?P<value>.*)$",
    re.S,
)
_COVER_DATE = re.compile(
    r"^\s*(?:\d{4}|20[xX]{2}|20)?\s*年\s*(?:\d{1,2}|[xX])?\s*月"
    r"(?:\s*(?:\d{1,2}|[xX])?\s*日)?\s*$"
)


def _cover_paragraphs(document):
    """The cover ends before a table/body heading or at its own page/section break."""
    for child in document.element.body:
        if child.tag != qn("w:p"):
            break
        paragraph = Paragraph(child, document)
        text = paragraph.text.strip()
        if re.match(r"^变更记录", re.sub(r"\s+", "", text)):
            break
        if re.match(r"(?:Heading|标题)\s*[1-9]", paragraph.style.name, re.I):
            if re.sub(r"\s+", "", text) != "研制任务书":
                break
        if child.xpath("./w:pPr/w:pageBreakBefore[not(@w:val='0')]"):
            break
        yield paragraph
        # Some controlled templates keep the page break in the date paragraph.
        if _COVER_DATE.fullmatch(text) or child.xpath("./w:pPr/w:sectPr | .//w:br[@w:type='page']"):
            break


def _font_twips(paragraph, run=None):
    """Read the cover's existing type size; one half-point is ten twips."""
    properties = [run._r.rPr] if run is not None else []
    properties.append(paragraph._p.pPr.find(qn("w:rPr")) if paragraph._p.pPr is not None else None)
    style = paragraph.style
    while style is not None:
        properties.append(style.element.rPr)
        style = style.base_style
    for prop in properties:
        size = prop.find(qn("w:sz")) if prop is not None else None
        if size is not None:
            return int(size.get(qn("w:val"))) * 10
    return 240


def _label_width(paragraph, boundary):
    """Chinese cover labels use full-em ideographs and half-em Latin spaces."""
    width, offset = 0.0, 0
    for run in paragraph.runs:
        text = run.text[:max(0, boundary - offset)]
        width += _font_twips(paragraph, run) * sum(
            0 if unicodedata.combining(char) else (1 if unicodedata.east_asian_width(char) in {"W", "F"} else 0.5)
            for char in text
        )
        offset += len(run.text)
    return round(width)


def _align_cover_value(paragraph, label_width):
    """Turn a first-line-only indent into a hanging indent at the value column."""
    ind = paragraph._p.get_or_add_pPr().get_or_add_ind()
    em = _font_twips(paragraph, paragraph.runs[0] if paragraph.runs else None)

    def distance(name):
        chars = ind.get(qn(f"w:{name}Chars"))
        return round(int(chars) * em / 100) if chars is not None else int(ind.get(qn(f"w:{name}"), "0"))

    left = distance("left")
    if ind.get(qn("w:start")) is not None:
        left = int(ind.get(qn("w:start")))
    hanging = ind.get(qn("w:hanging")) is not None or ind.get(qn("w:hangingChars")) is not None
    label_start = left - distance("hanging") if hanging else left + distance("firstLine")
    for name in ("left", "leftChars", "start", "startChars", "firstLine", "firstLineChars", "hanging", "hangingChars"):
        ind.attrib.pop(qn(f"w:{name}"), None)
    ind.set(qn("w:left"), str(label_start + label_width))
    ind.set(qn("w:hanging"), str(label_width))
    # Some templates inherit firstLineChars from Normal.  Merely deleting the
    # direct attribute lets that inherited value override the hanging indent.
    ind.set(qn("w:firstLineChars"), "0")


def _replace_cover_value(paragraph, match, value):
    """Keep label runs and copy the existing value format without relying on run count."""
    boundary = match.end("label")
    width = _label_width(paragraph, boundary)
    originals = list(paragraph.runs)
    offset, donor = 0, None
    for run in originals:
        if offset + len(run.text) > boundary:
            donor = donor or run
            if run.underline:
                donor = run
                break
        offset += len(run.text)
    donor = donor or (originals[-1] if originals else None)
    properties = deepcopy(donor._r.rPr) if donor is not None and donor._r.rPr is not None else None
    offset = 0
    for run in originals:
        original_text = run.text
        label_part = original_text[:max(0, boundary - offset)]
        if label_part:
            run.text = label_part
        else:
            run._r.getparent().remove(run._r)
        offset += len(original_text)
    value_run = paragraph.add_run(value)
    if properties is not None:
        value_run._r.insert(0, properties)
    _align_cover_value(paragraph, width)


def _replace_cover_date(paragraph, value):
    # Setting run.text would discard a page break sharing the same date run.
    texts = paragraph._p.xpath("./w:r/w:t")
    if not texts:
        paragraph.add_run(value)
        return
    texts[0].text = value
    for text in texts[1:]:
        text.text = ""


def _is_cover_spacer(paragraph):
    if paragraph.text.strip() or paragraph._p.xpath("./w:pPr/w:sectPr | ./w:pPr/w:pageBreakBefore"):
        return False
    # A visually empty field, image, bookmark, or page break still carries content.
    for child in paragraph._p:
        if child.tag == qn("w:pPr"):
            continue
        if child.tag != qn("w:r"):
            return False
        if any(node.tag not in {qn("w:rPr"), qn("w:t")} for node in child):
            return False
    return True


def _cover_spacing(paragraph):
    """Read existing line/paragraph spacing from direct, style, and default XML."""
    properties = [paragraph._p.pPr]
    style = paragraph.style
    while style is not None:
        properties.append(style.element.pPr)
        style = style.base_style
    properties.extend(paragraph.part.document.styles.element.xpath("./w:docDefaults/w:pPrDefault/w:pPr"))
    values = {}
    for prop in properties:
        spacing = prop.find(qn("w:spacing")) if prop is not None else None
        if spacing is not None:
            for name in ("line", "lineRule", "before", "after"):
                value = spacing.get(qn(f"w:{name}"))
                if value is not None:
                    values.setdefault(name, value)
        snap = prop.find(qn("w:snapToGrid")) if prop is not None else None
        if snap is not None:
            values.setdefault("snapToGrid", snap.get(qn("w:val"), "1"))
    return values


def _cover_line_height(paragraph):
    spacing = _cover_spacing(paragraph)
    rule = spacing.get("lineRule", "auto")
    font = max([_font_twips(paragraph)] + [_font_twips(paragraph, run) for run in paragraph.runs])
    line = int(spacing.get("line", "240"))
    height = line if rule == "exact" else (max(line, font) if rule == "atLeast" else math.ceil(font * line / 240))
    grid = paragraph.part.document.sections[0]._sectPr.find(qn("w:docGrid"))
    # Nonempty cover lines snap to the template grid; its empty spacer lines
    # retain their configured line height (e.g. 31.2 pt versus 22 pt in CY).
    if rule != "exact" and paragraph.text.strip() and spacing.get("snapToGrid", "1") not in {"0", "false", "off"}:
        if grid is not None and grid.get(qn("w:type")) in {"lines", "linesAndChars"}:
            pitch = int(grid.get(qn("w:linePitch"), "0"))
            if pitch > 0:
                height = math.ceil(height / pitch) * pitch
    return height


def _reclaim_cover_spacing(paragraphs, height):
    removed = 0
    for paragraph in reversed(paragraphs):
        if height <= 0:
            break
        if not _is_cover_spacer(paragraph):
            continue
        spacing = _cover_spacing(paragraph)
        spacer_height = _cover_line_height(paragraph) + int(spacing.get("before", "0")) + int(spacing.get("after", "0"))
        if height >= spacer_height:
            paragraph._p.getparent().remove(paragraph._p)
            removed += 1
            height -= spacer_height
        else:
            # Retain the unused portion of the last spacer instead of removing
            # another whole line and unnecessarily moving the cover footer up.
            paragraph.paragraph_format.line_spacing = Twips(spacer_height - height)
            paragraph.paragraph_format.space_before = Twips(0)
            paragraph.paragraph_format.space_after = Twips(0)
            snap = paragraph._p.get_or_add_pPr().find(qn("w:snapToGrid"))
            if snap is None:
                snap = OxmlElement("w:snapToGrid")
                paragraph._p.pPr.insert_element_before(snap, "w:spacing")
            snap.set(qn("w:val"), "0")
            height = 0
    return removed


def fill_cover_fields(document, product: str, user: str, date: CalendarDate | None = None) -> dict:
    """Fill controlled cover fields, preserving its layout and multiline value column.

    Explicit extra value lines consume the template's own line/grid height.
    Reclaim only that height from plain spacers before the company/date pair;
    never change the title, page geometry, body, or section/page-break paragraphs.
    """
    date = date or CalendarDate.today()
    paragraphs = list(_cover_paragraphs(document))
    result = {"filled_fields": [], "continuation_lines": 0, "removed_spacers": 0}
    last_field = -1
    date_index = None
    extra_height = 0
    for index, paragraph in enumerate(paragraphs):
        match = _COVER_FIELD.fullmatch(paragraph.text)
        if match:
            label = re.sub(r"\s+", "", match.group("label"))
            value = str(user if label.startswith("使用") else product).replace("\r\n", "\n").replace("\r", "\n")
            extra_lines = value.count("\n") - match.group("value").count("\n")
            result["continuation_lines"] += extra_lines
            extra_height += extra_lines * _cover_line_height(paragraph)
            _replace_cover_value(paragraph, match, value)
            result["filled_fields"].append(label)
            last_field = index
        elif _COVER_DATE.fullmatch(paragraph.text.strip()):
            _replace_cover_date(paragraph, f"{date.year}年{date.month}月{date.day}日")
            date_index = index
    result["continuation_lines"] = max(0, result["continuation_lines"])
    if date_index is None or last_field < 0:
        return result
    company_index = next((index for index in range(date_index - 1, last_field, -1) if paragraphs[index].text.strip()), None)
    if company_index is None:
        return result
    company, dated = paragraphs[company_index], paragraphs[date_index]
    company.paragraph_format.keep_with_next = True
    dated.paragraph_format.keep_together = True
    result["removed_spacers"] = _reclaim_cover_spacing(paragraphs[last_field + 1:company_index], max(0, extra_height))
    return result


def normalize_cover_phase(value: str | None) -> str:
    """Return a validated F/C/S/D cover phase.

    The cover phase is independent from the development-process class
    (全新/改型I/改型II/改型III), so it must never be inferred from it.
    """

    phase = str(value or "").strip().upper()
    if phase and phase not in ALLOWED_COVER_PHASES:
        raise ValueError("研制阶段只能是 F、C、S、D 之一")
    return phase


def apply_cover_phase(document, value: str | None) -> bool:
    """Replace the template cover placeholder without changing its styling."""

    phase = normalize_cover_phase(value)
    if not phase:
        return False

    for paragraph in document.paragraphs:
        compact = re.sub(r"\s+", "", paragraph.text or "")
        if not compact.startswith("研制阶段"):
            continue

        replacement = f"研制阶段：{phase}"
        runs = paragraph.runs
        if runs:
            runs[0].text = replacement
            for run in runs[1:]:
                run.text = ""
        else:
            paragraph.add_run(replacement)
        return True
    return False
