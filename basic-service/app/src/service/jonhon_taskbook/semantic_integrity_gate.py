# -*- coding: utf-8 -*-
"""Validate that exact source evidence was written to its semantic slot.

Coverage alone is insufficient for a controlled document: a sentence can occur
somewhere in the output while still being placed under the wrong heading.  This
gate joins the requirement classification, route plan and live output heading
tree.  Business policy stays in YAML; this module has no product or chapter IDs.
"""
from __future__ import annotations

import json
import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from .environmental_prose import is_environmental_slot, project_environmental_evidence
from .template_scanner import scan_template_tree, semantic_title
from .source_scope import normalize_source_display_text


_NON_SEMANTIC = re.compile(r"[\s，,。；;：:、.!！?？（）()\[\]【】]+")
_MANUAL_LIST = re.compile(
    r"^\s*(?:[（(][a-zA-Z\d一二三四五六七八九十]+[）)]|"
    r"[a-zA-Z\d]+[)）、]|[a-zA-Z]\.\s*|[•●▪]|[\d一二三四五六七八九十]+[.、](?!\d))"
)


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


def _evidence_in_target(
    source_text: str, target_text: str, *, heading_number: str = "", heading_text: str = ""
) -> tuple[bool, str]:
    """Allow controlled display changes without dropping technical evidence."""
    normalized_target = _norm(target_text)
    if _norm(source_text) in normalized_target:
        return True, "exact"

    source_display = normalize_source_display_text(
        source_text, heading_number=heading_number, heading_text=heading_text,
    )
    target_display = "\n".join(normalize_source_display_text(line) for line in target_text.splitlines())
    if source_display and source_display in target_display:
        return True, "display_number_or_terminal_punctuation"

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


def _is_list_paragraph(element, document) -> bool:
    if _MANUAL_LIST.match(_element_text(element)):
        return True
    paragraph = Paragraph(element, document)
    properties = [element.find(qn("w:pPr"))]
    style = paragraph.style
    while style is not None:
        properties.append(style.element.find(qn("w:pPr")))
        style = style.base_style
    for properties_node in properties:
        if properties_node is None:
            continue
        numbering = properties_node.find(qn("w:numPr"))
        if numbering is not None:
            number_id = numbering.find(qn("w:numId"))
            # numId=0 explicitly cancels numbering inherited from a style.
            return number_id is None or number_id.get(qn("w:val")) != "0"
    return False


def _section_contents(docx_path: str | Path) -> tuple[
    dict[str, str], list[dict[str, Any]], dict[str, list[str]], dict[str, list[str]],
]:
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
    non_prose: dict[str, list[str]] = {}
    prose_paragraphs: dict[str, list[str]] = {}
    for node in tree:
        heading = heading_by_slot.get(node["id"])
        if heading is None:
            continue
        level = int(node.get("level", 0))
        chunks: list[str] = []
        paragraphs: list[str] = []
        structures: set[str] = set()
        current = heading.getnext()
        while current is not None:
            current_level = level_by_element.get(current, 0)
            if current_level and current_level <= level:
                break
            chunks.append(_element_text(current))
            if is_environmental_slot(node):
                if any(True for _ in current.iter(qn("w:tbl"))):
                    structures.add("table")
                for paragraph in current.iter(qn("w:p")):
                    if paragraph in level_by_element:
                        continue
                    paragraphs.append(_element_text(paragraph))
                    if _is_list_paragraph(paragraph, document):
                        structures.add("list")
            current = current.getnext()
        result[node["id"]] = "\n".join(chunks)
        prose_paragraphs[node["id"]] = paragraphs
        if structures:
            non_prose[node["id"]] = sorted(structures)
    return result, tree, non_prose, prose_paragraphs


def _section_texts(docx_path: str | Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    texts, tree, _, _ = _section_contents(docx_path)
    return texts, tree


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
    require_complete_source_checks: bool = False,
) -> dict[str, Any]:
    """Return a deterministic target-slot integrity report.

    Categories marked ``target_integrity: exact`` retain whole-block checking.
    Environmental destinations check the source-owned prose projection even
    when the source block's primary category uses a separate indicator gate.
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
        "output_sha256": hashlib.sha256(Path(output_path).read_bytes()).hexdigest(),
        "require_complete_source_checks": require_complete_source_checks,
    }
    environmental_policy = (mapping.get("categories") or {}).get(
        "environmental_adaptability", {"target_heading_keywords": ["环境适应性"]},
    )
    coverage_path = Path(output_path).with_suffix(".coverage_ledger.json")
    if coverage_path.is_file():
        report["coverage_ledger_sha256"] = hashlib.sha256(coverage_path.read_bytes()).hexdigest()

    if not plan or not classification:
        report["violations"].append({"code": "MISSING_SEMANTIC_AUDIT_INPUT"})
    else:
        section_texts, live_tree, non_prose, prose_paragraphs = _section_contents(output_path)
        live_by_id = {str(node["id"]): node for node in live_tree}
        checked_prose_slots: set[str] = set()
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

            environmental_target = is_environmental_slot(planned_slot) or is_environmental_slot(live_slot)

            for routed_source_id in decision.get("source_ids", []):
                routed_source_id = str(routed_source_id)
                evidence_ids = (
                    [routed_source_id]
                    if routed_source_id in class_by_id
                    else fragments_by_parent.get(routed_source_id, [])
                )
                if environmental_target and not evidence_ids and (
                    routed_source_id in class_source_by_id or routed_source_id in plan_source_by_id
                ):
                    evidence_ids = [routed_source_id]
                for evidence_id in evidence_ids:
                    category = str(class_by_id.get(evidence_id, {}).get("category", ""))
                    policy = environmental_policy if environmental_target else category_policies.get(category)
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
                    if environmental_target:
                        # Recompute evidence from the source block, not from an
                        # execution sidecar or from the generated document.
                        # No projection means no source check: strict routing
                        # and the independent whole-source coverage gate remain
                        # responsible for non-environmental evidence.
                        try:
                            projections = project_environmental_evidence(evidence_block)
                        except (OSError, ValueError, IndexError) as exc:
                            report["violations"].append({
                                "code": "ENVIRONMENTAL_SOURCE_EVIDENCE_INVALID",
                                "source_id": evidence_id, "target_slot": slot_id,
                                "detail": str(exc),
                            })
                            continue
                        if projections and slot_id in non_prose and slot_id not in checked_prose_slots:
                            # Unfilled controlled template guidance is audited
                            # by template provenance. Once source requirements
                            # populate this slot, all retained lists/tables are
                            # invalid, including old template instructions.
                            report["violations"].append({
                                "code": "ENVIRONMENTAL_PROSE_REQUIRED", "target_slot": slot_id,
                                "target_path": slot.get("semantic_path", ""),
                                "structures": non_prose[slot_id],
                            })
                            checked_prose_slots.add(slot_id)
                        target_paragraphs = {
                            normalize_source_display_text(line)
                            for line in prose_paragraphs.get(slot_id, [])
                        }
                        for projection in projections:
                            # Keep decimal points and operators: general exact
                            # matching historically normalizes more punctuation
                            # than this controlled projection permits.
                            output_contains = normalize_source_display_text(projection["text"]) in target_paragraphs
                            evidence_match = "environmental_prose" if output_contains else "missing"
                            check = {
                                "source_id": evidence_id,
                                "parent_source_id": routed_source_id if evidence_id != routed_source_id else "",
                                "category": category, "target_slot": slot_id,
                                "planned_target_slot": planned_slot_id,
                                "slot_rebound_by_semantics": rebound,
                                "target_path": slot.get("semantic_path", ""),
                                "target_matches_category": target_matches,
                                "exact_evidence_in_target": output_contains,
                                "evidence_match": evidence_match,
                                "projection_policy": projection["policy"],
                                "source_fragments": projection["source_fragments"],
                                "source_coordinates": projection["source_coordinates"],
                            }
                            if projection.get("source_headers"):
                                check["source_headers"] = projection["source_headers"]
                            report["checked"].append(check)
                            if not target_matches:
                                report["violations"].append({"code": "WRONG_SEMANTIC_TARGET", **check})
                            elif not output_contains:
                                report["violations"].append({
                                    "code": "SOURCE_EVIDENCE_MISSING_FROM_TARGET", **check,
                                    "source_preview": projection["text"][:160],
                                })
                        continue
                    output_contains, evidence_match = _evidence_in_target(
                        source_text,
                        section_texts.get(slot_id, ""),
                        heading_number=str(evidence_block.get("heading_number", "")),
                        heading_text=str(evidence_block.get("heading_text", "")),
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

        if require_complete_source_checks:
            checked_ids = {check["source_id"] for check in report["checked"]}
            expected_ids = {
                source_id for source_id, item in class_by_id.items()
                if item.get("category") in category_policies
                and str(class_source_by_id.get(source_id, {}).get("text", "")).strip()
                and not str(class_source_by_id.get(source_id, {}).get("text", "")).startswith("[图片对象")
            }
            report["expected_source_ids"] = sorted(expected_ids)
            for source_id in sorted(expected_ids - checked_ids):
                report["violations"].append({
                    "code": "SOURCE_SEMANTIC_ROUTE_NOT_CHECKED", "source_id": source_id,
                    "category": class_by_id[source_id].get("category", ""),
                })

    report["passed"] = not report["violations"]
    destination = Path(sidecar_path) if sidecar_path else Path(output_path).with_suffix(
        ".semantic_integrity_gate.json"
    )
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["sidecar"] = str(destination)
    return report
