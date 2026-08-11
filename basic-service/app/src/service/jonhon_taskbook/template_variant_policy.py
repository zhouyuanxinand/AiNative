"""配置驱动的模板互斥分支治理。

本模块只读取受控业务字段，并按实时模板标题语义删除不适用分支。
章节号、产品型号、文件名和模板顺序都不是路由依据。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from docx.document import Document as _Document
from docx.text.paragraph import Paragraph


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = ROOT / "config" / "template_variant_policy.yaml"


def load_template_variant_policy(
    policy_path: str | Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    path = Path(policy_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("fields"), dict):
        raise ValueError(f"模板分支策略缺少 fields: {path}")
    groups = data.get("mutually_exclusive_groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError(f"模板分支策略缺少 mutually_exclusive_groups: {path}")
    return data


def allowed_organization_scopes(
    policy_path: str | Path = DEFAULT_POLICY_PATH,
) -> dict[str, str]:
    policy = load_template_variant_policy(policy_path)
    field = (policy.get("fields") or {}).get("organization_scope") or {}
    values = field.get("values") or {}
    return {
        str(key): str((value or {}).get("label") or key)
        for key, value in values.items()
        if isinstance(value, dict)
    }


def normalize_organization_scope(
    value: str,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
) -> str:
    normalized = str(value or "").strip()
    allowed = allowed_organization_scopes(policy_path)
    if normalized in allowed:
        return normalized
    by_label = {label: key for key, label in allowed.items()}
    if normalized in by_label:
        return by_label[normalized]
    raise ValueError(
        "产品归属范围无效，允许值为: "
        + "、".join(f"{key}（{label}）" for key, label in allowed.items())
    )


def _compact(text: str) -> str:
    return re.sub(r"[\s\u3000]+", "", str(text or ""))


def _heading_level(paragraph: Paragraph) -> int:
    style_name = str(getattr(paragraph.style, "name", "") or "")
    match = re.search(r"(?:Heading|标题)\s*([1-9])", style_name, re.I)
    if match:
        return int(match.group(1))

    p_pr = paragraph._p.pPr
    if p_pr is None:
        return 0
    outline = p_pr.find(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}outlineLvl"
    )
    if outline is None:
        return 0
    raw = outline.get(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val"
    )
    try:
        return int(raw) + 1
    except (TypeError, ValueError):
        return 0


def _matching_headings(
    doc: _Document,
    variants: dict[str, Any],
) -> dict[str, list[Paragraph]]:
    matches: dict[str, list[Paragraph]] = {str(key): [] for key in variants}
    for paragraph in doc.paragraphs:
        if _heading_level(paragraph) <= 0:
            continue
        title = _compact(paragraph.text)
        if not title:
            continue
        for variant_id, rule in variants.items():
            markers = [
                _compact(marker)
                for marker in (rule or {}).get("heading_markers", [])
                if _compact(marker)
            ]
            if markers and all(marker in title for marker in markers):
                matches[str(variant_id)].append(paragraph)
    return matches


def _delete_heading_section(paragraph: Paragraph) -> int:
    """删除标题及其内容，直到下一个同级或更高层级标题。"""
    start = paragraph._p
    body = start.getparent()
    if body is None:
        raise ValueError("模板标题没有正文父节点")
    children = list(body)
    try:
        start_index = children.index(start)
    except ValueError as exc:
        raise ValueError("模板标题不在主文档正文中") from exc
    level = _heading_level(paragraph)
    end_index = len(children)
    for index in range(start_index + 1, len(children)):
        child = children[index]
        if not child.tag.endswith("}p"):
            continue
        candidate = Paragraph(child, paragraph._parent)
        candidate_level = _heading_level(candidate)
        if candidate_level and candidate_level <= level:
            end_index = index
            break

    removed = 0
    for child in children[start_index:end_index]:
        # 文档末尾 sectPr 不是章节内容，不能删除。
        if child.tag.endswith("}sectPr"):
            continue
        parent = child.getparent()
        if parent is not None:
            parent.remove(child)
            removed += 1
    return removed


def apply_template_variant_policy(
    doc: _Document,
    *,
    organization_scope: str,
    out_path: str | Path,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    policy = load_template_variant_policy(policy_path)
    scope = normalize_organization_scope(organization_scope, policy_path)
    allowed = allowed_organization_scopes(policy_path)
    audit: dict[str, Any] = {
        "schema_version": "template-variant-audit-v1",
        "policy_path": str(Path(policy_path).resolve()),
        "selectors": {
            "organization_scope": {
                "value": scope,
                "label": allowed[scope],
            }
        },
        "groups": [],
        "passed": True,
        "errors": [],
    }

    for group in policy.get("mutually_exclusive_groups", []):
        group_id = str(group.get("id") or "").strip()
        selector = str(group.get("selector") or "").strip()
        variants = group.get("variants") or {}
        if selector != "organization_scope":
            raise ValueError(f"不支持的模板分支选择器: {selector}")
        if scope not in variants:
            raise ValueError(f"模板分支组 {group_id} 不支持 {scope}")

        before = _matching_headings(doc, variants)
        group_audit: dict[str, Any] = {
            "id": group_id,
            "selector": selector,
            "selected_variant": scope,
            "matched_before": {
                key: [paragraph.text for paragraph in paragraphs]
                for key, paragraphs in before.items()
            },
            "removed": [],
        }

        if len(before.get(scope, [])) != 1:
            message = (
                f"模板分支组 {group_id} 的选中分支 {scope} "
                f"匹配到 {len(before.get(scope, []))} 个标题，要求恰好1个"
            )
            audit["passed"] = False
            audit["errors"].append(message)
        for variant_id, paragraphs in before.items():
            if variant_id == scope:
                continue
            if len(paragraphs) != 1:
                message = (
                    f"模板分支组 {group_id} 的排除分支 {variant_id} "
                    f"匹配到 {len(paragraphs)} 个标题，要求恰好1个"
                )
                audit["passed"] = False
                audit["errors"].append(message)

        if not audit["passed"]:
            audit_path = Path(out_path).with_suffix(".template_variant_audit.json")
            audit_path.write_text(
                json.dumps(audit, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            raise ValueError("；".join(audit["errors"]))

        for variant_id, paragraphs in before.items():
            if variant_id == scope:
                continue
            paragraph = paragraphs[0]
            removed_nodes = _delete_heading_section(paragraph)
            group_audit["removed"].append(
                {
                    "variant": variant_id,
                    "heading": paragraph.text,
                    "removed_nodes": removed_nodes,
                }
            )

        after = _matching_headings(doc, variants)
        remaining = {
            key: [paragraph.text for paragraph in paragraphs]
            for key, paragraphs in after.items()
            if paragraphs
        }
        group_audit["matched_after"] = remaining
        group_audit["passed"] = (
            len(after.get(scope, [])) == 1
            and all(not paragraphs for key, paragraphs in after.items() if key != scope)
        )
        if not group_audit["passed"]:
            audit["passed"] = False
            audit["errors"].append(f"模板分支组 {group_id} 裁剪后仍不满足互斥约束")
        audit["groups"].append(group_audit)

    audit_path = Path(out_path).with_suffix(".template_variant_audit.json")
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not audit["passed"]:
        raise ValueError("；".join(audit["errors"]))
    return audit
