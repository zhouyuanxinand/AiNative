"""Confirmation freezes adopted requirements and does not perform engineering approval."""
import json

import pytest

from test_lifecycle_policy import v2_project
from test_store import issue, new_store
from test_http import make_client, create


def requirements_project(store, context=None):
    project = v2_project(store)
    if context:
        project = issue(store, project, "save_context", {"context": context})
    cid = project["cases"][0]["id"]
    for role in ("tech", "spec"):
        project = store.add_source("owner", project["id"], cid, project["version"], "source-" + role, role, role + ".txt", b"source evidence")
    sid = project["cases"][0]["sources"][0]["id"]
    return issue(store, project, "save_requirement", {"title": "压力", "content": "0.3 MPa", "source_ids": [sid]})


def confirm(store, project):
    case = project["cases"][0]
    return issue(store, project, "confirm_requirements", {"expected_input_revision": case["input_revision"], "scope": "当前液冷需求", "source_ids": [case["sources"][0]["id"]]})


def clarify_requirement(store, project, index=0, content=None):
    """Explicitly perform both clarification steps when a fixture needs adopted values."""
    row = project["cases"][0]["requirements"][index]
    content = row["content"] if content is None else content
    project = issue(store, project, "open_clarification", {"requirement_id": row["id"],
        "source_ids": row["source_ids"], "question": "请根据来源确认当前指标及适用工况"})
    cid = project["cases"][0]["clarifications"][-1]["id"]
    project = issue(store, project, "answer_clarification", {"clarification_id": cid,
        "source_ids": row["source_ids"], "answer": content})
    return issue(store, project, "adopt_clarification", {"clarification_id": cid, "requirement_content": content})


def test_confirmation_fixes_adopted_requirement_and_enters_selection_without_approval(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    project = clarify_requirement(store, project)
    confirmed = confirm(store, project)
    case = confirmed["cases"][0]
    baseline = case["requirement_baselines"][0]
    assert case["stage"] == "selection"
    assert case["decisions"] == [] and case["workpackages"] == []
    assert baseline["items"][0]["content"] == "0.3 MPa"
    assert baseline["source_refs"][0]["sha256"] == case["sources"][0]["sha256"]
    assert baseline["actor"] == "owner" and baseline["digest"]
    assert case["business_lifecycle"]["current_requirement_baseline_id"] == baseline["id"]
    changed = issue(store, confirmed, "save_requirement", {"id": case["requirements"][0]["id"], "title": "压力", "content": "0.4 MPa", "source_ids": [case["sources"][0]["id"]]})
    assert changed["cases"][0]["requirement_baselines"][0]["items"][0]["content"] == "0.3 MPa"
    assert changed["cases"][0]["requirement_baselines"][0]["invalidated_reason"]
    assert changed["cases"][0]["stage"] == "input"


def test_stale_input_and_open_clarification_cannot_confirm(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    case = project["cases"][0]
    with pytest.raises(Exception) as error:
        issue(store, project, "confirm_requirements", {"expected_input_revision": case["input_revision"] - 1, "scope": "旧版", "source_ids": [case["sources"][0]["id"]]})
    assert error.value.status == 409
    project = issue(store, project, "open_clarification", {"requirement_id": case["requirements"][0]["id"], "question": "核对工况", "source_ids": [case["sources"][0]["id"]]})
    with pytest.raises(Exception) as error:
        confirm(store, project)
    assert error.value.status == 422
    assert store.get_project("owner", project["id"])["cases"][0]["requirement_baselines"] == []


def test_empty_requirements_cannot_be_confirmed(tmp_path):
    store = new_store(tmp_path)
    project = v2_project(store)
    with pytest.raises(Exception) as error:
        issue(store, project, "confirm_requirements", {"expected_input_revision": 1, "scope": "空", "source_ids": []})
    assert error.value.status == 422


@pytest.mark.parametrize("stage", ["input", "requirements", "selection", "planning", "design"])
def test_http_legacy_advance_cannot_bypass_v2_gates(tmp_path, stage):
    client = make_client(tmp_path)
    project = create(client)
    endpoint = f"/api/rd/projects/{project['id']}/commands"
    project = client.post(endpoint, json={"expected_version": project["version"], "command": "create_case", "data": {"scenario_id": "taskbook", "title": "新流程"}}, headers={"Idempotency-Key": "case"}).json()
    case = project["cases"][0]
    # Put each gate under test in its current stage; the legacy rejection path
    # needs no evidence and used to append a decision for every stage.
    with client.app.state.rd_store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        raw["cases"][0]["stage"] = stage
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    response = client.post(endpoint, json={"expected_version": project["version"], "command": "advance_stage", "data": {"case_id": case["id"], "stage": stage, "verdict": "rejected", "rationale": "旧命令不应办理新版决定", "source_ids": []}}, headers={"Idempotency-Key": "bypass"})
    assert response.status_code == 422
    assert client.get(f"/api/rd/projects/{project['id']}").json()["cases"][0]["decisions"] == []


def test_bulk_analysis_adoption_preserves_explicitly_rejected_candidates(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    case = project["cases"][0]
    sid = case["sources"][0]["id"]
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        raw["cases"][0]["source_analysis"] = {"id": "proposal", "status": "proposed", "input_revision": case["input_revision"],
            "source_hashes": {source["id"]: source["sha256"] for source in case["sources"]}, "context": {},
            "requirements": [{"title": "已拒绝候选", "content": "不得批量恢复", "source_ids": [sid], "evidence": [], "status": "rejected"}]}
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    adopted = issue(store, project, "adopt_source_analysis", {"analysis_id": "proposal"})
    assert [row["title"] for row in adopted["cases"][0]["requirements"]] == ["压力"]
    assert adopted["cases"][0]["source_analysis"]["requirements"][0]["status"] == "rejected"
