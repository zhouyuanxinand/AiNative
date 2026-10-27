"""Final, content-preserving pagination and cell-picture fitting."""
from __future__ import annotations

import re
import math

from lxml import etree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
V = "{urn:schemas-microsoft-com:vml}"

_COLUMN_LABELS = {
    "序号", "项目", "名称", "项目名称", "要求", "指标", "用户要求指标", "拟采用指标",
    "拟采用指标和试验的依据", "测试项目", "测试内容", "判定标准", "备注", "配件名称",
    "数量", "材料或型号", "尺寸", "外观处理", "图样或照片", "技术特性类型", "特性描述",
    "任务阶段", "任务内容", "进度要求", "节点", "进度", "技术文件名称", "批量数量",
    "抽样数量", "批次数量", "抽样数", "技术特征", "性能指标", "客户料号", "中航型号",
}


def _text(element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{W}t"))


def _properties(element, name):
    node = element.find(f"{W}{name}")
    if node is None:
        node = etree.Element(f"{W}{name}")
        element.insert(0, node)
    return node


def _flag(properties, name, value):
    node = properties.find(f"{W}{name}")
    if node is None:
        node = etree.SubElement(properties, f"{W}{name}")
    changed = node.get(f"{W}val") != value
    node.set(f"{W}val", value)
    return int(changed)


def _header_count(rows) -> int:
    count = 0
    for row in rows:
        marker = row.find(f"{W}trPr/{W}tblHeader")
        if marker is None or marker.get(f"{W}val", "on") in {"off", "false", "0"}:
            break
        count += 1
    if count:
        return count
    # A key/value datasheet starts with data, not a repeating column header.
    # Existing explicit multi-row headers remain authoritative above.
    labels = [re.sub(r"\s+", "", _text(cell)) for cell in rows[0].findall(f"{W}tc")]
    return int(sum(label in _COLUMN_LABELS for label in labels) >= 2)


def _page_height(table) -> int:
    block = table
    while block is not None:
        for sibling in block.itersiblings():
            sections = [sibling] if sibling.tag == f"{W}sectPr" else sibling.findall(f".//{W}sectPr")
            for section in sections:
                size, margins = section.find(f"{W}pgSz"), section.find(f"{W}pgMar")
                if size is not None and margins is not None:
                    try:
                        return int(size.get(f"{W}h")) - int(margins.get(f"{W}top", "0")) - int(margins.get(f"{W}bottom", "0"))
                    except (TypeError, ValueError):
                        pass
        block = block.getparent()
        if block is None or block.tag == f"{W}body":
            break
    return 0


def _paragraph_inset(paragraph) -> int | None:
    indent = paragraph.find(f"{W}pPr/{W}ind")
    if indent is None:
        return 0
    try:
        # Logical and character-based indent attributes may override their
        # physical counterparts. Use the larger inset for a conservative fit.
        left = max(0, int(indent.get(f"{W}left", "0")), int(indent.get(f"{W}start", "0")),
                   int(indent.get(f"{W}leftChars", "0")) * 210 / 100)
        right = max(0, int(indent.get(f"{W}right", "0")), int(indent.get(f"{W}end", "0")),
                    int(indent.get(f"{W}rightChars", "0")) * 210 / 100)
        first_line = max(0, int(indent.get(f"{W}firstLine", "0")),
                         int(indent.get(f"{W}firstLineChars", "0")) * 210 / 100)
        return math.ceil(left + right + first_line)
    except ValueError:
        return None


def _short_row(row, table, page_height) -> bool:
    """Conservatively distinguish short rows from evidence needing page flow.

    Word versions do not consistently flow an over-page cantSplit row despite
    the OOXML specification. Only keep rows whose text/image height estimate
    leaves ample room for a repeated header and font/layout differences.
    """
    if page_height <= 0:
        return False
    limit = page_height * .75
    for height in row.findall(f"{W}trPr/{W}trHeight"):
        if int(height.get(f"{W}val", "0")) > limit:
            return False
    for cell in row.findall(f"{W}tc"):
        if cell.find(f"{W}tbl") is not None:
            return False
        width = _cell_width(cell, table) - _cell_margin(cell, table, "left") - _cell_margin(cell, table, "right")
        if width <= 0:
            return False
        estimated = 0
        for paragraph in cell.findall(f"{W}p"):
            inset = _paragraph_inset(paragraph)
            if inset is None or width - inset <= 0:
                return False
            # Table typography is normalized to 10.5pt before this pass.
            # Counting every character at full CJK width overestimates Latin
            # text, keeping ambiguous large rows free to span pages.
            explicit_lines = len(list(paragraph.iter(f"{W}br"))) + len(list(paragraph.iter(f"{W}cr")))
            lines = max(1, math.ceil(len(_text(paragraph)) * 210 / (width - inset))) + explicit_lines
            line_height, paragraph_spacing = 315, 0
            spacing = paragraph.find(f"{W}pPr/{W}spacing")
            if spacing is not None:
                try:
                    if spacing.get(f"{W}lineRule", "auto") == "auto":
                        line_height *= max(1, int(spacing.get(f"{W}line", "240")) / 240)
                    else:
                        line_height = max(line_height, int(spacing.get(f"{W}line", "0")))
                    paragraph_spacing = sum(max(0, int(spacing.get(f"{W}{side}", "0"))) for side in ("before", "after"))
                except ValueError:
                    return False
            estimated += lines * line_height + paragraph_spacing
            for extent in paragraph.iter(f"{WP}extent"):
                estimated += int(extent.get("cy", "0")) / 635
            for shape in paragraph.iter(f"{V}shape"):
                match = re.search(r"(?:^|;)\s*height:([^;]+)", shape.get("style", ""))
                if match:
                    estimated += _points(match[1]) * 20
            if estimated > limit:
                return False
    return True


def _paginate_table(table) -> tuple[int, int, int]:
    rows = table.findall(f"{W}tr")
    header_count = _header_count(rows)
    page_height = _page_height(table)
    kept_rows, flowing_rows = 0, 0
    for index, row in enumerate(rows):
        properties = _properties(row, "trPr")
        short = _short_row(row, table, page_height)
        changed = _flag(properties, "cantSplit", "on" if short else "off")
        kept_rows += changed if short else 0
        flowing_rows += 0 if short else changed
        for height in properties.findall(f"{W}trHeight"):
            if height.get(f"{W}hRule") == "exact":
                # Imported rows can retain a source-specific fixed height.
                # Preserve that minimum while allowing the retained text to
                # grow naturally at the taskbook's font and column widths.
                height.set(f"{W}hRule", "atLeast")
        if index < header_count:
            _flag(properties, "tblHeader", "on")
        for cell in row.findall(f"{W}tc"):
            for paragraph in cell.findall(f"{W}p"):
                # Join only header rows to the first data row, never every
                # body row into one unbreakable table through source styles.
                _flag(_properties(paragraph, "pPr"), "keepNext", "1" if index < header_count else "0")
    return kept_rows, flowing_rows, header_count


def _cell_margin(cell, table, side) -> int:
    logical = "start" if side == "left" else "end"
    for container in (cell.find(f"{W}tcPr/{W}tcMar"), table.find(f"{W}tblPr/{W}tblCellMar")):
        if container is None:
            continue
        for name in (logical, side):
            value = container.find(f"{W}{name}")
            if value is not None and value.get(f"{W}type", "dxa") in {"dxa", "nil"}:
                try:
                    return max(0, int(value.get(f"{W}w", "0")))
                except ValueError:
                    pass
    return 108  # Word's standard 0.075-inch left/right cell inset.


def _cell_width(cell, table) -> int:
    node = cell.find(f"{W}tcPr/{W}tcW")
    if node is not None and node.get(f"{W}type", "dxa") == "dxa":
        try:
            return int(node.get(f"{W}w", "0"))
        except ValueError:
            pass
    return 0


def _resize_drawing(container, limit) -> bool:
    extent = container.find(f"{WP}extent")
    if extent is None:
        return False
    try:
        width, height = int(extent.get("cx", "0")), int(extent.get("cy", "0"))
    except ValueError:
        return False
    if width <= limit or height <= 0:
        return False
    ratio = limit / width
    for node in [extent, *container.findall(f".//{A}xfrm/{A}ext")]:
        for coordinate in ("cx", "cy"):
            if node.get(coordinate):
                node.set(coordinate, str(max(1, round(int(node.get(coordinate)) * ratio))))
    return True


def _points(value):
    match = re.fullmatch(r"\s*([0-9.]+)(pt|in|cm|mm|px)\s*", value, re.I)
    if not match:
        return 0.0
    return float(match[1]) * {"pt": 1, "in": 72, "cm": 72 / 2.54, "mm": 72 / 25.4, "px": .75}[match[2].lower()]


def _resize_vml(shape, limit) -> bool:
    if shape.find(f"{V}imagedata") is None:
        return False
    parts = [part.split(":", 1) for part in shape.get("style", "").split(";") if ":" in part]
    styles = {key.strip(): value.strip() for key, value in parts}
    width, height = _points(styles.get("width", "")), _points(styles.get("height", ""))
    limit_points = limit / 12700
    if width <= limit_points or height <= 0:
        return False
    ratio = limit_points / width
    replacements = {"width": f"{limit_points:.6f}pt", "height": f"{height * ratio:.6f}pt"}
    shape.set("style", ";".join(f"{key}:{replacements.get(key.strip(), value)}" for key, value in parts))
    return True


def _fit_cell_images(table) -> int:
    changed = 0
    for cell in table.iter(f"{W}tc"):
        owner = next(cell.iterancestors(f"{W}tbl"), table)
        width = _cell_width(cell, owner)
        if width <= 0:
            continue
        # Reserve cell insets and one point for border rounding. The source
        # media part and all crop/relationship metadata stay untouched.
        available = width - _cell_margin(cell, owner, "left") - _cell_margin(cell, owner, "right") - 20
        for paragraph in cell.findall(f"{W}p"):
            inset = _paragraph_inset(paragraph)
            if inset is None:
                continue
            limit = (available - inset) * 635
            if limit <= 0:
                continue
            for tag in ("inline", "anchor"):
                for drawing in paragraph.iter(f"{WP}{tag}"):
                    changed += int(_resize_drawing(drawing, limit))
            for shape in paragraph.iter(f"{V}shape"):
                changed += int(_resize_vml(shape, limit))
    return changed


def normalize_document_layout(blocks, *, is_heading) -> dict:
    """Apply the same final layout contract to generated and copied body data."""
    stats = {"table_rows_kept_together": 0, "table_long_rows_allowed_to_split": 0, "table_header_rows_repeated": 0,
             "heading_paragraphs_kept_with_next": 0, "table_titles_kept_with_next": 0, "table_images_fitted": 0}
    in_chapter = False
    join_blank = False
    for index, block in enumerate(blocks):
        if block.tag == f"{W}p":
            if is_heading(block):
                in_chapter = join_blank = True
                properties = _properties(block, "pPr")
                stats["heading_paragraphs_kept_with_next"] += _flag(properties, "keepNext", "1")
                _flag(properties, "keepLines", "1")
            elif join_blank and not _text(block).strip() and not list(block.iter(f"{W}drawing")) and not list(block.iter(f"{W}pict")):
                _flag(_properties(block, "pPr"), "keepNext", "1")
            else:
                join_blank = False
            continue
        join_blank = False
        if block.tag != f"{W}tbl" or not in_chapter:
            continue
        if index:
            previous = blocks[index - 1]
            alignment = previous.find(f"{W}pPr/{W}jc")
            if (previous.tag == f"{W}p" and alignment is not None
                    and alignment.get(f"{W}val") == "center"
                    and 0 < len(_text(previous).strip()) <= 80
                    and not list(previous.iter(f"{W}drawing"))
                    and not list(previous.iter(f"{W}pict"))):
                stats["table_titles_kept_with_next"] += _flag(_properties(previous, "pPr"), "keepNext", "1")
        rows = block.findall(f"{W}tr")
        stats["table_images_fitted"] += _fit_cell_images(block)
        if len(rows) > 1 and _text(rows[0]).strip():
            row_count, flowing_count, header_count = _paginate_table(block)
            stats["table_rows_kept_together"] += row_count
            stats["table_long_rows_allowed_to_split"] += flowing_count
            stats["table_header_rows_repeated"] += header_count
    return stats
