"""受控研制流程分类及模板治理策略。

业务规则来自 ``config/development_process_policy.yaml``。代码只负责校验、
别名归一化和返回语义标题规则，不绑定任何显示章节号。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "development_process_policy.yaml"
)


@lru_cache(maxsize=1)
def load_development_process_policy() -> dict[str, Any]:
    if not POLICY_PATH.is_file():
        raise FileNotFoundError(f"研制流程策略文件不存在: {POLICY_PATH}")
    raw = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
    canonical = tuple(
        str(item).strip()
        for item in raw.get("canonical_processes", [])
        if str(item).strip()
    )
    if "全新" not in canonical:
        raise ValueError("研制流程策略必须包含“全新”")
    rules = raw.get("non_new_remove_sections", [])
    if not isinstance(rules, list):
        raise ValueError("non_new_remove_sections 必须是列表")
    validate_section_retention_rules(raw)
    raw["canonical_processes"] = canonical
    raw["aliases"] = {
        str(key).strip(): str(value).strip()
        for key, value in (raw.get("aliases") or {}).items()
        if str(key).strip() and str(value).strip()
    }
    return raw


def canonical_development_processes() -> tuple[str, ...]:
    return tuple(load_development_process_policy()["canonical_processes"])


def normalize_development_process(value: str | None) -> str:
    """把界面、API 或外部系统的流程名称归一化为受控值。"""
    policy = load_development_process_policy()
    text = str(value or "全新").strip() or "全新"
    normalized = policy["aliases"].get(text, text)
    allowed = tuple(policy["canonical_processes"])
    if normalized not in allowed:
        raise ValueError(f"研制流程分类必须是：{'、'.join(allowed)}")
    return normalized


def validate_section_retention_rules(policy: dict[str, Any]) -> None:
    """Use the same process/section validation for generation and rule edits."""
    rules = policy.get("section_retention_rules", [])
    if not isinstance(rules, list):
        raise ValueError("章节保留规则必须是列表")
    allowed = set(policy.get("canonical_processes", []))
    seen = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"第 {index + 1} 条章节保留规则必须是映射")
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id.strip() or rule_id in seen:
            raise ValueError("章节保留规则必须使用非空且唯一的标识")
        seen.add(rule_id)
        label = rule.get("label") or rule_id
        for key in ("semantic_titles", "keep_processes", "linked_semantic_titles"):
            values = rule.get(key)
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"{label}：{key} 必须是文本列表")
            if len(values) != len(set(values)):
                raise ValueError(f"{label}：{key} 存在重复值")
        if not rule["semantic_titles"]:
            raise ValueError(f"{label}：章节标题至少保留一项")
        if set(rule["keep_processes"]) - allowed:
            raise ValueError(f"{label}：保留流程包含未登记的研制流程")


def section_retention_rules() -> tuple[dict[str, Any], ...]:
    """Return process choices and linked sections from the live business rules."""
    return tuple(
        {
            "id": item["id"],
            "label": str(item.get("label") or item["id"]),
            "semantic_titles": tuple(item["semantic_titles"]),
            "keep_processes": tuple(item["keep_processes"]),
            "linked_semantic_titles": tuple(item["linked_semantic_titles"]),
        }
        for item in load_development_process_policy().get("section_retention_rules", [])
    )


def non_new_remove_section_rules() -> tuple[dict[str, Any], ...]:
    """兼容旧配置读取方；7-22 B56 下未规定的流程删节清单为空。"""
    controlled: list[dict[str, Any]] = []
    for index, item in enumerate(
        load_development_process_policy().get("non_new_remove_sections", [])
    ):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index + 1} 条非全新删节规则必须是映射")
        titles = tuple(
            str(title).strip()
            for title in item.get("semantic_titles", [])
            if str(title).strip()
        )
        if not titles:
            raise ValueError(f"第 {index + 1} 条非全新删节规则缺少 semantic_titles")
        controlled.append(
            {
                "id": str(item.get("id") or f"rule_{index + 1}"),
                "semantic_titles": titles,
                "reason": str(item.get("reason") or "非全新流程模板治理"),
            }
        )
    return tuple(controlled)


def new_process_manual_section_rules() -> tuple[dict[str, Any], ...]:
    """Legacy policy reader; B56 leaves template bodies intact, so no rewrites."""
    controlled: list[dict[str, Any]] = []
    raw_rules = load_development_process_policy().get(
        "new_process_manual_sections", []
    )
    if not isinstance(raw_rules, list):
        raise ValueError("new_process_manual_sections 必须是列表")
    for index, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index + 1} 条全新流程人工章节规则必须是映射")
        titles = tuple(
            str(title).strip()
            for title in item.get("semantic_titles", [])
            if str(title).strip()
        )
        output_title = str(item.get("output_title") or "").strip()
        note = str(item.get("note") or "").strip()
        if not titles or not output_title or not note:
            raise ValueError(
                f"第 {index + 1} 条全新流程人工章节规则缺少标题或提示语"
            )
        controlled.append(
            {
                "id": str(item.get("id") or f"manual_{index + 1}"),
                "semantic_titles": titles,
                "output_title": output_title,
                "note": note,
            }
        )
    return tuple(controlled)


def quality_section_evidence_rules() -> tuple[dict[str, Any], ...]:
    """Return externalized evidence rules for non-new quality sections."""
    controlled: list[dict[str, Any]] = []
    raw_rules = load_development_process_policy().get(
        "quality_section_evidence", []
    )
    if not isinstance(raw_rules, list):
        raise ValueError("quality_section_evidence 必须是列表")
    for index, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index + 1} 条六性证据规则必须是映射")
        title = str(item.get("semantic_title") or "").strip()
        roles = tuple(
            str(role).strip()
            for role in item.get("evidence_roles", [])
            if str(role).strip()
        )
        leaf_roles = tuple(
            str(role).strip()
            for role in item.get("leaf_evidence_roles", [])
            if str(role).strip()
        )
        titles = tuple(dict.fromkeys((title, *(
            str(alias).strip()
            for alias in item.get("semantic_aliases", [])
            if str(alias).strip()
        ))))
        signals = tuple(
            str(signal).strip()
            for signal in item.get("indicator_signals", [])
            if str(signal).strip()
        )
        if not title or not (roles or leaf_roles or signals):
            raise ValueError(
                f"第 {index + 1} 条六性证据规则缺少标题或证据条件"
            )
        controlled.append(
            {
                "id": str(item.get("id") or f"quality_{index + 1}"),
                "semantic_title": title,
                "semantic_titles": titles,
                "evidence_roles": roles,
                "leaf_evidence_roles": leaf_roles,
                "indicator_signals": signals,
            }
        )
    return tuple(controlled)


def failure_mode_section_titles() -> tuple[str, ...]:
    return tuple(load_development_process_policy().get(
        "failure_mode_section_titles", ["初步的失效模式分析", "初步失效模式分析"]
    ))


def quality_section_parent_titles() -> tuple[str, ...]:
    return tuple(load_development_process_policy().get(
        "quality_section_parent_titles", ["通用质量特性要求", "可通用质量特性要求"]
    ))
