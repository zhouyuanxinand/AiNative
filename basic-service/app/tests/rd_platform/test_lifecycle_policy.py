"""New cases cannot choose legacy gates; historical reads invent no approvals."""
import json

import pytest

from test_store import issue, new_store


def v2_project(store):
    project = store.create_project("owner", "液冷研发")
    return issue(store, project, "create_case", {"scenario_id": "taskbook", "title": "首场景"})


def test_new_case_gets_selection_identity_without_rd_authorization(tmp_path):
    store = new_store(tmp_path)
    project = v2_project(store)
    lifecycle = project["cases"][0]["business_lifecycle"]
    assert lifecycle["policy_version"] == "v2"
    assert lifecycle["selection_order_id"]
    assert lifecycle["rd_project_code"] is None
    assert lifecycle["rd_activation_state"] == "not_started"
    assert lifecycle["can_confirm_requirements"] is True
    assert lifecycle["can_record_decision"] is False
    assert project["cases"][0]["decisions"] == []
    assert store.get_project("owner", project["id"]) == project


def test_legacy_read_preserves_database_bytes_and_unknown_authorization(tmp_path):
    store = new_store(tmp_path)
    project = v2_project(store)
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        case = raw["cases"][0]
        case.pop("business_lifecycle", None)
        case["stage"] = "design"
        case["decisions"] = [{"id": "old-stage", "kind": "stage", "stage": "planning", "verdict": "approved"}]
        original = json.dumps(raw, ensure_ascii=False)
        db.execute("UPDATE projects SET payload=? WHERE id=?", (original, project["id"]))
    for project_read in (store.get_project("owner", project["id"]), store.list_projects("owner")[0]):
        loaded = project_read["cases"][0]
        assert loaded["business_lifecycle"]["policy_version"] == "legacy_v1"
        assert loaded["business_lifecycle"]["rd_activation_state"] == "historical_unverified"
        assert loaded["business_lifecycle"]["rd_project_code"] is None
        assert loaded["decisions"] == case["decisions"]
    with store._connection() as db:
        assert db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0] == original


@pytest.mark.parametrize("extra", [{"policy_version": "legacy_v1"}, {"business_lifecycle": {"policy_version": "legacy_v1"}}])
def test_client_cannot_create_legacy_policy_case(tmp_path, extra):
    store = new_store(tmp_path)
    project = store.create_project("owner", "项目")
    with pytest.raises(Exception) as error:
        issue(store, project, "create_case", {"scenario_id": "taskbook", "title": "禁止降级", **extra})
    assert error.value.status == 422
    assert store.get_project("owner", project["id"])["cases"] == []


def test_case_creation_replay_keeps_same_selection_order(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project("owner", "项目")
    data = {"scenario_id": "taskbook", "title": "首场景"}
    first = issue(store, project, "create_case", data, key="same-intent")
    assert issue(store, project, "create_case", data, key="same-intent") == first
    with pytest.raises(Exception) as error:
        issue(store, project, "create_case", {**data, "title": "其他"}, key="same-intent")
    assert error.value.status == 409
