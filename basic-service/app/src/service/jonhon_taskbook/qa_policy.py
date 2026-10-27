"""Load the live QA policy shared by fill and the final pipeline gate."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "qa_gate.yaml"

_PROFILE_REQUIREMENTS = {
    "forbidden_phrases": "forbidden_phrases_exist",
    "required_phrases_all": "required_phrases_all",
    "required_phrase_groups": "required_phrase_groups",
    "required_headings": "required_headings",
    "required_figure_captions": "required_figure_captions",
    "required_table_keywords": "required_table_keywords",
    "required_table_headers": "required_table_headers",
}


def _merge(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_configured_qa_policy(
    profile_data: dict,
    *,
    preserve_template_guidance: bool,
    selected_product_domain: str = "",
    config_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Read each invocation so published rules apply without restarting.

    Product QA overrides replace common thresholds and switches. Required
    content supplied by the selected profile remains additive evidence: a
    common-format override must not erase expected text, figures or tables.
    """
    path = Path(config_path) if config_path is not None else DEFAULT_POLICY_PATH
    configured = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    override = profile_data.get("qa_gate") or {}
    qa_profile = profile_data.get("qa_profile") or {}
    if not all(isinstance(value, dict) for value in (configured, override, qa_profile)):
        raise ValueError("质量规则、qa_gate 和 qa_profile 必须是对象")
    rules = _merge(configured, override)
    block_rules = rules.setdefault("block_if", {})
    if not isinstance(block_rules, dict) or not isinstance(rules.get("warn_if", {}), dict):
        raise TypeError("质量规则 block_if 和 warn_if 必须是对象")
    # Some supplied templates express performance in dedicated chapters.  An
    # absent grid is valid there; any grid that is present still receives all
    # column, provenance and contamination checks below.
    if profile_data.get("technical_requirements_mode") == "sections":
        block_rules["indicator_table_missing"] = False
    for profile_key, rule_key in _PROFILE_REQUIREMENTS.items():
        requirements = qa_profile.get(profile_key, [])
        if not isinstance(requirements, list):
            raise TypeError(f"qa_profile.{profile_key} 必须是列表")
        if not requirements:
            continue
        existing = block_rules.setdefault(rule_key, [])
        if not isinstance(existing, list):
            raise TypeError(f"block_if.{rule_key} 必须是列表")
        for requirement in requirements:
            if requirement not in existing:
                existing.append(deepcopy(requirement))

    normalized_domain = str(selected_product_domain or "").strip().lower()
    flags = {
        "preserve_template_guidance": preserve_template_guidance,
        "is_as9100": bool(normalized_domain == "as9100" or qa_profile.get("is_as9100", False)),
        "is_civil_aircraft": bool(
            normalized_domain in {"airworthiness", "civil_aviation"}
            or qa_profile.get("is_civil_aircraft", False)
        ),
        "allow_landscape": bool(qa_profile.get("allow_landscape", False)),
        "standard_sort_order": deepcopy(profile_data.get("std_sort_order", [])),
        "standards_heading_keywords": deepcopy(qa_profile.get(
            "standards_heading_keywords", ["适用的法律法规要求", "适用法律法规", "引用标准"]
        )),
    }
    return rules, flags, str(path)
