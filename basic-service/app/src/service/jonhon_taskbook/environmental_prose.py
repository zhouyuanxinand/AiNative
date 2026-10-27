"""Project source-owned environmental requirements into plain paragraphs.

The chapter owns environmental requirements, not every metric in a table
that happens to contain one. Selection uses the row's subject before its
conditions; electrical tests at low pressure remain electrical requirements.
"""
from __future__ import annotations

import copy
import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


_ENVIRONMENT = re.compile(
    r"(?:工作|环境|使用|贮存|储存|存储|运输|运行)温度|温度范围|高低温|高温|低温|"
    r"温度冲击|温度循环|热冲击|湿热|湿度|盐雾|腐蚀|霉菌|淋雨|浸水|防水|防尘|"
    r"防护等级|沙尘|砂尘|振动|振荡|冲击|加速度|过载|低气压|海拔|高原|"
    r"海洋环境|工业(?:干扰)?环境|电磁环境|气候|太阳辐射|耐候|老化|"
    r"环境稳定性|环境适配|环境适应性|环境条件|环境性能|环境试验|环境指标"
)
_OTHER_SUBJECT = re.compile(
    r"^(?:产品)?(?:工作电压|额定电压|工作电流|额定电流|接触电阻|绝缘电阻|"
    r"介质耐电压|耐电压|介质耐压|电气强度|冲击电流|冲击电压|电气过载|电流过载|功率过载|电容|电感|插入损耗|回波损耗|"
    r"机械寿命|电气寿命|插拔寿命|寿命|可靠性|MTBF|长期通电|插拔力|分离力|"
    r"插入力|锁紧力|接触件|尺寸|重量|质量|工作频率|频率范围|工作压力)"
)
_BULLET = re.compile(r"^\s*(?:(?:[（(][a-zA-Z\d一二三四五六七八九十]+[）)]|"
                     r"[a-zA-Z\d]+[)）、]|[a-zA-Z]\.\s*|\d+(?:\.\d+)*[.、]?\s+|[•●▪])\s*)")
_HEADERS = {"项目", "项目名称", "指标项目", "性能项目", "指标名称", "参数名称", "试验项目", "检验项目", "名称", "技术特性类型"}
_GENERIC = {"环境适应性", "环境适应性要求", "环境条件", "环境性能", "环境指标", "环境要求", "技术指标", "技术要求", "性能要求"}
_DETAIL_LABEL = re.compile(
    r"^(?:试验|测试|考核|验收|评价|温度|时间|持续|频率(?:范围)?|幅值|振幅|峰值|"
    r"加速度|波形|条件|要求|指标|性能指标|判据|耐受阈值|阈值|约束条件|适配约束|环境适配约束|"
    r"安装约束|运行约束|贮存约束|储存约束|运输约束|适用条件|施加方向|循环次数|"
    r"升降温速率|恢复条件|恢复时间|污染等级)"
)
_CONTEXT_HEADER = re.compile(
    r"^(?:(?:试验|测试|考核|验收|评价)(?:要求|条件|方法|依据|标准|判据|程序|时间|时长|次数|方向)|"
    r"耐受阈值|阈值|约束条件|(?:环境)?适配约束(?:条件)?|安装约束|运行约束|贮存约束|"
    r"储存约束|运输约束|适用条件|施加方向|频率范围|加速度|循环次数|持续时间|升降温速率|恢复条件|恢复时间)$"
)


def is_environmental_slot(slot: dict | None) -> bool:
    slot = slot or {}
    if slot.get("target_role") == "environmental_adaptability" or slot.get("category") == "environmental_adaptability":
        return True
    return any("环境适应性" in str(slot.get(key) or "") for key in ("title", "heading"))


def _clean(text: str) -> str:
    return _BULLET.sub("", str(text or "")).strip()


def _environment_subject(text: str) -> bool:
    clean = _clean(text)
    return bool(_ENVIRONMENT.search(clean) and not _OTHER_SUBJECT.match(clean))


def _paragraph_spans(text: str, *, environmental_context: bool = False, other_subject_context: bool = False) -> list[tuple[int, int]]:
    """Keep environmental clauses and their unlabelled continuation criteria."""
    boundaries = [0]
    for separator in re.finditer(r"[；;。\n]|[，,](?=\s*[^，,；;。\n]{1,24}[：:])", text):
        boundaries.append(separator.end())
    boundaries.append(len(text))
    selected: list[tuple[int, int]] = []
    active = environmental_context
    other_subject = other_subject_context
    for start, end in zip(boundaries, boundaries[1:]):
        clause = _clean(text[start:end])
        if not clause:
            continue
        label = re.match(r"^([^：:]{1,24})[：:]", clause)
        detail_label = _DETAIL_LABEL.match(label.group(1) if label else clause)
        other_label = bool(label and not _environment_subject(label.group(1)) and not detail_label)
        if active and detail_label:
            # Thresholds, assessment criteria and constraints belong to the
            # selected environmental trial, including its frequency range.
            pass
        elif other_subject and detail_label and not _environment_subject(label.group(1) if label else ""):
            active = False
        elif _OTHER_SUBJECT.match(clause):
            active = False
            other_subject = True
        elif other_label:
            active = False
            other_subject = True
        elif _environment_subject(clause):
            # A semicolon may introduce an alternate electrical test condition,
            # not a second environmental requirement: 耐电压...；低气压：150 V.
            electrical_condition = bool(
                other_subject
                and re.match(r"^(?:低气压|常温|常压|高温|低温|湿热|盐雾后)", clause)
                and not re.match(r"^(?:低气压|高温|低温|湿热)(?:试验|要求|适应性)", clause)
                and re.search(r"\d\s*(?:[kKmMμµu]?[VAΩΩ]|[kKmM]?欧姆)|耐电压|绝缘电阻|接触电阻", clause)
            )
            active = not electrical_condition
            if active:
                other_subject = False
        if active:
            if selected and selected[-1][1] == start:
                selected[-1] = (selected[-1][0], end)
            else:
                selected.append((start, end))
    return selected


def _table_rows(block: dict, source_element) -> list[list[str]]:
    if source_element is None:
        embedded = block.get("table_rows")
        if isinstance(embedded, (list, tuple)):
            return [[str(cell or "") for cell in row] for row in embedded]
        path, index = block.get("source_path"), block.get("body_index")
        if not path or not isinstance(index, int):
            return []
        from docx import Document
        document = Document(path)
        source_element = document.element.body[index]
    if source_element.tag != qn("w:tbl"):
        return []
    # Expand Word's merged cells so vertically merged row subjects apply to
    # every continuation while retaining the original logical coordinates.
    from docx.table import Table
    return [["\n".join(p.text for p in cell.paragraphs).strip() for cell in row.cells]
            for row in Table(source_element, None).rows]


def project_environmental_evidence(block: dict, source_element=None) -> list[dict]:
    """Return exact source fragments plus permitted prose punctuation.

    No values come from specifications, templates or generated narration.
    Coordinates identify paragraphs or source cells for independent auditing.
    """
    if block.get("source", "tech") != "tech":
        return []
    heading_context = " / ".join([*map(str, block.get("parent_headings") or []),
                                   str(block.get("heading_text") or block.get("section") or "")])
    if re.search(r"引用标准|引用文件|编制依据|参考文献|适用法律法规|规范性引用", heading_context):
        return []
    if source_element is None and block.get("source_path") and isinstance(block.get("body_index"), int):
        from docx import Document
        document = Document(block["source_path"])
        source_element = document.element.body[block["body_index"]]
    result: list[dict] = []

    def append(text, fragments, coordinates):
        clean = _clean(text)
        if not clean:
            return
        result.append({
            "text": clean, "source_id": str(block.get("id") or ""),
            "source_fragments": fragments,
            "source_coordinates": {"body_index": block.get("body_index"), **coordinates},
            "policy": "environmental_prose",
        })

    if block.get("type") != "table":
        text = str(block.get("text") or "")
        if source_element is not None:
            original = "".join(node.text or "" for node in source_element.iter(qn("w:t"))).strip()
            if block.get("is_fragment"):
                start, end = int(block.get("source_span_start", -1)), int(block.get("source_span_end", -1))
                if start < 0 or end <= start or original[start:end] != text:
                    raise ValueError("environmental fragment does not match its original source span")
            else:
                # The original XML owns values. Cached classification text is
                # metadata and cannot override a value while retaining its hash.
                text = original
        heading = str(block.get("heading_text") or block.get("section") or "")
        for start, end in _paragraph_spans(
            text, environmental_context=_environment_subject(heading),
            other_subject_context=bool(_OTHER_SUBJECT.match(_clean(heading))),
        ):
            raw = text[start:end]
            offset = int(block.get("source_span_start", 0)) if block.get("is_fragment") else 0
            append(raw, [raw], {"start": offset + start, "end": offset + end})
        return result

    rows = _table_rows(block, source_element)
    label_columns = sorted({column for row in rows[:4] for column, cell in enumerate(row)
                            if re.sub(r"\s+", "", cell) in _HEADERS})
    context_headers = {
        column: {"text": cell.strip(), "table_row": row_index, "column": column}
        for row_index, row in enumerate(rows[:4])
        if any(re.sub(r"\s+", "", cell) in _HEADERS for cell in row)
        for column, cell in enumerate(row)
        if _CONTEXT_HEADER.fullmatch(re.sub(r"\s+", "", cell))
    }
    for row_index, row in enumerate(rows):
        if any(re.sub(r"\s+", "", cell) in _HEADERS for cell in row):
            continue
        subjects = label_columns or [next((i for i, cell in enumerate(row)
                                          if cell.strip() and not re.fullmatch(r"\d+[)）.]?", cell.strip())), 0)]
        for column in subjects:
            if column >= len(row):
                continue
            label = _clean(row[column]).strip("：:；;。")
            if not _environment_subject(label):
                continue
            next_column = next((col for col in subjects if col > column), len(row))
            value_cells = [(i, row[i]) for i in range(column + 1, next_column) if row[i].strip()]
            if not value_cells:
                continue
            fragments, values, selected_columns, selected_headers = [row[column]], [], [], []
            seen_values = set()
            for cell_column, value in value_cells:
                header = context_headers.get(cell_column)
                # A dedicated assessment/threshold/condition column belongs to
                # this environmental row even when its acceptance criterion is
                # an electrical measurement (e.g. resistance after salt spray).
                spans = ([(0, len(value))] if header and label not in _GENERIC
                         else _paragraph_spans(value, environmental_context=label not in _GENERIC))
                for start, end in spans:
                    fragment = value[start:end].strip()
                    header_text = header["text"] if header else ""
                    key = (header_text, fragment)
                    if fragment and key not in seen_values:
                        seen_values.add(key)
                        display = fragment
                        if header_text and not re.match(re.escape(header_text) + r"[：:]", fragment):
                            display = header_text + "：" + fragment
                        values.append(display)
                        fragments.append(value[start:end])
                        selected_columns.append(cell_column)
                        if header and header not in selected_headers:
                            selected_headers.append(header)
            if values:
                text = label + "：" + "；".join(value.rstrip("；;。") for value in values) + "。"
                append(text, fragments, {"table_row": row_index, "label_column": column,
                                         "value_columns": selected_columns})
                if selected_headers:
                    result[-1]["source_headers"] = selected_headers
    return result


def _source_character_alignments(element, *, cell: bool = False) -> tuple[str, list[str | None]]:
    """Keep source superscript/subscript positions without changing characters."""
    paragraphs = element.findall(qn("w:p")) if cell else [element]
    characters, alignments = [], []
    for paragraph_index, paragraph in enumerate(paragraphs):
        if paragraph_index:
            characters.append("\n")
            alignments.append(None)
        for run in paragraph.iter(qn("w:r")):
            position = run.find(f"{qn('w:rPr')}/{qn('w:vertAlign')}")
            alignment = position.get(qn("w:val")) if position is not None else None
            for node in run.iter():
                value = node.text or "" if node.tag == qn("w:t") else ""
                if cell and node.tag in {qn("w:br"), qn("w:cr"), qn("w:tab")}:
                    value = "\t" if node.tag == qn("w:tab") else "\n"
                characters.extend(value)
                alignments.extend([alignment] * len(value))
    return "".join(characters), alignments


def _projection_character_alignments(projection: dict, source_element) -> list[str | None]:
    alignments: list[str | None] = [None] * len(projection["text"])
    if source_element is None:
        return alignments
    fragments = projection.get("source_fragments") or []
    coordinate = projection["source_coordinates"]
    if source_element.tag == qn("w:tbl"):
        from docx.table import Table
        row = Table(source_element, None).rows[coordinate["table_row"]]
        columns = [coordinate["label_column"], *coordinate["value_columns"]]
        sources = [_source_character_alignments(row.cells[column]._tc, cell=True) for column in columns]
    else:
        sources = [_source_character_alignments(source_element)]
    output_cursor = 0
    for fragment, (source_text, source_alignments) in zip(fragments, sources):
        display_text = _clean(fragment).rstrip("：:；;。")
        if not display_text:
            continue
        source_offset = source_text.find(display_text)
        output_offset = projection["text"].find(display_text, output_cursor)
        if source_offset < 0 or output_offset < 0:
            continue
        end = output_offset + len(display_text)
        alignments[output_offset:end] = source_alignments[source_offset:source_offset + len(display_text)]
        output_cursor = end
    return alignments


def environmental_paragraph(projection: dict, block: dict, source_element=None, *, preserve_formatting=True):
    """Reuse full paragraph formatting when possible, with no list identity."""
    if (preserve_formatting and source_element is not None and source_element.tag == qn("w:p")
            and projection["text"] == str(block.get("text") or "")
            and not block.get("is_fragment") and not block.get("has_drawing")):
        paragraph = copy.deepcopy(source_element)
        properties = paragraph.find(qn("w:pPr"))
        if properties is not None:
            for name in ("numPr", "outlineLvl", "pStyle"):
                for node in properties.findall(qn("w:" + name)):
                    properties.remove(node)
        return paragraph
    paragraph = OxmlElement("w:p")
    alignments = _projection_character_alignments(projection, source_element)
    start = 0
    while start < len(projection["text"]):
        end = start + 1
        while end < len(alignments) and alignments[end] == alignments[start]:
            end += 1
        run = OxmlElement("w:r")
        if alignments[start] in {"superscript", "subscript"}:
            properties = OxmlElement("w:rPr")
            alignment = OxmlElement("w:vertAlign")
            alignment.set(qn("w:val"), alignments[start])
            properties.append(alignment)
            run.append(properties)
        text = OxmlElement("w:t")
        text.text = projection["text"][start:end]
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        run.append(text)
        paragraph.append(run)
        start = end
    return paragraph
