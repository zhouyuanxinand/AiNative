"""Offline lifecycle adoption never invents approvals or rewrites execution facts."""
from copy import deepcopy
import hashlib
import importlib

import pytest


def migration():
    return importlib.import_module("service.rd_platform.migration")


def legacy_project(tmp_path, status="completed"):
    source = tmp_path / "requirements.txt"
    source.write_bytes(b"original requirements")
    document = tmp_path / "taskbook.docx"
    document.write_bytes(b"historical generated document")
    source_ref = {"id": "source-1", "role": "tech", "version": 1,
                  "path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    artifact = {"id": "artifact-1", "kind": "docx", "name": document.name,
                "path": str(document), "sha256": hashlib.sha256(document.read_bytes()).hexdigest()}
    draft = status == "draft"
    package = {"id": "package-1", "definition_id": "taskbook", "definition_version": "1",
               "stage": "design", "status": status, "plan_revision": 1,
               "run_id": None if draft else "run-1",
               "nodes": [{"id": "generate", "action_id": "generate", "action_version": "1",
                          "depends_on": [], "status": "draft" if draft else status,
                          "attempt": 0 if draft else 1}],
               "snapshot": None if draft else {"stage": "design", "definition_version": "1",
                    "actor_id": "legacy-owner", "sources": [deepcopy(source_ref)],
                    "actions": [{"id": "generate", "resource_id": "generate", "resource_version": 1}]},
               "artifacts": [] if draft else [artifact]}
    return {"id": "project-1", "version": 7, "owner_id": "legacy-owner", "members": ["reader"],
            "events": [{"id": "event-1", "type": "created"}],
            "cases": [{"id": "case-1", "scenario_id": "taskbook", "stage": "design",
                       "status": "completed" if status == "completed" else "active",
                       "input_revision": 2, "sources": [source_ref], "source_selection": {"tech": "source-1"},
                       "requirements": [{"id": "requirement-1", "source_ids": ["source-1"], "content": "original"}],
                       "decisions": [{"id": "legacy-stage-1", "kind": "stage", "stage": "planning",
                                      "verdict": "approved", "actor": "legacy-owner"}],
                       "workpackages": [package]}]}


def accept(project, preview, **kwargs):
    return migration().apply(project, preview, kwargs.pop("expected_version", 7),
                             accepted_digest=kwargs.pop("accepted_digest", preview["digest"]),
                             idempotency_key=kwargs.pop("idempotency_key", "accept-1"),
                             actor=kwargs.pop("actor", "migration-operator"), **kwargs)


def test_inspect_is_read_only_and_stable_and_lists_real_files(tmp_path):
    project = legacy_project(tmp_path)
    before = deepcopy(project)
    preview = migration().inspect(project)
    assert project == before
    assert migration().inspect(project) == preview
    assert len(preview["digest"]) == 64
    assert preview["source_version"] == 7
    assert preview["target_policy"] == "v2"
    assert preview["counts"]["artifacts"] == 1
    assert preview["counts"]["files"] == 2
    assert all(item["status"] == "verified" for item in preview["files"])
    mapping = preview["case_mappings"][0]
    assert mapping["source_policy"] == "legacy_v1"
    assert mapping["source_stage"] == mapping["target_stage"] == "design"
    assert mapping["target_lifecycle"]["rd_activation_state"] == "historical_unverified"
    assert "rd_start_evidence_missing" in mapping["unknown_facts"]
    assert preview["convertible"] is True


@pytest.mark.parametrize("status", ["completed", "draft", "failed", "cancelled"])
def test_adoption_preserves_history_and_does_not_infer_start_from_outputs(tmp_path, status):
    project = legacy_project(tmp_path, status)
    original = deepcopy(project)
    result = accept(project, migration().inspect(project))
    changed = result["project"]
    case = changed["cases"][0]
    assert project == original
    for key, value in original["cases"][0].items():
        assert case[key] == value
    assert case["business_lifecycle"]["policy_version"] == "v2"
    assert case["business_lifecycle"]["rd_activation_state"] == "historical_unverified"
    assert case["business_lifecycle"]["rd_project_code"] is None
    assert case["business_lifecycle"]["current_selection_decision_id"] is None
    assert case["rd_activations"] == []
    assert changed["owner_id"] == "legacy-owner" and changed["members"] == ["reader"]
    assert changed["version"] == 8
    assert result["receipt"]["counts_before"] == result["receipt"]["counts_after"]
    assert result["receipt"]["facts_preserved"] is True


@pytest.mark.parametrize("status", ["submitted", "running"])
def test_active_run_remains_with_original_owner_and_blocks_conversion(tmp_path, status):
    project = legacy_project(tmp_path, status)
    original = deepcopy(project)
    preview = migration().inspect(project)
    assert preview["convertible"] is False
    assert preview["active_runs"] == [{"case_id": "case-1", "workpackage_id": "package-1",
                                       "run_id": "run-1", "status": status, "owner_id": "legacy-owner"}]
    with pytest.raises(migration().MigrationError) as error:
        accept(project, preview)
    assert error.value.status == 409
    assert project == original


def test_draft_candidate_requires_separate_new_plan_adoption(tmp_path):
    project = legacy_project(tmp_path, "draft")
    preview = migration().inspect(project)
    candidate = preview["case_mappings"][0]["draft_candidates"][0]
    assert candidate["source_workpackage_id"] == "package-1"
    assert candidate["target_definition_version"] == "2"
    assert candidate["target_stage"] == "planning"
    assert candidate["requires_new_plan"] is True
    result = accept(project, preview)
    assert result["project"]["cases"][0]["workpackages"] == project["cases"][0]["workpackages"]


def test_acceptance_digest_and_version_are_required(tmp_path):
    project = legacy_project(tmp_path)
    preview = migration().inspect(project)
    for options in ({"accepted_digest": ""}, {"accepted_digest": "0" * 64},
                    {"expected_version": 6}, {"expected_version": True}):
        with pytest.raises(migration().MigrationError):
            accept(project, preview, **options)


def test_preflight_cannot_be_forged_or_reused_after_source_change(tmp_path):
    project = legacy_project(tmp_path)
    preview = migration().inspect(project)
    forged = deepcopy(preview)
    forged["case_mappings"][0]["target_lifecycle"]["rd_activation_state"] = "active"
    with pytest.raises(migration().MigrationError):
        accept(project, forged)
    project["cases"][0]["input_revision"] += 1
    with pytest.raises(migration().MigrationError) as error:
        accept(project, preview)
    assert error.value.status == 409


def test_file_bytes_must_match_at_preflight_and_acceptance(tmp_path):
    project = legacy_project(tmp_path)
    preview = migration().inspect(project)
    (tmp_path / "taskbook.docx").write_bytes(b"replaced document")
    with pytest.raises(migration().MigrationError):
        accept(project, preview)
    refreshed = migration().inspect(project)
    assert refreshed["convertible"] is False
    assert any(item["status"] == "hash_mismatch" for item in refreshed["files"])
    (tmp_path / "taskbook.docx").unlink()
    assert any(item["status"] == "missing" for item in migration().inspect(project)["files"])


def test_same_acceptance_is_idempotent_and_changed_intent_conflicts(tmp_path):
    project = legacy_project(tmp_path)
    preview = migration().inspect(project)
    result = accept(project, preview)
    assert accept(result["project"], preview) == result
    assert len(result["project"]["migration_receipts"]) == 1
    for options in ({"actor": "other-operator"}, {"expected_version": 8}, {"accepted_digest": "f" * 64}):
        with pytest.raises(migration().MigrationError) as error:
            accept(result["project"], preview, **options)
        assert error.value.status == 409


def test_unknown_authorization_fields_are_not_start_evidence(tmp_path):
    project = legacy_project(tmp_path)
    project["cases"][0]["authorization"] = {"approved": True, "actor": "admin", "project_code": "FAKE-1"}
    preview = migration().inspect(project)
    assert preview["case_mappings"][0]["target_lifecycle"]["rd_project_code"] is None
    assert preview["case_mappings"][0]["target_lifecycle"]["rd_activation_state"] == "historical_unverified"


def test_fixed_source_references_resolve_to_original_bytes(tmp_path):
    project = legacy_project(tmp_path)
    source = project["cases"][0]["sources"][0]
    project["cases"][0]["requirement_baselines"] = [{"id": "baseline-1", "source_refs": [
        {key: source[key] for key in ("id", "role", "version", "sha256")}]}]
    preview = migration().inspect(project)
    assert preview["convertible"] is True
    assert preview["counts"]["files"] == 2


def test_only_selected_cases_change_while_another_case_keeps_running(tmp_path):
    project = legacy_project(tmp_path, "running")
    running = deepcopy(project["cases"][0])
    draft = deepcopy(running)
    draft["id"] = "case-2"
    draft["workpackages"] = []
    project["cases"].append(draft)
    preview = migration().inspect(project, case_ids=["case-2"])
    assert preview["convertible"] is True
    result = accept(project, preview)
    assert result["project"]["cases"][0] == running
    assert "business_lifecycle" not in project["cases"][1]
    assert result["receipt"]["case_ids"] == ["case-2"]


@pytest.mark.parametrize("corrupt", ["duplicate_case", "duplicate_source", "dangling_requirement_source", "unknown_run_outcome"])
def test_unreconciled_identity_or_execution_state_blocks_conversion(tmp_path, corrupt):
    project = legacy_project(tmp_path)
    case = project["cases"][0]
    if corrupt == "duplicate_case":
        project["cases"].append(deepcopy(case))
    elif corrupt == "duplicate_source":
        case["sources"].append(deepcopy(case["sources"][0]))
    elif corrupt == "dangling_requirement_source":
        case["requirements"][0]["source_ids"] = ["missing-source"]
    else:
        case["workpackages"][0]["status"] = "blocked"
    preview = migration().inspect(project)
    assert preview["convertible"] is False
    with pytest.raises(migration().MigrationError):
        accept(project, preview)


def test_migration_report_does_not_echo_execution_credentials(tmp_path):
    import json

    project = legacy_project(tmp_path)
    project["cases"][0]["workpackages"][0]["snapshot"]["actions"][0]["configuration"] = {
        "api_key": "secret-never-in-report", "provider": "local"}
    preview = migration().inspect(project)
    assert "secret-never-in-report" not in json.dumps(preview)
    assert "secret-never-in-report" not in json.dumps(accept(project, preview)["receipt"])


def server_recorded_start(tmp_path):
    """Use domain commands, not a hand-authored approved record, as evidence."""
    import json
    from test_selection_activation import activated_project, local_store

    store = local_store(tmp_path)
    project = activated_project(store)
    with store._connection() as db:
        detached = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
    # Simulate an imported historical copy lacking a policy declaration. The
    # actual source database and its server-recorded evidence are unchanged.
    detached["cases"][0]["business_lifecycle"].pop("policy_version")
    return detached


def test_server_recorded_local_start_is_preserved_without_becoming_formal_approval(tmp_path):
    project = server_recorded_start(tmp_path)
    case = project["cases"][0]
    original_records = deepcopy(case["rd_activations"])
    preview = migration().inspect(project)
    evidence = preview["case_mappings"][0]["activation_evidence"][0]
    assert evidence["activation_id"] == original_records[0]["id"]
    assert evidence["status"] == "candidate_requires_policy_review"
    assert evidence["review_mode"] == "local_review"
    assert preview["convertible"], preview["blockers"]
    result = accept(project, preview, expected_version=project["version"])
    adopted = result["project"]["cases"][0]
    assert adopted["rd_activations"] == original_records
    assert adopted["rd_activations"][0]["electronic_signature"] is False
    assert adopted["business_lifecycle"]["rd_activation_state"] == "historical_unverified"
    assert adopted["business_lifecycle"]["local_review_enabled"] is False
    assert adopted["business_lifecycle"]["current_activation_id"] is None
    assert len(adopted["decisions"]) == len(case["decisions"])
    assert result["receipt"]["source_lifecycles"] == [{"case_id": case["id"], "value": case["business_lifecycle"]}]


@pytest.mark.parametrize("change", ["missing_actor", "broken_reference", "stale_input", "replaced_report", "invalidated"])
def test_incomplete_or_stale_start_evidence_is_not_an_adoption_candidate(tmp_path, change):
    project = server_recorded_start(tmp_path)
    case = project["cases"][0]
    record = case["rd_activations"][0]
    if change == "missing_actor":
        record["actor"] = ""
    elif change == "broken_reference":
        record["selection_decision_id"] = "missing"
    elif change == "stale_input":
        case["input_revision"] += 1
    elif change == "replaced_report":
        case["review_bundles"][0]["report"]["title"] = "unreviewed replacement"
    else:
        case["decisions"][-1]["invalidated_at"] = "2026-11-01T00:00:00Z"
    mapping = migration().inspect(project)["case_mappings"][0]
    assert mapping["activation_evidence"][0]["status"] == "unverified"
    assert mapping["target_lifecycle"]["rd_activation_state"] == "historical_unverified"


def test_already_adopted_policy_cannot_be_reapplied_as_a_new_migration(tmp_path):
    project = legacy_project(tmp_path)
    adopted = accept(project, migration().inspect(project))["project"]
    preview = migration().inspect(adopted)
    assert preview["convertible"] is False
    with pytest.raises(migration().MigrationError):
        accept(adopted, preview, expected_version=8, idempotency_key="different-key")


def test_draft_with_previous_execution_is_not_a_new_plan_candidate(tmp_path):
    project = legacy_project(tmp_path, "draft")
    project["cases"][0]["workpackages"][0]["nodes"][0]["attempt"] = 1
    preview = migration().inspect(project)
    assert preview["case_mappings"][0]["draft_candidates"] == []


@pytest.mark.parametrize("actor,key", [("", "key"), ("operator", ""), (None, "key")])
def test_acceptance_requires_named_operator_and_intent_key(tmp_path, actor, key):
    project = legacy_project(tmp_path)
    with pytest.raises(migration().MigrationError) as error:
        accept(project, migration().inspect(project), actor=actor, idempotency_key=key)
    assert error.value.status == 422


def test_preflight_maps_original_action_resource_and_template_versions(tmp_path):
    project = legacy_project(tmp_path)
    project["cases"][0]["workpackages"][0]["snapshot"]["taskbook_binding"] = {
        "workflow": {"id": "taskbook-modification-v1", "version": "1"},
        "document_template": {"product_type": "liquid_cooling_pipeline", "product_domain": "military",
                              "assets": {"template": {"path": str(tmp_path / "taskbook.docx"),
                                        "sha256": hashlib.sha256(b"historical generated document").hexdigest()}}}}
    refs = migration().inspect(project)["case_mappings"][0]["reference_map"]["workpackages"][0]
    assert refs["action_refs"] == [{"node_id": "generate", "action_id": "generate", "action_version": "1"}]
    assert refs["resource_refs"] == [{"resource_id": "generate", "resource_version": 1}]
    assert refs["workflow_ref"] == {"id": "taskbook-modification-v1", "version": "1"}
    assert refs["document_template_ref"]["product_type"] == "liquid_cooling_pipeline"
    assert refs["document_template_ref"]["asset_digests"]["template"] == hashlib.sha256(b"historical generated document").hexdigest()
