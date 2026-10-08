"""Evidence-led value gate between the indicator ledger and final DOCX.

The semantic classifier decides *where* an indicator belongs.  This gate does
not classify or invent content; it verifies that the final template-governed
table still contains the controlled values recorded by ``indicator_audit``.
It is deliberately product-neutral and chapter-number-neutral.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from docx import Document
from docx.table import Table

from jonhon_taskbook.indicator_identity import canonical_indicator_name
from jonhon_taskbook.source_scope import review_reference_source_ids


AUDIT_FIELDS = (
    "user_requirement",
    "standard_requirement",
    "adopted_requirement",
    "basis",
)

_FORMAL_SPEC_HEADING = re.compile(r"技术(?:规格|指标|参数|特性|要求)|性能(?:指标|参数)|主要技术要求")
_FORMAL_LABEL_HEADERS = {"技术特性类型", "技术特性", "指标名称", "指标项目", "参数名称", "项目"}
_FORMAL_VALUE_HEADERS = {"特性描述", "指标值", "参数值", "技术要求", "性能要求", "指标内容"}


def _comparison_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", normalized)


def _field_evidence(value: Any, field: str) -> tuple[str, int]:
    text = _comparison_text(value)
    marker = "【人工填写】"
    # Postprocessing places this controlled annotation at the end of the
    # cell. Preserve its count and every substantive character; moving the
    # annotation must not look like a changed numerical requirement.
    if field == "adopted_requirement":
        return text.replace(marker, ""), text.count(marker)
    return text, 0


def _indicator_name(value: Any) -> str:
    return canonical_indicator_name(str(value or "")).casefold()


def _indicator_header_columns(cells: list[str]) -> dict[str, int]:
    """Map audit fields from the actual four- or five-column header."""

    if len(cells) not in {4, 5}:
        return {}
    normalized = [_comparison_text(value) for value in cells]
    columns: dict[str, int] = {}
    for index, value in enumerate(normalized):
        if "项目" in value and "indicator_name" not in columns:
            columns["indicator_name"] = index
        if "用户要求" in value and "user_requirement" not in columns:
            columns["user_requirement"] = index
        if (
            ("标准要求" in value or "规范要求" in value)
            and "standard_requirement" not in columns
        ):
            columns["standard_requirement"] = index
        if (
            "拟采用" in value
            and "依据" not in value
            and "adopted_requirement" not in columns
        ):
            columns["adopted_requirement"] = index
        if "依据" in value and "basis" not in columns:
            columns["basis"] = index
    required = {
        "indicator_name",
        "user_requirement",
        "adopted_requirement",
        "basis",
    }
    if len(cells) == 5:
        required.add("standard_requirement")
    return columns if required.issubset(columns) else {}


def _read_output_rows(path: Path) -> dict[str, list[dict[str, str]]]:
    rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    document = Document(path)
    for table in document.tables:
        matrix = [
            [str(cell.text or "").strip() for cell in row.cells]
            for row in table.rows
        ]
        if not matrix:
            continue
        columns = _indicator_header_columns(matrix[0])
        if not columns:
            continue
        required_width = max(columns.values()) + 1
        for row in matrix[1:]:
            if len(row) < required_width or not any(value.strip() for value in row):
                continue
            name = _indicator_name(row[columns["indicator_name"]])
            if name:
                rows[name].append({
                    field: row[column]
                    for field, column in columns.items()
                    if field != "indicator_name" and column < len(row)
                })
    return dict(rows)


def _source_table_row_checks(path: Path, ledger: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Check formal two-column source specifications independently of extracted facts.

    A copied source table cannot prove its individual values reached the governed
    indicator table. Historical test results and other source roles are outside
    this check; they remain review material.
    """
    classification_path = path.with_suffix(".effective_requirement_classification.json")
    if not classification_path.is_file():
        classification_path = path.with_suffix(".requirement_classification.json")
    if not classification_path.is_file():
        return [], []
    try:
        classification = json.loads(classification_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [], []  # The separate source-classification gate reports this.
    if not isinstance(classification, dict):
        return [], []

    categories: dict[str, set[str]] = defaultdict(set)
    for item in classification.get("classifications", []) or []:
        if isinstance(item, dict) and item.get("source_id"):
            categories[str(item["source_id"])].add(str(item.get("category") or ""))
    review_only = review_reference_source_ids(classification)
    source_docs: dict[Path, Any] = {}
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    facts = [item for item in ledger.get("input_indicator_facts", []) if isinstance(item, dict)]

    for block in classification.get("source_blocks", []) or []:
        if not isinstance(block, dict):
            continue
        source_id = str(block.get("id") or "")
        if (block.get("source") != "tech" or block.get("type") != "table"
                or not source_id or source_id in review_only
                or categories.get(source_id) != {"performance_indicator"}):
            continue
        headings = " ".join(str(value or "") for value in (
            *(block.get("parent_headings") or []), block.get("heading_text"), block.get("section")
        ))
        if not _FORMAL_SPEC_HEADING.search(headings):
            continue
        source_name = str(block.get("source_path") or "")
        body_index = block.get("body_index")
        if not source_name or type(body_index) is not int or body_index < 0:
            continue
        source_path = Path(source_name)
        if not source_path.is_absolute():
            source_path = classification_path.parent / source_path
        try:
            if source_path not in source_docs:
                source_docs[source_path] = Document(source_path)
            document = source_docs[source_path]
            element = list(document.element.body.iterchildren())[body_index]
            if not element.tag.endswith("}tbl"):
                raise ValueError("source block no longer points to a table")
            table = Table(element, document)
            if not table.rows:
                continue
            header = [_comparison_text(cell.text) for cell in table.rows[0].cells]
            if (len(header) != 2 or header[0] not in _FORMAL_LABEL_HEADERS
                    or header[1] not in _FORMAL_VALUE_HEADERS):
                continue
            for row_index, row in enumerate(table.rows[1:], start=1):
                label, value = (cell.text.strip() for cell in row.cells)
                if not label or not value:
                    continue
                matched = any(
                    source_id in (fact.get("source_ids") or [])
                    and _comparison_text(fact.get("source_label")) == _comparison_text(label)
                    and _comparison_text(fact.get("source_value")) == _comparison_text(value)
                    and (not isinstance(fact.get("source_coordinates"), dict)
                         or fact["source_coordinates"].get("table_row", row_index) == row_index)
                    for fact in facts
                )
                check = {
                    "source_id": source_id, "source_path": str(source_path),
                    "body_index": body_index, "table_row": row_index,
                    "indicator": label, "source_value": value, "passed": matched,
                }
                checks.append(check)
                if not matched:
                    blockers.append({
                        "code": "UNEXTRACTED_SOURCE_INDICATOR_ROW",
                        "field": "input_indicator_facts", "source_id": source_id,
                        "source_path": str(source_path), "body_index": body_index,
                        "table_row": row_index, "indicator": label,
                        "message": f"正式技术规格表的指标未进入事实账本：{label}（第 {row_index + 1} 行）",
                    })
        except (OSError, ValueError, IndexError, KeyError) as exc:
            blockers.append({
                "code": "SOURCE_INDICATOR_TABLE_UNREADABLE",
                "field": "source_blocks", "source_id": source_id,
                "source_path": str(source_path), "body_index": body_index,
                "message": f"无法核对正式技术规格源表：{type(exc).__name__}",
            })
    return checks, blockers


def audit_indicator_values(
    docx_path: str | Path,
    indicator_audit_path: str | Path | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Verify ledger decisions against the final Word table.

    Presentation whitespace is ignored, but numbers, units, inequalities and
    all other characters remain significant.  Therefore ``0.15 N`` equals
    ``0.15N`` while ``0.15N`` does not equal ``0.31N``.
    """
    path = Path(docx_path).resolve()
    audit_path = (
        Path(indicator_audit_path).resolve()
        if indicator_audit_path
        else path.with_suffix(".indicator_audit.json")
    )
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    try:
        ledger = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        ledger = {}
        blockers.append({
            "code": "INDICATOR_LEDGER_UNREADABLE",
            "field": "indicator_audit",
            "message": f"无法读取技术指标审计账本: {type(exc).__name__}",
            "path": str(audit_path),
        })

    try:
        output_rows = _read_output_rows(path)
    except Exception as exc:  # malformed DOCX must become a gate result
        output_rows = {}
        blockers.append({
            "code": "INDICATOR_TABLE_UNREADABLE",
            "field": "docx",
            "message": f"无法读取最终Word技术指标表: {type(exc).__name__}",
            "path": str(path),
        })

    decisions = [
        item
        for item in ledger.get("comparison_decisions", [])
        if isinstance(item, dict) and _indicator_name(item.get("indicator_name"))
    ]
    source_table_checks, source_table_blockers = _source_table_row_checks(path, ledger)
    blockers.extend(source_table_blockers)
    if isinstance(ledger.get("input_indicator_facts"), list):
        from jonhon_taskbook.indicator_facts import audit_indicator_fact_coverage
        fact_check = audit_indicator_fact_coverage(ledger["input_indicator_facts"], decisions)
        for fact in fact_check["missing_facts"]:
            blockers.append({
                "code": "MISSING_SOURCE_INDICATOR", "indicator": fact["indicator_name"],
                "field": "user_fact_ids", "fact_id": fact["fact_id"],
                "message": f"来源指标事实未进入技术指标表：{fact['indicator_name']}",
            })
        for duplicate in fact_check["duplicate_consumption"]:
            blockers.append({
                "code": "DUPLICATE_INDICATOR_FACT", "field": "user_fact_ids", **duplicate,
                "message": "同一来源指标事实被重复写入指标行",
            })
        for mismatch in fact_check["wrong_indicator_identity"]:
            blockers.append({
                "code": "INDICATOR_FACT_IDENTITY_MISMATCH", "field": "user_fact_ids", **mismatch,
                "message": "来源指标事实被写入不同的指标名称",
            })
        if fact_check["unknown_fact_ids"]:
            blockers.append({
                "code": "UNKNOWN_INDICATOR_FACT", "field": "user_fact_ids",
                "message": "指标行引用了不存在的原始指标事实", "fact_ids": fact_check["unknown_fact_ids"],
            })
    for decision in decisions:
        display_name = str(decision.get("indicator_name", "")).strip()
        name = _indicator_name(display_name)
        candidates = output_rows.get(name, [])
        if not candidates:
            blockers.append({
                "code": "MISSING_INDICATOR_ROW",
                "indicator": display_name,
                "field": "indicator_name",
                "message": f"最终Word缺少指标行：{display_name}",
            })
            continue
        if len(candidates) != 1:
            blockers.append({
                "code": "DUPLICATE_INDICATOR_ROW",
                "indicator": display_name,
                "field": "indicator_name",
                "message": f"最终Word存在重复指标行：{display_name}（{len(candidates)}行）",
            })
            continue
        row = candidates[0]
        for field in AUDIT_FIELDS:
            # Four-column customer templates intentionally omit a separate
            # standard field.  The standard decision still governs the
            # adopted value and basis, which remain fully audited.
            if field not in row:
                continue
            expected = str(decision.get(field, "") or "")
            if decision.get("display_labels") and field in {
                "user_requirement", "standard_requirement", "adopted_requirement",
            }:
                from jonhon_taskbook.indicator_identity import indicator_display_value
                expected = indicator_display_value(expected, display_name, decision["display_labels"])
            actual = str(row.get(field, "") or "")
            passed = _field_evidence(expected, field) == _field_evidence(actual, field)
            check = {
                "indicator": display_name,
                "field": field,
                "passed": passed,
                "expected": expected,
                "actual": actual,
            }
            checks.append(check)
            if not passed:
                blockers.append({
                    "code": "INDICATOR_VALUE_MISMATCH",
                    "indicator": display_name,
                    "field": field,
                    "message": f"{display_name} 的 {field} 与受控账本不一致",
                    "expected": expected,
                    "actual": actual,
                })

    if not decisions and not blockers:
        blockers.append({
            "code": "INDICATOR_LEDGER_EMPTY",
            "field": "comparison_decisions",
            "message": "技术指标审计账本没有可核验的裁决记录",
        })

    result = {
        "passed": not blockers,
        "checked_decisions": len(decisions),
        "checked_fields": len(checks),
        "blockers": blockers,
        "checks": checks,
        "source_table_rows_checked": len(source_table_checks),
        "source_table_checks": source_table_checks,
        "docx_path": str(path),
        "indicator_audit_path": str(audit_path),
    }
    if persist:
        sidecar = path.with_suffix(".business_value_audit.json")
        sidecar.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result["sidecar"] = str(sidecar)
    return result
