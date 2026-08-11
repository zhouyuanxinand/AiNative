"""Read a source document's own title, identifier and revision.

This module deliberately knows nothing about taskbook chapter numbers,
product families or acceptance fixtures.  It is used by the production
pipeline when rebuilding the compilation-basis section from the uploaded
design input.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from lxml import etree


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{W}}}"


def _paragraph_text(paragraph) -> str:
    return "".join(
        text.text or "" for text in paragraph.findall(f".//{_W}t")
    ).strip()


def _cell_text(cell) -> str:
    return "".join(text.text or "" for text in cell.findall(f".//{_W}t")).strip()


def read_document_identity(path: str | Path, kind: str) -> dict[str, str]:
    """Extract identity from the uploaded DOCX without inventing metadata.

    ``kind`` is limited to ``tech`` and ``spec`` because they use different
    controlled identifier patterns.  Missing identifiers and revisions are
    returned as empty strings; the title alone may fall back to the clean
    filename.
    """

    if kind not in {"tech", "spec"}:
        raise ValueError(f"unsupported document identity kind: {kind}")

    source = Path(path)
    with zipfile.ZipFile(source, "r") as package:
        root = etree.fromstring(package.read("word/document.xml"))
        xml_texts: list[str] = []
        for name in package.namelist():
            if not name.endswith(".xml"):
                continue
            try:
                xml_texts.append(
                    "".join(etree.fromstring(package.read(name)).itertext())
                )
            except etree.XMLSyntaxError:
                continue

    texts = [
        _paragraph_text(paragraph)
        for paragraph in root.findall(f".//{_W}p")
        if _paragraph_text(paragraph)
    ]
    keyword = "技术要求" if kind == "tech" else "产品规范"
    title = next(
        (
            re.sub(r"^\d+(?:\.\d+)*\s*", "", text).strip()
            for text in texts
            if keyword in text and 4 < len(text) < 80 and "编制" not in text
        ),
        source.stem,
    )
    title = re.sub(r"[_（(]?上传[）)]?$", "", title).strip(" _")

    all_text = "\n".join(texts + xml_texts)
    if kind == "tech":
        number_match = re.search(r"(?<!\d)\d{3}-\d{8}(?!\d)", all_text)
    else:
        number_match = re.search(
            r"Q/\s*[0-9A-Z]+\s*\d+(?:\.\d+)*-\d{4}",
            all_text,
            re.I,
        )

    versions: list[str] = []
    for table in root.findall(f".//{_W}tbl"):
        rows = table.findall(f"{_W}tr")
        if len(rows) < 2 or "版本" not in _cell_text(rows[0]):
            continue
        for row in rows[1:]:
            first_cell = row.find(f"{_W}tc")
            value = _cell_text(first_cell) if first_cell is not None else ""
            if re.fullmatch(r"[A-Z]", value.strip(), re.I):
                versions.append(value.strip().upper())

    return {
        "title": title,
        "number": (
            re.sub(r"\s+", "", number_match.group(0)) if number_match else ""
        ),
        "version": max(versions) if versions else "",
    }
