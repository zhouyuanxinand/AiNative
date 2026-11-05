"""Local evidence search and conservative, exhaustive template gap accounting.

The output is a routing/evidence plan. It never manufactures engineering prose
and never changes the submitted source documents.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.table import Table

from jonhon_taskbook.template_scanner import heading_level, semantic_title, scan_template_tree


FIELDS = ("product_type", "product_domain", "development_process", "cover_phase",
          "product_series", "organization_scope")
FIELD_LABELS = {
    "product_type": ("产品类型",), "product_domain": ("产品领域", "质量体系"),
    "development_process": ("研制流程", "研制流程分类"), "cover_phase": ("研制阶段",),
    "product_series": ("产品系列", "产品型号"), "organization_scope": ("组织范围", "产品归属范围"),
}
PLACEHOLDER = re.compile(r"【人工填写】|【请人工标注】|待(?:填写|补充|确定|定)|请填写|[＿_]{3,}|[xX]{3,}|[□]{2,}")


class EvidenceBlocked(ValueError):
    pass


def sha256(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def context_of(snapshot):
    raw = snapshot.get("context") or snapshot.get("parameters") or {}
    return {key: str(raw.get(key) or "").strip() for key in FIELDS}


def validate_sources(snapshot):
    """Validate the fixed bytes before *every* action, including verify."""
    for source in snapshot.get("sources", []):
        for scope in ("project_id", "case_id"):
            if source.get(scope) and source[scope] != snapshot.get(scope):
                raise EvidenceBlocked(f"来源 {source.get('id')} 的 {scope} 与本案例不一致")
        if source.get("role") not in {"tech", "spec", "reference"}:
            raise EvidenceBlocked(f"来源 {source.get('id')} 的资料角色不受支持")
        path = Path(source.get("path") or "")
        if not path.is_file():
            raise EvidenceBlocked(f"来源 {source.get('id')} 文件缺失")
        if not source.get("sha256") or sha256(path) != source["sha256"]:
            raise EvidenceBlocked(f"来源 {source.get('id')} hash 与提交快照不一致")
        if not isinstance(source.get("version"), int) or source["version"] < 1:
            raise EvidenceBlocked(f"来源 {source.get('id')} 版本无效")
        if source.get("binding_mode", source.get("mode", "local_real")) != "local_real":
            raise EvidenceBlocked(f"来源 {source.get('id')} 不是本地真实资料")


def evidence_blocks(sources, work_dir):
    """Return exact quotes with original body/table locations; no filename guesses."""
    blocks = []
    for source in sources:
        path = source_input_path(source, work_dir)
        normalization = None
        if path.suffix.lower() in {".txt", ".md"}:
            for index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines()):
                if line.strip():
                    blocks.append(_block(source, line.strip(), {"line": index + 1, "body_index": index}, ""))
            continue
        if path.suffix.lower() != ".docx":
            from jonhon_taskbook.input_normalizer import normalize_input
            normalized = normalize_input(path, Path(work_dir) / "normalized" / source["id"])
            path = normalized.path
            # Reading a converted source is not approval of its fidelity. Keep
            # the original hash and the conversion obligation through generation.
            normalization = {"method": normalized.method, "requires_review": normalized.requires_review,
                             "normalized_sha256": sha256(path), "warnings": list(normalized.warnings)}
        try:
            document = Document(path)
        except Exception as exc:
            raise EvidenceBlocked(f"来源 {source['id']} 不是可读取的 Word 资料") from exc
        current = ""
        first_block = len(blocks)
        for body_index, element in enumerate(document.element.body):
            if element.tag == qn("w:p"):
                paragraph = Paragraph(element, document)
                text = paragraph.text.strip()
                if not text:
                    continue
                if heading_level(paragraph):
                    current = semantic_title(text)
                else:
                    blocks.append(_block(source, text, {"body_index": body_index}, current))
            elif element.tag == qn("w:tbl"):
                table = Table(element, document)
                for row_index, row in enumerate(table.rows):
                    values = [cell.text.strip() for cell in row.cells]
                    if any(values):
                        blocks.append(_block(source, " | ".join(values),
                                             {"body_index": body_index, "row": row_index}, current))
        if normalization:
            for block in blocks[first_block:]:
                block["normalization"] = normalization
    return blocks


def source_input_path(source, work_dir):
    """Store uses opaque blob names; preserve the uploaded format on a copy."""
    original = Path(source["path"])
    suffix = Path(source.get("name") or original.name).suffix.lower()
    if not suffix:
        raise EvidenceBlocked(f"来源 {source['id']} 缺少可识别的原始文件格式")
    if original.suffix.lower() == suffix:
        return original
    target = Path(work_dir) / "inputs" / (str(source["id"]) + suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, target)
    return target


def _block(source, text, location, heading):
    return {"source_id": source["id"], "role": source["role"], "sha256": source["sha256"],
            "version": source["version"], "location": location, "quote": text, "heading": heading}


def labeled_values(blocks, labels):
    result = []
    pattern = re.compile(r"^(?:" + "|".join(re.escape(label) for label in labels) + r")\s*[:：]\s*(.+?)\s*$")
    for block in blocks:
        match = pattern.match(block["quote"])
        if match:
            result.append({**block, "value": match.group(1).strip()})
    return result


def canonical_value(field, value):
    from jonhon_taskbook.template_registry import list_product_catalog
    if field == "product_type":
        for item in list_product_catalog():
            if value in {item["value"], item["label"]}:
                return item["value"]
        # Unknown identity is retained for candidate asset planning, never mapped
        # to a different product just because that product has a template.
        return value
    if field == "product_domain":
        domains = {domain["label"]: domain["value"]
                   for item in list_product_catalog() for domain in item["domains"]}
        return domains.get(value, value)
    if field == "development_process":
        from jonhon_taskbook.development_process_policy import normalize_development_process
        return normalize_development_process(value) if value else ""
    if field == "cover_phase":
        from jonhon_taskbook.cover_fields import normalize_cover_phase
        return normalize_cover_phase(value)
    if field == "organization_scope":
        from jonhon_taskbook.template_variant_policy import normalize_organization_scope
        return normalize_organization_scope(value)
    return value


def resolve_context(snapshot, blocks):
    context = context_of(snapshot)
    provenance, candidates, missing, reasons = {}, {}, [], []
    for field in FIELDS:
        found = []
        for candidate in labeled_values(blocks, (*FIELD_LABELS[field], field)):
            try:
                candidate["value"] = canonical_value(field, candidate["value"])
            except ValueError:
                continue
            found.append(candidate)
        candidates[field] = found
        if context[field]:
            try:
                context[field] = canonical_value(field, context[field])
            except ValueError as exc:
                reasons.append(str(exc))
            provenance[field] = {"kind": "submitted_context", "value": context[field]}
        else:
            trusted = [item for item in found if item["role"] != "reference"]
            values = {item["value"] for item in trusted}
            if len(values) == 1:
                chosen = trusted[0]
                context[field] = chosen["value"]
                provenance[field] = chosen
        if not context[field]:
            missing.append({"id": f"context:{field}", "field": field, "status": "blocked",
                            "reason": "缺少唯一有来源的参数依据", "candidates": found})
    route = (snapshot.get("product_route") or {}).get("value", "")
    process = context["development_process"]
    if (route == "new" and process and process != "全新") or (route == "modification" and process == "全新"):
        reasons.append(f"产品路线 {route} 与研制流程 {process} 冲突；编制路线不能改变产品路线或研制流程")
    return context, provenance, candidates, missing, reasons


def _candidate_matches(blocks, title, label=""):
    result = []
    for block in blocks:
        text = block["quote"]
        # Exact semantic heading or an explicit field is evidence; fuzzy word
        # overlap is only a retrieval hint and is never adopted as a fact.
        match = re.match(r"^" + re.escape(label or title) + r"\s*[:：]\s*(.+)$", text)
        if match:
            result.append({**block, "quote": match.group(1), "match": "explicit_label"})
        elif block.get("heading") == title and (not label or label in text):
            result.append({**block, "match": "exact_heading"})
    return result


def _generation_template_scope(template, context, profile):
    """Inspect the same in-memory deletions used by the generation engine.

    Keep original coordinates for the ledger. The uploaded template is never
    edited, and removed historical cells are accounted for separately below.
    """
    from jonhon_taskbook.development_process_policy import failure_mode_section_titles, section_retention_rules
    from jonhon_taskbook.domain_sections import apply_domain_sections
    from jonhon_taskbook.fill import _clean_change_record, _remove_semantic_section
    from jonhon_taskbook.template_variant_policy import _delete_heading_section

    planned = deepcopy(template)
    before = list(planned.element.body)
    if context.get("product_domain"):
        apply_domain_sections(planned, context["product_domain"])
    process = context.get("development_process")
    for rule in section_retention_rules():
        if process and process not in rule["keep_processes"]:
            for keys in (rule["semantic_titles"], rule.get("linked_semantic_titles", [])):
                while _remove_semantic_section(planned, keys):
                    pass
    if process in {"改型II", "改型III"}:
        titles = set(failure_mode_section_titles())
        for paragraph in list(planned.paragraphs):
            title = semantic_title(paragraph.text)
            # The engine removes the top-level failure chapter, not a test
            # procedure that merely mentions failure analysis in its title.
            if heading_level(paragraph) == 1 and any(
                title == key or re.fullmatch(re.escape(key) + r"[（(].*[）)]", title)
                for key in titles
            ):
                _delete_heading_section(paragraph)
    excluded = {index for index, element in enumerate(before) if element.getparent() != planned.element.body}
    row_counts = {element: len(Table(element, planned).rows)
                  for element in planned.element.body if element.tag == qn("w:tbl")}
    _clean_change_record(planned)
    history = {index for index, element in enumerate(before)
               if element in row_counts and len(Table(element, planned).rows) < row_counts[element]}
    indicator = None
    if ((profile or {}).get("semantic_structures", {}).get("performance_indicator") or {}).get("mode") == "indicator_table":
        for index, element in enumerate(before):
            if index in excluded or element.tag != qn("w:tbl"):
                continue
            table = Table(element, planned)
            if table.rows and len(table.rows[0].cells) >= 4 and "用户要求" in "".join(c.text for c in table.rows[0].cells):
                indicator = index
                break
    return excluded, history, indicator


def _defer_to_generation(entry, handler, reason):
    """A generation obligation is neither a source fact nor delivery approval."""
    entry.update(status="deferred_to_generation", generation_handler=handler,
                 verification_required=True, reason=reason)
    for candidate in entry["candidates"]:
        candidate["adopted"] = False
    return entry


def build_completion_ledger(template_path, context, blocks, *, profile=None, requirements=None, clarifications=None):
    """Account for all retained leaf sections, placeholders, guidance and cells."""
    from jonhon_taskbook.development_process_policy import section_retention_rules
    from jonhon_taskbook.template_variant_policy import load_template_variant_policy
    from jonhon_taskbook.template_cleanup import _is_pure_instruction_paragraph
    template = Document(template_path)
    excluded_body, history_tables, indicator_table = _generation_template_scope(template, context, profile)
    tree = scan_template_tree(str(template_path))
    body_coordinates = {element: index for index, element in enumerate(template.element.body)}
    excluded_paragraphs = {index for index, paragraph in enumerate(template.paragraphs)
                           if body_coordinates[paragraph._p] in excluded_body}
    parents = {node["parent_id"] for node in tree}
    by_paragraph = {int(node["paragraph_index"]): node for node in tree}
    removed = set()
    for rule in section_retention_rules():
        if context.get("development_process") not in rule["keep_processes"]:
            removed.update(rule["semantic_titles"])
            removed.update(rule.get("linked_semantic_titles", []))
    policy_name = (profile or {}).get("template_variant_policy")
    variant_policy = load_template_variant_policy(
        Path(__file__).resolve().parents[1] / "config" / policy_name
    ) if policy_name else load_template_variant_policy()
    for group in variant_policy.get("mutually_exclusive_groups", []):
        selected = context.get(group["selector"])
        for value, variant in group.get("variants", {}).items():
            if value == selected:
                continue
            markers = variant.get("heading_markers", [])
            for node in tree:
                if markers and all(marker in node["title"] for marker in markers):
                    removed.add(node["title"])
    ledger = []
    current = {"id": "cover", "title": "封面", "semantic_path": "封面"}
    paragraph_index = 0
    section_has_content = {}
    excluded = False
    for body_index, element in enumerate(template.element.body):
        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, template)
            node = by_paragraph.get(paragraph_index)
            paragraph_index += 1
            if body_index in excluded_body:
                continue
            if node:
                current = node
                excluded = any(title.strip() in removed for title in node["semantic_path"].split(" / "))
                section_has_content.setdefault(node["id"], False)
                continue
            if excluded:
                continue
            text = paragraph.text.strip()
            if not text:
                continue
            section_has_content[current["id"]] = True
            marker = PLACEHOLDER.search(text)
            red = any((color.get(qn("w:val")) or "").upper() in {"FF0000", "C00000", "D00000"}
                      for color in element.iter(qn("w:color")))
            if marker or red:
                kind = "manual_marker" if "【人工填写】" in text else "placeholder" if marker else "template_guidance"
                entry = _entry(current, kind, {"body_index": body_index}, text, blocks)
                if kind != "manual_marker" and _is_pure_instruction_paragraph(text):
                    _defer_to_generation(entry, "template_instruction_cleanup", "模板说明由原引擎清理；本章节实际工程内容仍需独立来源与生成后复核")
                elif kind != "manual_marker" and current["title"] == "任务书编制依据":
                    _defer_to_generation(entry, "compilation_basis", "原引擎按本次需求及规范文件建立编制依据；模板中的示例编号不是需用户补填的独立需求")
                ledger.append(entry)
        elif element.tag == qn("w:tbl") and not excluded and body_index not in excluded_body:
            section_has_content[current["id"]] = True
            table = Table(element, template)
            for row_index, row in enumerate(table.rows):
                seen = set()
                for cell_index, cell in enumerate(row.cells):
                    if cell._tc in seen:
                        continue
                    seen.add(cell._tc)
                    text = cell.text.strip()
                    marker = PLACEHOLDER.search(text) or re.search(r"20[xX]{2}\s*年", text)
                    if (not text and row_index > 0) or marker:
                        label = row.cells[0].text.strip() if cell_index > 0 else ""
                        kind = "empty_table_cell" if not text else "manual_marker" if "【人工填写】" in text else "placeholder"
                        entry = _entry(current, kind, {"body_index": body_index, "row": row_index, "cell": cell_index}, text, blocks, label)
                        column = table.rows[0].cells[cell_index].text.strip()
                        entry["column_label"] = column
                        entry["column_count"] = len(row.cells)
                        if body_index in history_tables:
                            _defer_to_generation(entry, "change_record", "原引擎删除模板历史版本并建立本次新发记录；历史行空格不是本项目工程事实缺口")
                        elif not marker and body_index == indicator_table:
                            _defer_to_generation(entry, "indicator_table", "由受控指标表装配器按本次来源构建；空模板格不是预先批准的指标，生成后检查指标来源和缺项")
                        elif not text and current["title"] == "任务进度要求" and column == "备注":
                            _defer_to_generation(entry, "optional_schedule_remark", "进度表备注允许为空；不免除节点日期、责任及交付计划的证据要求")
                        ledger.append(entry)
    accounted = {item["slot_id"] for item in ledger}
    for node in tree:
        if node["paragraph_index"] in excluded_paragraphs or node["id"] in parents or any(title in removed for title in node["semantic_path"].split(" / ")):
            continue
        if node["id"] not in accounted:
            if not section_has_content.get(node["id"]):
                entry = _entry(node, "empty_section", {"paragraph_index": node["paragraph_index"]}, "", blocks)
                if re.sub(r"\s+", "", node["title"]) == "研制任务书":
                    _defer_to_generation(entry, "document_title", "封面文档标题不是待填写的工程章节，封面实际字段由原引擎填充并核验")
                ledger.append(entry)
            else:
                ledger.append({"id": f"gap:{len(ledger)}:{node['id']}", "slot_id": node["id"],
                               "title": node["title"], "semantic_path": node["semantic_path"],
                               "kind": "retained_template_section", "status": "retained_template",
                               "candidates": [], "reason": "沿用受控模板原文；不声明为本项目已完成的工程事实"})
    existing_titles = {node["title"] for node in tree}
    for title in ((profile or {}).get("delivery_gate") or {}).get("required_headings", []):
        if title not in existing_titles and title not in removed:
            entry = _entry({"id": "profile:" + title, "title": title, "semantic_path": title},
                           "missing_mandatory_section", {}, "", blocks)
            entry.update(status="blocked", reason="目标Profile要求此章节，但受控模板中缺失；需有依据的结构适配")
            ledger.append(entry)
    for requirement in requirements or []:
        content = str(requirement.get("content") or "").strip()
        candidates = [{**block, "quote": content, "match": "case_requirement_exact_source"}
                      for block in blocks if block["source_id"] in requirement.get("source_ids", [])
                      and content and content in block["quote"]]
        for candidate in candidates:
            adoption = _clarification_adoption(requirement, candidate, clarifications or [])
            if adoption:
                candidate["adoption"] = adoption
            candidate["adopted"] = bool(not PLACEHOLDER.search(content) and
                                        (candidate["role"] in {"tech", "spec"} or adoption))
        ready = any(candidate["adopted"] for candidate in candidates)
        ledger.append({"slot_id": "requirement:" + str(requirement.get("id", "")),
                       "title": requirement.get("title", "案例需求"), "semantic_path": requirement.get("title", "案例需求"),
                       "kind": "case_requirement", "requirement_id": requirement.get("id"),
                       "status": "evidence_ready" if ready else "blocked", "candidates": candidates,
                       "reason": "已定位需求对应的本次原文" if ready else "需求尚未定位到有来源的原文；不能改写或虚构需求事实"})
    for index, entry in enumerate(ledger):
        entry["id"] = f"gap-{index + 1:04}"
    return ledger


def _clarification_adoption(requirement, candidate, clarifications):
    """An adopted reply proves only its fixed current requirement and source."""
    revision = requirement.get("revision")
    for record in clarifications:
        adoption = record.get("adoption") or {}
        if (record.get("status") != "adopted" or record.get("requirement_id") != requirement.get("id")
                or adoption.get("requirement_revision") != revision
                or adoption.get("requirement_content") != requirement.get("content")):
            continue
        if not any(item.get("revision") == revision and item.get("clarification_id") == record.get("id")
                   for item in requirement.get("history", [])):
            continue
        if not any(item.get("id") == candidate["source_id"] and item.get("sha256") == candidate["sha256"]
                   and item.get("version") == candidate["version"] for item in record.get("answer_source_snapshots", [])):
            continue
        return {"clarification_id": record["id"], "requirement_revision": revision,
                "source_id": candidate["source_id"], "source_sha256": candidate["sha256"],
                "source_version": candidate["version"]}
    return None


def _entry(node, kind, location, text, blocks, label=""):
    candidates = _candidate_matches(blocks, node["title"], label)
    trusted = [item for item in candidates if item["role"] in {"tech", "spec"} and not PLACEHOLDER.search(item["quote"])]
    # Different source paragraphs can jointly form one section, but conflicting
    # labeled values are not silently resolved by source order.
    values = {item["quote"] for item in trusted if item.get("match") == "explicit_label"}
    ready = bool(trusted) and len(values) <= 1
    for candidate in candidates:
        candidate["adopted"] = bool(ready and candidate in trusted)
    return {"slot_id": node["id"], "title": node["title"], "semantic_path": node["semantic_path"],
            "kind": kind, "location": location, "template_text": text, "field_label": label,
            "status": "evidence_ready" if ready else "blocked", "candidates": candidates,
            "reason": "定位到本次设计输入原文，交由原引擎复制并复核" if ready else "缺少明确适用的本次设计输入；候选不能自动成为工程事实"}
