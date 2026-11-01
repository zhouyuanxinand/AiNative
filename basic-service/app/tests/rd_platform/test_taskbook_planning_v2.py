"""Taskbooks run in planning; engineering design requires fixed scope approval."""
import json

import pytest

from service.rd_platform import catalog
from test_selection_activation import local_store, activated_project, selection_project, prepare, decide
from test_store import issue
from test_runtime import finish_taskbook_with_document, submitted


def adopted_project(store):
    project = activated_project(store)
    return issue(store, project, "adopt_taskbook_flow", {"workflow_id": "taskbook-modification-v1", "workflow_version": "1", "scope": "本次液冷改型", "rationale": "按当前需求和选型差异"})


def submitted_v2(store):
    project = adopted_project(store)
    project = issue(store, project, "pull_workpackage", {"definition_id": "taskbook"})
    return issue(store, project, "submit_workpackage", {"workpackage_id": project["cases"][0]["workpackages"][-1]["id"]})


def test_versioned_definition_preserves_legacy_design_and_new_planning():
    assert catalog.definition("taskbook", "1")["stages"] == ["design"]
    assert catalog.definition("taskbook", "2")["stages"] == ["planning"]
    assert catalog.definition("taskbook", "2")["business_node_id"] == "taskbook_planning"
    assert catalog.definition("taskbook", "999") is None


def test_new_taskbook_plan_fixes_activation_and_runs_in_planning(tmp_path):
    store = local_store(tmp_path)
    project = submitted_v2(store)
    case = project["cases"][0]
    package = case["workpackages"][-1]
    assert case["stage"] == package["stage"] == "planning"
    assert package["definition_version"] == "2" and package["business_node_id"] == "taskbook_planning"
    refs = package["snapshot"]["lifecycle_refs"]
    assert refs["requirement_baseline_id"] == case["business_lifecycle"]["current_requirement_baseline_id"]
    assert refs["activation_id"] == case["business_lifecycle"]["current_activation_id"]
    assert package["snapshot"]["taskbook_binding"]["lifecycle_refs"] == refs
    finish_taskbook_with_document(store)
    completed = store.get_project("owner", project["id"])
    assert completed["cases"][0]["stage"] == "planning"
    assert completed["cases"][0]["workpackages"][-1]["status"] == "completed"


def test_unstarted_case_and_legacy_definition_cannot_bypass_planning_gate(tmp_path):
    store = local_store(tmp_path)
    project = decide(store, prepare(store, selection_project(store)))
    for command, data in (("pull_workpackage", {"definition_id": "taskbook"}), ("adopt_taskbook_flow", {"workflow_id": "taskbook-modification-v1", "workflow_version": "1", "scope": "范围", "rationale": "依据"})):
        with pytest.raises(Exception) as error:
            issue(store, project, command, data)
        assert error.value.status in {409, 422}
    project = adopted_project(local_store(tmp_path / "other"))
    store = local_store(tmp_path / "other")
    with pytest.raises(Exception) as error:
        issue(store, project, "pull_workpackage", {"definition_id": "taskbook", "definition_version": "1"})
    assert error.value.status == 422


def test_scope_decision_is_bound_to_current_generated_file_and_quality(tmp_path):
    store = local_store(tmp_path)
    project = submitted_v2(store)
    wid = project["cases"][0]["workpackages"][-1]["id"]
    with pytest.raises(Exception) as error:
        issue(store, project, "prepare_taskbook_scope_review", {"workpackage_id": wid})
    assert error.value.status == 422
    finish_taskbook_with_document(store)
    project = store.get_project("owner", project["id"])
    project = issue(store, project, "prepare_taskbook_scope_review", {"workpackage_id": wid})
    bundle = project["cases"][0]["review_bundles"][-1]
    assert bundle["kind"] == "taskbook_scope"
    data = {"bundle_id": bundle["id"], "bundle_digest": bundle["digest"], "verdict": "approved", "scope": "当前任务书工程范围", "rationale": "负责人核对成果与质量报告"}
    with pytest.raises(Exception) as error:
        issue(store, project, "record_taskbook_scope_decision", {**data, "bundle_digest": "wrong"})
    assert error.value.status == 409
    project = issue(store, project, "record_taskbook_scope_decision", data)
    case = project["cases"][0]
    assert case["stage"] == "design"
    assert case["business_lifecycle"]["current_taskbook_scope_decision_id"] == case["decisions"][-1]["id"]
    assert case["decisions"][-1]["electronic_signature"] is False


def test_generated_file_with_negative_quality_cannot_enter_scope_review(tmp_path):
    store = local_store(tmp_path)
    project = submitted_v2(store)
    finish_taskbook_with_document(store)
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        package = raw["cases"][0]["workpackages"][-1]
        next(node for node in package["nodes"] if node["action_id"] == "verify")["result"]["delivery_approved"] = False
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    project = store.get_project("owner", project["id"])
    with pytest.raises(Exception) as error:
        issue(store, project, "prepare_taskbook_scope_review", {"workpackage_id": package["id"]})
    assert error.value.status == 422
    assert project["cases"][0]["stage"] == "planning"


def test_running_legacy_package_keeps_original_snapshot_when_new_policy_is_available(tmp_path):
    store, project = submitted(tmp_path)
    claim = store.claim_node()
    original = claim["snapshot"]
    reopened = local_store(tmp_path)
    new_case = issue(reopened, reopened.get_project("owner", project["id"]), "create_case", {"scenario_id": "taskbook", "title": "新办理"})
    assert new_case["cases"][-1]["business_lifecycle"]["policy_version"] == "v2"
    assert reopened.complete_node(claim, {"status": "completed", "result": {}, "artifacts": []})
    following = reopened.claim_node()
    assert following["snapshot"] == original
    assert original["definition_version"] == "1" and original["stage"] == "design"


def test_stale_parameter_evidence_blocks_template_adoption(tmp_path):
    store = local_store(tmp_path)
    project = activated_project(store)
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        raw["cases"][0]["context_provenance"]["product_series"] = {"kind": "source_analysis", "source_refs": [{"source_id": "removed-source", "version": 1, "sha256": "old"}]}
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    project = store.get_project("owner", project["id"])
    with pytest.raises(Exception) as error:
        issue(store, project, "adopt_taskbook_flow", {"workflow_id": "taskbook-modification-v1", "workflow_version": "1", "scope": "范围", "rationale": "依据"})
    assert error.value.status == 422
    assert "product_series" in error.value.detail


def test_new_followup_command_preserves_direct_delivery_gate(tmp_path):
    store = local_store(tmp_path)
    project = decide(store, prepare(store, selection_project(store, "direct")))
    sid = project["cases"][0]["sources"][0]["id"]
    data = {"stage": "delivery", "verdict": "approved", "rationale": "收到固定选用结果", "source_ids": [sid]}
    with pytest.raises(Exception) as error:
        issue(store, project, "confirm_engineering_stage", data)
    assert error.value.status == 422
    project = issue(store, project, "record_delivery", {"outcome": "accepted", "recipient": "客户", "receipt": "本地登记接收回执", "source_ids": [sid]})
    project = issue(store, project, "confirm_engineering_stage", data)
    assert project["cases"][0]["stage"] == "knowledge"
    assert project["cases"][0]["decisions"][-1]["review_mode"] == "local_review"


def test_scope_review_cannot_choose_old_result_while_replacement_is_running(tmp_path):
    store = local_store(tmp_path)
    project = submitted_v2(store)
    first_id = project["cases"][0]["workpackages"][-1]["id"]
    finish_taskbook_with_document(store)
    project = store.get_project("owner", project["id"])
    project = issue(store, project, "pull_workpackage", {"definition_id": "taskbook"})
    project = issue(store, project, "submit_workpackage", {"workpackage_id": project["cases"][0]["workpackages"][-1]["id"]})
    with pytest.raises(Exception) as error:
        issue(store, project, "prepare_taskbook_scope_review", {"workpackage_id": first_id})
    assert error.value.status == 409


def test_member_cannot_record_v2_engineering_decision_after_scope_approval(tmp_path):
    store = local_store(tmp_path)
    project = submitted_v2(store)
    finish_taskbook_with_document(store)
    project = store.get_project("owner", project["id"])
    case = project["cases"][0]
    project = issue(store, project, "prepare_taskbook_scope_review", {"workpackage_id": case["workpackages"][-1]["id"]})
    bundle = project["cases"][0]["review_bundles"][-1]
    project = issue(store, project, "record_taskbook_scope_decision", {"bundle_id": bundle["id"], "bundle_digest": bundle["digest"], "verdict": "approved", "scope": "本次任务书", "rationale": "负责人核对"})
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        raw["members"] = ["member"]
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    with pytest.raises(Exception) as error:
        store.command("member", project["id"], project["version"], "member-scheme", "record_engineering_node", {"case_id": case["id"], "node_id": "scheme", "verdict": "rejected", "summary": "成员不应签署", "source_ids": [case["sources"][0]["id"]]})
    assert error.value.status == 403


def test_followup_quality_check_preserves_v2_business_binding_references(tmp_path):
    from service.rd_platform.business_binding import verify_binding
    store = local_store(tmp_path)
    project = submitted_v2(store)
    finish_taskbook_with_document(store)
    project = store.get_project("owner", project["id"])
    project = issue(store, project, "pull_workpackage", {"definition_id": "quality_check"})
    project = issue(store, project, "submit_workpackage", {"workpackage_id": project["cases"][0]["workpackages"][-1]["id"]})
    snapshot = store.claim_node()["snapshot"]
    assert verify_binding(snapshot)["id"] == project["cases"][0]["taskbook_binding"]["id"]
    assert snapshot["lifecycle_refs"]["activation_id"] == project["cases"][0]["business_lifecycle"]["current_activation_id"]


def test_supplementary_engineering_reports_do_not_invalidate_selection_baseline(tmp_path):
    from test_runtime import approve_engineering
    store = local_store(tmp_path)
    project = submitted_v2(store)
    finish_taskbook_with_document(store)
    project = store.get_project("owner", project["id"])
    case = project["cases"][0]
    project = issue(store, project, "prepare_taskbook_scope_review", {"workpackage_id": case["workpackages"][-1]["id"]})
    bundle = project["cases"][0]["review_bundles"][-1]
    project = issue(store, project, "record_taskbook_scope_decision", {"bundle_id": bundle["id"], "bundle_digest": bundle["digest"], "verdict": "approved", "scope": "当前任务书", "rationale": "负责人核对"})
    project = approve_engineering(store, project)
    project = issue(store, project, "confirm_engineering_stage", {"stage": "design", "verdict": "approved", "rationale": "逐项核对专业成果", "source_ids": [case["sources"][0]["id"]]})
    assert project["cases"][0]["stage"] == "verification"
    assert project["cases"][0]["business_lifecycle"]["rd_activation_state"] == "active"


def test_scope_review_uses_submission_order_when_older_draft_runs_later(tmp_path):
    store = local_store(tmp_path)
    project = adopted_project(store)
    project = issue(store, project, "pull_workpackage", {"definition_id": "taskbook"})
    first_draft = project["cases"][0]["workpackages"][-1]["id"]
    project = issue(store, project, "pull_workpackage", {"definition_id": "taskbook"})
    second_draft = project["cases"][0]["workpackages"][-1]["id"]
    project = issue(store, project, "submit_workpackage", {"workpackage_id": second_draft})
    finish_taskbook_with_document(store)
    project = store.get_project("owner", project["id"])
    project = issue(store, project, "submit_workpackage", {"workpackage_id": first_draft})
    with pytest.raises(Exception) as error:
        issue(store, project, "prepare_taskbook_scope_review", {"workpackage_id": second_draft})
    assert error.value.status == 409
