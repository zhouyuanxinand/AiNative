"""Taskbook content view and narrowly scoped, structure-preserving DOCX edits.

This is a content projection, not a Word pagination engine. Element identities are
bound to the source archive hash. Edits replace only ``word/document.xml``; all
other package members (including styles, numbering, media and headers) survive
byte-for-byte. Files are never converted to HTML and rebuilt to save an edit.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import posixpath
import re
import tempfile
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile

from lxml import etree

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "v": "urn:schemas-microsoft-com:vml",
}
W = "{" + NS["w"] + "}"
R = "{" + NS["r"] + "}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
DOCUMENT_PART = "word/document.xml"
IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 20 * 1024 * 1024
MAX_XML_BYTES = 32 * 1024 * 1024
MAX_OPERATIONS = 1000
MAX_PARAGRAPH_CHARS = 100000


def _xml(data: bytes):
    return etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True))


def _load(path):
    file_path = Path(path)
    if file_path.suffix.lower() != ".docx":
        raise ValueError("内容审阅仅支持 DOCX；DOC、PDF 或图片请先转换为可审阅的 DOCX。")
    payload = file_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    try:
        archive = ZipFile(io.BytesIO(payload))
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("DOCX 包含重复文件部件，无法安全审阅。")
        if archive.getinfo(DOCUMENT_PART).file_size > MAX_XML_BYTES:
            raise ValueError("文档正文过大，无法在内容视图中处理。")
        tree = _xml(archive.read(DOCUMENT_PART))
        body = tree.find(W + "body")
        if body is None:
            raise ValueError("DOCX 缺少正文。")
    except (BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise ValueError("文件不是有效的 DOCX 文档。") from exc
    return payload, digest, archive, tree, body


def _element_id(element, digest):
    path = element.getroottree().getpath(element)
    return f"el-{digest[:16]}-{hashlib.sha256(path.encode()).hexdigest()[:16]}"


def _text_tokens(paragraph):
    # Do not include a nested text box's paragraphs in its containing paragraph.
    for node in paragraph.iter():
        if node.tag not in {W + "t", W + "tab", W + "br", W + "cr"}:
            continue
        parent = node.getparent()
        while parent is not None and parent.tag != W + "p":
            parent = parent.getparent()
        if parent is paragraph:
            yield node


def _token_text(node):
    if node.tag == W + "tab":
        return "\t"
    if node.tag in {W + "br", W + "cr"}:
        return "\n"
    return node.text or ""


def _paragraph_text(paragraph):
    return "".join(_token_text(node) for node in _text_tokens(paragraph))


def _edit_reason(paragraph):
    protected = {
        W + "fldSimple": "该段落包含自动域，请使用版式编辑器修改。",
        W + "fldChar": "该段落包含自动域，请使用版式编辑器修改。",
        W + "instrText": "该段落包含自动域，请使用版式编辑器修改。",
        W + "hyperlink": "该段落包含超链接，请使用版式编辑器修改。",
        W + "sdt": "该段落包含内容控件，请使用版式编辑器修改。",
        W + "ins": "该段落包含修订记录，请使用版式编辑器修改。",
        W + "del": "该段落包含修订记录，请使用版式编辑器修改。",
        W + "moveFrom": "该段落包含修订记录，请使用版式编辑器修改。",
        W + "moveTo": "该段落包含修订记录，请使用版式编辑器修改。",
        W + "txbxContent": "该段落包含文本框，请使用版式编辑器修改。",
    }
    for node in paragraph.iter():
        if node.tag in protected:
            return protected[node.tag]
        if isinstance(node.tag, str) and node.tag.startswith("{http://schemas.openxmlformats.org/officeDocument/2006/math}"):
            return "该段落包含公式，请使用版式编辑器修改。"
    if any(parent.tag in {W + "sdt", W + "ins", W + "del", W + "txbxContent"} for parent in paragraph.iterancestors()):
        return "该段落位于内容控件、文本框或修订范围内，请使用版式编辑器修改。"
    return ""


def _delete_reason(paragraph):
    reason = _edit_reason(paragraph)
    if reason:
        return reason
    special = {W + name for name in ("drawing", "pict", "object", "sectPr", "bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd", "commentReference", "footnoteReference", "endnoteReference")}
    if any(node.tag in special for node in paragraph.iter()):
        return "该段落包含图片、分节或引用标记，不能在内容视图中删除。"
    parent = paragraph.getparent()
    if parent.tag == W + "tc":
        paragraphs = parent.findall(W + "p")
        if len(paragraphs) <= 1:
            return "表格单元格至少需要保留一个段落，可清空文字。"
        siblings = list(parent)
        if siblings[-1] is paragraph and siblings[-2].tag == W + "tbl":
            return "嵌套表格之后必须保留一个段落，可清空文字。"
    return ""


def _styles(archive):
    result = {}
    try:
        root = _xml(archive.read("word/styles.xml"))
    except KeyError:
        return result
    for node in root.findall(W + "style"):
        key = node.get(W + "styleId", "")
        name = node.find(W + "name")
        outline = node.find(f"{W}pPr/{W}outlineLvl")
        base = node.find(W + "basedOn")
        result[key] = {
            "name": name.get(W + "val", key) if name is not None else key,
            "outline": outline.get(W + "val") if outline is not None else None,
            "based_on": base.get(W + "val", "") if base is not None else "",
        }
    return result


def _paragraph_style(paragraph, styles):
    node = paragraph.find(f"{W}pPr/{W}pStyle")
    style_id = node.get(W + "val", "") if node is not None else ""
    info = styles.get(style_id, {})
    name = info.get("name", style_id) or "Normal"
    outline = paragraph.find(f"{W}pPr/{W}outlineLvl")
    raw_outline = outline.get(W + "val") if outline is not None else None
    if raw_outline is None:
        visited = set()
        next_id = style_id
        while next_id and next_id not in visited:
            visited.add(next_id)
            inherited = styles.get(next_id, {})
            raw_outline = inherited.get("outline")
            if raw_outline is not None:
                break
            next_id = inherited.get("based_on", "")
    if raw_outline is not None:
        return name, int(raw_outline) + 1 if str(raw_outline).isdigit() and 0 <= int(raw_outline) < 9 else 0
    match = re.search(r"(?:heading|标题)\s*([1-9])", name + " " + style_id, re.IGNORECASE)
    return name, int(match.group(1)) if match else 0


def _image_catalog(archive):
    relationships = {}
    try:
        for item in _xml(archive.read("word/_rels/document.xml.rels")):
            if item.get("TargetMode") == "External":
                continue
            target = item.get("Target", "")
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("word/" + target)
            if target.startswith("word/media/") and ".." not in PurePosixPath(target).parts:
                relationships[item.get("Id")] = target
    except KeyError:
        pass
    types, overrides = {}, {}
    try:
        for item in _xml(archive.read("[Content_Types].xml")):
            if item.tag.endswith("}Default"):
                types[item.get("Extension", "").lower()] = item.get("ContentType", "")
            elif item.tag.endswith("}Override"):
                overrides[item.get("PartName", "").lstrip("/")] = item.get("ContentType", "")
    except KeyError:
        pass
    return relationships, types, overrides


def document_projection(path, asset_id=None, revision_id=None) -> dict[str, Any]:
    """Return safe structured content, stable within one exact DOCX version."""
    _, digest, archive, _tree, body = _load(path)
    styles = _styles(archive)
    relationships, content_types, overrides = _image_catalog(archive)
    warnings = []
    outline, sections = [], []
    section_stack = []
    image_bytes = 0
    image_cache = {}

    def images(paragraph):
        nonlocal image_bytes
        result = []
        for node in paragraph.iter():
            rid = node.get(R + "embed") if node.tag == "{" + NS["a"] + "}blip" else node.get(R + "id") if node.tag == "{" + NS["v"] + "}imagedata" else None
            if not rid:
                continue
            target = relationships.get(rid)
            item = {"id": _element_id(node, digest), "src": "", "mime": "", "alt": "文档图片", "available": False}
            if target in image_cache:
                cached = image_cache[target]
                if cached.get("available") and image_bytes + cached["byte_size"] > MAX_TOTAL_IMAGE_BYTES:
                    item["reason"] = "图片超出内容视图预览大小，请查看原文件。"
                else:
                    item.update(cached)
                    image_bytes += cached.get("byte_size", 0)
            elif target:
                mime = overrides.get(target) or content_types.get(PurePosixPath(target).suffix.lstrip(".").lower(), "")
                item["mime"] = mime
                try:
                    size = archive.getinfo(target).file_size
                    if mime not in IMAGE_MIMES:
                        item["reason"] = "该图片格式请在原文件或版式视图中查看。"
                    elif size > MAX_IMAGE_BYTES or image_bytes + size > MAX_TOTAL_IMAGE_BYTES:
                        item["reason"] = "图片超出内容视图预览大小，请查看原文件。"
                    else:
                        blob = archive.read(target)
                        image_bytes += len(blob)
                        item.update(src=f"data:{mime};base64," + base64.b64encode(blob).decode("ascii"), available=True, byte_size=len(blob))
                except KeyError:
                    item["reason"] = "文档内图片文件缺失。"
                image_cache[target] = {key: value for key, value in item.items() if key != "id"}
            else:
                item["reason"] = "图片引用不可用。"
            if not item["available"]:
                warning = item.get("reason", "图片无法预览。")
                if warning not in warnings:
                    warnings.append(warning)
            result.append(item)
        return result

    def block(node, body_index, allow_outline=True):
        identity = _element_id(node, digest)
        section_id = section_stack[-1]["id"] if section_stack else ""
        parent_section_id = section_stack[-1].get("parent_id", "") if section_stack else ""
        common = {"id": identity, "source_body_index": body_index, "section_id": section_id, "parent_section_id": parent_section_id}
        if node.tag == W + "p":
            text = _paragraph_text(node)
            style, level = _paragraph_style(node, styles)
            if level and text.strip() and allow_outline:
                while section_stack and section_stack[-1]["level"] >= level:
                    section_stack.pop()
                parent_id = section_stack[-1]["id"] if section_stack else ""
                entry = {"id": identity, "text": text, "title": text, "level": level, "parent_id": parent_id, "source_body_index": body_index}
                outline.append(entry)
                section = dict(entry, block_ids=[])
                sections.append(section)
                section_stack.append(section)
                common.update(section_id=identity, parent_section_id=parent_id)
            if section_stack:
                section_stack[-1]["block_ids"].append(identity)
            reason = _edit_reason(node)
            delete_reason = _delete_reason(node)
            return dict(common, kind="paragraph", text=text, heading_level=level, style=style, editable=not bool(reason), edit_reason=reason, can_delete=not bool(delete_reason), delete_reason=delete_reason, images=images(node))
        if node.tag == W + "tbl":
            rows = []
            vertical = {}
            for row_index, row in enumerate(node.findall(W + "tr")):
                before = row.find(f"{W}trPr/{W}gridBefore")
                col_index = int(before.get(W + "val", "0")) if before is not None else 0
                cells = []
                next_vertical = {}
                for cell in row.findall(W + "tc"):
                    span_node = cell.find(f"{W}tcPr/{W}gridSpan")
                    span = int(span_node.get(W + "val", "1")) if span_node is not None else 1
                    merge = cell.find(f"{W}tcPr/{W}vMerge")
                    if merge is not None and merge.get(W + "val", "continue") == "continue" and col_index in vertical:
                        origin = vertical[col_index]
                        origin["rowspan"] += 1
                        for offset in range(span):
                            next_vertical[col_index + offset] = origin
                        col_index += span
                        continue
                    children = [block(child, body_index, False) for child in cell if child.tag in {W + "p", W + "tbl"}]
                    cell_view = {"id": _element_id(cell, digest), "blocks": children, "colspan": span, "rowspan": 1, "row_index": row_index, "col_index": col_index}
                    cells.append(cell_view)
                    if merge is not None:
                        for offset in range(span):
                            next_vertical[col_index + offset] = cell_view
                    col_index += span
                rows.append({"id": _element_id(row, digest), "cells": cells})
                vertical = next_vertical
            if section_stack:
                section_stack[-1]["block_ids"].append(identity)
            return dict(common, kind="table", rows=rows, editable=False)
        return None

    blocks = []
    for index, child in enumerate(body):
        if child.tag in {W + "p", W + "tbl"}:
            blocks.append(block(child, index))
        elif child.tag not in {W + name for name in ("sectPr", "bookmarkStart", "bookmarkEnd", "proofErr", "commentRangeStart", "commentRangeEnd")}:
            # Block-level content controls remain read-only but visible.
            for nested in child.iter():
                if nested.tag in {W + "p", W + "tbl"} and not any(parent.tag in {W + "p", W + "tbl"} for parent in nested.iterancestors() if parent is not child):
                    blocks.append(block(nested, index))
            warnings.append("文档含内容控件或其他特殊结构，相关部分请使用版式编辑器修改。")
    archive.close()
    return {"document_id": "doc-" + digest[:24], "sha256": digest, "asset_id": asset_id, "revision_id": revision_id, "format": "docx", "view_mode": "content", "blocks": blocks, "outline": outline, "sections": sections, "warnings": list(dict.fromkeys(warnings))}


def _write_token(node, text):
    parent = node.getparent()
    index = parent.index(node)
    # Preserve an unchanged break (notably an explicit page break) exactly.
    if text == _token_text(node):
        return
    parent.remove(node)
    for part in re.split(r"([\t\n])", text):
        if not part:
            continue
        replacement = etree.Element(W + ("tab" if part == "\t" else "br" if part == "\n" else "t"))
        if part not in {"\t", "\n"}:
            replacement.text = part
            replacement.set(XML_SPACE, "preserve")
        parent.insert(index, replacement)
        index += 1


def _replace_text(paragraph, new_text):
    tokens = list(_text_tokens(paragraph))
    if not tokens:
        run = etree.SubElement(paragraph, W + "r")
        token = etree.SubElement(run, W + "t")
        _write_token(token, new_text)
        return
    values = [_token_text(node) for node in tokens]
    offsets = []
    position = 0
    for value in values:
        offsets.append((position, position + len(value)))
        position += len(value)
    previous = "".join(values)
    for opcode, start, end, new_start, new_end in reversed(SequenceMatcher(None, previous, new_text, autojunk=True).get_opcodes()):
        if opcode == "equal":
            continue
        anchor = next((i for i, (left, right) in enumerate(offsets) if left <= start < right), len(tokens) - 1)
        insertion_offset = start - offsets[anchor][0]
        for i, (left, right) in enumerate(offsets):
            if right <= start or left >= end:
                continue
            local_start = max(start, left) - left
            local_end = min(end, right) - left
            values[i] = values[i][:local_start] + values[i][local_end:]
        values[anchor] = values[anchor][:insertion_offset] + new_text[new_start:new_end] + values[anchor][insertion_offset:]
    for node, value in zip(tokens, values):
        _write_token(node, value)


def apply_edits(source_path, dest_path, operations) -> dict[str, Any]:
    """Apply a validated batch to a new DOCX; invalid batches create no file."""
    source, destination = Path(source_path), Path(dest_path)
    if source.resolve() == destination.resolve():
        raise ValueError("修订件必须另存，不能覆盖原始文件。")
    if destination.suffix.lower() != ".docx":
        raise ValueError("修订文件必须使用 DOCX 格式。")
    if not isinstance(operations, list) or not operations or len(operations) > MAX_OPERATIONS:
        raise ValueError("请提交 1 至 1000 个正文修改操作。")
    source_payload, digest, archive, tree, body = _load(source)
    paragraphs = {_element_id(node, digest): node for node in body.iter(W + "p")}
    seen, validated = {}, []
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("正文修改操作格式不正确。")  # noqa: TRY004 - public API reports all invalid edit payloads as ValueError.
        action, identity = operation.get("op"), operation.get("element_id")
        if action not in {"replace_text", "insert_paragraph", "delete_paragraph"}:
            raise ValueError("不支持的正文修改操作。")
        if not isinstance(identity, str) or identity not in paragraphs:
            raise ValueError("段落不存在或文档版本已变化，请刷新后重试。")
        actions = seen.setdefault(identity, set())
        if action in actions or "delete_paragraph" in actions or (action == "delete_paragraph" and actions):
            raise ValueError("同一段落包含重复或互相冲突的修改操作。")
        actions.add(action)
        paragraph = paragraphs[identity]
        reason = _edit_reason(paragraph)
        if reason:
            raise ValueError(reason)
        if action == "delete_paragraph":
            reason = _delete_reason(paragraph)
            if reason:
                raise ValueError(reason)
        else:
            text = operation.get("text")
            if not isinstance(text, str) or len(text) > MAX_PARAGRAPH_CHARS:
                raise ValueError("段落文字不能为空类型或超过 100000 字符。")
            if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", text):
                raise ValueError("段落文字包含 Word 无法保存的控制字符。")
            if action == "insert_paragraph" and operation.get("position", "after") not in {"before", "after"}:
                raise ValueError("新增段落位置必须为 before 或 after。")
        validated.append((operation, paragraph))

    # Validate cell survival against the complete batch, not one deletion at a time.
    deletions = {id(node) for op, node in validated if op["op"] == "delete_paragraph"}
    for cell in body.iter(W + "tc"):
        direct = cell.findall(W + "p")
        if direct and all(id(node) in deletions for node in direct):
            raise ValueError("表格单元格至少需要保留一个段落，可清空文字。")
        remaining = [node for node in cell if id(node) not in deletions]
        if remaining and remaining[-1].tag == W + "tbl":
            raise ValueError("嵌套表格之后必须保留一个段落，可清空文字。")

    changes = []
    styles = _styles(archive)
    for operation, paragraph in validated:
        action = operation["op"]
        before = _paragraph_text(paragraph)
        after = operation.get("text", "").replace("\r\n", "\n").replace("\r", "\n")
        if action == "replace_text":
            if before == after:
                continue
            _replace_text(paragraph, after)
        elif action == "insert_paragraph":
            new = etree.Element(W + "p")
            properties = paragraph.find(W + "pPr")
            if properties is not None:
                properties = deepcopy(properties)
                _, level = _paragraph_style(paragraph, styles)
                removed = {W + "numPr", W + "sectPr", W + "outlineLvl"}
                if level:
                    removed.add(W + "pStyle")
                for child in list(properties):
                    if child.tag in removed:
                        properties.remove(child)
                new.append(properties)
            _replace_text(new, after)
            if operation.get("position", "after") == "before":
                paragraph.addprevious(new)
            else:
                paragraph.addnext(new)
            before = ""
        else:
            paragraph.getparent().remove(paragraph)
        changes.append({"op": action, "element_id": operation["element_id"], "before": before, "after": after, "position": operation.get("position") if action == "insert_paragraph" else None})

    xml_payload = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, standalone=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".review-edit-", suffix=".docx", dir=destination.parent)
    os.close(handle)
    try:
        if not changes:
            Path(temporary).write_bytes(source_payload)
        else:
            with ZipFile(temporary, "w") as output:
                output.comment = archive.comment
                for member in archive.infolist():
                    output.writestr(member, xml_payload if member.filename == DOCUMENT_PART else archive.read(member.filename))
        archive.close()
        os.replace(temporary, destination)
    finally:
        archive.close()
        if os.path.exists(temporary):
            os.remove(temporary)
    return {"sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "changed_element_ids": list(dict.fromkeys(item["element_id"] for item in changes)), "changes": changes}
