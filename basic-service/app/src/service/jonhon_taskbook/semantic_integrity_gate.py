# -*- coding: utf-8 -*-
"""Validate that exact source evidence was written to its semantic slot.

Coverage alone is insufficient for a controlled document: a sentence can occur
somewhere in the output while still being placed under the wrong heading.  This
gate joins the requirement classification, route plan and live output heading
tree.  Business policy stays in YAML; this module has no product or chapter IDs.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from docx import Document
from docx.oxml.ns import qn

from .template_scanner import scan_template_tree, semantic_title


_NON_SEMANTIC = re.compile(r"[\s，,。；;：:、.!！?？（）()\[\]【】]+")


_FIGURE_CAPTION = re.compile(
    r"^\s*(?:图\s*[0-9一二三四五六七八九十百]+|fig(?:ure)?\.?\s*[0-9]+)"
    r"\s*[：:、.\-—]?\s*(?P<body>.+?)\s*$",
    re.IGNORECASE,
)
_NORMALIZED_FIGURE_REFERENCE = re.compile(
    r"(?:图[0-9一二三四五六七八九十百]+|fig(?:ure)?[0-9]+)",
    re.IGNORECASE,
)


def _norm(value: Any) -> str:
    """Normalize display punctuation only; retain values, units and operators."""
    return _NON_SEMANTIC.sub("", str(value or "")).casefold()


def _element_text(element) -> str:
    # ``itertext()`` walks both Word text nodes and wrapper/tail proxies.  For
    # table XML this can expose the same visible cell text multiple times and
    # make exact-evidence checks fail even though the table was copied intact.
    # Controlled evidence is the visible ``w:t`` stream in document order.
    return "".join(node.text or "" for node in element.iter(qn("w:t")))


def _evidence_in_target(source_text: str, target_text: str) -> tuple[bool, str]:
    """Allow only deterministic figure-number changes in exact evidence checks."""
    normalized_target = _norm(target_text)
    if _norm(source_text) in normalized_target:
        return True, "exact"

    caption = _FIGURE_CAPTION.match(source_text)
    if caption:
        body = _norm(caption.group("body"))
        if len(body) >= 2 and body in normalized_target:
            return True, "figure_number_renumbered"

    # Figure renumbering also updates inline references such as “如下图7所示”.
    # Compare the complete normalized evidence after replacing only the figure
    # identifier.  Every other character, value and unit must still be present
    # in the target slot; this is not fuzzy matching.
    normalized_source = _norm(source_text)
    if _NORMALIZED_FIGURE_REFERENCE.search(normalized_source):
        source_skeleton = _NORMALIZED_FIGURE_REFERENCE.sub(
            "<figure>",
            normalized_source,
        )
        target_skeleton = _NORMALIZED_FIGURE_REFERENCE.sub(
            "<figure>",
            normalized_target,
        )
        if source_skeleton in target_skeleton:
            return True, "figure_reference_renumbered"

    return False, "missing"


def _section_texts(docx_path: str | Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    document = Document(str(docx_path))
    tree = scan_template_tree(str(docx_path))
    heading_by_slot = {
        node["id"]: document.paragraphs[node["paragraph_index"]]._p
        for node in tree
        if int(node.get("paragraph_index", -1)) < len(document.paragraphs)
    }
    # lxml 在沿 sibling 遍历时可能为同一 XML 节点创建新的 Python proxy；
    # `id(proxy)` 因此不是稳定节点身份。元素本身的 hash/equality 才按底层
    # libxml2 节点判断，否则遇到多级标题时会把后续章节正文并入前一章节。
    level_by_element = {
        heading_by_slot[node["id"]]: int(node.get("level", 0))
        for node in tree
        if node["id"] in heading_by_slot
    }
    result: dict[str, str] = {}
    for node in tree:
        heading = heading_by_slot.get(node["id"])
        if heading is None:
            continue
        level = int(node.get("level", 0))
        chunks: list[str] = []
        current = heading.getnext()
        while current is not None:
            current_level = level_by_element.get(current, 0)
            if current_level and current_level <= level:
                break
            chunks.append(_element_text(current))
            current = current.getnext()
        result[node["id"]] = "\n".join(chunks)
    return result, tree


def _slot_matches_category(
    slot: dict[str, Any],
    tree_by_id: dict[str, dict[str, Any]],
    category_policy: dict[str, Any],
) -> bool:
    title = _norm(semantic_title(str(slot.get("heading") or slot.get("title") or "")))
    keywords = [_norm(item) for item in category_policy.get("target_heading_keywords", [])]
    if keywords and not any(title == keyword or keyword in title for keyword in keywords):
        return False

    expected_parent = _norm(category_policy.get("target_parent_heading", ""))
    if expected_parent:
        parent = tree_by_id.get(str(slot.get("parent_id", "")), {})
        parent_title = _norm(parent.get("title") or parent.get("heading") or "")
        if not (parent_title == expected_parent or expected_parent in parent_title):
            return False

    expected_level = category_policy.get("target_heading_level")
    if expected_level is not None and int(slot.get("level", 0)) != int(expected_level):
        return False
    return bool(keywords)


def _rebind_live_slot(
    planned_slot: dict[str, Any],
    live_tree: list[dict[str, Any]],
    live_by_id: dict[str, dict[str, Any]],
    category_policy: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve a pre-assembly slot against the live post-assembly title tree.

    Slot IDs are hashes of the live semantic path. They intentionally change
    when controlled template editing removes a prompt suffix, renames a title,
    or inserts a sibling. A missing old ID is therefore rebound by configured
    title semantics, never by chapter number or source order.
    """
    candidates = [
        node
        for node in live_tree
        if _slot_matches_category(node, live_by_id, category_policy)
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    planned_title = _norm(
        semantic_title(
            str(planned_slot.get("heading") or planned_slot.get("title") or "")
        )
    )
    planned_occurrence = int(planned_slot.get("occurrence", 1) or 1)

    def score(node: dict[str, Any]) -> tuple[int, int]:
        live_title = _norm(
            semantic_title(str(node.get("heading") or node.get("title") or ""))
        )
        title_score = 2 if live_title == planned_title else 0
        occurrence_score = (
            1 if int(node.get("occurrence", 1) or 1) == planned_occurrence else 0
        )
        return title_score + occurrence_score, -int(node.get("paragraph_index", 0))

    ranked = sorted(candidates, key=score, reverse=True)
    if len(ranked) > 1 and score(ranked[0])[0] == score(ranked[1])[0]:
        return None
    return ranked[0]


def run_semantic_integrity_gate(
    output_path: str | Path,
    semantic_plan: dict[str, Any] | None,
    requirement_classification: dict[str, Any] | None,
    category_mapping_path: str | Path,
    *,
    sidecar_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a deterministic target-slot integrity report.

    Only categories explicitly marked ``target_integrity: exact`` participate.
    Structured writers such as the indicator table keep their dedicated gate.
    """
    plan = semantic_plan or {}
    classification = requirement_classification or {}
    mapping = yaml.safe_load(Path(category_mapping_path).read_text(encoding="utf-8")) or {}
    category_policies = {
        str(name): dict(policy or {})
        for name, policy in (mapping.get("categories") or {}).items()
        if str((policy or {}).get("target_integrity", "")).casefold() == "exact"
    }

    report: dict[str, Any] = {
        "policy": {
            "identity": "semantic_heading_path",
            "chapter_numbers_used": False,
            "exact_categories": sorted(category_policies),
        },
        "checked": [],
        "violations": [],
        "passed": False,
    }

    if not plan or not classification:
        report["violations"].append({"code": "MISSING_SEMANTIC_AUDIT_INPUT"})
    else:
        section_texts, live_tree = _section_texts(output_path)
        live_by_id = {str(node["id"]): node for node in live_tree}
        plan_slots = {str(node["id"]): node for node in plan.get("slots", [])}
        class_by_id = {
            str(item.get("source_id")): item
            for item in classification.get("classifications", [])
            if item.get("source_id")
        }
        class_source_by_id = {
            str(item.get("id")): item
            for item in classification.get("source_blocks", [])
            if item.get("id")
        }
        plan_source_by_id = {
            str(item.get("id")): item
            for item in plan.get("source_blocks", [])
            if item.get("id")
        }
        fragments_by_parent: dict[str, list[str]] = defaultdict(list)
        for source_id, block in class_source_by_id.items():
            parent = str(block.get("parent_source_id", ""))
            if parent:
                fragments_by_parent[parent].append(source_id)

        for decision in plan.get("decisions", []):
            if decision.get("operation") != "copy_exact":
                continue
            planned_slot_id = str(decision.get("target_slot", ""))
            planned_slot = plan_slots.get(planned_slot_id)
            live_slot = live_by_id.get(planned_slot_id)
            if not live_slot and not planned_slot:
                report["violations"].append({
                    "code": "TARGET_SLOT_NOT_FOUND",
                    "target_slot": planned_slot_id,
                })
                continue

            for routed_source_id in decision.get("source_ids", []):
                routed_source_id = str(routed_source_id)
                evidence_ids = (
                    [routed_source_id]
                    if routed_source_id in class_by_id
                    else fragments_by_parent.get(routed_source_id, [])
                )
                for evidence_id in evidence_ids:
                    category = str(class_by_id.get(evidence_id, {}).get("category", ""))
                    policy = category_policies.get(category)
                    if not policy:
                        continue
                    evidence_block = (
                        class_source_by_id.get(evidence_id)
                        or plan_source_by_id.get(evidence_id)
                        or plan_source_by_id.get(routed_source_id)
                        or {}
                    )
                    source_text = str(evidence_block.get("text", ""))
                    if not source_text or source_text.startswith("[图片对象"):
                        continue

                    slot = live_slot
                    rebound = False
                    if slot is None and planned_slot is not None:
                        slot = _rebind_live_slot(
                            planned_slot,
                            live_tree,
                            live_by_id,
                            policy,
                        )
                        rebound = slot is not None
                    if slot is None:
                        slot = planned_slot or {}
                    slot_id = str(slot.get("id", planned_slot_id))
                    target_matches = _slot_matches_category(slot, live_by_id, policy)
                    output_contains, evidence_match = _evidence_in_target(
                        source_text,
                        section_texts.get(slot_id, ""),
                    )
                    check = {
                        "source_id": evidence_id,
                        "parent_source_id": routed_source_id if evidence_id != routed_source_id else "",
                        "category": category,
                        "target_slot": slot_id,
                        "planned_target_slot": planned_slot_id,
                        "slot_rebound_by_semantics": rebound,
                        "target_path": slot.get("semantic_path", ""),
                        "target_matches_category": target_matches,
                        "exact_evidence_in_target": output_contains,
                        "evidence_match": evidence_match,
                    }
                    report["checked"].append(check)
                    if not target_matches:
                        report["violations"].append({"code": "WRONG_SEMANTIC_TARGET", **check})
                    elif not output_contains:
                        report["violations"].append({
                            "code": "SOURCE_EVIDENCE_MISSING_FROM_TARGET",
                            **check,
                            "source_preview": source_text[:160],
                        })

    report["passed"] = not report["violations"]
    destination = Path(sidecar_path) if sidecar_path else Path(output_path).with_suffix(
        ".semantic_integrity_gate.json"
    )
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["sidecar"] = str(destination)
    return report
