"""按标题树和表格语义抽取产品规范指标，不依赖章节号或章节顺序。"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field

from lxml import etree

from .docx_io import get_cell_text, get_para_text

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


SPEC_DENIED_ITEM_PATTERNS = re.compile(
    r"^(\d+组|[0-9]{1,2}|[A-Z]$|产品规范|检验项目|检验顺序|要求条款|试验方法条款)",
    re.IGNORECASE,
)
_DENIED_CONTEXT_WORDS = {
    "变更记录",
    "目录",
    "前言",
    "发放",
    "型号命名",
    "检验项目和顺序",
    "检验分组",
    "规范性引用",
    "术语定义",
    "包装标志",
    "封面",
}
_INDICATOR_CONTEXT_WORDS = {
    "性能",
    "指标",
    "电气",
    "机械",
    "环境",
    "可靠",
    "维修",
    "保障",
    "测试性",
    "电压",
    "电流",
    "电阻",
    "耐压",
    "温度",
    "振动",
    "冲击",
    "加速度",
    "盐雾",
    "霉菌",
    "寿命",
    "插拔",
    "按压力",
    "弹力",
    "互换",
    "安全",
}
_TABLE_HEADER_WORDS = {
    "项目",
    "指标",
    "要求",
    "规格",
    "电压",
    "电流",
    "电阻",
    "温度",
    "时间",
    "频率",
    "方向",
    "插入力",
    "分离力",
    "加载方向",
}
_CHANGE_RECORD_HEADER_WORDS = {
    "版本",
    "章条编号",
    "改前内容",
    "改后内容",
    "日期",
}


@dataclass
class SpecRequirementItem:
    item_name: str
    standard_text: str
    source_section: str = ""
    table_caption: str = ""
    applicable_model: str = ""
    category_or_series: str = ""
    spec: str = ""
    test_method: str = ""
    condition: str = ""
    raw_row: dict = field(default_factory=dict)
    # 三者只记录源表语义；提取阶段不选择档位、不把 typ 改成保证值。
    value_kind: str = ""
    qualifiers: dict[str, str] = field(default_factory=dict)
    unit: str = ""
    excluded_models: tuple[str, ...] = ()


def _norm_header(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _semantic_title(value: str) -> str:
    return re.sub(r"^\s*\d+(?:\.\d+)*\s*", "", value or "").strip()


def _paragraph_style(element) -> str:
    ppr = element.find(f"{{{W}}}pPr")
    style = ppr.find(f"{{{W}}}pStyle") if ppr is not None else None
    return style.get(f"{{{W}}}val", "") if style is not None else ""


def _is_heading(element) -> bool:
    if element.tag != f"{{{W}}}p":
        return False
    style = _paragraph_style(element)
    if re.match(r"^[1-9]$|^[Hh]eading", style):
        return True
    text = get_para_text(element).strip()
    return bool(
        text
        and len(text) <= 100
        and re.match(r"^\d+(?:\.\d+)*\s+[\u4e00-\u9fffA-Za-z]", text)
    )


def _heading_level(element) -> int:
    style = _paragraph_style(element)
    match = re.search(r"(?:Heading|heading)?\s*([1-9])$", style)
    if match:
        return int(match.group(1))
    number = re.match(r"^(\d+(?:\.\d+)*)\s+", get_para_text(element).strip())
    return number.group(1).count(".") + 1 if number else 1


def _series_from_row(row_dict: dict) -> str:
    # 受控产品规范的适用范围列没有统一表头。保留完整的范围文本，供
    # 后续型号/系列匹配器作保守裁决，不能只识别“系列”这一种写法。
    priority = (
        "系列 / 型号 / 类别",
        "型号/系列",
        "型号（系列）",
        "适用型号",
        "产品型号",
        "适用系列",
        "产品系列",
        "适用产品",
        "适用范围",
        "系列",
        "型号",
        "类别",
        "产品类别",
    )
    normalized = {
        _norm_header(str(key)): str(value or "").strip()
        for key, value in row_dict.items()
    }
    for key in priority:
        value = normalized.get(_norm_header(key), "")
        if value:
            return value
    return ""


def _test_method_from_row(row_dict: dict) -> str:
    """提取独立的试验方法列，避免在结构化台账中静默丢失。"""
    method_markers = ("试验方法", "检验方法", "检测方法", "测试方法", "方法条款")
    for key, value in row_dict.items():
        header = _norm_header(str(key))
        method = str(value or "").strip()
        if method and any(marker in header for marker in method_markers):
            return method
    return ""


_BOUND_PATTERN = re.compile(
    r"(?<![A-Za-z])(?P<en>minimum|typical|maximum|min|typ|max)(?![A-Za-z])"
    r"|(?P<cn>最小值?|典型值?|最大值?)",
    re.IGNORECASE,
)
_NAME_HEADERS = {
    "项目",
    "指标",
    "指标名称",
    "项目名称",
    "试验项目",
    "性能项目",
    "参数",
    "参数名称",
}
_VALUE_HEADERS = {
    "值",
    "数值",
    "指标值",
    "要求",
    "技术要求",
    "标准要求",
    "规范要求",
    "规定",
    "规定值",
    "试验标准/要求",
    "性能指标",
}
_QUALIFIER_MARKERS = (
    "规格",
    "档位",
    "壳体号",
    "位数",
    "芯数",
    "孔数",
    "接触件号",
    "接触件尺寸",
    "接触件直径",
    "线规",
    "AWG",
    "针径",
)
_MODEL_MARKERS = ("型号", "系列", "类别", "适用产品", "适用范围")
_CONDITION_MARKERS = (
    "条件",
    "工作环境",
    "测试温度",
    "试验温度",
    "环境温度",
    "试验状态",
    "测试状态",
    "试验阶段",
    "测试阶段",
    "大气压",
    "DC/AC",
    "加载方向",
)
_CONDITION_PARAMETERS = {
    "温度",
    "湿度",
    "频率",
    "测试时间",
    "试验时间",
    "持续时间",
    "试验电压",
    "漏电流",
    "漏电流值",
    "方向",
}
_GENERIC_TITLES = {
    "电性能",
    "电气性能",
    "机械性能",
    "环境性能",
    "技术要求",
    "技术指标",
    "性能要求",
    "（前置区域）",
}
_CONDITION_ATOM = r"(?:常温|室温|高温|低温|标准(?:条件|大气压)?|试验前|试验后|初始|[+-]?\d+(?:\.\d+)?\s*(?:℃|°C))"
_CONDITION_TEXT = re.compile(rf"{_CONDITION_ATOM}(?:[、，,；;\s]+{_CONDITION_ATOM})*")
_UNIT_PATTERN = re.compile(
    r"(?:[GMkmunpμµ]?Ω|[GMkmunpμµ]?(?:Hz|Pa|V|A|F|H|W)|[kmunμµ]?(?:m|s|g)|"
    r"℃|°C|°F|N(?:[·.]m)?|dB|%|次|年|h|mm²|mm2)(?:[²³23])?"
)


def _value_kind(value: str) -> str:
    match = _BOUND_PATTERN.search(value)
    if not match:
        return ""
    token = match.group(0).lower()
    return (
        "min"
        if token.startswith(("min", "最小"))
        else "max"
        if token.startswith(("max", "最大"))
        else "typ"
    )


def _header_unit(heading: str) -> str:
    for candidate in re.findall(r"[（(\[]([^）)\]]+)[）)\]]", heading):
        if _UNIT_PATTERN.fullmatch(candidate.strip()):
            return candidate.strip()
    slash_unit = re.search(r"[/／]\s*([^/／]+)$", heading)
    if slash_unit and _UNIT_PATTERN.fullmatch(slash_unit.group(1).strip()):
        return slash_unit.group(1).strip()
    # Controlled Word tables often put the unit on another line in the same
    # cell: “接触电阻\nΩ”, “接触件规格\nmm”.  The matrix compacts that text;
    # retain its unit rather than turning the size column into a measurement.
    trailing = re.search(r"(?<=[\u4e00-\u9fff])(" + _UNIT_PATTERN.pattern + r")$", heading.strip())
    if trailing:
        return trailing.group(1)
    return heading.strip() if _UNIT_PATTERN.fullmatch(heading.strip()) else ""


def _metric_header(heading: str) -> str:
    unit = _header_unit(heading)
    heading = _BOUND_PATTERN.sub("", heading)
    heading = re.sub(
        r"[（(\[]([^）)\]]*)[）)\]]",
        lambda match: (
            ""
            if not match.group(1).strip()
            or _UNIT_PATTERN.fullmatch(match.group(1).strip())
            else match.group(0)
        ),
        heading,
    )
    if unit:
        heading = re.sub(r"(?:[/／]\s*)?" + re.escape(unit) + r"$", "", heading)
    return heading.strip(" /／：:")


def _header_role(heading: str) -> str:
    value = _norm_header(heading)
    metric = _metric_header(value)
    if metric in _NAME_HEADERS:
        return "name"
    if any(marker.lower() in value.lower() for marker in _QUALIFIER_MARKERS):
        return "qualifier"
    if any(marker in value for marker in _MODEL_MARKERS):
        return "model"
    if any(
        marker in value
        for marker in ("试验方法", "检验方法", "检测方法", "测试方法", "方法条款")
    ):
        return "method"
    if any(marker in value for marker in _CONDITION_MARKERS):
        return "condition"
    if any(marker in value for marker in ("备注", "说明")):
        return "note"
    if _value_kind(value) or metric in _VALUE_HEADERS or metric == "指标":
        return "value"
    if value in {"序号", "序", "单位"}:
        return "metadata"
    return "other"


def _column_scope(heading: str) -> tuple[dict[str, str], str, str]:
    """只识别有显式语义的并列列头，不猜测任意首列或数字属于哪个型号。"""
    pieces = [part.strip() for part in heading.split(" / ") if part.strip()]
    qualifiers: dict[str, str] = {}
    model, condition = "", ""
    for piece in pieces:
        piece = _metric_header(piece) if _header_unit(piece) else piece
        if re.fullmatch(r"#\s*\d+[A-Za-z]*", piece):
            qualifiers["接触件规格"] = piece
        elif re.fullmatch(r"(?:AWG\s*#?\s*\d+|#?\s*\d+\s*AWG)", piece, re.IGNORECASE):
            qualifiers["线规"] = piece
        elif re.match(r"^(?:壳体号|位数|芯数|接触件规格|档位)\s*[:：]?\s*\S+", piece):
            key = re.match(r"^(?:壳体号|位数|芯数|接触件规格|档位)", piece).group(0)
            qualifiers[key] = piece[len(key) :].strip(" :：")
        elif _CONDITION_TEXT.fullmatch(piece):
            condition = "；".join(part for part in (condition, piece) if part)
        elif re.fullmatch(
            r"(?:型号\s*[:：]?\s*\S+|[A-Z][A-Z0-9._/-]*\d[A-Z0-9._/-]*|[A-Z0-9]+型)",
            piece,
        ):
            model = re.sub(r"^型号\s*[:：]?\s*", "", piece)
    return qualifiers, model, condition


def _table_headers(matrix: list[list[str]]) -> tuple[list[str], int]:
    header = list(matrix[0])
    depth = 1
    # 多层表头以明确字段名、min/typ/max 或同一层档位列为依据；绝不靠章节号。
    for row in matrix[1:3]:
        nonempty = [cell for cell in row if cell]
        if not nonempty:
            break
        known = [
            _header_role(cell)
            in {
                "name",
                "value",
                "qualifier",
                "model",
                "condition",
                "method",
                "metadata",
                "note",
            }
            or any(_column_scope(cell))
            for cell in nonempty
        ]
        if not all(known):
            break
        # 数据行中的 #22D + 5 不符合此条件；min/typ/max 的第二层才并入表头。
        if not any(
            _value_kind(cell) or _header_role(cell) in {"name", "value"}
            for cell in nonempty
        ):
            break
        width = max(len(header), len(row))
        header += [""] * (width - len(header))
        for index, value in enumerate(row):
            if value and value != header[index]:
                header[index] = " / ".join(
                    part for part in (header[index], value) if part
                )
        depth += 1
    return header, depth


def _value_parts(value: str, heading: str) -> list[tuple[str, str]]:
    """单格中的 typ/max 也是不同候选；原格留在 raw_row。"""
    bounds = list(_BOUND_PATTERN.finditer(value))
    if not bounds:
        return [(_value_kind(heading), value)]
    # 只有标签前无指标正文时才切开，避免截断‘不得超过最大值……’的文字要求。
    if value[: bounds[0].start()].strip(" ，,；;：:"):
        return [(_value_kind(heading), value)]
    result = []
    for index, match in enumerate(bounds):
        end = bounds[index + 1].start() if index + 1 < len(bounds) else len(value)
        part = value[match.end() : end].strip(" ，,；;：:")
        if part:
            result.append((_value_kind(match.group(0)), part))
    return result


def _matches_metric(heading: str, item_name: str) -> bool:
    aliases = {
        "额定电压": ("电压",),
        "工作电压": ("电压",),
        "额定电流": ("电流",),
        "工作电流": ("电流",),
        "介质耐电压": ("电压",),
        "机械寿命": ("寿命",),
        "工作温度": ("温度",),
        "接触件弹力": ("单芯弹力", "弹力"),
        "接触件插入力和分离力": ("插入力", "分离力"),
        "插拔力": ("插入力", "拔出力"),
    }
    return _norm_header(_metric_header(heading)) in {
        _norm_header(item_name),
        *aliases.get(item_name, ()),
    }


def _condition_column(heading: str, item_name: str) -> bool:
    return not _matches_metric(heading, item_name) and (
        _header_role(heading) == "condition"
        or _metric_header(heading) in _CONDITION_PARAMETERS
    )


def _context_metric(context: dict) -> tuple[str, str]:
    metric = ""
    conditions = []
    for title in context["semantic_path"].split(" / "):
        if _CONDITION_TEXT.fullmatch(title):
            conditions.append(title)
            continue
        for parenthesized in re.findall(r"[（(]([^）)]+)[）)]", title):
            if _CONDITION_TEXT.fullmatch(parenthesized):
                conditions.append(parenthesized)
                title = re.sub(
                    r"[（(]" + re.escape(parenthesized) + r"[）)]", "", title
                )
        candidate = _metric_header(title)
        if candidate not in _GENERIC_TITLES and any(
            word in candidate for word in _INDICATOR_CONTEXT_WORDS
        ):
            metric = candidate
    return metric or context["title"], "；".join(dict.fromkeys(conditions))


def _item_allowed(item_name: str) -> bool:
    name = (item_name or "").strip()
    if not name or name in {"项目", "指标", "序号", "系列", "型号", "要求", "规定"}:
        return False
    return not bool(SPEC_DENIED_ITEM_PATTERNS.match(name))


def _iter_tables_with_context(root) -> list[dict]:
    """按 DOCX body 顺序为每张表绑定无编号标题路径。"""
    body = root.find(f"{{{W}}}body")
    if body is None:
        body = root
    stack: list[tuple[int, str]] = []
    last_caption = ""
    tables: list[dict] = []
    section_text: list[str] = []
    section_tables: list[dict] = []
    for body_index, child in enumerate(body):
        if child.tag == f"{{{W}}}p":
            text = get_para_text(child).strip()
            if not text:
                continue
            if _is_heading(child):
                level = _heading_level(child)
                title = _semantic_title(text)
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                last_caption = ""
                section_text = []
                section_tables = []
            elif re.match(r"^表\s*\d+", text):
                last_caption = text
            else:
                section_text.append(text)
                for table_context in section_tables:
                    table_context["nearby_text"] = "\n".join(section_text)
        elif child.tag == f"{{{W}}}tbl":
            titles = [title for _, title in stack]
            tables.append(
                {
                    "element": child,
                    "body_index": body_index,
                    "title": titles[-1] if titles else "（前置区域）",
                    "semantic_path": " / ".join(titles) if titles else "（前置区域）",
                    "caption": last_caption,
                    "nearby_text": "\n".join(section_text),
                }
            )
            section_tables.append(tables[-1])
            last_caption = ""
    return tables


def _matrix(rows) -> list[list[str]]:
    """展开 Word 合并单元格，保持多层表头和纵向合并的档位所在列。"""
    matrix: list[list[str]] = []
    previous: list[str] = []
    for row in rows:
        values: list[str] = []
        row_properties = row.find(f"{{{W}}}trPr")
        before = (
            row_properties.find(f"{{{W}}}gridBefore")
            if row_properties is not None
            else None
        )
        if before is not None:
            values.extend([""] * int(before.get(f"{{{W}}}val", "0")))
        for cell in row.findall(f"{{{W}}}tc"):
            properties = cell.find(f"{{{W}}}tcPr")
            span = (
                properties.find(f"{{{W}}}gridSpan") if properties is not None else None
            )
            merge = (
                properties.find(f"{{{W}}}vMerge") if properties is not None else None
            )
            width = int(span.get(f"{{{W}}}val", "1")) if span is not None else 1
            text = get_cell_text(cell).strip()
            continuing = (
                merge is not None and merge.get(f"{{{W}}}val", "continue") == "continue"
            )
            for _ in range(width):
                column = len(values)
                values.append(
                    previous[column] if continuing and column < len(previous) else text
                )
        matrix.append(values)
        previous = values
    return matrix


def _matrix_text(matrix: list[list[str]]) -> str:
    rendered = []
    for row in matrix:
        values = list(dict.fromkeys(value for value in row if value))
        if values:
            rendered.append(
                "：".join(values) if len(values) == 2 else "、".join(values)
            )
    return "；".join(dict.fromkeys(rendered))


def _context_allows_table(context: dict, matrix: list[list[str]]) -> bool:
    path = context["semantic_path"]
    table_text = _matrix_text(matrix)
    if any(word in path for word in _DENIED_CONTEXT_WORDS):
        return False
    header_text = "".join(matrix[0]) if matrix else ""
    # 变更记录可能位于封面后的“前置区域”，没有可用标题路径；其中常会提到
    # 振动、冲击、寿命等指标名。必须先按表头结构排除，不能把整张变更表
    # 误当成某个性能指标的标准要求。
    if sum(word in header_text for word in _CHANGE_RECORD_HEADER_WORDS) >= 2:
        return False
    title_signal = any(word in path for word in _INDICATOR_CONTEXT_WORDS)
    header_signal = bool(matrix) and any(
        word in header_text for word in _TABLE_HEADER_WORDS
    )
    row_signal = any(row and _item_allowed(row[0]) for row in matrix[1:])
    # 性能标题、指标表头或可解析指标行任一成立即可；禁止用章节号决定。
    return bool(
        title_signal or (header_signal and row_signal) or "随机振动" in table_text
    )


def _nearby_qualifier(full_text: str, keyword: str) -> str:
    """从原文提取包含关键词的完整短句，不写死任何型号或数值。"""
    pattern = (
        rf"[^。；\n]{{0,80}}{re.escape(keyword)}[^。；\n]{{0,160}}"
        rf"(?:。[^。；\n]{{0,160}})?"
    )
    match = re.search(pattern, full_text, re.IGNORECASE)
    return match.group(0).strip(" ，,：:") if match else ""


def _special_matrix_items(
    context: dict, matrix: list[list[str]]
) -> list[SpecRequirementItem]:
    if any(_norm_header(value) in _NAME_HEADERS for value in matrix[0]):
        # “项目 | 条件 | 要求”即使含随机振动，也应逐行保留条件与指标。
        return []
    table_text = _matrix_text(matrix)
    title = context["title"]
    item_name = ""
    if "随机振动" in table_text or "振动" in title and "功率谱密度" in table_text:
        item_name = "振动"
    elif "冲击谱值" in table_text or "冲击" in title and "冲击次数" in table_text:
        item_name = "冲击"
    elif "加载方向" in table_text and "纵向" in table_text and "横向" in table_text:
        item_name = "加速度"
    if not item_name:
        return []
    groups: dict[str, list[list[str]]] = {}
    condition_columns = [
        index
        for index, heading in enumerate(matrix[0])
        if "条件" in heading or "等级" in heading
    ]
    for row in matrix[1:]:
        condition = "；".join(
            f"{matrix[0][index]}：{row[index]}"
            for index in condition_columns
            if index < len(row) and row[index]
        )
        groups.setdefault(condition, []).append(row)
    items = []
    _, heading_condition = _context_metric(context)
    for condition, rows in groups.items():
        group_matrix = [matrix[0], *rows]
        parts = [_matrix_text(group_matrix)]
        if item_name == "振动":
            qualifier = _nearby_qualifier(context.get("nearby_text", ""), "配重")
            if qualifier and qualifier not in parts[0]:
                parts.append(qualifier)
        items.append(
            SpecRequirementItem(
                item_name=item_name,
                standard_text="；".join(part for part in parts if part),
                spec="；".join(part for part in parts if part),
                condition="；".join(
                    part for part in (heading_condition, condition) if part
                ),
                source_section=context["semantic_path"],
                table_caption=context["caption"] or f"{item_name}试验条件",
                raw_row={"matrix": group_matrix, "body_index": context["body_index"]},
            )
        )
    return items


def extract_spec_chapter3_tables(
    spec_path: str,
    product_name: str | None = None,
) -> list[SpecRequirementItem]:
    """抽取产品规范指标表；`product_name` 仅为兼容旧调用，不参与定位。"""
    del product_name
    with zipfile.ZipFile(spec_path, "r") as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    items: list[SpecRequirementItem] = []

    for context in _iter_tables_with_context(root):
        table = context["element"]
        rows = table.findall(f"{{{W}}}tr")
        if len(rows) < 2:
            continue
        matrix = _matrix(rows)
        if not _context_allows_table(context, matrix):
            continue
        special = _special_matrix_items(context, matrix)
        if special:
            items.extend(special)
            continue

        header, header_depth = _table_headers(matrix)
        if not header or not any(header):
            continue
        name_columns = [
            index
            for index, heading in enumerate(header)
            if _header_role(heading) == "name"
        ]
        # “项目 | 指标”中“指标”是值；有“项目”时先按显式项目列取名称。
        name_index = next(
            (index for index in name_columns if _norm_header(header[index]) == "项目"),
            name_columns[0] if name_columns else None,
        )
        for row_index, values in enumerate(matrix[header_depth:], start=header_depth):
            if not any(values):
                continue
            row_dict = {
                header[index] if index < len(header) else f"col{index}": values[index]
                for index in range(len(values))
            }
            context_name, context_condition = _context_metric(context)
            raw_name = (
                values[name_index]
                if name_index is not None and name_index < len(values)
                else context_name
            )
            item_name = _metric_header(raw_name).strip()
            if name_index is not None and not _item_allowed(item_name):
                continue
            series = _series_from_row(row_dict)
            test_method = _test_method_from_row(row_dict)
            qualifiers = {
                key: value
                for key, value in row_dict.items()
                if value
                and _header_role(key) == "qualifier"
                and not any(_column_scope(key))
            }
            conditions = [
                (key, value)
                for key, value in row_dict.items()
                if value
                and _condition_column(key, item_name)
                and not any(_column_scope(key))
            ]
            notes = [
                f"{key}：{value}"
                for key, value in row_dict.items()
                if value and _header_role(key) == "note"
            ]
            row_condition = (
                conditions[0][1]
                if len(conditions) == 1
                else "；".join(f"{key}：{value}" for key, value in conditions)
            )
            row_condition = "；".join(
                part for part in (context_condition, row_condition) if part
            )
            compound_columns = [
                index
                for index, (heading, value) in enumerate(zip(header, values))
                if item_name in {"接触件插入力和分离力", "插拔力"}
                and value
                and _matches_metric(heading, item_name)
                and not _value_kind(heading)
            ]
            for column_index, (heading, value) in enumerate(zip(header, values)):
                if column_index == name_index or not value.strip():
                    continue
                if len(compound_columns) > 1 and column_index in compound_columns:
                    if column_index != compound_columns[0]:
                        continue
                    # 插入力与拔出力属于同一复合指标，不是可任意择一的档位。
                    value = "；".join(
                        f"{header[index]}：{values[index]}"
                        for index in compound_columns
                    )
                    heading = item_name
                column_qualifiers, column_model, column_condition = _column_scope(
                    heading
                )
                parallel_column = bool(
                    column_qualifiers or column_model or column_condition
                )
                role = _header_role(heading)
                metric = item_name
                is_metric_value = _matches_metric(heading, item_name)
                if (
                    not parallel_column
                    and not is_metric_value
                    and (
                        role
                        in {
                            "qualifier",
                            "model",
                            "condition",
                            "method",
                            "note",
                            "metadata",
                        }
                        or _condition_column(heading, item_name)
                    )
                ):
                    continue
                generic_value = (
                    role == "value"
                    or _norm_header(heading) == "指标"
                    or bool(_header_unit(heading) and not _metric_header(heading))
                )
                if not (parallel_column or is_metric_value or generic_value):
                    # 独立指标列（型号 | 电流(A) | 电压(V)）由列名确定指标。
                    if name_index is None and any(
                        word in heading for word in _INDICATOR_CONTEXT_WORDS
                    ):
                        metric = _metric_header(heading)
                    else:
                        continue
                if not _item_allowed(metric) or metric in _GENERIC_TITLES:
                    continue
                scope = column_model or series
                candidate_qualifiers = {**qualifiers, **column_qualifiers}
                condition = "；".join(
                    part for part in (row_condition, column_condition) if part
                )
                unit = (
                    _header_unit(heading)
                    or _header_unit(raw_name)
                    or str(row_dict.get("单位", "")).strip()
                )
                for value_kind, metric_value in _value_parts(value.strip(), heading):
                    display_value = (
                        f"{value_kind}：{metric_value}" if value_kind else metric_value
                    )
                    if unit and unit not in metric_value:
                        display_value += f" {unit}"
                    details = [display_value]
                    if scope:
                        details.append(f"适用型号/系列：{scope}")
                    details.extend(
                        f"{key}：{text}" for key, text in candidate_qualifiers.items()
                    )
                    if condition:
                        details.append(f"条件：{condition}")
                    details.extend(notes)
                    if test_method:
                        details.append(f"试验方法：{test_method}")
                    items.append(
                        SpecRequirementItem(
                            item_name=metric,
                            standard_text="；".join(details),
                            source_section=context["semantic_path"],
                            table_caption=context["caption"],
                            applicable_model=scope,
                            category_or_series=scope,
                            spec=metric_value,
                            test_method=test_method,
                            condition=condition,
                            value_kind=value_kind,
                            qualifiers=candidate_qualifiers,
                            unit=unit,
                            raw_row={
                                **row_dict,
                                "_body_index": context["body_index"],
                                "_row_index": row_index,
                                "_column_index": column_index,
                                "_header": header,
                                "_values": values,
                            },
                        )
                    )
    return items


def extract_spec_paragraph_requirements(spec_path: str) -> list[SpecRequirementItem]:
    """Read explicit voltage overrides and mating-cycle requirements.

    These forms have named metric headings and independently identifiable
    value/model/condition fields. Other prose and trial-method numbers are
    not candidates. Raw paragraphs and body coordinates remain evidence.
    """
    with zipfile.ZipFile(spec_path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    body = root.find(f"{{{W}}}body")
    if body is None:
        return []
    stack: list[tuple[int, str]] = []
    scope = ""
    scope_evidence = ""
    unresolved_scope_levels: set[int] = set()
    items: list[SpecRequirementItem] = []
    model_list = r"[A-Za-z][A-Za-z0-9/-]*(?:[、，,][A-Za-z][A-Za-z0-9/-]*)*"
    voltage_clause = re.compile(
        r"^(常温常压|低气压[（(]([\d.]+)\s*(kPa|MPa|Pa)[）)])"
        r"[：:，,]\s*(\d+(?:\.\d+)?)\s*V\s*[，,]?\s*(AC|DC)"
        r"\s*(?:测试|试验)时间\s*(\d+(?:\.\d+)?\s*(?:min|ms|s))[；;。]?\s*$",
        re.IGNORECASE,
    )
    life_clause = re.compile(
        r"^(按[A-Za-z][A-Za-z0-9/.-]*\s*方法[\d.]+(?:的规定)?进行试验[，,])?"
        r"连接器插合和分离循环次数为\s*(\d+)次[。.]?"
        r"(?:[（(]当型号为(" + model_list + r")时[，,]循环次数为\s*(\d+)次[）)])?[。.]?$"
    )

    def add(metric, value, *, condition="", models="", method="", excluded=()):
        details = [value]
        if condition:
            details.append(f"条件：{condition}")
        if method:
            details.append(f"试验方法：{method}")
        items.append(SpecRequirementItem(
            item_name=metric, standard_text="；".join(details), spec=value,
            source_section=" / ".join(title for _, title in stack),
            applicable_model=models, condition=condition, test_method=method,
            excluded_models=tuple(excluded),
            raw_row={"_body_index": body_index, "_source_text": text,
                "_scope_text": scope_evidence if models == scope else ""},
        ))

    for body_index, child in enumerate(body):
        if child.tag == f"{{{W}}}tbl":
            scope = scope_evidence = ""
            continue
        if child.tag != f"{{{W}}}p":
            continue
        text = get_para_text(child).strip()
        if _is_heading(child):
            level = _heading_level(child)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, _semantic_title(text)))
            unresolved_scope_levels = {depth for depth in unresolved_scope_levels if depth < level}
            scope = scope_evidence = ""
            continue
        if not text or not stack:
            continue
        path = " / ".join(title for _, title in stack)
        if re.match(r"^(?:仅|只|本(?:节|条|章))?(?:适用于|适用范围|型号为|产品型号|当型号为|仅限|不适用于|除)", text):
            unresolved_scope_levels.add(stack[-1][0])
            items[:] = [item for item in items if item.source_section != path]
            continue
        if (any(word in path for word in _DENIED_CONTEXT_WORDS)
            or re.search(r"历史|示例|样例|案例|记录", path)
            or re.search(r"[A-Za-z][A-Za-z0-9/-]*\d[A-Za-z0-9/-]*", path)
            or unresolved_scope_levels):
            continue
        metric = stack[-1][1]
        if metric in {"介质耐电压", "耐电压", "耐压"}:
            introduction = re.fullmatch(
                r"[①②③④⑤⑥⑦⑧⑨⑩]?\s*(" + model_list + r")"
                r"(?:连接器|产品)(?:介质)?耐电压要求如下[：:]", text,
            )
            if introduction:
                models = re.split(r"[、，,]", introduction.group(1))
                scope = introduction.group(1) if all(re.search(r"\d", model) for model in models) else ""
                scope_evidence = text if scope else ""
                continue
            clause = voltage_clause.fullmatch(text)
            if scope and clause:
                environment, pressure, pressure_unit, voltage, current, duration = clause.groups()
                conditions = ["常温", "常压"] if environment == "常温常压" else [
                    pressure + {"kpa": "kPa", "mpa": "MPa", "pa": "Pa"}[pressure_unit.lower()]]
                add(metric, voltage + "V", models=scope,
                    condition="；".join([*conditions, current.upper(), duration]))
            elif text:
                # An unparsed scope/form must not inherit the previous model.
                scope = scope_evidence = ""
        elif metric == "机械寿命":
            clause = life_clause.fullmatch(text)
            if not clause:
                if re.search(r"适用|仅限|型号|例外|除外|历史|示例|样例|案例|记录", text):
                    unresolved_scope_levels.add(stack[-1][0])
                    # A later unsupported scope note can qualify preceding
                    # statements too; do not leave a generic candidate behind.
                    items[:] = [item for item in items if item.source_section != path]
                continue
            method, cycles, exceptions, exception_cycles = clause.groups()
            excluded = re.split(r"[、，,]", exceptions) if exceptions else []
            if any(not re.search(r"\d", model) for model in excluded):
                continue
            method = (method or "").rstrip("，,。 ")
            add(metric, cycles + "次", method=method, excluded=excluded)
            if exceptions:
                add(metric, exception_cycles + "次", models=exceptions,
                    method=method)
    return items
