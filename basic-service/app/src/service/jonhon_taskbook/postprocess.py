# -*- coding: utf-8 -*-
"""
postprocess.py — 输出文档后处理（通用，适用于任意 docx）
扫描步骤：
  1. 清红色字体 → 黑色
  2. 清高亮/底纹
  3. 清 20xx 占位日期文字
  4. 删除模板残留整段（全红段、研制阶段占位、模板话术）
  5. 整节删除（适航/AS9100/QFD/过时淘汰等无用分支）
  6. 清横版分节符
  7. 图片段落强制居中
  8. 表格列宽超页宽时等比缩放
"""
from __future__ import annotations
import os, posixpath, re, tempfile, time, zipfile
from pathlib import Path
from lxml import etree
import yaml
from jonhon_taskbook.renderer.table_style_engine import (
    DEFAULT_FONT,
    apply_table_style,
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
_DATE_RE  = re.compile(r'20[xX]{2}年[xX]月|20xx年x月', re.I)
_PHASE_RE = re.compile(r'[（(]?与产品研制阶段同步转阶段[）)]?|F/C/S/D（与')
_PHASE_PLACEHOLDER_RE = re.compile(
    r'F/C/S/D\s*[（(]\s*与产品研制阶段同步转阶段\s*[）)]'
)
_FIGURE_CAPTION_RE = re.compile(r'^(\s*图\s*)(\d+)(?=\D|$)')
_FIGURE_REFERENCE_RE = re.compile(r'图\s*(\d+)')
_STANDALONE_PLACEHOLDER_RE = re.compile(r'^(?:[.．·•]{3,}|…{2,})$')

# 整段话术删除（段落内容匹配到任一条则删除该段）
_JUNK_PATTERNS = [
    re.compile(r'适用时保留.*不适用.*删除', re.S),
    re.compile(r'不适用.*请删除', re.S),
    re.compile(r'适用于.*请删除', re.S),
    re.compile(r'[(（]适用时保留'),
    re.compile(r'20[Xx]{2}年'),
    re.compile(r'[Xx]{2}只'),
    re.compile(r'[Xx]万元'),
    re.compile(r'共[Xx]套'),
    re.compile(r'请补充.*编号'),
    re.compile(r'[（(]请补充'),
    re.compile(r'PCD.*批量|民机.*批量'),
    re.compile(r'适航条款|适航性顶层文件|型号审定|民用航空'),
    re.compile(r'AS9100'),
    re.compile(r'过时淘汰风险'),
    re.compile(r'原材料.*元器件.*过时'),
    # Formal-output-only template authoring instructions.  These phrases are
    # directions to the taskbook author, not product requirements.  Keep the
    # patterns semantic and number-independent so a re-numbered/re-ordered
    # customer template is handled the same way.
    re.compile(r'此条要求对用户的特殊要求进行识别', re.S),
    re.compile(r'内容要求[：:].*顾客要求超出', re.S),
    re.compile(r'按照技术协议要求写.*没有要求的删除此项', re.S),
    re.compile(
        r'XX产品(?:可靠性|维修性|测试性|保障性|安全性|环境适应性)'
        r'(?:定量|定性)?要求',
        re.S,
    ),
    re.compile(r'对于改型、派生产品.*应明示产品类型', re.S),
    re.compile(r'投入模具必要性论述', re.S),
    re.compile(r'^\s*XXX\s*[：:]\s*XX\b', re.S),
]

# 整节删除（标题匹配则删除标题及其下所有内容直到同级/上级标题）
# 不加行首锚点，标题文字只要包含关键词就删整节
_SECTION_DELETE_PATTERNS = [
    re.compile(r'适航要求'),
    re.compile(r'适用的适航条款'),
    re.compile(r'适航性顶层文件'),
    re.compile(r'适航审查方式'),
    re.compile(r'适航其他管理要求'),
    re.compile(r'过时淘汰风险'),
    re.compile(r'原材料.*元器件.*过时'),
    re.compile(r'AS9100'),
]


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
        if not _is_indicator_table(child):
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
            if not _is_indicator_instruction(text):
                break
            parent = previous.getparent()
            if parent is not None:
                parent.remove(previous)
                stats["indicator_instruction_deleted"] += 1
            cursor -= 1


def _normalize_indicator_table_formatting(body, stats: dict) -> None:
    """Normalize the generated indicator table as one visual component.

    Source runs are intentionally copied byte-for-byte everywhere else.  The
    indicator table is different: it is a controlled structured rendering
    surface, so source/template review styling (blue, italic, mixed fonts and
    sizes) must not leak into the deliverable.  The dominant size/font already
    present in the table is used as the template-native baseline; no business
    text is changed.
    """
    tables = [tbl for tbl in body.iter(f"{_W}tbl") if _is_indicator_table(tbl)]
    if not tables:
        return
    normalized_runs = 0
    for table in tables:
        runs = [
            run for run in table.findall(f".//{_W}r")
            if run.findall(f".//{_W}t")
        ]
        sizes: list[str] = []
        fonts: list[str] = []
        for run in runs:
            rpr = run.find(f"{_W}rPr")
            if rpr is None:
                continue
            sz = rpr.find(f"{_W}sz")
            if sz is not None and sz.get(f"{_W}val"):
                sizes.append(str(sz.get(f"{_W}val")))
            rfonts = rpr.find(f"{_W}rFonts")
            if rfonts is not None:
                for key in ("eastAsia", "ascii", "hAnsi", "cs"):
                    value = rfonts.get(f"{_W}{key}")
                    if value:
                        fonts.append(value)
        # 21 half-points = 10.5pt, the normal body size of the controlled
        # templates.  Prefer the most common existing template value.
        size = max(set(sizes), key=sizes.count) if sizes else "21"
        font = max(set(fonts), key=fonts.count) if fonts else "仿宋_GB2312"
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
            rfonts = rpr.find(f"{_W}rFonts")
            if rfonts is None:
                rfonts = etree.Element(f"{_W}rFonts")
                rpr.insert(0, rfonts)
            for key in ("ascii", "hAnsi", "eastAsia", "cs"):
                rfonts.set(f"{_W}{key}", font)
            sz = rpr.find(f"{_W}sz")
            if sz is None:
                sz = etree.SubElement(rpr, f"{_W}sz")
            sz.set(f"{_W}val", size)
            sz_cs = rpr.find(f"{_W}szCs")
            if sz_cs is None:
                sz_cs = etree.SubElement(rpr, f"{_W}szCs")
            sz_cs.set(f"{_W}val", size)
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
    """Apply final controlled-table layout after all DOCX XML mutations.

    Earlier table writers style the tables they own, but later cleanup and
    width normalization can encounter tables that came directly from a
    customer template.  This final, semantic pass normalizes the grid, live
    page width, repeatable header, row flow and fonts of indicator/failure
    tables without touching unrelated signature or cover tables.  Existing
    table-native font size is retained when available.
    """
    normalized = 0
    for table in root.findall(f".//{_W}tbl"):
        if not (_is_indicator_table(table) or _is_failure_table(table)):
            continue
        runs = [
            run
            for run in table.findall(f".//{_W}r")
            if run.findall(f".//{_W}t")
        ]
        sizes: list[str] = []
        fonts: list[str] = []
        for run in runs:
            rpr = run.find(f"{_W}rPr")
            if rpr is None:
                continue
            size = rpr.find(f"{_W}sz")
            if size is not None and size.get(f"{_W}val"):
                sizes.append(str(size.get(f"{_W}val")))
            rfonts = rpr.find(f"{_W}rFonts")
            if rfonts is not None:
                for key in ("eastAsia", "ascii", "hAnsi", "cs"):
                    value = rfonts.get(f"{_W}{key}")
                    if value:
                        fonts.append(str(value))
        size = int(max(set(sizes), key=sizes.count)) if sizes else 21
        font = max(set(fonts), key=fonts.count) if fonts else DEFAULT_FONT
        table_kind = "indicator" if _is_indicator_table(table) else "failure"
        apply_table_style(
            table,
            table_kind,
            font_name=font,
            size_half_points=size,
        )
        normalized += len(runs)
    if normalized:
        stats["controlled_table_font_normalized"] = normalized
        stats["controlled_table_layout_normalized"] = normalized


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


def _is_junk_para(text: str) -> bool:
    for pat in _JUNK_PATTERNS:
        if pat.search(text):
            return True
    return False


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

    # Empty controlled-template sections are business content and must remain,
    # but review-only formatting is not business content. Preservation mode
    # therefore keeps the paragraphs/tables while still normalizing red text,
    # highlights, page orientation, images and table geometry.
    stats["template_guidance_preserved"] = bool(preserve_template_guidance)

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

    # 独立省略号只表示模板待填位置，不是模板业务正文。即使启用“保留
    # 未填模板内容”，也必须清除这种占位符；含有实际文字的段落不受影响。
    for paragraph in list(body.findall(f".//{_W}p")):
        compact = re.sub(r"\s+", "", _para_text(paragraph))
        if not _STANDALONE_PLACEHOLDER_RE.fullmatch(compact):
            continue
        parent = paragraph.getparent()
        if parent is not None:
            parent.remove(paragraph)
            stats["standalone_placeholder_deleted"] += 1

    # 未提供研制阶段时不得编造 F/C/S/D；清除模板占位说明但保留字段。
    for paragraph in body.findall(f".//{_W}p"):
        full_text = _para_text(paragraph)
        updated = _PHASE_PLACEHOLDER_RE.sub("", full_text).rstrip()
        if updated != full_text:
            _replace_paragraph_text(paragraph, updated)
            stats["phase_placeholder_cleared"] += 1

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
        for t_el in r.findall(f"{_W}t"):
            if t_el.text and _DATE_RE.search(t_el.text):
                t_el.text = _DATE_RE.sub("", t_el.text).strip()
                stats["date_cleared"] += 1

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

    # ── 步骤2：整段删除（全红段、研制阶段占位、模板话术）──────────────────────
    paras_to_del = []
    for p in ([] if preserve_template_guidance else
              (body.findall(f".//{_W}p") if body is not None else [])):
        full_text = _para_text(p).strip()

        if _PHASE_RE.search(full_text) and len(full_text) < 60:
            paras_to_del.append(p); stats["para_deleted"] += 1; continue

        if full_text and _is_junk_para(full_text):
            paras_to_del.append(p); stats["para_deleted"] += 1; continue

        if not full_text:
            continue
        text_runs = [r for r in p.findall(f"{_W}r")
                     if "".join(t.text or "" for t in r.findall(f"{_W}t")).strip()]
        if not text_runs:
            continue
        still_red = all(
            any((c.get(f"{_W}val") or "").upper() in _RED_VALS
                for c in r.findall(f".//{_W}color"))
            for r in text_runs
        )
        if still_red:
            paras_to_del.append(p); stats["para_deleted"] += 1

    for p in paras_to_del:
        parent = p.getparent()
        if parent is not None:
            parent.remove(p)

    # ── 步骤3：整节删除（适航/AS9100/QFD 等无用分支）──────────────────────────
    if body is not None and not preserve_template_guidance:
        body_children = list(body)
        to_del_ranges = []
        i = 0
        while i < len(body_children):
            child = body_children[i]
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag != "p":
                i += 1; continue
            txt = _para_text(child).strip()
            depth = _heading_depth(child)
            if depth > 0 and txt:
                matched = any(pat.search(txt) for pat in _SECTION_DELETE_PATTERNS)
                if matched:
                    start = i
                    j = i + 1
                    while j < len(body_children):
                        nc = body_children[j]
                        nc_tag = nc.tag.split("}")[-1] if "}" in nc.tag else nc.tag
                        if nc_tag == "p":
                            nd = _heading_depth(nc)
                            if nd > 0 and nd <= depth:
                                break
                        j += 1
                    to_del_ranges.append((start, j - 1))
                    stats["section_deleted"] += 1
                    i = j
                    continue
            i += 1

        for start, end in reversed(to_del_ranges):
            for idx in range(end, start - 1, -1):
                if idx < len(body_children):
                    el = body_children[idx]
                    par = el.getparent()
                    if par is not None:
                        par.remove(el)

        # “产品运行场景识别”当前没有业务输入，只保留受控人工编辑提示。
        # QFD 是否保留由研制流程策略治理：全新项目保留人工编辑槽位，
        # 改型项目已在规则填充阶段按语义标题删除。
        body_children = list(body)
        for i, child in enumerate(body_children):
            if child.tag != f"{_W}p":
                continue
            txt = _para_text(child).strip()
            depth = _heading_depth(child)
            if depth <= 0 or "产品运行场景识别" not in txt:
                continue
            j = i + 1
            while j < len(body_children):
                current = body_children[j]
                if current.tag == f"{_W}p":
                    current_depth = _heading_depth(current)
                    if current_depth > 0 and current_depth <= depth:
                        break
                j += 1
            for current in reversed(body_children[i + 1:j]):
                current_text = _para_text(current).strip() if current.tag == f"{_W}p" else ""
                if current_text in {"本阶段不填写。", "需设计员编辑。"}:
                    continue
                parent = current.getparent()
                if parent is not None:
                    parent.remove(current)
                    stats["para_deleted"] += 1
            break

        # 接口尺寸正文已按语义整体迁入目标标题；删除后方没有正文的模板子标题，
        # 避免空子标题干扰模板自身的多级编号。
        empty_interface_labels = {"安装方式", "安装尺寸", "外形尺寸", "端接形式"}
        body_children = list(body)
        empty_heading_ranges = []
        for i, child in enumerate(body_children):
            if child.tag != f"{_W}p" or _heading_depth(child) <= 0:
                continue
            label = re.sub(r"^\d+(?:\.\d+)*\s*", "", _para_text(child)).strip().strip("：:")
            if label not in empty_interface_labels:
                continue
            j = i + 1
            while j < len(body_children):
                current = body_children[j]
                if current.tag != f"{_W}p" or _para_text(current).strip():
                    break
                j += 1
            if j < len(body_children):
                following = body_children[j]
                if following.tag == f"{_W}p" and _heading_depth(following) > 0:
                    empty_heading_ranges.append((i, j))
        for start, end in reversed(empty_heading_ranges):
            for current in reversed(body_children[start:end]):
                parent = current.getparent()
                if parent is not None:
                    parent.remove(current)
                    stats["para_deleted"] += 1

        # 源文档章节号不是目标模板结构。仅剥离接口原文块中“5 大型……”这类
        # 标题式行首号，正文内部的“1）/2）”枚举保持不变。
        source_number_pattern = re.compile(r"^\s*\d+\s+(?=(?:小型|大型).*(?:外形|接口|节点))")
        source_heading_pattern = re.compile(r"^(?:小型|大型).*(?:外形|接口|节点).*(?:要求|如下)")
        for child in list(body):
            if child.tag != f"{_W}p" or _heading_depth(child) > 0:
                continue
            full_text = _para_text(child)
            cleaned = source_number_pattern.sub("", full_text, count=1)
            changed = cleaned != full_text
            if changed:
                text_nodes = child.findall(f".//{_W}t")
                if text_nodes:
                    text_nodes[0].text = cleaned
                    for node in text_nodes[1:]:
                        node.text = ""
            if source_heading_pattern.search(cleaned):
                p_pr = child.find(f"{_W}pPr")
                if p_pr is not None:
                    for num_pr in list(p_pr.findall(f"{_W}numPr")):
                        p_pr.remove(num_pr)
                        changed = True
            if changed:
                stats["source_numbers_stripped"] = stats.get("source_numbers_stripped", 0) + 1

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
    _DML = "http://schemas.openxmlformats.org/drawingml/2006/main"
    _PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
    img_centered = 0
    for p in root.findall(f".//{_W}p"):
        has_img = (
            p.find(f".//{_W}drawing") is not None or
            p.find(f".//{{{_DML}}}blip") is not None or
            p.find(f".//{{{_PIC}}}pic") is not None
        )
        if not has_img:
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

    # ── 步骤6：表格列宽等比缩放（超 A4 竖版可用宽 9638 twip）──────────────
    PAGE_W = 9638
    rescaled = 0
    for tbl in root.findall(f".//{_W}tbl"):
        grid = tbl.find(f"{_W}tblGrid")
        if grid is None:
            continue
        cols = grid.findall(f"{_W}gridCol")
        if not cols:
            continue
        total_w = sum(int(c.get(f"{_W}w") or 0) for c in cols)
        if total_w <= PAGE_W or total_w == 0:
            continue
        ratio = PAGE_W / total_w
        for c in cols:
            c.set(f"{_W}w", str(int(int(c.get(f"{_W}w") or 0) * ratio)))
        for tc in tbl.findall(f".//{_W}tc"):
            tcPr = tc.find(f"{_W}tcPr")
            if tcPr is None:
                continue
            tcW = tcPr.find(f"{_W}tcW")
            if tcW is not None and tcW.get(f"{_W}type", "dxa") in ("dxa", ""):
                tcW.set(f"{_W}w", str(int(int(tcW.get(f"{_W}w") or 0) * ratio)))
        tblPr = tbl.find(f"{_W}tblPr")
        if tblPr is not None:
            tblW = tblPr.find(f"{_W}tblW")
            if tblW is not None:
                tblW.set(f"{_W}w", str(PAGE_W))
                tblW.set(f"{_W}type", "dxa")
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
                    elif name.startswith("word/header") and name.endswith(".xml"):
                        data, normalized = _normalize_header_identity_xml(data)
                        stats["header_identity_paragraphs_normalized"] = (
                            stats.get("header_identity_paragraphs_normalized", 0)
                            + normalized
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
