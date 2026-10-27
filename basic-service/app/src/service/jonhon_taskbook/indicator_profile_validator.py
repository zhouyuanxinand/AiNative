# -*- coding: utf-8 -*-
"""Validate product indicator vocabularies before a controlled run.

An indicator profile may freeze canonical names and safe exact aliases.  It
must not freeze template chapter numbers, source presence, product values, or
ambiguous related concepts.  Related terms are useful retrieval candidates,
but they are not exact aliases and therefore live in ``related_kws``.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


_EXACT_FIELDS = (
    "name",
    "tech_kws",
    "std_kws",
    "spec_kws",
    "spec_exact_names",
)
_FORBIDDEN_LOCATION_FIELDS = {
    "target_section",
    "target_table",
    "tech_sec",
    "spec_sec",
    "section_prefix",
    "source_section",
}
_FORBIDDEN_EXACT_ALIASES = {
    "工作电压": {"额定电压", "电压范围"},
    "额定电压": {"工作电压", "工作电压范围"},
    "工作电流": {"额定电流", "额定载流量", "载流量"},
    "额定电流": {"工作电流", "工作载流"},
    "温度冲击": {"温度循环"},
    "湿热": {"潮湿"},
    "插拔力": {
        "插入力",
        "插合力",
        "分离力",
        "拔出力",
        "分离扭矩",
        "接触件插入力",
        "接触件分离力",
    },
}


def _values(item: dict[str, Any], field: str) -> list[str]:
    value = item.get(field, [])
    if field == "name":
        value = [value]
    elif not isinstance(value, (list, tuple, set)):
        value = [value]
    return [str(entry).strip() for entry in value if str(entry).strip()]


def validate_indicator_profile(
    profile: dict[str, Any],
    *,
    source: str = "<profile>",
) -> None:
    """Raise ``ValueError`` when a profile embeds unsafe indicator rules."""
    indicator_map = profile.get("indicator_map") or {}
    if not isinstance(indicator_map, dict):
        raise ValueError(f"{source}: indicator_map 必须是按指标类别组织的映射")

    errors: list[str] = []
    exact_owners: dict[str, set[str]] = defaultdict(set)

    for category, items in indicator_map.items():
        if not isinstance(items, list):
            errors.append(f"{category}: 指标集合必须是列表")
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{category}[{index}]: 指标必须是对象")
                continue
            name = str(item.get("name", "")).strip()
            label = name or f"{category}[{index}]"
            if not name:
                errors.append(f"{label}: 缺少规范化指标名 name")
                continue

            if "required" in item:
                errors.append(
                    f"{label}: 不允许全局 required；是否出现必须由本次设计输入证据决定"
                )
            for field in _FORBIDDEN_LOCATION_FIELDS:
                if field in item:
                    errors.append(
                        f"{label}: 不允许 {field}；目标必须由模板实时语义槽位决定"
                    )

            exact_terms: set[str] = set()
            for field in _EXACT_FIELDS:
                for term in _values(item, field):
                    exact_terms.add(term)
                    exact_owners[term].add(name)

            related_terms = set(_values(item, "related_kws"))
            overlap = exact_terms & related_terms
            if overlap:
                errors.append(
                    f"{label}: related_kws 与精确词重复: {sorted(overlap)}"
                )

            forbidden = exact_terms & _FORBIDDEN_EXACT_ALIASES.get(name, set())
            if forbidden:
                errors.append(
                    f"{label}: 相关概念不能作为精确同义词: {sorted(forbidden)}"
                )

            for value in item.values():
                if (
                    isinstance(value, str)
                    and re.match(r"^\s*\d+(?:\.\d+)+(?:\s|$)", value)
                ):
                    errors.append(f"{label}: 不允许在指标配置中固化章节号: {value}")

    for term, owners in sorted(exact_owners.items()):
        if len(owners) > 1:
            errors.append(
                f"精确词“{term}”同时属于多个指标: {sorted(owners)}；请降级为 related_kws"
            )

    if errors:
        detail = "\n- ".join(errors)
        raise ValueError(f"{source}: 指标配置未通过通用性门禁\n- {detail}")

