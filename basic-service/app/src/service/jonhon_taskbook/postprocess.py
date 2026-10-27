# -*- coding: utf-8 -*-
"""
postprocess.py — 输出文档后处理（通用，适用于任意 docx）
扫描步骤：
  1. 清红色字体 → 黑色
  2. 清高亮/底纹
  3. 保留受控模板的正文、表格及待填位置
  4. 清理生成指标表的编写说明
  5. 统一红色【人工填写】提示（章节选择由受控业务规则执行）
  6. 清横版分节符
  7. 图片段落强制居中
  8. 表格列宽超页宽时等比缩放
"""
from __future__ import annotations
import os, posixpath, re, tempfile, time, zipfile
from pathlib import Path
from lxml import etree
import yaml
from jonhon_taskbook.figure_pairing import pair_figure_captions
from jonhon_taskbook.renderer.paragraph_style_engine import has_image, normalize_image_paragraph
from jonhon_taskbook.renderer.table_style_engine import (
    DEFAULT_FONT,
    apply_table_style,
    available_page_width,
    normalize_table_borders,
    normalize_table_header,
    normalize_table_typography,
    normalize_table_width,
)

W  = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{W}}}"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
O_NS = "urn:schemas-microsoft-com:office:office"
V_NS = "urn:schemas-microsoft-com:vml"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"

_RED_VALS = {"FF0000","C00000","E00000","D00000","F00000","B00000","A00000"}
_FIGURE_CAPTION_RE = re.compile(r'^(\s*图\s*)(\d+)(?=\D|$)')
_FIGURE_REFERENCE_RE = re.compile(r'图\s*(\d+)')
_STANDALONE_PLACEHOLDER_RE = re.compile(r'^(?:[.．·•]{3,}|…{2,})$')
_BODY_CAPTION_RE = re.compile(r'^\s*(?:图|表)\s*\d+(?=\D|$)', re.I)
_ITALIC_ANNOTATION_MARKER = "【人工填写】"
_ITALIC_ANNOTATION_ALIASES = (_ITALIC_ANNOTATION_MARKER, "【请人工标注】", "【人工标注】")
_ANNOTATION_EXEMPT_HEADING_MARKERS = (
    "相似失效问题规避",
)
_ANNOTATION_REQUIRED_HEADING_MARKERS = (
    "潜在失效模式", "进度要求", "研制经费预算",
    "产品运行场景识别", "产品需求分解", "QFD质量功能分解",
)
_MANUAL_GUIDANCE_RE = re.compile(r"由设计(?:员|人员)?(?:人工)?填写|需设计员编辑|人工填写|请设计人员填写")
_BODY_FONT = "宋体"
_BODY_SIZE_HALF_POINTS = "21"  # 五号 = 10.5 pt = 21 half-points

def _para_text(p) -> str:
    return "".join(t.text or "" for t in p.findall(f".//{_W}t"))


def _normalize_header_identity_xml(data: bytes) -> tuple[bytes, int]:
    """Keep the document number and version in one stable top-right position.

    The controlled template contains four header variants (first/default/even
    headers across sections).  Some variants carry old direct formatting such
    as ``both`` justification or a large first-line indent.  Word expands or
    wraps the short ``编号：`` / ``版本：A`` labels differently on each page as a
    result.  Normalize only those identity paragraphs; all other header
    content, section settings, and the displayed values remain untouched.
    """
    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError:
        return data, 0

    normalized = 0
    for paragraph in root.findall(f".//{_W}p"):
        compact = re.sub(r"\s+", "", _para_text(paragraph))
        if not (
            compact.startswith("编号：")
            or compact.startswith("版本：")
        ):
            continue

        p_pr = paragraph.find(f"{_W}pPr")
        if p_pr is None:
            p_pr = etree.Element(f"{_W}pPr")
            paragraph.insert(0, p_pr)

        # Direct indents and distributed justification are the cause of the
        # observed split "版 / 本：A" layout.  Leave the header style and its
        # font/line-height intact, then apply a deterministic right alignment.
        for tag in (f"{_W}ind", f"{_W}tabs", f"{_W}jc", f"{_W}wordWrap"):
            for node in list(p_pr.findall(tag)):
                p_pr.remove(node)
        alignment = etree.Element(f"{_W}jc")
        alignment.set(f"{_W}val", "right")
        p_pr.append(alignment)
        normalized += 1

    if not normalized:
        return data, 0
    return (
        etree.tostring(
            root,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        ),
        normalized,
    )


def _scrub_privacy_xml_part(name: str, data: bytes) -> tuple[bytes, dict[str, int]]:
    """Remove author/device fingerprints without changing document content.

    This is package-level cleanup: it is independent of product, template,
    chapter number and source document.  Word's RSID values and core-property
    author fields are editing fingerprints, not auditable technical evidence.
    """
    stats = {
        "metadata_fields_cleared": 0,
        "rsid_attributes_removed": 0,
        "comment_authors_cleared": 0,
    }
    if not name.endswith(".xml"):
        return data, stats
    if name != "docProps/core.xml" and not name.startswith("word/"):
        return data, stats
    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError:
        return data, stats

    if name == "docProps/core.xml":
        for tag in (
            f"{{{DC_NS}}}creator",
            f"{{{CP_NS}}}lastModifiedBy",
            f"{{{CP_NS}}}lastPrinted",
        ):
            for node in root.findall(f".//{tag}"):
                # Count the controlled field that was scrubbed, not only a
                # non-empty value.  python-docx can reuse an already-empty
                # default core-property node across documents in the same
                # process; the privacy contract is that the field is present
                # and forced empty, which must yield deterministic audit
                # statistics independent of test/run order.
                stats["metadata_fields_cleared"] += 1
                node.text = ""

    if name.startswith("word/"):
        for node in root.iter():
            if not isinstance(node.tag, str):
                continue
            for attr_name in list(node.attrib):
                local_name = etree.QName(attr_name).localname.lower()
                if local_name.startswith("rsid"):
                    del node.attrib[attr_name]
                    stats["rsid_attributes_removed"] += 1
            if etree.QName(node).localname == "comment":
                for attr_name in list(node.attrib):
                    local_name = etree.QName(attr_name).localname
                    if local_name in {"author", "initials"} and node.attrib.get(attr_name):
                        node.attrib[attr_name] = ""
                        stats["comment_authors_cleared"] += 1
        for rsids in list(root.findall(f".//{_W}rsids")):
            parent = rsids.getparent()
            if parent is not None:
                parent.remove(rsids)
                stats["rsid_attributes_removed"] += 1

    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    ), stats


def _fix_orphan_ole_objects(root, relationship_ids: set[str]) -> int:
    """Keep the visible preview while removing a dangling embedded object.

    A copied CAD/OLE block can contain a VML preview image plus an
    ``o:OLEObject`` relationship.  If the relationship was not copied into the
    output package, WPS may still display the preview but Microsoft Word rejects
    the DOCX as damaged.  This integrity repair is independent of product type,
    chapter number and image number.
    """
    fixed = 0
    for ole in list(root.findall(f".//{{{O_NS}}}OLEObject")):
        rid = str(ole.get(f"{{{R_NS}}}id") or "")
        if rid and rid in relationship_ids:
            continue
        object_node = ole.getparent()
        if object_node is None:
            continue
        object_node.remove(ole)
        previews = object_node.findall(f".//{{{V_NS}}}shape")
        has_preview = any(
            shape.find(f".//{{{V_NS}}}imagedata") is not None
            for shape in previews
        )
        if has_preview:
            for shape in previews:
                shape.attrib.pop(f"{{{O_NS}}}ole", None)
        else:
            parent = object_node.getparent()
            if parent is not None:
                parent.remove(object_node)
        fixed += 1
    return fixed


def _is_indicator_instruction(text: str) -> bool:
    """Identify template-only guidance immediately above the indicator table.

    These are instructions to the document author, not technical evidence.
    The check is intentionally local to the indicator table and does not
    remove ordinary template guidance elsewhere.
    """
    compact = re.sub(r"\s+", "", text or "")
    if compact.strip("（）()。") == "此条要求将所有技术指标要求和试验方法详细列出":
        return True
    return compact.startswith(
        "\u5728\u4e0b\u8868\u4e2d\u5217\u51fa\u7528\u6237\u660e\u786e\u8981\u6c42\u7684\u6280\u672f\u6307\u6807"
    ) or compact.startswith(
        "\u5bf9\u4e8e\u6309\u7167\u516c\u53f8\u73b0\u6709\u4ea7\u54c1\u89c4\u8303\u8bbe\u8ba1\u5f00\u53d1"
    )


def _is_indicator_table(element) -> bool:
    if element.tag != f"{_W}tbl":
        return False
    table_text = "".join(t.text or "" for t in element.findall(f".//{_W}t"))
    compact = re.sub(r"\s+", "", table_text)
    return (
        "\u7528\u6237\u8981\u6c42\u6307\u6807" in compact
        and "\u62df\u91c7\u7528\u6307\u6807" in compact
    )


def _remove_indicator_instructions(body, stats: dict) -> None:
    """Remove authoring prompts directly before the performance table.

    This runs even when the controlled-template preservation policy is on.
    It does not infer a chapter number and it does not touch source evidence.
    """
    children = list(body)
    for index, child in enumerate(children):
        if not _is_indicator_table(child) or not _indicator_table_has_values(child):
            continue
        cursor = index - 1
        while cursor >= 0:
            previous = children[cursor]
            if previous.tag != f"{_W}p":
                break
            text = _para_text(previous).strip()
            if not text:
                cursor -= 1
                continue
            if _heading_depth(previous) > 0:
                from jonhon_taskbook.template_scanner import semantic_title
                if semantic_title(text) == "技术指标":
                    cursor -= 1
                    continue
                break
            if not _is_indicator_instruction(text):
                break
            parent = previous.getparent()
            if parent is not None:
                parent.remove(previous)
                stats["indicator_instruction_deleted"] += 1
            cursor -= 1


def _indicator_table_has_values(table) -> bool:
    """Only a populated data cell makes the authoring prompt obsolete."""
    for row in table.findall(f"{_W}tr"):
        cells = row.findall(f"{_W}tc")
        if len(cells) < 3 or (
            _para_text(cells[0]).strip() in {"项目", "项目名称", "指标", "指标名称"}
            and "用户要求" in _para_text(row)
        ):
            continue
        for cell in cells[1:-1]:
            value = _para_text(cell).strip()
            if value and value not in {"\\", "/", "-", "—", "【人工填写】"} and not re.fullmatch(r"[Xx_＿….\s]+", value):
                return True
    return False


def _normalize_indicator_table_formatting(body, stats: dict) -> None:
    """Normalize the generated indicator table as one visual component.

    The indicator table is a controlled structured rendering surface, so
    source/template review styling (blue, italic, mixed fonts and sizes) must
    not leak into the deliverable. No business text is changed.
    """
    tables = [tbl for tbl in body.iter(f"{_W}tbl") if _is_indicator_table(tbl)]
    if not tables:
        return
    normalized_runs = 0
    for table in tables:
        normalize_table_typography(table)
        runs = [
            run for run in table.findall(f".//{_W}r")
            if run.findall(f".//{_W}t")
        ]
        for run in runs:
            rpr = run.find(f"{_W}rPr")
            if rpr is None:
                rpr = etree.Element(f"{_W}rPr")
                run.insert(0, rpr)
            for tag in ("i", "iCs"):
                for italic in list(rpr.findall(f"{_W}{tag}")):
                    rpr.remove(italic)
            color = rpr.find(f"{_W}color")
            if color is None:
                color = etree.SubElement(rpr, f"{_W}color")
            color.set(f"{_W}val", "000000")
            normalized_runs += 1
    if normalized_runs:
        stats["indicator_font_normalized"] = normalized_runs


def _is_failure_table(element) -> bool:
    """Recognize the two controlled failure-mode tables by their headers.

    The table position and chapter number are deliberately ignored.  Customer
    templates may insert, remove, or renumber chapters while retaining the
    semantic field names required by the 7-22 rule pack.
    """
    if element.tag != f"{_W}tbl":
        return False
    compact = re.sub(
        r"\s+",
        "",
        "".join(t.text or "" for t in element.findall(f".//{_W}t")),
    )
    return (
        "失效模式" in compact
        and (
            "数据所属产品的产品名称" in compact
            or "可能发生的失效模式" in compact
        )
    )


def _normalize_controlled_table_formatting(root, stats: dict) -> None:
    """Give chapter data tables one width and header treatment at delivery.

    Imported tables retain their cell content and proportions;
    indicator/failure tables also receive their controlled row flow.
    Front matter, nested tables and picture-only layouts are not data tables.
    """
    body = root.find(f".//{_W}body")
    if body is None:
        return
    normalized = 0
    layouts = 0
    in_chapter = False
    for table in _iter_body_blocks(body):
        if table.tag == f"{_W}p":
            if _heading_depth(table) > 0:
                in_chapter = True
            continue
        controlled = _is_indicator_table(table) or _is_failure_table(table)
        rows = table.findall(f"{_W}tr")
        if not controlled and not (
            in_chapter and len(rows) > 1
            and len(table.findall(f"./{_W}tblGrid/{_W}gridCol")) > 1
            and _para_text(rows[0]).strip()
        ):
            continue
        page_width = available_page_width(table)
        if page_width and not controlled:
            normalize_table_width(table, page_width, inline=True)
        layouts += 1
        if not controlled:
            normalize_table_borders(table)
            normalize_table_header(table)
            continue
        runs = [
            run
            for run in table.findall(f".//{_W}r")
            if run.findall(f".//{_W}t")
        ]
        table_kind = "indicator" if _is_indicator_table(table) else "failure"
        apply_table_style(table, table_kind)
        if page_width:
            normalize_table_width(table, page_width, inline=True)
        normalized += len(runs)
    if normalized:
        stats["controlled_table_font_normalized"] = normalized
        stats["controlled_table_layout_normalized"] = normalized
    if layouts:
        stats["body_table_layout_normalized"] = layouts


def _normalize_all_table_typography(root) -> int:
    """Apply the universal font rule independently of table layout/routing."""
    tables = root.findall(f".//{_W}tbl")
    for table in tables:
        # The common renderer already includes descendants, including nested
        # tables. Process each table tree once without changing its geometry.
        if not any(parent.tag == f"{_W}tbl" for parent in table.iterancestors()):
            normalize_table_typography(table)
    return len(tables)


def _ensure_table_font_definition(data: bytes) -> bytes:
    """Declare the installed FangSong family without changing other fonts."""
    root = etree.fromstring(data)
    font = next(
        (node for node in root.findall(f"{_W}font")
         if node.get(f"{_W}name") == DEFAULT_FONT),
        None,
    )
    if font is None:
        font = etree.SubElement(root, f"{_W}font")
        font.set(f"{_W}name", DEFAULT_FONT)
    alias = font.find(f"{_W}altName")
    if alias is None:
        alias = etree.Element(f"{_W}altName")
        font.insert(0, alias)
    alias.set(f"{_W}val", "FangSong")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _table_dxa_width(table) -> int:
    """Return the table's effective absolute width from its live geometry."""

    tbl_w = table.find(f"./{_W}tblPr/{_W}tblW")
    if tbl_w is not None and tbl_w.get(f"{_W}type") == "dxa":
        try:
            value = int(tbl_w.get(f"{_W}w", "0"))
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    grid = table.find(f"{_W}tblGrid")
    if grid is None:
        return 0
    try:
        return sum(
            int(column.get(f"{_W}w", "0"))
            for column in grid.findall(f"{_W}gridCol")
        )
    except (TypeError, ValueError):
        return 0


def _table_alignment(table) -> str:
    alignment = table.find(f"./{_W}tblPr/{_W}jc")
    return str(alignment.get(f"{_W}val") or "left") if alignment is not None else "left"


def _table_indent(table) -> int:
    indent = table.find(f"./{_W}tblPr/{_W}tblInd")
    if indent is None or indent.get(f"{_W}type", "dxa") != "dxa":
        return 0
    try:
        return int(indent.get(f"{_W}w", "0"))
    except (TypeError, ValueError):
        return 0


def _normalize_budget_table_widths(root, stats: dict) -> None:
    """Align economic-analysis tables with the task-progress table.

    The controlled template stores these neighbouring sections with different
    width mechanisms: the progress table uses an absolute width, while the
    economic-analysis tables mix percentage ``tblW``/``tcW`` values with a
    wider DXA grid.  Word then renders the latter visibly narrower.  Locate the
    sections by heading semantics, never by chapter number, and use the live
    progress table as the presentation reference.
    """

    body = root.find(f".//{_W}body")
    if body is None:
        return

    reference_width = 0
    reference_alignment = "left"
    reference_indent = 0
    active_section = ""
    budget_heading_style = ""
    budget_tables: list = []

    for child in body:
        if child.tag == f"{_W}p":
            text = re.sub(r"\s+", "", _para_text(child))
            style = child.find(f"./{_W}pPr/{_W}pStyle")
            style_id = str(style.get(f"{_W}val") or "") if style is not None else ""
            if "任务进度要求" in text:
                active_section = "progress"
                continue
            if "研制经费预算" in text or "经济性分析" in text:
                active_section = "budget"
                budget_heading_style = style_id
                continue
            if (
                active_section == "budget"
                and budget_heading_style
                and style_id == budget_heading_style
                and text
            ):
                active_section = ""
        elif child.tag == f"{_W}tbl":
            if active_section == "progress" and not reference_width:
                reference_width = _table_dxa_width(child)
                reference_alignment = _table_alignment(child)
                reference_indent = _table_indent(child)
                active_section = ""
            elif active_section == "budget":
                budget_tables.append(child)

    if reference_width <= 0 or not budget_tables:
        return

    normalized = 0
    for table in budget_tables:
        fitted = normalize_table_width(
            table,
            reference_width,
            alignment=reference_alignment,
            indent=reference_indent,
        )
        if fitted:
            normalized += 1
    if normalized:
        stats["budget_tables_width_normalized"] = normalized
        stats["section_table_reference_width_dxa"] = reference_width


def _is_run_italic(r) -> bool:
    """Return True when the run carries an explicit italic attribute that is ON."""
    rpr = r.find(f"{_W}rPr")
    if rpr is None:
        return False
    for tag in ("i", "iCs"):
        node = rpr.find(f"{_W}{tag}")
        if node is not None:
            val = (node.get(f"{_W}val") or "").strip().lower()
            if val not in ("0", "false", "off", "no"):
                return True
    return False


def _run_text(r) -> str:
    return "".join(t.text or "" for t in r.findall(f".//{_W}t"))


def _contains_visible_italic(element, excluded_paragraphs: set | None = None) -> bool:
    excluded_paragraphs = excluded_paragraphs or set()
    for run in element.findall(f".//{_W}r"):
        if not _run_text(run).strip() or not _is_run_italic(run):
            continue
        paragraph = run.getparent()
        while paragraph is not None and paragraph.tag != f"{_W}p":
            paragraph = paragraph.getparent()
        if paragraph not in excluded_paragraphs:
            return True
    return False


def _iter_body_blocks(container):
    """Yield body paragraphs/tables in visual order, including SDT wrappers."""
    for child in container:
        if child.tag in {f"{_W}p", f"{_W}tbl"}:
            yield child
            continue
        if child.tag == f"{_W}sdt":
            content = child.find(f"{_W}sdtContent")
            if content is not None:
                yield from _iter_body_blocks(content)


def _style_italic_annotation_run(marker_run) -> None:
    marker_rpr = marker_run.find(f"{_W}rPr")
    if marker_rpr is None:
        marker_rpr = etree.Element(f"{_W}rPr")
        marker_run.insert(0, marker_rpr)
    color_el = marker_rpr.find(f"{_W}color")
    if color_el is None:
        color_el = etree.SubElement(marker_rpr, f"{_W}color")
    color_el.set(f"{_W}val", "FF0000")
    bold_el = marker_rpr.find(f"{_W}b")
    if bold_el is None:
        bold_el = etree.SubElement(marker_rpr, f"{_W}b")
    bold_el.set(f"{_W}val", "1")


def _append_italic_annotation_to_heading(heading) -> None:
    marker_run = etree.SubElement(heading, f"{_W}r")
    _style_italic_annotation_run(marker_run)
    marker_text = etree.SubElement(marker_run, f"{_W}t")
    marker_text.text = _ITALIC_ANNOTATION_MARKER
    marker_text.set(
        "{http://www.w3.org/XML/1998/namespace}space",
        "preserve",
    )


def _is_inside_table(element) -> bool:
    parent = element.getparent()
    while parent is not None:
        if parent.tag == f"{_W}tbl":
            return True
        parent = parent.getparent()
    return False


def _is_descendant_heading(heading, ancestor, heading_parents: dict) -> bool:
    parent = heading_parents.get(heading)
    while parent is not None:
        if parent is ancestor:
            return True
        parent = heading_parents.get(parent)
    return False


def _collapse_annotation_targets(
    target_headings: list,
    heading_parents: dict,
    heading_depths: dict,
    heading_order: dict,
) -> tuple[list, int]:
    """Collapse multiple pending descendants to their nearest shared heading.

    A chapter is the review unit presented to the designer.  When several of
    its child headings are pending, repeating the marker on every descendant
    adds no information; the deepest common parent receives one marker.  A
    single pending child remains precise, and exempt headings are never made
    annotation targets by this reduction.
    """
    active = set(target_headings)
    candidates = set()
    for target in active:
        parent = heading_parents.get(target)
        while parent is not None:
            candidates.add(parent)
            parent = heading_parents.get(parent)

    before = len(active)
    for candidate in sorted(
        candidates,
        key=lambda heading: heading_depths.get(heading, 0),
        reverse=True,
    ):
        descendants = {
            target
            for target in active
            if _is_descendant_heading(target, candidate, heading_parents)
        }
        if candidate in active:
            active.difference_update(descendants)
            continue
        if len(descendants) < 2 or _annotation_heading_policy(candidate) == "exempt":
            continue
        active.difference_update(descendants)
        active.add(candidate)

    return (
        sorted(active, key=lambda heading: heading_order.get(heading, 0)),
        before - len(active),
    )


def _remove_annotation_aliases_from_run(run) -> int:
    """Remove labels across text nodes while retaining surrounding formatting.

    The input may be a paragraph: Word frequently splits a marker over runs.
    """
    text_nodes = list(run.findall(f".//{_W}t"))
    full_text = "".join(node.text or "" for node in text_nodes)
    if not full_text:
        return 0

    removed_chars = [False] * len(full_text)
    removed_count = 0
    for marker in _ITALIC_ANNOTATION_ALIASES:
        start = 0
        while True:
            start = full_text.find(marker, start)
            if start < 0:
                break
            end = start + len(marker)
            if not any(removed_chars[start:end]):
                removed_chars[start:end] = [True] * len(marker)
                removed_count += 1
            start = end

    if not removed_count:
        return 0

    cursor = 0
    for node in text_nodes:
        original = node.text or ""
        node.text = "".join(
            char
            for offset, char in enumerate(original)
            if not removed_chars[cursor + offset]
        )
        if node.text[:1].isspace() or node.text[-1:].isspace():
            node.set(
                "{http://www.w3.org/XML/1998/namespace}space",
                "preserve",
            )
        cursor += len(original)

    if run.tag == f"{_W}p":
        for child_run in list(run.findall(f".//{_W}r")):
            has_payload = any(child.tag not in {f"{_W}rPr", f"{_W}t"} for child in child_run)
            if not _run_text(child_run) and not has_payload:
                child_run.getparent().remove(child_run)
    elif not _run_text(run):
        non_text_payload = any(
            child.tag not in {f"{_W}rPr", f"{_W}t"}
            for child in run
        )
        parent = run.getparent()
        if not non_text_payload and parent is not None:
            parent.remove(run)
    return removed_count


def _annotation_heading_policy(heading) -> str:
    text = re.sub(r"\s+", "", _para_text(heading))
    if any(marker in text for marker in _ANNOTATION_EXEMPT_HEADING_MARKERS):
        return "exempt"
    if any(
        marker in text for marker in _ANNOTATION_REQUIRED_HEADING_MARKERS
    ):
        return "required"
    return "auto"


def _pending_customer_question_parents(body):
    """Find unanswered template questions stored as subheadings, not body text."""
    from jonhon_taskbook.template_scanner import semantic_title

    blocks = list(body)
    ancestors = {}
    question = re.compile(r"如有(?:请)?注明[^。；;\n]{0,40}(?:没有|如无)[^。；;\n]{0,8}删除")
    pending = set()
    for index, block in enumerate(blocks):
        if block.tag != f"{_W}p":
            continue
        depth = _heading_depth(block)
        if depth <= 0:
            continue
        ancestors = {level: heading for level, heading in ancestors.items() if level < depth}
        parents = list(ancestors.values())
        titles = [semantic_title(_para_text(p).replace(_ITALIC_ANNOTATION_MARKER, "")) for p in parents]
        if titles[-2:] == ["顾客的特殊要求", "其他要求"] and question.search(_para_text(block)):
            answered = False
            for following in blocks[index + 1:]:
                following_depth = _heading_depth(following) if following.tag == f"{_W}p" else 0
                if following_depth and following_depth <= depth:
                    break
                text = _para_text(following).strip()
                if not following_depth and text and not (
                    _MANUAL_GUIDANCE_RE.search(text)
                    or re.fullmatch(r"[Xx_＿….\s]+", text)
                ):
                    answered = True
                    break
            if not answered:
                pending.add(parents[-1])
        ancestors[depth] = block
    return pending


def _mark_italic_runs_with_annotation(body, stats: dict) -> None:
    """每个待填标题子树只在最小公共父标题上标注一次。

    先规范化旧标记，再按标题树归属待填位置。同一父标题下有多个待填
    子标题时，标记提升到其最小公共父标题；表格单元格中的明确待填位
    置保持原位。标题本身的斜体版式不触发标注，重复处理保持幂等。
    """
    if body is None:
        return

    exempt_markers_removed = 0
    original_marker_headings: set = set()
    for paragraph in body.findall(f".//{_W}p"):
        if _heading_depth(paragraph) <= 0:
            continue
        had_marker = any(marker in _para_text(paragraph) for marker in _ITALIC_ANNOTATION_ALIASES)
        if not had_marker:
            continue
        removed = _remove_annotation_aliases_from_run(paragraph)
        if _annotation_heading_policy(paragraph) == "exempt":
            exempt_markers_removed += removed
        else:
            original_marker_headings.add(paragraph)

    relocated = 0
    relocated_paragraphs: set = set()
    explicit_table_marker_paragraphs: set = set()
    for paragraph in body.findall(f".//{_W}p"):
        if _heading_depth(paragraph) > 0:
            continue
        paragraph_text = _para_text(paragraph)
        has_explicit_marker = any(
            marker in paragraph_text for marker in _ITALIC_ANNOTATION_ALIASES
        )
        if has_explicit_marker and _is_inside_table(paragraph):
            # 指标比较/封面表格字段已有明确的人工位置时就地保留。不能把
            # 单元格标记移到章标题，否则设计员与指标审计都失去具体位置。
            _remove_annotation_aliases_from_run(paragraph)
            _append_italic_annotation_to_heading(paragraph)
            explicit_table_marker_paragraphs.add(paragraph)
            continue
        removed = _remove_annotation_aliases_from_run(paragraph)
        if removed:
            relocated += removed
            relocated_paragraphs.add(paragraph)

    current_heading = None
    current_heading_policy = "auto"
    target_headings = []
    target_elements: set = set()
    heading_parents = {}
    heading_depths = {}
    heading_order = {}
    heading_stack = {}
    italic_without_heading = 0

    def queue_heading(heading) -> None:
        if heading not in target_elements:
            target_elements.add(heading)
            target_headings.append(heading)

    for heading in _pending_customer_question_parents(body):
        queue_heading(heading)

    for order, block in enumerate(_iter_body_blocks(body)):
        if block.tag == f"{_W}p" and _heading_depth(block) > 0:
            if _para_text(block).strip():
                depth = _heading_depth(block)
                parent_depths = [level for level in heading_stack if level < depth]
                heading_parents[block] = (
                    heading_stack[max(parent_depths)] if parent_depths else None
                )
                heading_depths[block] = depth
                heading_order[block] = order
                heading_stack = {
                    level: heading
                    for level, heading in heading_stack.items()
                    if level < depth
                }
                heading_stack[depth] = block
                current_heading = block
                current_heading_policy = _annotation_heading_policy(block)
                if current_heading_policy == "required" or block in original_marker_headings:
                    queue_heading(block)
            continue
        if block.tag == f"{_W}p":
            had_relocated_marker = block in relocated_paragraphs
        else:
            had_relocated_marker = any(
                paragraph in relocated_paragraphs
                for paragraph in block.findall(f".//{_W}p")
            )
        block_text = _para_text(block)
        guidance_text = block_text
        for marker in _ITALIC_ANNOTATION_ALIASES:
            guidance_text = guidance_text.replace(marker, "")
        if not (
            had_relocated_marker
            or _contains_visible_italic(block, explicit_table_marker_paragraphs)
            or _MANUAL_GUIDANCE_RE.search(guidance_text)
            or _STANDALONE_PLACEHOLDER_RE.fullmatch(re.sub(r"\s+", "", guidance_text))
        ):
            continue
        if current_heading is None:
            if had_relocated_marker:
                # 封面等无章节位置也必须保留可见人工提示。
                if block.tag == f"{_W}p":
                    _append_italic_annotation_to_heading(block)
                else:
                    for paragraph in block.findall(f".//{_W}p"):
                        if paragraph in relocated_paragraphs:
                            _append_italic_annotation_to_heading(paragraph)
            italic_without_heading += 1
            continue
        if current_heading_policy == "exempt":
            continue
        queue_heading(current_heading)

    target_headings, collapsed = _collapse_annotation_targets(
        target_headings,
        heading_parents,
        heading_depths,
        heading_order,
    )

    added = 0
    for heading in target_headings:
        _append_italic_annotation_to_heading(heading)
        if heading not in original_marker_headings:
            added += 1

    stats["italic_annotation_chapters"] = len(target_headings)
    if added:
        stats["italic_annotations_added"] = added
    if relocated:
        stats["italic_annotations_relocated"] = relocated
    if exempt_markers_removed:
        stats["annotation_exempt_markers_removed"] = exempt_markers_removed
    if italic_without_heading:
        stats["italic_without_heading"] = italic_without_heading
    if collapsed:
        stats["italic_annotations_collapsed"] = collapsed


def _set_body_run_typography(run) -> None:
    rpr = run.find(f"{_W}rPr")
    if rpr is None:
        rpr = etree.Element(f"{_W}rPr")
        run.insert(0, rpr)

    fonts = rpr.find(f"{_W}rFonts")
    if fonts is None:
        fonts = etree.Element(f"{_W}rFonts")
        rpr.insert(0, fonts)
    for key in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme", "csTheme"):
        fonts.attrib.pop(f"{_W}{key}", None)
    for key in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(f"{_W}{key}", _BODY_FONT)
    fonts.set(f"{_W}hint", "eastAsia")

    size = rpr.find(f"{_W}sz")
    if size is None:
        size = etree.SubElement(rpr, f"{_W}sz")
    size.set(f"{_W}val", _BODY_SIZE_HALF_POINTS)
    size_cs = rpr.find(f"{_W}szCs")
    if size_cs is None:
        size_cs = etree.SubElement(rpr, f"{_W}szCs")
    size_cs.set(f"{_W}val", _BODY_SIZE_HALF_POINTS)


def _normalize_body_text_formatting(body, stats: dict) -> None:
    """Normalize chapter prose to 宋体五号 without changing other roles.

    Cover/front matter before the first heading, heading runs, figure/table
    captions and all table-cell text retain their template-controlled sizes.
    Only visible runs in direct chapter prose paragraphs are normalized.
    """
    if body is None:
        return
    seen_heading = False
    paragraph_count = 0
    run_count = 0
    for block in _iter_body_blocks(body):
        if block.tag != f"{_W}p":
            continue
        if _heading_depth(block) > 0:
            seen_heading = True
            continue
        if not seen_heading:
            continue
        text = _para_text(block).strip()
        if not text or _BODY_CAPTION_RE.match(text):
            continue
        changed = False
        for run in block.findall(f".//{_W}r"):
            if not _run_text(run).strip():
                continue
            _set_body_run_typography(run)
            changed = True
            run_count += 1
        if changed:
            paragraph_count += 1
    if paragraph_count:
        stats["body_paragraphs_normalized"] = paragraph_count
        stats["body_runs_normalized"] = run_count


def _keep_figure_captions_with_images(body, stats: dict) -> None:
    """Join adjacent image/caption groups without joining unrelated figures."""
    blocks = list(_iter_body_blocks(body))
    texts = [_para_text(block).strip() for block in blocks]
    images = {index for index, block in enumerate(blocks)
              if block.tag == f"{_W}p" and has_image(block)}
    pairs = pair_figure_captions(
        texts, images,
        lambda text: text if _FIGURE_CAPTION_RE.match(text) else "",
    )
    linked = set()
    for image_index, (_, caption_index, _) in pairs.items():
        if image_index == caption_index:
            continue
        start, end = sorted((image_index, caption_index))
        for index in range(start, end):
            paragraph = blocks[index]
            if paragraph.tag != f"{_W}p":
                continue
            properties = paragraph.find(f"{_W}pPr")
            if properties is None:
                properties = etree.Element(f"{_W}pPr")
                paragraph.insert(0, properties)
            keep = properties.find(f"{_W}keepNext")
            if keep is None:
                keep = etree.SubElement(properties, f"{_W}keepNext")
            keep.set(f"{_W}val", "1")
            linked.add(index)
    if linked:
        stats["figure_paragraphs_kept_together"] = len(linked)


def _replace_paragraph_text(p, new_text: str) -> None:
    """Replace paragraph text while retaining its existing run properties.

    Figure numbers are document-structure metadata rather than technical body
    content.  Replacing only the text-node payloads lets the surrounding
    caption/reference formatting survive the renumbering pass.
    """
    text_nodes = p.findall(f".//{_W}t")
    if not text_nodes:
        return
    original_lengths = [len(node.text or "") for node in text_nodes]
    cursor = 0
    for index, (node, length) in enumerate(zip(text_nodes, original_lengths)):
        if index == len(text_nodes) - 1:
            node.text = new_text[cursor:]
        else:
            node.text = new_text[cursor:cursor + length]
            cursor += length


def _renumber_figure_captions(root, stats: dict) -> None:
    """Renumber moved source figures by their final output order.

    Semantic routing can legitimately move an exact source block from one
    source chapter to another template slot.  Keeping its old source figure
    number would then produce visible sequences such as 3, 1, 5, 2, 4.  This
    pass changes only the structural ``图N`` labels and unambiguous references;
    paragraph/table/image body content remains untouched.
    """
    paragraphs = root.findall(f".//{_W}p")
    captions: list[tuple[object, int]] = []
    for paragraph in paragraphs:
        match = _FIGURE_CAPTION_RE.match(_para_text(paragraph))
        if match:
            captions.append((paragraph, int(match.group(2))))

    if not captions:
        return

    old_counts: dict[int, int] = {}
    for _, old_number in captions:
        old_counts[old_number] = old_counts.get(old_number, 0) + 1

    # Only unique old labels can be updated safely in ordinary cross-references.
    reference_map = {
        old_number: new_number
        for new_number, (_, old_number) in enumerate(captions, start=1)
        if old_counts[old_number] == 1
    }

    caption_targets = {
        id(paragraph): new_number
        for new_number, (paragraph, _) in enumerate(captions, start=1)
    }
    for paragraph in paragraphs:
        original = _para_text(paragraph)
        caption_number = caption_targets.get(id(paragraph))
        if caption_number is not None:
            updated = _FIGURE_CAPTION_RE.sub(
                lambda match: f"{match.group(1)}{caption_number}",
                original,
                count=1,
            )
            if updated != original:
                _replace_paragraph_text(paragraph, updated)
                stats["figure_captions_renumbered"] += 1
            continue

        replacements = 0

        def _replace_reference(match):
            nonlocal replacements
            old_number = int(match.group(1))
            new_number = reference_map.get(old_number)
            if new_number is None or new_number == old_number:
                return match.group(0)
            replacements += 1
            prefix = match.group(0)[: match.group(0).find(match.group(1))]
            return f"{prefix}{new_number}"

        updated = _FIGURE_REFERENCE_RE.sub(_replace_reference, original)
        if replacements:
            _replace_paragraph_text(paragraph, updated)
            stats["figure_references_renumbered"] += replacements


def _heading_depth(p_el) -> int:
    ppr = p_el.find(f"{_W}pPr")
    if ppr is None:
        return 0
    ps = ppr.find(f"{_W}pStyle")
    if ps is None:
        return 0
    sv = ps.get(f"{_W}val", "")
    m = re.match(r'^(\d)$|^[Hh]eading\s*(\d)', sv)
    if m:
        return int(m.group(1) or m.group(2))
    return 0


def _domain_policy() -> dict:
    path = Path(__file__).resolve().parent.parent / "config" / "standard_applicability.yaml"
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def _remove_inapplicable_domain_paragraphs(
    body,
    selected_product_domain: str,
    stats: dict,
) -> None:
    """删除与受控领域冲突的模板分支说明，不受模板正文保留策略影响。"""
    policy = _domain_policy()
    aliases = policy.get("domain_aliases") or {}
    normalized = str(selected_product_domain or "").strip()
    normalized = str(aliases.get(normalized, normalized)).strip().lower()
    markers = policy.get("marker_allowed_domains") or {}
    if not normalized:
        return
    for paragraph in list(body.findall(f".//{_W}p")):
        text = _para_text(paragraph).strip()
        for marker, allowed_domains in markers.items():
            allowed = {
                str(value).strip().lower() for value in (allowed_domains or [])
            }
            if str(marker) in text and normalized not in allowed:
                parent = paragraph.getparent()
                if parent is not None:
                    parent.remove(paragraph)
                    stats["domain_artifact_deleted"] += 1
                break


def clean_doc_xml(
    doc_xml: bytes,
    preserve_template_guidance: bool = False,
    relationship_ids: set[str] | None = None,
    selected_product_domain: str = "",
) -> tuple[bytes, dict]:
    root  = etree.fromstring(doc_xml)
    stats = {"red_cleared": 0, "hl_cleared": 0, "date_cleared": 0,
             "para_deleted": 0, "section_deleted": 0,
             "indicator_instruction_deleted": 0,
             "figure_captions_renumbered": 0,
             "figure_references_renumbered": 0,
             "phase_placeholder_cleared": 0,
             "standalone_placeholder_deleted": 0,
             "domain_artifact_deleted": 0}
    stats["orphan_ole_repaired"] = _fix_orphan_ole_objects(
        root,
        relationship_ids or set(),
    )

    # 开发逻辑 B56 的保留规则同时适用于正式件和复核件，不再按旧开关
    # 删除可能属于真实输入或模板的正文。保留参数仅为旧调用方兼容。
    stats["template_guidance_preserved"] = True

    body = root.find(f".//{_W}body")
    if body is None:
        body = root

    # Indicator-table authoring prompts are never deliverable content.  This
    # targeted cleanup is safe even when other unused template guidance is
    # intentionally preserved.
    _remove_indicator_instructions(body, stats)
    _normalize_indicator_table_formatting(body, stats)
    _renumber_figure_captions(root, stats)
    _remove_inapplicable_domain_paragraphs(
        body,
        selected_product_domain,
        stats,
    )

    # ── 步骤1：全文 w:r 清格式 ──────────────────────────────────────────────
    for r in root.findall(f".//{_W}r"):
        rpr = r.find(f"{_W}rPr")
        if rpr is None:
            continue
        for c_el in rpr.findall(f"{_W}color"):
            val = (c_el.get(f"{_W}val") or "").upper()
            if val in _RED_VALS:
                c_el.set(f"{_W}val", "000000")
                stats["red_cleared"] += 1
        for hl in list(rpr.findall(f"{_W}highlight")):
            rpr.remove(hl)
            stats["hl_cleared"] += 1
        for shd in list(rpr.findall(f"{_W}shd")):
            rpr.remove(shd)
    # ── 步骤1B：清段落级 rPr ────────────────────────────────────────────────
    for ppr in root.findall(f".//{_W}pPr"):
        rpr = ppr.find(f"{_W}rPr")
        if rpr is None:
            continue
        for c_el in rpr.findall(f"{_W}color"):
            val = (c_el.get(f"{_W}val") or "").upper()
            if val in _RED_VALS:
                c_el.set(f"{_W}val", "000000")
                stats["red_cleared"] += 1
        for hl in list(rpr.findall(f"{_W}highlight")):
            rpr.remove(hl)
            stats["hl_cleared"] += 1
        for shd in list(rpr.findall(f"{_W}shd")):
            rpr.remove(shd)

    # B57：人工填写位置使用统一红色加粗标记，不能以斜体作为唯一信号。
    _mark_italic_runs_with_annotation(body, stats)

    # 接口尺寸下的安装方式、安装尺寸、外形尺寸、端接形式以及互换性是模板
    # 中真实存在的子章节。必须保留 Heading/outlineLvl 和模板自己的 numPr，
    # 否则后续语义门禁无法按无编号标题树定位，Word 也无法自动重排章节号。
    # 这里故意不写任何显示编号；编号始终由客户模板样式负责。

    # ── 步骤4：清横版分节符 ────────────────────────────────────────────────
    if body is not None:
        removed_sects = 0
        for sect in root.findall(f".//{_W}sectPr"):
            pgSz = next((c for c in sect if c.tag.endswith("}pgSz")), None)
            if pgSz is None:
                continue
            orient = pgSz.get(f"{_W}orient") or pgSz.get("orient") or ""
            width = int(pgSz.get(f"{_W}w") or pgSz.get("w") or 0)
            height = int(pgSz.get(f"{_W}h") or pgSz.get("h") or 0)
            if orient != "landscape" and not (width and height and width > height):
                continue
            for attr in list(pgSz.attrib):
                if attr.endswith("}orient") or attr == "orient":
                    del pgSz.attrib[attr]
            pgSz.set(f"{_W}w", "11906")
            pgSz.set(f"{_W}h", "16838")
            removed_sects += 1
        if removed_sects:
            stats["landscape_cleared"] = removed_sects

    # ── 步骤5：图片段落强制居中 ────────────────────────────────────────────
    img_centered = 0
    for p in root.findall(f".//{_W}p"):
        if not normalize_image_paragraph(p):
            continue
        pPr = p.find(f"{_W}pPr")
        if pPr is None:
            pPr = etree.Element(f"{_W}pPr")
            p.insert(0, pPr)
        jc = pPr.find(f"{_W}jc")
        if jc is None:
            jc = etree.SubElement(pPr, f"{_W}jc")
        jc.set(f"{_W}val", "center")
        img_centered += 1
    if img_centered:
        stats["img_centered"] = img_centered

    # ── 步骤6：超宽表格按所在节的可用宽度等比缩放 ──────────────────────
    rescaled = 0
    for tbl in root.findall(f".//{_W}tbl"):
        grid = tbl.find(f"{_W}tblGrid")
        if grid is None:
            continue
        cols = grid.findall(f"{_W}gridCol")
        if not cols:
            continue
        total_w = sum(int(c.get(f"{_W}w") or 0) for c in cols)
        page_width = available_page_width(tbl)
        if not page_width or total_w <= page_width or total_w == 0:
            continue
        normalize_table_width(
            tbl, page_width,
            alignment=_table_alignment(tbl), indent=_table_indent(tbl),
        )
        rescaled += 1
    if rescaled:
        stats["table_rescaled"] = rescaled

    # The adjacent progress and economic-analysis sections must share one
    # visible table width.  Run after generic overflow scaling so all three
    # width layers (tblW/tblGrid/tcW) finish in the same DXA coordinate system.
    _normalize_budget_table_widths(root, stats)

    # Run after width scaling and all paragraph cleanup so a template table
    # cannot reintroduce mixed fonts in the final deliverable.
    _normalize_controlled_table_formatting(root, stats)
    stats["table_typography_normalized"] = _normalize_all_table_typography(root)

    # Source paragraphs can carry direct 小四 formatting into the template.
    # Final chapter prose is controlled as 宋体五号 while headings, captions,
    # cover/front matter and table-specific typography remain untouched.
    _normalize_body_text_formatting(body, stats)
    _keep_figure_captions_with_images(body, stats)

    return (
        etree.tostring(root, xml_declaration=True,
                       encoding="UTF-8", standalone=True),
        stats
    )


def postprocess(
    doc_path: str,
    preserve_template_guidance: bool = False,
    selected_product_domain: str = "",
) -> dict:
    """就地处理 docx，返回统计信息。"""
    doc_path = Path(doc_path)
    tmp_file = tempfile.NamedTemporaryFile(
        prefix=f"{doc_path.stem}.",
        suffix=".tmp.docx",
        dir=doc_path.parent,
        delete=False,
    )
    tmp_path = Path(tmp_file.name)
    tmp_file.close()

    try:
        with zipfile.ZipFile(doc_path, "r") as zin:
            names = zin.namelist()
            referenced_parts: set[str] = set()
            document_relationship_ids: set[str] = set()
            rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
            for rel_name in (name for name in names if name.endswith(".rels")):
                try:
                    rel_root = etree.fromstring(zin.read(rel_name))
                except etree.XMLSyntaxError:
                    continue
                if "/_rels/" in rel_name:
                    prefix, leaf = rel_name.rsplit("/_rels/", 1)
                    owner_part = posixpath.join(prefix, leaf[:-5])
                elif rel_name.startswith("_rels/"):
                    owner_part = rel_name[len("_rels/"):-5]
                else:
                    continue
                owner_dir = posixpath.dirname(owner_part)
                for rel in rel_root.xpath("//r:Relationship", namespaces=rel_ns):
                    if rel_name == "word/_rels/document.xml.rels":
                        document_relationship_ids.add(str(rel.get("Id") or ""))
                    if rel.get("TargetMode") == "External":
                        continue
                    target = rel.get("Target") or ""
                    referenced_parts.add(
                        posixpath.normpath(posixpath.join(owner_dir, target)).lstrip("/")
                    )
            orphan_media = {
                name for name in names
                if name.startswith("word/media/") and name not in referenced_parts
            }
            stats: dict = {"orphan_media_removed": len(orphan_media)}
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
                for name in names:
                    if name in orphan_media:
                        continue
                    data = zin.read(name)
                    if name == "word/document.xml":
                        data, clean_stats = clean_doc_xml(
                            data,
                            preserve_template_guidance=preserve_template_guidance,
                            relationship_ids=document_relationship_ids,
                            selected_product_domain=selected_product_domain,
                        )
                        stats.update(clean_stats)
                    elif name == "word/fontTable.xml":
                        data = _ensure_table_font_definition(data)
                    elif name.startswith("word/header") and name.endswith(".xml"):
                        data, normalized = _normalize_header_identity_xml(data)
                        stats["header_identity_paragraphs_normalized"] = (
                            stats.get("header_identity_paragraphs_normalized", 0)
                            + normalized
                        )
                    if (
                        name.startswith(("word/header", "word/footer"))
                        and name.endswith(".xml")
                    ) or name in {"word/footnotes.xml", "word/endnotes.xml"}:
                        story = etree.fromstring(data)
                        normalized = _normalize_all_table_typography(story)
                        if normalized:
                            data = etree.tostring(
                                story, xml_declaration=True,
                                encoding="UTF-8", standalone=True,
                            )
                            stats["table_typography_normalized"] = (
                                stats.get("table_typography_normalized", 0) + normalized
                            )
                    data, privacy_stats = _scrub_privacy_xml_part(name, data)
                    for key, value in privacy_stats.items():
                        stats[key] = stats.get(key, 0) + value
                    zout.writestr(name, data)

        # Windows 的杀毒/索引器可能短暂占用刚写出的 DOCX；有界重试避免
        # 一次瞬时锁定导致后处理整体失效。
        for attempt in range(6):
            try:
                os.replace(tmp_path, doc_path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.1 * (attempt + 1))
        return stats
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True)
    args = ap.parse_args()
    if not Path(args.doc).exists():
        print(f"文件不存在: {args.doc}"); return
    stats = postprocess(args.doc)
    print(f"后处理完成: {args.doc}")
    for k, v in stats.items():
        if v:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
