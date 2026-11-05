"""Durable execution resumes from claims and rejects cancelled or stale attempts."""
import importlib
import json
import time
from pathlib import Path

import pytest

from test_store import case_project, issue, new_store, taskbook


def submitted(tmp_path):
    store = new_store(tmp_path)
    project = taskbook(store)
    project = issue(store, project, "submit_workpackage", {"workpackage_id": project["cases"][0]["workpackages"][0]["id"]})
    return store, project


def completed(**extra):
    return {"status": "completed", "result": {"execution_mode": "local_real"}, "artifacts": [], "obligations": [], "blocked_reasons": [], **extra}


def package_of(store, project):
    return store.get_project("owner", project["id"])["cases"][0]["workpackages"][0]


def test_worker_resumes_dependency_order_without_advancing_business_stage(tmp_path):
    store, project = submitted(tmp_path)
    Worker = importlib.import_module("service.rd_platform.runtime").Worker
    def execute(action_id, snapshot, previous_results, work_dir, progress, cancelled):
        assert Path(snapshot["sources"][0]["path"]).read_bytes() == b"source evidence"
        assert len(previous_results) == {"resolve_context": 0, "template_plan": 1, "content_completion": 2, "generate": 3, "verify": 4}[action_id]
        progress({"message": "真实执行"})
        assert not cancelled()
        if action_id == "generate":
            path = Path(work_dir) / "任务书.docx"
            path.write_bytes(b"document fixture")
            return completed(artifacts=[{"id": "doc", "name": "任务书.docx", "path": str(path), "kind": "docx"}])
        return completed()
    assert Worker(store, execute).tick()
    for _ in range(4):
        assert Worker(new_store(tmp_path), execute).tick()
    assert Worker(store, execute).tick() is False
    final = store.get_project("owner", project["id"])
    package = final["cases"][0]["workpackages"][0]
    assert final["cases"][0]["stage"] == "design" and package["status"] == "completed"
    assert store.artifact_path("owner", project["id"], project["cases"][0]["id"], package["id"], "doc").read_bytes() == b"document fixture"
    assert all(node["attempt"] == 1 and node["status"] == "completed" for node in package["nodes"])
    assert '"path"' not in json.dumps(package)
    with pytest.raises(Exception) as error:
        store.artifact_path("outsider", project["id"], project["cases"][0]["id"], package["id"], "doc")
    assert error.value.status == 404


def test_blocked_outcome_preserves_obligations_and_stops_dependants(tmp_path):
    store, project = submitted(tmp_path)
    Worker = importlib.import_module("service.rd_platform.runtime").Worker
    worker = Worker(store, lambda *args: {"status": "blocked", "result": {}, "artifacts": [], "obligations": [{"id": "O1", "status": "unresolved"}], "blocked_reasons": ["无依据，不补造"]})
    assert worker.tick() and not worker.tick()
    package = package_of(store, project)
    assert package["status"] == "blocked" and package["obligations"][0]["id"] == "O1"
    assert package["nodes"][1]["attempt"] == 0


def test_cancelled_package_refuses_late_result(tmp_path):
    store, project = submitted(tmp_path)
    claim = store.claim_node()
    current = store.get_project("owner", project["id"])
    issue(store, current, "cancel_workpackage", {"workpackage_id": package_of(store, project)["id"]})
    assert not store.complete_node(claim, completed()) and not store.renew_claim(claim)
    assert package_of(store, project)["status"] == "cancelled" and store.claim_node() is None


def test_expired_claim_is_retried_and_old_attempt_cannot_register_result(tmp_path, monkeypatch):
    store, project = submitted(tmp_path)
    reopened = new_store(tmp_path)
    clock = [1_000_000.0]
    monkeypatch.setattr(importlib.import_module("service.rd_platform.store").time, "time", lambda: clock[0])
    stale = store.claim_node(lease_seconds=60)
    assert reopened.claim_node() is None
    clock[0] += 61
    current = reopened.claim_node()
    assert current["attempt"] == 2 and current["token"] != stale["token"]
    assert not store.complete_node(stale, completed()) and store.complete_node(current, completed())


def test_expired_attempt_retries_have_persistent_budget(tmp_path, monkeypatch):
    store, project = submitted(tmp_path)
    clock = [1_000_000.0]
    monkeypatch.setattr(importlib.import_module("service.rd_platform.store").time, "time", lambda: clock[0])
    for _ in range(3):
        assert new_store(tmp_path).claim_node(lease_seconds=60)
        clock[0] += 61
    assert new_store(tmp_path).claim_node() is None
    assert package_of(store, project)["status"] == "blocked"
    assert package_of(store, project)["nodes"][0]["attempt"] == 3


def test_contract_example_cannot_be_promoted_into_production_result(tmp_path):
    store, project = submitted(tmp_path)
    claim = store.claim_node()
    assert store.complete_node(claim, completed(result={"execution_mode": "local_real", "dependencies": [{"execution_mode": "contract_example"}]}))
    assert package_of(store, project)["status"] == "blocked"


def test_missing_or_outside_artifact_never_becomes_downloadable(tmp_path):
    store, project = submitted(tmp_path)
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"not a controlled outcome")
    claim = store.claim_node()
    assert store.complete_node(claim, completed(artifacts=[{"id": "escape", "name": "outside.docx", "kind": "docx", "path": str(outside)}]))
    assert package_of(store, project)["status"] == "failed" and package_of(store, project)["artifacts"] == []


def test_hash_tampering_blocks_fixed_submission_before_executor(tmp_path):
    store, project = submitted(tmp_path)
    source = project["cases"][0]["sources"][0]
    path = store.source_path("owner", project["id"], project["cases"][0]["id"], source["id"])
    path.write_bytes(b"tampered")
    assert store.claim_node() is None and package_of(store, project)["status"] == "blocked"


def test_retired_bound_resource_blocks_fixed_submission(tmp_path):
    store, project = submitted(tmp_path)
    resource = next(item for item in store.list_resources() if item["id"] == "resolve_context")
    store.save_resource("manager", {**resource, "expected_version": resource["version"], "operation": "retire"}, can_manage=True)
    assert store.claim_node() is None and package_of(store, project)["status"] == "blocked"


def test_verification_cannot_advance_without_completed_checks_and_artifacts(tmp_path):
    store, project = submitted(tmp_path)
    sid = project["cases"][0]["sources"][0]["id"]
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "design", "verdict": "approved", "rationale": "没有任务书成果不能离开设计阶段", "source_ids": [sid]})
    assert error.value.status == 422


def test_worker_thread_starts_and_stops_cleanly(tmp_path):
    store, project = submitted(tmp_path)
    Worker = importlib.import_module("service.rd_platform.runtime").Worker
    worker = Worker(store, lambda *args: completed(), poll_interval=0.01)
    worker.start()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and package_of(store, project)["status"] != "completed":
        time.sleep(0.01)
    worker.stop()
    assert package_of(store, project)["status"] == "completed"


def upload_engineering_evidence(store, project, label):
    cid = project["cases"][0]["id"]
    project = store.add_source("owner", project["id"], cid, project["version"], "professional-" + str(project["version"]), "reference", label + ".txt", (label + "：专业人员完成并核对的实际报告夹具").encode("utf-8"))
    return project, project["cases"][0]["sources"][-1]["id"]


def approve_engineering(store, project):
    for node in ("scheme", "detail", "integration"):
        project, sid = upload_engineering_evidence(store, project, node + "-专业报告")
        project = issue(store, project, "record_engineering_node", {"node_id": node, "verdict": "approved", "summary": "测试夹具明确核对当前实际专业报告", "source_ids": [sid], "artifact_ids": []})
    return project


def test_completed_taskbook_still_needs_all_real_stage_decisions(tmp_path):
    store, project = submitted(tmp_path)
    Worker = importlib.import_module("service.rd_platform.runtime").Worker
    def execute(action, snapshot, previous, work_dir, progress, cancelled):
        if action == "generate":
            path = Path(work_dir) / "任务书.docx"
            path.write_bytes(b"actual fixed outcome")
            return completed(artifacts=[{"id": "document", "name": path.name, "kind": "docx", "path": str(path)}])
        if action == "verify":
            return completed(result={"execution_mode": "local_real", "delivery_approved": True})
        return completed()
    worker = Worker(store, execute)
    for _ in range(5):
        assert worker.tick()
    current = store.get_project("owner", project["id"])
    cid = current["cases"][0]["id"]
    sid = current["cases"][0]["sources"][0]["id"]
    current = approve_engineering(store, current)
    for stage, expected in (("design", "verification"), ("verification", "delivery"), ("delivery", "knowledge"), ("knowledge", "knowledge")):
        if stage == "delivery":
            current = issue(store, current, "record_delivery", {"artifact_ids": ["document"], "recipient": "测试接收方", "receipt": "本人据测试回执人工登记",
                "feedback": "接收本次固定成果", "outcome": "accepted", "source_ids": [sid]})
        if stage == "knowledge":
            current = issue(store, current, "prepare_reuse", {"title": "测试案例复用候选", "content": "有来源的本案例候选，尚未发布", "source_ids": [sid], "artifact_ids": ["document"]})
        current = issue(store, current, "advance_stage", {"stage": stage, "verdict": "approved", "rationale": "本人依据来源及成果作出决定", "source_ids": [sid], "artifact_ids": ["document"]})
        assert current["cases"][0]["stage"] == expected
    case = current["cases"][0]
    assert case["status"] == "completed"
    assert len([decision for decision in case["decisions"] if decision["kind"] == "stage"]) == 8
    assert all(decision["actor"] == "owner" for decision in case["decisions"])
    with pytest.raises(Exception) as error:
        issue(store, current, "save_context", {"context": {"product_type": "overwrite approved facts"}})
    assert error.value.status == 409
    with pytest.raises(Exception) as error:
        store.add_source("owner", current["id"], cid, current["version"], "after-closure", "tech", "revised.txt", b"changed")
    assert error.value.status == 409


def test_private_executor_output_paths_are_not_disclosed_in_project_results(tmp_path):
    store, project = submitted(tmp_path)
    claim = store.claim_node()
    private = str(Path(claim["work_dir"]) / "source-private.txt")
    assert store.complete_node(claim, completed(result={"execution_mode": "local_real", "output": private, "receipt": {"files": {"output": private}}}))
    result = package_of(store, project)["nodes"][0]["result"]
    assert result["output"] != private
    assert result["receipt"]["files"]["output"] != private


def test_retirement_remains_effective_when_only_a_draft_revision_is_saved(tmp_path):
    store, project = submitted(tmp_path)
    resource = store.get_resource("resolve_context")
    retired = store.save_resource("manager", {**resource, "operation": "retire", "expected_version": 1}, can_manage=True)
    assert retired["version"] == 1
    store.save_resource("manager", {**retired, "operation": "save", "expected_version": 1}, can_manage=True)
    assert store.claim_node() is None and package_of(store, project)["status"] == "blocked"


def test_active_worker_heartbeats_prevent_a_second_worker_reclaiming(tmp_path):
    store, project = submitted(tmp_path)
    Worker = importlib.import_module("service.rd_platform.runtime").Worker
    import threading
    entered, release = threading.Event(), threading.Event()
    def execute(*args):
        entered.set()
        release.wait(2)
        return completed()
    worker = Worker(store, execute, lease_seconds=1)
    thread = threading.Thread(target=worker.tick)
    thread.start()
    assert entered.wait(1)
    time.sleep(1.3)
    try:
        assert store.claim_node() is None
    finally:
        release.set()
        thread.join(2)
    assert package_of(store, project)["nodes"][0]["attempt"] == 1


def test_expiry_while_registering_files_cannot_commit_a_late_result(tmp_path, monkeypatch):
    store, project = submitted(tmp_path)
    clock = [1_000_000.0]
    monkeypatch.setattr(importlib.import_module("service.rd_platform.store").time, "time", lambda: clock[0])
    claim = store.claim_node(lease_seconds=60)
    register = store._register_artifacts
    def slow_registration(*args):
        result = register(*args)
        clock[0] += 61
        return result
    monkeypatch.setattr(store, "_register_artifacts", slow_registration)
    assert not store.complete_node(claim, completed())
    assert package_of(store, project)["nodes"][0]["status"] == "running"


def finish_taskbook_with_document(store):
    Worker = importlib.import_module("service.rd_platform.runtime").Worker
    def execute(action, snapshot, previous, work_dir, progress, cancelled):
        if action == "generate":
            output = Path(work_dir) / "任务书.docx"
            output.write_bytes(b"actual result fixture")
            return completed(result={"execution_mode": "local_real", "workpackage_id": snapshot["workpackage_id"]},
                             artifacts=[{"id": "taskbook", "name": output.name, "kind": "docx", "path": str(output)}])
        if action == "verify":
            return completed(result={"execution_mode": "local_real", "delivery_approved": True})
        return completed()
    worker = Worker(store, execute)
    for _ in range(5):
        assert worker.tick()


def test_quality_check_fixes_upstream_receipts_but_new_taskbook_does_not_inherit_results(tmp_path):
    store, project = submitted(tmp_path)
    finish_taskbook_with_document(store)
    current = store.get_project("owner", project["id"])
    upstream_id = current["cases"][0]["workpackages"][0]["id"]
    current = issue(store, current, "pull_workpackage", {"definition_id": "quality_check", "request_ref": upstream_id})
    check_id = current["cases"][0]["workpackages"][-1]["id"]
    current = issue(store, current, "submit_workpackage", {"workpackage_id": check_id})
    claim = store.claim_node()
    assert claim["snapshot"]["upstream_workpackage_id"] == upstream_id
    assert claim["previous_results"]["generate"]["workpackage_id"] == upstream_id
    assert claim["snapshot"]["upstream_artifacts"][0]["sha256"]
    assert store.complete_node(claim, completed(result={"execution_mode": "local_real", "delivery_approved": True}))
    current = store.get_project("owner", project["id"])
    current = issue(store, current, "pull_workpackage", {"definition_id": "taskbook"})
    package = current["cases"][0]["workpackages"][-1]
    assert package["id"] != upstream_id and package["status"] == "draft"
    assert all(node["result"] is None and node["attempt"] == 0 for node in package["nodes"])
    issue(store, current, "submit_workpackage", {"workpackage_id": package["id"]})
    fresh = store.claim_node()
    assert fresh["previous_results"] == {} and not fresh["snapshot"].get("upstream_workpackage_id")


def test_quality_check_cannot_reuse_receipts_after_current_context_changes(tmp_path):
    store, project = submitted(tmp_path)
    finish_taskbook_with_document(store)
    current = store.get_project("owner", project["id"])
    current = issue(store, current, "save_context", {"context": {"product_type": "different product"}})
    current = issue(store, current, "pull_workpackage", {"definition_id": "quality_check"})
    with pytest.raises(Exception) as error:
        issue(store, current, "submit_workpackage", {"workpackage_id": current["cases"][0]["workpackages"][-1]["id"]})
    assert error.value.status == 422


def test_design_does_not_accept_a_verify_action_without_positive_check_receipt(tmp_path):
    store, project = submitted(tmp_path)
    Worker = importlib.import_module("service.rd_platform.runtime").Worker
    def execute(action, snapshot, previous, work_dir, progress, cancelled):
        if action == "generate":
            path = Path(work_dir) / "draft.docx"
            path.write_bytes(b"draft")
            return completed(artifacts=[{"id": "draft", "name": path.name, "kind": "docx", "path": str(path)}])
        return completed(result={"execution_mode": "local_real", "delivery_approved": False})
    worker = Worker(store, execute)
    for _ in range(5):
        worker.tick()
    current = store.get_project("owner", project["id"])
    sid = current["cases"][0]["sources"][0]["id"]
    with pytest.raises(Exception) as error:
        issue(store, current, "advance_stage", {"stage": "design", "verdict": "approved", "rationale": "未通过校验", "source_ids": [sid]})
    assert error.value.status == 422


def test_last_budgeted_attempt_is_not_revoked_by_an_idle_second_worker(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project = case_project(store)
    project = issue(store, project, "pull_workpackage", {"definition_id": "input_check"})
    project = issue(store, project, "submit_workpackage", {"workpackage_id": project["cases"][0]["workpackages"][0]["id"]})
    clock = [1_000_000.0]
    monkeypatch.setattr(importlib.import_module("service.rd_platform.store").time, "time", lambda: clock[0])
    for _ in range(2):
        assert store.claim_node(lease_seconds=60)
        clock[0] += 61
    final_attempt = store.claim_node()
    assert final_attempt["attempt"] == 3
    assert store.claim_node() is None
    assert package_of(store, project)["status"] == "running"
    assert store.complete_node(final_attempt, completed())
    assert package_of(store, project)["status"] == "completed"


def test_submission_fixes_actual_rule_hashes(tmp_path, monkeypatch):
    module = importlib.import_module("service.rd_platform.store")
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "policy.yaml").write_bytes(b"approved: true")
    monkeypatch.setattr(module, "_RULE_ROOT", rules, raising=False)
    store, project = submitted(tmp_path)
    import hashlib
    assert package_of(store, project)["snapshot"]["rule_versions"]["policy.yaml"] == hashlib.sha256(b"approved: true").hexdigest()


def test_changed_rules_block_before_execution_instead_of_changing_fixed_policy(tmp_path, monkeypatch):
    module = importlib.import_module("service.rd_platform.store")
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "policy.yaml").write_bytes(b"approved: true")
    monkeypatch.setattr(module, "_RULE_ROOT", rules, raising=False)
    store, project = submitted(tmp_path)
    (rules / "policy.yaml").write_bytes(b"approved: false")
    assert store.claim_node() is None and package_of(store, project)["status"] == "blocked"


def test_public_projection_keeps_logical_document_locations_but_removes_file_paths(tmp_path):
    store, project = submitted(tmp_path)
    claim = store.claim_node()
    store.complete_node(claim, completed(result={"ledger": [{"semantic_path": "章节/设计", "target_path": "document/section/1", "template_path": "C:/private/template.docx"}]}))
    row = package_of(store, project)["nodes"][0]["result"]["ledger"][0]
    assert row["semantic_path"] == "章节/设计" and row["target_path"] == "document/section/1"
    assert "template_path" not in row


def test_budget_expiration_rejects_result_even_when_lease_was_extended(tmp_path, monkeypatch):
    store, project = submitted(tmp_path)
    clock = [time.time()]
    monkeypatch.setattr(importlib.import_module("service.rd_platform.store").time, "time", lambda: clock[0])
    claim = store.claim_node(lease_seconds=2000)
    clock[0] += 1801
    assert not store.renew_claim(claim, lease_seconds=2000)
    assert not store.complete_node(claim, completed())
    assert store.claim_node() is None and package_of(store, project)["status"] == "blocked"


def test_running_optional_check_blocks_stage_exit_but_cancelled_optional_check_does_not(tmp_path):
    store, project = submitted(tmp_path)
    finish_taskbook_with_document(store)
    current = store.get_project("owner", project["id"])
    sid = current["cases"][0]["sources"][0]["id"]
    current = issue(store, current, "pull_workpackage", {"definition_id": "context_resolve"})
    optional_id = current["cases"][0]["workpackages"][-1]["id"]
    current = issue(store, current, "submit_workpackage", {"workpackage_id": optional_id})
    claim = store.claim_node()
    current = store.get_project("owner", project["id"])
    with pytest.raises(Exception) as error:
        issue(store, current, "advance_stage", {"stage": "design", "verdict": "approved", "rationale": "当前阶段动作仍运行", "source_ids": [sid]})
    assert error.value.status == 422
    current = issue(store, current, "cancel_workpackage", {"workpackage_id": optional_id})
    assert not store.complete_node(claim, completed())
    current = approve_engineering(store, current)
    current = issue(store, current, "advance_stage", {"stage": "design", "verdict": "approved", "rationale": "任务书完成，可选检查已取消", "source_ids": [sid]})
    assert current["cases"][0]["stage"] == "verification"


def test_design_without_any_taskbook_cannot_enter_an_unrecoverable_verification_stage(tmp_path):
    from test_store import evidence_project
    store = new_store(tmp_path)
    current = evidence_project(store)
    sid = current["cases"][0]["sources"][0]["id"]
    with pytest.raises(Exception) as error:
        issue(store, current, "advance_stage", {"stage": "design", "verdict": "approved", "rationale": "尚未装配任务书", "source_ids": [sid]})
    assert error.value.status == 422


@pytest.mark.parametrize("change", ["context", "model", "requirement", "new_requirement"])
def test_changed_facts_after_design_return_to_input_for_reconfirmation(tmp_path, change):
    store, project = submitted(tmp_path)
    finish_taskbook_with_document(store)
    current = store.get_project("owner", project["id"])
    case = current["cases"][0]
    sid = case["sources"][0]["id"]
    current = approve_engineering(store, current)
    current = issue(store, current, "advance_stage", {"stage": "design", "verdict": "approved", "rationale": "设计成果核对通过", "source_ids": [sid]})
    old_case = current["cases"][0]
    if change == "context":
        command, data = "save_context", {"context": {"product_type": "changed-product"}}
    elif change == "model":
        command, data = "save_context", {"context": {}, "model_selection": {"provider": "controlled", "name": "chosen", "id": "model-2"}}
    elif change == "requirement":
        command, data = "save_requirement", {**old_case["requirements"][0], "content": "人工更新后的需求正文"}
    else:
        command, data = "save_requirement", {"title": "新增需求", "content": "新的明确要求", "source_ids": [sid]}
    updated = issue(store, current, command, data)
    case = updated["cases"][0]
    assert case["stage"] == "input" and case["input_revision"] == old_case["input_revision"] + 1
    assert case["product_route"] is None and case["composition_route"] is None
    assert all(decision.get("invalidated_at") for decision in case["decisions"] if decision.get("verdict") == "approved" or decision["kind"] == "route")
    assert case["workpackages"][0]["snapshot"] == old_case["workpackages"][0]["snapshot"]
    assert updated["events"][-1]["data"]["invalidated_decision_ids"]


@pytest.mark.parametrize("save", ["context", "model", "requirement"])
def test_unchanged_fact_saves_keep_stage_approvals_and_input_revision(tmp_path, save):
    store, project = submitted(tmp_path)
    finish_taskbook_with_document(store)
    current = store.get_project("owner", project["id"])
    old_case = current["cases"][0]
    if save == "context":
        command, data = "save_context", {"context": dict(old_case["context"])}
    elif save == "empty_context_fields":
        command, data = "save_context", {"context": {"product_type": "", "product_domain": " "}}
    elif save == "model":
        command, data = "save_context", {"context": {}, "model_selection": dict(old_case["model_selection"])}
    else:
        command, data = "save_requirement", dict(old_case["requirements"][0])
    updated = issue(store, current, command, data)
    case = updated["cases"][0]
    assert case["stage"] == old_case["stage"] and case["input_revision"] == old_case["input_revision"]
    assert case["context"] == old_case["context"]
    assert case["decisions"] == old_case["decisions"]
    assert case["product_route"] == old_case["product_route"] and case["composition_route"] == old_case["composition_route"]


def test_inflight_old_result_does_not_restore_approvals_or_overwrite_new_facts(tmp_path):
    store, project = submitted(tmp_path)
    claim = store.claim_node()
    current = store.get_project("owner", project["id"])
    fixed = current["cases"][0]["workpackages"][0]["snapshot"]
    updated = issue(store, current, "save_context", {"context": {"product_type": "new-input"}})
    assert updated["cases"][0]["stage"] == "input"
    assert updated["cases"][0]["workpackages"][0]["nodes"][0]["status"] == "running"
    assert store.complete_node(claim, completed(result={"context": {"product_type": "old-resolved-value"}, "execution_mode": "local_real"}))
    case = store.get_project("owner", project["id"])["cases"][0]
    assert case["context"] == {**fixed["context"], "product_type": "new-input"} and case["stage"] == "input"
    assert case["product_route"] is None and case["composition_route"] is None
    assert case["workpackages"][0]["snapshot"] == fixed
    assert case["workpackages"][0]["nodes"][0]["result"]["context"] == {"product_type": "old-resolved-value"}


def test_actual_dates_come_from_claims_and_successful_outcomes(tmp_path):
    from datetime import datetime, timezone
    store, project = submitted(tmp_path)
    package = package_of(store, project)
    assert package["started_at"] is None and package["completed_at"] is None and package["ended_at"] is None
    before = datetime.now(timezone.utc)
    finish_taskbook_with_document(store)
    after = datetime.now(timezone.utc)
    package = package_of(store, project)
    assert before <= datetime.fromisoformat(package["started_at"]) <= datetime.fromisoformat(package["completed_at"]) <= after
    assert package["ended_at"] == package["completed_at"]
    previous_end = package["started_at"]
    for node in package["nodes"]:
        assert previous_end <= node["started_at"] <= node["completed_at"] == node["ended_at"]
        previous_end = node["ended_at"]
    reopened = new_store(tmp_path).get_project("owner", project["id"])["cases"][0]["workpackages"][0]
    assert reopened["started_at"] == package["started_at"] and reopened["ended_at"] == package["ended_at"]


@pytest.mark.parametrize("status", ["blocked", "failed"])
def test_unsuccessful_execution_has_an_end_fact_but_no_completed_date(tmp_path, status):
    store, project = submitted(tmp_path)
    claim = store.claim_node()
    running = package_of(store, project)
    assert running["started_at"] and running["ended_at"] is None
    assert store.complete_node(claim, {"status": status, "result": {}, "blocked_reasons": ["真实执行未完成"]})
    package = package_of(store, project)
    assert package["status"] == status and package["started_at"] == running["started_at"]
    assert package["ended_at"] and package["completed_at"] is None
    assert package["nodes"][0]["ended_at"] and package["nodes"][0]["completed_at"] is None
    assert package["nodes"][1]["started_at"] is None and package["nodes"][1]["ended_at"] is None


@pytest.mark.parametrize("started", [False, True])
def test_cancel_records_end_without_inventing_a_success_or_unstarted_date(tmp_path, started):
    store, project = submitted(tmp_path)
    claim = store.claim_node() if started else None
    current = store.get_project("owner", project["id"])
    current = issue(store, current, "cancel_workpackage", {"workpackage_id": current["cases"][0]["workpackages"][0]["id"]})
    package = package_of(store, project)
    assert bool(package["started_at"]) is started
    assert package["status"] == "cancelled" and package["ended_at"] and package["completed_at"] is None
    terminal_time = package["ended_at"]
    if claim:
        assert not store.complete_node(claim, completed())
    assert package_of(store, project)["ended_at"] == terminal_time
    assert all(node["completed_at"] is None for node in package["nodes"])


def test_block_before_claim_has_an_end_fact_and_no_invented_start(tmp_path):
    store, project = submitted(tmp_path)
    source = project["cases"][0]["sources"][0]
    store.source_path("owner", project["id"], project["cases"][0]["id"], source["id"]).write_bytes(b"tampered")
    assert store.claim_node() is None
    package = package_of(store, project)
    assert package["status"] == "blocked" and package["ended_at"]
    assert package["started_at"] is None and package["completed_at"] is None
    assert all(node["started_at"] is None and node["completed_at"] is None for node in package["nodes"])


def test_expired_generation_claim_blocks_instead_of_replaying_external_side_effects(tmp_path, monkeypatch):
    store, project = submitted(tmp_path)
    for _ in range(3):
        assert store.complete_node(store.claim_node(), completed())
    clock = [time.time()]
    monkeypatch.setattr(importlib.import_module("service.rd_platform.store").time, "time", lambda: clock[0])
    generation = store.claim_node(lease_seconds=1)
    assert generation["action_id"] == "generate"
    clock[0] += 2
    assert new_store(tmp_path).claim_node() is None
    package = package_of(store, project)
    assert package["status"] == "blocked"
    assert package["nodes"][3]["attempt"] == 1
    assert not store.complete_node(generation, completed())
