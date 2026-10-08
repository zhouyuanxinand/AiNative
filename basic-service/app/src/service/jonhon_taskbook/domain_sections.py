"""Quality-system chapter selection from workbook 开发逻辑 C55."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from .template_scanner import heading_level, semantic_title

POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "standard_applicability.yaml"


def apply_domain_sections(doc, domain: str) -> dict[str, Any]:
    """Remove unselected domain chapters and explicit conditional table branches.

    Display numbering and table positions are not chapter identities. A source
    standard quoted in ordinary prose is never interpreted as a chapter rule.
    """
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
    aliases = policy.get("domain_aliases") or {}
    selected = str(domain or "").strip()
    selected = str(aliases.get(selected, selected)).lower()
    audit: dict[str, Any] = {
        "domain": selected,
        "selected": bool(selected),
        "deleted_sections": [],
        "deleted_semantic_headings": [],
        "deleted_table_branches": [],
    }
    if not selected:
        return audit
    if selected not in {"military", "airworthiness", "civil_aviation", "as9100"}:
        raise ValueError(f"未知质量管理体系分类: {domain}")

    rules = policy.get("domain_section_rules") or []
    table_rules = policy.get("domain_table_branch_rules") or []
    reference_titles = policy.get("reference_heading_markers") or []

    def prune_container(container, inherited_headings=()) -> None:
        blocks = list(container)
        headings = list(inherited_headings)
        index = 0
        while index < len(blocks):
            node = blocks[index]
            if node.tag == qn("w:sdt"):
                content = node.find(qn("w:sdtContent"))
                if content is not None:
                    prune_container(content, headings)
            if node.tag != qn("w:p"):
                index += 1
                continue
            paragraph = Paragraph(node, doc)
            depth = heading_level(paragraph)
            title = semantic_title(paragraph.text)
            compact = re.sub(r"\s+", "", title).upper()
            if depth:
                headings = [(level, text) for level, text in headings if level < depth]
                headings.append((depth, title))
            else:
                branch_matches = [
                    rule for rule in table_rules
                    if any(
                        marker in heading
                        for marker in rule["section_markers"]
                        for _, heading in headings
                    ) and any(re.search(pattern, compact) for pattern in rule["paragraph_patterns"])
                ]
                allowed = {
                    str(value).lower()
                    for rule in branch_matches for value in rule["allowed_domains"]
                }
                table_index = index + 1
                while table_index < len(blocks) and blocks[table_index].tag == qn("w:p"):
                    following = Paragraph(blocks[table_index], doc)
                    if following.text.strip() or heading_level(following):
                        break
                    table_index += 1
                if (
                    branch_matches and selected not in allowed
                    and table_index < len(blocks) and blocks[table_index].tag == qn("w:tbl")
                ):
                    for deleted in blocks[index:table_index + 1]:
                        container.remove(deleted)
                    audit["deleted_table_branches"].append({
                        "section_heading": headings[-1][1],
                        "condition": paragraph.text,
                        "allowed_domains": sorted(allowed),
                        "removed_nodes": table_index + 1 - index,
                        "reason": "开发逻辑!C55：删除未选择的质量管理体系专用表格分支",
                    })
                    index = table_index + 1
                    continue
            # 引用标准标题本身可以说明 AS9100 等标准族，不表示领域专章。
            if not depth or any(marker in title for marker in reference_titles):
                index += 1
                continue
            matches = [
                rule for rule in rules
                if any(str(marker).upper() in compact for marker in rule["heading_markers"])
            ]
            allowed = {
                str(value).lower()
                for rule in matches for value in rule["allowed_domains"]
            }
            if not matches or selected in allowed:
                index += 1
                continue

            end = index + 1
            deleted_titles = [title]
            while end < len(blocks):
                following = blocks[end]
                if following.tag == qn("w:sectPr"):
                    break
                if following.tag == qn("w:p"):
                    following_paragraph = Paragraph(following, doc)
                    following_depth = heading_level(following_paragraph)
                    if following_depth and following_depth <= depth:
                        break
                    if following_depth:
                        deleted_titles.append(semantic_title(following_paragraph.text))
                end += 1
            for deleted in blocks[index:end]:
                container.remove(deleted)
            audit["deleted_sections"].append({
                "semantic_heading": title,
                "allowed_domains": sorted(allowed),
                "removed_nodes": end - index,
                "reason": "开发逻辑!C55：删除未选择的质量管理体系专用章节",
            })
            audit["deleted_semantic_headings"].extend(deleted_titles)
            index = end

    prune_container(doc.element.body)
    return audit
