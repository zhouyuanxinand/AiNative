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

from jonhon_taskbook.indicator_identity import canonical_indicator_name


AUDIT_FIELDS = (
    "user_requirement",
    "standard_requirement",
    "adopted_requirement",
    "basis",
)


def _comparison_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", normalized)


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
            actual = str(row.get(field, "") or "")
            passed = _comparison_text(expected) == _comparison_text(actual)
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
