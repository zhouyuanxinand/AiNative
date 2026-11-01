"""Product-neutral final cleanup for unresolved template placeholders.

This module deliberately contains no product, model, source-section, or
template-section knowledge.  It is safe to load from the production web
pipeline after the controlled fill plan has been rendered.
"""

from __future__ import annotations

import re
import zipfile
from copy import deepcopy
from pathlib import Path

from lxml import etree

from .config import W
from .docx_io import MANUAL_FILL_COLOR, MANUAL_FILL_MARKER, fill_cell, get_cell_text, get_para_text, set_para_text
from .renderer.table_style_engine import normalize_table_typography

NO_VALUE_MARKER = "/"
DESIGNER_FILL = MANUAL_FILL_MARKER
BUDGET_FILL = "—"

_UNRESOLVED_VALUE_PLACEHOLDER = re.compile(
    r"(?i)(?:\[\s*XXh\s*\]|（\s*XXh\s*）|\(\s*XXh\s*\)|\bXXh\b)"
)


def _replace_unresolved_value_placeholder(text: str) -> str:
    return _UNRESOLVED_VALUE_PLACEHOLDER.sub(NO_VALUE_MARKER, text)


def _pending_run(original_run):
    run = etree.Element(f"{{{W}}}r", attrib=dict(original_run.attrib))
    original_props = original_run.find(f"{{{W}}}rPr")
    props = deepcopy(original_props) if original_props is not None else etree.Element(f"{{{W}}}rPr")
    run.append(props)
    for node in list(props.findall(f"{{{W}}}vertAlign")):
        props.remove(node)
    for tag, value in (("color", MANUAL_FILL_COLOR), ("b", "1"), ("i", "0"), ("iCs", "0")):
        node = props.find(f"{{{W}}}{tag}")
        if node is None:
            node = etree.SubElement(props, f"{{{W}}}{tag}")
        node.set(f"{{{W}}}val", value)
    etree.SubElement(run, f"{{{W}}}t").text = DESIGNER_FILL
    return run


def _mark_pending_spans(para, pattern: str) -> None:
    """Replace only template gaps; preserve surrounding runs and paragraph XML."""
    text = get_para_text(para)
    spans = [match.span() for match in re.finditer(pattern, text)]
    offset = 0
    for run in list(para.iter(f"{{{W}}}r")):
        text_nodes = run.findall(f"{{{W}}}t")
        length = sum(len(node.text or "") for node in text_nodes)
        if not any(start < offset + length and end > offset for start, end in spans):
            offset += length
            continue
        pieces = []

        def empty_run():
            value = etree.Element(run.tag, attrib=dict(run.attrib))
            props = run.find(f"{{{W}}}rPr")
            if props is not None:
                value.append(deepcopy(props))
            return value

        current = empty_run()
        for child in run:
            if child.tag == f"{{{W}}}rPr":
                continue
            if child.tag != f"{{{W}}}t":
                current.append(deepcopy(child))
                continue
            value = child.text or ""
            cursor = 0
            for start, end in spans:
                if end <= offset or start >= offset + len(value):
                    continue
                left, right = max(0, start - offset), min(len(value), end - offset)
                if left > cursor:
                    prefix = deepcopy(child)
                    prefix.text = value[cursor:left]
                    prefix.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                    current.append(prefix)
                if start >= offset:
                    pieces.extend((current, _pending_run(run)))
                    current = empty_run()
                cursor = right
            if cursor < len(value):
                suffix = deepcopy(child)
                suffix.text = value[cursor:]
                suffix.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                current.append(suffix)
            offset += len(value)
        pieces.append(current)
        parent = run.getparent()
        index = parent.index(run)
        for piece in pieces:
            if any(child.tag != f"{{{W}}}rPr" for child in piece):
                parent.insert(index, piece)
                index += 1
        parent.remove(run)


def _set_pending_cell(cell) -> None:
    for child in list(cell):
        if child.tag != f"{{{W}}}tcPr":
            cell.remove(child)
    etree.SubElement(cell, f"{{{W}}}p").append(_pending_run(etree.Element(f"{{{W}}}r")))


def _table_signature(table) -> tuple:
    """Compare copied table content independently of Word presentation XML."""
    return tuple(
        tuple(get_cell_text(cell) for cell in row.findall(f"{{{W}}}tc"))
        for row in table.findall(f"{{{W}}}tr")
    )


def _source_table_signatures(source_paths) -> set[tuple]:
    signatures = set()
    for source_path in source_paths:
        with zipfile.ZipFile(source_path) as package:
            root = etree.fromstring(package.read("word/document.xml"))
        signatures.update(
            _table_signature(table)
            for table in root.findall(f".//{{{W}}}tbl")
        )
    return signatures


def _belongs_to_source_table(element, source_tables: set) -> bool:
    return any(
        ancestor in source_tables
        for ancestor in element.iterancestors(f"{{{W}}}tbl")
    )


def final_placeholder_sweep(root, *, source_table_signatures=()) -> int:
    """Remove unresolved display placeholders without inventing facts."""
    changed = 0
    changed_tables = set()
    source_tables = {
        table for table in root.findall(f".//{{{W}}}tbl")
        if _table_signature(table) in source_table_signatures
    }
    for para in list(root.findall(f".//{{{W}}}p")):
        if _belongs_to_source_table(para, source_tables):
            continue
        before = changed
        text = get_para_text(para)
        stripped = text.strip()
        replaced = _replace_unresolved_value_placeholder(text)
        if replaced != text:
            set_para_text(para, replaced)
            changed += 1
        elif stripped in {"……", "..."} or re.fullmatch(r"\.{4,}", stripped):
            _mark_pending_spans(para, r"……|\.{3,}")
            changed += 1
        elif stripped.endswith("……") and len(stripped) < 40:
            _mark_pending_spans(para, r"……(?=\s*$)")
            changed += 1
        elif re.fullmatch(r"20[xX]{2}年[xX]月", stripped):
            set_para_text(para, BUDGET_FILL)
            changed += 1
        elif re.search(r"20[xX]{2}", stripped) and len(stripped) < 30:
            set_para_text(para, BUDGET_FILL)
            changed += 1
        elif (
            re.search(r"\bXX\b", stripped)
            and "MTBF" not in stripped
            and "xxxx" not in stripped.lower()
        ):
            _mark_pending_spans(para, r"\bXX\b")
            changed += 1
        if changed != before:
            changed_tables.update(para.iterancestors(f"{{{W}}}tbl"))

    for cell in root.findall(f".//{{{W}}}tc"):
        if _belongs_to_source_table(cell, source_tables):
            continue
        before = changed
        text = get_cell_text(cell)
        replaced = _replace_unresolved_value_placeholder(text)
        if replaced != text:
            fill_cell(cell, replaced)
            changed += 1
        elif text.strip() in {"……", "..."} or re.fullmatch(r"\.{4,}", text.strip()):
            _set_pending_cell(cell)
            changed += 1
        elif re.search(r"20[xX]{2}", text) or "XX号" in text:
            fill_cell(cell, BUDGET_FILL)
            changed += 1
        if changed != before:
            changed_tables.update(cell.iterancestors(f"{{{W}}}tbl"))
    # This sweep runs after postprocess in production. Replacement runs must
    # retain the shared table font contract, including newly emptied cells.
    for table in changed_tables:
        normalize_table_typography(table)
    return changed


def final_placeholder_sweep_docx(
    docx_path: str | Path, *, source_paths=()
) -> int:
    """Apply :func:`final_placeholder_sweep` to a built DOCX package."""
    path = Path(docx_path)
    with zipfile.ZipFile(path, "r") as source:
        root = etree.fromstring(source.read("word/document.xml"))
        styles_root = etree.fromstring(source.read("word/styles.xml")) if "word/styles.xml" in source.namelist() else None

    changed = final_placeholder_sweep(
        root,
        source_table_signatures=_source_table_signatures(source_paths),
    )
    if not changed:
        return 0

    # This is the last DOCX write in the controlled pipeline. A changed table
    # receives font properties again above, so retain valid property order.
    from jonhon_taskbook.ooxml_properties import normalize_properties

    normalize_properties(root, styles_root=styles_root)
    document_xml = etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )
    temp_path = path.with_suffix(path.suffix + ".placeholder.tmp")
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temp_path, "w", zipfile.ZIP_DEFLATED
        ) as target:
            for item in source.infolist():
                payload = (
                    document_xml
                    if item.filename == "word/document.xml"
                    else source.read(item.filename)
                )
                target.writestr(item, payload)
        path.unlink()
        temp_path.rename(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return changed
