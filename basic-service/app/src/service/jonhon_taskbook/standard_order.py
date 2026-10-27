"""Configured standard-family ordering shared by generation and QA.

The sorter reads families from the selected product profile. It never uses a
template chapter number or a product/model name as an identity. A family may
contain multiple equivalent prefixes (for example ``[GB/T, GB]``), so standards
inside that family are ordered by their numeric standard identifier.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def normalize_standard_families(order: Sequence[Any] | None) -> list[tuple[str, ...]]:
    """Normalize YAML string/list entries into ordered prefix families."""
    families: list[tuple[str, ...]] = []
    for entry in order or ():
        raw: Iterable[Any] = entry if isinstance(entry, (list, tuple)) else (entry,)
        prefixes = tuple(
            sorted(
                {_compact(prefix) for prefix in raw if _compact(prefix)},
                key=len,
                reverse=True,
            )
        )
        if prefixes:
            families.append(prefixes)
    return families


def standard_sort_key(value: str, order: Sequence[Any] | None) -> tuple[int, int, str]:
    """Return family rank, numeric identifier and normalized full text."""
    compact = _compact(value)
    families = normalize_standard_families(order)
    family_rank = len(families)
    matched_prefix = ""
    matches = [
        (len(prefix), index, prefix)
        for index, prefixes in enumerate(families)
        for prefix in prefixes
        if compact.startswith(prefix)
    ]
    if matches:
        _, family_rank, matched_prefix = max(matches, key=lambda item: item[0])
    suffix = compact[len(matched_prefix):] if matched_prefix else compact
    number = re.search(r"\d+", suffix)
    return family_rank, int(number.group()) if number else 10**12, compact


def sort_standards(lines: Sequence[str], order: Sequence[Any] | None) -> list[str]:
    return sorted(lines, key=lambda value: standard_sort_key(value, order))
