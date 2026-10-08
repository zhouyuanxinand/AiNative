"""Failure-mode database matching for the controlled taskbook flow.

The database is reference evidence, not a source of generated prose.  A row is
eligible only when the selected product type is present in the product name and
the manually supplied product series matches the database model field.  The
matching code deliberately does not use template chapter numbers.
"""
from __future__ import annotations

import re
import hashlib
import unicodedata
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .failure_mode_policy import failure_match_policy, failure_no_match_policy


ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = ROOT / "resources" / "mappings" / "failure_mode_database_20260722.xlsx"


def _compact(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[‐‑‒–—−]", "-", text)
    return re.sub(r"\s+", "", text).strip().lower()


def _product_names(product_label: str) -> tuple[str, ...]:
    """The supplied optical template uses 光纤连接器 for catalog 光连接器.

    Sharing a taskbook template does not make the other product types aliases.
    In particular 机箱, 安装板 and 光布线箱 retain separate failure evidence.
    """
    key = _compact(product_label)
    if key in {"光连接器", "光纤连接器"}:
        return ("光连接器", "光纤连接器")
    return (key,) if key else ()


def _product_name_matches(product_label: str, source_name: str) -> bool:
    """Match complete product taxonomy nodes, excluding a trailing part name.

    Historical names are paths such as 产品族-产品类型-失效部位. A bare
    substring would assign 液冷机箱 to 机箱. A final non-root node alone may
    be a failure location, so it is not product proof.
    """
    source = _compact(source_name)
    for name in _product_names(product_label):
        for match in re.finditer(r"(?:^|-)" + re.escape(name) + r"(?=-|$)", source):
            if match.start() == 0 or match.end() < len(source):
                return True
    return False


def _clean_cell(value: Any) -> str:
    text = str(value if value is not None else "")
    text = text.replace("_x000D_", "\r").replace("_x000A_", "\n")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    # The source export wraps multiline cells in quotes. Remove only that
    # wrapper, keeping quoted part names and dimensions inside the evidence.
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1].replace('""', '"').strip()
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
    series_key = re.sub(r"系列(?:产品)?$", "", _compact(series))
    if not model_key or not series_key:
        return False
    if not model_key.startswith(series_key):
        return False
    remainder = model_key[len(series_key):]
    if not remainder:
        return True
    # C53 requires a complete series identifier, not a partial letter or
    # number group: ICG != ICGB, J599 != J5990, J599L != J599LM.
    return not (
        (re.fullmatch(r"[a-z]", series_key[-1]) and re.match(r"[a-z]", remainder))
        or (series_key[-1].isdigit() and remainder[0].isdigit())
    )


def _model_entries(model: str) -> list[str]:
    """Read explicitly listed models without breaking slashes in J599/20."""
    entries: list[str] = []
    items, start, depth = [], 0, 0
    for index, char in enumerate(model):
        if char in "(（[":
            depth += 1
        elif char in ")）]":
            depth = max(0, depth - 1)
        elif char in "、,，;；\r\n" and depth == 0:
            items.append(model[start:index])
            start = index + 1
    items.append(model[start:])
    for item in items:
        # A slash between two full hyphenated models is also a list separator,
        # e.g. SMA-KYW2-115/SMP-JW2-170. HDA/YBM... remains one model.
        parts = re.split(r"/(?=[A-Za-z][A-Za-z0-9()]*-)", item) if "-" in item.split("/", 1)[0] else [item]
        entries.extend(part.strip() for part in parts if part.strip())
    return list(dict.fromkeys(entries))


def _database_rows(database_path: str | Path, audit: dict, *, include_extra=False):
    """Locate event sheets by their schema; dictionary/cover sheets are skipped."""
    book = load_workbook(database_path, read_only=True, data_only=True)
    required = ("数据所属产品的产品名称", "所属型号", "故障描述", "故障原因", "设计改进措施")
    try:
        for sheet in book.worksheets:
            try:
                header_row, headers = _header_map(sheet)
            except ValueError:
                continue
            missing = [name for name in required if name not in headers]
            if missing:
                raise ValueError(f"故障模式库工作表 {sheet.title} 缺少列: {', '.join(missing)}")
            audit["data_sheets"].append({"name": sheet.title, "header_row": header_row})
            names = [name for name in headers if name] if include_extra else required
            for row_number, values in enumerate(sheet.iter_rows(
                min_row=header_row + 1, max_col=max(headers[name] for name in names) + 1,
                values_only=True,
            ), header_row + 1):
                yield sheet.title, row_number, {
                    name: _clean_cell(values[headers[name]]) for name in names
                }
        if not audit["data_sheets"]:
            raise ValueError("故障模式库缺少产品名称/所属型号表头，未找到故障事件工作表")
    finally:
        book.close()


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
    database_path: str | Path | None = None,
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
    database_path: str | Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return matches plus row-level acceptance/rejection evidence.

    The audit deliberately records why database rows were not used.  That makes
    an empty taskbook table distinguishable from a matcher that never ran.
    """
    product_key = _compact(product_label)
    series_key = _compact(product_series)
    audit: dict[str, Any] = {
        "database": str(Path(database_path)) if database_path is not None else "故障数据库",
        "data_sheets": [],
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
        audit["human_review_required"] = True
        return [], audit

    if database_path is None:
        from .failure_database import get_failure_database
        rows = get_failure_database().matching_rows(audit)
    else:
        audit["database_sha256"] = hashlib.sha256(Path(database_path).read_bytes()).hexdigest()
        rows = _database_rows(database_path, audit)
    result: list[dict[str, Any]] = []
    seen: dict[tuple[str, ...], dict] = {}
    for sheet_name, row_number, values in rows:
        get = values.get
        product_name = get("数据所属产品的产品名称")
        model = get("所属型号")
        if not product_name and not model:
            audit["rejected_counts"]["blank_row"] += 1
            continue
        audit["candidate_count"] += 1
        decision = {
            "source_sheet": sheet_name,
            "source_row": row_number,
            "source_product_name": product_name,
            "source_series": model,
            "accepted": False,
            "reason": "",
        }
        provenance = {key: values[key] for key in ("record_id", "record_version") if key in values}
        decision.update(provenance)
        controlled_product = values.get("controlled_product_label", "")
        product_matches = (_compact(controlled_product) in _product_names(product_label) if controlled_product
                           else _product_name_matches(product_label, product_name))
        if not product_matches:
            decision["reason"] = "PRODUCT_MISMATCH"
            audit["rejected_counts"]["product_mismatch"] += 1
            audit["candidates"].append(decision)
            continue
        audit["product_family_candidate_count"] += 1
        if len(audit["product_family_candidate_models"]) < 20 and model:
            if model not in audit["product_family_candidate_models"]:
                audit["product_family_candidate_models"].append(model)
        declared_series = values.get("controlled_series", "")
        if declared_series:
            # An explicit series is a business assertion; never infer aliases
            # such as J599/20 -> J599L from the old workbook's model field.
            series_id = lambda value: re.sub(r"系列(?:产品)?$", "", _compact(value))
            matched_models = [model] if series_id(declared_series) == series_id(product_series) else []
            decision["controlled_series"] = declared_series
        else:
            matched_models = [entry for entry in _model_entries(model) if _series_matches(entry, product_series)]
        decision["matched_models"] = matched_models
        if not matched_models:
            decision["reason"] = "SERIES_MISMATCH"
            audit["rejected_counts"]["series_mismatch"] += 1
            audit["candidates"].append(decision)
            continue
        # C53 指定“故障描述”字段；空值不能换用未约定的列或导致 KeyError。
        failure_mode = get("故障描述")
        record = {
            "product_name": values.get("product_name", _parent_product_name(product_name)),
            "source_product_name": product_name,
            "product_series": model,
            "failure_location": values.get("failure_location", _failure_location(product_name)),
            "failure_mode": failure_mode,
            "failure_analysis": get("故障原因"),
            "reliability_design_method": get("设计改进措施"),
            "source_row": row_number,
            "source_sheet": sheet_name,
            "matched_models": matched_models,
            "missing_fields": [name for name in ("故障描述", "故障原因", "设计改进措施") if not get(name)],
            **provenance,
        }
        source_record = {name: record[name] for name in (
            "source_sheet", "source_row", "product_series", "matched_models",
        )}
        source_record.update(provenance)
        key = tuple(str(record[name]) for name in (
            "product_name", "failure_location", "failure_mode",
            "failure_analysis", "reliability_design_method",
        ))
        if key not in seen:
            record["source_records"] = [source_record]
            seen[key] = record
            result.append(record)
            decision["accepted"] = True
            decision["reason"] = "MATCHED"
            audit["accepted_count"] += 1
        else:
            seen[key]["source_records"].append(source_record)
            decision["reason"] = "DUPLICATE"
            audit["rejected_counts"]["duplicate"] += 1
        audit["candidates"].append(decision)
    audit["status"] = "MATCHED" if result else "NO_APPLICABLE_RECORD"
    audit["matched_source_count"] = audit["accepted_count"] + audit["rejected_counts"]["duplicate"]
    if not result and audit["product_family_candidate_count"]:
        audit["no_match_reason"] = "PRODUCT_FAMILY_RECORDS_EXIST_BUT_SERIES_NOT_MATCHED"
    elif not result:
        audit["no_match_reason"] = "NO_PRODUCT_FAMILY_RECORD"
    # An empty result is a valid controlled outcome, but it must be visible as
    # a review item.  Never silently substitute a similar product/series: the
    # failure database is evidence, not a source for invented content.
    audit["human_review_required"] = not bool(result) or any(record["missing_fields"] for record in result)
    return result, audit
