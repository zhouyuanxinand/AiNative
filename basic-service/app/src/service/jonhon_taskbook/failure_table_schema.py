"""Shared semantic fields of controlled historical failure tables."""
from __future__ import annotations

import re
from collections.abc import Sequence

from docx.oxml.ns import qn


FIELD_ALIASES = {
    "product_name": ("数据所属产品", "产品名称"),
    "product_series": ("所属型号", "产品型号", "型号"),
    "failure_location": ("失效部位", "故障部位"),
    "failure_mode": ("失效模式", "故障现象", "故障模式"),
    "failure_analysis": ("失效分析", "失效机理", "失效模式机理", "故障原因", "故障机理", "原因分析"),
    "reliability_design_method": ("可靠性设计方法", "设计改进措施", "预防措施", "改进措施"),
}


def failure_mode_columns(headers: Sequence[str]) -> dict[str, int]:
    """Read header meaning without treating an analysis column as a mode."""
    result = {}
    for index, header in enumerate(headers):
        text = re.sub(r"\s+", "", str(header))
        for key, aliases in FIELD_ALIASES.items():
            if key == "failure_mode" and any(word in text for word in ("机理", "后果", "影响")):
                continue
            if any(text.startswith(alias) for alias in aliases):
                result.setdefault(key, index)
                break
    return result


def is_failure_table(headers: Sequence[str]) -> bool:
    columns = failure_mode_columns(headers)
    identity = bool({"product_name", "product_series"} & columns.keys())
    evidence_fields = {"failure_location", "failure_mode", "failure_analysis", "reliability_design_method"} & columns.keys()
    return (identity and len(evidence_fields) >= 2) or (
        "failure_location" in columns and "failure_mode" in columns
    )


def has_ordered_failure_fields(headers: Sequence[str]) -> bool:
    """Five distinct fields in identity/location/mode/analysis/method order."""
    if len(headers) != 5:
        return False
    columns = failure_mode_columns(headers)
    identity = "product_name" if "product_name" in columns else "product_series"
    expected = (identity, "failure_location", "failure_mode", "failure_analysis", "reliability_design_method")
    return all(columns.get(field) == index for index, field in enumerate(expected))


def has_independent_failure_cells(table) -> bool:
    """Five aligned physical fields may each span multiple Word grid columns.

    The optical-cable template gives its analysis field two grid columns.
    That is one field, unlike merging analysis and improvement body cells.
    Every body row must keep the header's exact five field boundaries.
    """
    rows = table.findall(qn("w:tr"))
    grid = table.find(qn("w:tblGrid"))
    if not rows or grid is None:
        return False
    grid_width = len(grid.findall(qn("w:gridCol")))
    expected = None
    for row in rows:
        cells = row.findall(qn("w:tc"))
        if len(cells) != 5 or row.findall(".//" + qn("w:vMerge")):
            return False
        # Omitted leading/trailing cells would shift a semantic field even
        # when the visible physical-cell count happens to remain five.
        if any(row.findall(".//" + qn(tag)) for tag in ("w:gridBefore", "w:gridAfter")):
            return False
        spans = []
        for cell in cells:
            span = cell.find(qn("w:tcPr") + "/" + qn("w:gridSpan"))
            try:
                width = int(span.get(qn("w:val"))) if span is not None else 1
            except (TypeError, ValueError):
                return False
            if width < 1:
                return False
            spans.append(width)
        if sum(spans) != grid_width or (expected is not None and spans != expected):
            return False
        expected = spans
    return True
