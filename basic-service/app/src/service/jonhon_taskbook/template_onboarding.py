from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable

import yaml

from jonhon_taskbook.template_scanner import scan_template_tree


ChatJSON = Callable[[str, str], dict]
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TAXONOMY = ROOT / "config" / "taskbook_requirement_taxonomy.yaml"
_SLUG = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_slug(value: str, label: str) -> str:
    value = str(value).strip()
    if not _SLUG.fullmatch(value):
        raise ValueError(f"{label}必须是小写英文/数字/下划线标识: {value}")
    return value


def _require_version(value: str) -> str:
    value = str(value).strip()
    if not _VERSION.fullmatch(value):
        raise ValueError(f"模板版本格式非法: {value}")
    return value


def load_taxonomy(path: str | Path = DEFAULT_TAXONOMY) -> dict[str, Any]:
    taxonomy_path = Path(path).resolve()
    if not taxonomy_path.exists():
        raise FileNotFoundError(f"分类本体不存在: {taxonomy_path}")
    data = yaml.safe_load(taxonomy_path.read_text(encoding="utf-8")) or {}
    categories = data.get("categories")
    semantic_roles = data.get("semantic_roles") or {}
    if not isinstance(categories, dict) or not categories or "other" not in categories:
        raise ValueError("分类本体必须包含非空 categories 且包含 other")
    if not isinstance(semantic_roles, dict):
        raise ValueError("semantic_roles 必须是对象")
    for key, rule in {**semantic_roles, **categories}.items():
        if not isinstance(rule, dict):
            raise ValueError(f"分类本体 {key} 必须是对象")
        if not str(rule.get("definition") or rule.get("label") or "").strip():
            raise ValueError(f"分类本体 {key} 缺少 definition/label")
    return data


def _taxonomy_description(key: str, rule: dict[str, Any]) -> str:
    """从外置分类本体读取说明，避免在代码中维护易失真的业务词典。"""

    return str(rule.get("definition") or rule.get("label") or key).strip()


def _mapping_prompt(taxonomy: dict[str, Any]) -> str:
    roles = {**(taxonomy.get("semantic_roles") or {}), **taxonomy["categories"]}
    definitions = "\n".join(
        f"- {key}: {rule.get('label', key)}；{_taxonomy_description(key, rule)}"
        for key, rule in roles.items()
    )
    return f"""你是受控研制任务书模板接入规划器，只做分类类别到模板标题槽位的匹配。
必须匹配的类别：
{definitions}

约束：
1. 每个 category 必须且只能返回一次；
2. target_slot 只能来自输入 slots；
3. 只能依据无编号标题、父子语义路径、层级和模板提示语判断；
4. 不得依据章节显示编号、段落绝对顺序或文件名判断；
5. 不得生成、改写或补充任何正文、表格内容、技术数值；
6. 无法可靠定位时仍返回最可能槽位，但 confidence 必须低于 0.75，候选包会被阻断；
7. 仅返回 JSON：{{"mappings":[{{"category":"source_and_function","target_slot":"slot-...","confidence":0.95,"reason":"简短依据"}}]}}。"""


def build_onboarding_plan(
    template_path: str,
    *,
    taxonomy_path: str | Path = DEFAULT_TAXONOMY,
    chat_json_fn: ChatJSON | None = None,
    min_confidence: float = 0.75,
) -> dict[str, Any]:
    template = Path(template_path).resolve()
    if template.suffix.lower() != ".docx" or not template.exists():
        raise ValueError(f"客户模板必须是存在的 DOCX: {template}")
    taxonomy = load_taxonomy(taxonomy_path)
    slots = scan_template_tree(str(template))
    if not slots:
        raise ValueError("客户模板没有可识别的 Heading/outlineLvl 标题")
    if chat_json_fn is None:
        from jonhon_taskbook.llm_client import chat_json as chat_json_fn

    requested = list((taxonomy.get("semantic_roles") or {}).keys()) + list(
        taxonomy["categories"].keys()
    )
    payload = {
        "node": "template_onboarding",
        "categories": [
            {
                "category": key,
                "label": (
                    (taxonomy.get("semantic_roles") or {}).get(key)
                    or taxonomy["categories"].get(key)
                    or {}
                ).get("label", key),
                "description": _taxonomy_description(
                    key,
                    (
                        (taxonomy.get("semantic_roles") or {}).get(key)
                        or taxonomy["categories"].get(key)
                        or {}
                    ),
                ),
            }
            for key in requested
        ],
        "slots": [
            {
                "id": slot["id"],
                "title": slot["title"],
                "semantic_path": slot["semantic_path"],
                "level": slot["level"],
                "parent_id": slot["parent_id"],
            }
            for slot in slots
        ],
    }
    raw = chat_json_fn(
        _mapping_prompt(taxonomy), json.dumps(payload, ensure_ascii=False)
    )
    valid_slots = {slot["id"]: slot for slot in slots}
    accepted: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    for item in raw.get("mappings", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", ""))
        slot_id = str(item.get("target_slot", ""))
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        reason = str(item.get("reason", ""))[:240]
        record = {
            "category": category,
            "target_slot": slot_id,
            "confidence": confidence,
            "reason": reason,
        }
        if category not in requested:
            rejected.append({**record, "error": "unknown_category"})
        elif category in accepted:
            rejected.append({**record, "error": "duplicate_category"})
        elif slot_id not in valid_slots:
            rejected.append({**record, "error": "unknown_target_slot"})
        else:
            accepted[category] = record

    unresolved = []
    for category in requested:
        record = accepted.get(category)
        if record is None:
            unresolved.append({"category": category, "error": "missing_mapping"})
        elif record["confidence"] < min_confidence:
            unresolved.append({**record, "error": "low_confidence"})

    return {
        "schema_version": "1.0",
        "policy": {
            "chapter_numbers_are_identity": False,
            "source_order_is_identity": False,
            "llm_may_generate_body_text": False,
            "human_review_required_before_publish": True,
            "minimum_confidence": min_confidence,
        },
        "template": {
            "path": str(template),
            "sha256": _sha256(template),
            "slot_count": len(slots),
        },
        "slots": slots,
        "mappings": [accepted[key] for key in requested if key in accepted],
        "rejected": rejected,
        "unresolved": unresolved,
        "passed": not rejected and not unresolved and len(accepted) == len(requested),
    }


def _build_mapping(taxonomy: dict[str, Any], plan: dict[str, Any], template_id: str) -> dict:
    slots = {slot["id"]: slot for slot in plan["slots"]}
    decisions = {item["category"]: item for item in plan["mappings"]}

    def group(source: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for category, base_rule in source.items():
            slot = slots[decisions[category]["target_slot"]]
            rule = {
                "label": str(base_rule.get("label", category)),
                "target_heading_keywords": [slot["title"]],
                "target_heading_level": int(slot["level"]),
            }
            if slot.get("parent_id"):
                parent = slots[slot["parent_id"]]
                rule["target_parent_heading"] = parent["title"]
            for key in ("write_mode", "preserve_child_headings", "insert_position"):
                if key in base_rule:
                    rule[key] = base_rule[key]
            result[category] = rule
        return result

    return {
        "version": "3.0",
        "template_id": template_id,
        "semantic_roles": group(taxonomy.get("semantic_roles") or {}),
        "categories": group(taxonomy["categories"]),
    }


def validate_candidate_mapping(
    template_path: str,
    mapping_path: str,
    *,
    taxonomy_path: str | Path = DEFAULT_TAXONOMY,
) -> dict[str, Any]:
    taxonomy = load_taxonomy(taxonomy_path)
    mapping = yaml.safe_load(Path(mapping_path).read_text(encoding="utf-8")) or {}
    slots = scan_template_tree(template_path)
    expected_groups = {
        "semantic_roles": taxonomy.get("semantic_roles") or {},
        "categories": taxonomy["categories"],
    }
    problems: list[str] = []
    matches: list[dict[str, Any]] = []
    for group_name, expected in expected_groups.items():
        actual = mapping.get(group_name) or {}
        if set(actual) != set(expected):
            problems.append(
                f"{group_name} 类别集合不一致: missing={sorted(set(expected)-set(actual))}, "
                f"extra={sorted(set(actual)-set(expected))}"
            )
        for category in expected:
            rule = actual.get(category) or {}
            headings = rule.get("target_heading_keywords") or []
            if isinstance(headings, str):
                headings = [headings]
            level = int(rule.get("target_heading_level", 0) or 0)
            parent = str(rule.get("target_parent_heading", ""))
            candidates = [
                slot for slot in slots
                if slot["title"] in headings
                and (not level or slot["level"] == level)
                and (
                    not parent
                    or (
                        slot.get("parent_id")
                        and next(
                            (x["title"] for x in slots if x["id"] == slot["parent_id"]),
                            "",
                        ) == parent
                    )
                )
            ]
            if len(candidates) != 1:
                problems.append(
                    f"{category} 目标标题必须唯一，当前匹配 {len(candidates)} 个"
                )
            else:
                matches.append({"category": category, "slot": candidates[0]["id"]})
    return {
        "passed": not problems,
        "problem_count": len(problems),
        "problems": problems,
        "matches": matches,
        "slot_count": len(slots),
        "policy": "title + parent title + heading level; never chapter number",
    }


def prepare_template_candidate(
    template_path: str,
    output_dir: str,
    *,
    product_type: str,
    product_label: str,
    domain: str,
    domain_label: str,
    version: str,
    taxonomy_path: str | Path = DEFAULT_TAXONOMY,
    chat_json_fn: ChatJSON | None = None,
    min_confidence: float = 0.75,
) -> dict[str, Any]:
    product_type = _require_slug(product_type, "产品类型")
    domain = _require_slug(domain, "产品领域")
    version = _require_version(version)
    product_label = str(product_label).strip()
    domain_label = str(domain_label).strip()
    if not product_label or not domain_label:
        raise ValueError("产品类型名称和领域名称不能为空")

    plan = build_onboarding_plan(
        template_path,
        taxonomy_path=taxonomy_path,
        chat_json_fn=chat_json_fn,
        min_confidence=min_confidence,
    )
    if not plan["passed"]:
        raise ValueError(
            "模板语义槽位规划未通过，禁止生成可发布候选包: "
            + json.dumps(plan["unresolved"] + plan["rejected"], ensure_ascii=False)
        )

    output = Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"候选包目录必须为空: {output}")
    output.mkdir(parents=True, exist_ok=True)
    stem = f"{product_type}_{domain}_{version}"
    template_name = f"{stem}.docx"
    mapping_name = f"{stem}_requirement_categories.yaml"
    profile_name = f"{stem}_profile.yaml"
    template_out = output / template_name
    mapping_out = output / mapping_name
    profile_out = output / profile_name

    shutil.copy2(Path(template_path).resolve(), template_out)
    taxonomy = load_taxonomy(taxonomy_path)
    mapping = _build_mapping(taxonomy, plan, stem)
    mapping_out.write_text(
        yaml.safe_dump(mapping, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    slot_by_category = {item["category"]: item["target_slot"] for item in plan["mappings"]}
    slot_by_id = {slot["id"]: slot for slot in plan["slots"]}
    profile = {
        "schema_version": "3.0",
        "profile_id": stem,
        "product_type": product_label,
        "semantic_routing": {
            "category_mapping": mapping_name,
            "chapter_numbers_are_identity": False,
            "source_order_is_identity": False,
            "copy_source_text_only": True,
        },
        # 7-22：新接入模板默认合并技术要求、产品规范和模板中的标准后去重。
        "standards_policy": "merge_template",
        "semantic_structures": {
            "performance_indicator": {"mode": "indicator_table"}
        },
        "spec_model_filter": {"enabled": True},
        "indicator_map": {},
        "qa_profile": {
            "required_headings": [
                slot_by_id[slot_by_category[key]]["title"]
                for key in ("performance_indicator", "other")
            ],
            "forbidden_phrases": [],
        },
    }
    profile_out.write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    catalog_patch = {
        "review_status": "pending_human_approval",
        "publish_instructions": (
            "审核模板、映射、实文档回归和全页渲染后，将 enabled 改为 true，"
            "再合并到 config/template_catalog.yaml"
        ),
        "product_types": {
            product_type: {
                "label": product_label,
                "enabled": False,
                "template_label": f"研制任务书（{product_label}）",
                "unavailable_reason": "候选模板尚未完成人工审核发布",
                "domains": {
                    domain: {
                        "label": domain_label,
                        "template": template_name,
                        "profile": profile_name,
                        "category_mapping": mapping_name,
                        "preserve_unfilled_template": True,
                    }
                },
            }
        },
    }
    (output / "catalog_patch.yaml").write_text(
        yaml.safe_dump(catalog_patch, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    validation = validate_candidate_mapping(
        str(template_out), str(mapping_out), taxonomy_path=taxonomy_path
    )
    report = {
        "schema_version": "1.0",
        "machine_validation_passed": bool(validation["passed"]),
        "publish_ready": False,
        "review_status": "pending_human_approval",
        "review_required": True,
        "product_type": product_type,
        "product_label": product_label,
        "domain": domain,
        "domain_label": domain_label,
        "version": version,
        "template_sha256": _sha256(template_out),
        "policy": plan["policy"],
        "mapping_plan": plan["mappings"],
        "mapping_validation": validation,
        "files": {
            "template": template_name,
            "mapping": mapping_name,
            "profile": profile_name,
            "catalog_patch": "catalog_patch.yaml",
        },
    }
    (output / "onboarding_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="生成客户模板受控接入候选包")
    parser.add_argument("--template", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--product-type", required=True)
    parser.add_argument("--product-label", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--domain-label", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY))
    args = parser.parse_args()
    try:
        report = prepare_template_candidate(
            args.template,
            args.output_dir,
            product_type=args.product_type,
            product_label=args.product_label,
            domain=args.domain,
            domain_label=args.domain_label,
            version=args.version,
            taxonomy_path=args.taxonomy,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
