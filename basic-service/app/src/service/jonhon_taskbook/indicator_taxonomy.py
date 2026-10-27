"""External indicator taxonomy loader.

The taxonomy is a vocabulary only.  It must never provide a value, chapter
number, or product-specific default.  Values always come from the user's
technical requirement and (when applicable) the product specification.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from openpyxl import load_workbook
except Exception:  # pragma: no cover - optional until a taxonomy is installed
    load_workbook = None


DEFAULT_TAXONOMY = Path(__file__).resolve().parent / "resources" / "mappings" / "indicator_taxonomy_20260722.xlsx"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def load_indicator_taxonomy(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load rows as semantic names/categories, without hardcoded values."""
    target = Path(path) if path else DEFAULT_TAXONOMY
    if load_workbook is None or not target.is_file():
        return []
    workbook = load_workbook(target, read_only=True, data_only=True)
    try:
        sheet = workbook[workbook.sheetnames[0]]
        rows = sheet.iter_rows(values_only=True)
        header = [_text(value) for value in next(rows, ())]
        index = {name: pos for pos, name in enumerate(header) if name}
        name_index = next((index[key] for key in ("项目名称", "指标名称", "项目") if key in index), None)
        if name_index is None:
            return []
        category_index = next((index[key] for key in ("项目分类", "分类", "类别") if key in index), None)
        type_index = next((index[key] for key in ("类型", "指标类型") if key in index), None)
        # “备注”通常保存标准号、试验方法或业务说明，绝不能当成指标
        # 同义词。否则诸如 GJB 1217 的备注会激活“潮湿”等并不存在于
        # 设计输入中的正式指标。
        alias_index = next(
            (
                index[key]
                for key in ("别名", "同义词", "别称")
                if key in index
            ),
            None,
        )
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for values in rows:
            name = _text(values[name_index] if name_index < len(values) else "")
            if not name or name in seen:
                continue
            seen.add(name)
            aliases: list[str] = []
            if alias_index is not None and alias_index < len(values):
                aliases = [part.strip() for part in _text(values[alias_index]).replace("；", ";").split(";") if part.strip()]
            result.append({
                "name": name,
                "aliases": aliases,
                "category": _text(values[category_index]) if category_index is not None and category_index < len(values) else "",
                "type": _text(values[type_index]) if type_index is not None and type_index < len(values) else "",
                "source": str(target),
            })
        return result
    finally:
        workbook.close()


def taxonomy_indicator_map(path: str | Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """Return category -> vocabulary entries for semantic matching."""
    result: dict[str, list[dict[str, Any]]] = {}
    for entry in load_indicator_taxonomy(path):
        category = entry.get("category") or entry.get("type") or "其他"
        result.setdefault(category, []).append(entry)
    return result
