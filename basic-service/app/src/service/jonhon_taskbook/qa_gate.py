# -*- coding: utf-8 -*-
"""qa_gate.py — 质量门禁检查器"""
from __future__ import annotations
from collections import Counter
import re
from typing import Any, Dict, List

from jonhon_taskbook.standard_order import sort_standards

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{W}}}"
_W_DRAW = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
MANUAL_FILL_MARKER = "【人工填写】"
ITALIC_ANNOTATION_MARKER = "【请人工标注】"
_RED_VALUES = {"FF0000", "C00000", "E00000", "D00000"}


def _para_text(para) -> str:
    return "".join(t.text or "" for t in para.findall(f".//{_W}t")).strip()


def _cell_text(cell) -> str:
    return "".join(t.text or "" for t in cell.findall(f".//{_W}t")).strip()


def _visual_relationship_ids(element) -> list[str]:
    """Return visible DrawingML/VML image relationship IDs.

    Generic shapes, drawing containers and OLE objects are not enough: a real
    relationship attribute is required.  Deleted/moved-from/hidden runs are
    not visible body evidence.
    """
    values: list[str] = []
    for node in element.xpath(
        './/*[local-name()="blip" or local-name()="imagedata"]'
    ):
        if node.xpath('ancestor::*[local-name()="del" or local-name()="moveFrom"]'):
            continue
        if node.xpath(
            'ancestor::*[local-name()="r"]/*[local-name()="rPr"]/*[local-name()="vanish"]'
        ):
            continue
        for attr_name, value in node.attrib.items():
            if re.sub(r"^.*}", "", attr_name) in {"embed", "id"} and value:
                values.append(str(value))
    return values


def _has_visual_object(element) -> bool:
    return bool(_visual_relationship_ids(element))


def _is_figure_caption(text: str) -> bool:
    return bool(
        re.match(r"^\s*(?:图\s*\d+|Fig\.?\s*\d+)(?=\D|$)", text or "", re.I)
    )


class QAGate:
    def __init__(self, rules: dict, flags: dict):
        self.block_rules = rules.get("block_if", {})
        self.warn_rules = rules.get("warn_if", {})
        self.flags = flags

    def _count_red(self, root) -> int:
        """Count uncontrolled red runs, excluding the governed manual marker.

        The old implementation counted ``w:color`` nodes.  That made the
        leadership-approved red ``【人工填写】`` marker indistinguishable from
        leaked red template instructions.  Counting at run level lets the
        gate exempt only the exact controlled marker while every other red
        run remains a blocker.
        """
        count = 0
        for run in root.findall(f".//{_W}r"):
            color = run.find(f"./{_W}rPr/{_W}color")
            if color is None:
                continue
            val = (color.get(f"{_W}val") or "").upper()
            if val not in _RED_VALUES:
                continue
            text = "".join(
                node.text or "" for node in run.findall(f".//{_W}t")
            ).strip()
            if text == MANUAL_FILL_MARKER or text == ITALIC_ANNOTATION_MARKER:
                continue
            count += 1
        return count

    def _count_highlight(self, root) -> int:
        return len(root.findall(f".//{_W}highlight"))

    def _full_text(self, root) -> str:
        return " ".join(t.text or "" for t in root.findall(f".//{_W}t"))

    def _paras(self, root) -> list[str]:
        return [_para_text(p) for p in root.findall(f".//{_W}p")]

    def _find_tables_with_header(self, root, keyword: str) -> list:
        body = root.find(f".//{_W}body")
        if body is None:
            body = root
        children = list(body)
        result = []
        for i, child in enumerate(children):
            if child.tag != f"{_W}tbl":
                continue
            prev_txt = ""
            for j in range(i - 1, max(i - 5, -1), -1):
                if children[j].tag == f"{_W}p":
                    prev_txt = _para_text(children[j])
                    if prev_txt:
                        break
            if keyword in prev_txt:
                result.append(child)
        return result

    def _change_record_data_rows(self, root) -> int:
        for tbl in root.findall(f".//{_W}tbl"):
            rows = tbl.findall(f"{_W}tr")
            if len(rows) < 2:
                continue
            h = _cell_text(rows[0])
            if "版本" in h or "章条" in h:
                return len(rows) - 1
        return 0

    def _indicator_table_exists(self, root) -> bool:
        for tbl in root.findall(f".//{_W}tbl"):
            rows = tbl.findall(f"{_W}tr")
            if len(rows) < 2:
                continue
            h = _cell_text(rows[0])
            if "指标" in h or "参数" in h:
                return True
        return False

    def _indicator_has_basis_col(self, root) -> bool:
        for tbl in root.findall(f".//{_W}tbl"):
            rows = tbl.findall(f"{_W}tr")
            if len(rows) < 2:
                continue
            h = _cell_text(rows[0])
            if ("指标" in h or "参数" in h) and "依据" in h:
                return True
        return False

    def _indicator_has_expected_columns(self, root) -> bool:
        """Accept the governed fields exposed by the live customer template."""
        required = ("项目", "用户要求", "拟采用", "依据")
        for tbl in root.findall(f".//{_W}tbl"):
            rows = tbl.findall(f"{_W}tr")
            if not rows:
                continue
            header = _cell_text(rows[0])
            if "用户要求" in header or "标准要求" in header:
                column_count = len(rows[0].findall(f"{_W}tc"))
                if column_count not in {4, 5}:
                    return False
                if not all(token in header for token in required):
                    return False
                return column_count == 4 or (
                    "标准要求" in header or "规范要求" in header
                )
        return False

    def _indicator_data_row_shape_defects(self, root) -> list[str]:
        """Return rows that diverge from the live template header geometry.

        ``python-docx`` exposes repeated logical cells for a horizontally
        merged OOXML cell.  Visual inspection therefore cannot rely on
        ``row.cells``.  The delivery gate must inspect the raw ``w:tc``
        elements and derives the expected row width from the actual header,
        which may legitimately contain four or five columns.
        """
        defects: list[str] = []
        for table in root.findall(f".//{_W}tbl"):
            rows = table.findall(f"{_W}tr")
            if not rows:
                continue
            header = _cell_text(rows[0])
            if "用户要求" not in header and "标准要求" not in header:
                continue
            expected_cells = len(rows[0].findall(f"{_W}tc"))
            if expected_cells < 4:
                continue

            for row_index, row in enumerate(rows[1:], start=2):
                cells = row.findall(f"{_W}tc")
                texts = [_cell_text(cell) for cell in cells]
                if not any(texts):
                    continue

                # A category divider is one physical cell spanning the full
                # controlled table width.  It is structural, not a data row.
                if len(cells) == 1:
                    grid_span = cells[0].find(f"{_W}tcPr/{_W}gridSpan")
                    try:
                        span = int(grid_span.get(f"{_W}val")) if grid_span is not None else 1
                    except (TypeError, ValueError):
                        span = 1
                    if span >= expected_cells:
                        continue

                if len(cells) != expected_cells:
                    label = next((text for text in texts if text), "未命名行")
                    defects.append(
                        f"第{row_index}行 {label[:30]}（物理单元格 {len(cells)}，"
                        f"应与表头一致为 {expected_cells}）"
                    )
        return defects

    def _indicator_instruction_paragraphs(self, root) -> list[str]:
        """Find template authoring prompts that survived post-processing."""
        prompts = (
            "将输入中的指标",
            "模板中没有时",
            "输入指标中没有",
            "需要在研制任务书模板中进行添加",
        )
        body = root.find(f".//{_W}body")
        if body is None:
            body = root
        children = list(body)
        leftovers: list[str] = []
        for i, child in enumerate(children):
            if child.tag != f"{_W}tbl":
                continue
            rows = child.findall(f"{_W}tr")
            header = _cell_text(rows[0]) if rows else ""
            if "用户要求" not in header and "标准要求" not in header:
                continue
            for previous in reversed(children[max(0, i - 3):i]):
                if previous.tag != f"{_W}p":
                    continue
                text = _para_text(previous)
                if text and any(token in text for token in prompts):
                    leftovers.append(text)
        return leftovers

    def _indicator_change_record_contamination(self, root) -> list[str]:
        """Reject change-record text copied into indicator value columns."""
        markers = (
            "改前内容", "改后内容", "后续节点顺序依次变更",
            "删除小节", "删除表", "新发",
        )
        contaminated: list[str] = []
        for table in root.findall(f".//{_W}tbl"):
            rows = table.findall(f"{_W}tr")
            if len(rows) < 2:
                continue
            header_cells = rows[0].findall(f"{_W}tc")
            headers = [_cell_text(cell) for cell in header_cells]
            if "用户要求指标" not in headers and "标准要求" not in headers:
                continue
            value_indexes = [
                index for index, header in enumerate(headers)
                if header in {"标准要求", "拟采用指标"}
            ]
            for row in rows[1:]:
                cells = row.findall(f"{_W}tc")
                for index in value_indexes:
                    if index >= len(cells):
                        continue
                    text = _cell_text(cells[index])
                    if any(marker in text for marker in markers):
                        contaminated.append(text)
        return contaminated

    def _landscape_sections(self, root) -> int:
        """Count explicit landscape section settings in the output package."""
        return sum(
            1
            for section in root.findall(f".//{_W}sectPr")
            if (
                section.find(f"{_W}pgSz") is not None
                and section.find(f"{_W}pgSz").get(f"{_W}orient", "").lower() == "landscape"
            )
        )

    def _all_figure_caption_orphans(self, root) -> list[str]:
        """Check every visible 图/Fig caption, not only profile-listed captions."""
        captions = []
        for text in self._paras(root):
            if _is_figure_caption(text):
                captions.append(text)
        return self._figure_caption_orphans(root, captions)

    def _standard_order_issues(self, root) -> list[str]:
        """Return standard lines that violate the configured semantic order."""
        # Keep grouped YAML prefix families intact (for example
        # ``[GB/T, GB]``).  Stringifying these lists makes generation and QA
        # use different sort policies and causes a false warning even when the
        # visible references are already in the configured order.
        order = [
            item
            for item in self.flags.get("standard_sort_order", [])
            if item
        ]
        if not order:
            return []
        heading_words = self.flags.get(
            "standards_heading_keywords",
            ["适用的法律法规要求", "适用法律法规", "引用标准"],
        )
        body = root.find(f".//{_W}body")
        if body is None:
            body = root
        children = list(body)
        standard_re = re.compile(
            r"^\s*(?:GB(?:/T)?|GJB(?:/Z)?|Q/|KJB|AS\d+|MIL|SAE)\s*[A-Za-z0-9./_-]+",
            re.I,
        )

        def is_heading(element) -> bool:
            if element.tag != f"{_W}p":
                return False
            ppr = element.find(f"{_W}pPr")
            if ppr is not None and ppr.find(f"{_W}outlineLvl") is not None:
                return True
            style = ppr.find(f"{_W}pStyle") if ppr is not None else None
            value = style.get(f"{_W}val", "") if style is not None else ""
            return "heading" in value.lower() or bool(
                re.match(r"^\d+(?:\.\d+)*\s+\S", _para_text(element))
            )

        for i, child in enumerate(children):
            if child.tag != f"{_W}p" or not any(word in _para_text(child) for word in heading_words):
                continue
            lines = []
            for following in children[i + 1:]:
                if is_heading(following):
                    break
                if following.tag == f"{_W}p":
                    text = _para_text(following)
                    if standard_re.match(text):
                        lines.append(text)
            if len(lines) < 2:
                continue

            sorted_lines = sort_standards(lines, order)
            if lines != sorted_lines:
                return lines
        return []

    def _figure_caption_sequence_issues(self, root) -> list[int]:
        """Return visible structural figure numbers when they are not 1..N."""
        numbers: list[int] = []
        for text in self._paras(root):
            match = re.match(r"^\s*图\s*(\d+)\s*", text)
            if match:
                numbers.append(int(match.group(1)))
        return numbers if numbers and numbers != list(range(1, len(numbers) + 1)) else []

    def _appendix_a_empty_table(self, root) -> bool:
        in_app = False
        body = root.find(f".//{_W}body")
        if body is None:
            body = root
        for child in list(body):
            if child.tag == f"{_W}p":
                txt = _para_text(child).replace(" ", "")
                if re.match(r"^附录A", txt):
                    in_app = True
                elif re.match(r"^附录[B-Z]", txt):
                    in_app = False
            if in_app and child.tag == f"{_W}tbl":
                rows = child.findall(f"{_W}tr")
                empty = sum(
                    1
                    for r in rows
                    if not "".join(t.text or "" for t in r.findall(f".//{_W}t")).strip()
                )
                if len(rows) > 3 and empty > len(rows) // 2:
                    return True
        return False

    def _standard_version_conflict(self, root) -> bool:
        full = self._full_text(root)
        for num in set(re.findall(r"GJB\s*(\d+)", full)):
            versions = re.findall(rf"GJB\s*{num}([AB])", full)
            if len(set(versions)) > 1:
                return True
        return False

    def _contains_any_phrase(self, root, phrases: list[str]) -> list[str]:
        full = self._full_text(root)
        return [p for p in phrases if p and p in full]

    def _missing_required_phrases(self, root, phrases: list[str]) -> list[str]:
        full = self._full_text(root)
        return [p for p in phrases if p and p not in full]

    def _missing_phrase_groups(self, root, groups: list[list[str]]) -> list[str]:
        full = self._full_text(root)
        missing = []
        for group in groups:
            opts = [p for p in group if p]
            if opts and not any(p in full for p in opts):
                missing.append(" / ".join(opts))
        return missing

    def _missing_headings(self, root, headings: list[str]) -> list[str]:
        paras = self._paras(root)
        return [h for h in headings if h and not any(h in p for p in paras)]

    def _missing_figure_captions(self, root, figures: list[str]) -> list[str]:
        paras = self._paras(root)
        return [f for f in figures if f and not any(f in p for p in paras)]

    def _missing_table_keywords(self, root, keywords: list[str]) -> list[str]:
        all_tables = []
        for tbl in root.findall(f".//{_W}tbl"):
            rows = tbl.findall(f"{_W}tr")
            txt = " ".join(_cell_text(r) for r in rows)
            if txt:
                all_tables.append(txt)
        return [kw for kw in keywords if kw and not any(kw in t for t in all_tables)]

    def _figure_caption_orphans(self, root, captions: list[str]) -> list[str]:
        """
        检查图题是否紧邻其前方图片。

        只跳过空排版段落；一旦遇到其他可见正文、表格或另一张图片就
        终止。这样既证明“图片在图题之前”的顺序，也防止宽松的前后窗口
        把不相关图片误认成当前图题的证据。
        """
        body = root.find(f".//{_W}body")
        if body is None:
            body = root
        children = list(body)
        orphans: list[str] = []

        for cap in captions:
            if not cap:
                continue
            for i, child in enumerate(children):
                paragraphs = (
                    [child]
                    if child.tag == f"{_W}p"
                    else child.findall(f".//{_W}p")
                )
                if not any(cap in _para_text(paragraph) for paragraph in paragraphs):
                    continue
                # Some producers place the drawing and its caption text in
                # the same paragraph.  That is still one continuous object.
                has_image = _has_visual_object(child)
                if not has_image:
                    for previous in reversed(children[:i]):
                        previous_text = (
                            _para_text(previous)
                            if previous.tag == f"{_W}p"
                            else _cell_text(previous)
                            if previous.tag == f"{_W}tbl"
                            else ""
                        )
                        previous_has_image = _has_visual_object(previous)
                        if not previous_text and not previous_has_image:
                            continue
                        has_image = previous_has_image
                        break
                if not has_image:
                    orphans.append(cap)
                break
        return orphans

    def _duplicate_body_image_relationships(self, root) -> list[str]:
        """Return image relationships duplicated inside one semantic section.

        docxcompose reuses one image part when the same source image is copied
        twice.  Reusing the relationship is correct when one source figure is
        deliberately projected into two different template responsibilities
        (for example the installation summary and the detailed interface
        subsection).  It is a regression only when the same relationship is
        emitted repeatedly under the same current heading.

        The heading key is derived from Word heading style/outline metadata and
        visible title text.  Displayed chapter numbers are stripped before
        comparison, so numbering changes do not alter the decision.
        """
        body = root.find(f".//{_W}body")
        if body is None:
            body = root

        def heading_key(paragraph) -> str:
            text = _para_text(paragraph)
            if not text:
                return ""
            ppr = paragraph.find(f"{_W}pPr")
            style = ""
            outline = False
            if ppr is not None:
                style_node = ppr.find(f"{_W}pStyle")
                if style_node is not None:
                    style = str(style_node.get(f"{_W}val") or "")
                outline = ppr.find(f"{_W}outlineLvl") is not None
            looks_like_heading = (
                outline
                or bool(re.search(r"(?:Heading|标题|目录)", style, re.I))
                # Many controlled Chinese templates name heading styles with
                # numeric IDs such as "2", "3" and "4".  A non-empty custom
                # style on a short top-level paragraph is therefore valid
                # heading evidence even when the localized style name is not
                # present in document.xml.
                or bool(style and len(text) <= 64)
                or bool(re.match(r"^\s*\d+(?:\.\d+)*\s+\S", text))
            )
            if not looks_like_heading:
                return ""
            return re.sub(
                r"^\s*(?:第\s*[一二三四五六七八九十百千万零〇]+\s*章\s*|"
                r"\d+(?:\.\d+)*(?:\s+|[、)）]))",
                "",
                text,
            ).strip(" ：:；;。")

        contexts: dict[str, list[str]] = {}
        current_heading = ""
        for child in list(body):
            if child.tag == f"{_W}p":
                key = heading_key(child)
                if key:
                    current_heading = key
            for relationship_id in _visual_relationship_ids(child):
                contexts.setdefault(relationship_id, []).append(current_heading)

        duplicates: list[str] = []
        for relationship_id, headings in contexts.items():
            if len(headings) < 2:
                continue
            # Empty heading is intentionally a shared context: repeated images
            # outside any controlled section remain a blocking defect.
            if len(set(headings)) < len(headings):
                duplicates.append(relationship_id)
        return sorted(duplicates)

    def _empty_or_stub_tables(self, root, headers: list[str]) -> list[str]:
        """
        检查标题关键词匹配到的表格是否是空表或仅有表头一行。
        headers: list of (heading_keyword, min_data_rows)  或  list of str（默认要求 >= 2 行数据）
        返回判定为空/存根的表名列表。
        """
        body = root.find(f".//{_W}body")
        if body is None:
            body = root
        children = list(body)
        stub_tables: list[str] = []

        for entry in headers:
            if isinstance(entry, dict):
                kw = entry.get("keyword", "")
                min_rows = int(entry.get("min_data_rows", 2))
            else:
                kw = entry
                min_rows = 2

            if not kw:
                continue

            for i, child in enumerate(children):
                if child.tag != f"{_W}tbl":
                    continue
                prev_txt = ""
                for j in range(i - 1, max(i - 6, -1), -1):
                    if children[j].tag == f"{_W}p":
                        prev_txt = _para_text(children[j])
                        if prev_txt:
                            break

                header_row_txt = ""
                rows = child.findall(f"{_W}tr")
                if rows:
                    header_row_txt = _cell_text(rows[0])

                if kw not in prev_txt and kw not in header_row_txt:
                    continue

                data_rows = [
                    r for r in rows[1:]
                    if "".join(t.text or "" for t in r.findall(f".//{_W}t")).strip()
                ]
                if len(data_rows) < min_rows:
                    stub_tables.append(kw)
                break

        return stub_tables

    def check(self, root) -> Dict[str, Any]:
        block_reasons: List[str] = []
        warnings: List[str] = []
        full_txt = self._full_text(root)
        br = self.block_rules
        wr = self.warn_rules

        unresolved_value_tokens = sorted(
            set(
                re.findall(
                    r"(?i)(?:\[\s*XXh\s*\]|（\s*XXh\s*）|\(\s*XXh\s*\)|\bXXh\b)",
                    full_txt,
                )
            )
        )
        if unresolved_value_tokens:
            block_reasons.append(
                "模板未决值占位符残留：" + ", ".join(unresolved_value_tokens)
            )

        red_count = self._count_red(root)
        hl_count = self._count_highlight(root)
        if br.get("red_text_count_gt", 0) == 0 and red_count > 0:
            block_reasons.append(f"残余红字 run 数：{red_count}")
        if br.get("highlight_count_gt", 0) == 0 and hl_count > 0:
            block_reasons.append(f"残余高亮数：{hl_count}")

        for phrase in br.get("template_phrases_exist", []):
            # ``XXh`` is already covered by the dedicated unresolved-value
            # rule above.  Keep the blocker, but do not report the same
            # underlying token again as a generic template phrase.
            if re.search(
                r"(?i)(?:\[\s*XXh\s*\]|\(\s*XXh\s*\)|\bXXh\b)",
                str(phrase),
            ):
                continue
            if phrase in full_txt:
                block_reasons.append(f"模板词残留：「{phrase}」")
        for phrase in self._contains_any_phrase(root, br.get("forbidden_phrases_exist", [])):
            block_reasons.append(f"跨项目/污染词残留：「{phrase}」")
        for phrase in self._missing_required_phrases(root, br.get("required_phrases_all", [])):
            block_reasons.append(f"关键内容缺失：「{phrase}」")
        for group in self._missing_phrase_groups(root, br.get("required_phrase_groups", [])):
            block_reasons.append(f"关键内容组缺失：[{group}]")
        for heading in self._missing_headings(root, br.get("required_headings", [])):
            block_reasons.append(f"关键章节缺失：「{heading}」")
        for fig in self._missing_figure_captions(root, br.get("required_figure_captions", [])):
            block_reasons.append(f"关键图题缺失：「{fig}」")
        missing_tbl_kws = set(self._missing_table_keywords(root, br.get("required_table_keywords", [])))
        for kw in missing_tbl_kws:
            block_reasons.append(f"关键表内容缺失：「{kw}」")

        # 结构级：图题有了但图片对象不在附近
        orphans = self._figure_caption_orphans(root, br.get("required_figure_captions", []))
        for cap in orphans:
            block_reasons.append(f"图题「{cap}」附近无图片对象（图题孤立）")

        # 结构级：空表/存根表检查（跳过整张表已缺失的关键词，避免重复报告）
        for kw in self._empty_or_stub_tables(root, br.get("required_table_headers", [])):
            if kw not in missing_tbl_kws:
                block_reasons.append(f"关键表「{kw}」为空表或仅有表头（数据行不足）")

        if br.get("as9100_table_exists") and not self.flags.get("is_as9100", False):
            if self._find_tables_with_header(root, "AS9100"):
                block_reasons.append("AS9100 相关表格残留（项目不适用）")

        if br.get("civil_aircraft_table_exists") and not self.flags.get("is_civil_aircraft", False):
            if self._find_tables_with_header(root, "民机"):
                block_reasons.append("民机进度表残留（项目不适用）")

        if br.get("appendix_a_empty_table_exists") and self._appendix_a_empty_table(root):
            block_reasons.append("附录A 存在大空表（应删除或写[本阶段不填写]）")

        cr_rows = self._change_record_data_rows(root)
        limit = br.get("change_record_data_rows_gt", 1)
        if cr_rows > limit:
            block_reasons.append(f"变更记录数据行 {cr_rows} > {limit}（只允许 A 版新发）")

        if br.get("indicator_table_missing") and not self._indicator_table_exists(root):
            block_reasons.append("技术指标表缺失")

        if br.get("indicator_table_no_basis_col") and self._indicator_table_exists(root):
            if not self._indicator_has_basis_col(root):
                block_reasons.append("技术指标表缺少[依据]列")

        if br.get("indicator_table_wrong_columns") and self._indicator_table_exists(root):
            if not self._indicator_has_expected_columns(root):
                block_reasons.append(
                    "技术指标表字段不完整：应包含项目、用户要求、拟采用指标和依据；"
                    "标准要求仅在模板原有该列时校验"
                )
            for defect in self._indicator_data_row_shape_defects(root):
                block_reasons.append(f"技术指标表数据行结构错位：{defect}")

        if br.get("indicator_instruction_exists"):
            for prompt in self._indicator_instruction_paragraphs(root):
                block_reasons.append(f"技术指标表上方残留模板提示：{prompt[:80]}")

        if br.get("indicator_change_record_contamination"):
            for text in self._indicator_change_record_contamination(root):
                block_reasons.append(f"技术指标值混入产品规范变更记录：{text[:80]}")

        if br.get("landscape_section_exists") and not self.flags.get("allow_landscape", False):
            landscape_count = self._landscape_sections(root)
            if landscape_count:
                block_reasons.append(f"输出仍包含横向页面节：{landscape_count} 处")

        if br.get("figure_caption_orphan_auto"):
            for cap in self._all_figure_caption_orphans(root):
                block_reasons.append(f"图题「{cap[:60]}」附近无图片对象（图题孤立）")

        if br.get("duplicate_body_image_relationship"):
            duplicates = self._duplicate_body_image_relationships(root)
            if duplicates:
                block_reasons.append(
                    "正文存在重复图片引用："
                    + ", ".join(duplicates[:20])
                )

        if br.get("figure_caption_sequence_wrong"):
            sequence = self._figure_caption_sequence_issues(root)
            if sequence:
                block_reasons.append(
                    "图题编号未按最终文档顺序连续排列：" + ", ".join(map(str, sequence))
                )

        if wr.get("standard_version_conflict") and self._standard_version_conflict(root):
            warnings.append("法规版本冲突：同一 GJB 编号存在 A/B 两版，请设计员确认")

        if wr.get("standard_sort_wrong"):
            if self._standard_order_issues(root):
                warnings.append("标准引用顺序与受控排序策略不一致，请人工确认")

        if wr.get("cover_phase_empty"):
            cover_txt = " ".join(_para_text(p) for p in root.findall(f".//{_W}p"))[:500]
            if "研制阶段" in cover_txt and not re.search(r"研制阶段[：:]\s*[FCSD]", cover_txt):
                warnings.append("封面研制阶段为空，请填写 F/C/S/D 其一")

        if wr.get("figure_caption_orphan"):
            orphan_warns = self._figure_caption_orphans(
                root, wr.get("figure_caption_orphan_list", [])
            )
            for cap in orphan_warns:
                warnings.append(f"图题「{cap}」附近未检测到图片，请确认")

        if wr.get("failure_mode_table_empty"):
            for tbl in root.findall(f".//{_W}tbl"):
                rows = tbl.findall(f"{_W}tr")
                if not rows:
                    continue
                h = _cell_text(rows[0])
                if "失效" in h or "故障" in h:
                    data_texts = [
                        "".join(t.text or "" for t in r.findall(f".//{_W}t")).strip()
                        for r in rows[1:]
                    ]
                    data_empty = all(not text for text in data_texts)
                    if data_empty:
                        warnings.append(
                            "失效模式表数据区为空：7-22要求无精确记录时写入“未查询到历史故障信息”"
                        )
                    break

        # ── 新增：[冲突] 字样阻断 ─────────────────────────────────────────────
        if "[冲突]" in full_txt:
            block_reasons.append("正式正文包含 [冲突] 标记，指标裁决未完成，不得交付")

        # ── 新增：孤立短段落警告（非标题、非列表、正文不足15字）────────────────
        # 只按“孤立量值”的通用形态检查，不写入任何样品型号或固定指标值。
        orphan_metric = re.compile(
            r"^(?:[≤≥<>+\-]?\s*)?\d+(?:\.\d+)?\s*"
            r"(?:V|mV|A|mA|Ω|mΩ|MΩ|N|℃|Hz|kHz|MHz|GHz|mm|cm|m|次|s|ms)\b",
            re.I,
        )
        # 收集表格内所有 <w:p> 元素，排除误报
        _tbl_paras: set = set()
        for tbl in root.findall(f".//{_W}tbl"):
            for tp in tbl.findall(f".//{_W}p"):
                _tbl_paras.add(id(tp))

        def _in_table(el):
            p = el.getparent()
            while p is not None:
                if p.tag == f"{_W}tbl":
                    return True
                p = p.getparent()
            return False

        orphan_count = 0
        for para in root.findall(f".//{_W}p"):
            if _in_table(para):
                continue
            txt = _para_text(para)
            ppr = para.find(f"{_W}pPr")
            sty = ""
            if ppr is not None:
                ps = ppr.find(f"{_W}pStyle")
                sty = ps.get(f"{_W}val", "") if ps is not None else ""
            if "Heading" in sty or "heading" in sty:
                continue
            if txt and orphan_metric.search(txt) and len(txt) < 100:
                orphan_count += 1
        if orphan_count > 0:
            warnings.append(f"检测到 {orphan_count} 处孤立指标片段（未落位字段），建议检查输出文档")

        return {
            "blocked": len(block_reasons) > 0,
            "block_reasons": block_reasons,
            "warnings": warnings,
            "red_count": red_count,
            "hl_count": hl_count,
        }
