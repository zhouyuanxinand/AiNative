"""
完整性交付门禁：全文未填完整 → 不予交付，移入「未通过审查」。
"""
import json
import hashlib
import os
import posixpath
import re
import shutil
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from lxml import etree

from .config import BASE_DIR, W
from .document_zone_detector import (
    contains_unresolved_xxx, is_table_sequence_ellipsis, scan_document_zones,
)
from .docx_io import MANUAL_FILL_MARKER, get_cell_text, get_para_text
from .failure_table_schema import has_independent_failure_cells, has_ordered_failure_fields, is_failure_table
from .indicator_identity import canonical_indicator_name
from .final_reviewer import (
    HALLUCINATION_PATTERNS,
    compare_to_ground_truth,
    validate_v3_user_column,
)
from .qa_gate import (
    load_template_baseline,
    manual_marker_counts,
    normalized_template_text,
    paragraph_template_key,
)
from .renderer.table_style_engine import THICK_BORDER_SIZE, THIN_BORDER_SIZE

REJECTED_DIR = os.path.join(BASE_DIR, "未通过审查")

# 出现即视为「未填完整」，不允许交付
INCOMPLETE_PATTERNS = [
    (r"……|\.\.\.", "省略号占位符"),
    (r"(?i)(?:\[\s*XXh\s*\]|（\s*XXh\s*）|\(\s*XXh\s*\)|\bXXh\b)", "未决值占位符"),
    (r"(?<![a-zA-Z])\bXX\b(?![a-zA-Z])", "XX占位符"),
    (r"\bxxx\b", "xxx占位符"),
    (r"\bXXXX\b", "XXXX占位符"),
    (r"20[Xx]{2}", "年份占位符"),
    (r"待设计人员填写|待设计填写|待人工确认|待人工复核|需设计员确认", "待填写标记"),
    (r"没有可写|适用时保留|（型号名称）|Q/21EJxxxx", "模板残留"),
    (r"共X[套万元]|共\s*X\s*", "数量/金额占位"),
]

REQUIRED_HEADINGS = [
    "来源和功能",
    "使用环境和部位",
    "产品组成",
    "适用的法律法规要求",
    "技术指标",
    "接口尺寸要求",
    "通用质量特性要求",
    "任务进度要求",
    "任务书编制依据",
]

MIN_IMAGES = 6
MIN_INDICATOR_ROWS = 10
MIN_INTERFACE_FILLS = 3


def _normalized_table_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _controlled_table_kind(header_texts: List[str]) -> str | None:
    """Recognize governed tables by header semantics, never chapter number."""

    normalized = [_normalized_table_text(value) for value in header_texts]
    if (
        "\u9879\u76ee" in normalized
        and "\u7528\u6237\u8981\u6c42\u6307\u6807" in normalized
        and any("\u62df\u91c7\u7528\u6307\u6807" in value for value in normalized)
    ):
        return "indicator"
    if (
        "\u5931\u6548\u90e8\u4f4d" in normalized
        and any(value.startswith("\u5931\u6548\u6a21\u5f0f") for value in normalized)
    ):
        return "failure"
    return None


def _cell_border_size(cell, side: str) -> int | None:
    border = cell.find(f"./{{{W}}}tcPr/{{{W}}}tcBorders/{{{W}}}{side}")
    if border is None:
        return None
    raw = border.get(f"{{{W}}}sz")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _table_border_size(table, side: str) -> int | None:
    border = table.find(f"./{{{W}}}tblPr/{{{W}}}tblBorders/{{{W}}}{side}")
    if border is None:
        return None
    raw = border.get(f"{{{W}}}sz")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _controlled_table_border_errors(table, table_kind: str) -> list[str]:
    """Return precise deviations from the shared 1.5pt/0.5pt contract."""

    errors: list[str] = []
    table_expected = {
        "top": THICK_BORDER_SIZE,
        "left": THICK_BORDER_SIZE,
        "bottom": THICK_BORDER_SIZE,
        "right": THICK_BORDER_SIZE,
        "insideH": THIN_BORDER_SIZE,
        "insideV": THIN_BORDER_SIZE,
    }
    for side, expected_size in table_expected.items():
        actual_size = _table_border_size(table, side)
        if actual_size != expected_size:
            errors.append(
                f"{table_kind}:table:{side} "
                f"expected={expected_size} actual={actual_size}"
            )
    rows = table.findall(f"{{{W}}}tr")
    last_row = len(rows) - 1
    for row_index, row in enumerate(rows):
        cells = row.findall(f"{{{W}}}tc")
        if not cells:
            continue
        for cell_index, cell in enumerate(cells):
            if row_index == 0:
                expected = {
                    "top": THICK_BORDER_SIZE,
                    "left": (
                        THICK_BORDER_SIZE if cell_index == 0 else THIN_BORDER_SIZE
                    ),
                    "bottom": THICK_BORDER_SIZE,
                    "right": (
                        THICK_BORDER_SIZE
                        if cell_index == len(cells) - 1
                        else THIN_BORDER_SIZE
                    ),
                }
                zone = "header"
            else:
                expected = {
                    "top": THIN_BORDER_SIZE,
                    "left": (
                        THICK_BORDER_SIZE if cell_index == 0 else THIN_BORDER_SIZE
                    ),
                    "bottom": (
                        THICK_BORDER_SIZE
                        if row_index == last_row
                        else THIN_BORDER_SIZE
                    ),
                    "right": (
                        THICK_BORDER_SIZE
                        if cell_index == len(cells) - 1
                        else THIN_BORDER_SIZE
                    ),
                }
                zone = "body"
            for side, expected_size in expected.items():
                actual_size = _cell_border_size(cell, side)
                if actual_size != expected_size:
                    errors.append(
                        f"{table_kind}:{zone}:row={row_index}:cell={cell_index}:"
                        f"{side} expected={expected_size} actual={actual_size}"
                    )
    return errors


def _manual_review_gate_findings(
    scan: Dict[str, Any], indicator_audit: Dict[str, Any]
) -> tuple[list[Dict[str, str]], list[str], bool]:
    """Reconcile typed manual-review decisions with visible Word markers."""

    expected_names = [
        canonical_indicator_name(item.get("indicator_name", ""))
        for item in indicator_audit.get("manual_review_required", [])
        if isinstance(item, dict) and item.get("indicator_name")
    ]
    actual_names = [
        canonical_indicator_name(value)
        for value in scan.get("manual_indicator_names", [])
        if canonical_indicator_name(value)
    ]
    expected = Counter(expected_names)
    actual = Counter(actual_names)
    missing = list((expected - actual).elements())
    unexpected = list((actual - expected).elements())
    defects: list[Dict[str, str]] = []
    warnings: list[str] = []

    invalid_count = int(scan.get("invalid_manual_marker_count", 0) or 0)
    if invalid_count:
        defects.append({
            "code": "INVALID_MANUAL_FILL_MARKER_STYLE",
            "severity": "BLOCKER",
            "location": "manual-fill marker",
            "label": "Manual-fill marker must be exact red controlled text",
            "text": json.dumps(
                scan.get("invalid_manual_marker_locations", []),
                ensure_ascii=False,
            ),
        })
    if missing:
        defects.append({
            "code": "MISSING_MANUAL_FILL_MARKER",
            "severity": "BLOCKER",
            "location": "indicator table",
            "label": "Manual-review indicator is missing the visible marker",
            "text": json.dumps(missing, ensure_ascii=False),
        })
    if unexpected:
        defects.append({
            "code": "UNEXPECTED_MANUAL_FILL_MARKER",
            "severity": "BLOCKER",
            "location": "indicator table",
            "label": "Marker exists without a typed manual-review decision",
            "text": json.dumps(unexpected, ensure_ascii=False),
        })

    input_names = set(indicator_audit.get("input_canonical_names", []) or [])
    output_names = set(indicator_audit.get("output_canonical_names", []) or [])
    manual_only = bool(expected_names) and (
        not indicator_audit.get("unbacked_output_names", [])
        and int(indicator_audit.get("unmapped_review_required_count", 0) or 0) == 0
        and input_names.issubset(output_names)
    )
    if manual_only and not defects:
        warnings.append(
            f"{len(expected_names)} indicator(s) require human input and are visibly marked."
        )
    return defects, warnings, manual_only


def _semantic_location(report: Dict[str, Any], metric: str, default: str) -> str:
    """Return a human-readable semantic location, never a fixed chapter number."""
    labels = report.get("semantic_labels") or {}
    value = labels.get(metric)
    if value:
        return str(value)
    detail = report.get(f"{metric}_detail") or {}
    for key in ("target_heading", "target_label", "heading", "semantic_path", "location"):
        value = detail.get(key)
        if value:
            return str(value)
    return default


def _metric_count(report: Dict[str, Any], semantic_key: str, *legacy_keys: str) -> int:
    """Read a semantic metric, accepting old report aliases during migration."""
    for key in (semantic_key, *legacy_keys):
        value = report.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


def _delivery_threshold(report: Dict[str, Any], key: str, default: int) -> int:
    """Read a product/profile delivery policy, with a safe legacy default."""
    policy = report.get("delivery_gate") or {}
    if not isinstance(policy, dict):
        policy = {}
    if not policy:
        meta = report.get("meta") or {}
        if isinstance(meta, dict):
            policy = meta.get("delivery_gate") or meta.get("delivery_policy") or {}
    try:
        return max(0, int(policy.get(key, default)))
    except (TypeError, ValueError):
        return default


def _explicitly_absent_variant_groups(audit: dict[str, Any], docx_path: str) -> bool:
    """An empty group list requires a live controlled absence policy and DOCX proof."""
    if audit.get("groups") != [] or audit.get("no_mutually_exclusive_sections") is not True:
        return False
    from docx import Document
    from .template_variant_policy import ROOT, budget_headings, load_template_variant_policy

    policy_path = Path(str(audit.get("policy_path", ""))).resolve()
    if policy_path.parent != (ROOT / "config").resolve():
        return False
    try:
        policy = load_template_variant_policy(policy_path)
        return bool(
            policy.get("no_mutually_exclusive_sections") is True
            and policy.get("mutually_exclusive_groups") == []
            and audit.get("policy_sha256") == hashlib.sha256(policy_path.read_bytes()).hexdigest()
            and not budget_headings(Document(docx_path))
        )
    except (OSError, ValueError, TypeError):
        return False


def _section_evidence_findings(docx_path: str) -> list[dict[str, str]]:
    """Chapter templates need exact target evidence and complete source coverage."""
    defects: list[dict[str, str]] = []

    def reject(code: str, message: str, detail: str = "") -> None:
        defects.append({"code": code, "severity": "BLOCKER", "location": "技术要求章节审计",
                        "label": message, "text": detail[:500]})

    semantic_path = Path(docx_path).with_suffix(".semantic_integrity_gate.json")
    coverage_path = Path(docx_path).with_suffix(".coverage_ledger.json")
    try:
        semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
        if not isinstance(semantic, dict):
            raise ValueError("语义审计不是对象")
        checks = semantic.get("checked")
        expected = semantic.get("expected_source_ids")
        valid = (
            semantic.get("passed") is True
            and semantic.get("violations") == []
            and semantic.get("require_complete_source_checks") is True
            and semantic.get("output_sha256") == hashlib.sha256(Path(docx_path).read_bytes()).hexdigest()
            and bool((semantic.get("policy") or {}).get("exact_categories"))
            and isinstance(checks, list) and isinstance(expected, list)
            and all(isinstance(check, dict) and check.get("target_matches_category") is True
                    and check.get("exact_evidence_in_target") is True for check in checks)
        )
        if valid:
            checked_ids = {check.get("source_id") for check in checks}
            valid = set(expected).issubset(checked_ids)
        if not valid:
            reject("SEMANTIC_INTEGRITY_AUDIT", "技术要求未完成逐项原文落章核验，或审计与当前Word不一致")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        semantic = {}
        reject("SEMANTIC_INTEGRITY_AUDIT", "缺少或无法读取技术要求章节审计", str(exc))

    try:
        coverage_bytes = coverage_path.read_bytes()
        coverage = json.loads(coverage_bytes)
        blocks = coverage.get("blocks") if isinstance(coverage, dict) else None
        if not isinstance(blocks, list) or any(
            not isinstance(block, dict) or block.get("covered") is not True for block in blocks
        ):
            reject("SOURCE_COVERAGE_AUDIT", "存在未传递的来源内容，或覆盖账本不完整")
        if semantic.get("coverage_ledger_sha256") != hashlib.sha256(coverage_bytes).hexdigest():
            reject("SOURCE_COVERAGE_AUDIT", "覆盖账本与本次语义落章审计不一致")
    except (OSError, ValueError, TypeError) as exc:
        reject("SOURCE_COVERAGE_AUDIT", "缺少或无法读取来源覆盖账本", str(exc))
    return defects


def _scan_text_defects(text: str, location: str) -> List[Dict[str, str]]:
    defects = []
    if not text or not text.strip():
        return defects
    # 图题、规范号中的 x 不算占位
    if re.match(r"^图\s*\d+", text.strip()):
        return defects
    for pat, label in INCOMPLETE_PATTERNS:
        if re.search(pat, text, re.I):
            if label == "xxx占位符" and not contains_unresolved_xxx(text):
                continue
            defects.append({
                "code": "INCOMPLETE",
                "severity": "BLOCKER",
                "location": location,
                "label": label,
                "text": text[:120],
            })
            break
    for pat, msg in HALLUCINATION_PATTERNS:
        if re.search(pat, text, re.I):
            defects.append({
                "code": "HALLUCINATION",
                "severity": "BLOCKER",
                "location": location,
                "label": msg,
                "text": text[:120],
            })
    return defects


def _referenced_package_parts(package: zipfile.ZipFile) -> set[str]:
    """Resolve every internal OOXML relationship target in the package.

    Images may legally belong to the main document, a header, a footer,
    footnotes, comments, or another Word part.  Looking only at
    ``document.xml.rels`` incorrectly labels header/footer images as orphaned.
    """
    referenced: set[str] = set()
    rel_namespace = {
        "r": "http://schemas.openxmlformats.org/package/2006/relationships"
    }
    for rel_name in (name for name in package.namelist() if name.endswith(".rels")):
        try:
            rel_root = etree.fromstring(package.read(rel_name))
        except (KeyError, etree.XMLSyntaxError):
            continue
        if "/_rels/" in rel_name:
            prefix, leaf = rel_name.rsplit("/_rels/", 1)
            owner_part = posixpath.join(prefix, leaf[:-5])
        elif rel_name.startswith("_rels/"):
            owner_part = rel_name[len("_rels/"):-5]
        else:
            continue
        owner_dir = posixpath.dirname(owner_part)
        for relationship in rel_root.xpath(
            "//r:Relationship", namespaces=rel_namespace
        ):
            if relationship.get("TargetMode") == "External":
                continue
            target = str(relationship.get("Target") or "").strip()
            if not target:
                continue
            referenced.add(
                posixpath.normpath(
                    posixpath.join(owner_dir, target)
                ).lstrip("/")
            )
    return referenced


def scan_document_completeness(
    docx_path: str,
    required_headings: List[str] | None = None,
    *,
    preserve_template_guidance: bool = False,
    template_path: str | None = None,
    min_images: int = 0,
) -> Dict[str, Any]:
    """扫描 docx 全文（段落+表格）是否仍有未完成内容。"""
    privacy_findings: list[str] = []
    with zipfile.ZipFile(docx_path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
        package_names = set(z.namelist())
        referenced_parts = _referenced_package_parts(z)
        if "docProps/core.xml" in package_names:
            try:
                core = etree.fromstring(z.read("docProps/core.xml"))
                core_ns = {
                    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
                    "dc": "http://purl.org/dc/elements/1.1/",
                }
                for label, xpath in (
                    ("creator", "//dc:creator"),
                    ("lastModifiedBy", "//cp:lastModifiedBy"),
                    ("lastPrinted", "//cp:lastPrinted"),
                ):
                    if any((node.text or "").strip() for node in core.xpath(xpath, namespaces=core_ns)):
                        privacy_findings.append(f"docProps/core.xml:{label}")
            except etree.XMLSyntaxError:
                privacy_findings.append("docProps/core.xml:invalid")
        for part_name in sorted(
            name for name in package_names
            if name.startswith("word/") and name.endswith(".xml")
        ):
            try:
                part_root = etree.fromstring(z.read(part_name))
            except etree.XMLSyntaxError:
                continue
            if any(
                isinstance(node.tag, str)
                and any(
                    etree.QName(attr_name).localname.lower().startswith("rsid")
                    for attr_name in node.attrib
                )
                for node in part_root.iter()
            ):
                privacy_findings.append(f"{part_name}:rsid")
                break

    defects: List[Dict[str, str]] = []
    full_text_parts: List[str] = []
    controlled_table_count = 0
    controlled_table_border_results: list[Dict[str, Any]] = []
    manual_marker_count = 0
    manual_indicator_names: list[str] = []
    manual_marker_locations: list[str] = []
    invalid_manual_marker_locations: list[str] = []
    template_root = load_template_baseline(template_path) if preserve_template_guidance else None
    template_paragraphs = Counter()
    template_cells = Counter()
    if template_root is not None:
        template_paragraphs.update(
            paragraph_template_key(p)
            for p in template_root.findall(f".//{{{W}}}p")
            if not any(parent.tag == f"{{{W}}}tc" for parent in p.iterancestors())
        )
        template_cells.update(normalized_template_text(get_cell_text(cell)) for cell in template_root.findall(f".//{{{W}}}tc"))
    elif preserve_template_guidance:
        defects.append({"code": "MISSING_TEMPLATE_BASELINE", "severity": "BLOCKER", "location": "受控模板",
                        "label": "模板基线缺失或不可读，无法验证原有保留内容", "text": str(template_path or "")})

    for i, p in enumerate(root.findall(f".//{{{W}}}p")):
        if any(parent.tag == f"{{{W}}}tc" for parent in p.iterancestors()):
            continue
        t = get_para_text(p)
        full_text_parts.append(t)
        occurrences, invalid = manual_marker_counts(p)
        location = f"paragraph#{i}"
        manual_marker_count += occurrences
        manual_marker_locations.extend([location] * occurrences)
        invalid_manual_marker_locations.extend([location] * invalid)
        key = paragraph_template_key(p)
        preserved = template_paragraphs[key] > 0
        if preserved:
            template_paragraphs[key] -= 1
        if not preserved:
            defects.extend(_scan_text_defects(t, f"段落#{i}"))

    for ti, table in enumerate(root.findall(f".//{{{W}}}tbl")):
        rows = table.findall(f"{{{W}}}tr")
        table_kind = None
        if rows:
            header_cells = rows[0].findall(f"{{{W}}}tc")
            header_texts = [get_cell_text(cell).strip() for cell in header_cells]
            table_kind = _controlled_table_kind(header_texts)
            if table_kind:
                controlled_table_count += 1
                border_errors = _controlled_table_border_errors(table, table_kind)
                controlled_table_border_results.append({
                    "table_index": ti,
                    "table_kind": table_kind,
                    "passed": not border_errors,
                    "errors": border_errors,
                })
                if border_errors:
                    defects.append({
                        "code": "INVALID_CONTROLLED_TABLE_BORDER",
                        "severity": "BLOCKER",
                        "location": f"table#{ti}",
                        "label": "Controlled table border contract is not satisfied",
                        "text": "; ".join(border_errors[:20]),
                    })
            if is_failure_table(header_texts):
                independent_cells = has_independent_failure_cells(table)
                if not has_ordered_failure_fields(header_texts) or not independent_cells:
                    defects.append({
                        "code": "FAILURE_TABLE_SCHEMA",
                        "severity": "BLOCKER",
                        "location": f"表格{ti}",
                        "label": "失效模式表须依次包含产品名称或型号、失效部位、故障现象、失效分析及改进措施五个独立字段",
                        "text": " | ".join(header_texts),
                    })
        for ri, row in enumerate(table.findall(f"{{{W}}}tr")):
            for ci, cell in enumerate(row.findall(f"{{{W}}}tc")):
                t = get_cell_text(cell)
                full_text_parts.append(t)
                marker_occurrences, invalid_markers = manual_marker_counts(cell)
                if marker_occurrences:
                    location = f"table#{ti}:row={ri}:cell={ci}"
                    manual_marker_count += marker_occurrences
                    manual_marker_locations.extend(
                        [location] * marker_occurrences
                    )
                    invalid_manual_marker_locations.extend([location] * invalid_markers)
                    if table_kind == "indicator" and ri > 0:
                        item_cells = row.findall(f"{{{W}}}tc")
                        item_name = (
                            get_cell_text(item_cells[0]).strip()
                            if item_cells
                            else ""
                        )
                        manual_indicator_names.extend(
                            [item_name] * marker_occurrences
                        )
                key = normalized_template_text(t)
                preserved = template_cells[key] > 0
                if preserved:
                    template_cells[key] -= 1
                if not preserved and not is_table_sequence_ellipsis(cell):
                    defects.extend(_scan_text_defects(t, f"表格{ti}行{ri}列{ci}"))
                # 7-22 受控规则允许故障库无精确产品/系列记录时，在五列表格
                # 第一列写入唯一标识。其合法性由 failure_mode_audit 与矩阵门禁
                # 共同验证，这里不再把该受控状态误判为模板污染。

    for location in dict.fromkeys(invalid_manual_marker_locations):
        defects.append({"code": "INVALID_MANUAL_MARKER", "severity": "BLOCKER", "location": location,
                        "label": "【人工填写】必须使用完整的红色受控标记", "text": MANUAL_FILL_MARKER})

    # DOCX 包内存在未被正文关系引用的媒体，通常说明删节后遗留了
    # 图片二进制。它会扩大文件并破坏“可见内容即审计内容”的证据边界。
    all_media = {
        name for name in package_names
        if name.startswith("word/media/") and not name.endswith("/")
    }
    for media_path in sorted(all_media - referenced_parts):
        defects.append({
            "code": "UNREFERENCED_MEDIA",
            "severity": "BLOCKER",
            "location": "DOCX媒体包",
            "label": "存在正文未引用的孤立媒体",
            "text": media_path,
        })
    for finding in privacy_findings:
        defects.append({
            "code": "PRIVACY_METADATA",
            "severity": "BLOCKER",
            "location": "DOCX元数据",
            "label": "正式件仍含作者、打印人或编辑指纹",
            "text": finding,
        })

    full_text = "\n".join(full_text_parts)
    headings = required_headings if required_headings is not None else REQUIRED_HEADINGS
    missing_headings = [h for h in headings if h and h not in full_text]
    for h in missing_headings:
        defects.append({
            "code": "MISSING_SECTION",
            "severity": "BLOCKER",
            "location": "章节结构",
            "label": f"缺少必要章节：{h}",
            "text": h,
        })

    images = len(root.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"))
    if images < min_images:
        defects.append({
            "code": "INSUFFICIENT_IMAGES",
            "severity": "BLOCKER",
            "location": "图片",
            "label": f"图片不足：需要≥{min_images}，当前{images}",
            "text": str(images),
        })

    # 去重（同位置同类型）
    seen = set()
    unique = []
    for d in defects:
        key = (d.get("code"), d.get("location"), d.get("label"))
        if key not in seen:
            seen.add(key)
            unique.append(d)

    return {
        "defects": unique,
        "defect_count": len(unique),
        "images": images,
        "missing_headings": missing_headings,
        "controlled_table_count": controlled_table_count,
        "controlled_table_border_results": controlled_table_border_results,
        "manual_marker_count": manual_marker_count,
        "manual_indicator_names": manual_indicator_names,
        "manual_marker_locations": manual_marker_locations,
        "invalid_manual_marker_count": len(invalid_manual_marker_locations),
        "invalid_manual_marker_locations": invalid_manual_marker_locations,
    }


def run_delivery_gate(
    docx_path: str,
    pipeline_report: Dict[str, Any],
    identity_result: Dict[str, Any],
    gt_json_path: str = "",
    benchmark_result: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """运行交付门禁；passed=True 才允许给用户。"""
    policy = pipeline_report.get("delivery_gate") or {}
    if not isinstance(policy, dict):
        policy = {}
    if not policy:
        meta = pipeline_report.get("meta") or {}
        if isinstance(meta, dict):
            policy = meta.get("delivery_gate") or meta.get("delivery_policy") or {}
    required_headings = policy.get("required_headings")
    if not isinstance(required_headings, list):
        required_headings = None
    excluded_required_headings = {
        str(value).strip()
        for value in policy.get("excluded_required_headings", [])
        if str(value).strip()
    }
    if required_headings is not None and excluded_required_headings:
        required_headings = [
            heading
            for heading in required_headings
            if str(heading).strip() not in excluded_required_headings
        ]
    meta = pipeline_report.get("meta") or {}
    preserve_template_guidance = bool(
        policy.get("preserve_template_guidance")
        or (
            isinstance(meta, dict)
            and meta.get("preserve_unfilled_template")
        )
    )
    template_path = (
        str(meta.get("template_path", ""))
        if isinstance(meta, dict)
        else ""
    )
    scan = scan_document_completeness(
        docx_path,
        required_headings,
        preserve_template_guidance=preserve_template_guidance,
        template_path=template_path,
        min_images=_delivery_threshold(pipeline_report, "min_images", 0),
    )
    defects = scan["defects"]
    warnings: list[str] = []
    section_mode = pipeline_report.get("technical_requirements_mode") == "sections"

    # 模板互斥分支必须由配置驱动的审计证明已正确裁剪。
    # 没有审计、审计损坏或审计未通过都不能交付；否则可能出现
    # “非中央研究院产品”和“中央研究院产品”两个预算分支同时保留，
    # 而内容覆盖率等旧门禁仍误判为通过。
    variant_audit_path = Path(docx_path).with_suffix(
        ".template_variant_audit.json"
    )
    try:
        variant_audit = json.loads(
            variant_audit_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        defects.append({
            "code": "TEMPLATE_VARIANT_POLICY",
            "severity": "BLOCKER",
            "location": "模板互斥分支",
            "label": "缺少或无法读取模板互斥分支审计",
            "text": f"{variant_audit_path}: {type(exc).__name__}",
        })
    else:
        groups = variant_audit.get("groups")
        group_passed = bool(
            isinstance(groups, list)
            and groups
            and all(
                isinstance(group, dict) and group.get("passed") is True
                for group in groups
            )
        )
        if not group_passed:
            group_passed = _explicitly_absent_variant_groups(variant_audit, docx_path)
        if variant_audit.get("passed") is not True or not group_passed:
            defects.append({
                "code": "TEMPLATE_VARIANT_POLICY",
                "severity": "BLOCKER",
                "location": "模板互斥分支",
                "label": "模板互斥分支审计未通过",
                "text": "；".join(
                    str(item)
                    for item in variant_audit.get("errors", [])
                )[:500],
            })

    # 技术指标和引用标准使用独立审计真源。正文中“看起来有值”不能证明
    # 该值经过受控目录、适用条件和版本冲突检查。
    if section_mode:
        defects.extend(_section_evidence_findings(docx_path))
    else:
        indicator_audit_path = Path(docx_path).with_suffix(".indicator_audit.json")
        try:
            indicator_audit = json.loads(
                indicator_audit_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            defects.append({
                "code": "INDICATOR_AUDIT",
                "severity": "BLOCKER",
                "location": "技术指标审计",
                "label": "缺少或无法读取技术指标审计",
                "text": f"{indicator_audit_path}: {type(exc).__name__}",
            })
        else:
            manual_defects, manual_warnings, manual_only = (
                _manual_review_gate_findings(scan, indicator_audit)
            )
            defects.extend(manual_defects)
            warnings.extend(manual_warnings)
            if indicator_audit.get("passed") is not True and not manual_only:
                defects.append({
                    "code": "INDICATOR_AUDIT",
                    "severity": "BLOCKER",
                    "location": "技术指标审计",
                    "label": "存在未受控指标、无原文证据或条件规范待人工复核",
                    "text": json.dumps({
                        "unbacked_output_names": indicator_audit.get("unbacked_output_names", []),
                        "unmapped_review_required_count": indicator_audit.get(
                            "unmapped_review_required_count", 0
                        ),
                        "manual_review_required_count": indicator_audit.get(
                            "manual_review_required_count", 0
                        ),
                    }, ensure_ascii=False),
                })

    standards_audit_path = Path(docx_path).with_suffix(".standards_audit.json")
    try:
        standards_audit = json.loads(
            standards_audit_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        defects.append({
            "code": "STANDARDS_AUDIT",
            "severity": "BLOCKER",
            "location": "引用标准审计",
            "label": "缺少或无法读取引用标准审计",
            "text": f"{standards_audit_path}: {type(exc).__name__}",
        })
    else:
        version_conflicts = standards_audit.get("version_conflicts", [])
        if version_conflicts:
            defects.append({
                "code": "STANDARD_VERSION_CONFLICT",
                "severity": "BLOCKER",
                "location": "引用标准审计",
                "label": "同一标准存在版本冲突，必须人工裁决",
                "text": json.dumps(version_conflicts[:10], ensure_ascii=False),
            })

    process_audit_path = Path(docx_path).with_suffix(".process_rule_audit.json")
    try:
        process_audit = json.loads(
            process_audit_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        defects.append({
            "code": "PROCESS_RULE_AUDIT",
            "severity": "BLOCKER",
            "location": "研制流程规则审计",
            "label": "缺少或无法读取研制流程/故障模式审计",
            "text": f"{process_audit_path}: {type(exc).__name__}",
        })
    failure_audit_path = Path(docx_path).with_suffix(".failure_mode_audit.json")
    try:
        failure_audit = json.loads(
            failure_audit_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        defects.append({
            "code": "FAILURE_MODE_AUDIT",
            "severity": "BLOCKER",
            "location": "故障模式库匹配",
            "label": "缺少或无法读取独立故障模式匹配审计",
            "text": f"{failure_audit_path}: {type(exc).__name__}",
        })
    else:
        query_executed = failure_audit.get("query_executed")
        match_audit = failure_audit.get("match")
        if query_executed:
            if not isinstance(match_audit, dict) or not isinstance(
                match_audit.get("candidates"), list
            ):
                defects.append({
                    "code": "FAILURE_MODE_AUDIT",
                    "severity": "BLOCKER",
                    "location": "故障模式库匹配",
                    "label": "故障模式库审计缺少候选及逐条接受/拒绝原因",
                    "text": json.dumps(match_audit, ensure_ascii=False)[:500],
                })
            elif match_audit.get("status") == "NO_APPLICABLE_RECORD":
                family_count = int(match_audit.get("product_family_candidate_count", 0) or 0)
                if family_count:
                    warnings.append(
                        f"故障模式库存在 {family_count} 条当前产品族记录，但没有与受控系列 "
                        f"“{match_audit.get('selected_product_series', '')}”匹配的记录；"
                        "已按7-22写入无历史记录标识，不得跨系列搬运；请补充对应系列记录或人工确认。"
                    )
                else:
                    warnings.append(
                        "故障模式库未找到当前受控产品/系列的适用记录；已按7-22写入"
                        "无历史记录标识，不代表匹配成功，请补充数据库或人工确认。"
                    )
        elif failure_audit.get("development_process") not in {"改型II", "改型III"}:
            defects.append({
                "code": "FAILURE_MODE_QUERY_NOT_EXECUTED",
                "severity": "BLOCKER",
                "location": "故障模式库匹配",
                "label": "当前研制流程要求查询故障模式库，但审计显示未执行",
                "text": json.dumps(failure_audit, ensure_ascii=False)[:500],
            })

    # 流水线统计门禁
    min_indicator_rows = _delivery_threshold(
        pipeline_report, "min_indicator_rows", MIN_INDICATOR_ROWS
    )
    min_interface_fills = _delivery_threshold(
        pipeline_report, "min_interface_fills", MIN_INTERFACE_FILLS
    )
    indicator_count = _metric_count(pipeline_report, "indicator_table")
    interface_count = _metric_count(
        pipeline_report, "interface_definition", "interface_fill_count", "interface_42"
    )
    if not section_mode and indicator_count < min_indicator_rows:
        defects.append({
            "code": "INSUFFICIENT_INDICATORS",
            "severity": "BLOCKER",
            "location": _semantic_location(pipeline_report, "indicator_table", "技术指标表"),
            "label": f"技术指标表填充不足：需要≥{min_indicator_rows}",
            "text": str(indicator_count),
        })
    if interface_count < min_interface_fills:
        defects.append({
            "code": "INSUFFICIENT_INTERFACE",
            "severity": "BLOCKER",
            "location": _semantic_location(pipeline_report, "interface_definition", "接口尺寸要求"),
            "label": f"接口尺寸要求填充不足：需要≥{min_interface_fills}",
            "text": str(interface_count),
        })

    ph = pipeline_report.get("placeholders", {})
    if ph.get("ellipsis", 0) > 0 or ph.get("xx", 0) > 0 or ph.get("date_xx", 0) > 0:
        defects.append({
            "code": "PIPELINE_PLACEHOLDER",
            "severity": "BLOCKER",
            "location": "占位符统计",
            "label": (
                f"仍有占位符 ……={ph.get('ellipsis')} XX={ph.get('xx')} "
                f"20xx={ph.get('date_xx', 0)}"
            ),
            "text": str(ph),
        })

    for b in identity_result.get("blockers", []):
        defects.append({
            "code": b.get("code", "IDENTITY"),
            "severity": "BLOCKER",
            "location": "身份门禁",
            "label": b.get("message", ""),
            "text": "",
        })

    # V3 is a legacy, customer-case-specific oracle.  It is used only when an
    # explicit ground-truth artifact is supplied; the generic 7-22 pipeline is
    # governed by indicator_audit + coverage_ledger instead.
    if gt_json_path:
        for item in validate_v3_user_column(docx_path, gt_json_path):
            defects.append({
                "code": "V3_USER_COLUMN",
                "severity": "BLOCKER",
                "location": item.get("field", ""),
                "label": item.get("message", ""),
                "text": "",
            })

    for item in compare_to_ground_truth(docx_path, gt_json_path):
        defects.append({
            "code": "GROUND_TRUTH",
            "severity": "BLOCKER",
            "location": item.get("field", ""),
            "label": item.get("conflict", ""),
            "text": "",
        })

    # 新增：标杆对比阈值检查
    if benchmark_result:
        threshold_check = benchmark_result.get("threshold_check", {})
        if threshold_check and not threshold_check.get("passed", True):
            for blocker in threshold_check.get("blockers", []):
                defects.append({
                    "code": blocker.get("code", "BENCHMARK_THRESHOLD"),
                    "severity": "BLOCKER",
                    "location": "标杆对比",
                    "label": blocker.get("message", ""),
                    "text": str(blocker.get("value", "")),
                })

    # 待填区域扫描（封面/空章节/模板说明）
    zone_scan = pipeline_report.get("zone_scan") or scan_document_zones(docx_path)

    def _zone_key(zone: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(zone.get("zone_type", "")),
            re.sub(r"\s+", "", normalized_template_text(zone.get("heading", ""))),
            re.sub(r"\s+", "", normalized_template_text(zone.get("snippet", ""))),
            str(zone.get("field_key", "")),
        )

    baseline_zones = Counter()
    if preserve_template_guidance and template_path and load_template_baseline(template_path) is not None:
        baseline_scan = scan_document_zones(template_path)
        baseline_zones.update(_zone_key(zone) for zone in baseline_scan.get("zones", []))
    zone_decisions = {}

    def _is_preserved_template_zone(zone: dict[str, Any]) -> bool:
        if not preserve_template_guidance:
            return False
        key = _zone_key(zone)
        identity = (str(zone.get("location", "")), key)
        if identity not in zone_decisions:
            preserved = baseline_zones[key] > 0
            zone_decisions[identity] = preserved
            if preserved:
                baseline_zones[key] -= 1
        return zone_decisions[identity]

    for z in zone_scan.get("blockers", []):
        if _is_preserved_template_zone(z):
            continue
        defects.append({
            "code": "FILL_ZONE",
            "severity": "BLOCKER",
            "location": z.get("location", ""),
            "label": f"{z.get('zone_type', '')}: {z.get('heading') or z.get('snippet', '')[:60]}",
            "text": z.get("suggested_action", ""),
        })
    high_zones = [
        z for z in zone_scan.get("zones", [])
        if z.get("severity") == "HIGH" and z.get("zone_type") in ("EMPTY_SECTION", "TEMPLATE_INSTRUCTION")
        and not _is_preserved_template_zone(z)
    ]
    for z in high_zones[:15]:
        defects.append({
            "code": "FILL_ZONE_HIGH",
            "severity": "HIGH",
            "location": z.get("location", ""),
            "label": f"{z.get('zone_type')}: {z.get('heading', '')[:40]}",
            "text": z.get("suggested_action", ""),
        })

    blockers = [d for d in defects if d.get("severity") == "BLOCKER"]
    passed = len(blockers) == 0

    return {
        "passed": passed,
        "approved_for_delivery": passed,
        "defect_count": len(defects),
        "blocker_count": len(blockers),
        "defects": defects[:50],
        "blockers": blockers[:30],
        "warnings": warnings[:30],
        "scan": scan,
        "zone_scan": zone_scan,
        "checked_at": datetime.now().isoformat(),
        "docx_path": docx_path,
        "benchmark_threshold_enabled": benchmark_result is not None,
    }


def _related_artifacts(docx_path: str) -> List[str]:
    base = docx_path.replace(".docx", "")
    paths = [docx_path]
    for suffix in (
        "_FillPlan.json",
        "_ProjectRequirementData.json",
        "_report.json",
        "_ReviewReport.json",
        "_ReviewReport.html",
        "_DeliveryGate.json",
        "_Blueprint.json",
        "_字段血缘.csv",
        "_缺口清单.csv",
        "_冲突清单.csv",
        "_待填区域.json",
        "_统一缺口清单.csv",
        "_BenchmarkCompare.json",
    ):
        p = base + suffix
        if os.path.exists(p):
            paths.append(p)
    return paths


def apply_delivery_policy(
    docx_path: str,
    gate_result: Dict[str, Any],
    review_report: Dict[str, Any],
) -> Dict[str, Any]:
    """
    通过 → 正式输出目录，文件名带「已验收」
    未通过 → 移入未通过审查，不留在正式输出
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    artifacts = _related_artifacts(docx_path)

    if gate_result["passed"]:
        approved_dir = os.path.dirname(docx_path)
        approved_name = f"研制任务书_已验收_{ts}.docx"
        approved_path = os.path.join(approved_dir, approved_name)
        os.rename(docx_path, approved_path)
        # 伴生文件同步改名
        old_base = docx_path.replace(".docx", "")
        new_base = approved_path.replace(".docx", "")
        for suffix in (
            "_FillPlan.json",
            "_ProjectRequirementData.json",
            "_report.json",
            "_ReviewReport.json",
            "_ReviewReport.html",
            "_Blueprint.json",
            "_字段血缘.csv",
            "_缺口清单.csv",
            "_冲突清单.csv",
            "_待填区域.json",
            "_统一缺口清单.csv",
            "_GroundTruth血缘表.xlsx",
        ):
            old_p = old_base + suffix
            if os.path.exists(old_p):
                os.rename(old_p, new_base + suffix)

        gate_path = new_base + "_DeliveryGate.json"
        with open(gate_path, "w", encoding="utf-8") as f:
            json.dump(gate_result, f, ensure_ascii=False, indent=2)

        return {
            "delivered": True,
            "docx_path": approved_path,
            "message": "全文完整性门禁通过，任务书已验收交付",
            "gate_path": gate_path,
        }

    # 未通过：移入未通过审查
    reject_dir = os.path.join(REJECTED_DIR, ts)
    os.makedirs(reject_dir, exist_ok=True)
    moved = []
    for p in artifacts:
        if not os.path.exists(p):
            continue
        dest = os.path.join(reject_dir, os.path.basename(p))
        shutil.move(p, dest)
        moved.append(dest)

    gate_path = os.path.join(reject_dir, "DeliveryGate.json")
    payload = {
        "gate": gate_result,
        "review_summary": review_report.get("summary", {}),
        "message": "全文未填完整，任务书不予交付",
        "moved_files": moved,
    }
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return {
        "delivered": False,
        "docx_path": None,
        "reject_dir": reject_dir,
        "gate_path": gate_path,
        "message": "全文未填完整，任务书不予交付（已移入未通过审查）",
        "blockers": gate_result.get("blockers", [])[:10],
    }


def append_manual_review_to_fillplan(docx_path: str, gate_result: Dict[str, Any]) -> None:
    """将门禁缺陷写入 FillPlan 的 manual_review_items。"""
    fill_plan_path = docx_path.replace(".docx", "_FillPlan.json")
    if not os.path.exists(fill_plan_path):
        return
    with open(fill_plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)
    if not isinstance(plan, list):
        return
    items = []
    for d in gate_result.get("blockers", []):
        items.append({
            "item_name": d.get("location", ""),
            "reason": d.get("label", ""),
            "code": d.get("code", ""),
            "severity": "BLOCKER",
        })
    if items:
        plan.append({"type": "delivery_gate_failures", "items": items})
        with open(fill_plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
