"""Evidence-bound repairs followed by the same full delivery checks.

The model never writes replacement requirements here. A misplaced duplicate
can be removed only when its source and approved destination (including its
image group) are verified. Unknown or incomplete evidence remains blocked.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from .environmental_prose import is_environmental_slot, project_environmental_evidence
from .ooxml_properties import normalize_properties_xml
from .template_scanner import scan_template_tree


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _text(element):
    return "".join(node.text or "" for node in element.iter(qn("w:t"))).strip()


def _identity(text):
    # Only figure display numbering and whitespace/terminal punctuation may
    # differ. Do not allow substring matches to delete mixed requirements.
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^(?:图[0-9一二三四五六七八九十百]+|Fig(?:ure)?\.?\d+)", "<figure>", text,
                  flags=re.IGNORECASE)
    return text.rstrip("。；;")


def _media(document, element):
    result = set()
    for node in element.iter():
        for key in (qn("r:embed"), qn("r:id")):
            relation = node.get(key)
            part = document.part.related_parts.get(relation)
            if part is not None and str(part.content_type).startswith("image/"):
                result.add(hashlib.sha256(part.blob).hexdigest())
    return result


def _sections(path, document):
    tree = scan_template_tree(str(path))
    headings = {node["id"]: document.paragraphs[node["paragraph_index"]]._p for node in tree}
    levels = {headings[node["id"]]: int(node["level"]) for node in tree}
    sections = {}
    for slot in tree:
        elements, current = [], headings[slot["id"]].getnext()
        while current is not None:
            if current in levels and levels[current] <= int(slot["level"]):
                break
            elements.append(current)
            current = current.getnext()
        sections[slot["id"]] = elements
    return {node["id"]: node for node in tree}, sections


def propose_repairs(path, plan, classification, semantic_report):
    """Return only source-verified duplicate removals and schema format repairs."""
    path = Path(path)
    document = Document(path)
    slots, sections = _sections(path, document)
    body_indices = {element: index for index, element in enumerate(document.element.body)}
    sources = {str(block["id"]): block for block in (plan or {}).get("source_blocks", [])}
    sources.update({str(block["id"]): block for block in (classification or {}).get("source_blocks", [])})
    categories = {}
    for item in (classification or {}).get("classifications", []):
        categories.setdefault(str(item.get("source_id")), set()).add(str(item.get("category")))
    documents, actions, handled = {}, [], set()

    def original(block):
        source_path = block.get("source_path")
        index = block.get("body_index")
        if not source_path or type(index) is not int or index < 0:
            raise ValueError("source coordinates unavailable")
        if source_path not in documents:
            documents[source_path] = Document(source_path)
        doc = documents[source_path]
        element = doc.element.body[index]
        if block.get("is_fragment") or block.get("parent_source_id"):
            raise ValueError("mixed fragments require replanning")
        if block.get("text") and not str(block["text"]).startswith("[图片对象"):
            if _identity(_text(element)) != _identity(str(block["text"])):
                raise ValueError("source text no longer matches classification")
        return doc, element

    for finding in (semantic_report or {}).get("violations", []):
        if finding.get("code") != "ENVIRONMENTAL_UNEXPECTED_CONTENT":
            continue
        wrong_slot = str(finding.get("target_slot", ""))
        if not is_environmental_slot(slots.get(wrong_slot)):
            continue
        ids = list(dict.fromkeys(finding.get("source_ids") or []))
        if len(ids) != 1 or ids[0] not in sources:
            continue
        source_id, block = ids[0], sources[ids[0]]
        try:
            source_doc, source_element = original(block)
            if project_environmental_evidence(block, source_element, categories=categories.get(source_id, ())):
                continue
            if _media(source_doc, source_element) or not _text(source_element):
                continue
            routes = {
                str(decision["target_slot"])
                for decision in (plan or {}).get("decisions", [])
                if decision.get("operation") == "copy_exact"
                and source_id in decision.get("source_ids", [])
                and float(decision.get("confidence", 0)) >= 0.60
                and decision.get("target_slot") in slots
                and not is_environmental_slot(slots[decision["target_slot"]])
            }
            if len(routes) != 1:
                continue
            correct_slot = next(iter(routes))
            correct_elements = sections[correct_slot]
            expected = _identity(_text(source_element))
            if not any(_identity(_text(el)) == expected for el in correct_elements):
                continue
            # A caption's approved destination must retain its actual image;
            # textual caption matches alone are not proof of a complete group.
            group_id = block.get("media_group_id")
            if expected.startswith("<figure>") and not group_id:
                continue
            if group_id:
                group = [item for item in sources.values() if item.get("media_group_id") == group_id]
                required_media = set()
                group_complete = True
                for member in group:
                    member_doc, member_element = original(member)
                    required_media.update(_media(member_doc, member_element))
                    member_text = _identity(_text(member_element))
                    if member_text and not any(_identity(_text(el)) == member_text for el in correct_elements):
                        group_complete = False
                present_media = set().union(*(_media(document, el) for el in correct_elements))
                if not group_complete or not required_media or not required_media <= present_media:
                    continue
            for element in sections[wrong_slot]:
                index = body_indices[element]
                if (element.tag != qn("w:p") or index in handled or _media(document, element)
                        or _identity(_text(element)) != expected):
                    continue
                handled.add(index)
                actions.append({
                    "code": "REMOVE_VERIFIED_ENVIRONMENTAL_DUPLICATE",
                    "source_id": source_id, "source_path": block["source_path"],
                    "source_body_index": block["body_index"], "output_body_index": index,
                    "wrong_slot": wrong_slot, "retained_slot": correct_slot,
                    "text": _text(element), "media_group_id": group_id or "",
                })
        except (OSError, ValueError, IndexError, KeyError):
            # Unverifiable input is not permission to remove content.
            continue

    counts = {}
    with ZipFile(path) as package:
        for name in package.namelist():
            if name.startswith("word/") and name.endswith(".xml"):
                _, stats = normalize_properties_xml(package.read(name))
                for key, count in stats.items():
                    counts[key] = counts.get(key, 0) + count
    if any(counts.values()):
        actions.append({"code": "NORMALIZE_WORD_PROPERTIES", "counts": counts})
    return actions


def _apply(path, actions, classification=None):
    """Modify a separate candidate, never the source document or prior round."""
    with ZipFile(path) as package:
        entries = [(item, package.read(item.filename)) for item in package.infolist()]
    document_xml = next(data for item, data in entries if item.filename == "word/document.xml")
    root = etree.fromstring(document_xml)
    body = root.find(qn("w:body"))
    removals = [action for action in actions if action["code"] == "REMOVE_VERIFIED_ENVIRONMENTAL_DUPLICATE"]
    for action in sorted(removals, key=lambda item: item["output_body_index"], reverse=True):
        element = body[action["output_body_index"]]
        if _text(element) != action["text"]:
            raise ValueError("candidate changed after repair proposal")
        body.remove(element)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as package:
        for item, data in entries:
            if item.filename == "word/document.xml" and removals:
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            if item.filename.startswith("word/") and item.filename.endswith(".xml"):
                data, _ = normalize_properties_xml(data)
            package.writestr(item, data)
    if removals:
        from .figure_references import synchronize_figure_references

        synchronize_figure_references(path, classification)


def _copy_artifacts(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    for item in source.parent.glob(source.stem + ".*"):
        if item.is_file() and item != source and item.suffix != ".docx":
            shutil.copy2(item, destination.parent / item.name)


def run_auto_repair(out_path, semantic_plan, requirement_classification, *, evaluate, max_rounds=2, cb=print):
    """Try at most two verified repairs; accept only without quality regression."""
    output = Path(out_path)
    snapshot = evaluate(str(output))
    audit_root = output.parent / (output.stem + ".auto_repair") / uuid.uuid4().hex[:12]
    audit_root.mkdir(parents=True)
    audit = {"policy": "source_verified_repairs", "max_rounds": min(2, max(0, max_rounds)),
             "rounds": [], "accepted_rounds": 0, "stop_reason": "round_limit"}

    def save_json(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    for number in range(1, audit["max_rounds"] + 1):
        actions = propose_repairs(output, semantic_plan, requirement_classification, snapshot.get("semantic_integrity"))
        if not actions:
            audit["stop_reason"] = "no_verified_repair"
            break
        cb(f"🔧 自动修复第 {number} 轮：{len(actions)} 项有来源依据的修复，随后重新执行全部门禁")
        folder = audit_root / f"round-{number:02}"
        before, candidate = folder / "before" / output.name, folder / "candidate" / output.name
        _copy_artifacts(output, before)
        _copy_artifacts(output, candidate)
        record = {"round": number, "actions": actions, "before": str(before),
                  "candidate": str(candidate), "before_sha256": _hash(output), "accepted": False}
        before_snapshot = deepcopy(snapshot)
        save_json(folder / "before.json", before_snapshot)
        publishing = False
        prior_files = {item.name for item in output.parent.glob(output.stem + ".*") if item.is_file()}

        def restore_before():
            for item in output.parent.glob(output.stem + ".*"):
                if item.is_file() and item.name not in prior_files:
                    item.unlink()
            _copy_artifacts(before, output)
            if _hash(output) != record["before_sha256"]:
                raise ValueError("rollback document does not match the saved original")
            record["rollback_restored"] = True

        try:
            _apply(candidate, actions, requirement_classification)
            record["candidate_sha256"] = _hash(candidate)
            if record["before_sha256"] == record["candidate_sha256"]:
                record["reason"] = "no_document_change"
            else:
                updated = evaluate(str(candidate))
                save_json(folder / "after.json", updated)
                old_keys, new_keys = set(snapshot.get("blocking_keys", [])), set(updated.get("blocking_keys", []))
                old_covered, new_covered = set(snapshot.get("covered_source_ids", [])), set(updated.get("covered_source_ids", []))
                remaining = propose_repairs(candidate, semantic_plan, requirement_classification, updated.get("semantic_integrity"))
                if not new_keys <= old_keys:
                    record["reason"] = "new_blocker"
                elif not old_covered <= new_covered:
                    record["reason"] = "source_coverage_regressed"
                elif not (new_keys < old_keys or len(remaining) < len(actions)):
                    record["reason"] = "no_verified_progress"
                else:
                    publishing = True
                    _copy_artifacts(candidate, output)
                    # Re-evaluate at the published path to bind every sidecar
                    # and digest to the exact file that users will download.
                    published = evaluate(str(output))
                    if (set(published.get("blocking_keys", [])) != new_keys
                            or not new_covered <= set(published.get("covered_source_ids", []))):
                        raise ValueError("published candidate did not retain its verified quality")
                    snapshot = published
                    record.update(accepted=True, reason="verified_improvement", output_sha256=_hash(output))
                    audit["accepted_rounds"] += 1
        except Exception as exc:
            record.update(reason="repair_failed", error=f"{type(exc).__name__}: {exc}")
            if publishing:
                try:
                    restore_before()
                    snapshot = evaluate(str(output))
                except Exception as rollback_exc:
                    record.update(reason="rollback_verification_failed",
                                  snapshot_origin=str(folder / "before.json"),
                                  rollback_error=f"{type(rollback_exc).__name__}: {rollback_exc}")
                    # A failing verifier may have written partial sidecars.
                    # Restore them again without attempting another evaluation.
                    try:
                        restore_before()
                    except Exception as restore_exc:
                        record.update(rollback_restored=False,
                                      rollback_restore_error=f"{type(restore_exc).__name__}: {restore_exc}")
                    snapshot = deepcopy(before_snapshot)
                    snapshot.update(qa_ok=False, delivery_gate_ok=False)
                    snapshot["blocking_keys"] = sorted(set(snapshot.get("blocking_keys", [])) | {
                        "auto_repair:ROLLBACK_VERIFICATION_FAILED",
                    })
                    result = snapshot.setdefault("result", {})
                    result.update(ok=False, delivery_status="blocked")
                    result.setdefault("meta", {}).update(qa_ok=False, delivery_status="blocked",
                                                          auto_repair_recheck_failed=True)
                    rollback_blocker = {
                        "code": "ROLLBACK_VERIFICATION_FAILED",
                        "message": "恢复后的复检失败，当前文件继续阻断交付；修复前审计证据另行保留。",
                    }
                    for current_gate in (
                        snapshot.setdefault("delivery_gate", {}),
                        result["meta"].setdefault("delivery_gate_result", {}),
                    ):
                        current_gate.update(passed=False, deliverable=False)
                        current_gate.setdefault("blockers", []).append(deepcopy(rollback_blocker))
                    restore_state = "已恢复修复前文件" if record["rollback_restored"] else "恢复修复前文件失败"
                    result.setdefault("warnings", []).append(
                        f"自动修复{restore_state}，复检失败；保留修复前审计证据并阻断交付: " + record["rollback_error"]
                    )
        audit["rounds"].append(record)
        save_json(folder / "decision.json", record)
        if not record["accepted"]:
            audit["stop_reason"] = record["reason"]
            break
    audit["output_sha256"] = _hash(output)
    audit["snapshot"] = snapshot
    audit_path = output.with_suffix(".auto_repair.json")
    audit["audit_path"] = str(audit_path)
    save_json(audit_path, audit)
    return audit
