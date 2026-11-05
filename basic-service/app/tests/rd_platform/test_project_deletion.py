"""Project deletion hides ordinary access while retaining assets and audit facts."""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_http import make_client
from test_project_workflow_templates import start
from test_store import case_project, issue, new_store


def stored_project(store, pid):
    with store._connection() as db:
        return json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (pid,)).fetchone()[0])


def replace_project(store, project):
    with store._transaction() as db:
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(project), project["id"]))


def delete(store, project, key="delete", actor="owner"):
    return store.delete_project(actor, project["id"], project["version"], key)


def assert_rd_error(status, operation):
    with pytest.raises(Exception) as error:
        operation()
    assert error.value.status == status


def test_delete_retains_project_audit_sources_and_artifacts_across_restart(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    cid = project["cases"][0]["id"]
    project = store.add_source("owner", project["id"], cid, project["version"], "source", "tech", "依据.txt", b"source")
    project = issue(store, project, "pull_workpackage", {"definition_id": "input_check"})
    source = project["cases"][0]["sources"][0]
    source_path = store.source_path("owner", project["id"], cid, source["id"])
    artifact_path = store.asset_root / "retained-artifact.docx"
    artifact_path.write_bytes(b"artifact")
    payload = stored_project(store, project["id"])
    package = payload["cases"][0]["workpackages"][0]
    package["artifacts"] = [{"id": "document", "name": artifact_path.name, "path": str(artifact_path),
                             "sha256": hashlib.sha256(b"artifact").hexdigest()}]
    replace_project(store, payload)
    assert store.artifact_path("owner", project["id"], cid, package["id"], "document") == artifact_path
    before = stored_project(store, project["id"])

    result = delete(store, project)
    assert result == {"ok": True, "project_id": project["id"], "version": project["version"] + 1,
                      "deleted_at": result["deleted_at"]}
    assert result["deleted_at"]
    restarted = new_store(tmp_path)
    assert restarted.list_projects("owner") == []
    assert_rd_error(404, lambda: restarted.get_project("owner", project["id"]))
    assert_rd_error(404, lambda: restarted.source_path("owner", project["id"], cid, source["id"]))
    assert_rd_error(404, lambda: restarted.artifact_path("owner", project["id"], cid, package["id"], "document"))
    retained = stored_project(restarted, project["id"])
    assert retained["cases"] == before["cases"]
    assert retained["events"][:-1] == before["events"]
    assert retained["deleted_by"] == "owner" and retained["deleted_at"] == result["deleted_at"]
    assert retained["events"][-1]["type"] == "project_deleted"
    assert retained["events"][-1]["actor"] == "owner"
    assert retained["version"] == result["version"]
    assert source_path.read_bytes() == b"source" and artifact_path.read_bytes() == b"artifact"


def test_delete_is_owner_only_and_rechecks_permissions_on_retry(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project("owner", "共享项目")
    payload = stored_project(store, project["id"])
    payload["members"] = ["member"]
    replace_project(store, payload)
    assert store.get_project("owner", project["id"])["can_delete"] is True
    member = store.get_project("member", project["id"])
    assert member["can_delete"] is False and member["delete_blocked_reason"]
    assert_rd_error(403, lambda: delete(store, project, actor="member"))
    assert_rd_error(404, lambda: delete(store, project, actor="outsider"))
    result = delete(store, project)
    assert delete(new_store(tmp_path), project) == result
    assert_rd_error(403, lambda: delete(store, project, actor="member"))
    assert_rd_error(404, lambda: delete(store, project, actor="outsider"))


def test_delete_cas_and_idempotency_never_resurrect_ordinary_receipts(tmp_path):
    store = new_store(tmp_path)
    first = store.create_project("owner", "重试项目", key="create")
    project = issue(store, first, "create_case", {"scenario_id": "taskbook", "title": "案例"}, key="case")
    assert_rd_error(409, lambda: delete(store, first))
    assert store.get_project("owner", project["id"])["version"] == project["version"]
    result = delete(store, project)
    assert delete(store, project) == result
    assert_rd_error(409, lambda: store.delete_project("owner", project["id"], project["version"] + 1, "delete"))
    assert_rd_error(404, lambda: delete(store, project, key="another-delete"))
    assert_rd_error(404, lambda: store.create_project("owner", "重试项目", key="create"))
    assert_rd_error(404, lambda: issue(store, first, "create_case", {"scenario_id": "taskbook", "title": "案例"}, key="case"))
    assert_rd_error(404, lambda: issue(store, project, "save_project_profile", {"title": "不能复活"}))
    assert store.list_projects("owner") == []


@pytest.mark.parametrize("scope,status", [("package", "submitted"), ("package", "running"),
                                          ("run", "submitted"), ("run", "running"), ("lease", "completed")])
def test_active_execution_blocks_delete_and_refreshes_create_receipt_flags(tmp_path, scope, status):
    store = new_store(tmp_path)
    first = store.create_project("owner", "执行项目", key="create")
    project = issue(store, first, "create_case", {"scenario_id": "taskbook", "title": "案例"}, key="case")
    project = issue(store, project, "pull_workpackage", {"definition_id": "input_check"})
    payload = stored_project(store, project["id"])
    cid = payload["cases"][0]["id"]
    package = payload["cases"][0]["workpackages"][0]
    package["run_id"] = "retained-run"
    package["status"] = status if scope == "package" else "completed"
    replace_project(store, payload)
    if scope != "package":
        with store._transaction() as db:
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                       ("retained-run", project["id"], cid, package["id"], status, time.time(), "{}"))
            if scope == "lease":
                db.execute("INSERT INTO claims VALUES(?,?,?,?)", ("retained-run", "node", "token", time.time() + 300))

    current = store.get_project("owner", project["id"])
    assert current["can_delete"] is True and current["delete_blocked_reason"]
    assert store.list_projects("owner")[0]["delete_blocked_reason"] == current["delete_blocked_reason"]
    replay = store.create_project("owner", "执行项目", key="create")
    assert replay["version"] == first["version"]
    assert replay["can_delete"] is True and replay["delete_blocked_reason"] == current["delete_blocked_reason"]
    command_replay = issue(store, first, "create_case", {"scenario_id": "taskbook", "title": "案例"}, key="case")
    assert command_replay["delete_blocked_reason"] == current["delete_blocked_reason"]
    before = stored_project(store, project["id"])
    assert_rd_error(409, lambda: delete(store, current))
    assert stored_project(store, project["id"]) == before
    if scope != "package":
        with store._connection() as db:
            assert db.execute("SELECT status FROM runs WHERE id='retained-run'").fetchone()[0] == status


def test_expired_terminal_lease_and_unrelated_jobs_do_not_block_delete(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project("owner", "可删除项目")
    other = store.create_project("owner", "其他执行项目")
    with store._transaction() as db:
        for pid, status, lease in ((project["id"], "completed", time.time() - 1),
                                   (other["id"], "running", time.time() + 300)):
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (pid, pid, "case", pid, status, time.time(), "{}"))
            db.execute("INSERT INTO claims VALUES(?,?,?,?)", (pid, "node", "token", lease))
    assert store.get_project("owner", project["id"])["delete_blocked_reason"] == ""
    delete(store, project)
    assert [item["id"] for item in store.list_projects("owner")] == [other["id"]]
    with store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 2


def test_concurrent_delete_retries_record_one_event_and_version(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project("owner", "并发删除")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: delete(new_store(tmp_path), project), range(2)))
    assert results[0] == results[1]
    payload = stored_project(store, project["id"])
    assert payload["version"] == project["version"] + 1
    assert len([event for event in payload["events"] if event["type"] == "project_deleted"]) == 1


def test_delete_and_concurrent_update_cannot_overwrite_each_other(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project("owner", "并发更新")
    def mutate(operation):
        try:
            if operation == "delete":
                return delete(new_store(tmp_path), project)
            return issue(new_store(tmp_path), project, "save_project_profile", {"title": "新名称"})
        except Exception as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(mutate, ("delete", "update")))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert next(result for result in results if isinstance(result, int)) in {404, 409}
    assert stored_project(store, project["id"])["version"] == project["version"] + 1


def test_deleted_projects_disappear_from_workflow_template_usage_history(tmp_path):
    store = new_store(tmp_path)
    project = start(store)
    assert store.workflow_templates.history("owner", "taskbook-generation")["usages"]
    delete(store, project)
    assert store.workflow_templates.history("owner", "taskbook-generation")["usages"] == []
    assert stored_project(store, project["id"])["cases"][0]["workflow_template_adoptions"]


def test_http_delete_requires_version_key_owner_and_same_origin(tmp_path):
    client = make_client(tmp_path)
    project = client.post("/api/rd/projects", json={"title": "HTTP删除"}).json()
    assert project["can_delete"] is True and project["delete_blocked_reason"] == ""
    url = f"/api/rd/projects/{project['id']}"
    assert client.delete(url, params={"expected_version": 1}).status_code == 400
    assert client.delete(url, headers={"Idempotency-Key": "delete"}).status_code == 422
    assert client.delete(url, params={"expected_version": 0}, headers={"Idempotency-Key": "delete"}).status_code == 422
    assert client.delete(url, params={"expected_version": 1},
                         headers={"Idempotency-Key": "delete", "Sec-Fetch-Site": "cross-site"}).status_code == 403
    stranger = make_client(tmp_path)
    assert stranger.delete(url, params={"expected_version": 1}, headers={"Idempotency-Key": "delete"}).status_code == 404
    result = client.delete(url, params={"expected_version": 1}, headers={"Idempotency-Key": "delete"})
    assert result.status_code == 200, result.text
    assert result.json()["ok"] is True
    assert client.delete(url, params={"expected_version": 1}, headers={"Idempotency-Key": "delete"}).json() == result.json()
    assert client.get(url).status_code == 404
    assert client.get("/api/rd/projects").json()["projects"] == []


def test_http_deleted_project_blocks_sources_assistant_and_previous_requests(tmp_path):
    client = make_client(tmp_path)
    first = client.post("/api/rd/projects", json={"title": "含资料项目"}, headers={"Idempotency-Key": "create"}).json()
    url = f"/api/rd/projects/{first['id']}"
    case_payload = {"expected_version": first["version"], "command": "create_case",
                    "data": {"scenario_id": "taskbook", "title": "案例"}}
    project = client.post(url + "/commands", json=case_payload, headers={"Idempotency-Key": "case"}).json()
    cid = project["cases"][0]["id"]
    case_url = f"{url}/cases/{cid}"
    project = client.post(case_url + "/sources", data={"expected_version": project["version"], "role": "tech"},
                          files={"file": ("依据.txt", b"source")}, headers={"Idempotency-Key": "upload"}).json()
    source_url = case_url + "/sources/" + project["cases"][0]["sources"][0]["id"]
    question = {"message": "当前该做什么"}
    assert client.post(case_url + "/assistant", json=question, headers={"Idempotency-Key": "ask"}).status_code == 200
    assert client.get(source_url).status_code == 200
    assert client.delete(url, params={"expected_version": project["version"]}, headers={"Idempotency-Key": "delete"}).status_code == 200
    assert client.get(source_url).status_code == 404
    assert client.get(case_url + "/assistant").status_code == 404
    assert client.post(case_url + "/assistant", json=question, headers={"Idempotency-Key": "ask"}).status_code == 404
    assert client.post(url + "/commands", json=case_payload, headers={"Idempotency-Key": "case"}).status_code == 404
    assert client.post("/api/rd/projects", json={"title": "含资料项目"}, headers={"Idempotency-Key": "create"}).status_code == 404
