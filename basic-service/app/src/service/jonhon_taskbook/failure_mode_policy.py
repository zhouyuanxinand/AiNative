"""受控故障模式匹配与空结果治理策略。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "failure_mode_policy.yaml"
ALLOWED_EMPTY_ACTIONS = {"write_no_history_marker"}


@lru_cache(maxsize=1)
def load_failure_mode_policy() -> dict[str, Any]:
    if not POLICY_PATH.is_file():
        raise FileNotFoundError(f"故障模式策略文件不存在: {POLICY_PATH}")
    raw = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
    matching = raw.get("matching") or {}
    if str(matching.get("mode") or "") != "exact_product_and_series":
        raise ValueError("故障模式匹配必须使用 exact_product_and_series")
    if bool(matching.get("auto_similar_record_recall")):
        raise ValueError("7-22 不允许自动借用相似产品或相似系列故障记录")

    empty = raw.get("no_applicable_record") or {}
    action = str(empty.get("action") or "").strip()
    text = str(empty.get("text") or "").strip()
    if action not in ALLOWED_EMPTY_ACTIONS:
        raise ValueError(f"不支持的故障模式空结果动作: {action}")
    if action == "write_no_history_marker" and not text:
        raise ValueError("write_no_history_marker 必须配置非空 text")
    return raw


def failure_match_policy() -> dict[str, Any]:
    return dict(load_failure_mode_policy()["matching"])


def failure_no_match_policy() -> dict[str, str]:
    empty = load_failure_mode_policy()["no_applicable_record"]
    return {
        "action": str(empty["action"]),
        "text": str(empty["text"]),
    }

