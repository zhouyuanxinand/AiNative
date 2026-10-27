"""读取模板标题的说明文字和表格元数据，不使用显示章节号。"""
from __future__ import annotations

from docx import Document
from lxml import etree

from .template_scanner import scan_template_tree


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{W}}}"
_RED_VALUES = {"FF0000", "C00000", "E00000", "D00000", "F00000", "B00000", "FF4040"}


def _paragraph_text(element) -> str:
    return "".join(node.text or "" for node in element.findall(f".//{_W}t")).strip()


def _is_guidance(element) -> bool:
    for color in element.findall(f".//{_W}color"):
        if (color.get(f"{_W}val") or "").upper() in _RED_VALUES:
            return True
    return bool(element.findall(f".//{_W}highlight"))


def parse_template_metadata(template_path: str) -> list[dict]:
    """按实时标题树返回说明、表头等元数据，节点身份始终是 ``slot-*``。"""
    document = Document(template_path)
    nodes = scan_template_tree(template_path)
    paragraph_nodes = {
        document.paragraphs[int(node["paragraph_index"])]._p: node
        for node in nodes
        if int(node["paragraph_index"]) < len(document.paragraphs)
    }

    result: list[dict] = []
    current: dict | None = None
    for element in document.element.body:
        tag = etree.QName(element).localname
        if tag == "p" and element in paragraph_nodes:
            node = paragraph_nodes[element]
            current = {
                "id": node["id"],
                "title": node["title"],
                "instructions": [],
                "has_table": False,
                "table_headers": [],
            }
            result.append(current)
            continue
        if current is None:
            continue
        if tag == "p":
            text = _paragraph_text(element)
            if text and _is_guidance(element):
                current["instructions"].append(text)
        elif tag == "tbl":
            current["has_table"] = True
            rows = element.findall(f"{_W}tr")
            if rows and not current["table_headers"]:
                current["table_headers"] = [
                    "".join(node.text or "" for node in cell.findall(f".//{_W}t")).strip()
                    for cell in rows[0].findall(f"{_W}tc")
                ]
                current["table_headers"] = [
                    value for value in current["table_headers"] if value
                ]
    return result
