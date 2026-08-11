"""
文档待填区域检测：封面字段、占位符、模板说明（红字语义）、空章节槽位、表格空单元格。

规则引擎为主；仅对「结构已识别但无来源」的槽位可选调用 LLM（见 llm_zone_resolver）。
"""
import re
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree

from .config import W
from .docx_io import get_cell_text, get_para_text
from .template_cleanup import INSTRUCTION_KEYWORDS, strip_parenthetical_instructions

PLACEHOLDER_RE = re.compile(
    r"……|\.\.\.|\.{4,}|_{2,}|(?<![a-zA-Z])\bXX\b(?![a-zA-Z])|"
    r"\bxxx\b|20\s*年\s*月|20[xX]{2}|F/C/S/D|（型号名称）",
    re.I,
)

SECTION_HEADING_RE = re.compile(
    r"^(\d+(?:\.\d+)*)\s+(\S.+)$|^附录\s*[A-Z]?\s*|^第[一二三四五六七八九十]+章",
)

SECTION_TITLE_KEYWORDS = (
    "来源和功能", "使用环境和部位", "安装形式和方法", "产品组成",
    "适用的法律法规", "接口尺寸要求", "条件保障要求", "初步的失效模式",
    "顾客的特殊要求", "通用质量特性", "工艺要求", "以前类似设计",
    "设计开发所需", "涉密科研", "任务进度要求", "研制经费", "任务书编制依据",
)

# 仅作为表格/子标题，不算「空章节」
TABLE_SUBHEADINGS = (
    "可能发生的失效模式", "失效模式机理", "故障原因", "故障影响",
    "严酷度", "发生概率", "检测方法", "纠正措施", "技术指标",
    "电性能", "机械性能", "环境性能",
)

COVER_LABELS = (
    (re.compile(r"研制阶段[：:]"), "cover_phase", "研制阶段"),
    (re.compile(r"名\s*称[：:]"), "cover_product_name", "产品名称"),
    (re.compile(r"使用单位[：:]"), "cover_customer_unit", "使用单位"),
    (re.compile(r"研制单位[：:]"), "cover_developer_unit", "研制单位"),
    (re.compile(r"^20\s*年\s*月$"), "cover_doc_date", "封面日期"),
)

INSTRUCTION_LINE_RE = re.compile(
    r"^[（(].{6,}[）)]$|删除|设计填写|设计员|没有可写|适用时|可删除|可附图|"
    r"根据具体情况|待设计|请填写|型号名称",
)


@dataclass
class FillZone:
    zone_type: str
    location: str
    heading: str = ""
    snippet: str = ""
    severity: str = "MEDIUM"
    suggested_action: str = ""
    auto_fillable: bool = False
    field_key: str = ""
    para_index: int = -1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _is_placeholder_text(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if t in {"……", "...", "无", "/"}:
        return t in {"……", "..."}
    return bool(PLACEHOLDER_RE.search(t))


def _is_instruction_text(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if INSTRUCTION_LINE_RE.search(t):
        return True
    if t.startswith("（") and t.endswith("）") and any(k in t for k in INSTRUCTION_KEYWORDS):
        return True
    return False


def _has_red_markup(para) -> bool:
    """检测 run 级颜色/高亮/下划线（模板红字常通过这些标记）。"""
    for r in para.findall(f".//{{{W}}}r"):
        col = r.find(f"{{{W}}}color")
        if col is not None:
            val = (col.get(f"{{{W}}}val") or "").upper()
            if val in ("FF0000", "C00000", "EE0000", "C0504D", "RED", "DARKRED"):
                return True
        hi = r.find(f"{{{W}}}highlight")
        if hi is not None:
            val = (hi.get(f"{{{W}}}val") or "").upper()
            if val in ("RED", "DARKRED", "YELLOW"):
                return True
        u = r.find(f"{{{W}}}u")
        if u is not None and (u.get(f"{{{W}}}val") or "") not in ("", "none"):
            txt = "".join(t.text or "" for t in r.findall(f".//{{{W}}}t"))
            if txt.strip() and _is_instruction_text(txt):
                return True
    return False


def _is_section_heading(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 90 or t.endswith("。"):
        return False
    if re.match(r"^\d{4}\s*年\s*\d", t) or re.match(r"^20\s*年", t):
        return False
    if "中航光电" in t or "研制任务书" in t:
        return False
    if SECTION_HEADING_RE.match(t):
        return True
    if any(k in t for k in SECTION_TITLE_KEYWORDS) and len(t) < 50:
        return True
    return False


def _label_value_empty(text: str, label_pat: re.Pattern) -> Tuple[bool, str]:
    m = label_pat.search(text)
    if not m:
        return False, ""
    rest = text[m.end() :].strip()
    if not rest or _is_placeholder_text(rest):
        return True, rest
    return False, rest


def detect_cover_zones(paras: List, limit: int = 45) -> List[FillZone]:
    zones: List[FillZone] = []
    for i, para in enumerate(paras[:limit]):
        text = get_para_text(para).strip()
        if not text:
            continue
        for pat, field_key, label in COVER_LABELS:
            if pat.search(text):
                empty, _ = _label_value_empty(text, pat)
                if empty or field_key == "cover_doc_date":
                    zones.append(
                        FillZone(
                            zone_type="COVER_FIELD",
                            location=f"封面段落#{i}",
                            heading=label,
                            snippet=text[:120],
                            severity="BLOCKER",
                            suggested_action=f"填写封面{label}",
                            auto_fillable=True,
                            field_key=field_key,
                            para_index=i,
                        )
                    )
                break
        if re.match(r"^20\s*年\s*月", text):
            zones.append(
                FillZone(
                    zone_type="COVER_FIELD",
                    location=f"封面段落#{i}",
                    heading="封面日期",
                    snippet=text,
                    severity="BLOCKER",
                    suggested_action="填写封面年月",
                    auto_fillable=True,
                    field_key="cover_doc_date",
                    para_index=i,
                )
            )
        if "F/C/S/D" in text and "研制阶段" in text:
            zones.append(
                FillZone(
                    zone_type="COVER_FIELD",
                    location=f"封面段落#{i}",
                    heading="研制阶段",
                    snippet=text[:120],
                    severity="HIGH",
                    suggested_action="将 F/C/S/D 占位改为实际研制阶段（如 C）",
                    auto_fillable=True,
                    field_key="cover_phase",
                    para_index=i,
                )
            )
    return zones


def detect_placeholder_zones(paras: List) -> List[FillZone]:
    zones = []
    for i, para in enumerate(paras):
        text = get_para_text(para).strip()
        if not text or re.match(r"^图\s*\d+", text):
            continue
        if _is_placeholder_text(text):
            zones.append(
                FillZone(
                    zone_type="PLACEHOLDER",
                    location=f"段落#{i}",
                    snippet=text[:120],
                    severity="BLOCKER",
                    suggested_action="替换省略号/XX/日期占位",
                    auto_fillable=False,
                    para_index=i,
                )
            )
    return zones


def detect_instruction_zones(paras: List) -> List[FillZone]:
    zones = []
    for i, para in enumerate(paras):
        text = get_para_text(para).strip()
        if not text:
            continue
        is_inst = _is_instruction_text(text) or _has_red_markup(para)
        if is_inst:
            zones.append(
                FillZone(
                    zone_type="TEMPLATE_INSTRUCTION",
                    location=f"段落#{i}",
                    snippet=text[:160],
                    severity="HIGH",
                    suggested_action="删除或替换模板红字/括号说明",
                    auto_fillable=True,
                    para_index=i,
                )
            )
    return zones


def _element_has_following_table(paras: List, texts: List[str], start_idx: int, root) -> bool:
    """标题后若干段内是否紧跟表格（4.1 等指标在表里不算空章节）。"""
    body = root.find(f"{{{W}}}body")
    if body is None:
        return False
    # 简化：标题后 8 段内有「表」字或已填长文本
    for j in range(start_idx + 1, min(start_idx + 9, len(texts))):
        t = texts[j]
        if re.match(r"^表\s*\d+", t):
            return True
        if re.match(r"^4\.1", texts[start_idx]) and len(t) > 15:
            return True
    return False


def detect_empty_section_zones(paras: List, root=None, lookahead: int = 8) -> List[FillZone]:
    """标题下无正文：需有编号章节或明确章标题，且后续无表格/正文。"""
    zones = []
    texts = [get_para_text(p).strip() for p in paras]

    for i, text in enumerate(texts):
        if i < 35 and not re.match(r"^\d+(?:\.\d+)*\s", text):
            continue
        if text in TABLE_SUBHEADINGS:
            continue
        if not _is_section_heading(text):
            continue
        if i < 40 and any(k in text for k in ("变更记录", "章条编号", "版本")):
            continue
        # 必须有章节编号（避免「技术指标」单独误报）或完整章名
        has_number = bool(re.match(r"^\d+(?:\.\d+)*\s+\S", text))
        if not has_number and not re.match(r"^附录", text):
            if not any(k in text for k in ("失效模式", "工艺要求", "类似设计", "顾客的特殊", "编制依据")):
                continue

        if root is not None and _element_has_following_table(paras, texts, i, root):
            continue

        j = i + 1
        found_body = False
        while j < min(i + 1 + lookahead, len(texts)):
            nt = texts[j]
            if not nt:
                j += 1
                continue
            if nt in TABLE_SUBHEADINGS:
                j += 1
                continue
            if _is_section_heading(nt) and has_number:
                break
            if _is_instruction_text(nt):
                j += 1
                continue
            if _is_placeholder_text(nt):
                j += 1
                continue
            if len(nt) >= 8 and not nt.startswith("表"):
                found_body = True
                break
            j += 1

        if not found_body:
            zones.append(
                FillZone(
                    zone_type="EMPTY_SECTION",
                    location=f"段落#{i}",
                    heading=text[:80],
                    snippet=text[:120],
                    severity="HIGH",
                    suggested_action="章节标题下缺少正文，需从技术要求抽取或人工填写",
                    auto_fillable=True,
                    field_key=f"section:{text[:40]}",
                    para_index=i,
                )
            )
    return zones


def detect_table_empty_zones(root, catalog_names: set = None) -> List[FillZone]:
    from .indicator_catalog_loader import get_indicator_catalog

    if catalog_names is None:
        indicator_catalog = get_indicator_catalog()
        catalog_names = {e["name"] for e in indicator_catalog}
        for e in indicator_catalog:
            catalog_names.update(e.get("aliases", []))

    zones = []
    for ti, table in enumerate(root.findall(f".//{{{W}}}tbl")):
        rows = table.findall(f"{{{W}}}tr")
        if len(rows) < 2:
            continue
        header_full = " ".join(get_cell_text(c) for c in rows[0].findall(f"{{{W}}}tc"))
        if "用户要求" not in header_full:
            continue

        for ri, row in enumerate(rows[1:], start=1):
            cells = row.findall(f"{{{W}}}tc")
            if not cells:
                continue
            name = get_cell_text(cells[0]).strip()
            if name in {"", "电性能", "机械性能", "环境性能", "项目", "序号"}:
                continue
            if not any(name in cn or cn in name for cn in catalog_names if len(cn) > 1):
                continue
            empty_cols = 0
            for ci, cell in enumerate(cells[1:], start=1):
                ct = get_cell_text(cell).strip()
                if not ct or _is_placeholder_text(ct):
                    empty_cols += 1
            if empty_cols >= 2:
                zones.append(
                    FillZone(
                        zone_type="TABLE_EMPTY_CELL",
                        location=f"表格{ti}行{ri}",
                        heading=name,
                        snippet="(catalog行未填完整)",
                        severity="HIGH",
                        suggested_action="catalog 指标行需填完整",
                        auto_fillable=False,
                        para_index=-1,
                    )
                )
    return zones


def detect_fill_zones(root, include_tables: bool = True) -> List[FillZone]:
    paras = list(root.findall(f".//{{{W}}}p"))
    zones: List[FillZone] = []
    zones.extend(detect_cover_zones(paras))
    zones.extend(detect_placeholder_zones(paras))
    zones.extend(detect_instruction_zones(paras))
    zones.extend(detect_empty_section_zones(paras, root=root))
    if include_tables:
        zones.extend(detect_table_empty_zones(root))

    seen = set()
    unique = []
    for z in zones:
        key = (z.zone_type, z.location, z.heading, z.snippet[:40])
        if key in seen:
            continue
        seen.add(key)
        unique.append(z)
    return unique


def scan_document_zones(docx_path: str) -> Dict[str, Any]:
    with zipfile.ZipFile(docx_path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    zones = detect_fill_zones(root)
    by_type: Dict[str, int] = {}
    for z in zones:
        by_type[z.zone_type] = by_type.get(z.zone_type, 0) + 1
    blockers = [z for z in zones if z.severity == "BLOCKER"]
    return {
        "zone_count": len(zones),
        "blocker_count": len(blockers),
        "by_type": by_type,
        "zones": [z.to_dict() for z in zones],
        "blockers": [z.to_dict() for z in blockers[:40]],
    }


def zones_to_gaps(zones: List[FillZone]) -> List[Dict[str, str]]:
    return [
        {
            "chapter": z.heading or z.location,
            "field": z.zone_type,
            "reason": z.suggested_action + (f"：{z.snippet[:60]}" if z.snippet else ""),
            "severity": z.severity,
            "field_class": "D",
            "source": "zone_detector",
            "location": z.location,
            "auto_fillable": "是" if z.auto_fillable else "否",
        }
        for z in zones
        if z.severity in ("BLOCKER", "HIGH", "MEDIUM")
    ]


ZONE_TYPE_LABELS = {
    "COVER_FIELD": "封面字段",
    "PLACEHOLDER": "占位符",
    "TEMPLATE_INSTRUCTION": "模板说明/红字",
    "EMPTY_SECTION": "空章节",
    "TABLE_EMPTY_CELL": "表格空格",
}


def merge_zone_scan_into_gap_csv(
    gap_csv_path: str,
    zone_scan: Dict[str, Any],
    blueprint_gaps: Optional[List[Dict]] = None,
) -> str:
    """将待填区域合并进缺口清单 CSV（蓝图缺口 + 文档扫描）。"""
    import csv

    rows: List[List[str]] = []
    header = ["来源", "章节", "字段/类型", "位置", "原因", "严重度", "字段类", "可自动填"]

    for g in blueprint_gaps or []:
        rows.append([
            "蓝图",
            g.get("chapter", ""),
            g.get("field", ""),
            "",
            g.get("reason", ""),
            g.get("severity", ""),
            g.get("field_class", ""),
            "",
        ])

    for z in zone_scan.get("zones", []):
        zt = z.get("zone_type", "")
        rows.append([
            "文档扫描",
            z.get("heading", "")[:40],
            ZONE_TYPE_LABELS.get(zt, zt),
            z.get("location", ""),
            z.get("suggested_action", "") + (
                f"：{z.get('snippet', '')[:50]}" if z.get("snippet") else ""
            ),
            z.get("severity", ""),
            "D" if zt in ("EMPTY_SECTION", "COVER_FIELD") else "E" if zt == "TEMPLATE_INSTRUCTION" else "",
            "是" if z.get("auto_fillable") else "否",
        ])

    out_path = gap_csv_path.replace("_缺口清单.csv", "_统一缺口清单.csv")
    if not out_path.endswith("_统一缺口清单.csv"):
        out_path = gap_csv_path.replace(".csv", "_统一.csv")

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return out_path
