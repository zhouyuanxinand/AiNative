"""Failure-mode database matching for the controlled taskbook flow.

The database is reference evidence, not a source of generated prose.  A row is
eligible only when the selected product type is present in the product name and
the manually supplied product series matches the database model field.  The
matching code deliberately does not use template chapter numbers.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .failure_mode_policy import failure_match_policy, failure_no_match_policy


ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = ROOT / "resources" / "mappings" / "failure_mode_database_20260722.xlsx"


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def _clean_cell(value: Any) -> str:
    text = str(value or "").replace("_x000D_", "\n")
    text = text.replace('"', "").strip()
    return text


def _header_map(ws) -> tuple[int, dict[str, int]]:
    for row_index, values in enumerate(ws.iter_rows(values_only=True), 1):
        headers = {_clean_cell(value): idx for idx, value in enumerate(values)}
        if "数据所属产品的产品名称" in headers and "所属型号" in headers:
            return row_index, headers
        if row_index >= 20:
            break
    raise ValueError("故障模式库缺少产品名称/所属型号表头")


def _series_matches(model: str, series: str) -> bool:
    model_key = _compact(model)
    series_key = _compact(series)
    if not model_key or not series_key:
        return False
    # 允许用户输入完整型号，也允许数据库存储的是完整型号而界面输入的是
    # 系列前缀；不做模糊关键词扩散，避免把别的产品的历史故障带进来。
    return model_key.startswith(series_key) or series_key.startswith(model_key)


def _failure_location(product_name: str) -> str:
    parts = [part.strip() for part in str(product_name or "").split("-") if part.strip()]
    return parts[-1] if len(parts) > 1 else ""


def _parent_product_name(product_name: str) -> str:
    """7-22 输出“数据所属产品”时去掉最后一层失效部位。"""
    parts = [part.strip() for part in str(product_name or "").split("-") if part.strip()]
    return "-".join(parts[:-1]) if len(parts) > 1 else str(product_name or "").strip()


def match_failure_modes(
    product_label: str,
    product_series: str,
    database_path: str | Path = DEFAULT_DATABASE,
) -> list[dict[str, Any]]:
    """Return deterministic failure records for one controlled selection."""
    records, _ = match_failure_modes_with_audit(
        product_label,
        product_series,
        database_path,
    )
    return records


def match_failure_modes_with_audit(
    product_label: str,
    product_series: str,
    database_path: str | Path = DEFAULT_DATABASE,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return matches plus row-level acceptance/rejection evidence.

    The audit deliberately records why database rows were not used.  That makes
    an empty taskbook table distinguishable from a matcher that never ran.
    """
    product_key = _compact(product_label)
    series_key = _compact(product_series)
    audit: dict[str, Any] = {
        "database": str(Path(database_path)),
        "selected_product_label": product_label,
        "selected_product_series": product_series,
        "match_policy": {
            **failure_match_policy(),
            "empty_result_action": failure_no_match_policy()["action"],
        },
        "human_review_required": False,
        "candidate_count": 0,
        # 通过产品族语义/受控名称，但尚未通过系列前缀的行数。该字段只
        # 用于审计，不能作为自动降级匹配的依据。
        "product_family_candidate_count": 0,
        "product_family_candidate_models": [],
        "accepted_count": 0,
        "rejected_counts": {
            "blank_row": 0,
            "product_mismatch": 0,
            "series_mismatch": 0,
            "duplicate": 0,
        },
        "candidates": [],
    }
    if not product_key or not series_key:
        audit["status"] = "MISSING_CONTROLLED_SELECTION"
        return [], audit

    ws = load_workbook(database_path, read_only=True, data_only=True).worksheets[0]
    header_row, headers = _header_map(ws)
    required = (
        "数据所属产品的产品名称", "所属型号", "故障描述", "故障原因", "设计改进措施",
    )
    missing = [name for name in required if name not in headers]
    if missing:
        raise ValueError(f"故障模式库缺少列: {', '.join(missing)}")

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row_number, values in enumerate(
        ws.iter_rows(min_row=header_row + 1, values_only=True),
        header_row + 1,
    ):
        def get(name: str) -> str:
            index = headers[name]
            return _clean_cell(values[index] if index < len(values) else "")

        product_name = get("数据所属产品的产品名称")
        model = get("所属型号")
        if not product_name and not model:
            audit["rejected_counts"]["blank_row"] += 1
            continue
        audit["candidate_count"] += 1
        decision = {
            "source_row": row_number,
            "source_product_name": product_name,
            "source_series": model,
            "accepted": False,
            "reason": "",
        }
        if product_key not in _compact(product_name):
            decision["reason"] = "PRODUCT_MISMATCH"
            audit["rejected_counts"]["product_mismatch"] += 1
            audit["candidates"].append(decision)
            continue
        audit["product_family_candidate_count"] += 1
        if len(audit["product_family_candidate_models"]) < 20 and model:
            if model not in audit["product_family_candidate_models"]:
                audit["product_family_candidate_models"].append(model)
        if not _series_matches(model, product_series):
            decision["reason"] = "SERIES_MISMATCH"
            audit["rejected_counts"]["series_mismatch"] += 1
            audit["candidates"].append(decision)
            continue
        failure_mode = get("故障描述") or get("故障模式-产品") or get("故障模式-零件")
        record = {
            "product_name": _parent_product_name(product_name),
            "source_product_name": product_name,
            "product_series": model,
            "failure_location": _failure_location(product_name),
            "failure_mode": failure_mode,
            "failure_analysis": get("故障原因"),
            "reliability_design_method": get("设计改进措施"),
            "source_row": row_number,
        }
        key = tuple(str(record[name]) for name in (
            "product_name", "failure_location", "failure_mode",
            "failure_analysis", "reliability_design_method",
        ))
        if key not in seen:
            seen.add(key)
            result.append(record)
            decision["accepted"] = True
            decision["reason"] = "MATCHED"
            audit["accepted_count"] += 1
        else:
            decision["reason"] = "DUPLICATE"
            audit["rejected_counts"]["duplicate"] += 1
        audit["candidates"].append(decision)
    audit["status"] = "MATCHED" if result else "NO_APPLICABLE_RECORD"
    if not result and audit["product_family_candidate_count"]:
        audit["no_match_reason"] = "PRODUCT_FAMILY_RECORDS_EXIST_BUT_SERIES_NOT_MATCHED"
    # An empty result is a valid controlled outcome, but it must be visible as
    # a review item.  Never silently substitute a similar product/series: the
    # failure database is evidence, not a source for invented content.
    audit["human_review_required"] = not bool(result)
    return result, audit
