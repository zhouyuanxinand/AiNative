"""填充后清理：删除模板括号说明、示例附录、条件标准行。"""
import re
from typing import Any, Dict, List, Tuple

from .config import W
from .docx_io import delete_paragraph_range, find_section_range_by_keywords, get_cell_text, get_para_text, set_para_text


# 括号内为模板红字/说明的特征词
INSTRUCTION_KEYWORDS = (
    "删除", "保留", "可删除", "没有可写", "设计填写", "设计员", "可附图",
    "型号名称", "内容要求", "数据库", "故障现象", "设计改进", "历史失效",
    "待设计", "利用Edraw", "改型", "派生", "预研", "自研", "军品", "民机",
    "适用于", "不适用", "无相应", "没有明确", "编号", "技术协议", "技术协调",
    "应对技术协议", "根据具体情况", "增减", "填写", "说明", "可附图说明",
    "AS9100", "产品适用", "需求分析和定义",
)

# 整段删除：纯模板说明段
PURE_INSTRUCTION_RE = re.compile(
    r"^[（(].{8,}[）)]$|"
    r"^（改型、派生产品可删除|"
    r"^（产品有关的国军标|"
    r"^（此条要求对用户的特殊要求|"
    r"^（内容要求：|"
    r"^（故障现象）|"
    r"^（设计改进措施）|"
    r"^本小节对应（相似）产品历史失效|"
    r"^\(应对技术协议"
)

# 标准条目中按项目类型应整行删除的标记
DELETE_STANDARD_IF_MARKERS = (
    ("军品删除", lambda f: not f.get("is_military", True)),
    ("所有军品均保留", lambda f: not f.get("is_military", True)),
    ("民机项目保留", lambda f: not f.get("is_airworthiness", False)),
    ("无大型试验要求删除", lambda f: not f.get("has_large_test", False)),
    ("无交互式电子技术手册要求删除", lambda f: True),
    ("无电磁兼容性要求删除", lambda f: not f.get("has_emc", False)),
    ("航空军品保留", lambda f: not f.get("is_aviation", False)),
    ("适用于开展状态鉴定", lambda f: not f.get("is_status_qualification", False)),
    ("适用于开展环境应力筛选", lambda f: not f.get("has_ess", False)),
)


def _should_preserve_figure_caption(text: str) -> bool:
    return bool(re.match(r"^图\s*\d+", text.strip()))


def strip_parenthetical_instructions(text: str) -> str:
    """去掉模板括号说明；图题行保留（左）（右）等位置标注。"""
    if not text or _should_preserve_figure_caption(text):
        return text

    def drop_inner(inner: str) -> bool:
        if len(inner) <= 2:
            return True
        return any(k in inner for k in INSTRUCTION_KEYWORDS)

    def repl_cn(m):
        return "" if drop_inner(m.group(1)) else m.group(0)

    def repl_en(m):
        return "" if drop_inner(m.group(1)) else m.group(0)

    out = text
    for _ in range(5):
        new = re.sub(r"（([^（）]*)）", repl_cn, out)
        new = re.sub(r"\(([^()]*)\)", repl_en, new)
        if new == out:
            break
        out = new
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"：\s*$", "", out)
    return out


def strip_abbreviation_parens(text: str) -> str:
    """去掉正文中的简称括号，保留图题位置标注。"""
    if not text or _should_preserve_figure_caption(text):
        return text
    out = re.sub(r"（简称[^）]{1,40}）", "", text)
    out = re.sub(r"\(简称[^)]{1,40}\)", "", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def _replace_product_placeholders(text: str, product_name: str) -> str:
    text = text.replace("（型号名称）", product_name)
    text = text.replace("(型号名称)", product_name)
    text = re.sub(r"\bXXX\b", product_name, text)
    return text


def _is_pure_instruction_paragraph(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if PURE_INSTRUCTION_RE.search(t):
        return True
    if t.startswith("（") and t.endswith("）") and len(t) > 10:
        return any(k in t for k in INSTRUCTION_KEYWORDS)
    if t.startswith("(") and t.endswith(")") and len(t) > 10:
        return any(k in t for k in INSTRUCTION_KEYWORDS)
    return False



def _para_is_all_red_or_highlighted(para) -> bool:
    if para.findall(f".//{{{W}}}drawing"):
        return False
    txt = "".join(t.text or "" for t in para.findall(f".//{{{W}}}t")).strip()
    if not txt or re.match(r"^图\s*\d+", txt):
        return False
    runs = para.findall(f".//{{{W}}}r")
    total = colored = 0
    for r in runs:
        run_txt = "".join(t.text or "" for t in r.findall(f"{{{W}}}t")).strip()
        if not run_txt:
            continue
        total += 1
        rpr = r.find(f"{{{W}}}rPr")
        if rpr is None:
            continue
        color_el = rpr.find(f"{{{W}}}color")
        if color_el is not None:
            val = (color_el.get(f"{{{W}}}val") or "").upper()
            if val in ("FF0000", "C00000", "E00000", "D00000"):
                colored += 1
                continue
        hl = rpr.find(f"{{{W}}}highlight")
        if hl is not None:
            val = (hl.get(f"{{{W}}}val") or "").lower()
            if val in ("yellow", "cyan", "green", "magenta", "red"):
                colored += 1
    return total > 0 and colored == total

def _should_delete_standard_line(text: str, project_flags: Dict[str, Any]) -> bool:
    for marker, cond in DELETE_STANDARD_IF_MARKERS:
        if marker in text and cond(project_flags):
            return True
    return False


def _set_para_text_preserve_style(para, new_text: str) -> None:
    if not new_text.strip():
        return
    ts = para.findall(f".//{{{W}}}t")
    if ts:
        ts[0].text = new_text
        for t in ts[1:]:
            t.text = ""
    else:
        set_para_text(para, new_text)


def _clean_paragraph(para, product_name: str, project_flags: Dict[str, Any]) -> Tuple[str, bool]:
    """返回 (action, detail): action=delete|clean|skip"""
    text = get_para_text(para)
    if not text.strip():
        return "skip", ""
    if _should_delete_standard_line(text, project_flags):
        return "delete", text[:60]
    if _is_pure_instruction_paragraph(text):
        return "delete", text[:60]
    replaced = _replace_product_placeholders(text, product_name)
    cleaned = strip_parenthetical_instructions(replaced)
    cleaned = strip_abbreviation_parens(cleaned)
    if not cleaned.strip():
        return "delete", text[:60]
    if cleaned != text:
        _set_para_text_preserve_style(para, cleaned)
        return "clean", text[:60]
    return "skip", ""


def _clean_table_cells(root) -> int:
    n = 0
    for cell in root.findall(f".//{{{W}}}tc"):
        for para in cell.findall(f"{{{W}}}p"):
            text = get_para_text(para)
            if not text or _should_preserve_figure_caption(text):
                continue
            cleaned = strip_parenthetical_instructions(text)
            cleaned = strip_abbreviation_parens(cleaned)
            if cleaned != text:
                _set_para_text_preserve_style(para, cleaned)
                n += 1
    return n


def delete_operation_scenario_sections(root, project_flags: Dict[str, Any]) -> int:
    """清空附录A场景表格中的示例数据行（保留表头）；正文场景段由 template_rule_engine 处理。
    
    模板中附录A表格包含示例数据（汽车等行业串项），需要清空数据行内容，
    保留表格结构和表头，以便后续 fill_appendix_scenarios 填充实际数据。
    """
    cleared = 0
    
    for tbl in root.findall(f".//{{{W}}}tbl"):
        rows = tbl.findall(f"{{{W}}}tr")
        if len(rows) < 2:
            continue
        
        first_row_text = "".join(
            t.text or "" for tc in rows[0].findall(f".//{{{W}}}tc") 
            for t in tc.findall(f".//{{{W}}}t")
        ).strip()
        
        if "场景类别" in first_row_text and "任务场景" in first_row_text:
            for row in rows[1:]:
                for tc in row.findall(f"{{{W}}}tc"):
                    for p in tc.findall(f".//{{{W}}}p"):
                        for t_el in p.findall(f".//{{{W}}}t"):
                            t_el.text = ""
                cleared += 1
            break
    
    return cleared


def apply_template_cleanup(
    root,
    product_name: str = "",
    project_flags: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """填充完成后统一清理括号说明与模板残留。"""
    project_flags = project_flags or {}
    stats = {"deleted_paras": 0, "cleaned_paras": 0, "cleaned_cells": 0, "section_deleted": 0}

    stats["section_deleted"] = delete_operation_scenario_sections(root, project_flags)

    paras = list(root.findall(f".//{{{W}}}p"))
    to_delete = []
    for para in paras:
        if _para_is_all_red_or_highlighted(para):
            to_delete.append(para)
            continue
        action, _ = _clean_paragraph(para, product_name, project_flags)
        if action == "delete":
            to_delete.append(para)
        elif action == "clean":
            stats["cleaned_paras"] += 1

    for para in to_delete:
        parent = para.getparent()
        if parent is not None:
            parent.remove(para)
            stats["deleted_paras"] += 1

    stats["cleaned_cells"] = _clean_table_cells(root)
    stats["total"] = sum(stats.values())
    return stats


def fill_cover_and_basis(
    root,
    product_name: str,
    tech_doc_name: str,
    spec_doc_name: str,
    tech_doc_no: str = "",
) -> Dict[str, int]:
    """封面型号、第15章编制依据。"""
    filled = {"cover": 0, "basis": 0}
    basis_lines = []
    if tech_doc_no:
        basis_lines.append(f"《{tech_doc_name}》，编号：{tech_doc_no}；")
    else:
        basis_lines.append(f"《{tech_doc_name}》；")
    basis_lines.append(f"《{spec_doc_name}》；")

    in_basis = False
    basis_idx = 0
    remove_placeholders = ("信息传递单", "电话记录", "技术协议", "技术协调单")

    for para in root.findall(f".//{{{W}}}p"):
        text = get_para_text(para)
        if "（型号名称）" in text or "(型号名称)" in text:
            set_para_text(para, f"{product_name}连接器")
            filled["cover"] += 1
            continue
        if "任务书编制依据" in text:
            in_basis = True
            continue
        if not in_basis:
            continue
        if re.match(r"^附\s*录", text.replace(" ", "")):
            break
        stripped = text.strip()
        if stripped in {"……", "..."}:
            if basis_idx < len(basis_lines):
                set_para_text(para, basis_lines[basis_idx])
                basis_idx += 1
                filled["basis"] += 1
            continue
        if any(k in text for k in remove_placeholders):
            parent = para.getparent()
            if parent is not None:
                parent.remove(para)
            continue

    return filled
