# -*- coding: utf-8 -*-
"""
fill.py — 语义槽位驱动的研制任务书填充主程序
换设计输入: 不依赖章节号或章节顺序
换产品/模板: 注册语义标题锚点和受控模板，不修改主流程
"""
from __future__ import annotations
import argparse, copy, json, re, sys
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph

try:
    import yaml
except ImportError:
    print("pip install pyyaml"); sys.exit(1)

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent))
from jonhon_taskbook.extractor import (
    parse_doc, get_cover_field, dedup_stds,
)
from jonhon_taskbook.indicator_taxonomy import taxonomy_indicator_map
from jonhon_taskbook.indicator_catalog_loader import (
    load_reference_indicator_catalog,
)
from jonhon_taskbook.standard_order import sort_standards
from jonhon_taskbook.renderer.table_style_engine import apply_table_style
try:
    from jonhon_taskbook.template_scanner import (
        build_semantic_heading_map as _build_semantic_hmap,
    )
    _SCANNER_OK = True
except ImportError:
    _SCANNER_OK = False
    _build_semantic_hmap = None

try:
    from jonhon_taskbook.product_router import load_profile as _load_profile
    _ROUTER_OK = True
except ImportError:
    _ROUTER_OK = False
    _load_profile = None

def _txt(p) -> str:
    return "".join(r.text or "" for r in p.runs).strip()

def _is_heading(p) -> bool:
    s = p.style.name if p.style else ""
    if "Heading" in s or "heading" in s or "标题" in s:
        return True
    # 受控模板有时把标题名称改成自定义样式，但仍保留 Word 的
    # outlineLvl 结构信息。用该结构信息识别标题，不读取显示章节号。
    ppr = p._p.find(qn("w:pPr"))
    outline = ppr.find(qn("w:outlineLvl")) if ppr is not None else None
    return outline is not None and str(outline.get(qn("w:val"), "")).isdigit()

def _heading_depth_sv_val(sv: str) -> int:
    import re as _re
    m = _re.match(r'^\d$|^[Hh]eading\s*(\d)', sv)
    if m:
        g = m.group(0) if m.group(0).isdigit() else m.group(1)
        return int(g) if g else 0
    return 0

def _heading_depth_sv(p) -> int:
    ppr = p._p.find(qn('w:pPr'))
    if ppr is None: return 0
    ps = ppr.find(qn('w:pStyle'))
    if ps is None: return 0
    return _heading_depth_sv_val(ps.get(qn('w:val'), ''))

def _heading_level(p) -> int:
    style_name = p.style.name if p.style else ""
    match = re.search(r"(\d+)\s*$", style_name)
    if match:
        return int(match.group(1))
    ppr = p._p.find(qn("w:pPr"))
    outline = ppr.find(qn("w:outlineLvl")) if ppr is not None else None
    raw = outline.get(qn("w:val")) if outline is not None else None
    return int(raw) + 1 if raw is not None and str(raw).isdigit() else 0


_RED_VALS = {"FF0000","C00000","E00000","D00000","F00000","B00000"}

def _is_red(r) -> bool:
    rpr = r._r.find(qn("w:rPr"))
    if rpr is None: return False
    c = rpr.find(qn("w:color"))
    return c is not None and (c.get(qn("w:val")) or "").upper() in _RED_VALS

def _all_red(p) -> bool:
    runs = [r for r in p.runs if (r.text or "").strip()]
    return bool(runs) and all(_is_red(r) for r in runs)

def _clear_red(p) -> None:
    for r in list(p.runs):
        if _is_red(r): r._r.getparent().remove(r._r)

def _deep_clean_para(p) -> None:
    """清除 run 级红色字体和高亮（不删 run，只改格式）。"""
    for r in p.runs:
        rpr = r._r.find(qn("w:rPr"))
        if rpr is None: continue
        c = rpr.find(qn("w:color"))
        if c is not None and (c.get(qn("w:val")) or "").upper() in _RED_VALS:
            c.set(qn("w:val"), "000000")
        for tag in ("w:highlight", "w:shd"):
            el = rpr.find(qn(tag))
            if el is not None: rpr.remove(el)


def _compact_basis_reference(tech_basis: str, spec_basis: str) -> str:
    """把命中证据压缩成适合表格展示的章节/表号，不丢失可追溯性。"""
    def _first_section(value: str) -> str:
        match = re.search(r"(?<!\d)(\d+(?:\.\d+)+)(?!\d)", value or "")
        return match.group(1) if match else ""

    parts = []
    tech_section = _first_section(tech_basis)
    if tech_basis:
        parts.append(f"技术要求{tech_section}" if tech_section else "技术要求")

    spec_section = _first_section(spec_basis)
    table_match = re.search(r"表\s*(\d+)", spec_basis or "")
    if spec_basis:
        label = f"产品规范{spec_section}" if spec_section else "产品规范"
        if table_match:
            label += f"（表{table_match.group(1)}）"
        parts.append(label)
    return "；".join(parts)

def _fill_indicator_table(tpl, ind_rows: list, excluded_names: list[str] | None = None) -> int:
    """
    找到模板指标表（4列或5列），按名称匹配行填充单元格。
    列结构以模板为准，不再自动插入“标准要求”列。
    直接用 lxml w:tc 列表操作，绕开 python-docx 合并单元格陷阱。
    无对应行则克隆模板第一个数据行并插入对应分类组末尾。
    """
    from lxml import etree
    import copy

    W  = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    _W = f"{{{W}}}"

    excluded = {
        _canonical_indicator_name(str(name or ""))
        for name in (excluded_names or [])
        if str(name or "").strip()
    }

    def _is_excluded(name: str) -> bool:
        return _canonical_indicator_name(str(name or "")) in excluded

    target_tbl = None
    for tbl in tpl.tables:
        if not tbl.rows:
            continue
        header = "".join(c.text for c in tbl.rows[0].cells)
        if "用户要求" in header and len(tbl.rows[0].cells) >= 4:
            target_tbl = tbl
            break
    if target_tbl is None:
        return 0

    def _raw_tc_text(tc_el) -> str:
        return "".join(
            node.text or "" for node in tc_el.findall(f".//{_W}t")
        ).strip()

    def _raw_grid_span(tc_el) -> int:
        tc_pr = tc_el.find(f"{_W}tcPr")
        span = tc_pr.find(f"{_W}gridSpan") if tc_pr is not None else None
        try:
            return int(span.get(f"{_W}val", "1")) if span is not None else 1
        except (TypeError, ValueError):
            return 1

    header_row = target_tbl._tbl.find(f"{_W}tr")
    header_cells = header_row.findall(f"{_W}tc") if header_row is not None else []
    template_column_count = sum(_raw_grid_span(cell) for cell in header_cells)

    def _normalize_split_category_row(tr_el) -> bool:
        """把“前 N-1 列合并 + 最后一列空白”的分类行归一为整行合并。

        部分受控模板在分类标题行保留了一个空的“依据”单元格。该结构在
        视觉上像分类行，但若不先归一化，会被误选成新增指标行的克隆母版，
        最终造成指标名称跨列、指标值落入最后一列。
        """
        cells = tr_el.findall(f"{_W}tc")
        if template_column_count < 2 or len(cells) < 2:
            return False
        spans = [_raw_grid_span(cell) for cell in cells]
        if sum(spans) != template_column_count or spans[0] < template_column_count - 1:
            return False
        if any(_raw_tc_text(cell) for cell in cells[1:]):
            return False
        first = cells[0]
        tc_pr = first.find(f"{_W}tcPr")
        if tc_pr is None:
            tc_pr = etree.Element(f"{_W}tcPr")
            first.insert(0, tc_pr)
        span = tc_pr.find(f"{_W}gridSpan")
        if span is None:
            span = etree.SubElement(tc_pr, f"{_W}gridSpan")
        span.set(f"{_W}val", str(template_column_count))
        for trailing in cells[1:]:
            tr_el.remove(trailing)
        return True

    # 必须在选择数据行克隆母版之前做结构归一化。这里只识别 OOXML
    # 合并关系与空白尾格，不依赖产品名、章节号或模板行号。
    for _tr in target_tbl._tbl.findall(f"{_W}tr"):
        _normalize_split_category_row(_tr)

    # 设置表格居中
    tbl_pr = target_tbl._tbl.find(f"{_W}tblPr")
    if tbl_pr is None:
        tbl_pr = etree.SubElement(target_tbl._tbl, f"{_W}tblPr")
        target_tbl._tbl.insert(0, tbl_pr)
    jc = tbl_pr.find(f"{_W}jc")
    if jc is None:
        jc = etree.SubElement(tbl_pr, f"{_W}jc")
        tbl_pr.append(jc)
    jc.set(f"{_W}val", "center")

    tbl_el = target_tbl._tbl

    def _tc_list(tr_el):
        """返回 tr 里实际的 w:tc 元素列表（不含 vMerge continue 格）。"""
        tcs = tr_el.findall(f"{_W}tc")
        # 过滤掉 vMerge（无 val 或 val!='restart' 的跨行延续格）
        real = []
        for tc in tcs:
            tcp = tc.find(f"{_W}tcPr")
            vm  = tcp.find(f"{_W}vMerge") if tcp is not None else None
            if vm is not None and vm.get(f"{_W}val", "") != "restart":
                continue
            real.append(tc)
        return real

    def _write_tc(tc_el, text: str):
        """清空 tc 并写入文本，同时继承模板单元格的段落/字体格式。"""
        old_paragraphs = tc_el.findall(f"{_W}p")
        sample_ppr = None
        sample_rpr = None
        if old_paragraphs:
            old_ppr = old_paragraphs[0].find(f"{_W}pPr")
            if old_ppr is not None:
                sample_ppr = copy.deepcopy(old_ppr)
            first_run = old_paragraphs[0].find(f"{_W}r")
            if first_run is not None:
                old_rpr = first_run.find(f"{_W}rPr")
                if old_rpr is not None:
                    sample_rpr = copy.deepcopy(old_rpr)
        for p in old_paragraphs:
            tc_el.remove(p)
        p_el = etree.SubElement(tc_el, f"{_W}p")
        if sample_ppr is not None:
            p_el.append(sample_ppr)
        else:
            p_pr = etree.SubElement(p_el, f"{_W}pPr")
            p_jc = etree.SubElement(p_pr, f"{_W}jc")
            p_jc.set(f"{_W}val", "left")
        r_el = etree.SubElement(p_el,  f"{_W}r")
        if sample_rpr is not None:
            r_el.append(sample_rpr)
        t_el = etree.SubElement(r_el,  f"{_W}t")
        t_el.text = text
        t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    def _auto_height(tr_el):
        """指标数据行自适应，且不得继承模板占位行的重复表头标记。"""
        tr_pr = tr_el.find(f"{_W}trPr")
        if tr_pr is None:
            return
        for tr_height in list(tr_pr.findall(f"{_W}trHeight")):
            tr_pr.remove(tr_height)
        for repeated_header in list(tr_pr.findall(f"{_W}tblHeader")):
            tr_pr.remove(repeated_header)

    # 受控模板可能把性能域标题写成通用占位语句。以本次指标账本中的
    # 分类标记按出现顺序替换这些占位标题；业务分类来自配置/账本，代码
    # 不固化“电性能、机械性能、环境性能”等产品专用名称。
    requested_categories = [
        str(row[0])[1:-1].strip()
        for row in ind_rows
        if row and str(row[0]).startswith("【") and str(row[0]).endswith("】")
    ]
    generic_category_labels = {
        "定制产品，无相应标准",
        "定制产品无相应标准",
        "无相应标准",
    }
    generic_category_rows = []
    for _tr in tbl_el.findall(f"{_W}tr"):
        _cells = _tc_list(_tr)
        if len(_cells) == 1 and _raw_tc_text(_cells[0]) in generic_category_labels:
            generic_category_rows.append(_tr)
    for _tr, _category_name in zip(generic_category_rows, requested_categories):
        _cells = _tc_list(_tr)
        if _cells:
            _write_tc(_cells[0], _category_name)

    # 建立行索引：名称 → tr 元素；分类组末尾指针：分类名 → tr 元素
    row_index: dict     = {}
    template_labels: dict = {}
    cat_last:  dict     = {}
    clone_src           = None   # 用于追加新行的克隆模板
    category_clone_src  = None   # 用于追加外置词表未预置的分类行
    current_cat         = ""
    header_names = {"项目", "指标", "序号", "项目名称", "指标名称"}

    for tr in tbl_el.findall(f"{_W}tr"):
        tcs = _tc_list(tr)
        if not tcs:
            continue
        name = "".join(t.text or "" for t in tcs[0].findall(f".//{_W}t")).strip()
        if not name:
            continue
        row_text = "".join(t.text or "" for tc in tcs for t in tc.findall(f".//{_W}t"))
        if name in header_names or ("用户要求" in row_text and "拟采用" in row_text):
            continue
        # 分类行在受控模板中是跨列合并后的单一 tc。不能用“其余列为空”
        # 判断分类行，否则一个尚未填写的真实指标行会被误当分类，既不写值
        # 也不会清除模板继承的固定行高。
        is_cat = len(tcs) == 1
        if is_cat:
            current_cat = name
            cat_last[name] = tr
            if category_clone_src is None:
                category_clone_src = tr
        else:
            if _is_excluded(name):
                # A template may contain a pre-seeded row whose semantic
                # home is an independent section (for example reliability).
                # Remove that row from the structured indicator table instead
                # of leaving an empty ``\\`` row which falsely advertises it
                # as a technical indicator.
                tbl_el.remove(tr)
                continue
            canonical_name = _canonical_indicator_name(name)
            # 模板行名和指标清单名可能不同（如“总分离力”与“总分离力或
            # 分离扭矩”）。索引按受控同义名建立，但输出仍保留模板显示名。
            row_index.setdefault(canonical_name, tr)
            template_labels.setdefault(canonical_name, name)
            if current_cat:
                cat_last[current_cat] = tr
            if clone_src is None:
                clone_src = tr   # 固定第一个真实数据行作为克隆模板

    written = 0
    current_cat = ""
    for row_tuple in ind_rows:
        # 兼容四元组（旧格式）和五元组（新格式）
        if len(row_tuple) == 5:
            name, user_val, std_val, adopted_val, basis = row_tuple
        else:
            name, user_val, std_val, basis = row_tuple
            adopted_val = user_val or std_val

        if not name:
            continue
        if name.startswith("【") and name.endswith("】"):
            current_cat = name[1:-1]
            # 指标清单允许新增性能域或“其他”。模板没有预制
            # 分类行时，从当前模板的分类行克隆格式，不在代码中
            # 固定某个产品的行号或章节号。
            if current_cat not in cat_last and category_clone_src is not None:
                new_category = copy.deepcopy(category_clone_src)
                _auto_height(new_category)
                category_cells = _tc_list(new_category)
                if category_cells:
                    _write_tc(category_cells[0], current_cat)
                tbl_el.append(new_category)
                cat_last[current_cat] = new_category
            continue

        canonical_name = _canonical_indicator_name(name)
        tr = row_index.get(canonical_name)
        if tr is None and clone_src is not None:
            new_tr = copy.deepcopy(clone_src)
            _auto_height(new_tr)
            # 清空所有文字
            for t in new_tr.findall(f".//{_W}t"):
                t.text = ""
            anchor = cat_last.get(current_cat)
            if anchor is not None:
                anchor.addnext(new_tr)
                cat_last[current_cat] = new_tr
            else:
                tbl_el.append(new_tr)
            tr = new_tr
            row_index[canonical_name] = tr
            template_labels[canonical_name] = str(name)

        if tr is None:
            continue

        _auto_height(tr)

        tcs = _tc_list(tr)
        display_name = template_labels.get(canonical_name, str(name))
        if len(tcs) >= 5:
            # 五列：项目|用户要求|标准要求|拟采用|依据
            _write_tc(tcs[0], display_name)
            _write_tc(tcs[1], user_val or "")
            _write_tc(tcs[2], std_val or "")
            _write_tc(tcs[3], adopted_val or "")
            if basis: _write_tc(tcs[4], basis)
        elif len(tcs) == 4:
            # 四列回退：项目|用户要求|拟采用|依据（无标准列）
            _write_tc(tcs[0], display_name)
            _write_tc(tcs[1], user_val or "")
            _write_tc(tcs[2], adopted_val or "")
            if basis: _write_tc(tcs[3], basis)
        else:
            if len(tcs) >= 1: _write_tc(tcs[0], display_name)
            if len(tcs) >= 2: _write_tc(tcs[1], user_val or "")
            if len(tcs) >= 3: _write_tc(tcs[2], adopted_val or "")
        if current_cat:
            cat_last[current_cat] = tr
        written += 1

    # 7-22 规则：输入未提及、但模板原有的指标行必须保留；用户要求列写“\”。
    # 不再删除模板行，否则重复生成或更换输入时会出现“上次正确、这次丢失”。
    for tr in tbl_el.findall(f"{_W}tr"):
        tcs = _tc_list(tr)
        if len(tcs) < 3:
            continue
        name = "".join(t.text or "" for t in tcs[0].findall(f".//{_W}t")).strip()
        if not name:
            continue
        row_text = "".join(t.text or "" for tc in tcs for t in tc.findall(f".//{_W}t"))
        if name in header_names or ("用户要求" in row_text and "拟采用" in row_text):
            continue
        is_category = len(tcs) == 1 or (
            len(tcs) >= 3
            and not "".join(t.text or "" for t in tcs[1].findall(f".//{_W}t")).strip()
            and not "".join(t.text or "" for t in tcs[2].findall(f".//{_W}t")).strip()
            and _canonical_indicator_name(name) not in row_index
        )
        if is_category:
            continue
        col1 = "".join(t.text or "" for t in tcs[1].findall(f".//{_W}t")).strip()
        if not col1:
            _write_tc(tcs[1], "\\")

    return written


def _set_cell_text(cell, text: str) -> None:
    """清空单元格内容并写入纯文本。"""
    from docx.oxml.ns import qn as _qn
    from docx.oxml   import OxmlElement as _OE
    tc = cell._tc
    for p in tc.findall(_qn("w:p")):
        tc.remove(p)
    p_el  = _OE("w:p")
    r_el  = _OE("w:r")
    t_el  = _OE("w:t")
    t_el.text = text
    t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r_el.append(t_el)
    p_el.append(r_el)
    tc.append(p_el)


def _clone_table_row(src_row):
    """复制一行的 XML 结构（清空文字）用于追加新指标行。"""
    import copy
    new_tr = copy.deepcopy(src_row._tr)
    from docx.oxml.ns import qn as _qn
    for t in new_tr.findall(f".//{_qn('w:t')}"):
        t.text = ""
    return new_tr


def _clean_change_record(tpl) -> int:
    """变更记录表只保留表头行，删其余数据行。"""
    deleted = 0
    for tbl in tpl.tables:
        rows = tbl.rows
        if len(rows) < 2:
            continue
        header = "".join(c.text for c in rows[0].cells)
        if "版本" not in header and "章条" not in header:
            continue
        for row in rows[1:]:
            tbl._tbl.remove(row._tr)
            deleted += 1
        break
    return deleted


def _seed_change_record_default(tpl) -> bool:
    """新编文档默认补一行 A / 新发。"""
    for tbl in tpl.tables:
        rows = tbl.rows
        if len(rows) < 1:
            continue
        header = "".join(c.text for c in rows[0].cells)
        if "版本" not in header and "章条" not in header:
            continue
        row = tbl.add_row().cells
        if len(row) >= 5:
            row[0].text = "A"
            row[1].text = ""
            row[2].text = ""
            row[3].text = "新发"
            row[4].text = ""
            return True
    return False

# QFD 不是一律删除的模板垃圾：全新项目必须保留该章节供设计员编辑，
# 改型项目由研制流程策略在 _apply_process_specific_sections 中删除。
_BUILTIN_FORBIDDEN: list[str] = []

def _make_is_junk(extra_forbidden: list[str] | None = None):
    """
    返回一个 is_junk(p) -> bool 闭包。
    extra_forbidden 来自 profile 的 forbidden_phrases，在模板清洗时动态注入，
    避免把跨项目特有词（电池包、USCAR 等）硬编码进引擎。
    """
    forbidden = list(_BUILTIN_FORBIDDEN) + list(extra_forbidden or [])

    def _is_junk(p) -> bool:
        t = _txt(p)
        if t in ("……", "...", "…", "......"):
            return True
        if re.match(r'^[（(].{6,}[）)]$', t):
            return True
        if re.match(r'^XX\S{0,4}[:：]', t):
            return True
        if "XXh" in t and ("MTBF" in t or "MTTR" in t):
            return True
        if re.match(r'^[xX]{2,3}(技术协议|技术协调)', t):
            return True
        if re.match(r'^(信息传递单|电话记录)（编号）', t):
            return True
        if re.search(r'F/C/S/D', t):
            return True
        if re.search(r'研制阶段[：:][^\n]{0,30}F[^\n]{0,30}D', t):
            return True
        if any(bad in t for bad in forbidden):
            return True
        return False

    return _is_junk

def _make_p(text: str, ref=None, *, preserve_italic: bool = True):
    """创建一个沿用模板段落版式的正文段。

    模板中的占位段有时是斜体提示语。普通正文搬运需要保留原格式，
    但“适用的法律法规要求”是由系统重新汇总的正式标准清单，不能把
    第一个斜体占位段的斜体属性复制到整份标准清单。因此该类调用可
    通过 ``preserve_italic=False`` 只移除斜体属性，字体、字号、缩进、
    对齐等其余模板格式仍然保留。
    """
    new_p = OxmlElement("w:p")

    # 复制段落格式（缩进、对齐等）
    if ref is not None:
        src_ppr = ref._p.find(qn("w:pPr"))
        if src_ppr is not None:
            copied_ppr = copy.deepcopy(src_ppr)
            # 新写入正文不继承模板占位段落的自动编号，尤其保证标准清单无序号。
            num_pr = copied_ppr.find(qn("w:numPr"))
            if num_pr is not None:
                copied_ppr.remove(num_pr)
            new_p.append(copied_ppr)

    r_el = OxmlElement("w:r")

    # 构建 rPr：优先从 ref 的第一个 run 复制，否则使用模板默认正文字体
    ref_rpr = None
    if ref is not None:
        for ref_r in ref._p.findall(qn("w:r")):
            ref_rpr = ref_r.find(qn("w:rPr"))
            if ref_rpr is not None:
                break

    if ref_rpr is not None:
        copied_rpr = copy.deepcopy(ref_rpr)
        if not preserve_italic:
            # Word 可能同时写入 w:i 与 w:iCs；两者都移除才能确保中文
            # 与西文渲染均为正体。不要改动模板中未被替换的提示段。
            for italic_tag in (qn("w:i"), qn("w:iCs")):
                for italic_node in copied_rpr.findall(italic_tag):
                    copied_rpr.remove(italic_node)
        r_el.append(copied_rpr)
    else:
        # 默认：仿宋_GB2312，小四（21 half-points = 10.5pt）
        rpr = OxmlElement("w:rPr")
        fonts = OxmlElement("w:rFonts")
        fonts.set(qn("w:ascii"),    "仿宋_GB2312")
        fonts.set(qn("w:eastAsia"), "仿宋_GB2312")
        fonts.set(qn("w:hint"),     "eastAsia")
        sz = OxmlElement("w:sz");   sz.set(qn("w:val"), "21")
        szCs = OxmlElement("w:szCs"); szCs.set(qn("w:val"), "21")
        rpr.append(fonts); rpr.append(sz); rpr.append(szCs)
        r_el.append(rpr)

    t_el = OxmlElement("w:t")
    t_el.text = text
    t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r_el.append(t_el)
    new_p.append(r_el)
    return new_p


def _make_heading_p(text: str, ref=None):
    """Create a generated child-heading while preserving the template's numbering style.

    ``_make_p`` deliberately strips ``w:numPr`` because copied source *body*
    paragraphs must never leak their list numbering into the output.  The
    dynamic sub-headings used under the semantic ``other`` slot are different:
    their visible chapter label must be assigned by the current template's
    numbering definition.  We therefore copy the
    heading paragraph properties intact, including ``w:numPr``; no numeric
    prefix is generated or stored in Python.  If no heading reference exists,
    the caller still gets a normal paragraph and the template can style it.
    """
    new_p = OxmlElement("w:p")
    if ref is not None:
        src_ppr = ref._p.find(qn("w:pPr"))
        if src_ppr is not None:
            # Keep style, outline level and numbering exactly as supplied by
            # this template.  This is what lets Word renumber inserted nodes
            # after customers add/reorder chapters in a later template.
            new_p.append(copy.deepcopy(src_ppr))

    r_el = OxmlElement("w:r")
    ref_rpr = None
    if ref is not None:
        for ref_r in ref._p.findall(qn("w:r")):
            ref_rpr = ref_r.find(qn("w:rPr"))
            if ref_rpr is not None:
                break
    if ref_rpr is not None:
        r_el.append(copy.deepcopy(ref_rpr))
    else:
        rpr = OxmlElement("w:rPr")
        fonts = OxmlElement("w:rFonts")
        fonts.set(qn("w:ascii"), "仿宋_GB2312")
        fonts.set(qn("w:eastAsia"), "仿宋_GB2312")
        fonts.set(qn("w:hint"), "eastAsia")
        sz = OxmlElement("w:sz"); sz.set(qn("w:val"), "21")
        sz_cs = OxmlElement("w:szCs"); sz_cs.set(qn("w:val"), "21")
        rpr.extend((fonts, sz, sz_cs))
        r_el.append(rpr)

    t_el = OxmlElement("w:t")
    t_el.text = str(text or "")
    t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r_el.append(t_el)
    new_p.append(r_el)
    return new_p

def _find_body_ref(tpl_paras, from_idx):
    for j in range(from_idx + 1, min(from_idx + 6, len(tpl_paras))):
        bp = tpl_paras[j]
        if bp.style and "Body" in bp.style.name:
            return bp
    return None


def _remove_body_element(el) -> None:
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)


def _has_metric_value(text: str) -> bool:
    """
    判断字符串是否含具体指标值（数字+单位/符号），而非纯测试方法描述。
    先剥离标准号（GJB 1217A-2009 等），避免把标准号误判为数值。
    """
    if not text:
        return False
    # 剥离标准号：GJB/GB/GB/T/Q/KJB/MIL + 编号 + 版本 + 年份
    t = re.sub(r"(?:GJB|GB/T|GB|Q/[0-9A-Z]+|KJB|MIL(?:-[A-Z]+)?)\s*[0-9A-Z.]+(?:-\d+)?", " ", text)
    t = re.sub(r"方法\s*\d+", " ", t)        # "方法2003" 之类
    # 动态剥离原文交叉引用编号；该编号只用于值识别，不参与模板定位。
    t = re.sub(r"中\s*\d+(?:\.\d+)*", " ", t)
    if re.search(r"[≤≥＜＞<>]\s*\d", t):
        return True
    if re.search(r"\d+(?:\.\d+)?\s*(?:V|mA|A|mΩ|MΩ|Ω|N|℃|dB|GHz|MHz|Hz|次|ps|mm|μm|W)", t):
        return True
    if re.search(r"[-+]?\d+\s*[～~]\s*[-+]?\d+", t):  # 区间
        return True
    return False


def _refine_adopted(tv: str, stdv: str) -> tuple[str, str]:
    """
    提炼拟采用值。返回 (adopted, audit_note)。
    规则：
      1. 用户值和标准值完全相同 → 采用用户值
      2. 同量纲、同向阈值可确定比较 → 下限取较大、上限取较小
      3. 无法可靠比较 → 暂按用户值，明确记录人工复核，禁止静默选值
      4. 只有其一 → 采用有值的一方
    """
    tv = (tv or "").strip()
    stdv = (stdv or "").strip()
    tv_has = _has_metric_value(tv)
    std_has = _has_metric_value(stdv)

    if tv and stdv:
        if tv_has and std_has:
            tv_norm = re.sub(r"\s+", "", tv)
            std_norm = re.sub(r"\s+", "", stdv)
            if tv_norm == std_norm:
                return tv, ""
            # 同一量纲、同向阈值时采用更严格值：下限取更大，上限取更小。
            # 例如机械寿命 用户≥20次 / 规范≥25次 → 拟采用≥25次。
            threshold_pattern = (
                r"(不小于|不少于|≥|>=|不大于|不超过|≤|<=)\s*"
                r"(-?\d+(?:\.\d+)?)\s*([a-zA-ZμΩ℃%]+|次|小时|h|年)?"
            )
            t_cmp = re.search(threshold_pattern, tv)
            s_cmp = re.search(threshold_pattern, stdv)
            if t_cmp and s_cmp:
                lower_ops = {"不小于", "不少于", "≥", ">="}
                upper_ops = {"<=", "≤", "不大于", "不超过"}
                same_unit = (t_cmp.group(3) or "").lower() == (s_cmp.group(3) or "").lower()
                if same_unit and t_cmp.group(1) in lower_ops and s_cmp.group(1) in lower_ops:
                    return (stdv if float(s_cmp.group(2)) > float(t_cmp.group(2)) else tv), "[严格值裁决] 同向下限取较大值"
                if same_unit and t_cmp.group(1) in upper_ops and s_cmp.group(1) in upper_ops:
                    return (stdv if float(s_cmp.group(2)) < float(t_cmp.group(2)) else tv), "[严格值裁决] 同向上限取较小值"
            return tv, f"[人工复核] 用户要求与标准要求无法自动择严：用户要求={tv}；标准要求={stdv}"
        if not tv_has and std_has:
            return tv, f"[人工复核] 用户要求缺少可比较阈值：用户要求={tv}；标准要求={stdv}"
        if re.sub(r"\s+", "", tv) != re.sub(r"\s+", "", stdv):
            return tv, f"[人工复核] 用户要求与标准要求均无法量化比较：用户要求={tv}；标准要求={stdv}"
        return tv, ""
    return (tv or stdv), ""


def _indicator_basis(adopted: str, user_value: str, standard_value: str, spec_basis: str) -> str:
    """Return the 7-22 basis label for the adopted indicator."""
    normalize = lambda value: re.sub(r"\s+", "", str(value or ""))
    if standard_value and normalize(adopted) == normalize(standard_value) and normalize(adopted) != normalize(user_value):
        refs = re.findall(
            r"(?:GJB(?:/Z)?|GB/T|GB|KJB|Q/[0-9A-Z]+)\s*[0-9A-Z.]+(?:-\d{4})?",
            f"{standard_value} {spec_basis}",
            flags=re.I,
        )
        return "、".join(dict.fromkeys(ref.strip() for ref in refs if ref.strip())) or spec_basis or "产品规范"
    return "用户要求"


def _resolve_indicator_adoption(
    user_value: str,
    standard_value: str,
    spec_basis: str,
    adopt_policy: str = "",
) -> tuple[str, str, str]:
    """Resolve adopted value first, then derive the evidence basis from it."""
    adopted, audit_note = _refine_adopted(user_value, standard_value)
    # 7-22 只允许在可比较且同量纲时“择严”。多维条件更完整并不等于
    # 更严格，不能因为配置了旧版策略就无条件覆盖用户要求。
    if adopt_policy == "standard_if_more_complete" and standard_value and audit_note:
        audit_note = audit_note.replace(
            "[人工复核]", "[人工复核：禁止以完整代替择严]", 1
        )
    basis = _indicator_basis(adopted, user_value, standard_value, spec_basis)
    return adopted, basis, audit_note


def _find_body_ref_after(anchor: Paragraph, limit: int = 8):
    """按真实 XML 相邻关系找正文样式，避免前序插入后 paragraph 索引漂移。"""
    current = anchor._p.getnext()
    checked = 0
    while current is not None and checked < limit:
        if current.tag == qn("w:p"):
            candidate = Paragraph(current, anchor._parent)
            checked += 1
            if candidate.style and "Body" in candidate.style.name:
                return candidate
        current = current.getnext()
    return None


def _other_module_groups(ordered_elements):
    """按来源章节组织“其他要求”，标题编号完全交给当前模板。"""
    groups = []
    by_id = {}
    for item in ordered_elements:
        module_id = str(
            item.get("source_chapter_id")
            or item.get("source_section")
            or item.get("source_id")
            or f"unlabeled-module-{len(groups) + 1}"
        )
        group = by_id.get(module_id)
        if group is None:
            raw_title = str(
                item.get("source_heading")
                or item.get("source_section")
                or "其他未分类要求"
            ).strip()
            # Source headings may carry a display number in either Arabic
            # (``8.4``) or Chinese chapter form (``第八章``).  Keep only the
            # semantic title; the destination template's numbering style is
            # responsible for any visible child-section labels.
            title = re.sub(
                r"^\s*(?:第\s*[一二三四五六七八九十百千万零〇]+\s*章\s*|[（(]\s*[一二三四五六七八九十百千万零〇]+\s*[）)]\s*|[一二三四五六七八九十百千万零〇]+\s*[、.．]|\d+(?:\.\d+)*(?:\s+|[、)）]|[.．](?!\d)))",
                "",
                raw_title,
            ).strip(" ：:")
            group = {
                "module_id": module_id,
                "title": title or "其他未分类要求",
                "items": [],
            }
            groups.append(group)
            by_id[module_id] = group
        group["items"].append(item)
    return groups


def _technical_support_module_groups(ordered_elements):
    """Group acceptance/delivery evidence by its source semantic heading.

    The source chapter title (for example ``验收要求`` or ``交付要求``) is
    the child heading.  Individual source paragraphs and tables remain body
    evidence; promoting every sentence to a heading loses the 7-22 structure.
    """
    groups = []
    by_id = {}
    for item in ordered_elements:
        module_id = str(
            item.get("source_chapter_id")
            or item.get("source_heading")
            or item.get("source_section")
            or item.get("source_id")
            or f"unlabeled-support-module-{len(groups) + 1}"
        )
        group = by_id.get(module_id)
        if group is None:
            raw_title = str(
                item.get("source_heading")
                or item.get("source_section")
                or "条件保障要求"
            ).strip()
            title = re.sub(
                r"^\s*(?:第\s*[一二三四五六七八九十百千万零〇]+\s*章\s*|"
                r"\d+(?:\.\d+)*\s*)",
                "",
                raw_title,
            ).strip(" ：:")
            group = {
                "module_id": module_id,
                "title": title or "条件保障要求",
                "items": [],
            }
            groups.append(group)
            by_id[module_id] = group
        group["items"].append(item)
    return groups


def _dynamic_child_titles(text: str) -> list[str]:
    """Split one evidence paragraph into exact child-title clauses.

    The function only removes source display numbering and splits punctuation.
    It does not summarize, infer, or generate business content. Destination
    numbering remains owned by the selected template.
    """
    cleaned = re.sub(
        r"^\s*(?:\d+(?:\.\d+)*|[（(]?\d+[）)]?)\s*[、.．]?\s*",
        "",
        text or "",
    ).strip()
    if not cleaned:
        return []
    clauses = [
        clause.strip().rstrip("。；;")
        for clause in re.split(r"[；;、\n]+", cleaned)
        if clause.strip().rstrip("。；;")
    ]
    return [f"{clause}。" for clause in clauses]


def _semantic_heading_text(value: str) -> str:
    """Strip only display numbering; the returned title is the identity."""
    text = re.sub(r"\s+", "", str(value or "")).strip(" ：:")
    text = re.sub(
        r"^(?:第[一二三四五六七八九十百千万零〇]+章|[一二三四五六七八九十百千万零〇]+[、.．]|\d+(?:\.\d+)*(?:[、.)）]|\s+))",
        "",
        text,
    )
    return text.strip(" ：:")


def _remove_semantic_section(doc, keywords: list[str] | tuple[str, ...] | str) -> int:
    """Remove a heading subtree using title/outline semantics only."""
    if isinstance(keywords, str):
        keywords = [keywords]
    wanted = [re.sub(r"\s+", "", str(item)) for item in keywords if str(item).strip()]
    if not wanted:
        return 0
    target = None
    target_level = 0
    # Keep the real Paragraph objects while scanning.  Re-wrapping an XML
    # node with ``Paragraph(node, body)`` after removing a sibling loses the
    # document part context in python-docx, so style lookup can fail.  The
    # identity map below lets the deletion walk use only already-bound
    # paragraph objects and their semantic outline levels.
    # Keep the Paragraph wrappers alive for the whole deletion walk.  lxml
    # may create a new Python proxy for the same OOXML node after a temporary
    # ``doc.paragraphs`` list is released; an ``id(node)`` map would then miss
    # the next real heading and could delete every following section.  The
    # retained list keeps the proxies stable, while the equality fallback also
    # covers custom python-docx/lxml builds that still return a fresh proxy.
    paragraphs = list(doc.paragraphs)
    paragraph_levels = {}
    for paragraph in paragraphs:
        paragraph_levels[id(paragraph._p)] = _heading_level(paragraph)
        title = _semantic_heading_text(_txt(paragraph))
        style_name = str(paragraph.style.name if paragraph.style else "")
        is_appendix_anchor = (
            "附录" in re.sub(r"\s+", "", style_name)
            and title.startswith("附录")
        )
        if (
            target is None
            and (_is_heading(paragraph) or is_appendix_anchor)
            and any(key in title for key in wanted)
        ):
            target = paragraph._p
            # Some controlled Word templates use a dedicated appendix style
            # without OOXML outlineLvl.  Treat that semantic appendix marker
            # as a top-level section anchor; identity still comes from its
            # real title, never from a hard-coded chapter number.
            target_level = paragraph_levels[id(paragraph._p)] or (1 if is_appendix_anchor else 0)
    if target is None:
        return 0
    removed = 0
    node = target
    while node is not None:
        next_node = node.getnext()
        if node is not target and node.tag == qn("w:p"):
            # Only headings terminate the subtree.  Ordinary body paragraphs
            # have no entry in ``paragraph_levels`` and are removed with the
            # section.  Never reconstruct a Paragraph for a detached node.
            level = paragraph_levels.get(id(node), 0)
            if not level:
                level = next(
                    (
                        paragraph_levels.get(id(paragraph._p), 0)
                        for paragraph in paragraphs
                        if paragraph._p == node
                    ),
                    0,
                )
            if level and target_level and level <= target_level:
                break
            if level and not target_level:
                break
        elif node is not target and node.tag != qn("w:tbl") and node.tag != qn("w:p"):
            break
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
            removed += 1
        node = next_node
    return removed


def _find_failure_mode_table(doc):
    for table in doc.tables:
        header = "".join(cell.text for cell in table.rows[0].cells) if table.rows else ""
        if "数据所属产品" in header and "失效部位" in header and "失效模式" in header:
            return table
    return None


def _write_failure_cell(tc, text: str) -> None:
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    WNS = f"{{{W}}}"
    for child in list(tc):
        if child.tag == f"{WNS}p":
            tc.remove(child)
    p = OxmlElement("w:p")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = str(text or "")
    r.append(t)
    p.append(r)
    tc.append(p)


def _normalize_failure_mode_table(table) -> None:
    """Rebuild the failure table to the exact five-field 7-22 schema."""
    import copy as _copy

    canonical_headers = (
        "数据所属产品的产品名称",
        "失效部位",
        "失效模式（故障现象）",
        "失效分析",
        "可靠性设计方法（设计改进措施）",
    )
    aliases = (
        ("数据所属产品的产品名称", "数据所属产品"),
        ("失效部位",),
        ("失效模式（故障现象）", "失效模式", "故障现象"),
        ("失效分析", "故障原因"),
        ("可靠性设计方法（设计改进措施）", "可靠性设计方法", "设计改进措施"),
    )
    rows = list(table._tbl.findall(qn("w:tr")))
    if not rows:
        return
    header_cells = rows[0].findall(qn("w:tc"))
    header_texts = [
        re.sub(
            r"\s+",
            "",
            "".join(node.text or "" for node in cell.findall(".//" + qn("w:t"))),
        )
        for cell in header_cells
    ]
    selected: list[int] = []
    for field_aliases in aliases:
        index = next(
            (
                position
                for position, text in enumerate(header_texts)
                if position not in selected
                and any(re.sub(r"\s+", "", alias) in text for alias in field_aliases)
            ),
            None,
        )
        if index is None:
            index = min(len(selected), max(len(header_cells) - 1, 0))
        selected.append(index)

    for row in rows:
        cells = row.findall(qn("w:tc"))
        chosen = [
            _copy.deepcopy(cells[index])
            if index < len(cells)
            else _copy.deepcopy(cells[-1])
            for index in selected
            if cells
        ]
        for cell in cells:
            row.remove(cell)
        for cell in chosen:
            # The controlled template used merged header cells in one historic
            # revision.  python-docx exposes a horizontally merged cell more
            # than once through ``row.cells``; writing through that API can
            # therefore overwrite the preceding field and recreate the
            # duplicated "可靠性设计方法" column.  Once the five logical
            # columns have been selected they must be five independent OOXML
            # cells.
            tc_pr = cell.find(qn("w:tcPr"))
            if tc_pr is not None:
                for merge_tag in (qn("w:gridSpan"), qn("w:vMerge")):
                    for merge_node in list(tc_pr.findall(merge_tag)):
                        tc_pr.remove(merge_node)
            row.append(cell)

    grid = table._tbl.tblGrid
    if grid is not None:
        columns = grid.findall(qn("w:gridCol"))
        chosen_columns = [
            _copy.deepcopy(columns[index])
            if index < len(columns)
            else _copy.deepcopy(columns[-1])
            for index in selected
            if columns
        ]
        for column in columns:
            grid.remove(column)
        for column in chosen_columns:
            grid.append(column)

    # Write to the physical XML cells, not python-docx's expanded cell view.
    # This is what guarantees the exact five distinct 7-22 headers.
    normalized_header_cells = rows[0].findall(qn("w:tc"))
    for cell, value in zip(normalized_header_cells, canonical_headers):
        _write_failure_cell(cell, value)


def _fill_failure_mode_table(
    doc,
    records: list[dict],
    *,
    no_match_message: str | None = None,
) -> int:
    """Fill the semantically identified failure table, preserving its layout."""
    import copy as _copy
    table = _find_failure_mode_table(doc)
    if table is None:
        return 0
    _normalize_failure_mode_table(table)
    rows = list(table._tbl.findall(qn("w:tr")))
    if not rows:
        return 0
    template_row = _copy.deepcopy(rows[1] if len(rows) > 1 else rows[0])
    for row in rows[1:]:
        table._tbl.remove(row)
    rows_to_write = list(records)
    if not rows_to_write and no_match_message:
        rows_to_write = [{"product_name": no_match_message}]
    for record in rows_to_write:
        row = _copy.deepcopy(template_row)
        cells = row.findall(qn("w:tc"))
        values = (
            record.get("product_name", ""),
            record.get("failure_location", ""),
            record.get("failure_mode", ""),
            record.get("failure_analysis", ""),
            record.get("reliability_design_method", ""),
        )
        for cell, value in zip(cells, values):
            _write_failure_cell(cell, value)
        table._tbl.append(row)
    apply_table_style(table, "failure")
    return len(rows_to_write)


def _find_potential_failure_analysis_table(doc):
    """Find the 5.2 FMEA table by its semantic field, never by position."""
    for table in doc.tables:
        header = "".join(cell.text for cell in table.rows[0].cells) if table.rows else ""
        if "可能发生的失效模式" in re.sub(r"\s+", "", header):
            return table
    return None


def _fill_potential_failure_analysis_table(
    doc,
    records: list[dict],
) -> int:
    """Seed 5.2 only with the matched 5.1 failure-mode evidence.

    The 7-22 rule requires the historical modes from 5.1 to appear in the
    ``可能发生的失效模式`` column of 5.2.  The mechanism, impact and solution
    columns remain the designer's work and are intentionally untouched.
    """
    table = _find_potential_failure_analysis_table(doc)
    if table is None or not table.rows:
        return 0
    headers = [
        re.sub(r"\s+", "", cell.text or "")
        for cell in table.rows[0].cells
    ]
    mode_column = next(
        (index for index, text in enumerate(headers) if "可能发生的失效模式" in text),
        None,
    )
    if mode_column is None or len(table.rows) < 2:
        return 0

    modes = [
        str(record.get("failure_mode") or "").strip()
        for record in records
        if str(record.get("failure_mode") or "").strip()
    ]
    if not modes:
        return 0

    template_row = copy.deepcopy(table._tbl.findall(qn("w:tr"))[1])
    while len(table.rows) - 1 < len(modes):
        table._tbl.append(copy.deepcopy(template_row))

    for row, mode in zip(table.rows[1:], modes):
        if mode_column >= len(row.cells):
            continue
        _write_failure_cell(row.cells[mode_column]._tc, mode)
    apply_table_style(table, "failure")
    return len(modes)


def _set_paragraph_text_preserving_style(paragraph: Paragraph, text: str) -> None:
    """Replace visible text while retaining the template's heading style."""
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


def _replace_section_body_with_manual_note(
    doc,
    semantic_titles: tuple[str, ...],
    output_title: str,
    note: str,
) -> int:
    """Keep a semantic template section, remove its sample body, add a note."""
    wanted = [
        re.sub(r"\s+", "", str(title))
        for title in semantic_titles
        if str(title).strip()
    ]
    if not wanted:
        return 0

    paragraphs = list(doc.paragraphs)
    target = None
    target_level = 0
    for paragraph in paragraphs:
        style_name = str(paragraph.style.name if paragraph.style else "")
        appendix_anchor = (
            "附录" in re.sub(r"\s+", "", style_name)
            and _semantic_heading_text(_txt(paragraph)).startswith("附录")
        )
        title = re.sub(r"\s+", "", _semantic_heading_text(_txt(paragraph)))
        if (
            (_is_heading(paragraph) or appendix_anchor)
            and any(key in title for key in wanted)
        ):
            target = paragraph
            target_level = _heading_level(paragraph) or (1 if appendix_anchor else 0)
            break
    if target is None:
        return 0

    body_ref = None
    to_remove = []
    node = target._p.getnext()
    while node is not None:
        next_node = node.getnext()
        if node.tag == qn("w:p"):
            candidate = Paragraph(node, target._parent)
            candidate_level = _heading_level(candidate)
            if candidate_level and target_level and candidate_level <= target_level:
                break
            if body_ref is None and not candidate_level:
                body_ref = candidate
        to_remove.append(node)
        node = next_node

    for node in to_remove:
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    _set_paragraph_text_preserving_style(target, output_title)
    target._p.addnext(_make_p(note, body_ref))
    return 1


def _classification_has_role(classification: dict | None, role: str) -> bool:
    if not classification:
        return False
    return any(
        str(item.get("category", "")) == role
        for item in classification.get("classifications", [])
    )


def _classification_has_quality_evidence(
    classification: dict | None,
    evidence_roles: tuple[str, ...],
    indicator_signals: tuple[str, ...],
) -> tuple[bool, list[str]]:
    """Find source-backed quality evidence without relying on chapter numbers."""
    if not classification:
        return False, []
    blocks = {
        str(block.get("id")): block
        for block in classification.get("source_blocks", [])
        if isinstance(block, dict) and block.get("id")
    }
    chapters = {
        str(chapter.get("id")): chapter
        for chapter in classification.get("source_chapters", [])
        if isinstance(chapter, dict) and chapter.get("id")
    }
    matched: list[str] = []
    role_set = set(evidence_roles)
    for item in classification.get("classifications", []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("category", ""))
        source_id = str(item.get("source_id", ""))
        block = blocks.get(source_id, {})
        chapter = chapters.get(
            str(item.get("chapter_id") or block.get("chapter_id") or ""), {}
        )
        evidence_text = " ".join(
            str(value or "")
            for value in (
                chapter.get("heading_text"),
                block.get("heading_text"),
                block.get("section"),
                block.get("text"),
            )
        )
        if role in role_set or (
            role == "performance_indicator"
            and any(signal in evidence_text for signal in indicator_signals)
        ):
            matched.append(source_id)
    return bool(matched), list(dict.fromkeys(matched))


def _apply_process_specific_sections(doc, classification: dict | None, process: str, product_label: str, product_series: str, out_path: str) -> dict:
    """Apply 7-22 process rules without binding behavior to section numbers."""
    from jonhon_taskbook.development_process_policy import (
        new_process_manual_section_rules,
        non_new_remove_section_rules,
        normalize_development_process,
        quality_section_evidence_rules,
    )
    from jonhon_taskbook.failure_mode_matcher import match_failure_modes_with_audit
    from jonhon_taskbook.failure_mode_policy import failure_no_match_policy
    process = normalize_development_process(process)
    audit: dict = {
        "process": process,
        "product_label": product_label,
        "product_series": product_series,
        # 交付门禁据此排除“本流程已按受控规则删除”的标题。
        # 这里只记录真实发生的语义标题删除，不记录章节号。
        "deleted_semantic_headings": [],
    }
    if process in {"改型II", "改型III"}:
        audit["failure_mode_records"] = []
        audit["failure_mode_action"] = "delete"
        audit["potential_failure_mode_rows"] = 0
        audit["deleted_failure_section_nodes"] = _remove_semantic_section(doc, "初步的失效模式分析")
    else:
        records, failure_match_audit = match_failure_modes_with_audit(
            product_label,
            product_series,
        )
        audit["failure_mode_match_audit"] = failure_match_audit
        audit["failure_mode_records"] = records
        if records:
            audit["failure_mode_action"] = "fill"
            audit["failure_mode_rows"] = _fill_failure_mode_table(doc, records)
            audit["potential_failure_mode_rows"] = (
                _fill_potential_failure_analysis_table(doc, records)
            )
        else:
            no_match = failure_no_match_policy()
            audit["failure_mode_action"] = no_match["action"]
            audit["failure_mode_rows"] = _fill_failure_mode_table(
                doc,
                [],
                no_match_message=no_match["text"],
            )
            audit["potential_failure_mode_rows"] = 0
            audit["failure_mode_reason"] = (
                "故障模式库无适用产品/系列记录，按7-22受控规则写入无历史记录标识"
            )

    if process == "全新":
        manual_sections = []
        for rule in new_process_manual_section_rules():
            updated = _replace_section_body_with_manual_note(
                doc,
                rule["semantic_titles"],
                rule["output_title"],
                rule["note"],
            )
            manual_sections.append(
                {
                    "id": rule["id"],
                    "semantic_titles": list(rule["semantic_titles"]),
                    "output_title": rule["output_title"],
                    "note": rule["note"],
                    "updated": bool(updated),
                }
            )
        audit["new_process_manual_sections"] = manual_sections

    quality_sections = quality_section_evidence_rules()
    if process != "全新":
        deleted_process_sections = []
        for rule in non_new_remove_section_rules():
            count = _remove_semantic_section(doc, rule["semantic_titles"])
            deleted_process_sections.append(
                {
                    "id": rule["id"],
                    "semantic_titles": list(rule["semantic_titles"]),
                    "reason": rule["reason"],
                    "removed_nodes": count,
                    "deleted": bool(count),
                }
            )
            if count:
                audit["deleted_semantic_headings"].extend(rule["semantic_titles"])
        audit["deleted_process_sections"] = deleted_process_sections

        deleted = []
        retained_quality_evidence = []
        for rule in quality_sections:
            title = rule["semantic_title"]
            has_evidence, source_ids = _classification_has_quality_evidence(
                classification,
                rule["evidence_roles"],
                rule["indicator_signals"],
            )
            if not has_evidence:
                count = _remove_semantic_section(doc, title)
                if count:
                    deleted.append(title)
                    audit["deleted_semantic_headings"].append(title)
            else:
                retained_quality_evidence.append(
                    {
                        "id": rule["id"],
                        "semantic_title": title,
                        "source_ids": source_ids,
                    }
                )
        audit["deleted_quality_sections"] = deleted
        audit["retained_quality_evidence"] = retained_quality_evidence
        if len(deleted) == len(quality_sections):
            audit["deleted_quality_parent_nodes"] = _remove_semantic_section(doc, "通用质量特性要求")
            if audit["deleted_quality_parent_nodes"]:
                audit["deleted_semantic_headings"].append("通用质量特性要求")
    audit["deleted_semantic_headings"] = list(dict.fromkeys(audit["deleted_semantic_headings"]))
    Path(out_path).with_suffix(".process_rule_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    failure_audit = {
        "schema_version": "failure-mode-match-audit-v1",
        "development_process": process,
        "query_executed": process not in {"改型II", "改型III"},
        "action": audit.get("failure_mode_action", ""),
        "rows_written": int(audit.get("failure_mode_rows", 0) or 0),
        "potential_analysis_rows_written": int(
            audit.get("potential_failure_mode_rows", 0) or 0
        ),
        "match": audit.get("failure_mode_match_audit", {}),
        "records": audit.get("failure_mode_records", []),
        "reason": audit.get(
            "failure_mode_reason",
            "该流程按7-22规则删除失效模式章节"
            if process in {"改型II", "改型III"}
            else "",
        ),
    }
    Path(out_path).with_suffix(".failure_mode_audit.json").write_text(
        json.dumps(failure_audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return audit


def _apply_domain_specific_sections(doc, domain: str, out_path: str) -> dict:
    """Prune domain-only template subtrees by semantic heading, never number."""
    normalized = str(domain or "").strip().lower()
    audit = {"domain": normalized, "deleted_sections": []}
    rules = (
        (
            normalized not in {"airworthiness", "civil_aviation"},
            ("适航要求",),
            "适航要求",
        ),
        (
            normalized != "as9100",
            ("原材料/元器件过时淘汰风险",),
            "原材料/元器件过时淘汰风险（AS9100）",
        ),
    )
    for should_delete, keywords, label in rules:
        if not should_delete:
            continue
        removed = _remove_semantic_section(doc, keywords)
        if removed:
            audit["deleted_sections"].append(
                {"semantic_heading": label, "removed_nodes": removed}
            )
    Path(out_path).with_suffix(".domain_rule_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return audit


def _apply_compilation_basis(
    doc,
    tech_path: str,
    spec_path: str,
    out_path: str,
) -> dict:
    """Use the two uploaded source identities to rebuild compilation basis.

    Both the user requirement and the product specification are controlled
    inputs.  The template only owns the position and formatting; its example
    entries are never treated as source evidence.
    """
    from jonhon_taskbook.document_identity import read_document_identity

    identities = [
        ("tech", Path(tech_path), read_document_identity(tech_path, "tech")),
        ("spec", Path(spec_path), read_document_identity(spec_path, "spec")),
    ]
    sources: list[dict] = []
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for kind, source_path, identity in identities:
        title = str(identity.get("title", "")).strip() or source_path.stem
        number = str(identity.get("number", "")).strip()
        key = (title, number)
        if key in seen:
            continue
        seen.add(key)
        line = f"《{title}》，编号：{number}；" if number else f"《{title}》；"
        lines.append(line)
        sources.append(
            {
                "kind": kind,
                "source_file": source_path.name,
                "title": title,
                "number": number,
                "version": str(identity.get("version", "")).strip(),
                "inserted_line": line,
            }
        )
    heading = next(
        (
            paragraph
            for paragraph in doc.paragraphs
            if _is_heading(paragraph) and "任务书编制依据" in _txt(paragraph)
        ),
        None,
    )
    if heading is None:
        raise ValueError("模板缺少“任务书编制依据”语义标题")
    reference = _find_body_ref_after(heading)
    level = _heading_level(heading) or _heading_depth_sv(heading)
    scan = heading._p.getnext()
    removed = 0
    while scan is not None:
        next_node = scan.getnext()
        scan_level = 0
        if scan.tag == qn("w:p"):
            paragraph = Paragraph(scan, heading._parent)
            scan_level = _heading_level(paragraph) or _heading_depth_sv(paragraph)
        if scan_level and scan_level <= level:
            break
        parent = scan.getparent()
        if parent is not None:
            parent.remove(scan)
            removed += 1
        scan = next_node
    previous = heading._p
    for line in lines:
        node = _make_p(line, reference)
        previous.addnext(node)
        previous = node
    tech_identity = next(item for item in sources if item["kind"] == "tech")
    audit = {
        "policy": "uploaded_tech_and_spec_only",
        "source_file": tech_identity["source_file"],
        "title": tech_identity["title"],
        "number": tech_identity["number"],
        "inserted_line": tech_identity["inserted_line"],
        "sources": sources,
        "inserted_lines": lines,
        "removed_template_nodes": removed,
        "passed": len(sources) == 2 and all(item["title"] for item in sources),
    }
    Path(out_path).with_suffix(".compilation_basis_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return audit


def _canonical_indicator_name(name: str) -> str:
    value = re.sub(r"[\s：:（）()]+", "", str(name))
    aliases = (
        (("额定电流", "额定载流量"), "额定电流"),
        (("冲击电流", "脉冲电流"), "冲击电流"),
        (("其他接点总载流", "其他接点总电流"), "其他接点总载流"),
        # “插入力/分离力/分离扭矩”可能分别描述单针、接触件或整机，
        # 不能仅凭词面统一并入“插拔力”。是否合并必须由本次来源证据和
        # 受控指标定义决定。
        (("插拔力", "总插拔力", "插合分离力"), "插拔力"),
        # V3 底层表单与受控模板的显示名不同，但它们指向同一模板槽位。
        (("总分离力或分离扭矩", "总分离力"), "总分离力或分离扭矩"),
        (("低温低气压", "低气压"), "低温低气压"),
        (("环境温度", "工作温度"), "工作温度"),
        (("机械寿命", "插拔寿命"), "机械寿命"),
        (("灵巧指按压力", "按钮按压力", "按压力", "承压力"), "按压力"),
    )
    for candidates, canonical in aliases:
        if any(candidate in value for candidate in candidates):
            return canonical
    return value


def _canonical_indicator_category(category: str) -> str:
    """收敛指标清单与模板的性能域名称，避免同类指标拆成两个分组。"""
    value = re.sub(r"\s+", "", str(category or ""))
    aliases = (
        (("电性能", "电气性能"), "电性能"),
        (("机械性能", "机械性能要求"), "机械性能"),
        (("环境性能", "环境性能要求"), "环境性能"),
        (("光性能", "光学性能"), "光性能"),
    )
    for candidates, canonical in aliases:
        if value in candidates:
            return canonical
    return value or "其他"


def _apply_profile_route_overrides(
    classification: dict | None,
    cfg: dict | None,
) -> list[dict]:
    """Route configured independent indicators to semantic taskbook slots.

    The indicator table is only one output mode. A heading such as a life-cycle
    measure can have a dedicated quality chapter and must not become a 4.1 row.
    Profiles declare these aliases; no product name or chapter number is
    embedded in the executable pipeline.
    """
    if not isinstance(classification, dict) or not isinstance(cfg, dict):
        return []
    routes = cfg.get("indicator_excluded_routes") or {}
    if not isinstance(routes, dict):
        return []
    normalized_routes = {
        _canonical_indicator_name(str(name)): str(role).strip()
        for name, role in routes.items()
        if str(name).strip() and str(role).strip()
    }
    if not normalized_routes:
        return []
    blocks = {
        str(block.get("id")): block
        for block in classification.get("source_blocks", [])
        if isinstance(block, dict) and block.get("id")
    }
    chapters = {
        str(chapter.get("id")): chapter
        for chapter in classification.get("source_chapters", [])
        if isinstance(chapter, dict) and chapter.get("id")
    }
    changed: list[dict] = []
    for item in classification.get("classifications", []):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id", ""))
        block = blocks.get(source_id, {})
        chapter = chapters.get(str(item.get("chapter_id") or block.get("chapter_id")), {})
        heading = str(
            chapter.get("heading_text")
            or block.get("heading_text")
            or block.get("section")
            or ""
        )
        semantic_heading = re.sub(r"^\s*\d+(?:\.\d+)*\s*", "", heading)
        target = normalized_routes.get(_canonical_indicator_name(semantic_heading))
        if not target or str(item.get("category", "")) == target:
            continue
        previous = item.get("category", "")
        item["category"] = target
        item["method"] = f"profile_route_override:{previous}->{target}"
        item["reason"] = f"受控配置将独立指标标题“{semantic_heading.strip()}”路由到语义槽位 {target}"
        changed.append(
            {
                "source_id": source_id,
                "chapter_id": str(item.get("chapter_id") or block.get("chapter_id") or ""),
                "source_heading": semantic_heading.strip(),
                "content_hash": str(block.get("content_hash") or ""),
                "from": previous,
                "to": target,
                "policy": "configured_independent_semantic_route",
            }
        )
    return changed


def _write_profile_route_audit(
    out_path: str,
    classification: dict | None,
    route_overrides: list[dict],
    cfg: dict | None,
) -> None:
    """Persist both the raw-to-effective delta and the effective classification.

    The classifier sidecar remains the immutable model output.  This second
    sidecar proves which controlled profile rule changed a route before OOXML
    assembly, so an apparently correct DOCX is never attributed to an opaque
    one-off edit.
    """
    if not isinstance(classification, dict):
        return
    output = Path(out_path)
    configured_routes = (
        dict((cfg or {}).get("indicator_excluded_routes") or {})
        if isinstance(cfg, dict)
        else {}
    )
    audit = {
        "schema_version": "1.0",
        "policy": (
            "The raw LLM classification is preserved. Controlled profile aliases "
            "may move independent requirements out of the indicator table before "
            "deterministic DOCX assembly; no chapter number or product name is used."
        ),
        "configured_routes": configured_routes,
        "applied_count": len(route_overrides),
        "applied": route_overrides,
    }
    output.with_suffix(".profile_route_overrides.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    effective = copy.deepcopy(classification)
    effective["effective_policy"] = {
        "profile_route_overrides_applied": len(route_overrides),
        "raw_classification_sidecar": output.with_suffix(
            ".requirement_classification.json"
        ).name,
        "route_audit_sidecar": output.with_suffix(
            ".profile_route_overrides.json"
        ).name,
    }
    output.with_suffix(".effective_requirement_classification.json").write_text(
        json.dumps(effective, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _select_indicator_value(text: str, indicator: dict) -> str:
    """从同一技术要求段落中按受控语义片段拆分指标，不生成或改写原文。"""
    includes = [str(x) for x in indicator.get("value_include_keywords", []) if str(x)]
    excludes = [str(x) for x in indicator.get("value_exclude_keywords", []) if str(x)]
    patterns = [str(x) for x in indicator.get("value_patterns", []) if str(x)]
    if patterns:
        matches: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text or ""):
                value = match.group(0).strip()
                if not value:
                    continue
                if indicator.get("preserve_scope_context"):
                    # 只把同一枚举子句中、原文真实存在的产品范围前缀带回；
                    # 例如“1、小型……芯数为8芯”与“2、大型……芯数≥20芯”。
                    # 这不是生成文本，也不依赖具体型号、章节号或样例数值。
                    prefix = (text or "")[: match.start()]
                    enumerations = list(re.finditer(r"(?:^|[；;。])\s*\d+\s*[、.)）]", prefix))
                    clause_start = enumerations[-1].end() if enumerations else 0
                    scope_prefix = prefix[clause_start:].strip(" \t\r\n，,；;。")
                    scope_match = re.search(
                        r"([^；;。]{0,80}?(?:芯数|接点数|针数|位数)"
                        r"\s*(?:为|是|[:：=]|≥|≤|>|<)?\s*"
                        r"\d+(?:\.\d+)?(?:\s*[~～至-]\s*\d+(?:\.\d+)?)?\s*芯?)",
                        scope_prefix,
                    )
                    if scope_match:
                        scope = scope_match.group(1).strip(" \t\r\n，,；;。")
                        if scope and scope not in value:
                            value = f"{scope}，{value}"
                matches.append(value)
        return "；".join(dict.fromkeys(x for x in matches if x))
    if not includes:
        return text
    parts = [x.strip() for x in re.split(r"(?=\d+、)|[；;]", text or "") if x.strip()]
    selected = [
        part for part in parts
        if any(keyword in part for keyword in includes)
        and not any(keyword in part for keyword in excludes)
    ]
    return "；".join(selected)


def _indicator_value_is_source_backed(value: str, source_blob: str) -> bool:
    """Verify that every emitted indicator fragment occurs in the design input.

    A single source paragraph may contain several independently governed
    indicators.  The deterministic extractor is allowed to split that
    paragraph into semicolon-separated, verbatim fragments, but it is not
    allowed to synthesize wording or numbers.  Therefore the gate checks each
    emitted fragment separately instead of requiring the newly joined value to
    occur as one contiguous source substring.
    """
    normalized_value = re.sub(r"\s+", "", str(value or ""))
    if not normalized_value:
        return True
    # A governed row may combine two non-adjacent fragments from the same
    # original clause, for example the product scope prefix and its rated
    # current after the intervening pulse-current fragment is routed to a
    # separate row.  Each punctuation-delimited atom must still be verbatim.
    fragments = [
        fragment.strip("，,。；;")
        for fragment in re.split(r"[；;，,。]", normalized_value)
        if fragment.strip("，,。；;")
    ]
    return bool(fragments) and all(fragment in source_blob for fragment in fragments)


def _build_spec_table_ledger(spec_path: str) -> dict[str, list[dict]]:
    """把产品规范所有受控指标表接成通用台账，不再只依赖“型号列”。"""
    ledger: dict[str, list[dict]] = {}
    if not spec_path:
        return ledger
    from jonhon_taskbook.spec_extractor import extract_spec_chapter3_tables
    for item in extract_spec_chapter3_tables(spec_path):
        key = _canonical_indicator_name(item.item_name)
        metric_value = str(item.spec or "").strip()
        if not metric_value:
            # 无独立“要求”列时沿用原有整行提取，但不要把试验方法文本当成
            # 可择严的指标值；方法仍保留在 display_value 和审计台账中。
            metric_value = re.sub(
                r"(?:；)?试验方法：.*$", "", str(item.standard_text or "")
            ).strip("； ")
        ledger.setdefault(key, []).append({
            "name": item.item_name,
            "value": metric_value,
            "display_value": item.standard_text,
            "test_method": item.test_method,
            "section": item.source_section,
            "caption": item.table_caption,
            "scope": item.applicable_model or item.category_or_series,
        })
    return ledger


def _extract_spec_identifier(spec, spec_path: str) -> str:
    """Read the uploaded product-specification identifier without inventing it."""
    texts = [str(paragraph.text or "") for paragraph in getattr(spec, "paragraphs", [])]
    for table in getattr(spec, "tables", []):
        texts.extend(cell.text for row in table.rows for cell in row.cells)
    joined = "\n".join(texts)
    patterns = (
        r"Q/[0-9A-Z]+(?:[./-][0-9A-Z]+)*-\d{4}",
        r"(?:GJB(?:/Z)?|GB/T|GB|KJB)\s*[0-9A-Z.]+(?:-\d{4})?",
    )
    for pattern in patterns:
        match = re.search(pattern, joined, re.I)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip()
    return Path(spec_path).stem if spec_path else "产品规范"


def _scope_matches(scope: str, product_label: str = "", product_series: str = "") -> bool:
    """判断产品规范中的适用范围是否明确覆盖本次产品。"""
    return _scope_match_rank(scope, product_label, product_series) >= 0


def _scope_match_rank(scope: str, product_label: str = "", product_series: str = "") -> int:
    """Return the specificity of a product-scope match.

    A series match is more specific than a product-family match.  The rank is
    used only to choose among already extracted specification rows; it never
    creates a match when the controlled product/series selection is absent.
    """
    scope = re.sub(r"\s+", "", str(scope or "")).lower()
    if not scope:
        return 0

    def _scope_forms(value: str) -> set[str]:
        """Return explicit model/series phrases without free substring matching."""
        normalized = re.sub(r"\s+", "", str(value or "")).lower()
        if not normalized:
            return set()
        forms: set[str] = set()
        for segment in re.split(r"[、,，;；|/（）()\n]+", normalized):
            segment = segment.strip("：:、,，;；")
            if not segment:
                continue
            forms.add(segment)
            segment = re.sub(
                r"^(?:仅)?适用于|^适用(?:于)?|^型号为|^型号|^系列为|^系列|^产品类别为|^产品类别|^类别为|^类别",
                "",
                segment,
            )
            segment = segment.strip("：:、,，;；")
            if not segment:
                continue
            forms.add(segment)
            trimmed = re.sub(r"(?:系列|型号|型|产品|连接器)$", "", segment).strip()
            if trimmed:
                forms.add(trimmed)
        return forms

    scope_forms = _scope_forms(scope)
    product_forms = _scope_forms(product_label)
    series_forms = _scope_forms(product_series)
    # 规则优先避免错用其他型号的规范值：只认可明确的范围短语相等，
    # 不再使用 “J599 in J599A” 这类双向包含的模糊命中。
    if series_forms and scope_forms.intersection(series_forms):
        return 2
    if product_forms and scope_forms.intersection(product_forms):
        return 1
    return -1


def _match_spec_table_indicator(
    ledger: dict[str, list[dict]],
    indicator: dict,
    *,
    product_label: str = "",
    product_series: str = "",
    allow_scoped: bool = True,
) -> dict | None:
    direct_names = (
        [indicator.get("name", "")]
        + list(indicator.get("std_kws", []))
        + list(indicator.get("spec_kws", []))
    )
    related_names = list(indicator.get("related_kws", []))

    def _collect(names: list[str]) -> list[dict]:
        candidates: list[dict] = []
        for name in names:
            key = _canonical_indicator_name(name) if name else ""
            if key:
                candidates.extend(ledger.get(key, []))
        unique_candidates: list[dict] = []
        seen_candidates: set[tuple[str, ...]] = set()
        for item in candidates:
            signature = tuple(str(item.get(field, "")) for field in (
                "name", "value", "display_value", "test_method", "scope", "section", "caption",
            ))
            if signature not in seen_candidates:
                seen_candidates.add(signature)
                unique_candidates.append(item)
        return unique_candidates

    direct_candidates = _collect(direct_names)
    related_candidates = _collect(related_names)
    exact_names = {str(x) for x in indicator.get("spec_exact_names", []) if str(x)}

    if exact_names and direct_candidates:
        exact = [item for item in direct_candidates if item.get("name") in exact_names]
        direct_candidates = exact or direct_candidates

    # 关联词只作为直接指标名没有可用规范行时的检索回退，不能改变用户
    # 指标的身份。例如“工作电流”可以从规范表的“额定电流”行取标准值，
    # 但不会因此额外创建一个“额定电流”用户指标。
    condition_terms = (
        "仅适用于", "适用于", "不适用于", "验收级", "鉴定级", "准鉴定级",
        "等级", "某型", "某系列",
    )

    groups = [
        ("direct", direct_candidates),
        ("related", related_candidates),
    ]
    all_candidates: list[dict] = []
    all_seen: set[tuple[str, ...]] = set()
    for _, group in groups:
        for item in group:
            signature = tuple(str(item.get(field, "")) for field in (
                "name", "value", "display_value", "test_method", "scope", "section", "caption",
            ))
            if signature not in all_seen:
                all_seen.add(signature)
                all_candidates.append(item)

    if not all_candidates:
        return None

    chosen: list[dict] = []
    selection = "none"
    match_origin = "direct"
    for origin, candidates in groups:
        if not candidates:
            continue
        scoped = [
            (_scope_match_rank(item.get("scope", ""), product_label, product_series), item)
            for item in candidates
            if item.get("scope")
        ]
        applicable_scoped = (
            [(rank, item) for rank, item in scoped if rank > 0]
            if allow_scoped
            else []
        )
        if applicable_scoped:
            best_rank = max(rank for rank, _ in applicable_scoped)
            chosen = [item for rank, item in applicable_scoped if rank == best_rank]
            selection = "scoped"
            match_origin = origin
            break

        general = [
            item for item in candidates
            if not item.get("scope")
            and not any(term in str(item.get("value", "")) for term in condition_terms)
        ]
        if general:
            chosen = general
            selection = "general"
            match_origin = origin
            break

    if not chosen:
        return {
            "value": "",
            "basis": "",
            "items": [],
            "inapplicable": True,
            "rejected_items": all_candidates,
            "selection": "none",
            "match_origin": match_origin,
        }
    value = "；".join(dict.fromkeys(str(item["value"]) for item in chosen if item.get("value")))
    display_value = "；".join(dict.fromkeys(
        str(item.get("display_value") or item.get("value") or "")
        for item in chosen
        if item.get("display_value") or item.get("value")
    ))
    basis = "、".join(dict.fromkeys(
        f"{item.get('section', '')}{' ' + item.get('caption', '') if item.get('caption') else ''}".strip()
        for item in chosen
    ))
    return {
        "value": value,
        "display_value": display_value,
        "basis": basis,
        "items": chosen,
        "inapplicable": False,
        "rejected_items": [item for item in all_candidates if item not in chosen],
        "selection": selection,
        "match_origin": match_origin,
    }


def _find_value_by_semantics(paras: list, keywords: list[str]) -> tuple[str, str]:
    """按标题/正文语义找指标值，返回(值, 实际来源标题)，不依赖章节号。"""
    keywords = [str(k).strip() for k in keywords if str(k).strip()]
    if not keywords:
        return "", ""
    # 先找标题命中，再在该标题范围内取正文。这样“振动试验”标准清单行不会
    # 抢在真正的“振动”指标标题之前命中。
    for index, para in enumerate(paras):
        text = (para.text or "").strip()
        if not getattr(para, "is_heading", bool(para.sec_num)) or not text or not any(keyword in text for keyword in keywords):
            continue
        source_heading = text
        source_depth = para.depth
        values: list[str] = []
        for following in paras[index + 1:]:
            if getattr(following, "is_heading", bool(following.sec_num)) and following.depth <= source_depth:
                break
            value = (following.text or "").strip()
            if value and not getattr(following, "is_heading", bool(following.sec_num)):
                values.append(value)
        if values:
            # 同一语义标题下可能连续列出多个产品范围或多个约束段。
            # 这些段落都属于同一指标的用户要求，不能只取第一段，否则会
            # 出现“小型产品保留、大型产品丢失”的静默数据损失。
            # 这里只做原文片段拼接，不生成、不总结、不改写任何技术事实。
            return "；".join(dict.fromkeys(values)), source_heading
    for para in paras:
        text = (para.text or "").strip()
        if text and any(keyword in text for keyword in keywords):
            return text, text
    return "", ""


def _standard_line(text: str, prefixes: tuple[str, ...]) -> str:
    """识别标准条目；允许前面存在项目符号，但不依赖其所在章节。"""
    value = re.sub(r"^[\s·•●○\-—–（(]*\d*[）).、\s]*", "", (text or "").strip())
    return value if value.startswith(prefixes) else ""


def _sort_standards_semantic(lines: list[str], sort_order: list | None = None) -> list[str]:
    """按产品 Profile 声明的标准族和标准号数值排序。"""
    return sort_standards(lines, sort_order)


def _classified_indicator_evidence(
    classification: dict | None,
    keywords: list[str] | tuple[str, ...] | set[str],
) -> tuple[str, str, list[str]]:
    """从已经完成的语义分类中提取技术指标原文证据。

    这是 4.1 指标表的输入边界：只有被路由为 ``performance_indicator`` 的
    原文块才允许激活指标。普通段落、引用标准、模板示例和其它语义槽位即使
    出现同一个词，也不能成为用户指标来源。返回值为 ``(原文值, 语义来源,
    source_ids)``，只拼接原文，不生成或改写技术事实。
    """
    if not isinstance(classification, dict):
        return "", "", []
    signals = [
        re.sub(r"\s+", "", str(value or ""))
        for value in keywords
        if str(value or "").strip()
    ]
    signals = [value for value in signals if value]
    if not signals:
        return "", "", []

    blocks = {
        str(block.get("id")): block
        for block in classification.get("source_blocks", [])
        if isinstance(block, dict) and block.get("id")
    }
    chapters = {
        str(chapter.get("id")): chapter
        for chapter in classification.get("source_chapters", [])
        if isinstance(chapter, dict) and chapter.get("id")
    }
    assignments = [
        item
        for item in classification.get("classifications", [])
        if isinstance(item, dict)
        and item.get("category") == "performance_indicator"
        and str(item.get("source_id", "")) in blocks
    ]
    records: list[tuple[int, dict, dict, dict]] = []
    for item in assignments:
        block = blocks[str(item.get("source_id"))]
        chapter_id = str(item.get("chapter_id") or block.get("chapter_id") or "")
        chapter = chapters.get(chapter_id, {})
        try:
            body_index = int(block.get("body_index", 10**9))
        except (TypeError, ValueError):
            body_index = 10**9
        records.append((body_index, item, block, chapter))
    records.sort(key=lambda value: value[0])

    normalized = lambda text: re.sub(r"\s+", "", str(text or ""))
    # First use the semantic chapter title.  A heading such as “工作电压” owns
    # all classified blocks in that chapter, including a value-only paragraph.
    matched_chapters = {
        str(item.get("chapter_id") or block.get("chapter_id") or "")
        for _, item, block, chapter in records
        if any(
            signal in normalized(
                " ".join(
                    str(value or "")
                    for value in (
                        chapter.get("heading_text"),
                        chapter.get("section"),
                        block.get("heading_text"),
                        block.get("section"),
                    )
                )
            )
            for signal in signals
        )
    }
    selected = [
        record
        for record in records
        if (
            str(record[1].get("chapter_id") or record[2].get("chapter_id") or "")
            in matched_chapters
        )
    ]
    if not selected:
        selected = [
            record
            for record in records
            if any(signal in normalized(record[2].get("text")) for signal in signals)
        ]
    if not selected:
        return "", "", []

    values = [
        str(block.get("text") or "").strip()
        for _, _, block, _ in selected
        if str(block.get("text") or "").strip()
    ]
    if not values:
        return "", "", []
    headings = [
        str(
            chapter.get("heading_text")
            or chapter.get("section")
            or block.get("heading_text")
            or block.get("section")
            or ""
        ).strip()
        for _, _, block, chapter in selected
    ]
    basis = next((heading for heading in headings if heading), "")
    source_ids = list(dict.fromkeys(str(block.get("id")) for _, _, block, _ in selected))
    return "；".join(dict.fromkeys(values)), basis, source_ids


def _standard_applicability_policy() -> dict:
    """读取公共标准适用性策略；业务规则不写入算法。"""
    path = Path(__file__).resolve().parent.parent / "config" / "standard_applicability.yaml"
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def _filter_standards_by_domain(
    lines: list[str],
    domain: str,
    source_evidence: str = "",
    audit: dict | None = None,
) -> list[str]:
    """按外置领域策略过滤标准，不使用章节号或型号特例。"""
    def has_positive_evidence(term: str) -> bool:
        """命中业务术语且邻近位置没有明确否定词，才算适用性证据。"""
        if not term:
            return False
        for match in re.finditer(re.escape(term), source_evidence):
            prefix = source_evidence[max(0, match.start() - 40):match.start()]
            if not re.search(
                r"(?:没有|无需|不涉及|未提出|无|未|不)[^。；，,]{0,32}$",
                prefix,
            ):
                return True
        return False

    policy = _standard_applicability_policy()
    aliases = policy.get("domain_aliases") or {}
    normalized = str(domain or "").strip()
    normalized = str(aliases.get(normalized, normalized)).strip().lower()
    prefix_allowed = policy.get("prefix_allowed_domains") or {}
    marker_allowed = policy.get("marker_allowed_domains") or {}
    marker_excluded = policy.get("marker_excluded_domains") or {}
    conditional = policy.get("condition_marker_evidence") or {}
    control_markers = tuple(
        str(marker)
        for marker in (*marker_allowed, *marker_excluded, *conditional)
        if str(marker).strip()
    )
    kept: list[str] = []
    excluded: list[dict] = []
    seen: set[str] = set()

    for line in lines:
        reason = ""
        for prefix, allowed_domains in prefix_allowed.items():
            if line.lstrip().startswith(str(prefix)) and normalized not in {
                str(value).strip().lower() for value in (allowed_domains or [])
            }:
                reason = f"标准族 {prefix} 不适用于领域 {normalized or '[未选择]'}"
                break
        if not reason:
            for marker, allowed_domains in marker_allowed.items():
                if str(marker) in line and normalized not in {
                    str(value).strip().lower() for value in (allowed_domains or [])
                }:
                    reason = f"标记“{marker}”不适用于领域 {normalized or '[未选择]'}"
                    break
        if not reason:
            for marker, excluded_domains in marker_excluded.items():
                if str(marker) in line and normalized in {
                    str(value).strip().lower() for value in (excluded_domains or [])
                }:
                    reason = f"标记“{marker}”明确排除领域 {normalized}"
                    break
        if not reason:
            for marker, evidence_terms in conditional.items():
                if str(marker) in line and not any(
                    has_positive_evidence(str(term).strip())
                    for term in (evidence_terms or [])
                ):
                    reason = f"本次设计输入缺少“{marker}”所需适用性证据"
                    break
        if reason:
            excluded.append({"text": line, "reason": reason})
        else:
            cleaned = line
            for marker in control_markers:
                cleaned = re.sub(
                    rf"[（(][^（）()]*{re.escape(marker)}[^（）()]*[）)]",
                    "",
                    cleaned,
                )
            cleaned = re.sub(r"\s{2,}", "  ", cleaned).strip()
            canonical = re.sub(r"\s+", "", cleaned).lower()
            if canonical and canonical not in seen:
                seen.add(canonical)
                kept.append(cleaned)

    if audit is not None:
        audit.update(
            {
                "domain": normalized,
                "input_count": len(lines),
                "included_count": len(kept),
                "excluded_count": len(excluded),
                "excluded": excluded,
            }
        )
    return kept


def _collect_standards(
    tech, spec, tech_paras, spec_paras, sort_order: list[str], template_doc=None,
    include_template: bool = True, domain: str = "", audit: dict | None = None,
) -> list[str]:
    """合并标准并建立来源优先、占位过滤和版本冲突审计。"""
    prefixes = ("GJB", "GB", "Q/", "KJB", "MIL", "SAE", "CCAR", "TE-", "AS9")
    records: list[dict[str, str | int]] = []
    evidence_parts: list[str] = []
    template_paras = parse_doc(template_doc) if template_doc is not None else []
    sources = [
        ("tech", 30, tech, tech_paras),
        ("spec", 20, spec, spec_paras),
    ]
    if include_template:
        sources.append(("template", 10, template_doc, template_paras))

    placeholder_pattern = re.compile(
        r"(?:\bX{2,}\b|第\s*X+\s*部分|……|\.{4,}|示例|可删除|此处填写|"
        r"按实际|模板说明|标准名称|标准代号)",
        re.I,
    )

    def canonical_code(line: str) -> str:
        match = re.match(
            r"^((?:GJB(?:/Z)?|GB(?:/T)?|KJB|MIL|SAE|CCAR|TE-|AS)\s*"
            r"[A-Z0-9./-]+|Q/[A-Z0-9./-]+)",
            line,
            re.I,
        )
        return re.sub(r"\s+", "", match.group(1)).upper() if match else ""

    rejected: list[dict[str, str]] = []
    for source_name, priority, doc, paras in sources:
        for para in paras:
            line = _standard_line(para.text, prefixes)
            if line:
                if placeholder_pattern.search(line):
                    rejected.append(
                        {"source": source_name, "text": line, "reason": "placeholder"}
                    )
                else:
                    records.append(
                        {
                            "source": source_name,
                            "priority": priority,
                            "text": line,
                            "code": canonical_code(line),
                        }
                    )
            elif doc is not template_doc and (para.text or "").strip():
                evidence_parts.append((para.text or "").strip())
        if doc is not None:
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for line_text in cell.text.splitlines():
                            line = _standard_line(line_text, prefixes)
                            if line:
                                if placeholder_pattern.search(line):
                                    rejected.append(
                                        {
                                            "source": source_name,
                                            "text": line,
                                            "reason": "placeholder",
                                        }
                                    )
                                else:
                                    records.append(
                                        {
                                            "source": source_name,
                                            "priority": priority,
                                            "text": line,
                                            "code": canonical_code(line),
                                        }
                                    )
                            elif doc is not template_doc and line_text.strip():
                                evidence_parts.append(line_text.strip())

    # 只对“同一条标准文本”做来源优先去重：技术要求 > 产品规范 > 模板。
    #
    # 不能只用标准号作为 key。一个标准号可能包含多个分部/试验方法，
    # 例如 GJB 150.10A-2009 的“第1部分”和“第16部分”是两条不同的
    # 适用要求；按标准号去重会静默丢掉输入证据，最终覆盖率也会下降。
    # 因此 key 保留标准号后的分部、方法和名称，只折叠完全相同的原文。
    selected_by_code: dict[str, dict[str, str | int]] = {}
    duplicates: list[dict[str, str]] = []
    for record in sorted(records, key=lambda item: int(item["priority"]), reverse=True):
        code = str(record["code"])
        key = re.sub(r"\s+", "", str(record["text"])).upper()
        previous = selected_by_code.get(key)
        if previous is None:
            selected_by_code[key] = record
            continue
        previous_is_method = bool(re.search(r"(?:中)?方法\s*\d+", str(previous["text"])))
        current_is_method = bool(re.search(r"(?:中)?方法\s*\d+", str(record["text"])))
        if previous_is_method and not current_is_method:
            selected_by_code[key] = record
            dropped = previous
        else:
            dropped = record
        duplicates.append(
            {
                "text": str(dropped["text"]),
                "source": str(dropped["source"]),
                "reason": "duplicate_or_method_reference",
            }
        )

    # 同一标准族出现不同年份版本时，不能让低权责模板版本覆盖设计输入。
    # 例如产品规范明确使用 GJB 1406A-2005，而模板参考清单预置
    # GJB 1406A-2021，本任务应采用产品规范版本；只有同一权责层内部
    # 同时声明多个版本时，才保留冲突并进入人工裁决。
    selected_records: list[dict[str, str | int]] = []
    selected_family_index: dict[str, int] = {}
    for record in selected_by_code.values():
        code = str(record["code"])
        family = re.sub(r"-\d{4}[A-Z]?$", "", code)
        is_versioned = bool(family and family != code)
        if not is_versioned:
            selected_records.append(record)
            continue
        previous_index = selected_family_index.get(family)
        if previous_index is None:
            selected_family_index[family] = len(selected_records)
            selected_records.append(record)
            continue
        previous = selected_records[previous_index]
        previous_priority = int(previous["priority"])
        current_priority = int(record["priority"])
        if current_priority < previous_priority:
            duplicates.append(
                {
                    "text": str(record["text"]),
                    "source": str(record["source"]),
                    "reason": "lower_authority_version",
                }
            )
            continue
        if current_priority > previous_priority:
            duplicates.append(
                {
                    "text": str(previous["text"]),
                    "source": str(previous["source"]),
                    "reason": "lower_authority_version",
                }
            )
            selected_records[previous_index] = record
            continue
        # 同一权责层内的不同版本不能静默选择，全部保留给冲突门禁。
        selected_records.append(record)

    deduplicated = [str(record["text"]) for record in selected_records]
    version_groups: dict[str, set[str]] = {}
    for record in selected_records:
        code = str(record["code"])
        family = re.sub(r"-\d{4}[A-Z]?$", "", code)
        if family and code:
            version_groups.setdefault(family, set()).add(code)
    version_conflicts = [
        {"family": family, "versions": sorted(versions)}
        for family, versions in version_groups.items()
        if len(versions) > 1
    ]

    if audit is not None:
        audit.update(
            {
                "source_priority": ["tech", "spec", "template"],
                "rejected_placeholders": rejected,
                "deduplicated": duplicates,
                "version_conflicts": version_conflicts,
            }
        )
    applicable = _filter_standards_by_domain(
        deduplicated,
        domain,
        "\n".join(evidence_parts),
        audit,
    )
    return _sort_standards_semantic(applicable, sort_order)


def _runtime_indicator_map(
    cfg: dict,
    tech_paras: list,
    classification: dict | None = None,
) -> dict[str, list[dict]]:
    """Merge the profile vocabulary with matching entries from the 7-22 list.

    The external workbook contributes names and categories only.  Numeric
    values still have to exist in the user's technical requirement.
    """
    excluded = {
        _canonical_indicator_name(name)
        for name in (cfg.get("indicator_excluded_names") or [])
        if str(name).strip()
    }
    result: dict[str, list[dict]] = {}
    for category, indicators in (cfg.get("indicator_map") or {}).items():
        if not isinstance(indicators, list):
            continue
        result.setdefault(_canonical_indicator_category(str(category)), []).extend(
            dict(item) for item in indicators if isinstance(item, dict)
        )
    result = {
        category: [
            item for item in indicators
            if _canonical_indicator_name(item.get("name", "")) not in excluded
        ]
        for category, indicators in result.items()
    }
    # Workbook taxonomy entries may only be activated by blocks already
    # classified as performance indicators.  Scanning the entire document
    # previously turned a standards-reference line containing “潮湿” into a
    # fabricated user indicator.
    classified_indicator_texts: list[str] = []
    if isinstance(classification, dict):
        blocks = {
            str(block.get("id")): block
            for block in classification.get("source_blocks", [])
            if isinstance(block, dict) and block.get("id")
        }
        for assignment in classification.get("classifications", []):
            if (
                isinstance(assignment, dict)
                and assignment.get("category") == "performance_indicator"
            ):
                block = blocks.get(str(assignment.get("source_id", "")), {})
                classified_indicator_texts.extend(
                    str(value or "")
                    for value in (
                        block.get("heading_text"),
                        block.get("section"),
                        block.get("text"),
                    )
                    if str(value or "").strip()
                )
    # A supplied classification is authoritative about the source boundary.
    # An empty performance set must remain empty; falling back to the entire
    # document is how standards text and unrelated chapters became indicators.
    # ``classification=None`` is retained only for legacy deterministic unit
    # callers that do not have a semantic plan yet.
    source_text = re.sub(
        r"\s+",
        "",
        "\n".join(classified_indicator_texts)
        if isinstance(classification, dict)
        else "\n".join(str(para.text or "") for para in tech_paras),
    )
    # A product profile may already declare a taxonomy term as an alias (for
    # example, a shorter customer heading for a more precise canonical item).
    # Treat every externally configured name/keyword as one controlled
    # vocabulary before adding workbook entries.  This prevents the same source
    # requirement from being emitted twice without baking individual indicator
    # aliases into Python.
    configured_vocabulary = {
        re.sub(r"\s+", "", str(signal))
        for indicators in result.values()
        for item in indicators
        for field in (
            "name",
            "tech_kws",
            "std_kws",
            "spec_kws",
            "spec_exact_names",
        )
        for signal in (
            item.get(field, [])
            if isinstance(item.get(field, []), (list, tuple, set))
            else [item.get(field, "")]
        )
        if str(signal).strip()
    }
    existing = {
        _canonical_indicator_name(item.get("name", ""))
        for indicators in result.values()
        for item in indicators
        if item.get("name")
    }
    controlled_entries: list[tuple[str, dict]] = [
        (_canonical_indicator_category(str(category)), dict(entry))
        for category, entries in taxonomy_indicator_map().items()
        for entry in entries
        if isinstance(entry, dict)
    ]
    controlled_entries.extend(
        (_canonical_indicator_category(str(entry.get("category", "其他") or "其他")), dict(entry))
        for entry in load_reference_indicator_catalog()
        if isinstance(entry, dict)
    )
    for category, entry in controlled_entries:
        name = str(entry.get("name", "")).strip()
        aliases = [
            str(alias).strip()
            for alias in entry.get("aliases", [])
            if str(alias).strip()
        ]
        # `related_terms` are intentionally excluded: they are useful for
        # retrieval hints but are not exact identity.  Treating “潮湿” as an
        # alias of “湿热”, for example, fabricated an indicator in old builds.
        signals = [name] + [
            alias
            for alias in aliases
            if len(re.sub(r"\s+", "", alias)) >= 2
        ]
        if not name or not any(
            re.sub(r"\s+", "", signal) in source_text
            for signal in signals
            if signal
        ):
            continue
        normalized_signals = {
            re.sub(r"\s+", "", signal)
            for signal in signals
            if signal
        }
        if normalized_signals & configured_vocabulary:
            continue
        canonical = _canonical_indicator_name(name)
        if canonical in existing or canonical in excluded:
            continue
        result.setdefault(_canonical_indicator_category(category), []).append({
            "name": name,
            "tech_kws": signals,
            "std_kws": signals,
            "taxonomy_type": entry.get("type", ""),
            "target_role": entry.get("target_role", ""),
            "catalog_family": entry.get("catalog_family", ""),
        })
        existing.add(canonical)
        configured_vocabulary.update(normalized_signals)
    return result


def _dynamic_unlisted_indicator_rows(
    classification: dict | None,
    existing_rows: list[tuple],
    excluded_names: list[str] | tuple[str, ...] | set[str],
    spec_table_ledger: dict[str, list[dict]],
    spec_identifier: str,
    *,
    product_label: str = "",
    product_series: str = "",
) -> tuple[list[tuple[str, str, str, str, str]], list[dict]]:
    """Audit classified indicators that are absent from the controlled catalog.

    LLM classification is evidence discovery, not authority to create a formal
    4.1 row.  An unlisted candidate therefore enters the review ledger and
    blocks formal delivery; it is never silently promoted to ``其他``.
    """
    if not classification:
        return [], []

    blocks = {
        str(block.get("id")): block
        for block in classification.get("source_blocks", [])
        if isinstance(block, dict) and block.get("id")
    }
    chapters = {
        str(chapter.get("id")): chapter
        for chapter in classification.get("source_chapters", [])
        if isinstance(chapter, dict) and chapter.get("id")
    }
    existing_names = {
        _canonical_indicator_name(str(row[0]))
        for row in existing_rows
        if row and row[0] and not str(row[0]).startswith("【")
    }
    existing_values = {
        re.sub(r"\s+", "", str(row[1]))
        for row in existing_rows
        if len(row) > 1 and str(row[1]).strip()
    }
    excluded = {
        _canonical_indicator_name(str(name))
        for name in excluded_names
        if str(name).strip()
    }

    grouped: dict[str, dict] = {}
    for assignment in classification.get("classifications", []):
        if not isinstance(assignment, dict) or assignment.get("category") != "performance_indicator":
            continue
        block = blocks.get(str(assignment.get("source_id", "")))
        if not block or block.get("has_drawing") or block.get("type") not in {"paragraph", "table"}:
            continue
        text = str(block.get("text", "")).strip()
        if not text:
            continue
        chapter_id = str(assignment.get("chapter_id") or block.get("chapter_id") or block.get("id"))
        chapter = chapters.get(chapter_id, {})
        group = grouped.setdefault(
            chapter_id,
            {
                "heading": str(
                    chapter.get("heading_text")
                    or block.get("heading_text")
                    or block.get("section")
                    or ""
                ),
                "source_ids": [],
                "texts": [],
            },
        )
        group["source_ids"].append(str(block.get("id")))
        group["texts"].append(text)

    rows: list[tuple[str, str, str, str, str]] = []
    audit: list[dict] = []
    generic_headings = {
        "技术指标", "性能指标", "技术要求", "指标", "要求", "产品技术要求",
    }
    for group in grouped.values():
        raw_heading = str(group["heading"]).strip()
        name = re.sub(
            r"^\s*(?:第\s*[一二三四五六七八九十百千万零〇]+\s*章\s*|\d+(?:\.\d+)*(?:\s+|[、)）]))",
            "",
            raw_heading,
        ).strip(" ：:；;。")
        value = "\n".join(dict.fromkeys(str(text).strip() for text in group["texts"] if str(text).strip()))
        if not name or name in generic_headings:
            # 只接受原文中明确的“名称：值”，不从数值反猜指标名。
            label_match = re.match(r"^([^\n：:]{1,24})[：:]", value)
            name = label_match.group(1).strip() if label_match else ""
        canonical = _canonical_indicator_name(name)
        normalized_value = re.sub(r"\s+", "", value)
        if (
            not name
            or canonical in existing_names
            or canonical in excluded
            or normalized_value in existing_values
        ):
            continue

        audit.append({
            "indicator_name": name,
            "category": "其他",
            "source_ids": group["source_ids"],
            "source_heading": raw_heading,
            "source_value": value,
            "status": "UNMAPPED_REVIEW_REQUIRED",
            "policy": "controlled_catalog_only",
            "notes": [
                "该候选仅由语义分类发现，未进入当前产品受控指标清单；"
                "正式件不得自动创建指标行"
            ],
        })

    return rows, audit


def build_content(
    cfg,
    tech,
    spec,
    tech_paras,
    spec_paras,
    tech_path,
    spec_path="",
    template_doc=None,
    controlled_product_label: str = "",
    product_series: str = "",
    requirement_classification: dict | None = None,
    controlled_product_domain: str = "",
):
    """构造语义角色内容；任何模板章节号都不参与身份或定位。"""
    content = {}
    semantic_structures = cfg.get("semantic_structures", {})
    std_order = cfg.get("std_sort_order", ["GJB/","GJB","GB","Q/","KJB"])

    # 语义主流程不再从固定章节号取引用标准。技术要求优先，产品规范只补缺。
    standards_audit: dict = {}
    semantic_standards = _collect_standards(
        tech, spec, tech_paras, spec_paras, std_order, template_doc=template_doc,
        include_template=str(cfg.get("standards_policy", "merge_template")) != "source_only",
        domain=controlled_product_domain,
        audit=standards_audit,
    )
    content["__standards_reference__"] = {
        "lines": semantic_standards,
        "tables": [],
        "images": [],
        "image_warnings": [],
        "standards_audit": standards_audit,
    }

    # 产品规范表格只按标题路径、表头和指标名称解析。
    spec_table_ledger: dict[str, list[dict]] = {}
    spec_identifier = _extract_spec_identifier(spec, spec_path)
    spec_model_filter = cfg.get("spec_model_filter", {})
    scoped_spec_enabled = (
        bool(spec_model_filter.get("enabled", True))
        if isinstance(spec_model_filter, dict)
        else bool(spec_model_filter)
    )
    if spec is not None and spec_path:
        try:
            spec_table_ledger = _build_spec_table_ledger(spec_path)
            print(f"  产品规范表格台账: {sum(len(v) for v in spec_table_ledger.values())} 条")
        except Exception as e:
            print(f"  ⚠ 产品规范表格台账构建失败: {e}")

    for semantic_role, rule in semantic_structures.items():
        if not isinstance(rule, dict):
            continue
        mode   = rule.get("mode", "text")
        if mode != "indicator_table":
            raise ValueError(
                f"不支持的语义结构模式: {semantic_role}={mode}；"
                "普通正文必须由原文块语义分类流程复制"
            )
        if mode == "indicator_table":
            ind_rows = []
            indicator_comparison_audit: list[dict] = []
            for category, indicators in _runtime_indicator_map(
                cfg, tech_paras, requirement_classification
            ).items():
                category_rows = []
                for ind in indicators:
                    # 生产路径必须先经过语义分类；分类本身决定哪些原文块
                    # 有资格成为 4.1 用户指标。未提供分类时仅保留旧的
                    # 确定性单元测试/离线调用兼容路径。
                    tech_kws = ind.get("tech_kws", []) or [ind.get("name", "")]
                    tech_source_ids: list[str] = []
                    if isinstance(requirement_classification, dict):
                        tv, tech_basis, tech_source_ids = _classified_indicator_evidence(
                            requirement_classification,
                            tech_kws,
                        )
                    else:
                        tv, tech_basis = _find_value_by_semantics(tech_paras, tech_kws)
                    tv = _select_indicator_value(tv, ind)
                    # 指标集合完全由设计输入驱动。设计输入没有该指标时，禁止仅凭
                    # 模板目录或产品规范把它加入输出。
                    if not tv:
                        continue
                    # 标准要求：优先用型号过滤台账（精确），回退到章节文本搜索
                    std_k = ind.get("std_kws") or ind.get("spec_kws", [])
                    stdv = ""
                    standard_display = ""
                    spec_basis = ""
                    standard_audit_note = ""
                    table_hit = _match_spec_table_indicator(
                        spec_table_ledger,
                        ind,
                        product_label=controlled_product_label,
                        product_series=product_series,
                        allow_scoped=scoped_spec_enabled,
                    )
                    if table_hit and not table_hit.get("inapplicable"):
                        stdv = table_hit["value"]
                        standard_display = table_hit.get("display_value") or stdv
                        spec_basis = f"{spec_identifier}（产品规范表格：{table_hit['basis']}）"
                        if table_hit.get("match_origin") == "related":
                            standard_audit_note = (
                                "[关联词命中] 产品规范指标名与用户指标名不同，"
                                "通过受控 related_kws 取得标准要求"
                            )
                        comparison_status = (
                            "SCOPED_SPEC_APPLIED"
                            if table_hit.get("selection") == "scoped"
                            else "GENERAL_SPEC_APPLIED"
                        )
                        manual_review_required = False
                    elif table_hit and table_hit.get("inapplicable"):
                        # A restricted row for another model is not a standard
                        # for this job.  Keep the fact in the audit note but do
                        # not leak its value into the adopted column.
                        stdv = ""
                        spec_basis = "不适用：产品规范行的型号/系列条件未命中本次选择"
                        standard_audit_note = "[不适用] 产品规范候选的型号/系列条件未命中本次产品"
                        # 7-22 的裁决是确定性的：带具体型号或其它限制条件
                        # 且未命中本次产品时，不调取该规范值，直接采用用户
                        # 要求并把依据写为“用户要求”。这不是数值冲突，也
                        # 不应仅因为看见了不适用候选而阻断正式件。
                        comparison_status = "CONDITIONAL_SPEC_REJECTED_USER_APPLIED"
                        manual_review_required = False
                    else:
                        # 普通规范段落不是结构化指标候选。它可能只是试验
                        # 方法、说明性文字或另一产品的条件，不能被当作
                        # “标准要求”写入正式表格。
                        stdv = ""
                        spec_basis = ""
                        comparison_status = "NO_STRUCTURED_APPLICABLE_SPEC"
                        manual_review_required = False
                    if str(stdv or "").strip() in {"", "\\", "/", "-", "—", "无", "不适用"}:
                        stdv = ""
                        standard_display = ""
                        if not standard_audit_note:
                            standard_audit_note = "[不适用] 未找到本次产品可采用的规范指标"
                    else:
                        standard_display = standard_display or stdv
                    if stdv and re.search(r"符合下表|见下表|如下规定", stdv) and not table_hit:
                        raise ValueError(f"指标“{ind.get('name')}”存在未解析表格引用：{stdv}")
                    # 依据使用实际命中的标题/型号范围，不回写配置中的固定章节号。
                    # 拟采用指标裁决（提炼具体数值，用户优先，冲突入审计）
                    adopted, basis, audit_note = _resolve_indicator_adoption(
                        tv,
                        stdv,
                        spec_basis,
                        str(ind.get("adopt_policy", "")),
                    )
                    notes = "；".join(note for note in (standard_audit_note, audit_note) if note)
                    category_rows.append((ind["name"], tv, standard_display, adopted, basis, notes))
                    indicator_comparison_audit.append({
                        "indicator_name": str(ind.get("name", "")),
                        "category": str(category),
                        "status": comparison_status,
                        "manual_review_required": manual_review_required,
                        "user_requirement": tv,
                        "user_source_ids": tech_source_ids,
                        "user_source_heading": tech_basis,
                        "standard_requirement": standard_display,
                        "adopted_requirement": adopted,
                        "basis": basis,
                        "scoped_spec_filter_enabled": scoped_spec_enabled,
                        "rejected_candidates": (
                            table_hit.get("rejected_items", [])
                            if isinstance(table_hit, dict)
                            else []
                        ),
                    })
                # 性能域标题来自外置指标清单，即使本次设计输入在该域没有
                # 指标，也要用它治理模板的通用分类占位标题。这里只加入
                # 结构标记，不会凭空生成任何技术指标；审计输出会过滤标记。
                ind_rows.append((f"【{category}】", "", "", "", ""))
                ind_rows.extend(category_rows)
            dynamic_rows, dynamic_audit = _dynamic_unlisted_indicator_rows(
                requirement_classification,
                ind_rows,
                cfg.get("indicator_excluded_names") or [],
                spec_table_ledger,
                spec_identifier,
                product_label=controlled_product_label,
                product_series=product_series,
            )
            if dynamic_rows:
                ind_rows.append(("【其他】", "", "", "", ""))
                ind_rows.extend(dynamic_rows)
            audit_conflicts = [(r[0], r[5]) for r in ind_rows if len(r) > 5 and r[5]]
            clean_rows = [r[:5] for r in ind_rows]
            content_key = f"role:{semantic_role}"
            content[content_key] = {
                "lines": [], "tables": [], "images": [], "image_warnings": [],
                "indicator_rows": clean_rows,
                "audit_conflicts": audit_conflicts,
                "dynamic_indicator_audit": dynamic_audit,
                "indicator_comparison_audit": indicator_comparison_audit,
            }
            print(f"  {content_key}: {len(ind_rows)} 行  0 表  0 图")
            continue

    return content


def _merge_classified_content(
    content: dict,
    classification: dict | None,
    category_mapping_path: str | None,
    tech,
) -> dict[str, int]:
    """把全量语义分类写入语义槽位；other 是正式业务类别之一。"""
    if not classification or not category_mapping_path:
        return {"slots": 0, "paragraphs": 0, "tables": 0, "images": 0}
    import copy as _copy
    import hashlib as _hashlib
    import yaml as _yaml
    from lxml import etree as _etree

    mapping = _yaml.safe_load(Path(category_mapping_path).read_text(encoding="utf-8")) or {}
    categories = mapping.get("categories", {}) or {}
    semantic_roles = mapping.get("semantic_roles", {}) or {}
    routing_rules = {**categories, **semantic_roles}
    block_by_id = {b["id"]: b for b in classification.get("source_blocks", [])}
    assignment_by_source = {
        item.get("source_id"): item
        for item in classification.get("classifications", [])
        if item.get("source_id")
    }
    chapter_by_id = {
        chapter.get("id"): chapter
        for chapter in classification.get("source_chapters", [])
        if chapter.get("id")
    }

    from jonhon_taskbook.semantic_orchestrator import (
        copy_source_element_exact,
        protected_source_block_ids,
    )

    protected_block_ids = protected_source_block_ids(
        classification.get("source_blocks", [])
    )

    def _source_module_meta(block: dict) -> dict[str, str]:
        assignment = assignment_by_source.get(block.get("id"), {})
        chapter_id = str(assignment.get("chapter_id", ""))
        chapter = chapter_by_id.get(chapter_id, {})
        return {
            "source_chapter_id": chapter_id,
            "source_section": str(chapter.get("section") or block.get("section") or ""),
            "source_heading": str(
                chapter.get("heading_text")
                or block.get("heading_text")
                or block.get("section")
                or ""
            ),
        }
    grouped: dict[str, list[tuple[str, dict]]] = {}
    special_modes: dict[str, str] = {}
    for role_name, rule in semantic_roles.items():
        if not isinstance(rule, dict):
            continue
        slot = f"role:{role_name}"
        mode = str(rule.get("write_mode", "direct_chapter"))
        special_modes[slot] = mode
        if mode == "standards_merge":
            source = content.pop("__standards_reference__", None)
            if source and source.get("lines"):
                # 由语义角色声明替换策略；填充器不需要知道它原来位于哪一章。
                source["replace_existing"] = True
                content[slot] = source
    for item in classification.get("classifications", []):
        block = block_by_id.get(item.get("source_id"))
        if block and block.get("id") in protected_block_ids:
            # Cover and change-log data are filled by the deterministic
            # cover/change-record handlers.  They must never be appended to
            # "other" or any other semantic requirement slot.
            continue
        category = item.get("category", "other")
        rule = routing_rules.get(category) or categories.get("other") or {}
        heading_keywords = rule.get("target_heading_keywords") or []
        if isinstance(heading_keywords, str):
            heading_keywords = [heading_keywords]
        role = str(rule.get("target_role", category)).strip() or category
        slot = f"role:{role}" if heading_keywords else ""
        special_modes[slot] = str(rule.get("write_mode", "direct_chapter"))
        if slot and block:
            grouped.setdefault(slot, []).append((category, block))
            for replica_category in rule.get("replicate_to_categories", []) or []:
                replica_rule = routing_rules.get(str(replica_category), {})
                replica_headings = replica_rule.get("target_heading_keywords") or []
                if isinstance(replica_headings, str):
                    replica_headings = [replica_headings]
                if not replica_headings:
                    continue
                replica_role = (
                    str(replica_rule.get("target_role", replica_category)).strip()
                    or str(replica_category)
                )
                replica_slot = f"role:{replica_role}"
                special_modes[replica_slot] = str(
                    replica_rule.get("write_mode", "direct_chapter")
                )
                grouped.setdefault(replica_slot, []).append(
                    (str(replica_category), block)
                )

    # 配置化的证据投影只截取设计输入中原样存在的片段，不生成解释文字。
    # 典型用途是把“工作温度”这一既是技术指标、又是环境适应性证据的
    # 原文片段同时放入两个职责槽位。
    for projection in mapping.get("evidence_projections", []) or []:
        if not isinstance(projection, dict):
            continue
        source_category = str(projection.get("source_category", "")).strip()
        target_category = str(projection.get("target_category", "")).strip()
        target_rule = routing_rules.get(target_category, {})
        target_headings = target_rule.get("target_heading_keywords") or []
        if isinstance(target_headings, str):
            target_headings = [target_headings]
        if not source_category or not target_category or not target_headings:
            continue
        target_role = (
            str(target_rule.get("target_role", target_category)).strip()
            or target_category
        )
        target_slot = f"role:{target_role}"
        match_any = [
            str(term) for term in projection.get("match_any", []) if str(term)
        ]
        extract_patterns = [
            str(pattern)
            for pattern in projection.get("extract_patterns", [])
            if str(pattern)
        ]
        for assignment in classification.get("classifications", []):
            if (
                not isinstance(assignment, dict)
                or assignment.get("category") != source_category
            ):
                continue
            block = block_by_id.get(str(assignment.get("source_id", "")), {})
            text = str(block.get("text", ""))
            semantic_context = " ".join(
                str(block.get(key, ""))
                for key in ("heading_text", "section", "text")
            )
            if not text or (
                match_any
                and not any(term in semantic_context for term in match_any)
            ):
                continue
            fragments: list[str] = []
            for pattern in extract_patterns:
                fragments.extend(
                    match.group(0).strip()
                    for match in re.finditer(pattern, text, re.I)
                    if match.group(0).strip()
                )
            if not fragments:
                continue
            target = content.setdefault(
                target_slot,
                {
                    "lines": [],
                    "tables": [],
                    "images": [],
                    "ordered_elements": [],
                    "image_warnings": [],
                },
            )
            # 证据投影不是对模板示例的“补充”，而是设计输入已经证明该
            # 受控槽位有真实内容。此时必须由输入证据接管整段模板正文，
            # 否则 lines-only 投影会与模板中的说明/示例并存，造成无来源
            # 内容进入正式任务书。槽位身份仍来自实时标题语义，不依赖章号。
            target["replace_existing"] = True
            for fragment in fragments:
                if fragment not in target["lines"]:
                    target["lines"].append(fragment)
                    target.setdefault("projection_audit", []).append(
                        {
                            "source_id": block.get("id", ""),
                            "source_category": source_category,
                            "target_category": target_category,
                            "text": fragment,
                            "policy": "copy_exact_fragment",
                        }
                    )
            special_modes[target_slot] = str(
                target_rule.get("write_mode", "direct_chapter")
            )

    # 指标表和引用标准沿用模板格式：技术要求先填，产品规范只补缺项。
    for slot, mode in special_modes.items():
        if mode == "indicator_table":
            source_item = next(
                ((key, value) for key, value in content.items() if value.get("indicator_rows")),
                (None, None),
            )
            source_key, source = source_item
            if source:
                # 指标表只能由结构化指标抽取器写入。LLM 分类结果只用于证明
                # 来源覆盖，不能把整章标题或整段正文临时拼成新的指标行，否则
                # 会把“互换性、重量位置、验收条款”等误塞入指标表。
                output_rows = [
                    row for row in source["indicator_rows"]
                    if row and not str(row[0]).startswith("【")
                ]
                input_indicator_names = [str(row[0]) for row in output_rows]
                input_canonical = sorted(
                    {_canonical_indicator_name(name) for name in input_indicator_names}
                )
                output_canonical = sorted({_canonical_indicator_name(row[0]) for row in output_rows})
                indicator_source_aliases: dict[str, str] = {}
                source_chapters = {
                    str(chapter.get("id")): chapter
                    for chapter in classification.get("source_chapters", [])
                    if isinstance(chapter, dict) and chapter.get("id")
                }
                source_blocks = {
                    str(block.get("id")): block
                    for block in classification.get("source_blocks", [])
                    if isinstance(block, dict) and block.get("id")
                }
                for assignment in classification.get("classifications", []):
                    if not isinstance(assignment, dict) or assignment.get("category") != "performance_indicator":
                        continue
                    block = source_blocks.get(str(assignment.get("source_id", "")), {})
                    chapter = source_chapters.get(str(assignment.get("chapter_id", "")), {})
                    source_heading = str(
                        chapter.get("heading_text")
                        or block.get("heading_text")
                        or block.get("section")
                        or ""
                    ).strip()
                    source_heading = re.sub(r"^\s*\d+(?:\.\d+)*\s*", "", source_heading).strip(" ：:")
                    if not source_heading:
                        continue
                    canonical_heading = _canonical_indicator_name(source_heading)
                    output_label = next(
                        (
                            name for name in input_indicator_names
                            if _canonical_indicator_name(name) == canonical_heading
                        ),
                        "",
                    )
                    if output_label:
                        indicator_source_aliases[source_heading] = output_label
                # 证据门禁应检查整份技术要求原文，而不是只检查被 LLM
                # 分到 performance_indicator 的章节。某个章节可能同时含
                # 有机械寿命、工作温度等指标，模型将其归到可靠性/环境类
                # 时，不能因此把原文已有的指标误判为“无依据输出”。
                all_source_blocks = classification.get("source_blocks", [])
                source_blob = re.sub(
                    r"\s+", "", "".join(
                        str(block.get("text", ""))
                        for block in all_source_blocks
                        if isinstance(block, dict)
                    )
                )
                unbacked_output = [
                    str(row[0]) for row in output_rows
                    if len(row) > 1
                    and not _indicator_value_is_source_backed(str(row[1]), source_blob)
                ]
                missing_evidence = list(unbacked_output)
                unmapped_candidates = [
                    item
                    for item in source.get("dynamic_indicator_audit", [])
                    if item.get("status") == "UNMAPPED_REVIEW_REQUIRED"
                ]
                comparison_audit = list(
                    source.get("indicator_comparison_audit", [])
                )
                conditional_review = [
                    item
                    for item in comparison_audit
                    if item.get("manual_review_required") is True
                ]
                source["indicator_audit"] = {
                    "policy": "design_input_driven",
                    "input_indicator_names": input_indicator_names,
                    "output_indicator_names": [str(row[0]) for row in output_rows],
                    "input_canonical_names": input_canonical,
                    "output_canonical_names": output_canonical,
                    "missing_input_evidence_count": len(missing_evidence),
                    "unbacked_output_names": unbacked_output,
                    "unmapped_review_required": unmapped_candidates,
                    "unmapped_review_required_count": len(unmapped_candidates),
                    "comparison_decisions": comparison_audit,
                    "manual_review_required": conditional_review,
                    "manual_review_required_count": len(conditional_review),
                    "source_heading_aliases": indicator_source_aliases,
                    "passed": (
                        not unbacked_output
                        and not unmapped_candidates
                        and not conditional_review
                        and set(input_canonical).issubset(output_canonical)
                    ),
                }
                content[slot] = source
                if source_key and source_key != slot:
                    content.pop(source_key, None)
            grouped.pop(slot, None)
        elif mode == "standards_merge":
            grouped.pop(slot, None)

    stats = {"slots": 0, "paragraphs": 0, "tables": 0, "images": 0}
    body = tech.element.body
    for slot, items in grouped.items():
        current = content.setdefault(
            slot,
            {"lines": [], "tables": [], "images": [], "ordered_elements": [], "image_warnings": []},
        )
        seen_lines = {re.sub(r"\s+", "", str(x)) for x in current.get("lines", [])}

        def _table_hash(element) -> str:
            text = "".join(
                node.text or "" for node in element.findall(f".//{qn('w:t')}")
            )
            normalized = re.sub(r"\s+", "", text)
            payload = normalized.encode("utf-8") or _etree.tostring(element, method="c14n")
            return _hashlib.sha256(payload).hexdigest()

        def _image_hash(element) -> str:
            relationship_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
            drawing_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
            refs = []
            for blip in element.findall(f".//{{{drawing_ns}}}blip"):
                refs.extend(
                    value
                    for value in (
                        blip.get(f"{{{relationship_ns}}}embed"),
                        blip.get(f"{{{relationship_ns}}}link"),
                    )
                    if value
                )
            text = "".join(
                node.text or "" for node in element.findall(f".//{qn('w:t')}")
            )
            payload = ("|".join(refs) + "|" + re.sub(r"\s+", "", text)).encode("utf-8")
            if payload == b"|":
                payload = _etree.tostring(element, method="c14n")
            return _hashlib.sha256(payload).hexdigest()

        # 与旧配置内容交叉去重，避免语义路由后把同一张源表再次写入新槽位。
        seen_tables = set()
        for value in content.values():
            for item in value.get("tables", []):
                seen_tables.add(_table_hash(item[0] if isinstance(item, tuple) else item))
            for item in value.get("ordered_elements", []):
                if item.get("kind") == "table" and item.get("element") is not None:
                    seen_tables.add(_table_hash(item["element"]))
        seen_images = set()
        for image in current.get("images", []):
            image_el = image.get("image_el") if isinstance(image, dict) else image[0]
            if image_el is not None:
                seen_images.add(_image_hash(image_el))
        used = False
        for _, block in items:
            index = int(block.get("body_index", -1))
            if index < 0 or index >= len(body):
                continue
            source_el = body[index]
            source_meta = _source_module_meta(block)
            if block.get("type") == "table":
                source_hash = _table_hash(source_el)
                if source_hash not in seen_tables:
                    current.setdefault("ordered_elements", []).append(
                        {
                            "kind": "table",
                            "element": _copy.deepcopy(source_el),
                            "source_id": block["id"],
                            **source_meta,
                        }
                    )
                    seen_tables.add(source_hash)
                    stats["tables"] += 1
                    used = True
            elif block.get("has_drawing"):
                source_hash = _image_hash(source_el)
                if source_hash not in seen_images:
                    current.setdefault("ordered_elements", []).append(
                        {
                            "kind": "image",
                            "element": _copy.deepcopy(source_el),
                            "source_id": block["id"],
                            **source_meta,
                        }
                    )
                    seen_images.add(source_hash)
                    stats["images"] += 1
                    used = True
            else:
                text = str(block.get("text", "")).strip()
                normalized = re.sub(r"\s+", "", text)
                if text and normalized not in seen_lines:
                    try:
                        paragraph_copy = copy_source_element_exact(source_el, block)
                    except ValueError as exc:
                        raise ValueError(
                            f"原文精确片段复制失败 {block.get('id', '')}: {exc}"
                        ) from exc
                    # 来源文档的 numId 只在来源 numbering.xml 中有意义。直接带入
                    # 模板会污染模板标题计数器，使后续章节整体错号。正文原字句保留，
                    # 但来源自动列表关系一律移除；目标标题编号只由当前模板控制。
                    paragraph_ppr = paragraph_copy.find(qn("w:pPr"))
                    paragraph_numpr = (
                        paragraph_ppr.find(qn("w:numPr")) if paragraph_ppr is not None else None
                    )
                    if paragraph_numpr is not None:
                        paragraph_ppr.remove(paragraph_numpr)
                    # 某些输入把父/当前章节号写在首个长段落里，未被 Word 标题样式
                    # 识别。章节号只用于追溯，复制正文前要去掉该前缀。
                    prefix = re.match(r"^(\d+(?:\.\d+)*)\s+(?=[\u4e00-\u9fffA-Za-z])", text)
                    heading_number = str(block.get("heading_number", ""))
                    if not block.get("is_fragment") and prefix and (
                        heading_number == prefix.group(1)
                        or heading_number.startswith(prefix.group(1) + ".")
                    ):
                        visible = paragraph_copy.findall(f".//{qn('w:t')}")
                        if visible:
                            remainder = text[prefix.end():]
                            visible[0].text = remainder
                            for node in visible[1:]:
                                node.text = ""
                            text = remainder
                            normalized = re.sub(r"\s+", "", text)
                    current.setdefault("ordered_elements", []).append(
                        {
                            "kind": "paragraph",
                            "text": text,
                            "element": paragraph_copy,
                            "source_id": block["id"],
                            **source_meta,
                        }
                    )
                    seen_lines.add(normalized)
                    stats["paragraphs"] += 1
                    used = True
        if used:
            stats["slots"] += 1
    return stats


def run_coverage_and_qa(
    tech_path: str,
    out_path: str,
    cfg: dict | None = None,
    preserve_template_guidance: bool = False,
    template_path: str | None = None,
) -> bool:
    """
    自动运行覆盖率账本 + QA门禁，输出报告。
    返回 True 表示门禁通过，False 表示有阻断项。
    """
    try:
        from jonhon_taskbook.coverage_ledger import (
            exclude_semantic_structure_headings,
            parse_docx_to_ledger,
            mark_exact_fragment_coverage,
            mark_covered_from_output,
            mark_structured_indicator_coverage,
        )
        from jonhon_taskbook.qa_gate import QAGate
        import zipfile
        from lxml import etree
    except ImportError as e:
        print(f"   ⚠ 覆盖率/QA模块未安装依赖: {e}")
        # 门禁依赖缺失属于“无法证明通过”，不得按成功放行。
        return False

    # 1. 解析输入，建立覆盖账本
    ledger = parse_docx_to_ledger(tech_path)
    # 语义结构解析器会把无编号、Normal 样式的引导句识别为标题并从
    # source_blocks 中移除；覆盖解析器若仍把同一段计作正文，就会形成
    # “规划器没有 source_id、QA 却要求输出证据”的伪缺口。优先使用
    # 有效分类结果，并保留排除明细供报告审计；分类文件不可用时保持
    # 原有严格行为，不自行猜测标题。
    _classification = None
    for _suffix in (
        ".effective_requirement_classification.json",
        ".requirement_classification.json",
    ):
        _classification_path = Path(out_path).with_suffix(_suffix)
        if not _classification_path.is_file():
            continue
        try:
            _classification = json.loads(
                _classification_path.read_text(encoding="utf-8")
            )
            break
        except (OSError, ValueError, TypeError):
            continue
    _excluded_headings = exclude_semantic_structure_headings(
        ledger,
        _classification,
    )
    if _excluded_headings:
        print(
            f"   来源结构标题: {len(_excluded_headings)} 段（已审计，不计入正文覆盖分母）"
        )
    # 只按输出中可验证的原文、表格单元格或媒体哈希认定已覆盖。
    # 不再因“存在路由计划”而虚构 100% 覆盖率。
    mark_covered_from_output(ledger, out_path)
    mark_exact_fragment_coverage(ledger, out_path)
    mark_structured_indicator_coverage(ledger, out_path)

    # 2. 生成覆盖率报告
    rpt_dir = Path(out_path).parent
    # Sidecars are per-artifact.  A fixed filename lets concurrent/repeated
    # jobs overwrite one another and makes a report appear to describe the
    # wrong DOCX.
    rpt_path = Path(out_path).with_suffix(".coverage_report.md")
    rpt_path.write_text(ledger.coverage_report_md(), encoding="utf-8")
    ledger.save(Path(out_path).with_suffix(".coverage_ledger.json"))

    print(f"\n📊 覆盖率账本:")
    bt = ledger.by_type
    print(f"   段落: {bt.get('paragraph',0)}  表格: {bt.get('table',0)}"
          f"  图片: {bt.get('image',0)}  指标: {bt.get('indicator',0)}")
    print(f"   覆盖报告: {rpt_path.name}")

    # 3. QA门禁检查输出文档
    cfg = cfg or {}
    qa_profile = cfg.get("qa_profile", {}) or {}
    forbidden_phrases = list(qa_profile.get("forbidden_phrases", []))
    preserved_template_phrases: list[str] = []
    if preserve_template_guidance and template_path and Path(template_path).is_file():
        try:
            with zipfile.ZipFile(template_path) as template_package:
                template_root = etree.fromstring(template_package.read("word/document.xml"))
            template_text = " ".join(
                node.text or "" for node in template_root.findall(f".//{qn('w:t')}")
            )
            preserved_template_phrases = [
                phrase for phrase in forbidden_phrases if phrase in template_text
            ]
            forbidden_phrases = [
                phrase for phrase in forbidden_phrases if phrase not in preserved_template_phrases
            ]
        except Exception as exc:
            print(f"   ⚠ 模板基线污染词核对失败: {exc}")
    template_phrase_rules = [] if preserve_template_guidance else [
        "20xx年x月", "XX技术协议", "XXh", "（此处填写",
        "请在此处", "□", "▲",
    ]
    qa_rules = {
        "block_if": {
            "red_text_count_gt": 10**9 if preserve_template_guidance else 0,
            "highlight_count_gt": 10**9 if preserve_template_guidance else 0,
            "change_record_data_rows_gt": 10**9 if preserve_template_guidance else 1,
            "indicator_table_wrong_columns": True,
            "indicator_instruction_exists": True,
            "indicator_change_record_contamination": True,
            "landscape_section_exists": True,
            "figure_caption_orphan_auto": True,
            "duplicate_body_image_relationship": True,
            "template_phrases_exist": template_phrase_rules,
            "forbidden_phrases_exist": forbidden_phrases,
            "required_phrases_all": qa_profile.get("required_phrases_all", []),
            "required_phrase_groups": qa_profile.get("required_phrase_groups", []),
            "required_headings": qa_profile.get("required_headings", []),
            "required_figure_captions": qa_profile.get("required_figure_captions", []),
            "required_table_keywords": qa_profile.get("required_table_keywords", []),
            "required_table_headers": qa_profile.get("required_table_headers", []),
        },
        "warn_if": {
            "standard_version_conflict": True,
            "standard_sort_wrong": bool(cfg.get("std_sort_order")),
            "cover_phase_empty": True,
            "failure_mode_table_empty": True,
        }
    }
    qa_flags = {
        "is_as9100": bool(qa_profile.get("is_as9100", False)),
        "is_civil_aircraft": bool(qa_profile.get("is_civil_aircraft", False)),
        "allow_landscape": bool(qa_profile.get("allow_landscape", False)),
        "standard_sort_order": cfg.get("std_sort_order", []),
        "standards_heading_keywords": qa_profile.get(
            "standards_heading_keywords",
            ["适用的法律法规要求", "适用法律法规", "引用标准"],
        ),
    }
    gate = QAGate(qa_rules, qa_flags)

    with zipfile.ZipFile(out_path) as z:
        doc_xml = z.read("word/document.xml")
    root = etree.fromstring(doc_xml)
    result = gate.check(root)

    # Sidecar evidence is part of the delivery proof.  A clean-looking DOCX
    # must not pass when the semantic executor or classifier routed one source
    # block more than once.
    duplicate_routes: list[str] = []
    for suffix, field in (
        (".semantic_plan.json", "decisions"),
        (".semantic_evidence.json", "inserted"),
        (".requirement_classification.json", "classifications"),
    ):
        sidecar = Path(out_path).with_suffix(suffix)
        if not sidecar.is_file():
            continue
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            rows = payload.get(field, []) if isinstance(payload, dict) else []
            source_ids = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                values = row.get("source_ids") or [row.get("source_id")]
                source_ids.extend(str(value) for value in values if value)
            from collections import Counter
            duplicate_routes.extend(
                f"{source_id}×{count}"
                for source_id, count in Counter(source_ids).items()
                if count > 1
            )
        except (OSError, json.JSONDecodeError):
            result.setdefault("warnings", []).append(f"语义证据旁车读取失败：{sidecar.name}")
    if duplicate_routes:
        result["blocked"] = True
        result.setdefault("block_reasons", []).insert(
            0, "同一原文块被多个槽位重复路由：" + "、".join(duplicate_routes[:20])
        )
    if preserve_template_guidance:
        result.setdefault("warnings", []).append(
            "已启用受控模板保留策略：未填章节的模板提示、红字和高亮不作为阻断项"
        )
    if preserved_template_phrases:
        result.setdefault("warnings", []).append(
            "以下词来自受控模板原始保留区，未由本次输入或语义路由新增："
            + "、".join(preserved_template_phrases)
        )

    # 覆盖率是独立硬门禁。QA 格式检查通过也不能掩盖输入漏转。
    if not ledger.passed():
        result["blocked"] = True
        result["block_reasons"].insert(
            0,
            f"输入覆盖率未通过：{ledger.covered_count}/{ledger.total}，"
            f"仍有 {len(ledger.uncovered)} 块缺少输出证据",
        )

    print(f"\n🔍 QA门禁检查:")
    if result["red_count"] > 0:
        print(f"   ⚠ 残余红字: {result['red_count']} 处")
    if result["hl_count"] > 0:
        print(f"   ⚠ 残余高亮: {result['hl_count']} 处")
    for w in result["warnings"]:
        print(f"   ⚠ 警告: {w}")

    _GATE_CATEGORIES = [
        ("输入覆盖", ["输入覆盖率未通过"]),
        ("模板/污染", ["模板词残留", "跨项目/污染词残留"]),
        ("图题/图片",  ["关键图题缺失", "图题", "附近无图片"]),
        ("表格结构",  ["关键表内容缺失", "关键表「", "关键章节缺失"]),
        ("关键内容",  ["关键内容缺失", "关键内容组缺失"]),
        ("格式/变更", ["残余红字", "残余高亮", "变更记录", "指标表"]),
    ]

    def _classify(reason: str) -> str:
        for cat, kws in _GATE_CATEGORIES:
            if any(kw in reason for kw in kws):
                return cat
        return "其他"

    if result["blocked"]:
        from collections import defaultdict
        by_cat: dict = defaultdict(list)
        for r in result["block_reasons"]:
            by_cat[_classify(r)].append(r)
        print(f"   ❌ 门禁未通过 ({len(result['block_reasons'])} 项):")
        for cat, reasons in by_cat.items():
            print(f"      [{cat}]")
            for r in reasons:
                print(f"         - {r}")

        # 写入 qa_gate_report.md
        qa_rpt = Path(out_path).with_suffix(".qa_gate_report.md")
        lines_md = [
            f"# QA 门禁报告\n",
            f"**文档**: {Path(out_path).name}  \n",
            f"**状态**: ❌ 未通过（{len(result['block_reasons'])} 项阻断）\n\n",
        ]
        for cat, reasons in by_cat.items():
            lines_md.append(f"## {cat}\n")
            for r in reasons:
                lines_md.append(f"- {r}\n")
            lines_md.append("\n")
        if result["warnings"]:
            lines_md.append("## 警告\n")
            for w in result["warnings"]:
                lines_md.append(f"- {w}\n")
        qa_rpt.write_text("".join(lines_md), encoding="utf-8")
        print(f"   报告已写入: {qa_rpt.name}")
        return False
    else:
        print(f"   ✅ 门禁通过")
        qa_rpt = Path(out_path).with_suffix(".qa_gate_report.md")
        qa_rpt.write_text(
            f"# QA 门禁报告\n\n**文档**: {Path(out_path).name}  \n**状态**: ✅ 通过\n",
            encoding="utf-8",
        )
        return True


def fill(
    tech_path,
    spec_path,
    src_path,
    out_path,
    profile_path,
    finalize: bool = True,
    requirement_classification: dict | None = None,
    category_mapping_path: str | None = None,
    preserve_unfilled_template: bool = False,
    controlled_product_label: str = "",
    controlled_product_domain: str = "",
    development_process: str = "全新",
    product_series: str = "",
    organization_scope: str = "non_central_research",
    cover_phase: str = "",
):
    tech = Document(tech_path)
    spec = Document(spec_path)
    tpl  = Document(src_path)
    from .cover_fields import apply_cover_phase, normalize_cover_phase

    cover_phase = normalize_cover_phase(cover_phase)
    cover_phase_applied = apply_cover_phase(tpl, cover_phase)
    print(f"技术要求: {Path(tech_path).name}")
    print(f"产品规范: {Path(spec_path).name}")
    print(f"模板:     {Path(src_path).name}")

    tech_paras = parse_doc(tech)
    spec_paras = parse_doc(spec)

    # Profile 必须来自入口选定的受控产品目录。
    if _ROUTER_OK:
        _profiles_dir = str(ROOT)
        if profile_path:
            _profiles_dir = str(Path(profile_path).parent)
        cfg, resolved_yaml, type_name = _load_profile(
            tech_path=tech_path,
            profiles_dir=_profiles_dir,
            explicit_profile=profile_path,
            tech_paras=tech_paras,
            spec_paras=spec_paras,
        )
        shown_type = controlled_product_label or type_name
        print(f"配置: {Path(resolved_yaml).name}  [{shown_type}]")
    else:
        with open(profile_path, encoding="utf-8") as _pf:
            cfg = yaml.safe_load(_pf)
        print(f"配置: {Path(profile_path).name}  [{cfg.get('product_type','?')}]")

    route_overrides = _apply_profile_route_overrides(
        requirement_classification,
        cfg,
    )
    _write_profile_route_audit(
        out_path,
        requirement_classification,
        route_overrides,
        cfg,
    )
    if route_overrides:
        print(f"  独立指标语义路由: {len(route_overrides)} 条")

    # 实时扫描模板标题树，生成本次任务的语义槽位映射。
    heading_level_requirements: dict[str, int] = {}
    heading_parent_requirements: dict[str, str] = {}
    heading_preserve_children: set[str] = set()
    heading_insert_positions: dict[str, str] = {}
    heading_empty_policies: dict[str, str] = {}
    heading_write_modes: dict[str, str] = {}
    if not category_mapping_path:
        raise ValueError(
            "现行生成流程必须提供语义分类映射；已禁止按章节号、章节顺序或旧版数字槽位填充"
        )
    if _SCANNER_OK:
        try:
            heading_map = _build_semantic_hmap(src_path)
            _category_map = yaml.safe_load(
                Path(category_mapping_path).read_text(encoding="utf-8")
            ) or {}
            _semantic_rules = {}
            _semantic_rules.update(_category_map.get("semantic_roles") or {})
            _semantic_rules.update(_category_map.get("categories") or {})
            for _category, _rule in _semantic_rules.items():
                if not isinstance(_rule, dict):
                    continue
                _target_headings = _rule.get("target_heading_keywords") or []
                if isinstance(_target_headings, str):
                    _target_headings = [_target_headings]
                if _target_headings:
                    _role = str(_rule.get("target_role", _category)).strip() or _category
                    _semantic_slot = f"role:{_role}"
                    _target_level = int(_rule.get("target_heading_level", 0) or 0)
                    if _target_level:
                        heading_level_requirements[_semantic_slot] = _target_level
                    _target_parent = str(_rule.get("target_parent_heading", "")).strip()
                    if _target_parent:
                        heading_parent_requirements[_semantic_slot] = _target_parent
                    if bool(_rule.get("preserve_child_headings", False)):
                        heading_preserve_children.add(_semantic_slot)
                    _empty_policy = str(_rule.get("empty_policy", "")).strip()
                    if _empty_policy in {"fill_none", "clear_body"}:
                        heading_empty_policies[_semantic_slot] = _empty_policy
                    _write_mode = str(_rule.get("write_mode", "direct_chapter")).strip()
                    if _write_mode in {
                        "direct_chapter",
                        "dynamic_children",
                        "indicator_table",
                        "standards_merge",
                    }:
                        heading_write_modes[_semantic_slot] = _write_mode
                    _insert_position = str(_rule.get("insert_position", "after_heading")).strip()
                    if _insert_position in {"after_heading", "after_children"}:
                        heading_insert_positions[_semantic_slot] = _insert_position
                    for _target_heading in reversed(list(dict.fromkeys(_target_headings))):
                        heading_map.insert(0, ((_target_heading,), _semantic_slot))
            print(f"   模板扫描: 识别 {len(heading_map)} 个章节")
        except Exception as _e:
            raise ValueError(
                f"模板语义标题树扫描失败: {_e}；受控流程禁止退回固定章节号映射"
            ) from _e
    else:
        raise ValueError("模板语义标题树扫描器不可用；受控流程禁止退回固定章节号映射")

    # Profile 可声明已知封面表格位置，但这只能作为快速路径。客户上传文件常会
    # 增删封面表格，不能因为 table_index 改变就退化成使用文件名猜产品。
    from jonhon_taskbook.cover_metadata_extractor import extract_cover_metadata

    cov = cfg.get("cover_map", {})
    cover_meta = extract_cover_metadata(tech_path)
    product = get_cover_field(
        tech,
        cov.get("product", {}).get("table_index", 1),
        cov.get("product", {}).get("row_keywords", ["名称"]),
        cov.get("product", {}).get("value_col", 1),
    ) or cover_meta.get("product_name", "")
    user = get_cover_field(
        tech,
        cov.get("user", {}).get("table_index", 1),
        cov.get("user", {}).get("row_keywords", ["使用单位"]),
        cov.get("user", {}).get("value_col", 1),
    ) or cover_meta.get("customer_unit", "")
    if not product:
        product = Path(tech_path).stem.replace("技术要求", "").replace("（JONHON受控）", "").strip()
    if not user:
        user = "[待补使用单位]"
    print(f"封面: {product!r}  用户: {user!r}")

    content = build_content(
        cfg,
        tech,
        spec,
        tech_paras,
        spec_paras,
        tech_path,
        spec_path,
        template_doc=tpl,
        controlled_product_label=controlled_product_label,
        product_series=product_series,
        requirement_classification=requirement_classification,
        controlled_product_domain=controlled_product_domain,
    )
    standards_audit = content.get("__standards_reference__", {}).get("standards_audit", {})
    Path(out_path).with_suffix(".standards_audit.json").write_text(
        json.dumps(standards_audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    semantic_merge_stats = _merge_classified_content(
        content,
        requirement_classification,
        category_mapping_path,
        tech,
    )
    process_rule_audit = _apply_process_specific_sections(
        tpl,
        requirement_classification,
        development_process,
        controlled_product_label or str(cfg.get("product_type", "")),
        product_series,
        out_path,
    )
    process_rule_audit["cover_phase"] = cover_phase
    process_rule_audit["cover_phase_applied"] = cover_phase_applied
    Path(out_path).with_suffix(".process_rule_audit.json").write_text(
        json.dumps(process_rule_audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    domain_rule_audit = _apply_domain_specific_sections(
        tpl,
        controlled_product_domain,
        out_path,
    )
    from jonhon_taskbook.template_variant_policy import (
        apply_template_variant_policy,
    )

    template_variant_audit = apply_template_variant_policy(
        tpl,
        organization_scope=organization_scope,
        out_path=out_path,
    )
    print(
        f"  研制流程规则: {development_process}；"
        f"故障模式行 {process_rule_audit.get('failure_mode_rows', 0)}"
    )
    if domain_rule_audit.get("deleted_sections"):
        print(
            f"  产品领域规则: {controlled_product_domain}；"
            f"删除不适用章节 {len(domain_rule_audit['deleted_sections'])}"
        )
    print(
        "  模板互斥分支: "
        f"{template_variant_audit['selectors']['organization_scope']['label']}；"
        "审计通过"
    )
    indicator_audit = content.get("role:performance_indicator", {}).get("indicator_audit")
    if indicator_audit:
        indicator_audit_path = Path(out_path).with_suffix(".indicator_audit.json")
        indicator_audit_path.write_text(
            json.dumps(indicator_audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not indicator_audit.get("passed"):
            print(
                "  ⚠ 技术指标审计未通过：已继续生成复核件，"
                "正式交付将由门禁阻断"
            )
    if semantic_merge_stats["slots"]:
        print(
            "  语义分类补位: "
            f"{semantic_merge_stats['slots']} 槽位 / "
            f"{semantic_merge_stats['paragraphs']} 段 / "
            f"{semantic_merge_stats['tables']} 表 / "
            f"{semantic_merge_stats['images']} 图"
        )
    image_decision_warnings = []
    for k, v in content.items():
        print(f"  {k}: {len(v['lines'])} 行  {len(v['tables'])} 表  {len(v['images'])} 图")
        image_decision_warnings.extend(v.get("image_warnings", []))

    # 从 profile 动态读取跨项目污染词；不得用内容替换表改变模板正文。
    _qa_profile = cfg.get("qa_profile") or {}
    _extra_forbidden = list(_qa_profile.get("forbidden_phrases", []))
    _is_junk = _make_is_junk(_extra_forbidden)

    to_del, filled = [], {}
    pending_rich = []  # [(anchor_para, tables, images, caption_ref)]

    heading_stack: list[tuple[int, str]] = []
    for i, p in enumerate(tpl.paragraphs):
        # 前面的空槽策略可能已删除当前节点所属的模板子树。
        if p._p.getparent() is None:
            continue
        t = _txt(p)
        if not preserve_unfilled_template:
            if _all_red(p):   to_del.append(p._p); continue
            _clear_red(p)
            _deep_clean_para(p)
            if _is_junk(p):   to_del.append(p._p); continue

        is_h = _is_heading(p)
        parent_context: list[str] = []
        if is_h:
            level = _heading_level(p)
            while heading_stack and level and heading_stack[-1][0] >= level:
                heading_stack.pop()
            parent_context = [text for _, text in heading_stack]
        if is_h and t:
            for kws, sid in heading_map:
                _required_level = heading_level_requirements.get(sid, 0)
                _required_parent = heading_parent_requirements.get(sid, "")
                if (all(k in t for k in kws)
                        and (not _required_level or _heading_level(p) == _required_level)
                        and (not _required_parent or any(_required_parent in x for x in parent_context))
                        and sid not in filled):
                    c        = content.get(sid, {})
                    lines    = c.get("lines", [])
                    tables   = c.get("tables", [])
                    images   = c.get("images", [])
                    image_warnings = c.get("image_warnings", [])
                    ind_rows = c.get("indicator_rows", [])
                    ordered_elements = c.get("ordered_elements", [])

                    # 即使本次设计输入没有识别到指标，也必须执行一次指标表
                    # 结构治理：严格保留模板原有四列/五列结构，并将模板已有
                    # 指标的用户要求列按 7-22 规则写“\”。不能因为本次为空
                    # 就跳过，否则同一模板会随输入变化产生不同的表结构。
                    if "indicator_rows" in c:
                        _fill_indicator_table(
                            tpl,
                            ind_rows,
                            cfg.get("indicator_excluded_names") or [],
                        )
                    if ind_rows:
                        filled[sid] = (len(ind_rows), 0, 0)
                        break

                    if not lines and not tables and not images and not ordered_elements:
                        empty_policy = heading_empty_policies.get(sid, "")
                        if empty_policy:
                            current_level = _heading_level(p) or _heading_depth_sv(p)
                            scan = p._p.getnext()
                            removed = 0
                            while scan is not None:
                                next_node = scan.getnext()
                                scan_level = 0
                                if scan.tag == qn("w:p"):
                                    scan_para = Paragraph(scan, p._parent)
                                    scan_level = (
                                        _heading_level(scan_para)
                                        or _heading_depth_sv(scan_para)
                                    )
                                if scan_level and scan_level <= current_level:
                                    break
                                parent = scan.getparent()
                                if parent is not None:
                                    parent.remove(scan)
                                    removed += 1
                                scan = next_node
                            if empty_policy == "fill_none":
                                ref = _find_body_ref_after(p)
                                p._p.addnext(_make_p("无。", ref))
                                filled[sid] = (1, 0, 0)
                            else:
                                filled[sid] = (0, 0, 0)
                            print(
                                f"  空槽策略 {sid}: {empty_policy}，"
                                f"清理模板节点 {removed}"
                            )
                        break
                    ref = _find_body_ref_after(p)
                    # 子标题样式必须按实际 Heading 级别判断，不能把模板内部
                    # pStyle ID（例如“4”）误当成业务层级。
                    _current_heading_level = _heading_level(p)
                    child_heading_ref = None
                    _candidate_element = p._p.getnext()
                    while _candidate_element is not None:
                        if _candidate_element.tag != qn("w:p"):
                            _candidate_element = _candidate_element.getnext()
                            continue
                        candidate = Paragraph(_candidate_element, p._parent)
                        _candidate_depth = _heading_level(candidate)
                        if _candidate_depth > 0 and _candidate_depth <= _current_heading_level:
                            break
                        if _candidate_depth == _current_heading_level + 1:
                            child_heading_ref = candidate
                            break
                        _candidate_element = _candidate_element.getnext()
                    # A template is allowed to omit placeholder child
                    # headings entirely.  In that case borrow the first
                    # heading style at the required depth as a style sample;
                    # its numbering definition is still owned by the
                    # template, never by this engine.  This keeps dynamic
                    # ``other`` modules usable after customers simplify or
                    # reorder their template outline.
                    if child_heading_ref is None and _current_heading_level:
                        child_heading_ref = next(
                            (
                                candidate
                                for candidate in tpl.paragraphs
                                if _heading_level(candidate) == _current_heading_level + 1
                            ),
                            None,
                        )
                    # Prefer the structural Heading/outline level; custom
                    # templates may not encode it in the legacy style value
                    # consumed by _heading_depth_sv().
                    _current_depth = _heading_depth_sv(p) or _current_heading_level
                    prev = p._p
                    if heading_insert_positions.get(sid) == "after_children":
                        _scan_tail = p._p.getnext()
                        while _scan_tail is not None:
                            _tail_depth = 0
                            if _scan_tail.tag == qn("w:p"):
                                _tail_ppr = _scan_tail.find(qn("w:pPr"))
                                _tail_ps = (
                                    _tail_ppr.find(qn("w:pStyle"))
                                    if _tail_ppr is not None else None
                                )
                                _tail_depth = _heading_depth_sv_val(
                                    _tail_ps.get(qn("w:val"), "") if _tail_ps is not None else ""
                                )
                                if not _tail_depth:
                                    _tail_depth = _heading_level(
                                        Paragraph(_scan_tail, p._parent)
                                    )
                            if _tail_depth > 0 and _tail_depth <= _current_depth:
                                break
                            prev = _scan_tail
                            _scan_tail = _scan_tail.getnext()

                    # 先清掉模板该章节标题下已有旧内容，再插入新内容
                    # 规则：当前标题深度 N，遇到深度 <= N 的标题才停止；更深的子标题也删
                    # 配置声明了“替换章节正文”时，lines-only 也要清除模板旧内容。
                    # 这里不使用任何固定章节号；标准引用角色由语义映射配置声明。
                    if (
                        preserve_unfilled_template
                        or tables
                        or images
                        or ordered_elements
                        or (bool(c.get("replace_existing")) and lines)
                    ):
                        _cur_depth = _heading_depth_sv(p) or _current_heading_level
                        _del_existing = []
                        _scan = p._p.getnext()
                        while _scan is not None:
                            _stag = _scan.tag.split("}")[-1] if "}" in _scan.tag else _scan.tag
                            if _stag == "p":
                                _scan_txt = "".join(
                                    xe.text or "" for xe in _scan.findall(f".//{qn('w:t')}")
                                ).strip()
                                _scan_ppr = _scan.find(qn("w:pPr"))
                                _scan_ps  = _scan_ppr.find(qn("w:pStyle")) if _scan_ppr is not None else None
                                _scan_sv  = _scan_ps.get(qn("w:val"), "") if _scan_ps is not None else ""
                                _scan_depth = _heading_depth_sv_val(_scan_sv)
                                if not _scan_depth:
                                    _scan_depth = _heading_level(
                                        Paragraph(_scan, p._parent)
                                    )
                                # Populated dynamic slots own their complete subtree;
                                # stale child headings (for example a template ``……``
                                # row) must not survive just because the slot is marked
                                # preservable.  Preservation applies only to unfilled,
                                # static slots.
                                _preserve_children_here = (
                                    sid in heading_preserve_children
                                    and heading_write_modes.get(sid) != "dynamic_children"
                                )
                                if (_scan_depth > 0 and (
                                        _scan_depth <= _cur_depth
                                        or _preserve_children_here
                                )):
                                    break
                                if (not preserve_unfilled_template
                                        and _scan.find('.//' + qn('w:drawing')) is not None):
                                    _scan = _scan.getnext()
                                    continue
                                _del_existing.append(_scan)
                            elif _stag == "tbl":
                                _del_existing.append(_scan)
                            _scan = _scan.getnext()
                        for _el in _del_existing:
                            _par = _el.getparent()
                            if _par is not None:
                                _par.remove(_el)
                        # ``after_children`` may point at the last placeholder
                        # paragraph when the current template has no child
                        # headings.  That placeholder is intentionally removed
                        # above; inserting after the detached node would create
                        # content that never reaches document.xml.  Existing
                        # real child headings remain valid anchors, otherwise
                        # fall back to the live parent heading.
                        if prev.getparent() is None:
                            prev = p._p

                    # 清除完成后再插入 lines
                    for line in lines:
                        if not line: continue
                        # 标准清单是重新汇总出的正式正文；模板首个标准
                        # 占位段可能为斜体提示语，不能将其格式污染到每一行。
                        np = _make_p(
                            line,
                            ref,
                            # 标准引用是重建的正式正文；不要把模板中的斜体占位样式
                            # 复制到每一条标准。其它槽位仍按模板原样保留样式。
                            preserve_italic=(sid != "role:standards_reference"),
                        )
                        prev.addnext(np); prev = np

                    # 表格 addnext
                    for tbl_el, caption in tables:
                        if caption:
                            cp = _make_p(caption, ref)
                            prev.addnext(cp); prev = cp
                        prev.addnext(tbl_el); prev = tbl_el
                    def _append_ordered_element(item):
                        nonlocal prev
                        kind = item.get("kind")
                        if kind == "paragraph":
                            element = item.get("element")
                            if element is not None:
                                prev.addnext(element); prev = element
                            else:
                                np = _make_p(str(item.get("text", "")), ref)
                                prev.addnext(np); prev = np
                        elif kind in {"table", "image"} and item.get("element") is not None:
                            element = item["element"]
                            prev.addnext(element); prev = element

                    # 技术要求按整章节分类后，严格保持段落/表格/图片的原始顺序。
                    # “其他要求”的每个完整来源模块建立一个子标题。
                    # 子标题的显示编号完全由当前模板多级列表决定，代码不读取也不生成数字。
                    if sid == "role:other":
                        for module in _other_module_groups(ordered_elements):
                            module_heading_ref = (
                                child_heading_ref if child_heading_ref is not None else ref
                            )
                            # This is a template child-heading, not source
                            # body text: preserve its numbering definition so
                            # Word assigns the current template's next number
                            # automatically.  The title
                            # itself remains number-free and comes from the
                            # source semantic chapter.
                            heading = _make_heading_p(
                                module["title"],
                                module_heading_ref,
                            )
                            prev.addnext(heading); prev = heading
                            for item in module["items"]:
                                _append_ordered_element(item)
                    elif heading_write_modes.get(sid) == "dynamic_children":
                        # 条件保障的子章节由来源章节标题决定（如“验收要求”
                        # 与“交付要求”），正文段落/表格保持原始内容与顺序。
                        # 不能把每一条验收/交付句子误生成为三级标题。
                        for module in _technical_support_module_groups(
                            ordered_elements
                        ):
                            heading = _make_heading_p(
                                module["title"],
                                (
                                    child_heading_ref
                                    if child_heading_ref is not None
                                    else ref
                                ),
                            )
                            prev.addnext(heading)
                            prev = heading
                            for item in module["items"]:
                                _append_ordered_element(item)
                    else:
                        for item in ordered_elements:
                            _append_ordered_element(item)
                    # 图片延迟插入：记录锚点，save 之后用 lxml 直接操作 XML
                    if images:
                        pending_rich.append((p, images, ref))
                    if image_warnings:
                        for _w in image_warnings:
                            print(f"   ⚠ {_w}")
                    filled[sid] = (
                        len(lines) + sum(x.get("kind") == "paragraph" for x in ordered_elements),
                        len(tables) + sum(x.get("kind") == "table" for x in ordered_elements),
                        len(images) + sum(x.get("kind") == "image" for x in ordered_elements),
                    )
                    break
            heading_stack.append((_heading_level(p), t))

    if requirement_classification:
        unresolved_roles = []
        for sid, c in content.items():
            has_payload = bool(
                c.get("lines")
                or c.get("tables")
                or c.get("images")
                or c.get("ordered_elements")
                or c.get("indicator_rows")
            )
            if has_payload and sid not in filled:
                unresolved_roles.append(sid)
        if unresolved_roles:
            raise ValueError(
                "模板中无法按语义标题/父子路径定位以下受控角色: "
                + ", ".join(sorted(unresolved_roles))
                + "。已停止生成，未将内容改投其他章节。"
            )
    else:
        raise ValueError("缺少全量语义分类结果；受控流程不允许进入旧版兼容填充")

    for elem in to_del:
        par = elem.getparent()
        if par is not None: par.remove(elem)

    compilation_basis_audit = _apply_compilation_basis(
        tpl,
        tech_path,
        spec_path,
        out_path,
    )
    print(
        "  编制依据: "
        f"{compilation_basis_audit['title']}"
        + (
            f" / {compilation_basis_audit['number']}"
            if compilation_basis_audit["number"] else ""
        )
    )

    print(f"删除: {len(to_del)}  填充: {list(filled.keys())}")
    if image_decision_warnings:
        print("\n🖼 图片决策:")
        for _w in image_decision_warnings:
            print(f"   ⚠ {_w}")
        try:
            import json as _json
            (Path(out_path).with_suffix(Path(out_path).suffix + ".image_warnings.json")).write_text(
                _json.dumps(image_decision_warnings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as _img_warn_err:
            print(f"   ⚠ 图片决策写出失败: {_img_warn_err}")

    # 封面字段替换
    for p in tpl.paragraphs:
        t2 = _txt(p)
        normalized_t2 = re.sub(r"\s+", "", t2)
        full_text = "".join(r.text or "" for r in p.runs)
        if re.match(r"^名称[:：]", normalized_t2):
            if p.runs:
                p.runs[0].text = "名    称"
                if len(p.runs) >= 2:
                    p.runs[1].text = "："
                if len(p.runs) >= 3:
                    p.runs[2].text = product
                    for r in p.runs[3:]:
                        r.text = ""
                else:
                    p.add_run("：")
                    p.add_run(product)
            else:
                p.add_run(f"名    称：{product}")
        elif re.match(r"^使用单位[:：]", normalized_t2):
            if p.runs:
                p.runs[0].text = "使用单位："
                if len(p.runs) >= 2:
                    p.runs[1].text = user
                    for r in p.runs[2:]:
                        r.text = ""
                else:
                    p.add_run(user)
            else:
                p.add_run(f"使用单位：{user}")
        elif ("名称" in t2 or "型号" in t2) and len(t2) <= 24 and ("（型号名称）" not in t2 and "(型号名称)" not in t2):
            if product and not any(product in (r.text or "") for r in p.runs):
                for r in p.runs:
                    if not (r.text or "").strip():
                        r.text = product
                        break
        if re.match(r"^20\s+年\s+月", full_text.strip()):
            from datetime import datetime
            now = datetime.now()
            date_str = f"{now.year}年{now.month}月{now.day}日"
            # 把第一个 run 写入日期，其余 run 清空
            runs = p.runs
            if runs:
                runs[0].text = date_str
                for r in runs[1:]:
                    r.text = ""
            continue  # 跳过下面的逐 run 处理

        for r in p.runs:
            tx = r.text or ""
            if "（型号名称）" in tx or "(型号名称)" in tx:
                r.text = tx.replace("（型号名称）", product).replace("(型号名称)", product)
            if "20xx年x月" in tx:
                r.text = tx.replace("20xx年x月", "")
            # 单 run 内的日期占位（兜底）
            if re.match(r"^20\s+年\s+月", tx):
                from datetime import datetime
                now = datetime.now()
                r.text = f"{now.year}年{now.month}月{now.day}日"

    cr_del = _clean_change_record(tpl)
    if cr_del:
        print(f"变更记录: 删除 {cr_del} 行历史数据")
    if _seed_change_record_default(tpl):
        print("变更记录: 已补默认行 A / 新发")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    # python-docx save() 会丢弃从外部文件 addnext 进来的图片 XML。
    # 解决方案：save 之前用 lxml 序列化完整的 document body，
    # save 之后把这份完整 XML 写回 docx 的 word/document.xml。
    from lxml import etree as _etree
    import zipfile as _zf
    _full_doc_xml = _etree.tostring(
        tpl.element,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )
    _draw_before = _full_doc_xml.count(b"<w:drawing")

    tpl.save(out_path)

    if preserve_unfilled_template:
        original = Document(src_path)
        original_paragraphs = list(original.paragraphs)
        records = []
        for index, paragraph in enumerate(original_paragraphs):
            if not _is_heading(paragraph) or not _txt(paragraph):
                continue
            paragraph_text = _txt(paragraph)
            for keywords, sid in heading_map:
                required_level = heading_level_requirements.get(sid, 0)
                if (all(keyword in paragraph_text for keyword in keywords)
                        and (not required_level or _heading_level(paragraph) == required_level)):
                    records.append({
                        "slot": sid,
                        "heading": paragraph_text,
                        "index": index,
                        "level": _heading_level(paragraph),
                    })
                    break

        for record in records:
            record["end"] = len(original_paragraphs)
            for paragraph_index in range(record["index"] + 1, len(original_paragraphs)):
                paragraph = original_paragraphs[paragraph_index]
                level = _heading_level(paragraph) if _is_heading(paragraph) else 0
                if level and level <= record["level"]:
                    record["end"] = paragraph_index
                    break

        filled_ranges = [
            (record["index"], record["end"])
            for record in records
            if record["slot"] in filled
        ]
        preserved = []
        for record in records:
            if record["slot"] in filled:
                continue
            candidate_range = (record["index"], record["end"])
            overlaps_filled = any(
                start < candidate_range[1] and candidate_range[0] < end
                for start, end in filled_ranges
            )
            if not overlaps_filled:
                preserved.append({
                    "slot": record["slot"],
                    "heading": record["heading"],
                    "reason": "无来源内容，原模板保持不变",
                })
        preservation_path = Path(out_path).with_suffix(".preservation.json")
        preservation_path.write_text(
            json.dumps(
                {
                    "policy": "preserve_unfilled_template",
                    "filled_slots": sorted(filled),
                    "preserved_slots": preserved,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # ── 图片注入：绕过 python-docx save() 的命名空间限制 ─────────────────────
    # 用 lxml+zipfile 直接操作 document.xml，把图片段落插入锚点之后
    if pending_rich:
        import zipfile as _zf2
        from lxml import etree as _et2
        import copy as _copy2

        # 读取 save 后的 docx 全部文件（需要更新的 media/rels 等）
        with _zf2.ZipFile(out_path, "r") as _zin2:
            _all_files2 = {n: _zin2.read(n) for n in _zin2.namelist()}

        # 以 save 之前的完整 lxml 树（含 deepcopy 进来的表格）作为 base
        # 而不是 save 之后被 python-docx 截断的版本
        _W2 = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        _doc_root2 = _et2.fromstring(_full_doc_xml)
        _body2 = _doc_root2.find(f"{{{_W2}}}body")

        # 建立锚点文字 → body 子元素的映射
        def _p_key(p_el):
            return "".join(t.text or "" for t in p_el.findall(f".//{{{_W2}}}t")).strip()[:60]

        body_paras = {_p_key(c): c for c in _body2 if c.tag == f"{{{_W2}}}p"}

        total_injected = 0
        for anchor_p, images, ref in pending_rich:
            anchor_txt = "".join(r.text or "" for r in anchor_p.runs).strip()[:60]
            anchor_el = body_paras.get(anchor_txt)
            if anchor_el is None:
                # 退而求其次：遍历找包含锚点文字的段落
                for c in _body2:
                    if c.tag == f"{{{_W2}}}p":
                        if anchor_txt and anchor_txt in _p_key(c):
                            anchor_el = c; break
            if anchor_el is None:
                continue
            # 图片插在锚点后面（reverse 保持顺序）
            prev_el = anchor_el
            for img in images:
                caption = img.get("caption", "") if isinstance(img, dict) else img[1]
                img_el = img.get("image_el") if isinstance(img, dict) else img[0]
                if caption:
                    cap_p = _et2.SubElement(_body2, f"{{{_W2}}}p")
                    cap_r = _et2.SubElement(cap_p, f"{{{_W2}}}r")
                    cap_t = _et2.SubElement(cap_r, f"{{{_W2}}}t")
                    cap_t.text = caption
                    _body2.remove(cap_p)
                    prev_el.addnext(cap_p)
                    prev_el = cap_p
                img_copy = _copy2.deepcopy(img_el)
                prev_el.addnext(img_copy)
                prev_el = img_copy
                total_injected += 1

        if total_injected:
            _new_xml2 = _et2.tostring(_doc_root2, xml_declaration=True,
                                      encoding="UTF-8", standalone=True)
            _all_files2["word/document.xml"] = _new_xml2
            _tmp2 = out_path + ".imgpatch.tmp"
            with _zf2.ZipFile(_tmp2, "w", _zf2.ZIP_DEFLATED) as _zout2:
                for _nm2, _dat2 in _all_files2.items():
                    _zout2.writestr(_nm2, _dat2)
            import shutil as _sh2
            _sh2.move(_tmp2, out_path)
            print(f"   图片XML注入: {total_injected} 张图片写入 document.xml")

    # ── 原有 lxml 回写逻辑（保留作兜底，现在应该不需要）─────────────────────
    _tmp_path = out_path + ".imgfix.tmp"
    with _zf.ZipFile(out_path, "r") as _zin:
        _saved_xml = _zin.read("word/document.xml")
        _draw_after = _saved_xml.count(b"<w:drawing")

    if _draw_before > _draw_after:
        # save() 确实丢失了图片，用 lxml 版本替换
        with _zf.ZipFile(out_path, "r") as _zin,              _zf.ZipFile(_tmp_path, "w", _zf.ZIP_DEFLATED) as _zout:
            for _name in _zin.namelist():
                _data = _zin.read(_name)
                if _name == "word/document.xml":
                    _data = _full_doc_xml
                _zout.writestr(_name, _data)
        import shutil as _shutil
        _shutil.move(_tmp_path, out_path)
        print(f"   图片XML修复: {_draw_before} 个 drawing 已写回 document.xml")

    # 注入技术要求里的图片媒体文件（rId 注册）
    try:
        from jonhon_taskbook.media_injector import inject_media
        n_img = inject_media(tech_path, out_path)
        if n_img:
            print(f"   图片媒体注入: {n_img} 个文件")
    except Exception as e:
        print(f"   ⚠ 图片媒体注入失败: {e}")

    print("   正文写入: 受控语义分类 + 原文精确搬运（不生成正文）")

    print(f"\n✅ {out_path}")
    if finalize:
        # 直接调用 fill() 时保留完整收尾；统一 pipeline 会传 finalize=False，
        # 避免后处理、覆盖率、QA 和 HTML 报告各执行两遍。
        d2 = Document(out_path)
        print(f"   段落: {len(d2.paragraphs)}  表格: {len(d2.tables)}")
        del d2
        try:
            from jonhon_taskbook.postprocess import postprocess as _post
            ps = _post(out_path)
            print(f"   后处理: 红字改黑 {ps['red_cleared']}  "
                  f"高亮清除 {ps['hl_cleared']}  "
                  f"日期清除 {ps['date_cleared']}  "
                  f"整段删除 {ps['para_deleted']}")
        except Exception as e:
            print(f"   ⚠ 后处理失败: {e}")
        run_coverage_and_qa(tech_path, out_path, cfg)
        try:
            from jonhon_taskbook.html_reporter import generate_report as _html
            rpt = _html(out_path)
            print(f"   HTML报告: {Path(rpt).name}")
        except Exception as e:
            print(f"   ⚠ HTML报告失败: {e}")


def main():
    ap = argparse.ArgumentParser(description="配置驱动研制任务书填充")
    ap.add_argument("--tech", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--category-mapping", required=True)
    args = ap.parse_args()
    for label, path in [("技术要求",args.tech),("产品规范",args.spec),
                        ("模板",args.src),("配置",args.profile)]:
        if not Path(path).exists():
            print(f"错误：{label} 不存在: {path}"); sys.exit(1)
    fill(
        args.tech, args.spec, args.src, args.out, args.profile,
        category_mapping_path=args.category_mapping,
    )


if __name__ == "__main__":
    main()
