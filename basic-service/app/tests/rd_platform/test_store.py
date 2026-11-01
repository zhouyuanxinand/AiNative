"""Case lifecycle, independent route decisions and fixed delegations are durable facts."""
import hashlib
import importlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest


def new_store(tmp_path):
    return importlib.import_module("service.rd_platform.store").Store(tmp_path / "rd.sqlite3", tmp_path / "assets")


def issue(store, project, command, data=None, key=None):
    data = dict(data or {})
    if command != "create_case" and project["cases"]:
        data.setdefault("case_id", project["cases"][0]["id"])
    return store.command("owner", project["id"], project["version"], key or f"k-{project['version']}-{command}", command, data)


def case_project(store):
    project = store.create_project("owner", "连接器研发", {})
    return issue(store, project, "create_case", {"scenario_id": "taskbook", "title": "研制任务书案例"})


def fixture_comparison(store, project, axis):
    case = project["cases"][0]
    source_id = case["sources"][0]["id"]
    project = issue(store, project, "save_comparison", {"kind": "product" if axis == "product" else "document", "title": "测试夹具的逐项人工核对", "source_ids": [source_id],
        "rows": [{"requirement_id": requirement["id"], "assessment": "match", "candidate_value": requirement["content"], "reason": "测试夹具已按来源逐项核对", "source_ids": [source_id]}
                 for requirement in case["requirements"]]})
    return project, project["cases"][0]["comparisons"][-1]["id"]


def evidence_project(store, product_route="new", composition_route="direct", context=None, *, stop_at_planning=False):
    project = case_project(store)
    defaults = {"product_type": "low_frequency_rectangular", "product_domain": "military", "development_process": "全新", "cover_phase": "S", "product_series": "TEST-A", "organization_scope": "non_central_research"}
    project = issue(store, project, "save_context", {"context": {**defaults, **(context or {})}})
    cid = project["cases"][0]["id"]
    project = store.add_source("owner", project["id"], cid, project["version"], "upload", "tech", "技术要求.txt", b"source evidence")
    project = store.add_source("owner", project["id"], cid, project["version"], "upload-spec", "spec", "规范.txt", b"specification evidence")
    source_id = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "save_requirement", {"title": "温度要求", "content": "按原技术要求验证", "source_ids": [source_id]})
    for stage in ("input", "requirements", "selection", "planning"):
        if stage == "selection":
            for axis, value in (("product", product_route), ("composition", composition_route)):
                project, comparison_id = fixture_comparison(store, project, axis)
                project = issue(store, project, "record_route_decision", {"axis": axis, "value": value, "rationale": "人工分别核对路线依据", "source_ids": [source_id], "comparison_id": comparison_id})
        if stage == "planning":
            if product_route == "direct" or stop_at_planning:
                break
            project = issue(store, project, "adopt_taskbook_flow", {"workflow_id": "taskbook-" + product_route + "-v1", "workflow_version": "1", "scope": "按当前需求编制任务书", "rationale": "人工核对当前需求与研发范围"})
        project = issue(store, project, "advance_stage", {"stage": stage, "verdict": "approved", "rationale": "人工核对原始依据后决定", "source_ids": [source_id]})
    return project


def taskbook(store):
    project = evidence_project(store)
    return issue(store, project, "pull_workpackage", {"definition_id": "taskbook"})


def test_project_permissions_and_facts_survive_restart(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project("owner", "研发项目", {})
    assert project["cases"] == [] and project["owner_id"] == "owner"
    project = issue(store, project, "create_case", {"scenario_id": "taskbook", "title": "完整案例"})
    case = project["cases"][0]
    assert case["stage"] == "input" and case["context"] == {}
    assert case["product_route"] is None and case["composition_route"] is None
    assert new_store(tmp_path).get_project("owner", project["id"]) == project
    assert store.list_projects("outsider") == []
    with pytest.raises(Exception) as error:
        store.get_project("outsider", project["id"])
    assert error.value.status == 404


def test_idempotency_precedes_cas_and_changed_intent_is_rejected(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    data = {"case_id": project["cases"][0]["id"], "context": {"product_type": "connector"}}
    args = ("owner", project["id"], project["version"], "same-key", "save_context", data)
    result = store.command(*args)
    assert store.command(*args) == result
    with pytest.raises(Exception) as error:
        store.command(*args[:-1], {**data, "context": {"product_type": "other"}})
    assert error.value.status == 409
    with pytest.raises(Exception) as error:
        store.command("owner", project["id"], project["version"], "different-key", "save_context", data)
    assert error.value.status == 409


def test_concurrent_cas_writers_do_not_lose_updates(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    def write(index):
        try:
            return new_store(tmp_path).command("owner", project["id"], project["version"], str(index), "save_context", {"case_id": project["cases"][0]["id"], "context": {"product_type": str(index)}})["version"]
        except Exception as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, (1, 2))) == [3, 409]


def test_upload_versions_bytes_hash_and_access_checks(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    cid = project["cases"][0]["id"]
    first = store.add_source("owner", project["id"], cid, project["version"], "source-1", "tech", "../要求.txt", b"one")
    second = store.add_source("owner", project["id"], cid, first["version"], "source-2", "tech", "要求.txt", b"two")
    sources = second["cases"][0]["sources"]
    assert [row["version"] for row in sources] == [1, 2]
    assert sources[0]["sha256"] == hashlib.sha256(b"one").hexdigest()
    assert '"path"' not in json.dumps(second)
    assert store.source_path("owner", project["id"], cid, sources[0]["id"]).read_bytes() == b"one"
    with pytest.raises(Exception) as error:
        store.source_path("outsider", project["id"], cid, sources[0]["id"])
    assert error.value.status == 404
    assert store.add_source("owner", project["id"], cid, project["version"], "source-1", "tech", "../要求.txt", b"one") == first


def test_cases_cannot_borrow_sources_or_route_decisions_from_each_other(tmp_path):
    store = new_store(tmp_path)
    project = evidence_project(store)
    source_id = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "create_case", {"scenario_id": "taskbook", "title": "另一个案例"})
    second = project["cases"][1]
    assert second["stage"] == "input" and second["product_route"] is None
    with pytest.raises(Exception) as error:
        issue(store, project, "save_requirement", {"case_id": second["id"], "title": "错误复用", "content": "other case", "source_ids": [source_id]})
    assert error.value.status == 422


def test_full_lifecycle_and_both_routes_are_independent_even_for_direct_products(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    with pytest.raises(Exception):
        issue(store, project, "advance_stage", {"stage": "verification", "verdict": "approved", "rationale": "skip", "source_ids": []})
    with pytest.raises(Exception):
        issue(store, project, "advance_stage", {"stage": "input", "verdict": "approved", "rationale": "empty", "source_ids": []})
    project = evidence_project(store, product_route="direct", composition_route="new")
    case = project["cases"][0]
    assert case["stage"] == "planning"
    assert case["taskbook_binding"] is None
    assert case["product_route"]["value"] == "direct" and case["composition_route"]["value"] == "new"
    assert [row["stage"] for row in case["decisions"] if row["kind"] == "stage"] == ["input", "requirements", "selection"]
    assert case["context"]["product_type"] == "low_frequency_rectangular"


def test_selection_does_not_advance_with_only_one_route(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    cid = project["cases"][0]["id"]
    project = store.add_source("owner", project["id"], cid, project["version"], "s", "tech", "证据.txt", b"evidence")
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "save_requirement", {"title": "需求", "content": "有来源", "source_ids": [sid]})
    for stage in ("input", "requirements"):
        project = issue(store, project, "advance_stage", {"stage": stage, "verdict": "approved", "rationale": "人工决定", "source_ids": [sid]})
    project, comparison_id = fixture_comparison(store, project, "product")
    project = issue(store, project, "record_route_decision", {"axis": "product", "value": "new", "rationale": "新研", "source_ids": [sid], "comparison_id": comparison_id})
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "selection", "verdict": "approved", "rationale": "缺少编制路线", "source_ids": [sid]})
    assert error.value.status == 422


def test_rejection_stays_in_stage_and_never_synthesizes_approval(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    project = issue(store, project, "advance_stage", {"stage": "input", "verdict": "rejected", "rationale": "缺少技术要求", "source_ids": []})
    case = project["cases"][0]
    assert case["stage"] == "input" and case["decisions"][0]["verdict"] == "rejected"
    assert case["workpackages"] == []


def test_plan_keeps_mandatory_checks_and_rejects_cycles_or_wrong_versions(tmp_path):
    store = new_store(tmp_path)
    project = taskbook(store)
    package = project["cases"][0]["workpackages"][0]
    assert [row["action_id"] for row in package["nodes"]] == ["resolve_context", "template_plan", "content_completion", "generate", "verify"]
    bad = [dict(row) for row in package["nodes"] if row["action_id"] != "verify"]
    with pytest.raises(Exception):
        issue(store, project, "save_plan", {"workpackage_id": package["id"], "nodes": bad})
    bad = json.loads(json.dumps(package["nodes"]))
    bad[0]["depends_on"] = [bad[-1]["id"]]
    with pytest.raises(Exception):
        issue(store, project, "save_plan", {"workpackage_id": package["id"], "nodes": bad})
    bad[0]["depends_on"] = []
    bad[0]["action_version"] = "unpublished"
    with pytest.raises(Exception):
        issue(store, project, "save_plan", {"workpackage_id": package["id"], "nodes": bad})


def test_taskbook_is_design_local_but_other_stages_have_real_actions(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    with pytest.raises(Exception):
        issue(store, project, "pull_workpackage", {"definition_id": "taskbook"})
    project = issue(store, project, "pull_workpackage", {"definition_id": "input_check"})
    package = project["cases"][0]["workpackages"][0]
    assert package["stage"] == "input" and package["nodes"][0]["action_id"] == "consistency"


def test_submission_fixes_case_routes_versions_sources_and_durable_intent(tmp_path):
    store = new_store(tmp_path)
    project = taskbook(store)
    package_id = project["cases"][0]["workpackages"][0]["id"]
    project = issue(store, project, "submit_workpackage", {"workpackage_id": package_id})
    package = project["cases"][0]["workpackages"][0]
    assert package["status"] == "submitted" and package["run_id"]
    assert package["snapshot"]["actor_id"] == "owner"
    assert package["snapshot"]["sources"][0]["sha256"] == hashlib.sha256(b"source evidence").hexdigest()
    assert package["snapshot"]["product_route"]["value"] == "new"
    assert package["snapshot"]["composition_route"]["value"] == "direct"
    assert package["snapshot"]["rule_versions"] and package["snapshot"]["budget"]["max_total_attempts"] > 0
    changed = issue(store, project, "save_context", {"context": {"product_type": "later change"}})
    assert changed["cases"][0]["workpackages"][0]["snapshot"]["context"] == package["snapshot"]["context"]
    claim = new_store(tmp_path).claim_node()
    assert claim["action_id"] == "resolve_context" and claim["run_id"] == package["run_id"]
    with pytest.raises(Exception):
        issue(store, changed, "save_plan", {"workpackage_id": package_id, "nodes": package["nodes"]})


def test_workspace_revision_history_and_permission(tmp_path):
    store = new_store(tmp_path)
    assert {row["id"] for row in store.list_resources()} >= {"resolve_context", "template_plan", "content_completion", "generate", "verify", "consistency"}
    payload = {"kind": "skill", "name": "本地审查", "description": "工程说明", "configuration": {"execution_mode": "local_real"}, "operation": "save"}
    with pytest.raises(Exception) as error:
        store.save_resource("owner", payload)
    assert error.value.status == 403
    first = store.save_resource("manager", payload, can_manage=True)
    second = store.save_resource("manager", {**payload, "id": first["id"], "expected_version": 1, "operation": "publish"}, can_manage=True)
    assert first["version"] == 1 and first["status"] == "draft"
    assert second["version"] == 2 and second["status"] == "published"
    assert new_store(tmp_path).get_resource(first["id"], 1) == first
    with pytest.raises(Exception) as error:
        store.save_resource("manager", {**payload, "id": first["id"], "expected_version": 1}, can_manage=True)
    assert error.value.status == 409


@pytest.mark.parametrize("data", [{"context": {"not_a_parameter": "x"}}, {"context": {"product_type": 123}}, {"context": {}, "model_selection": {"provider": 1, "name": "", "id": ""}}])
def test_context_rejects_invalid_facts_instead_of_inventing_defaults(tmp_path, data):
    store = new_store(tmp_path)
    project = case_project(store)
    with pytest.raises(Exception) as error:
        issue(store, project, "save_context", data)
    assert error.value.status == 422


@pytest.mark.parametrize("classification,process", [("new", "modification"), ("new", "改型I"), ("direct", "全新")])
def test_conflicting_product_process_is_reported_without_changing_either_route(tmp_path, classification, process):
    store = new_store(tmp_path)
    project = evidence_project(store, product_route=classification, composition_route="direct", context={"development_process": process}, stop_at_planning=True)
    case = project["cases"][0]
    assert case["warnings"][0]["code"] == "product_route_context_conflict"
    assert case["context"]["development_process"] == process
    assert case["product_route"]["value"] == classification and case["composition_route"]["value"] == "direct"


def test_optional_consistency_can_be_inserted_without_bypassing_mandatory_dependency(tmp_path):
    store = new_store(tmp_path)
    project = taskbook(store)
    package = project["cases"][0]["workpackages"][0]
    nodes = json.loads(json.dumps(package["nodes"]))
    nodes.append({"id": "additional_check", "action_id": "consistency", "action_version": "1", "depends_on": ["content_completion"], "required": False})
    next(node for node in nodes if node["id"] == "generate")["depends_on"] = ["additional_check"]
    project = issue(store, project, "save_plan", {"workpackage_id": package["id"], "nodes": nodes})
    assert project["cases"][0]["workpackages"][0]["plan_revision"] == 2
    assert len(project["cases"][0]["workpackages"][0]["nodes"]) == 6


def test_stage_decision_cannot_use_missing_or_tampered_source_bytes(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    cid = project["cases"][0]["id"]
    project = store.add_source("owner", project["id"], cid, project["version"], "source", "tech", "source.txt", b"genuine")
    sid = project["cases"][0]["sources"][0]["id"]
    store.source_path("owner", project["id"], cid, sid).write_bytes(b"tampered")
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "input", "verdict": "approved", "rationale": "不可依赖失真资料", "source_ids": [sid]})
    assert error.value.status == 409


def test_create_project_retries_do_not_duplicate_projects_and_reject_changed_intent(tmp_path):
    store = new_store(tmp_path)
    first = store.create_project("owner", "项目", {"product_type": "connector"}, key="stable-create")
    replay = new_store(tmp_path).create_project("owner", "项目", {"product_type": "connector"}, key="stable-create")
    assert replay == first and len(store.list_projects("owner")) == 1
    with pytest.raises(Exception) as error:
        store.create_project("owner", "不同项目", {"product_type": "connector"}, key="stable-create")
    assert error.value.status == 409
    separate_actor = store.create_project("another", "项目", {"product_type": "connector"}, key="stable-create")
    assert separate_actor["id"] != first["id"]


def test_same_create_key_is_atomic_across_connections(tmp_path):
    store = new_store(tmp_path)
    def create(_):
        return new_store(tmp_path).create_project("owner", "相同创建", {}, key="same-create")["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(create, (1, 2)))) == 1
    assert len(store.list_projects("owner")) == 1


def test_dense_32_node_dag_validation_has_bounded_work(tmp_path):
    store = new_store(tmp_path)
    project = taskbook(store)
    package = project["cases"][0]["workpackages"][0]
    actions = ["resolve_context", "template_plan"] + ["consistency"] * 27 + ["content_completion", "generate", "verify"]
    nodes = [{"id": f"n{index}", "action_id": action, "action_version": "1", "depends_on": [f"n{previous}" for previous in range(index)],
              "required": action != "consistency"} for index, action in enumerate(actions)]
    calls = 0
    def watchdog(frame, event, argument):
        nonlocal calls
        if event == "call" and frame.f_globals.get("__name__") == "service.rd_platform.store":
            calls += 1
            if calls > 5000:
                raise AssertionError("DAG validation repeatedly recomputes ancestor subgraphs")
    sys.setprofile(watchdog)
    try:
        updated = issue(store, project, "save_plan", {"workpackage_id": package["id"], "nodes": nodes})
    finally:
        sys.setprofile(None)
    assert len(updated["cases"][0]["workpackages"][0]["nodes"]) == 32


def test_new_active_source_keeps_history_but_invalidates_prior_approvals(tmp_path):
    store = new_store(tmp_path)
    project = taskbook(store)
    cid = project["cases"][0]["id"]
    project = issue(store, project, "submit_workpackage", {"workpackage_id": project["cases"][0]["workpackages"][0]["id"]})
    old_snapshot = project["cases"][0]["workpackages"][0]["snapshot"]
    old_sid = project["cases"][0]["sources"][0]["id"]
    updated = store.add_source("owner", project["id"], cid, project["version"], "revision-2", "tech", "技术要求.txt", b"revised evidence")
    case = updated["cases"][0]
    new_sid = case["sources"][-1]["id"]
    assert len(case["sources"]) == 3 and case["sources"][-1]["version"] == 2
    assert case["source_selection"]["tech"] == new_sid
    assert case["stage"] == "input" and case["product_route"] is None and case["composition_route"] is None
    assert all(decision.get("invalidated_at") for decision in case["decisions"] if decision.get("verdict") == "approved" or decision["kind"] == "route")
    assert case["workpackages"][0]["snapshot"] == old_snapshot
    assert store.source_path("owner", project["id"], cid, old_sid).read_bytes() == b"source evidence"
    assert updated["events"][-1]["data"]["selected_source_id"] == new_sid
    updated = issue(store, updated, "advance_stage", {"stage": "input", "verdict": "approved", "rationale": "确认新版资料", "source_ids": [new_sid]})
    with pytest.raises(Exception) as error:
        issue(store, updated, "advance_stage", {"stage": "requirements", "verdict": "approved", "rationale": "旧需求尚未复核", "source_ids": [new_sid]})
    assert error.value.status == 422
    requirement = updated["cases"][0]["requirements"][0]
    updated = issue(store, updated, "save_requirement", {**requirement, "source_ids": [new_sid]})
    updated = issue(store, updated, "advance_stage", {"stage": "input", "verdict": "approved", "rationale": "按修改后的需求重新确认输入", "source_ids": [new_sid]})
    updated = issue(store, updated, "advance_stage", {"stage": "requirements", "verdict": "approved", "rationale": "按新版资料复核需求", "source_ids": [new_sid]})
    assert updated["cases"][0]["stage"] == "selection"


def test_selected_source_only_is_fixed_in_new_snapshot_and_can_be_reselected(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    cid = project["cases"][0]["id"]
    project = store.add_source("owner", project["id"], cid, project["version"], "v1", "tech", "要求.txt", b"one")
    first_sid = project["cases"][0]["sources"][0]["id"]
    project = store.add_source("owner", project["id"], cid, project["version"], "v2", "tech", "要求.txt", b"two")
    second_sid = project["cases"][0]["sources"][-1]["id"]
    project = issue(store, project, "pull_workpackage", {"definition_id": "input_check"})
    project = issue(store, project, "submit_workpackage", {"workpackage_id": project["cases"][0]["workpackages"][0]["id"]})
    fixed = project["cases"][0]["workpackages"][0]["snapshot"]
    assert [source["id"] for source in fixed["sources"]] == [second_sid]
    assert fixed["source_selection"] == {"tech": second_sid}
    project = issue(store, project, "select_source", {"role": "tech", "source_id": first_sid})
    assert project["cases"][0]["source_selection"] == {"tech": first_sid}
    assert project["cases"][0]["workpackages"][0]["snapshot"] == fixed
    with pytest.raises(Exception):
        issue(store, project, "select_source", {"role": "spec", "source_id": first_sid})


def test_draft_schedule_revisions_survive_restart_and_submission_fixes_the_selected_revision(tmp_path):
    store = new_store(tmp_path)
    project = taskbook(store)
    package = project["cases"][0]["workpackages"][0]
    wid = package["id"]
    assert package["planned_start"] is None and package["planned_end"] is None
    assert package["schedule_revision"] == 0 and package["schedule_history"] == []
    nodes_before = package["nodes"]
    project = issue(store, project, "save_schedule", {"workpackage_id": wid, "planned_start": "2026-11-02", "planned_end": "2026-11-04", "plan_note": "依据已确认的资源窗口"})
    first = project["cases"][0]["workpackages"][0]
    project = issue(store, project, "save_schedule", {"workpackage_id": wid, "planned_start": "2026-11-03", "planned_end": "2026-11-06", "plan_note": "草稿窗口修订"})
    package = new_store(tmp_path).get_project("owner", project["id"])["cases"][0]["workpackages"][0]
    assert package["schedule_revision"] == 2
    assert [entry["revision"] for entry in package["schedule_history"]] == [1, 2]
    assert package["schedule_history"][0]["planned_start"] == "2026-11-02"
    assert package["schedule_history"][0]["actor"] == "owner"
    assert package["nodes"] == nodes_before
    project = issue(store, project, "save_schedule", {"workpackage_id": wid, "planned_start": "2026-11-03", "planned_end": "2026-11-06", "plan_note": "草稿窗口修订"})
    assert project["cases"][0]["workpackages"][0]["schedule_revision"] == 2
    project = issue(store, project, "submit_workpackage", {"workpackage_id": wid})
    fixed = project["cases"][0]["workpackages"][0]["snapshot"]["schedule"]
    assert fixed == {"revision": 2, "planned_start": "2026-11-03", "planned_end": "2026-11-06", "plan_note": "草稿窗口修订"}
    with pytest.raises(Exception) as error:
        issue(store, project, "save_schedule", {"workpackage_id": wid, "planned_start": "2026-11-05", "planned_end": "2026-11-08", "plan_note": "不能改固定委托"})
    assert error.value.status == 409


@pytest.mark.parametrize("start,end", [("2026-11-04", "2026-11-02"), ("2026-02-30", "2026-03-01"), ("2026-11-01T12:00:00Z", None), (123, None)])
def test_schedule_rejects_invalid_or_reversed_calendar_dates(tmp_path, start, end):
    store = new_store(tmp_path)
    project = taskbook(store)
    wid = project["cases"][0]["workpackages"][0]["id"]
    project = issue(store, project, "save_schedule", {"workpackage_id": wid, "planned_start": "2026-11-01", "planned_end": "2026-11-05", "plan_note": "有效的初始日期窗口"})
    assert project["cases"][0]["workpackages"][0]["planned_start"] == "2026-11-01"
    with pytest.raises(Exception) as error:
        issue(store, project, "save_schedule", {"workpackage_id": wid, "planned_start": start, "planned_end": end, "plan_note": "人工计划"})
    assert error.value.status == 422
    unchanged = store.get_project("owner", project["id"])
    assert unchanged["version"] == project["version"]
    assert unchanged["cases"][0]["workpackages"][0]["schedule_revision"] == 1


def test_unknown_schedule_dates_stay_null_and_client_cannot_write_actual_dates(tmp_path):
    store = new_store(tmp_path)
    project = taskbook(store)
    wid = project["cases"][0]["workpackages"][0]["id"]
    project = issue(store, project, "save_schedule", {"workpackage_id": wid, "planned_start": None, "planned_end": "2026-11-10", "plan_note": "开始时间尚未确定", "started_at": "2026-11-01T00:00:00Z", "completed_at": "2026-11-10T00:00:00Z"})
    package = project["cases"][0]["workpackages"][0]
    assert package["planned_start"] is None and package["planned_end"] == "2026-11-10"
    assert package["started_at"] is None and package["completed_at"] is None and package["ended_at"] is None
    assert all(node["started_at"] is None and node["completed_at"] is None and node["ended_at"] is None for node in package["nodes"])


@pytest.mark.parametrize("configuration", [
    {"api_key": "actual-credential"}, {"nested": {"password": "actual-credential"}},
    {"nested": [{"access_token": "actual-credential"}]}, {"nested": {"authorization": "Bearer actual-credential"}},
    {"provider": {"apiKey": "actual-credential"}}, {"private_key": "actual-private-key"},
])
def test_workspace_rejects_raw_credentials_even_in_nested_configuration(tmp_path, configuration):
    store = new_store(tmp_path)
    before = len(store.list_resources())
    with pytest.raises(Exception) as error:
        store.save_resource("manager", {"kind": "agent", "name": "受控资源", "configuration": configuration, "operation": "save"}, can_manage=True)
    assert error.value.status == 422
    assert "凭证" in error.value.detail and "actual-credential" not in error.value.detail
    assert len(store.list_resources()) == before


def test_workspace_allows_credential_references_and_token_budgets_without_scanning_prompt_text(tmp_path):
    store = new_store(tmp_path)
    configuration = {"credentials_ref": "credentials/provider-1", "nested": {"secret_ref": "vault/rd-key", "model_config_ref": "models/local-1"},
                     "max_tokens": 8192, "prompt": "解释token预算以及password字段概念，不扫描这段普通提示词。"}
    resource = store.save_resource("manager", {"kind": "agent", "name": "仅引用凭证", "configuration": configuration, "operation": "publish"}, can_manage=True)
    assert resource["configuration"] == configuration
    assert store.get_resource(resource["id"])["configuration"] == configuration


def test_planning_requires_server_owned_taskbook_template_adoption(tmp_path):
    store = new_store(tmp_path)
    project = evidence_project(store)
    case = project["cases"][0]
    assert case.get("taskbook_binding", {}).get("status") == "current"
    assert case["taskbook_binding"]["workflow"]["id"] == "taskbook-new-v1"
    assert case["taskbook_binding"]["document_template"]["template_sha256"]
    assert len(case["taskbook_binding_history"]) == 1


def test_binding_is_retained_but_stale_after_input_change(tmp_path):
    store = new_store(tmp_path)
    project = evidence_project(store)
    binding = project["cases"][0].get("taskbook_binding")
    assert binding is not None
    project = issue(store, project, "save_context", {"context": {"product_series": "second-revision"}})
    case = project["cases"][0]
    assert case["taskbook_binding"]["status"] == "stale"
    assert case["taskbook_binding"]["fingerprint"] == binding["fingerprint"]
    assert case["taskbook_binding_history"][0]["status"] == "current"


def test_planning_cannot_advance_without_adoption_and_rejects_client_snapshots(tmp_path):
    store = new_store(tmp_path)
    project = evidence_project(store, stop_at_planning=True)
    sid = project["cases"][0]["sources"][0]["id"]
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "planning", "verdict": "approved", "rationale": "missing binding", "source_ids": [sid]})
    assert error.value.status == 422
    data = {"workflow_id": "taskbook-new-v1", "workflow_version": "1", "scope": "current requirements", "rationale": "user choice"}
    for changed in ({"document_template": {}}, {"workflow_id": "taskbook-modification-v1"}, {"workflow_version": "999"}):
        with pytest.raises(Exception) as error:
            issue(store, project, "adopt_taskbook_flow", {**data, **changed})
        assert error.value.status == 422
    project = issue(store, project, "adopt_taskbook_flow", data, key="adopt")
    assert len(project["cases"][0]["taskbook_binding_history"]) == 1
    project = issue(store, project, "adopt_taskbook_flow", data, key="adopt-again")
    assert len(project["cases"][0]["taskbook_binding_history"]) == 2
    binding = project["cases"][0]["taskbook_binding"]
    assert binding["revision"] == 2 and binding["adopted_by"] == "owner"
    assert '"path"' not in json.dumps(binding)
    assert new_store(tmp_path).get_project("owner", project["id"]) == project


def test_binding_comparison_revision_is_stale_and_history_remains_immutable(tmp_path):
    store = new_store(tmp_path)
    project = evidence_project(store, stop_at_planning=True)
    project = issue(store, project, "adopt_taskbook_flow", {"workflow_id": "taskbook-new-v1", "workflow_version": "1", "scope": "current scope", "rationale": "current evidence"})
    previous = project["cases"][0]["taskbook_binding_history"][0]
    comparison = project["cases"][0]["comparisons"][0]
    rows = [{key: row[key] for key in ("requirement_id", "assessment", "candidate_value", "reason", "source_ids")} for row in comparison["rows"]]
    rows[0]["reason"] = "new comparison evidence"
    project = issue(store, project, "save_comparison", {"id": comparison["id"], "kind": comparison["kind"], "title": comparison["title"], "source_ids": comparison["source_ids"], "rows": rows})
    assert project["cases"][0]["taskbook_binding"]["status"] == "stale"
    assert project["cases"][0]["taskbook_binding_history"][0] == previous


@pytest.mark.parametrize("field,value", [("cover_phase", "Z"), ("development_process", "invented-process"), ("organization_scope", "invented-scope")])
def test_adoption_rejects_uncontrolled_six_parameter_values(tmp_path, field, value):
    store = new_store(tmp_path)
    project = evidence_project(store, context={field: value}, stop_at_planning=True)
    with pytest.raises(Exception) as error:
        issue(store, project, "adopt_taskbook_flow", {"workflow_id": "taskbook-new-v1", "workflow_version": "1", "scope": "scope", "rationale": "basis"})
    assert error.value.status == 422


def test_bound_docx_bytes_changing_after_submit_block_execution(tmp_path, monkeypatch):
    from copy import deepcopy
    bindings = importlib.import_module("service.rd_platform.business_binding")
    original = bindings.document_template
    def isolated_template(context):
        document = deepcopy(original(context))
        for kind, asset in document["assets"].items():
            target = tmp_path / (kind + ".asset")
            target.write_bytes(__import__("pathlib").Path(asset["path"]).read_bytes())
            asset["path"] = str(target)
        return document
    monkeypatch.setattr(bindings, "document_template", isolated_template)
    store = new_store(tmp_path)
    project = taskbook(store)
    wid = project["cases"][0]["workpackages"][0]["id"]
    project = issue(store, project, "submit_workpackage", {"workpackage_id": wid})
    (tmp_path / "template.asset").write_bytes(b"changed template revision")
    assert new_store(tmp_path).claim_node() is None
    package = store.get_project("owner", project["id"])["cases"][0]["workpackages"][0]
    assert package["status"] == "blocked"
    assert all(node["attempt"] == 0 for node in package["nodes"])
    assert package["snapshot"]["taskbook_binding"]["document_template"]["template_sha256"] != hashlib.sha256(b"changed template revision").hexdigest()
