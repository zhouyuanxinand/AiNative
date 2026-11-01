"""Read-only preflight and explicit lifecycle adoption on detached project copies.

These functions never persist a project, change an execution plan, or dispatch a
run. A caller must separately authorize and transact any eventual live import.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path


class MigrationError(ValueError):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _files(project):
    """Include historical snapshots and fixed assets, deduplicating byte reads."""
    discovered = []

    def visit(value, location):
        if isinstance(value, dict):
            parent = location.rsplit("/", 2)[-2] if "/" in location else ""
            file_collection = parent in {"sources", "source_refs", "source_snapshots", "artifacts", "upstream_artifacts", "rule_assets", "assets"}
            if "path" in value or ("sha256" in value and file_collection):
                discovered.append((value.get("id"), str(value.get("path") or ""),
                                   str(value.get("sha256") or ""), location))
            for key, item in sorted(value.items()):
                if key != "migration_receipts":
                    visit(item, location + "/" + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, location + "/" + str(index))

    visit(project, "")
    paths_by_identity = {}
    for identity, path, expected, _ in discovered:
        if identity and path and expected:
            paths_by_identity.setdefault((identity, expected), set()).add(path)
    references = {}
    for identity, path, expected, location in discovered:
        matches = paths_by_identity.get((identity, expected), set())
        if not path and len(matches) == 1:
            path = next(iter(matches))
        references.setdefault((path, expected), []).append(location)
    rows = []
    for (path, expected), locations in sorted(references.items()):
        actual = None
        if not path:
            status = "path_missing"
        else:
            try:
                actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                status = "verified" if expected == actual else "hash_mismatch" if expected else "hash_missing"
            except FileNotFoundError:
                status = "missing"
            except OSError:
                status = "unreadable"
        rows.append({"path": path, "expected_sha256": expected or None,
                     "actual_sha256": actual, "status": status, "references": locations})
    return rows


def _reference_blockers(project):
    blockers = []

    def unique(rows, kind, case_id=None):
        ids = [row.get("id") for row in rows]
        if None in ids or len(ids) != len(set(ids)):
            blockers.append({"code": "ambiguous_identity", "kind": kind, "case_id": case_id})

    unique(project["cases"], "case")
    for case in project["cases"]:
        for kind in ("sources", "requirements", "decisions", "workpackages", "requirement_baselines", "review_bundles", "rd_activations"):
            unique(case.get(kind, []), kind, case["id"])
        sources = {row["id"] for row in case.get("sources", [])}
        for requirement in case.get("requirements", []):
            if set(requirement.get("source_ids", [])) - sources:
                blockers.append({"code": "dangling_source_reference", "case_id": case["id"], "record_id": requirement["id"]})
        if set(case.get("source_selection", {}).values()) - sources:
            blockers.append({"code": "dangling_source_selection", "case_id": case["id"]})
        for package in case.get("workpackages", []):
            unique(package.get("nodes", []), "nodes", case["id"])
            unique(package.get("artifacts", []), "artifacts", case["id"])
    return blockers


def _counts(project, files):
    cases = project["cases"]
    packages = [package for case in cases for package in case.get("workpackages", [])]
    result = {"cases": len(cases), "workpackages": len(packages),
              "runs": len({package["run_id"] for package in packages if package.get("run_id")}),
              "artifacts": sum(len(package.get("artifacts", [])) for package in packages),
              "files": len(files)}
    for name in ("sources", "requirements", "clarifications", "decisions", "requirement_baselines", "review_bundles", "rd_activations"):
        result[name] = sum(len(case.get(name, [])) for case in cases)
    return result


def _facts(project):
    facts = deepcopy(project)
    facts.pop("version", None)
    facts.pop("migration_receipts", None)
    for case in facts["cases"]:
        case.pop("business_lifecycle", None)
        for name in ("requirement_baselines", "review_bundles", "rd_activations"):
            if not case.get(name):
                case.pop(name, None)
    return facts


def _target_lifecycle(project, case):
    previous = case.get("business_lifecycle") or {}
    return {"policy_version": "v2", "selection_order_id": previous.get("selection_order_id") or
            "SEL-MIG-" + _digest([project["id"], case["id"]])[:20],
            "rd_activation_state": "historical_unverified", "rd_project_code": None,
            "current_requirement_baseline_id": None, "current_selection_bundle_id": None,
            "current_selection_decision_id": None, "current_activation_id": None,
            "current_taskbook_scope_decision_id": None,
            "review_mode": "formal_review", "required_policy_ref": "enterprise-review-unconfigured",
            "local_review_enabled": False}


def _activation_evidence(case):
    """Inventory server-recorded evidence; this does not confer current authority.

    A complete reference chain is a candidate for review under the destination
    policy. Legacy stage decisions and generated documents are never candidates.
    """
    result = []
    for activation in case.get("rd_activations", []):
        decision = next((row for row in case.get("decisions", [])
                         if row.get("id") == activation.get("selection_decision_id")), {})
        baseline = next((row for row in case.get("requirement_baselines", [])
                         if row.get("id") == activation.get("requirement_baseline_id")), {})
        bundle = next((row for row in case.get("review_bundles", [])
                       if row.get("id") == activation.get("bundle_id")), {})
        records = (activation, decision, baseline, bundle)
        fixed = bundle.get("fixed_objects", {})
        baseline_payload = {key: baseline.get(key) for key in ("input_revision", "items", "source_refs", "scope")}
        complete = all(
            row and not row.get("invalidated_at") and not row.get("invalidated_reason")
            and row.get("input_revision") == case.get("input_revision")
            and all(isinstance(row.get(key), str) and row[key].strip() for key in ("id", "actor", "created_at"))
            for row in records)
        complete = complete and all(
            isinstance(row.get("scope"), str) and row["scope"].strip()
            for row in (activation, decision, baseline))
        complete = complete and (
            activation.get("status") == "active" and decision.get("kind") == "selection"
            and decision.get("verdict") == "approved" and bundle.get("kind") == "selection"
            and activation.get("bundle_id") == decision.get("bundle_id")
            and activation.get("bundle_digest") == decision.get("bundle_digest") == bundle.get("digest")
            and bundle.get("digest") == _digest({"fixed_objects": fixed, "report": bundle.get("report")})
            and bundle.get("input_digest") == _digest(fixed)
            and baseline.get("digest") == _digest(baseline_payload)
            and fixed.get("requirement_baseline_id") == baseline.get("id")
            and fixed.get("requirement_baseline_digest") == baseline.get("digest")
            and baseline.get("items") == case.get("requirements")
            and fixed.get("product_route") == case.get("product_route")
            and fixed.get("composition_route") == case.get("composition_route")
            and fixed.get("context") == case.get("context")
            and activation.get("review_mode") == decision.get("review_mode") == bundle.get("review_mode")
            and activation.get("policy_ref") == decision.get("policy_ref") == bundle.get("required_policy_ref")
        )
        result.append({"activation_id": activation.get("id"), "selection_decision_id": activation.get("selection_decision_id"),
                       "requirement_baseline_id": activation.get("requirement_baseline_id"), "bundle_id": activation.get("bundle_id"),
                       "review_mode": activation.get("review_mode"),
                       "status": "candidate_requires_policy_review" if complete else "unverified"})
    return result


def _package_reference(package):
    snapshot = package.get("snapshot") or {}
    binding = snapshot.get("taskbook_binding") or {}
    workflow = binding.get("workflow") or {}
    template = binding.get("document_template") or {}
    return {"id": package["id"], "definition_id": package.get("definition_id"),
            "definition_version": package.get("definition_version"), "run_id": package.get("run_id"),
            "node_ids": [node["id"] for node in package.get("nodes", [])],
            "action_refs": [{"node_id": node["id"], "action_id": node.get("action_id"), "action_version": node.get("action_version")}
                            for node in package.get("nodes", [])],
            "resource_refs": [{"resource_id": row.get("resource_id"), "resource_version": row.get("resource_version")}
                              for row in snapshot.get("actions", [])],
            "workflow_ref": {key: workflow.get(key) for key in ("id", "version")} if workflow else None,
            "document_template_ref": {"product_type": template.get("product_type"), "product_domain": template.get("product_domain"),
                                      "asset_digests": {key: value.get("sha256") for key, value in template.get("assets", {}).items()}} if template else None,
            "snapshot_digest": _digest(package.get("snapshot"))}


def inspect(project, *, case_ids=None):
    """Return a deterministic preview; no accepted flag or permission is implied."""
    known = {case["id"] for case in project["cases"]}
    selected = sorted(known if case_ids is None else set(case_ids))
    if not selected or set(selected) - known:
        raise MigrationError(422, "请选择项目内实际存在的案例。")
    files = _files(project)
    blockers = _reference_blockers(project) + [
        {"code": "file_unverified", "path": row["path"], "status": row["status"]}
        for row in files if row["status"] != "verified"]
    mappings, active_runs = [], []
    for case in sorted(project["cases"], key=lambda item: item["id"]):
        if case["id"] not in selected:
            continue
        previous = case.get("business_lifecycle") or {}
        policy = previous.get("policy_version", "legacy_v1")
        if policy != "legacy_v1":
            blockers.append({"code": "source_policy_not_legacy", "case_id": case["id"], "policy": policy})
        packages = case.get("workpackages", [])
        drafts = []
        for package in packages:
            if package.get("status") not in {"draft", "submitted", "running", "completed", "failed", "cancelled"}:
                blockers.append({"code": "execution_outcome_unresolved", "case_id": case["id"], "workpackage_id": package["id"]})
            if package.get("status") in {"submitted", "running"} or any(
                    node.get("status") in {"submitted", "running"} for node in package.get("nodes", [])):
                active_runs.append({"case_id": case["id"], "workpackage_id": package["id"],
                                    "run_id": package.get("run_id"), "status": package["status"],
                                    "owner_id": project.get("owner_id")})
                blockers.append({"code": "active_run_retains_owner", "case_id": case["id"], "workpackage_id": package["id"]})
            if (package.get("status") == "draft" and not package.get("run_id") and not package.get("snapshot")
                    and not package.get("artifacts") and not any(node.get("attempt", 0) for node in package.get("nodes", []))
                    and package.get("definition_id") == "taskbook" and str(package.get("definition_version")) == "1"):
                drafts.append({"source_workpackage_id": package["id"], "target_definition_id": "taskbook",
                               "target_definition_version": "2", "target_stage": "planning", "requires_new_plan": True,
                               "required_steps": ["confirm_requirements", "record_selection_decision", "authorize_rd_start", "adopt_taskbook_flow", "pull_workpackage"]})
        evidence = _activation_evidence(case)
        unknown = "rd_start_policy_review_required" if any(row["status"] == "candidate_requires_policy_review" for row in evidence) else "rd_start_evidence_incomplete" if evidence else "rd_start_evidence_missing"
        mappings.append({"case_id": case["id"], "source_policy": policy,
                         "source_stage": case.get("stage"), "target_stage": case.get("stage"),
                         "target_lifecycle": _target_lifecycle(project, case),
                         "unknown_facts": [unknown], "activation_evidence": evidence, "draft_candidates": drafts,
                         "reference_map": {"project_id": project["id"], "case_id": case["id"],
                             "source_ids": [row["id"] for row in case.get("sources", [])],
                             "decision_ids": [row["id"] for row in case.get("decisions", [])],
                             "workpackages": [_package_reference(package) for package in packages]}})
    preview = {"schema_version": 1, "project_id": project["id"], "source_version": project["version"],
               "source_digest": _digest(project), "target_policy": "v2", "case_ids": selected,
               "case_mappings": mappings, "files": files, "counts": _counts(project, files),
               "active_runs": active_runs, "blockers": blockers, "convertible": not blockers}
    return {**preview, "digest": _digest(preview)}


def apply(project, approved_preview, expected_version, *, accepted_digest, idempotency_key, actor):
    """Adopt policy on a new in-memory copy; return that copy and its receipt.

    Replay checks precede CAS, as for project commands. A receipt is scoped to the
    project and records the exact actor, preview and original expected version.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or not isinstance(actor, str) or not actor.strip():
        raise MigrationError(422, "接受迁移需要具名操作人和幂等键。")
    intent = _digest({"preview": approved_preview, "accepted_digest": accepted_digest,
                      "expected_version": expected_version, "actor": actor})
    for receipt in project.get("migration_receipts", []):
        if receipt["idempotency_key"] == idempotency_key:
            if receipt["intent_digest"] != intent:
                raise MigrationError(409, "同一迁移幂等键对应了不同接受意图。")
            return {"project": deepcopy(project), "receipt": deepcopy(receipt)}
    if not accepted_digest or accepted_digest != approved_preview.get("digest"):
        raise MigrationError(409, "必须明确接受本次固定预检摘要。")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version != project["version"]:
        raise MigrationError(409, "项目版本已变化，请重新预检。")
    fresh = inspect(project, case_ids=approved_preview.get("case_ids"))
    if fresh != approved_preview:
        raise MigrationError(409, "预检内容、项目事实或文件已变化，请重新预检并接受。")
    if not fresh["convertible"]:
        raise MigrationError(409, "预检存在阻断项，不能接受迁移。")
    migrated = deepcopy(project)
    mapping = {item["case_id"]: item for item in fresh["case_mappings"]}
    for case in migrated["cases"]:
        if case["id"] in mapping:
            case["business_lifecycle"] = deepcopy(mapping[case["id"]]["target_lifecycle"])
            for name in ("requirement_baselines", "review_bundles", "rd_activations"):
                case.setdefault(name, [])
    migrated["version"] += 1
    counts_after = _counts(migrated, fresh["files"])
    facts_preserved = _facts(project) == _facts(migrated)
    if counts_after != fresh["counts"] or not facts_preserved:
        raise MigrationError(409, "迁移总量或原事实对账失败。")
    receipt = {"id": "migration-" + intent[:24], "idempotency_key": idempotency_key,
               "intent_digest": intent, "actor": actor, "preview_digest": fresh["digest"],
               "source_version": project["version"], "target_version": migrated["version"],
               "source_digest": fresh["source_digest"], "case_ids": fresh["case_ids"],
               "source_lifecycles": [{"case_id": case["id"], "value": deepcopy(case.get("business_lifecycle"))}
                                     for case in project["cases"] if case["id"] in mapping],
               "counts_before": fresh["counts"], "counts_after": counts_after,
               "files_digest": _digest(fresh["files"]), "facts_digest": _digest(_facts(migrated)),
               "facts_preserved": facts_preserved}
    migrated.setdefault("migration_receipts", []).append(deepcopy(receipt))
    return {"project": migrated, "receipt": receipt}
