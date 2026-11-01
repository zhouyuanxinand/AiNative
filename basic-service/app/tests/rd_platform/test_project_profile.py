"""Manually supplied project context is durable and isolated from case facts."""
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.platform_auth import AuthSettings
from src.controller.rd_controller import router
from src.service.rd_platform import catalog
from src.service.rd_platform.store import RdError, Store


PROFILE = {"brief": "验证低温环境下连接器的适用性", "customer_name": "客户提供的名称", "product_name": "连接器型号甲"}


def new_store(tmp_path):
    return Store(tmp_path / "rd.sqlite3", tmp_path / "assets")


def new_client(tmp_path):
    app = FastAPI()
    app.state.config = SimpleNamespace(max_upload_bytes=1024, logs_dir=tmp_path / "logs")
    app.state.auth_settings = AuthSettings(enabled=False)
    app.state.rd_store = new_store(tmp_path)
    app.include_router(router)
    return TestClient(app)


def save(store, project, data, key="profile", actor="owner"):
    return store.command(actor, project["id"], project["version"], key, "save_project_profile", data)


def test_profile_create_survives_restart_and_same_intent_replay(tmp_path):
    store = new_store(tmp_path)
    first = store.create_project("owner", "研发项目", key="create", **PROFILE)
    restarted = new_store(tmp_path)
    assert {key: first[key] for key in PROFILE} == PROFILE
    assert restarted.get_project("owner", first["id"]) == first
    assert restarted.list_projects("owner") == [first]
    assert restarted.create_project("owner", "研发项目", key="create", **PROFILE) == first
    with pytest.raises(RdError) as error:
        restarted.create_project("owner", "研发项目", key="create", **{**PROFILE, "brief": "另一个研发目标"})
    assert error.value.status == 409


def test_old_project_defaults_are_empty_without_inventing_case_facts(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project("owner", "原有项目")
    with sqlite3.connect(store.path) as db:
        original = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        for key in PROFILE:
            original.pop(key, None)
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(original), project["id"]))
    restarted = new_store(tmp_path)
    restored = restarted.get_project("owner", project["id"])
    assert {key: restored[key] for key in PROFILE} == {"brief": "", "customer_name": "", "product_name": ""}
    assert restored["version"] == 1 and restored["cases"] == []
    assert restarted.list_projects("owner") == [restored]


def test_legacy_create_receipt_still_replays_after_profile_upgrade(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project("owner", "原有项目")
    legacy_response = {key: value for key, value in project.items() if key not in PROFILE}
    intent = {"command": "create_project", "title": "原有项目", "context": {}}
    encoded_intent = json.dumps(intent, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(encoded_intent.encode()).hexdigest()
    with sqlite3.connect(store.path) as db:
        db.execute("INSERT INTO receipts VALUES(?,?,?,?,?)",
                   ("owner", "__project_create__", "legacy-create", fingerprint, json.dumps(legacy_response)))
    replay = new_store(tmp_path).create_project("owner", "原有项目", key="legacy-create")
    assert replay == project
    assert len(store.list_projects("owner")) == 1


def test_profile_command_is_project_scoped_and_invalidates_current_case_context(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project("owner", "原项目名称")
    project = store.command("owner", project["id"], project["version"], "case", "create_case",
                            {"scenario_id": "taskbook", "title": "研制任务书"})
    before_cases = project["cases"]
    changed = save(store, project, {"title": "新项目名称", **PROFILE})
    assert changed["title"] == "新项目名称"
    assert {key: changed[key] for key in PROFILE} == PROFILE
    assert changed["cases"][0]["requirements"] == before_cases[0]["requirements"]
    assert changed["cases"][0]["input_revision"] == before_cases[0]["input_revision"] + 1
    assert changed["cases"][0]["business_context"]["customer_name"] == PROFILE["customer_name"]
    assert changed["version"] == project["version"] + 1
    event = changed["events"][-1]
    assert event["type"] == "save_project_profile" and event["actor"] == "owner"
    assert "case_id" not in event["data"]
    assert new_store(tmp_path).get_project("owner", project["id"]) == changed
    cleared = save(store, changed, {"customer_name": ""}, key="clear")
    assert cleared["customer_name"] == ""
    assert cleared["product_name"] == PROFILE["product_name"] and cleared["brief"] == PROFILE["brief"]


def test_profile_replay_and_compare_and_swap_do_not_duplicate_changes(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project("owner", "研发项目")
    first = save(store, project, PROFILE)
    assert save(store, project, PROFILE) == first
    with pytest.raises(RdError) as changed_intent:
        save(store, project, {"brief": "另一个目标"})
    assert changed_intent.value.status == 409
    with pytest.raises(RdError) as stale:
        save(store, project, PROFILE, key="stale")
    assert stale.value.status == 409
    assert store.get_project("owner", project["id"]) == first


def test_profile_concurrent_writers_preserve_only_one_cas_update(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project("owner", "研发项目")
    def write(index):
        try:
            return save(new_store(tmp_path), project, {"brief": f"目标{index}"}, key=f"profile-{index}")["version"]
        except RdError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, (1, 2))) == [2, 409]
    updated = store.get_project("owner", project["id"])
    assert updated["brief"] in {"目标1", "目标2"}
    assert len(updated["events"]) == 2


@pytest.mark.parametrize("payload", [{"brief": None}, {"customer_name": 123}, {"product_name": "x" * 201},
                                     {"brief": "x" * 4001}, {"title": "  "}, {"owner_id": "outsider"},
                                     {"case_id": "some-case", "brief": "目标"}, {}])
def test_profile_command_rejects_invalid_or_non_profile_fields_without_writing(tmp_path, payload):
    store = new_store(tmp_path)
    project = store.create_project("owner", "研发项目")
    with pytest.raises(RdError) as error:
        save(store, project, payload)
    assert error.value.status == 422
    assert store.get_project("owner", project["id"]) == project


def test_profile_command_cannot_be_used_by_another_owner(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project("owner", "研发项目")
    with pytest.raises(RdError) as error:
        save(store, project, PROFILE, actor="outsider")
    assert error.value.status == 404
    assert store.get_project("owner", project["id"]) == project


def test_case_creation_uses_published_registry_and_preserves_initial_context(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project = store.create_project("owner", "研发项目", {"product_series": "CY"})
    registry = store.catalog()["scenarios"]
    assert len(registry) == 1 and registry[0]["id"] == "taskbook"
    assert registry[0]["initial_stage"] == "input" and "product_series" in registry[0]["context_fields"]
    intent = {"scenario_id": registry[0]["id"], "title": "首个应用案例"}
    with monkeypatch.context() as changes:
        changes.setattr(catalog, "SCENARIOS", [{**registry[0], "status": "draft"}])
        with pytest.raises(RdError) as unpublished:
            store.command("owner", project["id"], project["version"], "case", "create_case", intent)
        assert unpublished.value.status == 422
    created = store.command("owner", project["id"], project["version"], "case", "create_case", intent)
    assert created["cases"][0]["stage"] == "input"
    assert created["cases"][0]["context"] == {"product_series": "CY"}
    with pytest.raises(RdError) as unknown:
        store.command("owner", created["id"], created["version"], "unregistered", "create_case",
                      {"scenario_id": "arbitrary-unregistered", "title": "不能凭空创建场景"})
    assert unknown.value.status == 422


def test_project_profile_http_create_edit_replay_and_access(tmp_path):
    client = new_client(tmp_path)
    created = client.post("/api/rd/projects", headers={"Idempotency-Key": "create"},
                          json={"title": "研发项目", **PROFILE})
    assert created.status_code == 200, created.text
    project = created.json()
    assert {key: project[key] for key in PROFILE} == PROFILE
    url = f"/api/rd/projects/{project['id']}/commands"
    intent = {"expected_version": project["version"], "command": "save_project_profile",
              "data": {"brief": "修订后的研发目标", "product_name": "连接器型号乙"}}
    assert client.post(url, json=intent).status_code == 400
    headers = {"Idempotency-Key": "profile"}
    changed = client.post(url, json=intent, headers=headers)
    assert changed.status_code == 200, changed.text
    assert changed.json()["brief"] == "修订后的研发目标"
    assert client.post(url, json=intent, headers=headers).json() == changed.json()
    assert client.post(url, json=intent, headers={"Idempotency-Key": "stale"}).status_code == 409
    assert new_client(tmp_path).post(url, json=intent, headers=headers).status_code == 404
    assert client.get(f"/api/rd/projects/{project['id']}").json() == changed.json()


def test_profile_create_rejects_wrong_types_and_unbounded_fields_at_http_boundary(tmp_path):
    client = new_client(tmp_path)
    for data in ({"brief": None}, {"brief": 1}, {"customer_name": "x" * 201}, {"product_name": "x" * 201},
                 {"brief": "x" * 4001}, {"customer_id": "not-connected"}):
        assert client.post("/api/rd/projects", json={"title": "研发项目", **data}).status_code == 422
    assert client.get("/api/rd/projects").json()["projects"] == []


def test_profile_edit_invalidates_binding_but_keeps_running_snapshot_immutable(tmp_path):
    from test_store import taskbook, issue
    store = new_store(tmp_path)
    project = taskbook(store)
    cid = project["cases"][0]["id"]
    wid = project["cases"][0]["workpackages"][0]["id"]
    project = issue(store, project, "submit_workpackage", {"workpackage_id": wid})
    old = project["cases"][0]["workpackages"][0]["snapshot"]
    assert old["business_context"]["title"] == project["title"]
    project = store.command("owner", project["id"], project["version"], "change-business", "save_project_profile", {"customer_name": "新客户"})
    case = project["cases"][0]
    assert case["taskbook_binding"]["status"] == "stale"
    assert case["workpackages"][0]["snapshot"] == old
    assert case["business_context"]["customer_name"] == "新客户"
    assert not store._same_inputs(old, case)
