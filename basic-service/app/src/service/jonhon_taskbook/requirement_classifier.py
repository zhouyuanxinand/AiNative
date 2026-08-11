from __future__ import annotations

import json
import hashlib
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import yaml

from jonhon_taskbook.semantic_orchestrator import (
    extract_source_blocks,
    protected_source_block_ids,
)


ChatJSON = Callable[[str, str], dict]


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classification_cache_key(requirement_path: str, mapping_path: str) -> str:
    model_values = {
        key: os.getenv(key, "")
        for key in (
            "JTB_LLM_PROVIDER", "JTB_LLM_API_URL", "JTB_LLM_MODEL",
            "JTB_LLM_MODEL_ID", "JTB_LLM_APP_ID", "JTB_LLM_MAX_TOKENS",
        )
    }
    payload = {
        "schema": "requirement-classification-cache-v7-container-child-constraint",
        "module": _file_sha256(Path(__file__)),
        # Source block identities and image/caption groups are produced by
        # semantic_orchestrator.  A classifier-only cache fingerprint would
        # otherwise keep stale overlapping media groups after parser fixes.
        "source_block_parser": _file_sha256(
            Path(__file__).with_name("semantic_orchestrator.py")
        ),
        "requirement": _file_sha256(requirement_path),
        "mapping": _file_sha256(mapping_path),
        "model": model_values,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

def load_category_mapping(path: str) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    categories = data.get("categories")
    if not isinstance(categories, dict) or "other" not in categories:
        raise ValueError("语义分类映射必须包含 categories.other")
    semantic_roles = data.get("semantic_roles") or {}
    if not isinstance(semantic_roles, dict):
        raise ValueError("semantic_roles 必须是对象")
    for key, item in {**categories, **semantic_roles}.items():
        if not isinstance(item, dict):
            raise ValueError(f"语义分类 {key} 必须是对象")
        if not str(item.get("definition") or item.get("label") or "").strip():
            raise ValueError(f"语义分类 {key} 缺少 definition/label")
    return data


def _category_definition(key: str, item: Any) -> str:
    if not isinstance(item, dict):
        raise ValueError(f"语义分类 {key} 必须是对象")
    definition = str(item.get("definition") or item.get("label") or "").strip()
    if not definition:
        raise ValueError(f"语义分类 {key} 缺少 definition/label")
    return definition


def _prompt(categories: dict[str, Any]) -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "requirement_classification.md"
    template = prompt_path.read_text(encoding="utf-8")
    definitions = "\n".join(
        f"- {key}: {_category_definition(key, item)}"
        for key, item in categories.items()
    )
    return template.replace("{{ category_definitions }}", definitions)


def _classify_with_llm(
    blocks: list[dict], categories: dict[str, Any], chat_json_fn: ChatJSON
) -> dict[str, dict]:
    result: dict[str, dict] = {}
    system = _prompt(categories)
    # MaaS 兼容接口对超大 JSON 请求偶发主动断开；较小批次仍保持
    # “整块语义分类”，但降低单次正文负载，避免连接层失败。
    for start in range(0, len(blocks), 20):
        batch = blocks[start : start + 20]
        payload = {
            "node": "requirement_classification",
            "blocks": [
                {
                    "source_id": block["id"],
                    "heading_text": block.get("heading_text", ""),
                    "parent_headings": block.get("parent_headings", []),
                    "previous_heading": block.get("previous_heading", ""),
                    "next_heading": block.get("next_heading", ""),
                    "type": block["type"],
                    "text": block["text"][:2000],
                }
                for block in batch
            ],
        }
        raw = chat_json_fn(system, json.dumps(payload, ensure_ascii=False))
        valid_ids = {block["id"] for block in batch}
        for item in raw.get("classifications", []) if isinstance(raw, dict) else []:
            if not isinstance(item, dict):
                continue
            source_id = item.get("source_id")
            category = item.get("category")
            if source_id not in valid_ids or source_id in result:
                continue
            try:
                confidence = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
            except (TypeError, ValueError):
                confidence = 0.0
            if category not in categories or confidence < 0.60:
                category = "other"
            result[source_id] = {
                "source_id": source_id,
                "category": category,
                "confidence": confidence,
                "method": "llm",
                "reason": str(item.get("reason", ""))[:240],
            }
    return result


def _apply_configured_heading_constraints(
    chapters: list[dict[str, Any]],
    classifications: dict[str, dict],
    categories: dict[str, Any],
) -> dict[str, dict]:
    """Apply optional, externally configured source-title constraints.

    The mechanism is generic: product rule packs may declare strong semantic
    title/parent-title signals.  Chapter numbers and source order are never
    inspected.  The longest matching configured phrase wins so that a more
    specific title is preferred over a broad one.
    """
    constrained = dict(classifications)
    for chapter in chapters:
        heading = str(chapter.get("heading_text", "")).strip()
        parents = [
            str(item).strip()
            for item in chapter.get("parent_headings", [])
            if str(item).strip()
        ]
        matches: list[tuple[int, str, str]] = []
        for category, config in categories.items():
            if not isinstance(config, dict):
                continue
            for keyword in config.get("source_heading_keywords", []) or []:
                phrase = str(keyword).strip()
                if phrase and phrase in heading:
                    matches.append((len(phrase), category, phrase))
            parent_text = " / ".join(parents)
            for keyword in config.get("source_parent_heading_keywords", []) or []:
                phrase = str(keyword).strip()
                if phrase and phrase in parent_text:
                    matches.append((len(phrase), category, phrase))
        if not matches:
            continue
        _, category, phrase = max(matches, key=lambda item: item[0])
        current = constrained.get(chapter["id"], {})
        constrained[chapter["id"]] = {
            "source_id": chapter["id"],
            "category": category,
            "confidence": max(0.95, float(current.get("confidence", 0.0) or 0.0)),
            "method": "llm+configured_heading_constraint",
            "reason": f"无编号标题语义命中受控规则：{phrase}",
        }
    return constrained


def _apply_configured_content_constraints(
    blocks: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    categories: dict[str, Any],
) -> list[dict[str, Any]]:
    """用外置的正文证据规则细化粗粒度章节分类。

    规则只读取 YAML 中的 ``source_content_patterns``，不读取章节号、来源顺序
    或产品型号。它在整章分类和容器内分类之后执行，因此“交付要求”这类宽泛
    章节中的“随产品提供说明书/合格证/备件”仍可被识别为条件保障证据。
    """
    block_by_id = {str(block.get("id", "")): block for block in blocks}
    compiled: list[tuple[int, int, str, str, re.Pattern[str]]] = []
    for category, config in categories.items():
        if not isinstance(config, dict):
            continue
        try:
            priority = int(config.get("content_priority", 0) or 0)
        except (TypeError, ValueError):
            priority = 0
        for raw_pattern in config.get("source_content_patterns", []) or []:
            pattern = str(raw_pattern).strip()
            if not pattern:
                continue
            try:
                regex = re.compile(pattern, re.I)
            except re.error as exc:
                raise ValueError(
                    f"分类 {category} 的 source_content_patterns 非法: {pattern!r}"
                ) from exc
            compiled.append((priority, len(pattern), category, pattern, regex))

    if not compiled:
        return assignments

    refined: list[dict[str, Any]] = []
    for assignment in assignments:
        source_id = str(assignment.get("source_id", ""))
        block = block_by_id.get(source_id, {})
        text = str(block.get("text", "")).strip()
        matches = [
            item for item in compiled
            if text and item[4].search(text)
        ]
        if not matches:
            refined.append(assignment)
            continue
        priority, _, category, pattern, _ = max(
            matches, key=lambda item: (item[0], item[1])
        )
        current = dict(assignment)
        current.update({
            "category": category,
            "confidence": max(0.98, float(current.get("confidence", 0.0) or 0.0)),
            "method": f"{current.get('method', 'llm')}+configured_content_constraint",
            "reason": (
                f"正文证据命中外置受控规则（priority={priority}）：{pattern}"
            )[:240],
        })
        refined.append(current)
    return refined


def _classify_container_members(
    chapter: dict[str, Any],
    members: list[dict[str, Any]],
    categories: dict[str, Any],
    container_rule: dict[str, Any],
    chat_json_fn: ChatJSON,
) -> dict[str, dict[str, Any]]:
    """对“只作容器”的来源章执行块级二次语义路由。

    例如来源标题为“接口尺寸”时，章内可能同时包含安装方式、安装尺寸、
    外形尺寸、端接形式和互换性。父标题只用于确定这是一个容器，最终
    目标仍由每个原文块的语义决定。整个过程不读取章节号或来源顺序。
    """
    allowed = [
        str(name).strip()
        for name in container_rule.get("block_target_categories", []) or []
        if str(name).strip() in categories
    ]
    fallback = str(container_rule.get("block_fallback_category", "")).strip()
    if fallback not in allowed:
        raise ValueError(
            f"容器章 {chapter.get('heading_text', '')!r} 的兜底类别未包含在允许子槽中"
        )
    subset = {name: categories[name] for name in allowed}
    block_inputs: list[dict[str, Any]] = []
    for member in members:
        item = dict(member)
        item["heading_text"] = str(member.get("heading_text") or chapter.get("heading_text") or "")
        item["parent_headings"] = list(member.get("parent_headings") or chapter.get("parent_headings") or [])
        block_inputs.append(item)
    raw = _classify_with_llm(block_inputs, subset, chat_json_fn)

    def _is_visual(block: dict[str, Any]) -> bool:
        kind = str(block.get("type", "")).lower()
        text = str(block.get("text", "")).strip()
        return (
            kind in {"image", "picture", "drawing"}
            or text.startswith("[图片对象")
        )

    chosen: list[str] = []
    for block in members:
        result = raw.get(block["id"], {})
        category = str(result.get("category", ""))
        chosen.append(category if category in allowed else fallback)

    # 图片本身没有可供模型判断的正文。它必须跟随相邻图题/说明的语义，
    # 以保持“段落—图片—图题”连续搬运；找不到相邻证据才使用配置兜底。
    for index, block in enumerate(members):
        if not _is_visual(block):
            continue
        inherited = ""
        for candidate_index in range(index + 1, len(members)):
            if not _is_visual(members[candidate_index]):
                inherited = chosen[candidate_index]
                break
        if not inherited:
            for candidate_index in range(index - 1, -1, -1):
                if not _is_visual(members[candidate_index]):
                    inherited = chosen[candidate_index]
                    break
        chosen[index] = inherited or fallback

    assignments: dict[str, dict[str, Any]] = {}
    for block, category in zip(members, chosen):
        llm_item = raw.get(block["id"], {})
        assignments[block["id"]] = {
            "source_id": block["id"],
            "chapter_id": chapter["id"],
            "category": category,
            "confidence": float(llm_item.get("confidence", 0.60) or 0.60),
            "method": "llm+container_block_routing",
            # Preserve the container's externally configured write boundary.
            # A later exact-fragment pass must not reintroduce the parent
            # container as a writable category.
            "container_only_source": True,
            "container_target_categories": list(allowed),
            "container_fallback_category": fallback,
            "reason": (
                str(llm_item.get("reason", "")).strip()
                or f"容器章块级语义路由；无法细分时进入 {fallback}"
            )[:240],
        }
    return assignments


def _exact_fragment_prompt(categories: dict[str, Any]) -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "requirement_exact_fragment_routing.md"
    template = prompt_path.read_text(encoding="utf-8")
    definitions = "\n".join(
        f"- {key}: {_category_definition(key, item)}"
        for key, item in categories.items()
    )
    return template.replace("{{ category_definitions }}", definitions)


def _partition_mixed_blocks_with_llm(
    blocks: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    categories: dict[str, Any],
    routing_config: dict[str, Any],
    chat_json_fn: ChatJSON,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition mixed paragraphs into exact, non-overlapping source spans.

    This is multi-label *segmentation*, not text generation.  Every accepted
    partition is a lossless partition of an existing paragraph.  Invalid or
    incomplete model output is ignored and the original atomic block remains.
    """
    if not routing_config.get("enabled"):
        return blocks, assignments, []
    source_categories = {
        str(value) for value in routing_config.get("source_categories", []) or []
        if str(value) in categories
    }
    target_categories = {
        str(value) for value in routing_config.get("target_categories", []) or []
        if str(value) in categories
    }
    if not source_categories or len(target_categories) < 2:
        return blocks, assignments, []
    min_length = max(8, int(routing_config.get("min_text_length", 24) or 24))
    max_fragments = max(2, int(routing_config.get("max_fragments_per_block", 8) or 8))
    assignment_by_id = {
        str(item.get("source_id")): item for item in assignments if item.get("source_id")
    }
    candidates = [
        block for block in blocks
        if block.get("type") == "paragraph"
        and not block.get("has_drawing")
        and len(str(block.get("text", ""))) >= min_length
        and str(assignment_by_id.get(str(block.get("id")), {}).get("category", ""))
        in source_categories
    ]
    if not candidates:
        return blocks, assignments, []

    allowed = {key: categories[key] for key in target_categories}
    system = _exact_fragment_prompt(allowed)
    proposed: dict[str, list[dict[str, Any]]] = {}
    for start in range(0, len(candidates), 16):
        batch = candidates[start : start + 16]
        payload = {
            "node": "requirement_exact_fragment_routing",
            "blocks": [
                {
                    "source_id": block["id"],
                    "heading_text": block.get("heading_text", ""),
                    "parent_headings": block.get("parent_headings", []),
                    "text": block.get("text", ""),
                }
                for block in batch
            ],
        }
        raw = chat_json_fn(system, json.dumps(payload, ensure_ascii=False))
        valid = {str(block["id"]): block for block in batch}
        for partition in raw.get("partitions", []) if isinstance(raw, dict) else []:
            if not isinstance(partition, dict):
                continue
            source_id = str(partition.get("source_id", ""))
            block = valid.get(source_id)
            fragments = partition.get("fragments", [])
            if block is None or not isinstance(fragments, list):
                continue
            cleaned: list[dict[str, Any]] = []
            for item in fragments:
                if not isinstance(item, dict):
                    cleaned = []
                    break
                text = str(item.get("text", ""))
                category = str(item.get("category", ""))
                try:
                    confidence = float(item.get("confidence", 0.0))
                except (TypeError, ValueError):
                    confidence = 0.0
                if not text or category not in target_categories or confidence < 0.60:
                    cleaned = []
                    break
                if cleaned and cleaned[-1]["category"] == category:
                    cleaned[-1]["text"] += text
                    cleaned[-1]["confidence"] = min(cleaned[-1]["confidence"], confidence)
                else:
                    cleaned.append({
                        "text": text,
                        "category": category,
                        "confidence": max(0.0, min(1.0, confidence)),
                    })
            original_text = str(block.get("text", ""))
            if (
                len(cleaned) < 2
                or len(cleaned) > max_fragments
                or len({item["category"] for item in cleaned}) < 2
                or "".join(item["text"] for item in cleaned) != original_text
            ):
                continue
            proposed[source_id] = cleaned

    # Some OpenAI-compatible gateways occasionally return a valid chapter
    # classification but omit the lossless ``partitions`` array.  Do not fall
    # back to keywords or duplicate the whole paragraph.  Instead, split only
    # on existing sentence/clause punctuation (the split is byte-for-byte
    # lossless), ask the same LLM taxonomy to classify the exact clauses, and
    # accept the partition only when at least two semantic categories are
    # present.  This keeps the behavior product- and chapter-number agnostic.
    unresolved = [block for block in candidates if str(block["id"]) not in proposed]

    def _punctuation_spans(text: str, pattern: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        start_offset = 0
        for match in re.finditer(pattern, text):
            end_offset = match.end()
            if end_offset > start_offset:
                spans.append((start_offset, end_offset))
            start_offset = end_offset
        if start_offset < len(text):
            spans.append((start_offset, len(text)))
        return spans

    def _classify_lossless_clauses(
        pending: list[dict[str, Any]], pattern: str, pass_name: str
    ) -> set[str]:
        """Try one punctuation granularity and return accepted parent ids.

        Sentence punctuation is deliberately tried before comma punctuation.
        This preserves complete clauses whenever the model can already
        distinguish their semantics, while still allowing a second, finer
        pass for long compound sentences.  Both passes remain byte-for-byte
        partitions of the source paragraph.
        """
        clause_blocks: list[dict[str, Any]] = []
        clause_groups: dict[str, list[dict[str, Any]]] = {}
        block_by_id = {str(block["id"]): block for block in pending}
        for block in pending:
            original_text = str(block.get("text", ""))
            spans = _punctuation_spans(original_text, pattern)
            if len(spans) < 2:
                continue
            parent_id = str(block["id"])
            members: list[dict[str, Any]] = []
            for clause_index, (span_start, span_end) in enumerate(spans):
                clause = {
                    "id": f"{parent_id}-{pass_name}-{clause_index}",
                    "type": "paragraph",
                    "text": original_text[span_start:span_end],
                    "heading_text": block.get("heading_text", ""),
                    "parent_headings": block.get("parent_headings", []),
                    "previous_heading": "",
                    "next_heading": "",
                }
                members.append(clause)
                clause_blocks.append(clause)
            clause_groups[parent_id] = members
        if not clause_blocks:
            return set()

        accepted: set[str] = set()
        clause_results = _classify_with_llm(clause_blocks, allowed, chat_json_fn)
        for source_id, members in clause_groups.items():
            cleaned: list[dict[str, Any]] = []
            invalid = False
            for clause in members:
                assignment = clause_results.get(str(clause["id"]))
                if not assignment:
                    invalid = True
                    break
                category = str(assignment.get("category", ""))
                try:
                    confidence = float(assignment.get("confidence", 0.0))
                except (TypeError, ValueError):
                    confidence = 0.0
                if category not in target_categories or confidence < 0.60:
                    invalid = True
                    break
                clause_text = str(clause["text"])
                if cleaned and cleaned[-1]["category"] == category:
                    cleaned[-1]["text"] += clause_text
                    cleaned[-1]["confidence"] = min(
                        cleaned[-1]["confidence"], confidence
                    )
                else:
                    cleaned.append({
                        "text": clause_text,
                        "category": category,
                        "confidence": max(0.0, min(1.0, confidence)),
                    })
            original_text = str(block_by_id[source_id].get("text", ""))
            if (
                invalid
                or len(cleaned) < 2
                or len(cleaned) > max_fragments
                or len({item["category"] for item in cleaned}) < 2
                or "".join(item["text"] for item in cleaned) != original_text
            ):
                continue
            proposed[source_id] = cleaned
            accepted.add(source_id)
        return accepted

    accepted = _classify_lossless_clauses(
        unresolved, r"[。；;！？!?]+", "sentence"
    )
    fine_pending = [
        block for block in unresolved if str(block["id"]) not in accepted
    ]
    _classify_lossless_clauses(
        fine_pending, r"[。；;！？!?，,]+", "clause"
    )

    # Exact-fragment routing uses the global taxonomy.  A model may therefore
    # return a category that is intentionally only a structural container
    # (for example “接口尺寸”) even though the source block has already been
    # constrained to that container's writable children.  Re-apply the
    # externally configured boundary after segmentation.  This is independent
    # of chapter numbers, source order and product model.
    atomic_category_overrides: dict[str, str] = {}
    for source_id, fragments in list(proposed.items()):
        original_assignment = assignment_by_id.get(source_id, {})
        allowed_children = {
            str(value)
            for value in original_assignment.get("container_target_categories", []) or []
            if str(value) in categories
        }
        container_fallback = str(
            original_assignment.get("container_fallback_category", "")
        ).strip()
        if allowed_children and container_fallback not in allowed_children:
            raise ValueError(
                f"原文块 {source_id} 的容器兜底类别未包含在允许子槽中"
            )

        normalized: list[dict[str, Any]] = []
        for fragment in fragments:
            category = str(fragment["category"])
            if allowed_children and category not in allowed_children:
                category = container_fallback
            category_rule = categories.get(category, {})
            if isinstance(category_rule, dict) and category_rule.get("container_only"):
                category_fallback = str(
                    category_rule.get("block_fallback_category", "")
                ).strip()
                if category_fallback not in categories:
                    raise ValueError(
                        f"容器类别 {category} 缺少有效 block_fallback_category"
                    )
                category = category_fallback
            current = {**fragment, "category": category}
            if normalized and normalized[-1]["category"] == category:
                normalized[-1]["text"] += current["text"]
                normalized[-1]["confidence"] = min(
                    normalized[-1]["confidence"], current["confidence"]
                )
            else:
                normalized.append(current)

        if len({item["category"] for item in normalized}) < 2:
            # The semantic distinction disappeared after enforcing the
            # writable-child boundary.  Keep the original paragraph atomic so
            # its wording and inline formatting remain exact.
            atomic_category_overrides[source_id] = normalized[0]["category"]
            proposed.pop(source_id, None)
        else:
            proposed[source_id] = normalized

    if not proposed and not atomic_category_overrides:
        return blocks, assignments, []

    new_blocks: list[dict[str, Any]] = []
    new_assignments: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for block in blocks:
        source_id = str(block.get("id", ""))
        fragments = proposed.get(source_id)
        original_assignment = assignment_by_id.get(source_id)
        if not fragments or original_assignment is None:
            new_blocks.append(block)
            if original_assignment is not None:
                override = atomic_category_overrides.get(source_id)
                if override:
                    constrained = dict(original_assignment)
                    constrained.update({
                        "category": override,
                        "confidence": max(
                            0.95,
                            float(original_assignment.get("confidence", 0.0) or 0.0),
                        ),
                        "method": (
                            f"{original_assignment.get('method', 'llm')}"
                            "+container_child_constraint"
                        ),
                        "reason": "容器章原文块按外置规则约束到可写子槽",
                    })
                    new_assignments.append(constrained)
                else:
                    new_assignments.append(original_assignment)
            continue
        offset = 0
        fragment_ids: list[str] = []
        categories_used: list[str] = []
        for index, fragment in enumerate(fragments):
            text = fragment["text"]
            end = offset + len(text)
            identity = f"{source_id}|{offset}|{end}|{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
            fragment_id = f"{source_id}-f-{hashlib.sha1(identity.encode('utf-8')).hexdigest()[:10]}"
            fragment_block = dict(block)
            fragment_block.update({
                "id": fragment_id,
                "text": text,
                "content_hash": hashlib.sha256(re.sub(r"\s+", "", text).encode("utf-8")).hexdigest(),
                "is_fragment": True,
                "parent_source_id": source_id,
                "fragment_index": index,
                "source_span_start": offset,
                "source_span_end": end,
                "element_content_hash": str(block.get("content_hash", "")),
                "media_group_id": "",
                "media_group_members": [],
            })
            new_blocks.append(fragment_block)
            new_assignments.append({
                **original_assignment,
                "source_id": fragment_id,
                "category": fragment["category"],
                "confidence": fragment["confidence"],
                "method": "llm+exact_fragment_partition",
                "reason": "原文段落经逐字无损分区后按片段语义路由",
            })
            fragment_ids.append(fragment_id)
            categories_used.append(fragment["category"])
            offset = end
        audit.append({
            "parent_source_id": source_id,
            "fragment_source_ids": fragment_ids,
            "categories": categories_used,
            "reconstructed_exactly": offset == len(str(block.get("text", ""))),
        })
    return new_blocks, new_assignments, audit


def build_requirement_classification(
    requirement_path: str,
    mapping_path: str,
    output_path: str | None = None,
    use_llm: bool = True,
    chat_json_fn: ChatJSON | None = None,
) -> dict[str, Any]:
    mapping = load_category_mapping(mapping_path)
    cache_key = _classification_cache_key(requirement_path, mapping_path)
    cache_path = (
        Path(output_path).parent / f".{cache_key}.classification.cache.json"
        if output_path else None
    )
    if use_llm and cache_path and cache_path.is_file():
        try:
            envelope = json.loads(cache_path.read_text(encoding="utf-8"))
            if envelope.get("cache_key") == cache_key:
                cached = envelope["report"]
                if cached.get("passed"):
                    if output_path:
                        Path(output_path).write_text(
                            json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
                    return cached
        except (OSError, ValueError, TypeError, KeyError):
            pass
    business_categories = mapping["categories"]
    semantic_roles = mapping.get("semantic_roles") or {}
    categories = {**business_categories, **semantic_roles}
    if not use_llm:
        raise ValueError(
            "生产分类器禁止关闭 LLM；不得退回关键词、章节号或章节顺序猜测"
        )
    if chat_json_fn is None:
        from jonhon_taskbook.llm_client import chat_json as chat_json_fn
    all_blocks = extract_source_blocks(
        requirement_path,
        "tech",
        chat_json_fn=chat_json_fn,
        require_llm_structure=True,
    )
    protected_ids = protected_source_block_ids(all_blocks)
    body_blocks = [
        block
        for block in all_blocks
        if (
            block.get("section") != "（封面/前置区域）"
            and str(block.get("id", "")) not in protected_ids
        )
    ]
    # 有可识别的正文结构时，只分类正文；封面和变更记录由固定字段规则处理。
    # 对完全无章节结构的文档则保留全量块，保证通用输入不会被清空。
    blocks = body_blocks or all_blocks

    # 先按来源章节聚合。分类对象是“整章节”，不是章节里的单个段落；
    # 同一章节的段落、表格、图片随后共享同一个类别和目标位置。
    chapter_groups: dict[str, dict[str, Any]] = {}
    for block in blocks:
        chapter_id = str(block.get("chapter_id", ""))
        group = chapter_groups.setdefault(
            chapter_id,
            {"section": str(block.get("section", "")), "members": []},
        )
        group["members"].append(block)
    chapters = []
    for chapter_id, group in chapter_groups.items():
        section = group["section"]
        members = group["members"]
        visible_text = "\n".join(
            str(member.get("text", ""))
            for member in members
            if not str(member.get("text", "")).startswith("[图片对象")
        )
        chapters.append({
            "id": chapter_id,
            "section": section,
            "heading_number": members[0].get("heading_number", ""),
            "heading_text": members[0].get("heading_text", section),
            "parent_headings": members[0].get("parent_headings", []),
            "type": "chapter",
            "text": visible_text[:6000],
            "member_source_ids": [member["id"] for member in members],
        })
    for index, chapter in enumerate(chapters):
        chapter["previous_heading"] = chapters[index - 1]["heading_text"] if index else ""
        chapter["next_heading"] = chapters[index + 1]["heading_text"] if index + 1 < len(chapters) else ""

    llm_results = _classify_with_llm(chapters, categories, chat_json_fn)
    llm_results = _apply_configured_heading_constraints(
        chapters,
        llm_results,
        categories,
    )
    missing_chapters = [
        chapter["id"] for chapter in chapters if chapter["id"] not in llm_results
    ]
    if missing_chapters:
        raise ValueError(
            "LLM 语义分类结果不完整，缺少来源章节: "
            + ", ".join(missing_chapters[:10])
            + ("…" if len(missing_chapters) > 10 else "")
        )

    chapter_assignments = []
    for chapter in chapters:
        chapter_assignments.append(llm_results[chapter["id"]])

    chapter_category = {
        assignment["source_id"]: assignment
        for assignment in chapter_assignments
    }
    assignments = []
    blocks_by_chapter: dict[str, list[dict[str, Any]]] = {}
    for block in blocks:
        blocks_by_chapter.setdefault(str(block.get("chapter_id", "")), []).append(block)
    for chapter in chapters:
        chapter_assignment = chapter_category[chapter["id"]]
        chapter_rule = categories.get(chapter_assignment["category"]) or {}
        if isinstance(chapter_rule, dict) and chapter_rule.get("container_only"):
            member_assignments = _classify_container_members(
                chapter,
                blocks_by_chapter.get(chapter["id"], []),
                categories,
                chapter_rule,
                chat_json_fn,
            )
            for source_id in chapter["member_source_ids"]:
                assignments.append(member_assignments[source_id])
            continue
        for source_id in chapter["member_source_ids"]:
            assignments.append({
                "source_id": source_id,
                "chapter_id": chapter["id"],
                "category": chapter_assignment["category"],
                "confidence": chapter_assignment["confidence"],
                "method": chapter_assignment["method"],
                "reason": chapter_assignment["reason"],
            })

    assignments = _apply_configured_content_constraints(
        blocks,
        assignments,
        categories,
    )

    blocks, assignments, fragment_partitions = _partition_mixed_blocks_with_llm(
        blocks,
        assignments,
        categories,
        mapping.get("exact_fragment_routing") or {},
        chat_json_fn,
    )
    if fragment_partitions:
        replacement_ids = {
            item["parent_source_id"]: item["fragment_source_ids"]
            for item in fragment_partitions
        }
        for chapter in chapters:
            expanded: list[str] = []
            for source_id in chapter.get("member_source_ids", []):
                expanded.extend(replacement_ids.get(source_id, [source_id]))
            chapter["member_source_ids"] = expanded

    ids = [item["source_id"] for item in assignments]
    counts = Counter(item["category"] for item in assignments)
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "policy": {
            "llm_may_generate_text": False,
            "one_primary_category_per_source": True,
            "mixed_paragraph_policy": "exact_non_overlapping_fragment_partition",
            "low_confidence_category": "other",
        },
        "mapping_file": str(Path(mapping_path).resolve()),
        "source_blocks": blocks,
        "source_chapters": chapters,
        "chapter_classifications": chapter_assignments,
        "classifications": assignments,
        "fragment_partitions": fragment_partitions,
        "summary": {
            "source_count": len(blocks),
            "classified_count": len(assignments),
            "unique_source_count": len(set(ids)),
            "category_counts": dict(counts),
            "business_category_counts": {
                key: value for key, value in counts.items() if key in business_categories
            },
            "semantic_role_counts": {
                key: value for key, value in counts.items() if key in semantic_roles
            },
            "chapter_count": len(chapters),
        },
        "passed": len(blocks) == len(assignments) == len(set(ids)),
    }
    if output_path:
        cache_path.write_text(
            json.dumps({"cache_key": cache_key, "report": report}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        Path(output_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report
