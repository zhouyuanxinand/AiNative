# -*- coding: utf-8 -*-
"""
extractor.py — 通用文档结构解析与内容提取
同时识别 Word 标题样式/大纲级别与可选章节号；章节号仅作溯源信息，
不作为语义路由或模板槽位身份。
"""
from __future__ import annotations
import re, copy
from dataclasses import dataclass
from docx import Document
from docx.oxml.ns import qn

_SEC_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)")


@dataclass
class Para:
    idx: int
    text: str
    sec_num: str
    depth: int
    is_heading: bool
    heading_text: str
    has_image: bool
    raw: object


def _has_image(p) -> bool:
    return (len(p._p.findall(".//" + qn("w:drawing"))) > 0 or
            len(p._p.findall(".//" + qn("a:blip"))) > 0)


def parse_doc(doc: Document) -> list:
    result = []
    for i, p in enumerate(doc.paragraphs):
        text = "".join(r.text or "" for r in p.runs).strip()
        m = _SEC_RE.match(text)
        sec_num = m.group(1) if m else ""
        style_name = str(getattr(getattr(p, "style", None), "name", "") or "")
        style_match = re.search(r"(?:Heading|标题)\s*(\d+)", style_name, re.I)
        outline_values = p._p.xpath("./w:pPr/w:outlineLvl/@w:val")
        outline_depth = int(outline_values[0]) + 1 if outline_values else 0
        style_depth = int(style_match.group(1)) if style_match else 0
        numeric_depth = sec_num.count(".") + 1 if sec_num else 0
        depth = outline_depth or style_depth or numeric_depth
        is_heading = bool(outline_depth or style_depth or sec_num)
        heading_text = m.group(2).strip() if m else text
        result.append(Para(
            idx=i, text=text, sec_num=sec_num, depth=depth,
            is_heading=is_heading, heading_text=heading_text,
            has_image=_has_image(p), raw=p._p
        ))
    return result


def extract_section(paras: list, prefix: str) -> list:
    on, depth, out = False, prefix.count(".") + 1, []
    for para in paras:
        if not para.text and not para.has_image:
            continue
        n = para.sec_num
        if n == prefix:
            on = True; continue
        if on:
            if n and n.count(".") + 1 <= depth and n != prefix:
                break
            if not n:
                out.append(para)
    return out


def extract_broad(paras: list, prefix: str) -> list:
    on, depth, out = False, prefix.count(".") + 1, []
    for para in paras:
        if not para.text and not para.has_image:
            continue
        n = para.sec_num
        if n == prefix:
            on = True; continue
        if on:
            if n and n.count(".") + 1 <= depth and not n.startswith(prefix + "."):
                break
            if not n:
                out.append(para)
    return out


def find_val(paras: list, sec_prefix: str, keywords: list) -> str:
    found = False
    for para in paras:
        n = para.sec_num
        t = para.text
        if n and found and not n.startswith(sec_prefix):
            break
        if n and n.startswith(sec_prefix) and any(kw in t for kw in keywords):
            found = True; continue
        if found and not n and t:
            return t
    return ""


def extract_table_rows(doc: Document, idx: int) -> list:
    if idx >= len(doc.tables):
        return []
    out = []
    for row in doc.tables[idx].rows:
        cells = [c.text.strip() for c in row.cells if c.text.strip()]
        if cells:
            out.append("  ".join(cells))
    return out


def _sec_range(paras: list, prefix: str):
    """
    返回 (start_body_idx, end_body_idx)：在 doc.element.body 子元素序列中的范围。
    paras 里的 raw 是 w:p element，需要找它在 body 里的位置。
    """
    depth = prefix.count(".") + 1
    start_raw, end_raw = None, None

    for para in paras:
        n = para.sec_num
        if n == prefix:
            start_raw = para.raw
        elif start_raw is not None and n and n.count(".") + 1 <= depth and not n.startswith(prefix + "."):
            end_raw = para.raw
            break

    return start_raw, end_raw  # w:p elements, None means not found / end of doc


def copy_tables_from_section(doc: Document, paras: list, prefix: str) -> list:
    """返回章节内所有表格的 (deepcopy_tbl_element, preceding_caption)"""
    start_raw, end_raw = _sec_range(paras, prefix)
    if start_raw is None:
        return []

    result, last_caption, in_range = [], "", False
    for child in doc.element.body:
        if child is start_raw:
            in_range = True
            continue
        if end_raw is not None and child is end_raw:
            break
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if not in_range:
            continue
        if tag == "p":
            txt = "".join(t.text or "" for t in child.findall(".//" + qn("w:t")))
            if txt.strip():
                last_caption = txt.strip()
        elif tag == "tbl":
            result.append((copy.deepcopy(child), last_caption))
            last_caption = ""

    return result


def copy_images_from_section(doc, paras: list, prefix: str, source_doc: str = "tech") -> list:
    """返回章节内所有含图片段落的上下文信息。"""
    start_raw, end_raw = _sec_range(paras, prefix)
    if start_raw is None:
        return []

    _DRW = qn("w:drawing")
    _BLP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"

    body_items = []
    in_range = False
    for child in doc.element.body:
        if child is start_raw:
            in_range = True
            continue
        if end_raw is not None and child is end_raw:
            break
        if not in_range:
            continue
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag != "p":
            continue
        txt = "".join(t.text or "" for t in child.findall(".//" + qn("w:t"))).strip()
        has_img = (child.find(".//" + _DRW) is not None or
                   child.find(".//" + _BLP) is not None)
        body_items.append({"raw": child, "text": txt, "has_img": has_img})

    result = []
    last_caption = ""
    for idx, item in enumerate(body_items):
        txt = item["text"]
        has_img = item["has_img"]
        if txt and not has_img:
            last_caption = txt
            continue
        if not has_img:
            continue

        next_text = ""
        for nxt in body_items[idx + 1:]:
            if nxt["text"]:
                next_text = nxt["text"]
                break

        result.append({
            "image_el": copy.deepcopy(item["raw"]),
            "caption": last_caption,
            "section_prefix": prefix,
            "prev_text": last_caption,
            "next_text": next_text,
            "anchor_index": idx,
            "has_caption": bool(last_caption),
            "source_doc": source_doc,
        })
        last_caption = ""
    return result


def get_cover_field(doc: Document, table_idx: int,
                    row_keywords: list, value_col: int) -> str:
    if table_idx >= len(doc.tables):
        return ""
    for row in doc.tables[table_idx].rows:
        cells = [c.text.strip() for c in row.cells]
        if not cells or len(cells) <= value_col:
            continue
        cell0_normalized = re.sub(r"\s+", "", cells[0])
        if any(re.sub(r"\s+", "", kw) in cell0_normalized for kw in row_keywords):
            return cells[value_col]
    return ""


def dedup_stds(lines: list, sort_order: list) -> list:
    seen: dict = {}
    for s in lines:
        if not s.strip():
            continue
        k = re.sub(r"\s+", "", s.strip()).upper()
        if k not in seen or len(s) > len(seen[k]):
            seen[k] = s

    def sort_key(x: str):
        for i, pfx in enumerate(sort_order):
            if x.startswith(pfx):
                return (i, re.sub(r"\s+", "", x[:30]))
        return (len(sort_order), re.sub(r"\s+", "", x[:30]))

    return sorted(seen.values(), key=sort_key)
