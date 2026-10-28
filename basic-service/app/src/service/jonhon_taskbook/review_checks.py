"""Checks and source links for a saved revision. Never calls a generation model."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from lxml import etree
import yaml

from jonhon_taskbook.review_store import now


def flatten_blocks(blocks):
    for block in blocks:
        yield block
        if block.get("kind") == "table":
            for row in block.get("rows", []):
                for cell in row.get("cells", []):
                    yield from flatten_blocks(cell.get("blocks", []))


def _text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _asset(store, jid, asset_id):
    try:
        return store.asset_path(jid, asset_id)
    except FileNotFoundError:
        return None


def _ledger(store, jid, path):
    from jonhon_taskbook.coverage_ledger import (
        CoverageLedger, mark_covered_from_output, mark_exact_fragment_coverage,
        mark_structured_indicator_coverage,
    )
    evidence = _asset(store, jid, "evidence_coverage_ledger")
    if not evidence:
        return None
    ledger = CoverageLedger.load(evidence)
    # All three methods read the current XML. Original body positions are not trusted.
    with tempfile.TemporaryDirectory(prefix="review-evidence-") as directory:
        checked = Path(directory) / "revision.docx"
        shutil.copy2(path, checked)
        for suffix in ("requirement_classification", "effective_requirement_classification", "indicator_audit"):
            sidecar = _asset(store, jid, "evidence_" + suffix)
            if sidecar:
                shutil.copy2(sidecar, checked.with_suffix("." + suffix + ".json"))
        mark_covered_from_output(ledger, str(checked))
        mark_exact_fragment_coverage(ledger, str(checked))
        mark_structured_indicator_coverage(ledger, str(checked))
    return ledger


def review_links(store, jid: str, revision_id: str) -> dict:
    from jonhon_taskbook.review_document import document_projection
    path = store.revision_path(jid, revision_id)
    output = document_projection(path, revision_id=revision_id)
    output_blocks = list(flatten_blocks(output["blocks"]))
    paragraphs = [item for item in output_blocks if item.get("kind") == "paragraph" and _text(item.get("text"))]
    links, warnings = [], []
    unique_tech_links = {}
    bundle = store.get_review(jid)
    policy_path = _asset(store, jid, "rule_development_process_policy")
    retention = (yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}).get("section_retention_rules", []) if policy_path else []
    process = bundle["selection"].get("development_process", "")
    for asset in bundle["assets"]:
        if asset["role"] not in {"tech", "spec", "template", "template_original"} or not asset["available"]:
            continue
        if asset["format"] != "docx":
            warnings.append(f"{asset['label']}的精确来源联动仅在 DOCX 原文中提供，请结合原文件核对。")
            continue
        source = document_projection(store.asset_path(jid, asset["id"]), asset_id=asset["id"])
        source_blocks = list(flatten_blocks(source["blocks"]))
        outline_by_id = {item["id"]: item for item in source.get("outline", [])}
        for block in source_blocks:
            for picture in block.get("images", []):
                if not picture.get("available") or not picture.get("src"):
                    continue
                image_matches = [item for item in output_blocks if any(
                    image.get("available") and image.get("src") == picture["src"] for image in item.get("images", [])
                )]
                source_count = sum(image.get("available") and image.get("src") == picture["src"]
                                   for item in source_blocks for image in item.get("images", []))
                image_unique = len(image_matches) == 1 and source_count == 1
                links.append({"id": f"{asset['id']}-{picture['id']}", "source_asset_id": asset["id"],
                              "source_element_ids": [block["id"]], "output_element_ids": [item["id"] for item in image_matches],
                              "status": "verified" if image_unique else "candidate" if image_matches else "unmapped",
                              "label": block.get("text") or "文档图片", "reason": "来源与当前修订版图片一致且位置唯一" if image_unique else
                                  "图片重复，需结合图题核对位置" if image_matches else "当前版本尚未找到相同图片"})
            raw = _text(block.get("text", ""))
            if block.get("kind") != "paragraph" or len(raw) < 4:
                continue
            matches = [item for item in paragraphs if raw == _text(item.get("text")) or
                       (len(raw) >= 12 and raw in _text(item.get("text")))]
            # Repeated text has no unique section identity. Do not pretend precision.
            unique_source = sum(_text(item.get("text")) == raw for item in source_blocks) == 1
            status = "verified" if len(matches) == 1 and unique_source else "candidate" if matches else "unmapped"
            if asset["role"] in {"spec", "template_original"} and not matches:
                continue
            link = {"id": f"{asset['id']}-{block['id']}", "source_asset_id": asset["id"],
                          "source_element_ids": [block["id"]], "output_element_ids": [item["id"] for item in matches],
                          "status": status, "label": block.get("text", "")[:180],
                          "reason": "当前修订版中找到唯一完整原文" if status == "verified" else
                              "存在重复原文，需确认对应章节" if matches else "尚未验证写入位置，可能已拆分、按规则省略或人工改写"}
            if not matches and asset["role"] == "template":
                ancestors = []
                section_id = block.get("section_id")
                while section_id in outline_by_id:
                    entry = outline_by_id[section_id]
                    ancestors.append(_text(entry.get("text", entry.get("title", ""))))
                    section_id = entry.get("parent_id")
                for rule in retention:
                    titles = rule.get("semantic_titles", []) + rule.get("linked_semantic_titles", [])
                    if process not in rule.get("keep_processes", []) and any(_text(title) in ancestor for title in titles for ancestor in ancestors):
                        link.update(rule_excluded=True, reason=f"按生成时规则省略：{process}不保留{rule.get('label', titles[0])}及其关联内容")
                        break
            links.append(link)
            if unique_source and asset["id"] == "tech":
                unique_tech_links[raw] = link
    # Fresh deterministic evidence may establish split paragraphs/table entries.
    ledger = _ledger(store, jid, path)
    if ledger:
        for block in ledger.blocks:
            matched = unique_tech_links.get(_text(block.raw_text))
            if not matched or matched["status"] != "unmapped" or not block.covered:
                continue
            nodes = [item for item in output["blocks"] if item.get("source_body_index") in block.output_body_indices]
            def signature(node):
                return (node.get("kind"), _text("".join(item.get("text", "") for item in flatten_blocks([node]))))
            unique_positions = bool(nodes) and all(
                signature(node)[1] and sum(signature(other) == signature(node) for other in output["blocks"]) == 1
                for node in nodes
            )
            if nodes:
                matched.update(status="verified" if unique_positions else "candidate", output_element_ids=[item["id"] for item in nodes],
                               reason="已针对当前修订版重新验证原文/表格/指标证据" if unique_positions else "原文有覆盖证据，但所在段落重复，需确认具体位置")
    return {"revision_id": revision_id, "sha256": output["sha256"], "links": links, "warnings": warnings}


def check_review_revision(store, jid: str, revision_id: str, path: Path, *, independent_review: bool = False) -> dict:
    from jonhon_taskbook.review_document import document_projection
    from jonhon_taskbook.qa_gate import QAGate
    from jonhon_taskbook.qa_policy import load_configured_qa_policy
    issues = []
    results = {}
    bundle = store.get_review(jid)
    revision = store.revision(jid, revision_id)
    report = {"revision_id": revision_id, "sha256": revision["sha256"], "checked_at": now(),
              "scope": "revision_deterministic", "delivery_approved": False, "issues": issues,
              "results": results, "status": "needs_review"}
    def issue(code, message, severity="warning", element_id=None):
        item = {"code": code, "message": str(message), "severity": severity}
        if element_id:
            item["element_id"] = element_id
        issues.append(item)
    try:
        projection = document_projection(path, revision_id=revision_id)
        blocks = list(flatten_blocks(projection["blocks"]))
        for block in blocks:
            if "【人工填写】" in block.get("text", ""):
                issue("manual_fill", "仍有【人工填写】项，请核对并补齐适用内容", element_id=block["id"])
        ledger = _ledger(store, jid, path)
        if ledger:
            results["coverage"] = {"total": ledger.total, "covered": ledger.covered_count,
                                   "unverified": len(ledger.uncovered)}
            for block in ledger.uncovered:
                issue("source_unverified", f"原需求尚未在当前修订版中验证：{(block.raw_text or block.summary)[:200]}")
        else:
            issue("coverage_evidence_missing", "没有本次生成的覆盖率账本，无法自动复核需求完整性")

        indicator_audit = _asset(store, jid, "evidence_indicator_audit")
        if indicator_audit:
            from jonhon_taskbook.business_value_gate import audit_indicator_values
            values = audit_indicator_values(path, indicator_audit, persist=False)
            results["indicator_values"] = values
            for blocker in values["blockers"]:
                expected, actual = blocker.get("expected"), blocker.get("actual")
                detail = f"；生成依据：{expected}；修订内容：{actual}" if expected is not None else ""
                locations = [item["id"] for item in blocks if actual and _text(item.get("text")) == _text(actual)]
                issue("indicator_" + blocker["code"].lower(), blocker["message"] + detail, "error",
                      locations[0] if len(locations) == 1 else None)
        else:
            issue("indicator_evidence_missing", "没有归档的指标审计账本，指标值及适用规格需要人工核对")

        policy = _asset(store, jid, "rule_qa_gate")
        profile = _asset(store, jid, "profile")
        template = _asset(store, jid, "effective_template")
        if policy and profile and template:
            cfg = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
            selection = bundle["selection"]
            rules, flags, _ = load_configured_qa_policy(
                cfg, preserve_template_guidance=bool(selection.get("preserve_unfilled_template", True)),
                selected_product_domain=selection.get("product_domain", ""), config_path=policy,
            )
            flags["template_path"] = str(template)
            with zipfile.ZipFile(path) as package:
                root = etree.fromstring(package.read("word/document.xml"), etree.XMLParser(resolve_entities=False, no_network=True))
            gate = QAGate(rules, flags).check(root)
            results["configured_qa"] = gate
            for message in gate["block_reasons"]:
                issue("configured_qa", message, "error")
            for message in gate["warnings"]:
                issue("configured_qa_warning", message)
        else:
            issue("rule_snapshot_missing", "生成时的质量规则、产品规则或模板快照缺失；没有使用当前规则代替检查")

        process_policy = _asset(store, jid, "rule_development_process_policy")
        if process_policy:
            policy_data = yaml.safe_load(process_policy.read_text(encoding="utf-8")) or {}
            process = bundle["selection"].get("development_process", "")
            headings = [item for item in blocks if item.get("heading_level")]
            template_headings = []
            if template:
                template_document = document_projection(template)
                template_headings = [item for item in flatten_blocks(template_document["blocks"]) if item.get("heading_level")]
            for rule in policy_data.get("section_retention_rules", []):
                if process in rule.get("keep_processes", []):
                    groups = [rule.get("semantic_titles", [])] + [[title] for title in rule.get("linked_semantic_titles", [])]
                    for titles in groups:
                        present_in_template = any(_text(title) in _text(heading.get("text")) for title in titles for heading in template_headings)
                        retained = any(_text(title) in _text(heading.get("text")) for title in titles for heading in headings)
                        if present_in_template and not retained:
                            issue("process_section_missing", f"{process}应保留的章节缺失：{titles[0]}", "error")
                    continue
                for title in rule.get("semantic_titles", []) + rule.get("linked_semantic_titles", []):
                    for heading in headings:
                        if _text(title) in _text(heading.get("text")):
                            issue("process_section", f"{process}应删除章节：{title}", "error", heading["id"])

        baseline = store.revision(jid, "baseline")
        if revision["sha256"] != baseline["sha256"]:
            issue("manual_changes", "正文已人工修改；原生成报告不适用于当前版本，修改内容及指标适用性须人工复核",
                  "info" if independent_review else "warning")
        issue("scope_limit", "本检查复核 DOCX、归档规则和原文覆盖；未重新运行模型，不构成自动交付批准", "info")
        if any(item["severity"] == "error" for item in issues):
            report["status"] = "failed"
        elif any(item["severity"] == "warning" for item in issues) or bundle["generation_status"] != "done":
            report["status"] = "needs_review"
        else:
            report["status"] = "passed"
    except Exception as exc:
        issue("check_execution_error", f"检查未完成：{type(exc).__name__}。请查看运行日志或重新检查。", "error")
        import logging
        logging.getLogger(__name__).exception("Review revision check failed jid=%s revision=%s", jid, revision_id)
        report["status"] = "error"
    return report
