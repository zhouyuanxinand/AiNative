"""Load indicator vocabulary from controlled external resources.

This module deliberately contains no product values, chapter numbers, or
connector-specific defaults.  The technical requirement is the only source
of user values; a product specification is only an evidence source.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .config import BASE_DIR, RULE_PACK_PATH
from .indicator_taxonomy import load_indicator_taxonomy


REFERENCE_CATALOG_PATH = Path(BASE_DIR) / "config" / "connector_indicator_catalog.yaml"


_ROLE_CATEGORY = {
    "electrical": "电性能",
    "mechanical": "机械性能",
    "environmental": "环境性能",
    "high_frequency": "高频性能",
    "optical": "光性能",
}


@lru_cache(maxsize=4)
def load_reference_indicator_catalog(
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Load the value-free, number-free shared indicator vocabulary.

    The reference catalog is not a product baseline and never contributes
    values, required flags, or template chapter numbers.  An entry is only a
    controlled semantic name/alias that may be activated later when the
    current design input contains source evidence.
    """
    source = Path(path) if path else REFERENCE_CATALOG_PATH
    if not source.is_file():
        return []
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(raw, dict):
        return []

    entries: list[dict[str, Any]] = []
    for family_name in ("common", "high_frequency", "optical"):
        family = raw.get(family_name)
        if not isinstance(family, dict):
            continue
        for group_name, items in family.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                target_role = str(item.get("target_role", "")).strip()
                if not name or not target_role.startswith("performance_indicator."):
                    continue
                role_suffix = target_role.rsplit(".", 1)[-1]
                entries.append(
                    {
                        "name": name,
                        "aliases": [
                            str(value).strip()
                            for value in item.get("exact_aliases", [])
                            if str(value).strip()
                        ],
                        "related_terms": [
                            str(value).strip()
                            for value in item.get("related_terms", [])
                            if str(value).strip()
                        ],
                        "category": _ROLE_CATEGORY.get(
                            role_suffix,
                            str(group_name).strip() or "其他",
                        ),
                        "target_role": target_role,
                        "catalog_family": family_name,
                    }
                )
    return entries


def _resolve_catalog_path(rule_pack: Dict[str, Any], rule_pack_path: str) -> str:
    ref = rule_pack.get("indicator_catalog") or rule_pack.get("indicator_catalog_file") or ""
    if not ref:
        return ""
    if os.path.isabs(ref):
        return ref
    return os.path.join(os.path.dirname(rule_pack_path) or str(BASE_DIR), ref)


def _taxonomy_catalog() -> list[dict[str, Any]]:
    # Vocabulary entries intentionally omit `chapter`, `user_sections`,
    # `default_user`, and `default_adopted`.
    return [
        {
            "name": item["name"],
            "aliases": item.get("aliases", []),
            "category": item.get("category", ""),
            "type": item.get("type", ""),
        }
        for item in load_indicator_taxonomy()
        if item.get("name")
    ]


def _product_catalog(product_name: str) -> list[dict[str, Any]]:
    """Load an explicitly named product pack without aliases or sample inference."""
    if not product_name or Path(product_name).name != product_name:
        return []
    path = Path(BASE_DIR) / "products" / product_name / "catalog.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries: list[dict[str, Any]] = []
    for group in data.get("groups", []) if isinstance(data, dict) else []:
        for item in group.get("items", []):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            entry = dict(item)
            entry.setdefault("group", group.get("name", ""))
            entries.append(entry)
    return entries


@lru_cache(maxsize=8)
def get_indicator_catalog(
    rule_pack_path: str = RULE_PACK_PATH,
    product_name: str = "",
) -> List[Dict[str, Any]]:
    """Load an externally controlled indicator vocabulary.

    A missing catalog returns an empty list instead of silently using a
    connector quick-lock fixture.  This makes a missing product pack visible
    and prevents fabricated numeric rows in another product's document.
    """
    product_catalog = _product_catalog(product_name)
    if product_catalog:
        return product_catalog

    if os.path.isfile(rule_pack_path):
        try:
            with open(rule_pack_path, "r", encoding="utf-8") as handle:
                pack = json.load(handle)
        except (OSError, json.JSONDecodeError):
            pack = {}
        inline = pack.get("indicator_catalog_entries")
        if isinstance(inline, list) and inline:
            return [dict(entry) for entry in inline]
        external = _resolve_catalog_path(pack, rule_pack_path)
        if external and os.path.isfile(external):
            try:
                with open(external, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                entries = data if isinstance(data, list) else data.get("entries", [])
                if isinstance(entries, list):
                    return [dict(entry) for entry in entries]
            except (OSError, json.JSONDecodeError, AttributeError):
                pass

    return _taxonomy_catalog()


def catalog_entry_names(catalog: List[Dict[str, Any]] | None = None) -> set[str]:
    entries = catalog if catalog is not None else get_indicator_catalog()
    names: set[str] = set()
    for entry in entries:
        name = str(entry.get("name", "")).strip()
        if name:
            names.add(name)
        names.update(str(alias).strip() for alias in entry.get("aliases", []) if str(alias).strip())
    return names
