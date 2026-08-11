"""按标题树和表格语义抽取产品规范指标，不依赖章节号或章节顺序。"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List

from lxml import etree

from .docx_io import get_cell_text, get_para_text

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


SPEC_DENIED_ITEM_PATTERNS = re.compile(
    r"^(\d+组|[0-9]{1,2}|[A-Z]$|产品规范|检验项目|检验顺序|要求条款|试验方法条款)",
    re.I,
)
_DENIED_CONTEXT_WORDS = {
    "变更记录", "目录", "前言", "发放", "型号命名", "检验项目和顺序",
    "检验分组", "规范性引用", "术语定义", "包装标志", "封面",
}
_INDICATOR_CONTEXT_WORDS = {
    "性能", "指标", "电气", "机械", "环境", "可靠", "维修", "保障", "测试性",
    "电压", "电流", "电阻", "耐压", "温度", "振动", "冲击", "加速度", "盐雾",
    "霉菌", "寿命", "插拔", "按压力", "弹力", "互换", "安全",
}
_TABLE_HEADER_WORDS = {
    "项目", "指标", "要求", "规格", "电压", "电流", "电阻", "温度", "时间",
    "频率", "方向", "插入力", "分离力", "加载方向",
}
_CHANGE_RECORD_HEADER_WORDS = {
    "版本", "章条编号", "改前内容", "改后内容", "日期",
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
    raw_row: Dict = field(default_factory=dict)


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
        text and len(text) <= 100
        and re.match(r"^\d+(?:\.\d+)*\s+[\u4e00-\u9fffA-Za-z]", text)
    )


def _heading_level(element) -> int:
    style = _paragraph_style(element)
    match = re.search(r"(?:Heading|heading)?\s*([1-9])$", style)
    if match:
        return int(match.group(1))
    number = re.match(r"^(\d+(?:\.\d+)*)\s+", get_para_text(element).strip())
    return number.group(1).count(".") + 1 if number else 1


def _series_from_row(row_dict: Dict) -> str:
    # 受控产品规范的适用范围列没有统一表头。保留完整的范围文本，供
    # 后续型号/系列匹配器作保守裁决，不能只识别“系列”这一种写法。
    priority = (
        "系列 / 型号 / 类别", "型号/系列", "型号（系列）",
        "适用型号", "产品型号", "适用系列", "产品系列",
        "适用产品", "适用范围", "系列", "型号", "类别", "产品类别",
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


def _test_method_from_row(row_dict: Dict) -> str:
    """提取独立的试验方法列，避免在结构化台账中静默丢失。"""
    method_markers = ("试验方法", "检验方法", "检测方法", "测试方法", "方法条款")
    for key, value in row_dict.items():
        header = _norm_header(str(key))
        method = str(value or "").strip()
        if method and any(marker in header for marker in method_markers):
            return method
    return ""


def _value_column_for_item(item_name: str, header: List[str], values: List[str]) -> str:
    """表头含与项目同名列时，读取该列数值而不是邻近的规格列。"""
    normalized_name = _norm_header(item_name)
    # 规范表常用“电流/电压/寿命”等短表头，不能退回到相邻的“规格”列。
    # 后者可能是接触件直径、针径等辅助参数，误取后会把 0.51mm 当成额定
    # 电流，或者把适用范围文本当成机械寿命值。
    header_aliases = {
        "额定电压": ("电压",),
        "工作电压": ("电压",),
        "额定电流": ("电流",),
        "工作电流": ("电流",),
        "机械寿命": ("寿命",),
        "工作温度": ("温度",),
        "接触件弹力": ("单芯弹力", "弹力"),
    }
    accepted_headings = {normalized_name}
    accepted_headings.update(
        _norm_header(value) for value in header_aliases.get(item_name, ())
    )
    for index, heading in enumerate(header):
        normalized_heading = _norm_header(heading)
        if not normalized_heading or normalized_heading in {"项目", "指标", "序号"}:
            continue
        if normalized_heading in accepted_headings or (
            normalized_name in normalized_heading
            and len(normalized_heading) <= len(normalized_name) + 4
        ):
            if index < len(values) and values[index].strip():
                return values[index].strip()
    return ""


def _assemble_multi_column_value(item_name: str, row_dict: Dict) -> str:
    column_sets = {
        "额定电压": ("电压", "DC / AC", "DC/AC"),
        "工作电压": ("电压", "DC / AC", "DC/AC"),
        "额定电流": ("电流",),
        "工作电流": ("电流",),
        "介质耐电压": ("电压", "DC / AC", "DC/AC", "频率", "测试时间", "漏电流值", "漏电流"),
        "机械寿命": ("寿命",),
        "工作温度": ("温度",),
        "接触件弹力": ("单芯弹力", "弹力"),
        "绝缘电阻": ("绝缘电阻", "试验标准/要求", "试验电压", "DC / AC"),
        "接触件插入力和分离力": ("规格", "插入力", "分离力"),
        "插拔力": ("插入力", "拔出力"),
    }
    parts = [
        (row_dict.get(key) or "").strip()
        for key in column_sets.get(item_name, ())
        if (row_dict.get(key) or "").strip()
    ]
    return "，".join(parts)


def _build_standard_text(
    item_name: str, series: str, spec_value: str, extra: str,
    values: List[str], row_dict: Dict, test_method: str = "",
) -> str:
    multi_value = _assemble_multi_column_value(item_name, row_dict)
    if multi_value:
        spec_value = multi_value
    parts: List[str] = []
    if spec_value:
        parts.append(spec_value)
    if extra and extra not in {spec_value, series}:
        parts.append(f"（{extra}）")
    if test_method and test_method not in {spec_value, extra, series}:
        parts.append(f"试验方法：{test_method}")
    if parts:
        return "；".join(parts)
    return " ".join(value for value in values[1:] if value.strip()).strip()


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
            elif re.match(r"^表\s*\d+", text):
                last_caption = text
        elif child.tag == f"{{{W}}}tbl":
            titles = [title for _, title in stack]
            tables.append({
                "element": child,
                "body_index": body_index,
                "title": titles[-1] if titles else "（前置区域）",
                "semantic_path": " / ".join(titles) if titles else "（前置区域）",
                "caption": last_caption,
            })
            last_caption = ""
    return tables


def _matrix(rows) -> list[list[str]]:
    return [
        [get_cell_text(cell).strip() for cell in row.findall(f"{{{W}}}tc")]
        for row in rows
    ]


def _matrix_text(matrix: list[list[str]]) -> str:
    rendered = []
    for row in matrix:
        values = list(dict.fromkeys(value for value in row if value))
        if values:
            rendered.append("：".join(values) if len(values) == 2 else "、".join(values))
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
    return bool(title_signal or (header_signal and row_signal) or "随机振动" in table_text)


def _nearby_qualifier(full_text: str, keyword: str) -> str:
    """从原文提取包含关键词的完整短句，不写死任何型号或数值。"""
    pattern = (
        rf"[^。；\n]{{0,80}}{re.escape(keyword)}[^。；\n]{{0,160}}"
        rf"(?:。[^。；\n]{{0,160}})?"
    )
    match = re.search(pattern, full_text, re.I)
    return match.group(0).strip(" ，,：:") if match else ""


def _special_matrix_item(context: dict, matrix: list[list[str]], full_text: str) -> SpecRequirementItem | None:
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
        return None
    parts = [table_text]
    if item_name == "振动":
        qualifier = _nearby_qualifier(full_text, "配重")
        if qualifier and qualifier not in table_text:
            parts.append(qualifier)
    return SpecRequirementItem(
        item_name=item_name,
        standard_text="；".join(part for part in parts if part),
        source_section=context["semantic_path"],
        table_caption=context["caption"] or f"{item_name}试验条件",
        raw_row={"matrix": matrix, "body_index": context["body_index"]},
    )


def extract_spec_chapter3_tables(
    spec_path: str, product_name: str | None = None,
) -> List[SpecRequirementItem]:
    """抽取产品规范指标表；`product_name` 仅为兼容旧调用，不参与定位。"""
    del product_name
    with zipfile.ZipFile(spec_path, "r") as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    # 规范中的补充条件可能放在 Word 文本框/绘图容器里，不一定属于普通
    # paragraph 集合。读取全部 w:t 才能得到真实原文，同时仍不生成任何文字。
    full_text = "".join(
        node.text or "" for node in root.findall(f".//{{{W}}}t")
    )
    items: List[SpecRequirementItem] = []

    for context in _iter_tables_with_context(root):
        table = context["element"]
        rows = table.findall(f"{{{W}}}tr")
        if len(rows) < 2:
            continue
        matrix = _matrix(rows)
        if not _context_allows_table(context, matrix):
            continue
        special = _special_matrix_item(context, matrix, full_text)
        if special is not None:
            items.append(special)
            continue

        header = matrix[0]
        if not header or not any(header):
            continue
        for values in matrix[1:]:
            if not any(values):
                continue
            row_dict = {
                header[index] if index < len(header) else f"col{index}": values[index]
                for index in range(len(values))
            }
            item_name = row_dict.get("项目", row_dict.get("指标", values[0] if values else ""))
            if not _item_allowed(item_name):
                continue
            item_name = item_name.strip()
            series = _series_from_row(row_dict)
            spec_value = _value_column_for_item(item_name, header, values)
            if not spec_value:
                spec_value = row_dict.get("指标", row_dict.get("要求", row_dict.get("规格", "")))
            multi_value = _assemble_multi_column_value(item_name, row_dict)
            if multi_value:
                spec_value = multi_value
            extra = row_dict.get("补充说明", row_dict.get("备注", ""))
            test_method = _test_method_from_row(row_dict)
            standard_text = _build_standard_text(
                item_name, series, spec_value, extra, values, row_dict, test_method
            )
            if not standard_text:
                continue
            row_dict["_body_index"] = context["body_index"]
            items.append(SpecRequirementItem(
                item_name=item_name,
                standard_text=standard_text,
                source_section=context["semantic_path"],
                table_caption=context["caption"],
                applicable_model=series,
                category_or_series=series,
                spec=spec_value,
                test_method=test_method,
                condition=extra,
                raw_row=row_dict,
            ))
    return items
