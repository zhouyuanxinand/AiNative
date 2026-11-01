"""Read-only image occurrence statistics shared by pipeline and HTML reports."""
from __future__ import annotations

import zipfile
from pathlib import Path

from lxml import etree


_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_V = "{urn:schemas-microsoft-com:vml}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


def count_image_references(root) -> int:
    """Count image placements, including VML, rather than unique media parts.

    AlternateContent represents the same placement in alternative encodings.
    Count its first Choice, or Fallback when there is no Choice, exactly once.
    This is an object statistic, not a browser/Office rendering capability test.
    """
    count = 0
    pending = [root]
    while pending:
        node = pending.pop()
        if node.tag == _MC + "AlternateContent":
            branch = node.find(_MC + "Choice")
            if branch is None:
                branch = node.find(_MC + "Fallback")
            if branch is not None:
                pending.append(branch)
            continue
        if node.tag == _A + "blip" and (node.get(_R + "embed") or node.get(_R + "link")):
            count += 1
        elif node.tag == _V + "imagedata" and node.get(_R + "id"):
            count += 1
        pending.extend(node)
    return count


def document_image_stats(docx_path: str | Path) -> dict[str, int]:
    with zipfile.ZipFile(docx_path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
        media_count = sum(name.startswith("word/media/") and not name.endswith("/")
                          for name in archive.namelist())
    # Keep the existing result field name for report/UI consumers.
    return {"drawing_count": count_image_references(root), "media_count": media_count}
