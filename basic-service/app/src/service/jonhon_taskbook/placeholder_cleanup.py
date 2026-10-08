"""Product-neutral final cleanup for unresolved template placeholders.

This module deliberately contains no product, model, source-section, or
template-section knowledge.  It is safe to load from the production web
pipeline after the controlled fill plan has been rendered.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from lxml import etree

from .config import W
from .docx_io import fill_cell, get_cell_text, get_para_text, set_para_text

NO_VALUE_MARKER = "/"
DESIGNER_FILL = "无"
BUDGET_FILL = "—"

_UNRESOLVED_VALUE_PLACEHOLDER = re.compile(
    r"(?i)(?:\[\s*XXh\s*\]|（\s*XXh\s*）|\(\s*XXh\s*\)|\bXXh\b)"
)


def _replace_unresolved_value_placeholder(text: str) -> str:
    return _UNRESOLVED_VALUE_PLACEHOLDER.sub(NO_VALUE_MARKER, text)


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
    source_tables = {
        table for table in root.findall(f".//{{{W}}}tbl")
        if _table_signature(table) in source_table_signatures
    }
    for para in list(root.findall(f".//{{{W}}}p")):
        if _belongs_to_source_table(para, source_tables):
            continue
        text = get_para_text(para)
        stripped = text.strip()
        replaced = _replace_unresolved_value_placeholder(text)
        if replaced != text:
            set_para_text(para, replaced)
            changed += 1
            continue
        if stripped in {"……", "..."} or re.fullmatch(r"\.{4,}", stripped):
            set_para_text(para, DESIGNER_FILL)
            changed += 1
        elif stripped.endswith("……") and len(stripped) < 40:
            set_para_text(para, DESIGNER_FILL)
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
            set_para_text(para, DESIGNER_FILL)
            changed += 1

    for cell in root.findall(f".//{{{W}}}tc"):
        if _belongs_to_source_table(cell, source_tables):
            continue
        text = get_cell_text(cell)
        replaced = _replace_unresolved_value_placeholder(text)
        if replaced != text:
            fill_cell(cell, replaced)
            changed += 1
        elif text.strip() in {"……", "..."} or re.fullmatch(r"\.{4,}", text.strip()):
            fill_cell(cell, DESIGNER_FILL)
            changed += 1
        elif re.search(r"20[xX]{2}", text) or "XX号" in text:
            fill_cell(cell, BUDGET_FILL)
            changed += 1
    return changed


def final_placeholder_sweep_docx(
    docx_path: str | Path, *, source_paths=()
) -> int:
    """Apply :func:`final_placeholder_sweep` to a built DOCX package."""
    path = Path(docx_path)
    with zipfile.ZipFile(path, "r") as source:
        root = etree.fromstring(source.read("word/document.xml"))

    changed = final_placeholder_sweep(
        root,
        source_table_signatures=_source_table_signatures(source_paths),
    )
    if not changed:
        return 0

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
