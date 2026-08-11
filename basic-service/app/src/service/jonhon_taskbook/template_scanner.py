# -*- coding: utf-8 -*-
"""实时扫描任意任务书模板的标题树。

现行受控流程只把标题语义路径作为定位依据。章节显示编号、标题在文档中的
绝对顺序和段落索引都不是业务身份；它们只用于本次打开文档时执行 OOXML 操作。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from docx import Document
from docx.oxml.ns import qn


_DISPLAY_NUMBER = re.compile(
    # Display numbering is presentation only.  Support Arabic chapter paths,
    # Chinese ``第…章`` and common Chinese list prefixes such as ``一、`` or
    # ``（一）``; none of these values become a slot identity.
    r"^\s*(?:第\s*[一二三四五六七八九十百零〇]+\s*章\s*|[（(]\s*[一二三四五六七八九十百零〇]+\s*[）)]\s*|[一二三四五六七八九十百零〇]+\s*[、.．]|\d+(?:\.\d+)*(?:\s+|[、)）]|[.．](?!\d)))"
)
_HEADING_STYLE = re.compile(r"(?:Heading|标题)\s*([1-9])", re.I)


def semantic_title(text: str) -> str:
    """去掉可变显示编号，只保留标题本身。"""
    title = _DISPLAY_NUMBER.sub("", text or "").strip()
    # 标题末尾的全/半角冒号、分号和句号只是显示标点，不属于槽位身份。
    # 客户模板可能把“安装尺寸”改成“安装尺寸：”，两者必须命中同一语义槽。
    return re.sub(r"[\s:：;；。]+$", "", title).strip()


def heading_level(paragraph) -> int:
    """从标题样式或 OOXML outlineLvl 读取层级，不解析标题里的章节号。"""
    style_name = paragraph.style.name if paragraph.style else ""
    style_id = paragraph.style.style_id if paragraph.style else ""
    for value in (style_name, style_id):
        match = _HEADING_STYLE.search(value or "")
        if match:
            return int(match.group(1))

    paragraph_properties = paragraph._p.find(qn("w:pPr"))
    if paragraph_properties is not None:
        outline = paragraph_properties.find(qn("w:outlineLvl"))
        if outline is not None:
            raw = outline.get(qn("w:val"))
            if raw is not None and str(raw).isdigit():
                return min(9, int(raw) + 1)

    if paragraph.style is not None:
        style_properties = paragraph.style.element.find(qn("w:pPr"))
        if style_properties is not None:
            outline = style_properties.find(qn("w:outlineLvl"))
            if outline is not None:
                raw = outline.get(qn("w:val"))
                if raw is not None and str(raw).isdigit():
                    return min(9, int(raw) + 1)
    return 0


def scan_template_tree(template_path: str) -> list[dict[str, Any]]:
    """返回实时标题树；节点 ID 不包含章节号或绝对顺序。"""
    document = Document(template_path)
    tree: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    duplicate_count: dict[str, int] = {}

    for paragraph_index, paragraph in enumerate(document.paragraphs):
        raw_heading = paragraph.text.strip()
        level = heading_level(paragraph)
        if not raw_heading or not level:
            continue
        title = semantic_title(raw_heading)
        if not title:
            continue

        while stack and int(stack[-1]["level"]) >= level:
            stack.pop()
        parent = stack[-1] if stack else None
        path_titles = [str(node["title"]) for node in stack] + [title]
        semantic_path = " / ".join(path_titles)
        normalized_path = re.sub(r"\s+", "", semantic_path)
        duplicate_count[normalized_path] = duplicate_count.get(normalized_path, 0) + 1
        occurrence = duplicate_count[normalized_path]
        # 同一路径重名时只用 occurrence 消歧；普通章节的 ID 与插入位置无关。
        identity = normalized_path if occurrence == 1 else f"{normalized_path}#{occurrence}"
        node = {
            "id": f"slot-{hashlib.sha1(identity.encode('utf-8')).hexdigest()[:12]}",
            "heading": raw_heading,
            "title": title,
            "semantic_path": semantic_path,
            "level": level,
            "parent_id": parent["id"] if parent else "",
            # paragraph_index 是本次文档实例的执行坐标，不是跨模板身份。
            "paragraph_index": paragraph_index,
            "occurrence": occurrence,
        }
        tree.append(node)
        stack.append(node)
    return tree


def scan_template(template_path: str) -> dict[str, str]:
    """兼容调用名，但返回 ``{slot-id: 无编号标题}``，不再返回数字槽位。"""
    return {node["id"]: node["title"] for node in scan_template_tree(template_path)}


def build_semantic_heading_map(template_path: str) -> list[tuple[tuple[str, ...], str]]:
    """生成填充器使用的 ``[(标题关键词, slot-id)]`` 运行时映射。"""
    return [
        ((str(node["title"]),), str(node["id"]))
        for node in scan_template_tree(template_path)
    ]


def build_heading_map(template_path: str) -> list[tuple[tuple[str, ...], str]]:
    """旧函数名的安全别名；同样只返回无编号语义槽位。"""
    return build_semantic_heading_map(template_path)


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("用法: python template_scanner.py <模板.docx>")
    else:
        print(json.dumps(scan_template_tree(path), ensure_ascii=False, indent=2))
