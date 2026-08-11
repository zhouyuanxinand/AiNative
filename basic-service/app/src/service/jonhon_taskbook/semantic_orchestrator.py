# -*- coding: utf-8 -*-
"""多节点 LLM 语义编排器。

LLM 只返回分类、作用域和 source_id -> template_slot 路由决策；它无权
生成或改写正式文本。执行器只接受 ``copy_exact``，并从源 DOCX 中复制
对应 XML 元素。所有决策和复制结果均落盘，供追溯和门禁使用。
"""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from lxml import etree
import yaml

from .template_scanner import semantic_title as _semantic_title

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{W}}}"

ChatJSON = Callable[[str, str], Any]
_ALLOWED_ROLES = {"technical_requirement", "product_specification", "template", "unknown"}
_SKIP_SLOT_WORDS = {"目录", "封面", "变更记录", "批准", "审核", "会签", "签署"}
_ALLOWED_EDIT_ACTIONS = {
    "append", "replace", "insert_before", "insert_after", "preserve", "delete"
}


def _composer_class():
    """优先使用已安装包，缺失时使用项目内受控的 docxcompose 副本。"""
    try:
        from docxcompose.composer import Composer
        return Composer
    except ModuleNotFoundError:
        vendored_root = Path(__file__).resolve().parents[1] / "third_party_sources" / "docxcompose"
        if not (vendored_root / "docxcompose" / "composer.py").is_file():
            raise
        vendored_text = str(vendored_root)
        if vendored_text not in sys.path:
            sys.path.insert(0, vendored_text)
        from docxcompose.composer import Composer
        return Composer


def _text(el) -> str:
    return "".join(t.text or "" for t in el.findall(f".//{_W}t")).strip()


def _style(el) -> str:
    ppr = el.find(f"{_W}pPr")
    ps = ppr.find(f"{_W}pStyle") if ppr is not None else None
    return ps.get(f"{_W}val", "") if ps is not None else ""


def _outline_level(el) -> int:
    """读取 Word 的结构层级；显示编号和章节顺序不参与识别。"""
    ppr = el.find(f"{_W}pPr") if el is not None else None
    outline = ppr.find(f"{_W}outlineLvl") if ppr is not None else None
    raw = outline.get(f"{_W}val") if outline is not None else None
    return int(raw) + 1 if raw is not None and str(raw).isdigit() else 0


def _is_heading(el) -> bool:
    if el.tag != f"{_W}p":
        return False
    if re.match(r"^[1-9]$|^[Hh]eading|^标题", _style(el)) or _outline_level(el):
        return True
    # 真实受控文档常把章节号放在“正文/Normal”样式中。标题必须是
    # 短段落且以独立的层级编号开头，避免把 1000 V 等指标值误认成标题。
    text = _text(el).strip()
    return bool(
        len(text) <= 100
        and re.match(r"^\d+(?:\.\d+)*\s+[\u4e00-\u9fffA-Za-z]", text)
    )


def _is_style_heading(el) -> bool:
    """只判断 Word 结构样式，不读取显示章节号。"""
    return bool(
        el.tag == f"{_W}p"
        and (re.match(r"^[1-9]$|^[Hh]eading|^标题", _style(el)) or _outline_level(el))
    )


def _heading_level(el) -> int:
    style = _style(el)
    match = re.search(r"(?:Heading|heading)?\s*([1-9])$", style)
    if match:
        return int(match.group(1))
    outline_level = _outline_level(el)
    if outline_level:
        return outline_level
    number = re.match(r"^(\d+(?:\.\d+)*)\s+", _text(el).strip())
    return number.group(1).count(".") + 1 if number else 1


def _split_heading(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    match = re.match(r"^(\d+(?:\.\d+)*)(?:\s+|[、)]|[.．](?!\d))(.*)$", raw)
    if not match:
        # Chinese display numbering (``第八章``/``一、``/``（一）``) is
        # presentation only.  Removing it here keeps source chapter IDs and
        # parent paths stable when a customer renumbers or reorders a file.
        return "", _semantic_title(raw)
    return match.group(1), _semantic_title(raw)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _hash(text: str) -> str:
    return hashlib.sha256(_norm(text).encode("utf-8")).hexdigest()


def _file_sha256(path: str | Path) -> str:
    """Return a content fingerprint used only for reproducible plan caching."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_fingerprint() -> str:
    """Fingerprint routing configuration without ever persisting credentials."""
    keys = (
        "JTB_LLM_PROVIDER", "JTB_LLM_API_URL", "JTB_LLM_MODEL",
        "JTB_LLM_MODEL_ID", "JTB_LLM_APP_ID", "JTB_LLM_MAX_TOKENS",
    )
    values = {key: os.getenv(key, "") for key in keys}
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _plan_cache_key(
    tech_path: str,
    spec_path: str,
    template_path: str,
    *,
    category_mapping_path: str | None = None,
    requirement_classification: dict | None = None,
) -> str:
    classification_payload = (
        (requirement_classification or {}).get("classifications", [])
        if isinstance(requirement_classification, dict)
        else []
    )
    payload = {
        "schema": "semantic-plan-cache-v3",
        "module": _file_sha256(Path(__file__)),
        "tech": _file_sha256(tech_path),
        "spec": _file_sha256(spec_path),
        "template": _file_sha256(template_path),
        "category_mapping": (
            _file_sha256(category_mapping_path)
            if category_mapping_path and Path(category_mapping_path).is_file()
            else ""
        ),
        "requirement_classification": hashlib.sha256(
            json.dumps(
                classification_payload,
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
        "model": _model_fingerprint(),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _slot_depth(slot: dict) -> int:
    path = str(slot.get("semantic_path", ""))
    return max(int(slot.get("level", 1) or 1), len([x for x in re.split(r"\s*[>/|]\s*", path) if x]))


def _semantic_terms(value: Any) -> set[str]:
    """Extract generic Chinese/ASCII terms for deterministic tie breaking.

    This is deliberately only a last-resort tie breaker after the LLM has
    selected candidate slots.  It does not classify a block by itself and it
    contains no product-specific keyword list.
    """
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(value or "")).lower()
    terms: set[str] = set(re.findall(r"[a-z0-9_]{2,}", text))
    han = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    terms.update(han[i : i + 2] for i in range(max(0, len(han) - 1)))
    terms.update(han[i : i + 3] for i in range(max(0, len(han) - 2)))
    return {term for term in terms if term}


def _tie_break_score(source_block: dict | None, slot: dict) -> float:
    if not source_block:
        return 0.0
    source_text = " ".join(
        str(source_block.get(key, ""))
        for key in ("heading_text", "section", "semantic_path", "parent_headings", "text")
    )
    slot_text = " ".join(
        str(slot.get(key, ""))
        for key in ("title", "heading", "semantic_path", "instructions", "table_headers")
    )
    source_terms = _semantic_terms(source_text)
    slot_terms = _semantic_terms(slot_text)
    if not source_terms or not slot_terms:
        return 0.0
    return len(source_terms & slot_terms) / max(1, len(source_terms))


def _canonicalize_routes(
    decisions: list[dict], slots: list[dict], source_blocks: list[dict] | None = None,
) -> tuple[list[dict], dict]:
    """Make the LLM route a deterministic, one-source/one-slot plan.

    A parent and one of its children are not two destinations.  The leaf slot
    wins because it is the only place where appending cannot cross the child
    subtree.  Conflicts between unrelated slots at the same depth are not
    guessed: they are reported as an error by the caller.
    """
    slot_by_id = {str(slot.get("id")): slot for slot in slots}
    block_by_id = {str(block.get("id")): block for block in (source_blocks or [])}
    candidates: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for index, decision in enumerate(decisions):
        target = str(decision.get("target_slot", ""))
        if target not in slot_by_id:
            continue
        for source_id in dict.fromkeys(decision.get("source_ids", []) or []):
            candidates[str(source_id)].append((index, decision))

    selected: dict[str, tuple[int, dict]] = {}
    resolved_parent_child: list[dict] = []
    ambiguous: list[dict] = []
    for source_id, items in candidates.items():
        unique_targets = {str(item[1].get("target_slot")) for item in items}
        if len(unique_targets) == 1:
            selected[source_id] = items[0]
            continue
        ranked = sorted(
            items,
            key=lambda item: (
                _slot_depth(slot_by_id[str(item[1].get("target_slot"))]),
                float(item[1].get("confidence", 0.0) or 0.0),
                str(slot_by_id[str(item[1].get("target_slot"))].get("semantic_path", "")),
                str(item[1].get("target_slot")),
            ),
            reverse=True,
        )
        winner_depth = max(
            _slot_depth(slot_by_id[str(item[1].get("target_slot"))])
            for item in ranked
        )
        same_depth = [
            item for item in ranked
            if _slot_depth(slot_by_id[str(item[1].get("target_slot"))]) == winner_depth
        ]
        # Depth is the structural rule; confidence breaks ties within that
        # depth.  Only a genuine confidence tie between unrelated slots is
        # ambiguous and must be surfaced instead of guessed.
        winner_confidence = max(
            float(item[1].get("confidence", 0.0) or 0.0) for item in same_depth
        )
        top_same_depth = [
            item for item in same_depth
            if float(item[1].get("confidence", 0.0) or 0.0) == winner_confidence
        ]
        source_block = block_by_id.get(source_id)
        scores = {
            str(item[1].get("target_slot")): _tie_break_score(
                source_block,
                slot_by_id[str(item[1].get("target_slot"))],
            )
            for item in top_same_depth
        }
        max_score = max(scores.values(), default=0.0)
        top_scored = [
            item for item in top_same_depth
            if scores.get(str(item[1].get("target_slot")), 0.0) == max_score
        ]
        if len({str(item[1].get("target_slot")) for item in top_scored}) > 1:
            ambiguous.append({
                "source_id": source_id,
                "target_slots": sorted(unique_targets),
                "tie_break_scores": scores,
            })
            continue
        winner = sorted(
            top_scored,
            key=lambda item: (
                str(slot_by_id[str(item[1].get("target_slot"))].get("semantic_path", "")),
                str(item[1].get("target_slot")),
            ),
        )[0]
        selected[source_id] = winner
        resolved_parent_child.append({
            "source_id": source_id,
            "selected_slot": str(winner[1].get("target_slot")),
            "discarded_slots": sorted(unique_targets - {str(winner[1].get("target_slot"))}),
        })
    if ambiguous:
        raise ValueError(
            "semantic route conflict: one source block has unrelated target slots: "
            + json.dumps(ambiguous[:20], ensure_ascii=False)
        )

    # Preserve source order, while making decisions independent of LLM return
    # order and merging repeated entries for the same target/action.
    grouped: dict[tuple, dict] = {}
    source_order = {source_id: n for n, source_id in enumerate(candidates)}
    for source_id, (_index, decision) in selected.items():
        key = (
            str(decision.get("target_slot")),
            str(decision.get("edit_action", "append")),
            str(decision.get("anchor_slot", "")),
        )
        current = grouped.setdefault(key, {**decision, "source_ids": []})
        current["source_ids"].append(source_id)
    canonical = list(grouped.values())
    canonical.sort(key=lambda item: (
        next((source_order.get(source_id, 10**9) for source_id in item["source_ids"]), 10**9),
        str(item.get("target_slot")),
    ))
    for decision in canonical:
        decision["source_ids"] = sorted(
            dict.fromkeys(decision["source_ids"]), key=lambda source_id: source_order.get(source_id, 10**9)
        )
    audit = {
        "source_route_count": len(selected),
        "resolved_parent_child": resolved_parent_child,
        "ambiguous": ambiguous,
    }
    return canonical, audit


def _configured_category_slots(
    slots: list[dict],
    category_mapping_path: str | None,
) -> dict[str, str]:
    """Resolve configured semantic categories against the live title tree.

    The YAML contains semantic titles and optional parent/level constraints,
    never display chapter numbers.  A result is accepted only when the live
    template produces one unambiguous slot.
    """
    if not category_mapping_path:
        return {}
    mapping_file = Path(category_mapping_path)
    if not mapping_file.is_file():
        return {}
    data = yaml.safe_load(mapping_file.read_text(encoding="utf-8")) or {}
    rules = data.get("categories") or {}
    slot_by_id = {str(slot.get("id", "")): slot for slot in slots}
    resolved: dict[str, str] = {}

    def _controlled_title_rank(title: str, keywords: list[str]) -> int | None:
        """Return the configured synonym rank for a live template title.

        Customer templates often append an authoring note such as
        ``使用环境和部位（可附图说明）`` to the controlled business title.
        That note must not create a new semantic identity.  Only an exact title
        or a title followed immediately by a parenthetical suffix is accepted;
        arbitrary prefix matches remain forbidden.
        """
        for rank, keyword in enumerate(keywords):
            if title == keyword:
                return rank
            suffix = title[len(keyword):] if title.startswith(keyword) else ""
            if suffix.startswith(("(", "（")) and suffix.endswith((")", "）")):
                return rank
        return None

    for category, rule in rules.items():
        if not isinstance(rule, dict):
            continue
        keywords = rule.get("target_heading_keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        normalized_keywords = list(dict.fromkeys(
            _norm(_semantic_title(str(keyword)))
            for keyword in keywords
            if str(keyword).strip()
        ))
        if not normalized_keywords:
            continue
        target_level = int(rule.get("target_heading_level", 0) or 0)
        target_parent = _norm(_semantic_title(str(rule.get("target_parent_heading", ""))))
        candidates: list[tuple[int, dict]] = []
        for slot in slots:
            title = _norm(_semantic_title(str(slot.get("title") or slot.get("heading") or "")))
            keyword_rank = _controlled_title_rank(title, normalized_keywords)
            if keyword_rank is None:
                continue
            if target_level and int(slot.get("level", 0) or 0) != target_level:
                continue
            if target_parent:
                parent = slot_by_id.get(str(slot.get("parent_id", "")), {})
                parent_title = _norm(
                    _semantic_title(str(parent.get("title") or parent.get("heading") or ""))
                )
                if parent_title != target_parent:
                    continue
            # Prefer the first configured synonym, while keeping ambiguity
            # visible when the same semantic path occurs more than once.
            candidates.append((keyword_rank, slot))
        if len(candidates) == 1:
            resolved[str(category)] = str(candidates[0][1]["id"])
            continue
        if candidates:
            best_rank = min(rank for rank, _slot in candidates)
            best = [slot for rank, slot in candidates if rank == best_rank]
            if len(best) == 1:
                resolved[str(category)] = str(best[0]["id"])
    return resolved


def _enforce_requirement_route_authority(
    decisions: list[dict],
    slots: list[dict],
    source_blocks: list[dict],
    requirement_classification: dict | None,
    category_mapping_path: str | None,
) -> tuple[list[dict], dict]:
    """Constrain LLM routing with the approved 19-category classification.

    The model still performs semantic classification.  The deterministic
    boundary only converts that category into a live, number-independent
    template slot declared by YAML.  Product-specification blocks are excluded
    from requirement-body routing; their approved use remains indicator and
    standards evidence in the deterministic fill stage.
    """
    block_by_id = {str(block.get("id")): block for block in source_blocks}
    assignments = {
        str(item.get("source_id")): str(item.get("category"))
        for item in (
            (requirement_classification or {}).get("classifications", [])
            if isinstance(requirement_classification, dict)
            else []
        )
        if isinstance(item, dict) and item.get("source_id") and item.get("category")
    }
    category_slots = _configured_category_slots(slots, category_mapping_path)
    constrained: list[dict] = []
    overrides: list[dict] = []
    restricted_spec_sources: list[str] = []
    constrained_routes: list[dict] = []

    for decision in decisions:
        source_ids = list(dict.fromkeys(decision.get("source_ids", []) or []))
        if not source_ids:
            constrained.append(decision)
            continue
        grouped: dict[str, list[str]] = defaultdict(list)
        for source_id in source_ids:
            block = block_by_id.get(str(source_id), {})
            if str(block.get("source", "")) == "spec":
                restricted_spec_sources.append(str(source_id))
                continue
            category = assignments.get(str(source_id), "")
            target_slot = category_slots.get(category) or str(decision.get("target_slot", ""))
            if category and category in category_slots:
                constrained_routes.append({
                    "source_id": str(source_id),
                    "category": category,
                    "configured_slot": target_slot,
                })
            if target_slot != str(decision.get("target_slot", "")):
                overrides.append({
                    "source_id": str(source_id),
                    "category": category,
                    "model_slot": str(decision.get("target_slot", "")),
                    "configured_slot": target_slot,
                })
            if target_slot:
                grouped[target_slot].append(str(source_id))
        for target_slot, grouped_ids in grouped.items():
            constrained.append({
                **decision,
                "target_slot": target_slot,
                "source_ids": grouped_ids,
                "reason": (
                    f"{str(decision.get('reason', ''))[:180]} "
                    "[target constrained by approved semantic category]"
                ).strip(),
            })
    return constrained, {
        "classification_target_overrides": overrides,
        "classification_constrained_routes": constrained_routes,
        "restricted_product_specification_sources": sorted(
            dict.fromkeys(restricted_spec_sources)
        ),
        "category_slot_count": len(category_slots),
    }


def _backfill_classified_routes(
    decisions: list[dict],
    slots: list[dict],
    source_blocks: list[dict],
    requirement_classification: dict | None,
    category_mapping_path: str | None,
) -> tuple[list[dict], dict]:
    """Make the approved classification complete even when an LLM omits a block.

    The LLM route node is a semantic candidate generator, not the source of
    truth for coverage.  Every classified technical-requirement block that has
    a configured live template slot must appear exactly once in the route plan.
    This function adds only missing ``source_id`` references; it never creates,
    summarizes or rewrites document text.
    """
    if not requirement_classification:
        return decisions, {"classification_backfilled_routes": []}

    category_slots = _configured_category_slots(slots, category_mapping_path)
    if not category_slots:
        return decisions, {"classification_backfilled_routes": []}

    block_by_id = {
        str(block.get("id")): block
        for block in source_blocks
        if isinstance(block, dict) and block.get("id")
    }
    assignments = {
        str(item.get("source_id")): item
        for item in requirement_classification.get("classifications", [])
        if isinstance(item, dict) and item.get("source_id") and item.get("category")
    }
    already_routed = {
        str(source_id)
        for decision in decisions
        for source_id in (decision.get("source_ids", []) or [])
    }
    grouped: dict[str, list[tuple[str, str, float]]] = defaultdict(list)

    for source_id, assignment in assignments.items():
        if source_id in already_routed:
            continue
        block = block_by_id.get(source_id, {})
        # Product specifications are evidence for deterministic structured
        # writers, never ordinary requirement-body copy sources.
        if str(block.get("source", "")) != "tech":
            continue
        category = str(assignment.get("category", "")).strip()
        target_slot = category_slots.get(category, "")
        if not target_slot:
            continue
        confidence = float(assignment.get("confidence", 1.0) or 1.0)
        grouped[target_slot].append(
            (source_id, category, min(1.0, max(0.0, confidence)))
        )

    backfilled: list[dict] = []
    completed = list(decisions)
    for target_slot, items in grouped.items():
        source_ids = [source_id for source_id, _category, _confidence in items]
        confidence = min(confidence for _source_id, _category, confidence in items)
        completed.append({
            "target_slot": target_slot,
            "source_ids": source_ids,
            "operation": "copy_exact",
            "edit_action": "append",
            "anchor_slot": "",
            "confidence": confidence,
            "reason": (
                "approved classification coverage backfill; source text is "
                "copied exactly and was omitted by the LLM route candidate"
            ),
        })
        backfilled.extend({
            "source_id": source_id,
            "category": category,
            "configured_slot": target_slot,
        } for source_id, category, _confidence in items)

    return completed, {"classification_backfilled_routes": backfilled}


def _suppress_structured_writer_sources(
    decisions: list[dict],
    requirement_classification: dict | None,
    category_mapping_path: str | None,
) -> tuple[list[dict], dict]:
    """Keep structured evidence out of the ordinary paragraph copier.

    ``fill.py`` owns structured writers such as the indicator table and the
    standards ledger.  If the same source block is also left in the semantic
    copy plan, the executor appends a second copy after the table (the exact
    source is correct, but its destination is wrong and duplicated).  The
    classification remains in the audit ledger; only the ordinary copy action
    is suppressed.  The set is read from the category YAML, so new products or
    templates can add a structured writer without changing routing code.
    """
    if not requirement_classification or not category_mapping_path:
        return decisions, {"structured_sources_suppressed": [], "structured_writer_modes": {}}
    mapping_file = Path(category_mapping_path)
    if not mapping_file.is_file():
        return decisions, {"structured_sources_suppressed": [], "structured_writer_modes": {}}
    try:
        mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return decisions, {"structured_sources_suppressed": [], "structured_writer_modes": {}}
    rules = {
        **(mapping.get("categories") or {}),
        **(mapping.get("semantic_roles") or {}),
    }
    structured_modes = {
        str(category): str(rule.get("write_mode"))
        for category, rule in rules.items()
        if isinstance(rule, dict)
        and str(rule.get("write_mode", ""))
        in {"indicator_table", "standards_merge"}
    }
    if not structured_modes:
        return decisions, {"structured_sources_suppressed": [], "structured_writer_modes": {}}
    assignments = {
        str(item.get("source_id")): str(item.get("category"))
        for item in (requirement_classification.get("classifications") or [])
        if isinstance(item, dict) and item.get("source_id") and item.get("category")
    }
    suppressed: list[str] = []
    filtered: list[dict] = []
    for decision in decisions:
        kept_ids: list[str] = []
        for source_id in decision.get("source_ids", []) or []:
            sid = str(source_id)
            category = assignments.get(sid, "")
            if category in structured_modes:
                suppressed.append(sid)
                continue
            kept_ids.append(sid)
        if kept_ids:
            filtered.append({**decision, "source_ids": kept_ids})
        elif not (decision.get("source_ids") or []):
            filtered.append(decision)
    return filtered, {
        "structured_sources_suppressed": sorted(dict.fromkeys(suppressed)),
        "structured_writer_modes": structured_modes,
    }


def _element_hash(el) -> str:
    text = _text(el)
    if text:
        return _hash(text)
    return hashlib.sha256(etree.tostring(el)).hexdigest()


def copy_source_element_exact(source_el, block: dict):
    """Copy one source XML element, optionally trimming it to an exact span.

    Fragment coordinates are relative to the original paragraph text returned
    by :func:`_text`.  The helper edits only existing ``w:t`` nodes; it never
    asks a model to produce replacement wording.  Run properties, paragraph
    properties and styles therefore remain source-native.
    """
    copied = copy.deepcopy(source_el)
    if not block.get("is_fragment"):
        return copied
    if source_el.tag != f"{_W}p" or block.get("has_drawing"):
        raise ValueError("exact fragments are supported only for text-only paragraphs")
    # Only inline run controls affect the visible character stream.  Paragraph
    # tab-stop definitions are also named ``w:tab`` but live in ``w:pPr``;
    # they are formatting metadata and are safe to preserve.
    if (
        source_el.findall(f".//{_W}r/{_W}tab")
        or source_el.findall(f".//{_W}r/{_W}br")
    ):
        raise ValueError("exact fragment paragraph contains non-text layout controls")

    try:
        start = int(block.get("source_span_start", -1))
        end = int(block.get("source_span_end", -1))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid exact fragment coordinates") from exc
    parent_text = _text(source_el)
    fragment = str(block.get("text", ""))
    if start < 0 or end <= start or end > len(parent_text):
        raise ValueError("exact fragment coordinates are out of range")
    if parent_text[start:end] != fragment:
        raise ValueError("exact fragment text does not match the source coordinates")

    source_nodes = source_el.findall(f".//{_W}t")
    copied_nodes = copied.findall(f".//{_W}t")
    raw_text = "".join(node.text or "" for node in source_nodes)
    parent_offset = raw_text.find(parent_text)
    if parent_offset < 0:
        raise ValueError("source paragraph text cannot be aligned to its XML runs")
    raw_start = parent_offset + start
    raw_end = parent_offset + end
    cursor = 0
    for source_node, copied_node in zip(source_nodes, copied_nodes):
        value = source_node.text or ""
        node_start, node_end = cursor, cursor + len(value)
        keep_start = max(node_start, raw_start)
        keep_end = min(node_end, raw_end)
        kept = value[keep_start - node_start : keep_end - node_start] if keep_end > keep_start else ""
        copied_node.text = kept
        if kept and (kept[0].isspace() or kept[-1].isspace()):
            copied_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        cursor = node_end
    if "".join(node.text or "" for node in copied_nodes) != fragment:
        raise ValueError("exact fragment copy failed its byte-for-byte text check")
    return copied


def _referenced_image_hashes(document, element) -> set[str]:
    """Hash image payloads actually referenced by one body element.

    Package-level media presence is not enough: ``inject_media`` may copy an
    unused image part into the target package.  Resolve only relationship IDs
    referenced by the supplied paragraph or table.
    """
    relationship_ids = set(
        element.xpath(
            './/*[local-name()="blip"]/@*[local-name()="embed"]'
            ' | .//*[local-name()="imagedata"]/@*[local-name()="id"]'
        )
    )
    hashes: set[str] = set()
    for relationship_id in relationship_ids:
        part = document.part.related_parts.get(relationship_id)
        blob = getattr(part, "blob", None)
        if blob:
            hashes.add(hashlib.sha256(blob).hexdigest())
    return hashes


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _detect_source_heading_hints(
    elements: list[Any], source: str, chat_json_fn: ChatJSON,
) -> dict[int, dict[str, Any]]:
    """让 LLM 只识别标题段落坐标与层级；不让模型生成任何正文。"""
    paragraphs = []
    for body_index, element in enumerate(elements):
        if element.tag != f"{_W}p":
            continue
        text = _text(element)
        if not text:
            continue
        paragraphs.append({
            "body_index": body_index,
            "style": _style(element),
            "text": text[:500],
        })
    system = """你是技术文档结构识别器，只判断哪些原文段落是章节标题及标题层级，
不得分类业务内容，不得生成、改写或概括正文。章节显示编号和段落绝对顺序不是业务语义；
需要结合措辞、Word 样式和上下文识别有编号或无编号标题。只返回输入中存在的 body_index。
仅返回 JSON：{"headings":[{"body_index":12,"level":2,"confidence":0.95}]}。
level 只能是 1~9；普通正文、表格内容、图题和单独技术数值不得标成标题。"""
    raw = _call(chat_json_fn, system, {
        "node": "source_structure",
        "source": source,
        "paragraphs": paragraphs,
    })
    if "headings" not in raw or not isinstance(raw.get("headings"), list):
        raise ValueError(f"{source} 文档结构识别结果缺少 headings")
    paragraph_indices = {item["body_index"] for item in paragraphs}
    hints: dict[int, dict[str, Any]] = {}
    for item in raw["headings"]:
        if not isinstance(item, dict):
            continue
        try:
            body_index = int(item.get("body_index"))
            level = int(item.get("level"))
        except (TypeError, ValueError):
            continue
        confidence = _confidence(item.get("confidence", 0.0))
        if body_index not in paragraph_indices or not 1 <= level <= 9 or confidence < 0.60:
            continue
        hints[body_index] = {
            "level": level,
            "confidence": confidence,
            "method": "llm",
        }
    # Word 明确的 Heading/outline 样式属于文档结构事实，不需要模型猜测；
    # 它与显示章节号、业务槽位和章节顺序无关。
    for body_index, element in enumerate(elements):
        if _is_style_heading(element):
            hints[body_index] = {
                "level": _heading_level(element),
                "confidence": 1.0,
                "method": "word_style",
            }
    return hints


def extract_source_blocks(
    docx_path: str,
    source: str,
    *,
    chat_json_fn: ChatJSON | None = None,
    require_llm_structure: bool = False,
) -> list[dict]:
    """按 DOCX 内容建立本次运行的 source_id 清单。

    生产流程传入 ``chat_json_fn``，由 LLM 识别无编号/普通样式标题；直接调用
    时仍可使用 Word 结构与短编号标题解析，便于离线诊断。body_index 仅是
    当前 XML 的执行坐标，不参与 source_id 身份。
    """
    with zipfile.ZipFile(docx_path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(f"{_W}body")
    elements = list(body) if body is not None else []
    heading_hints: dict[int, dict[str, Any]] | None = None
    if chat_json_fn is not None:
        heading_hints = _detect_source_heading_hints(elements, source, chat_json_fn)
    elif require_llm_structure:
        raise ValueError(f"{source} 文档结构识别必须配置 LLM")
    blocks: list[dict] = []
    section = ""
    chapter_id = f"{source}-chapter-front"
    heading_number = ""
    heading_text = ""
    heading_stack: list[tuple[int, str]] = []
    chapter_occurrences: dict[str, int] = {}
    block_occurrences: dict[str, int] = {}
    for body_index, el in enumerate(elements):
        tag = el.tag.split("}")[-1]
        is_heading = (
            body_index in heading_hints
            if heading_hints is not None
            else _is_heading(el)
        )
        if tag == "p" and is_heading:
            section = _text(el)
            heading_number, heading_text = _split_heading(section)
            level = (
                int(heading_hints[body_index]["level"])
                if heading_hints is not None
                else _heading_level(el)
            )
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            parent_headings = [item[1] for item in heading_stack]
            heading_stack.append((level, heading_text))
            # 章节 ID 只由标题语义路径生成；同名路径用本次文档内 occurrence
            # 消歧。它不是全局编号，也不随其它章节插入而整体顺延。
            semantic_path = " / ".join(parent_headings + [heading_text])
            normalized_path = re.sub(r"\s+", "", semantic_path)
            chapter_occurrences[normalized_path] = chapter_occurrences.get(normalized_path, 0) + 1
            occurrence = chapter_occurrences[normalized_path]
            identity = normalized_path if occurrence == 1 else f"{normalized_path}#{occurrence}"
            digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
            chapter_id = f"{source}-chapter-{digest}"
            continue
        if tag not in {"p", "tbl"}:
            continue
        text = _text(el)
        # Word has two image encodings in the wild.  Newer files use
        # DrawingML (w:drawing); older engineering documents frequently use
        # VML/OLE (w:object/v:imagedata).  Both are source media blocks and
        # must participate in the same caption/media group.  Looking only at
        # w:drawing silently drops legacy CAD screenshots and leaves their
        # captions orphaned in the generated taskbook.
        has_drawing = bool(
            el.findall(f".//{_W}drawing")
            or el.findall(f".//{_W}object")
            or el.xpath('.//*[local-name()="imagedata"]')
            or el.xpath('.//*[local-name()="shape"]')
        )
        if not text and not has_drawing:
            continue
        kind = "table" if tag == "tbl" else "paragraph"
        content_hash = _element_hash(el)
        block_identity = f"{chapter_id}|{kind}|{content_hash}"
        block_occurrences[block_identity] = block_occurrences.get(block_identity, 0) + 1
        block_occurrence = block_occurrences[block_identity]
        block_key = block_identity if block_occurrence == 1 else f"{block_identity}#{block_occurrence}"
        block_digest = hashlib.sha1(block_key.encode("utf-8")).hexdigest()[:12]
        block_id = f"{source}-{kind[0]}-{block_digest}"
        blocks.append({
            "id": block_id,
            "source": source,
            "source_path": str(Path(docx_path).resolve()),
            "chapter_id": chapter_id,
            "section": section or "（封面/前置区域）",
            "heading_number": heading_number,
            "heading_text": heading_text or section or "（封面/前置区域）",
            "parent_headings": parent_headings if section else [],
            "type": kind,
            "body_index": body_index,
            "text": text or f"[图片对象 body={body_index}]",
            "content_hash": content_hash,
            "has_drawing": has_drawing,
        })
    # Bind a figure object to an immediately adjacent caption.  The pair is
    # copied as one media group so a later route cannot separate the image
    # from its figure title.  The group is structural metadata, not generated
    # document text.
    by_index = {block["body_index"]: block for block in blocks}
    caption_re = re.compile(r"^(?:\u56fe\s*\d+|Fig(?:ure)?\.?\s*\d+)", re.I)
    for block in blocks:
        if not block.get("has_drawing"):
            continue
        before = by_index.get(block["body_index"] - 1)
        after = by_index.get(block["body_index"] + 1)

        def _is_caption(candidate: dict | None) -> bool:
            return bool(
                candidate
                and candidate.get("type") == "paragraph"
                and caption_re.search(str(candidate.get("text", "")).strip())
            )

        # Engineering DOCX files commonly store ``image -> caption`` without
        # a blank paragraph between consecutive figures.  In that layout the
        # paragraph immediately before the next image is the *previous*
        # image's caption.  Binding both adjacent captions to the next image
        # makes two media groups overlap and later duplicates the same picture
        # in two semantic slots.  Prefer the following caption; use a preceding
        # caption only for documents whose caption is genuinely before image.
        caption = after if _is_caption(after) else before if _is_caption(before) else None
        if caption is None:
            continue
        members = sorted([block, caption], key=lambda item: item["body_index"])
        group_id = f"media-group-{block['id']}"
        member_ids = [item["id"] for item in members]
        for member in members:
            member["media_group_id"] = group_id
            member["media_group_members"] = member_ids
    return blocks


def extract_template_slots(template_path: str) -> list[dict]:
    from jonhon_taskbook.template_metadata import parse_template_metadata
    from jonhon_taskbook.template_scanner import scan_template_tree

    metadata = {
        section["id"]: section
        for section in parse_template_metadata(template_path)
    }

    slots = []
    for node in scan_template_tree(template_path):
        heading = node["heading"]
        title = node["title"]
        if any(word in title for word in _SKIP_SLOT_WORDS):
            continue
        section = metadata.get(node["id"], {})
        slots.append({
            "id": node["id"],
            "heading": heading,
            "title": title,
            "semantic_path": node["semantic_path"],
            "level": node["level"],
            "parent_id": node["parent_id"],
            "paragraph_index": node["paragraph_index"],
            "occurrence": node["occurrence"],
            "instructions": list(section.get("instructions", [])),
            "has_table": bool(section.get("has_table")),
            "table_headers": list(section.get("table_headers", [])),
        })
    return slots


def _call(chat_json_fn: ChatJSON, system: str, payload: dict) -> dict:
    result = chat_json_fn(system, json.dumps(payload, ensure_ascii=False))
    return result if isinstance(result, dict) else {}


def _document_previews(blocks: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for block in blocks:
        grouped[block["source"]].append(block)
    return [
        {
            "label": label,
            "sample_source_ids": [b["id"] for b in items[:8]],
            "preview": "\n".join(b["text"][:180] for b in items[:8]),
        }
        for label, items in grouped.items()
    ]


def _verify_roles(blocks: list[dict], chat_json_fn: ChatJSON) -> dict:
    system = """你是受控技术文档的文件角色校验器。只做分类，不生成正文。
仅返回 JSON：{"documents":[{"label":"tech","role":"technical_requirement",
"confidence":0.0,"evidence_source_ids":["..."]}]}。role 只能是
technical_requirement/product_specification/template/unknown。"""
    raw = _call(chat_json_fn, system, {"node": "document_role", "documents": _document_previews(blocks)})
    valid_ids = {b["id"] for b in blocks}
    documents = []
    for item in raw.get("documents", []):
        if not isinstance(item, dict) or item.get("role") not in _ALLOWED_ROLES:
            continue
        documents.append({
            "label": str(item.get("label", "")),
            "role": item["role"],
            "confidence": _confidence(item.get("confidence", 0.0)),
            "evidence_source_ids": [x for x in item.get("evidence_source_ids", []) if x in valid_ids],
        })
    return {"documents": documents}


def _require_expected_document_roles(role_result: dict) -> None:
    """强制确认输入顺序：tech 是需求文件，spec 是产品规范。"""
    expected = {
        "tech": "technical_requirement",
        "spec": "product_specification",
    }
    by_label: dict[str, list[dict]] = defaultdict(list)
    for item in role_result.get("documents", []):
        by_label[str(item.get("label", ""))].append(item)
    problems = []
    for label, role in expected.items():
        items = by_label.get(label, [])
        if len(items) != 1:
            problems.append(f"{label} 角色结果数量={len(items)}")
            continue
        item = items[0]
        if item.get("role") != role:
            problems.append(f"{label} 被识别为 {item.get('role')}")
        if float(item.get("confidence", 0.0)) < 0.60:
            problems.append(f"{label} 角色置信度低于0.60")
        if not item.get("evidence_source_ids"):
            problems.append(f"{label} 缺少原文证据ID")
    if problems:
        raise ValueError(
            "输入文件角色语义门禁失败: " + "；".join(problems)
            + "。禁止交换技术要求与产品规范，或依据文件名猜测角色。"
        )


def _identify_scope(blocks: list[dict], chat_json_fn: ChatJSON) -> dict:
    system = """你是产品与型号作用域识别器。只选择原文中的型号及证据ID，不写正文。
仅返回 JSON：{"target_models":["原文型号"],"evidence_source_ids":["..."],
"confidence":0.0}。型号必须逐字出现在给定原文。"""
    samples = [
        {
            "source_id": b["id"],
            "source": b["source"],
            "heading_text": b.get("heading_text", ""),
            "parent_headings": b.get("parent_headings", []),
            "text": b["text"][:260],
        }
        for b in blocks[:80]
    ]
    raw = _call(chat_json_fn, system, {"node": "product_scope", "blocks": samples})
    corpus = "\n".join(b["text"] for b in blocks)
    valid_ids = {b["id"] for b in blocks}
    models = [str(x).strip() for x in raw.get("target_models", []) if str(x).strip() in corpus]
    return {
        "target_models": list(dict.fromkeys(models)),
        "evidence_source_ids": [x for x in raw.get("evidence_source_ids", []) if x in valid_ids],
        "confidence": _confidence(raw.get("confidence", 0.0)),
    }


def _section_outline(blocks: list[dict]) -> tuple[list[dict], dict[str, list[str]]]:
    """按章节实例分组；同名标题的不同出现位置不得被合并。"""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for block in blocks:
        groups[(block["source"], block["chapter_id"])].append(block)
    outline, members = [], {}
    for index, ((source, chapter_id), items) in enumerate(groups.items()):
        sid = f"srcsec-{index:03d}"
        members[sid] = [b["id"] for b in items]
        first = items[0]
        title = str(first.get("heading_text") or "（封面/前置区域）")
        parents = list(first.get("parent_headings") or [])
        outline.append({
            "source_section_id": sid,
            "source": source,
            "source_chapter_id": chapter_id,
            "heading": title,
            "parent_headings": parents,
            "semantic_path": " / ".join([*parents, title]),
            "preview": " | ".join(b["text"][:100] for b in items[:3]),
            "block_count": len(items),
        })
    return outline, members


def _map_sections(
    slots: list[dict], outline: list[dict], chat_json_fn: ChatJSON,
    *, allow_delete: bool = False,
) -> list[dict]:
    system = """你是模板槽位与来源章节的语义映射器。只返回映射ID，不写正文。
target_slot 只能使用模板标题树提供的 slot-* 节点 ID，不得根据章节号猜测位置。
edit_action 只能为 append、replace、insert_before、insert_after、preserve、delete；
insert_before/insert_after 必须给出 anchor_slot。delete 只是建议，执行端仍需显式规则授权。
仅返回 JSON：{"mappings":[{"target_slot":"slot-...","source_section_ids":["srcsec-001"],
"edit_action":"append","anchor_slot":"","confidence":0.0}]}。无证据时 source_section_ids 为空。"""
    payload = {
        "node": "section_mapping",
        "template_slots": slots,
        "source_sections": outline,
    }
    # Optional advisory retrieval: it narrows the model's attention without
    # becoming an authority.  The live slot list and the JSON validator remain
    # the only legal routing targets.
    if os.getenv("JTB_SEMANTIC_RETRIEVAL", "1").strip().lower() in {
        "1", "true", "yes", "on"
    }:
        try:
            from .semantic_retrieval import build_slot_candidates
            payload["retrieval_candidates"] = build_slot_candidates(slots, outline)
        except Exception:
            # Retrieval is an enhancement; a provider outage must not turn
            # into a hidden keyword/number fallback.
            payload["retrieval_candidates"] = {}
    raw = _call(chat_json_fn, system, payload)
    valid_slots = {s["id"] for s in slots}
    valid_sections = {s["source_section_id"] for s in outline}
    mappings = []
    for item in raw.get("mappings", []):
        if not isinstance(item, dict) or item.get("target_slot") not in valid_slots:
            continue
        edit_action = str(item.get("edit_action", "append"))
        # 普通生成只负责把源文档原样路由到模板，不能因为模板说明文字
        # 中出现“请删除”就自动删掉模板章节。删除必须来自用户确认的
        # 模板编辑计划，并由独立执行器显式授权。
        if edit_action == "delete" and not allow_delete:
            edit_action = "preserve"
        if edit_action not in _ALLOWED_EDIT_ACTIONS:
            edit_action = "append"
        anchor_slot = str(item.get("anchor_slot", ""))
        if edit_action in {"insert_before", "insert_after"} and anchor_slot not in valid_slots:
            continue
        mappings.append({
            "target_slot": item["target_slot"],
            "source_section_ids": [x for x in item.get("source_section_ids", []) if x in valid_sections],
            "edit_action": edit_action,
            "anchor_slot": anchor_slot,
            "confidence": _confidence(item.get("confidence", 0.0)),
        })
    return mappings


def _route_blocks(
    slots: list[dict], blocks: list[dict], mappings: list[dict], members: dict[str, list[str]],
    chat_json_fn: ChatJSON,
) -> list[dict]:
    slot_by_id = {s["id"]: s for s in slots}
    block_by_id = {b["id"]: b for b in blocks}
    decisions = []
    for mapping in mappings:
        slot_id = mapping["target_slot"]
        edit_action = mapping.get("edit_action", "append")
        if edit_action in {"preserve", "delete"}:
            decisions.append({
                "target_slot": slot_id,
                "source_ids": [],
                "operation": "copy_exact",
                "edit_action": edit_action,
                "anchor_slot": mapping.get("anchor_slot", ""),
                "confidence": mapping.get("confidence", 0.0),
                "reason": "模板语义 CRUD 决策",
            })
            continue
        candidate_ids = []
        for sec_id in mapping["source_section_ids"]:
            candidate_ids.extend(members.get(sec_id, []))
        candidates = [block_by_id[x] for x in dict.fromkeys(candidate_ids) if x in block_by_id][:60]
        if not candidates:
            continue
        system = """你是原文块路由器。你只能选择 source_id 放入目标槽位，不得写、改写、
概括任何正文。仅返回 JSON：{"decisions":[{"target_slot":"...",
"source_ids":["..."],"operation":"copy_exact","confidence":0.0,"reason":"简短判断"}]}。
operation 必须是 copy_exact；target_slot 是语义标题树节点 ID，不是章节号。"""
        raw = _call(chat_json_fn, system, {
            "node": "block_routing",
            "target_slot": slot_by_id[slot_id],
            "candidate_blocks": [
                {
                    "source_id": b["id"],
                    "source": b["source"],
                    "heading_text": b.get("heading_text", ""),
                    "parent_headings": b.get("parent_headings", []),
                    "type": b["type"],
                    "text": b["text"][:350],
                }
                for b in candidates
            ],
        })
        valid_ids = {b["id"] for b in candidates}
        for item in raw.get("decisions", []):
            if not isinstance(item, dict) or item.get("target_slot") != slot_id:
                continue
            if item.get("operation", "copy_exact") != "copy_exact":
                continue
            ids = [x for x in item.get("source_ids", []) if x in valid_ids]
            if not ids:
                continue
            decisions.append({
                "target_slot": slot_id,
                "source_ids": list(dict.fromkeys(ids)),
                "operation": "copy_exact",
                "edit_action": edit_action,
                "anchor_slot": mapping.get("anchor_slot", ""),
                "confidence": _confidence(item.get("confidence", 0.0)),
                "reason": str(item.get("reason", ""))[:240],
            })
    return decisions


def _route_blocks_parallel(
    slots: list[dict], blocks: list[dict], mappings: list[dict],
    members: dict[str, list[str]], chat_json_fn: ChatJSON,
) -> list[dict]:
    """并发执行独立的 block_routing 节点，并按模板映射顺序合并结果。

    每个节点只返回 source_id -> slot 的 copy_exact 决策，不写正文；并发不会
    改变文档操作顺序，只缩短远端模型逐槽位等待时间。
    """
    slot_by_id = {s["id"]: s for s in slots}
    block_by_id = {b["id"]: b for b in blocks}

    def route_one(mapping: dict) -> list[dict]:
        slot_id = mapping["target_slot"]
        edit_action = mapping.get("edit_action", "append")
        if edit_action in {"preserve", "delete"}:
            return [{
                "target_slot": slot_id,
                "source_ids": [],
                "operation": "copy_exact",
                "edit_action": edit_action,
                "anchor_slot": mapping.get("anchor_slot", ""),
                "confidence": mapping.get("confidence", 0.0),
                "reason": "template semantic CRUD decision",
            }]
        candidate_ids: list[str] = []
        for sec_id in mapping.get("source_section_ids", []):
            candidate_ids.extend(members.get(sec_id, []))
        candidates = [
            block_by_id[x] for x in dict.fromkeys(candidate_ids)
            if x in block_by_id
        ][:60]
        if not candidates or slot_id not in slot_by_id:
            return []
        system = (
            "You route source blocks to a semantic template slot. "
            "Return JSON only: {\"decisions\":[{\"target_slot\":\"...\","
            "\"source_ids\":[\"...\"],\"operation\":\"copy_exact\","
            "\"confidence\":0.0,\"reason\":\"short\"}]}. "
            "Never write or rewrite正文; operation must be copy_exact. "
            "target_slot is a semantic heading-tree node id, never a chapter number."
        )
        raw = _call(chat_json_fn, system, {
            "node": "block_routing",
            "target_slot": slot_by_id[slot_id],
            "candidate_blocks": [
                {
                    "source_id": b["id"],
                    "source": b["source"],
                    "heading_text": b.get("heading_text", ""),
                    "parent_headings": b.get("parent_headings", []),
                    "type": b["type"],
                    "text": b["text"][:350],
                }
                for b in candidates
            ],
        })
        valid_ids = {b["id"] for b in candidates}
        routed: list[dict] = []
        for item in raw.get("decisions", []):
            if not isinstance(item, dict) or item.get("target_slot") != slot_id:
                continue
            if item.get("operation", "copy_exact") != "copy_exact":
                continue
            ids = [x for x in item.get("source_ids", []) if x in valid_ids]
            if not ids:
                continue
            routed.append({
                "target_slot": slot_id,
                "source_ids": list(dict.fromkeys(ids)),
                "operation": "copy_exact",
                "edit_action": edit_action,
                "anchor_slot": mapping.get("anchor_slot", ""),
                "confidence": _confidence(item.get("confidence", 0.0)),
                "reason": str(item.get("reason", ""))[:240],
            })
        return routed

    indexed = list(enumerate(mappings))
    if not indexed:
        return []
    routed_by_index: dict[int, list[dict]] = {}
    with ThreadPoolExecutor(
        max_workers=min(4, len(indexed)), thread_name_prefix="semantic-route"
    ) as pool:
        futures = {
            pool.submit(route_one, mapping): index
            for index, mapping in indexed
        }
        for future in as_completed(futures):
            routed_by_index[futures[future]] = future.result()
    decisions: list[dict] = []
    for index, _mapping in indexed:
        decisions.extend(routed_by_index.get(index, []))
    return decisions


def build_semantic_plan(
    tech_path: str, spec_path: str, template_path: str, plan_path: str | None = None,
    chat_json_fn: ChatJSON | None = None,
    requirement_classification: dict | None = None,
    category_mapping_path: str | None = None,
) -> dict:
    """依次执行角色、作用域、章节、块路由四个 LLM 节点。"""
    if chat_json_fn is None:
        from jonhon_taskbook.llm_client import chat_json as chat_json_fn
    cache_key = _plan_cache_key(
        tech_path,
        spec_path,
        template_path,
        category_mapping_path=category_mapping_path,
        requirement_classification=requirement_classification,
    )
    cache_path = (
        Path(plan_path).parent / f".{cache_key}.semantic_cache.json"
        if plan_path else None
    )
    if cache_path and cache_path.is_file():
        try:
            envelope = json.loads(cache_path.read_text(encoding="utf-8"))
            if envelope.get("cache_key") == cache_key:
                from jonhon_taskbook.semantic_schema import SemanticPlan
                cached = SemanticPlan.model_validate(envelope["plan"]).model_dump(mode="json")
                # The cache is content-addressed, so it may be reused by a
                # later web job whose uploads live under a different jid.
                # Rebind provenance paths to this job before execution; the
                # route decisions/source IDs remain unchanged.
                for block in cached.get("source_blocks", []):
                    block["source_path"] = str(
                        Path(tech_path if block.get("source") == "tech" else spec_path).resolve()
                    )
                Path(plan_path).write_text(
                    json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return cached
        except (OSError, ValueError, TypeError, KeyError):
            pass
    # 先用本地结构读取全部可见内容，只用于文件角色校验；角色通过后再让
    # LLM 识别真实标题边界，避免依赖显示章节号或固定 Word 模板样式。
    preview_blocks = (
        extract_source_blocks(tech_path, "tech")
        + extract_source_blocks(spec_path, "spec")
    )
    slots = extract_template_slots(template_path)
    roles = _verify_roles(preview_blocks, chat_json_fn)
    _require_expected_document_roles(roles)
    classified_tech_blocks = [
        dict(block)
        for block in (requirement_classification or {}).get("source_blocks", [])
        if isinstance(block, dict) and block.get("source") == "tech"
    ]
    # The requirement classifier may have partitioned a mixed paragraph into
    # exact source spans.  Reuse those validated spans here so the semantic
    # planner and deterministic fill stage operate on the same evidence IDs.
    # Product-specification blocks remain independently structure-scanned.
    blocks = (
        classified_tech_blocks
        or extract_source_blocks(
            tech_path, "tech", chat_json_fn=chat_json_fn, require_llm_structure=True
        )
    ) + extract_source_blocks(
        spec_path, "spec", chat_json_fn=chat_json_fn, require_llm_structure=True
    )
    scope = _identify_scope(blocks, chat_json_fn)
    outline, members = _section_outline(blocks)
    mappings = _map_sections(slots, outline, chat_json_fn, allow_delete=False)
    decisions = _route_blocks_parallel(slots, blocks, mappings, members, chat_json_fn)
    # Constrain every raw model candidate before resolving duplicate routes.
    # This prevents an unrelated-slot tie (for example, one performance
    # indicator suggested for several template sections) from being guessed.
    decisions, authority_audit = _enforce_requirement_route_authority(
        decisions,
        slots,
        blocks,
        requirement_classification,
        category_mapping_path,
    )
    decisions, model_route_audit = _canonicalize_routes(decisions, slots, blocks)
    # Canonicalization can select a child/parent representation of a mixed
    # paragraph. Re-apply the same category authority so that structural
    # tie-breaking can never undo the approved 19-category destination.
    decisions, second_authority_audit = _enforce_requirement_route_authority(
        decisions,
        slots,
        blocks,
        requirement_classification,
        category_mapping_path,
    )
    decisions, completeness_audit = _backfill_classified_routes(
        decisions,
        slots,
        blocks,
        requirement_classification,
        category_mapping_path,
    )
    decisions, structured_writer_audit = _suppress_structured_writer_sources(
        decisions,
        requirement_classification,
        category_mapping_path,
    )
    decisions, route_audit = _canonicalize_routes(decisions, slots, blocks)
    route_audit["model_resolved_parent_child"] = model_route_audit.get(
        "resolved_parent_child", []
    )
    authority_audit["classification_target_overrides"].extend(
        second_authority_audit.get("classification_target_overrides", [])
    )
    authority_audit["classification_constrained_routes"].extend(
        second_authority_audit.get("classification_constrained_routes", [])
    )
    authority_audit["restricted_product_specification_sources"] = sorted(
        dict.fromkeys(
            authority_audit.get("restricted_product_specification_sources", [])
            + second_authority_audit.get(
                "restricted_product_specification_sources", []
            )
        )
    )
    route_audit.update(authority_audit)
    route_audit.update(completeness_audit)
    route_audit.update(structured_writer_audit)
    plan = {
        "schema_version": "1.0",
        "policy": {
            "llm_may_generate_text": False,
            "allowed_operations": ["copy_exact"],
            "allowed_edit_actions": sorted(_ALLOWED_EDIT_ACTIONS),
            "delete_requires_explicit_rule": True,
        },
        "roles": roles,
        "scope": scope,
        "slots": slots,
        "source_blocks": blocks,
        "section_mappings": mappings,
        "decisions": decisions,
        "route_audit": route_audit,
    }
    from jonhon_taskbook.semantic_schema import SemanticPlan
    plan = SemanticPlan.model_validate(plan).model_dump(mode="json")
    if plan_path:
        cache_path.write_text(
            json.dumps({"cache_key": cache_key, "plan": plan}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        Path(plan_path).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def _load_body(path: str):
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    return root, root.find(f"{_W}body")


def _slot_has_content(body, heading_el) -> bool:
    started = False
    for el in body:
        if el is heading_el:
            started = True
            continue
        if not started:
            continue
        if _is_heading(el):
            break
        if el.tag == f"{_W}tbl" or _text(el):
            return True
    return False


def _rewrite_document_xml(docx_path: str, xml: bytes) -> None:
    tmp = docx_path + ".semantic.tmp"
    with zipfile.ZipFile(docx_path, "r") as zin, zipfile.ZipFile(
        tmp, "w", compression=zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            zout.writestr(item, xml if item.filename == "word/document.xml" else zin.read(item.filename))
    shutil.move(tmp, docx_path)


_SIGNATURE_MARKERS = (
    "使用单位签署", "研制或试制单位签署", "研制单位签署",
    "签字/盖章", "签字盖章", "本协议一式", "年月日",
)


def _is_protected_front_matter(block: dict) -> bool:
    """Keep cover/change-log evidence in their controlled template zones."""
    text = _norm(" ".join(
        str(block.get(key, ""))
        for key in ("section", "heading_text", "text")
    ))
    section = _norm(str(block.get("section", "")))
    heading = _norm(str(block.get("heading_text", "")))
    return (
        "\u5c01\u9762" in text
        or "\u524d\u7f6e" in text
        or "\u53d8\u66f4\u8bb0\u5f55" in text
        or "\u7248\u672c\u7ae0\u6761\u7f16\u53f7" in text
        or any(marker in text for marker in _SIGNATURE_MARKERS)
        # The source cover table is labelled "技术要求" rather than "封面".
        # Only the administrative table is protected; body tables under a
        # numbered requirement chapter remain routable.
        or (
            block.get("type") == "table"
            and section == "\u6280\u672f\u8981\u6c42"
            and heading == "\u6280\u672f\u8981\u6c42"
        )
    )


def protected_source_block_ids(blocks: list[dict]) -> set[str]:
    """Return administrative/signature blocks that must never enter正文.

    Floating seals and handwritten signatures are commonly anchored in a
    separate image-only paragraph immediately after the signature table.  The
    image paragraph contains no marker text of its own, so protect that
    structural tail together with the marked table.  This uses block type,
    section identity and adjacency only for exclusion; it never routes
    technical content by source order.
    """
    protected: set[str] = set()
    signature_tail_section = ""
    for block in blocks:
        block_id = str(block.get("id", ""))
        marker_text = _norm(" ".join(
            str(block.get(key, ""))
            for key in ("section", "heading_text", "text")
        ))
        section = _norm(str(block.get("section", "")))
        if _is_protected_front_matter(block):
            if block_id:
                protected.add(block_id)
            if any(marker in marker_text for marker in _SIGNATURE_MARKERS):
                signature_tail_section = section
            continue

        is_image_only = (
            block.get("type") == "image"
            or bool(block.get("image_refs"))
            or "[图片对象" in str(block.get("text", ""))
        )
        if signature_tail_section and section == signature_tail_section and is_image_only:
            if block_id:
                protected.add(block_id)
            continue
        signature_tail_section = ""
    return protected


def apply_semantic_plan(
    out_path: str, plan: dict, evidence_path: str | None = None,
    min_confidence: float = 0.60, only_empty: bool = True,
    allow_delete: bool = False,
) -> dict:
    """按语义标题树确定性执行 CRUD，并重绑定图片/样式/编号关系。"""
    from docx import Document
    from jonhon_taskbook.template_scanner import scan_template_tree
    Composer = _composer_class()

    output_doc = Document(out_path)
    composer = Composer(output_doc, preserve_styles=True)
    body = output_doc.element.body
    slot_by_id = {s["id"]: s for s in plan.get("slots", [])}
    block_by_id = {b["id"]: b for b in plan.get("source_blocks", [])}
    protected_block_ids = protected_source_block_ids(plan.get("source_blocks", []))
    headings = {_text(el): el for el in body if _is_heading(el)}
    live_tree = scan_template_tree(out_path)
    live_heading_by_id = {
        node["id"]: output_doc.paragraphs[node["paragraph_index"]]._p
        for node in live_tree
        if node["paragraph_index"] < len(output_doc.paragraphs)
    }
    # Do not use id(lxml_proxy) as an XML-node identity.  Sibling traversal
    # can materialize a new Python proxy for the same underlying node.
    live_level_by_element = {
        live_heading_by_id[node["id"]]: node["level"]
        for node in live_tree
        if node["id"] in live_heading_by_id
    }
    source_cache: dict[str, Any] = {}
    prepared_sources: set[str] = set()
    inserted, skipped = [], []
    # A source block is an atomic evidence unit.  It may be classified into
    # several semantic roles, but it must be copied into the generated
    # document only once.  This is deliberately keyed by source_id/content,
    # never by a chapter number.
    routed_source_ids: set[str] = set()
    existing_content_hashes = {
        _element_hash(element)
        for element in body
        if element.tag in {f"{_W}p", f"{_W}tbl"}
    }
    # ``fill`` can already have copied an image/caption group before the
    # semantic executor runs. Relationship IDs are regenerated during that
    # copy, so XML hashes alone cannot recognize the same image.
    existing_image_hashes: set[str] = set()
    for element in body:
        existing_image_hashes.update(
            _referenced_image_hashes(output_doc, element)
        )

    def _heading_element(slot_id: str):
        element = live_heading_by_id.get(slot_id)
        if element is not None:
            return element
        slot = slot_by_id.get(slot_id)
        return headings.get(slot.get("heading", "")) if slot else None

    def _section_tail(heading_el, level: int):
        tail = heading_el
        current = heading_el.getnext()
        while current is not None:
            current_level = live_level_by_element.get(current, 0)
            if current_level and current_level <= level:
                break
            tail = current
            current = current.getnext()
        return tail

    def _section_evidence(heading_el, level: int):
        """Return hashes that are already present in this semantic slot.

        Evidence is deliberately scoped to the target section.  A source
        paragraph that exists in some *other* chapter must not suppress the
        required copy into the selected slot; global de-duplication made a
        wrong placement look like successful coverage.
        """
        content_hashes: set[str] = set()
        image_hashes: set[str] = set()
        current = heading_el.getnext()
        while current is not None:
            current_level = live_level_by_element.get(current, 0)
            if current_level and current_level <= level:
                break
            if current.tag in {f"{_W}p", f"{_W}tbl"}:
                content_hashes.add(_element_hash(current))
                image_hashes.update(
                    _referenced_image_hashes(output_doc, current)
                )
            current = current.getnext()
        return content_hashes, image_hashes

    def _clear_section(heading_el, level: int, include_heading: bool = False):
        current = heading_el if include_heading else heading_el.getnext()
        removed = 0
        while current is not None:
            next_el = current.getnext()
            current_level = live_level_by_element.get(current, 0)
            if current is not heading_el and current_level and current_level <= level:
                break
            parent = current.getparent()
            if parent is not None:
                parent.remove(current)
                removed += 1
            current = next_el
        return removed

    for decision in plan.get("decisions", []):
        slot_id = decision.get("target_slot")
        edit_action = decision.get("edit_action", "append")
        slot = slot_by_id.get(slot_id)
        heading_el = _heading_element(slot_id)
        if heading_el is None:
            skipped.append({"target_slot": slot_id, "reason": "target_heading_not_found"})
            continue
        has_child_slots = any(node.get("parent_id") == slot_id for node in live_tree)
        if has_child_slots and edit_action in {"append", "replace"}:
            skipped.append({"target_slot": slot_id, "reason": "parent_section_has_child_slots"})
            continue
        # ``fill`` 会先按受控分类写入一部分原文，随后本执行器按 source_id
        # 复核和补齐。因此不能因为目标章节“已有任意内容”就整章跳过：
        # 那会让同一批输入在不同运行中随机缺块。受控模式下把 replace
        # 降级为 append，后面的原文哈希/图片哈希去重负责：
        #   1. 已存在的原文记为已覆盖；
        #   2. 缺失的原文才追加；
        #   3. 永不清空已有正确正文。
        if (
            only_empty
            and edit_action == "replace"
            and _slot_has_content(body, heading_el)
        ):
            edit_action = "append"
        # preserve 是明确的“保持模板原样”操作，不写入任何来源内容；它不应
        # 因模型对该无源槽位的置信度低而阻断整份交付。
        if edit_action == "preserve":
            inserted.append({
                "target_slot": slot_id, "source_id": "", "operation": "copy_exact",
                "edit_action": "preserve", "content_hash": "",
            })
            continue
        operation_is_valid = decision.get("operation") == "copy_exact"
        confidence_is_valid = _confidence(decision.get("confidence")) >= min_confidence
        if not operation_is_valid or not confidence_is_valid:
            # fill() runs before this executor.  A deterministic category writer may
            # therefore have copied the exact source block into the target section
            # already.  In that case a later low-confidence LLM recommendation must
            # not turn an already-complete document into a false gate failure.  This
            # is evidence based: only the same source content hash in the requested
            # target section is accepted.  Missing or differently placed content
            # remains blocking.
            level = int(
                (
                    next((x for x in live_tree if x["id"] == slot_id), {})
                    or {}
                ).get("level", 1)
            )
            target_content_hashes, _ = _section_evidence(heading_el, level)
            requested_source_ids = list(decision.get("source_ids", []))
            requested_hashes = [
                block_by_id[source_id].get("content_hash")
                for source_id in requested_source_ids
                if source_id in block_by_id
                and block_by_id[source_id].get("content_hash")
            ]
            if (
                operation_is_valid
                and requested_hashes
                and len(requested_hashes) == len(requested_source_ids)
                and all(
                    content_hash in target_content_hashes
                    for content_hash in requested_hashes
                )
            ):
                routed_source_ids.update(requested_source_ids)
                skipped.append(
                    {
                        "target_slot": slot_id,
                        "source_ids": requested_source_ids,
                        "reason": "source_already_present",
                        "content_hashes": requested_hashes,
                    }
                )
                continue
            skipped.append({"target_slot": slot_id, "reason": "invalid_operation_or_low_confidence"})
            continue
        # 普通生成只能向模板语义槽位补充原文，不能用模型提出的
        # ``replace`` 清空一个仍然包含子标题的父章节。否则父章节被清空时，
        # 子标题（例如“技术指标”“接口尺寸要求”）也会从 OOXML 树中移除；
        # 后续子槽位虽然仍有 source_id，却只能插入到已经脱离文档的旧元素，
        # 最终表现为“语义决策存在，但输入覆盖率缺失”。模板编辑器的显式
        # rename/add/move/delete 仍走 template_outline_editor，不经过这里。
        if edit_action == "replace" and any(
            node.get("parent_id") == slot_id for node in live_tree
        ):
            skipped.append({
                "target_slot": slot_id,
                "reason": "parent_section_has_child_slots",
            })
            continue
        if edit_action == "delete":
            if not allow_delete or _confidence(decision.get("confidence")) < 0.95:
                skipped.append({"target_slot": slot_id, "reason": "delete_not_authorized"})
                continue
            level = int((next((x for x in live_tree if x["id"] == slot_id), {}) or {}).get("level", 1))
            removed = _clear_section(heading_el, level, include_heading=True)
            inserted.append({
                "target_slot": slot_id, "source_id": "", "operation": "copy_exact",
                "edit_action": "delete", "content_hash": "", "removed_elements": removed,
            })
            continue
        level = int((next((x for x in live_tree if x["id"] == slot_id), {}) or {}).get("level", 1))
        insertion_mode = "after"
        if edit_action == "replace":
            _clear_section(heading_el, level)
            anchor = heading_el
        elif edit_action == "append":
            anchor = _section_tail(heading_el, level)
        elif edit_action in {"insert_before", "insert_after"}:
            anchor_slot = decision.get("anchor_slot") or slot_id
            anchor_heading = _heading_element(anchor_slot)
            if anchor_heading is None:
                skipped.append({"target_slot": slot_id, "reason": "anchor_heading_not_found"})
                continue
            if edit_action == "insert_before":
                anchor = anchor_heading
                insertion_mode = "before"
            else:
                anchor_level = int((next((x for x in live_tree if x["id"] == anchor_slot), {}) or {}).get("level", 1))
                anchor = _section_tail(anchor_heading, anchor_level)
        else:
            skipped.append({"target_slot": slot_id, "reason": "invalid_edit_action"})
            continue
        target_content_hashes, target_image_hashes = _section_evidence(
            heading_el, level
        )
        requested_source_ids = list(decision.get("source_ids", []))
        expanded_source_ids = list(requested_source_ids)
        for requested_id in requested_source_ids:
            requested_block = block_by_id.get(requested_id, {})
            expanded_source_ids.extend(requested_block.get("media_group_members", []))
        expanded_source_ids = sorted(
            dict.fromkeys(expanded_source_ids),
            key=lambda source_id: (
                block_by_id.get(source_id, {}).get("body_index", 10**9),
                block_by_id.get(source_id, {}).get("source_span_start", -1),
                block_by_id.get(source_id, {}).get("fragment_index", -1),
            ),
        )
        for source_id in expanded_source_ids:
            if source_id in routed_source_ids:
                skipped.append({
                    "target_slot": slot_id,
                    "source_id": source_id,
                    "reason": "source_already_routed",
                })
                continue
            block = block_by_id.get(source_id)
            if not block:
                skipped.append({"target_slot": slot_id, "source_id": source_id, "reason": "unknown_source_id"})
                continue
            if source_id in protected_block_ids:
                skipped.append({
                    "target_slot": slot_id,
                    "source_id": source_id,
                    "reason": "protected_front_matter",
                })
                continue
            source_path = block["source_path"]
            if source_path not in source_cache:
                source_cache[source_path] = Document(source_path)
            source_doc = source_cache[source_path]
            src_body = source_doc.element.body
            index = int(block["body_index"])
            if index >= len(src_body):
                skipped.append({"target_slot": slot_id, "source_id": source_id, "reason": "source_index_out_of_range"})
                continue
            src_el = src_body[index]
            expected_element_hash = (
                block.get("element_content_hash")
                if block.get("is_fragment")
                else block.get("content_hash")
            )
            if _element_hash(src_el) != expected_element_hash:
                skipped.append({"target_slot": slot_id, "source_id": source_id, "reason": "source_hash_mismatch"})
                continue
            source_image_hashes = _referenced_image_hashes(source_doc, src_el)
            if (
                source_image_hashes
                and source_image_hashes.issubset(target_image_hashes)
            ):
                routed_source_ids.add(source_id)
                skipped.append({
                    "target_slot": slot_id,
                    "source_id": source_id,
                    "reason": "source_image_already_present",
                    "image_hashes": sorted(source_image_hashes),
                })
                continue
            source_hash = block["content_hash"]
            if source_hash in target_content_hashes:
                routed_source_ids.add(source_id)
                skipped.append({
                    "target_slot": slot_id,
                    "source_id": source_id,
                    "reason": "source_already_present",
                    "content_hash": source_hash,
                })
                continue
            try:
                new_el = copy_source_element_exact(src_el, block)
            except ValueError as exc:
                skipped.append({
                    "target_slot": slot_id,
                    "source_id": source_id,
                    "reason": "source_fragment_mismatch",
                    "detail": str(exc),
                })
                continue
            # 复用 docxcompose 经验证的关系迁移逻辑：图片按 SHA-1 去重并
            # 重建 rId，同时迁移超链接、样式、编号、图表、形状和脚注。
            composer.reset_reference_mapping()
            composer._create_style_id_mapping(source_doc)
            composer.add_referenced_parts(source_doc.part, output_doc.part, new_el)
            composer.add_styles(source_doc, new_el)
            composer.add_numberings(source_doc, new_el)
            composer.add_images(source_doc, new_el)
            composer.add_diagrams(source_doc, new_el)
            composer.add_shapes(source_doc, new_el)
            composer.add_footnotes(source_doc, new_el)
            composer.remove_header_and_footer_references(source_doc, new_el)
            if insertion_mode == "before":
                anchor.addprevious(new_el)
            else:
                anchor.addnext(new_el)
                anchor = new_el
            prepared_sources.add(source_path)
            routed_source_ids.add(source_id)
            existing_content_hashes.add(source_hash)
            existing_image_hashes.update(source_image_hashes)
            target_content_hashes.add(source_hash)
            target_image_hashes.update(source_image_hashes)
            inserted.append({
                "target_slot": slot_id,
                "source_id": source_id,
                "parent_source_id": block.get("parent_source_id", ""),
                "source_span_start": block.get("source_span_start", -1),
                "source_span_end": block.get("source_span_end", -1),
                "operation": "copy_exact",
                "edit_action": edit_action,
                "content_hash": block["content_hash"],
            })

    if inserted:
        for source_path in prepared_sources:
            composer.add_styles_from_other_parts(source_cache[source_path])
        composer.renumber_bookmarks()
        composer.renumber_docpr_ids()
        composer.renumber_nvpicpr_ids()
        composer.save(out_path)
    # fill() 可能已经把一个子槽位的内容合并到父槽位，或按领域策略
    # 移除了该提示槽位；再次执行同一份语义计划时，这不是未处理正文。
    # 删除建议在普通生成中也必须保留模板，只有模板编辑器显式授权才执行。
    safe_skip_reasons = {
        "target_not_empty",
        "target_heading_not_found",
        "parent_section_has_child_slots",
        "delete_not_authorized",
        "source_already_routed",
        "source_already_present",
        "source_image_already_present",
        "protected_front_matter",
    }
    blocking_skipped = [
        item for item in skipped
        if item.get("reason") not in safe_skip_reasons
    ]
    verified_reasons = {
        "source_already_present",
        "source_image_already_present",
    }

    # ``fill`` is the primary assembler.  It can write an exact source block
    # before this semantic executor runs, in which case a later copy attempt is
    # correctly skipped as already present.  Expand both the singular
    # ``source_id`` and the batch ``source_ids`` forms into an explicit evidence
    # list so downstream gates do not have to infer successful coverage from a
    # skip reason.
    verified_present: list[dict] = []
    verified_keys: set[tuple[str, str, str]] = set()
    for item in skipped:
        reason = str(item.get("reason", ""))
        if reason not in verified_reasons:
            continue
        source_ids = item.get("source_ids") or [item.get("source_id")]
        for raw_source_id in source_ids:
            source_id = str(raw_source_id or "")
            if not source_id:
                continue
            target_slot = str(item.get("target_slot", ""))
            key = (source_id, target_slot, reason)
            if key in verified_keys:
                continue
            verified_keys.add(key)
            verified_present.append({
                "source_id": source_id,
                "target_slot": target_slot,
                "reason": reason,
            })

    safe_skipped = [
        item for item in skipped
        if item.get("reason") in safe_skip_reasons
        and item.get("reason") not in verified_reasons
    ]
    inserted_source_evidence = [
        item for item in inserted
        if isinstance(item, dict) and item.get("source_id")
    ]
    evidence = {
        "schema_version": "semantic-evidence-v2",
        "status": "blocked" if blocking_skipped else "complete",
        "policy": plan.get("policy", {}),
        "inserted": inserted,
        "verified_present": verified_present,
        "safe_skipped": safe_skipped,
        "skipped": skipped,
        "blocking_skipped": blocking_skipped,
        "counts": {
            "inserted": len(inserted_source_evidence),
            "verified_present": len(verified_present),
            "safe_skipped": len(safe_skipped),
            "blocking_skipped": len(blocking_skipped),
            "control_operations": len(inserted) - len(inserted_source_evidence),
        },
        "passed": (
            all(x["operation"] == "copy_exact" for x in inserted)
            and not blocking_skipped
        ),
    }
    if evidence_path:
        Path(evidence_path).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return evidence


def review_semantic_decisions(plan: dict, evidence: dict, chat_json_fn: ChatJSON | None = None) -> dict:
    """LLM 只提供语义复核建议，不直接决定交付门禁。

    复核模型没有独立的模板/源文档证据来证明一个槽位一定误路由，尤其
    无法区分“整章原样搬运”和“错误地把多个来源混到一个槽位”。因此它
    只能写入审计 sidecar；源 ID 合法性、目标槽位存在性、实际 OOXML 复制、
    覆盖率和结构完整性仍由确定性执行器及 QA 门禁负责。
    """
    executed_source_ids = {
        str(item.get("source_id"))
        for item in evidence.get("inserted", [])
        if isinstance(item, dict) and item.get("source_id")
    }
    # fill() 已经完成正文装配时，语义执行器会把重复计划安全跳过。
    # 这些未执行的计划不应再交给模型复核，否则模型可能对一个根本没有
    # 落到文档里的候选路由产生无效警告。没有实际插入就没有可复核对象。
    if not executed_source_ids:
        return {"issues": []}
    if chat_json_fn is None:
        from jonhon_taskbook.llm_client import chat_json as chat_json_fn
    system = """你是语义路由审计器，只报告可能的误位、重复、范围过宽或不确定项，
不生成、不改写正文，也不改变执行计划。你没有独立证据证明一个语义槽位一定错误，
因此 severity 必须始终为 warning；真正的阻断由确定性执行器和 QA 门禁完成。
仅返回 JSON：{"issues":[{"code":"MISROUTED|DUPLICATE|MODEL_SCOPE|UNCERTAIN",
"target_slot":"...","source_ids":["..."],"severity":"warning"}]}。"""
    valid_ids = {b["id"] for b in plan.get("source_blocks", [])}
    valid_slots = {s["id"] for s in plan.get("slots", [])}
    raw = _call(chat_json_fn, system, {
        "node": "semantic_review",
        "scope": plan.get("scope", {}),
        "decisions": plan.get("decisions", []),
        "execution": evidence,
    })
    approved_routes = {
        str(item.get("source_id")): str(item.get("configured_slot"))
        for item in (
            (plan.get("route_audit") or {}).get(
                "classification_constrained_routes", []
            )
        )
        if isinstance(item, dict)
        and item.get("source_id")
        and item.get("configured_slot")
    }
    content_hash_by_id = {
        str(block.get("id")): str(block.get("content_hash", ""))
        for block in plan.get("source_blocks", [])
        if block.get("id")
    }
    route_count: dict[str, int] = defaultdict(int)
    for decision in plan.get("decisions", []):
        for source_id in decision.get("source_ids", []) or []:
            route_count[str(source_id)] += 1
    issues = []
    for item in raw.get("issues", []):
        if not isinstance(item, dict) or item.get("target_slot") not in valid_slots:
            continue
        code = item.get("code")
        if code not in {"MISROUTED", "DUPLICATE", "MODEL_SCOPE", "UNCERTAIN"}:
            continue
        source_ids = [
            x
            for x in item.get("source_ids", [])
            if x in valid_ids and x in executed_source_ids
        ]
        if not source_ids:
            continue
        if code == "DUPLICATE":
            hash_counts: dict[str, int] = defaultdict(int)
            for source_id in source_ids:
                content_hash = content_hash_by_id.get(source_id, "")
                if content_hash:
                    hash_counts[content_hash] += 1
            source_ids = [
                source_id
                for source_id in source_ids
                if (
                    route_count.get(source_id, 0) > 1
                    or hash_counts.get(content_hash_by_id.get(source_id, ""), 0) > 1
                )
            ]
            if not source_ids:
                continue
        if code in {"MISROUTED", "MODEL_SCOPE", "UNCERTAIN"}:
            # A reviewer suggestion cannot overrule the approved 19-category
            # classification -> live template-slot mapping.  Keep only source
            # IDs for which no such authoritative mapping exists or whose
            # final target actually disagrees with it.
            source_ids = [
                source_id
                for source_id in source_ids
                if (
                    source_id not in approved_routes
                    or approved_routes[source_id] != item["target_slot"]
                )
            ]
            if not source_ids:
                continue
        issues.append({
            "code": code,
            "target_slot": item["target_slot"],
            "source_ids": source_ids,
            # LLM 复核是建议层；不允许模型把推测升级为交付阻断。
            "severity": "warning",
        })
    return {"issues": issues}
