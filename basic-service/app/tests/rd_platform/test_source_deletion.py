"""Deleting a source removes live input while retaining authorized audit evidence."""
from copy import deepcopy
from contextlib import nullcontext
import json
import time

import pytest

from service.rd_platform import analysis, assistant, migration
from service.rd_platform.store import RdError
from test_http import make_client
from test_store import case_project, issue, new_store


def stored_project(store, pid):
    with store._connection() as db:
        return json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (pid,)).fetchone()[0])


def replace_project(store, project):
    with store._transaction() as db:
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(project), project["id"]))


def upload(store, project, role="tech", content=b"source", key=None):
    return store.add_source("owner", project["id"], project["cases"][0]["id"], project["version"],
                            key or "upload-" + str(project["version"]), role, role + ".txt", content)


def delete(store, project, sid, *, key="delete-source", actor="owner", case_id=None, extra=None):
    return store.command(actor, project["id"], project["version"], key, "delete_source",
                         {"case_id": case_id or project["cases"][0]["id"], "source_id": sid, **(extra or {})})


@pytest.mark.parametrize("role", ["tech", "spec"])
def test_delete_current_source_keeps_remaining_history_unselected_and_preserves_file(tmp_path, role):
    store = new_store(tmp_path)
    project = upload(store, case_project(store), role, b"old")
    old = project["cases"][0]["sources"][0]
    project = upload(store, project, role, b"current")
    case = project["cases"][0]
    current, revision = case["sources"][-1], case["input_revision"]
    original_path = store.source_path("owner", project["id"], case["id"], current["id"])

    result = delete(store, project, current["id"])
    case = result["cases"][0]
    assert [source["id"] for source in case["sources"]] == [old["id"]]
    assert case["source_selection"][role] == ""
    assert store._active_sources(case) == []
    assert case["input_revision"] == revision + 1
    assert case["stage"] == "input"
    removed = case["deleted_sources"][0]
    assert removed["id"] == current["id"] and removed["deleted_by"] == "owner"
    assert removed["deleted_at"] and "path" not in removed
    assert store.source_path("owner", project["id"], case["id"], current["id"]) == original_path
    assert original_path.read_bytes() == b"current"
    assert result["events"][-1]["type"] == "delete_source"
    assert result["events"][-1]["data"]["source_id"] == current["id"]
    assert new_store(tmp_path).get_project("owner", project["id"]) == result
    assert assistant._facts(result, case)["active_sources"] == []
    reuploaded = upload(store, result, role, b"next version")
    assert reuploaded["cases"][0]["sources"][-1]["version"] == 3


def test_active_deletion_invalidates_analysis_binding_decisions_and_parameter_evidence(tmp_path):
    store = new_store(tmp_path)
    project = upload(store, case_project(store))
    payload = stored_project(store, project["id"])
    case = payload["cases"][0]
    source = case["sources"][0]
    case.update(stage="planning", context={"cover_phase": "S"},
                context_provenance={"cover_phase": {"kind": "source_analysis", "source_refs": [
                    {"source_id": source["id"], "version": source["version"], "sha256": source["sha256"]}]}},
                source_analysis={"id": "proposal", "status": "adopted", "context": {}, "input_revision": case["input_revision"]},
                taskbook_binding={"id": "binding", "status": "current", "input_revision": case["input_revision"]},
                product_route={"value": "new"}, composition_route={"value": "direct"},
                decisions=[{"id": "approval", "kind": "stage", "verdict": "approved"}])
    replace_project(store, payload)

    result = delete(store, project, source["id"])
    case = result["cases"][0]
    assert case["source_analysis"]["status"] == "stale"
    assert case["taskbook_binding"]["status"] == "stale"
    assert case["decisions"][0]["invalidated_at"]
    assert case["product_route"] is None and case["composition_route"] is None
    assert case["context"]["cover_phase"] == "S"
    assert analysis.parameter_facts(case)["cover_phase"]["evidence_status"] == "stale"
    with pytest.raises(RdError) as error:
        store.analyze_sources("owner", result["id"], case["id"], result["version"], "no-current-input")
    assert error.value.status == 422
    with pytest.raises(RdError) as error:
        issue(store, result, "save_requirement", {"title": "不得重新引用", "content": "旧文件", "source_ids": [source["id"]]})
    assert error.value.status == 422


def test_delete_reference_invalidates_current_input_but_keeps_formal_selection(tmp_path):
    store = new_store(tmp_path)
    project = upload(store, upload(store, case_project(store)), "reference")
    before = project["cases"][0]
    reference = before["sources"][-1]
    result = delete(store, project, reference["id"])
    case = result["cases"][0]
    assert case["input_revision"] == before["input_revision"] + 1
    assert case["source_selection"] == before["source_selection"]
    assert [source["role"] for source in store._active_sources(case)] == ["tech"]


def test_delete_historical_source_preserves_current_analysis_and_fixed_snapshot(tmp_path):
    store = new_store(tmp_path)
    project = upload(store, case_project(store), content=b"old")
    old = project["cases"][0]["sources"][0]
    project = upload(store, project, content=b"current")
    payload = stored_project(store, project["id"])
    case = payload["cases"][0]
    case["source_analysis"] = {"id": "proposal", "status": "proposed", "context": {}, "input_revision": case["input_revision"]}
    snapshot = {"input_revision": case["input_revision"] - 1, "sources": [deepcopy(old)]}
    case["workpackages"] = [{"id": "historical-package", "definition_id": "input_check", "stage": "input", "status": "completed",
                             "nodes": [], "artifacts": [], "obligations": [], "blocked_reasons": [], "snapshot": snapshot}]
    replace_project(store, payload)
    before = store.get_project("owner", project["id"])["cases"][0]

    result = delete(store, project, old["id"])
    case = result["cases"][0]
    assert case["input_revision"] == before["input_revision"]
    assert case["source_analysis"] == before["source_analysis"]
    assert case["source_selection"] == before["source_selection"]
    assert case["workpackages"][0]["snapshot"] == before["workpackages"][0]["snapshot"]
    assert [source["id"] for source in store._active_sources(case)] == [before["source_selection"]["tech"]]
    assert store.source_path("owner", project["id"], case["id"], old["id"]).read_bytes() == b"old"
    with pytest.raises(RdError):
        issue(store, result, "select_source", {"role": "tech", "source_id": old["id"]})


def test_delete_replays_same_key_before_cas_without_duplicate_events(tmp_path):
    store = new_store(tmp_path)
    project = upload(store, case_project(store))
    sid = project["cases"][0]["sources"][0]["id"]
    result = delete(store, project, sid)
    assert delete(new_store(tmp_path), project, sid) == result
    retained = stored_project(store, project["id"])
    assert len([event for event in retained["events"] if event["type"] == "delete_source"]) == 1
    assert retained["version"] == project["version"] + 1
    with pytest.raises(RdError) as error:
        delete(store, result, sid, key="new-delete")
    assert error.value.status == 404


def test_old_upload_and_delete_receipts_cannot_restore_deleted_source_cards(tmp_path):
    store = new_store(tmp_path)
    empty = case_project(store)
    project = upload(store, empty, key="original-upload")
    source = project["cases"][0]["sources"][0]
    with_reference = upload(store, project, "reference")
    deleted = delete(store, with_reference, source["id"])
    replay = upload(store, empty, key="original-upload")
    assert replay["version"] == project["version"]
    assert replay["cases"][0]["sources"] == []
    assert replay["cases"][0]["source_selection"]["tech"] == ""
    assert replay["cases"][0]["deleted_sources"][0]["id"] == source["id"]
    assert store.get_project("owner", project["id"]) == deleted
    reference = deleted["cases"][0]["sources"][0]
    latest = delete(store, deleted, reference["id"], key="delete-reference")
    replay = delete(store, with_reference, source["id"])
    assert replay["version"] == deleted["version"]
    assert replay["cases"][0]["sources"] == []
    assert store.get_project("owner", project["id"]) == latest


def test_project_member_keeps_existing_source_edit_permission(tmp_path):
    store = new_store(tmp_path)
    project = upload(store, case_project(store))
    payload = stored_project(store, project["id"])
    payload["members"] = ["member"]
    replace_project(store, payload)
    result = delete(store, project, project["cases"][0]["sources"][0]["id"], actor="member")
    assert result["cases"][0]["sources"] == []
    assert result["cases"][0]["deleted_sources"][0]["deleted_by"] == "member"


@pytest.mark.parametrize("extra", [{"role": "spec"}, {"name": "forged"}, {"deleted_by": "other"}, {"path": "outside"}])
def test_delete_accepts_only_server_resolved_source_identity(tmp_path, extra):
    store = new_store(tmp_path)
    project = upload(store, case_project(store))
    before = stored_project(store, project["id"])
    with pytest.raises(RdError) as error:
        delete(store, project, project["cases"][0]["sources"][0]["id"], extra=extra)
    assert error.value.status == 422
    assert stored_project(store, project["id"]) == before


def test_missing_cross_case_and_unauthorized_sources_cannot_be_deleted(tmp_path):
    store = new_store(tmp_path)
    project = upload(store, case_project(store))
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "create_case", {"scenario_id": "taskbook", "title": "另一案例"})
    for selected_id, cid, actor in (("missing", project["cases"][0]["id"], "owner"),
                                     (sid, project["cases"][1]["id"], "owner"),
                                     (sid, project["cases"][0]["id"], "stranger")):
        with pytest.raises(RdError) as error:
            delete(store, project, selected_id, case_id=cid, actor=actor)
        assert error.value.status == 404
    assert stored_project(store, project["id"])["cases"][0]["sources"][0]["id"] == sid


def test_stale_project_version_cannot_delete_newer_sources(tmp_path):
    store = new_store(tmp_path)
    project = upload(store, case_project(store))
    newer = upload(store, project, "reference")
    with pytest.raises(RdError) as error:
        delete(store, project, project["cases"][0]["sources"][0]["id"])
    assert error.value.status == 409
    assert store.get_project("owner", newer["id"]) == newer


@pytest.mark.parametrize("kind,status", [("case", "completed"), ("package", "submitted"), ("package", "running"),
                                           ("run", "submitted"), ("run", "running"), ("lease", "completed")])
def test_completed_case_or_active_execution_blocks_source_deletion(tmp_path, kind, status):
    store = new_store(tmp_path)
    project = upload(store, case_project(store))
    payload = stored_project(store, project["id"])
    case = payload["cases"][0]
    sid = case["sources"][0]["id"]
    if kind == "case":
        case["status"] = status
    elif kind == "package":
        case["workpackages"] = [{"id": "active-package", "status": status, "nodes": []}]
    replace_project(store, payload)
    if kind in {"run", "lease"}:
        with store._transaction() as db:
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", ("active-run", project["id"], case["id"], "active-package", status, time.time(), "{}"))
            if kind == "lease":
                db.execute("INSERT INTO claims VALUES(?,?,?,?)", ("active-run", "node", "token", time.time() + 60))
    before = stored_project(store, project["id"])
    with pytest.raises(RdError) as error:
        delete(store, project, sid)
    assert error.value.status == 409
    assert stored_project(store, project["id"]) == before


def test_another_case_run_and_expired_lease_do_not_block_source_deletion(tmp_path):
    store = new_store(tmp_path)
    project = upload(store, case_project(store))
    cid = project["cases"][0]["id"]
    with store._transaction() as db:
        for run_id, case_id, status, lease in (("expired", cid, "completed", time.time() - 1), ("other", "other-case", "running", time.time() + 60)):
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (run_id, project["id"], case_id, run_id + "-package", status, time.time(), "{}"))
            db.execute("INSERT INTO claims VALUES(?,?,?,?)", (run_id, "node", "token", lease))
    result = delete(store, project, project["cases"][0]["sources"][0]["id"])
    assert result["cases"][0]["sources"] == []


def test_archived_source_http_download_stays_authorized_after_deletion(tmp_path):
    client = make_client(tmp_path)
    actor = client.get("/api/rd/session").json()["actor_id"]
    store = client.app.state.rd_store
    project = store.create_project(actor, "资料删除HTTP")
    project = store.command(actor, project["id"], project["version"], "case", "create_case", {"scenario_id": "taskbook", "title": "资料案例"})
    cid = project["cases"][0]["id"]
    project = store.add_source(actor, project["id"], cid, project["version"], "upload", "tech", "original.txt", b"original evidence")
    sid = project["cases"][0]["sources"][0]["id"]
    endpoint = "/api/rd/projects/" + project["id"]
    result = client.post(endpoint + "/commands", headers={"Idempotency-Key": "delete"}, json={
        "expected_version": project["version"], "command": "delete_source", "data": {"case_id": cid, "source_id": sid}})
    assert result.status_code == 200, result.text
    assert result.json()["cases"][0]["sources"] == []
    response = client.get(endpoint + "/cases/" + cid + "/sources/" + sid)
    assert response.status_code == 200 and response.content == b"original evidence"
    assert "original.txt" in response.headers["content-disposition"]
    stranger = make_client(tmp_path)
    assert stranger.get(endpoint + "/cases/" + cid + "/sources/" + sid).status_code == 404


def test_repeated_historical_deletion_and_upload_preserve_current_candidate_and_source_order(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    for content in (b"first", b"second", b"third"):
        project = upload(store, project, content=content)
    first, second = project["cases"][0]["sources"][:2]
    project = issue(store, project, "pull_workpackage", {"definition_id": "input_check"})
    original_wid = project["cases"][0]["workpackages"][-1]["id"]
    project = issue(store, project, "create_flow_draft", {"workpackage_id": original_wid})
    original_draft = project["cases"][0]["flow_drafts"][-1]
    project = issue(store, project, "prepare_execution_bundle", {"draft_id": original_draft["id"]})
    original_candidate = deepcopy(project["cases"][0]["execution_candidates"][-1])
    project = delete(store, project, second["id"], key="delete-second")
    project = issue(store, project, "adopt_execution_bundle", {"candidate_id": original_candidate["id"], "candidate_digest": original_candidate["digest"]})
    project = upload(store, project, content=b"fourth")
    assert project["cases"][0]["sources"][-1]["version"] == 4
    project = issue(store, project, "pull_workpackage", {"definition_id": "input_check"})
    wid = project["cases"][0]["workpackages"][-1]["id"]
    project = issue(store, project, "create_flow_draft", {"workpackage_id": wid})
    draft = project["cases"][0]["flow_drafts"][-1]
    project = issue(store, project, "prepare_execution_bundle", {"draft_id": draft["id"]})
    candidate = deepcopy(project["cases"][0]["execution_candidates"][-1])

    project = delete(store, project, first["id"], key="delete-first")
    project = issue(store, project, "adopt_execution_bundle", {"candidate_id": candidate["id"], "candidate_digest": candidate["digest"]})
    assert project["cases"][0]["execution_candidates"][-1] == candidate
    assert project["cases"][0]["execution_adoptions"][-1]["candidate_id"] == candidate["id"]


def test_deleted_reference_never_reenters_real_analysis_snapshot(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project = upload(store, upload(store, case_project(store)), "reference", b"archived reference")
    reference = project["cases"][0]["sources"][-1]
    project = delete(store, project, reference["id"])
    observed = []

    def chat_json(system, user, **kwargs):
        payload = json.loads(user)
        observed.extend(source["source_id"] for source in payload["sources"])
        assert "archived reference" not in user
        return {"context": {}, "requirements": []}

    monkeypatch.setattr(analysis.llm_client, "get_model_status", lambda *args, **kwargs: {"configured": True, "provider": "fixture", "model": "fixture"})
    monkeypatch.setattr(analysis.llm_client, "model_scope", lambda *args, **kwargs: nullcontext(None))
    monkeypatch.setattr(analysis.llm_client, "chat_json", chat_json)
    result = store.analyze_sources("owner", project["id"], project["cases"][0]["id"], project["version"], "analyze-active")
    assert observed == [project["cases"][0]["source_selection"]["tech"]]
    assert reference["id"] not in result["cases"][0]["source_analysis"]["source_hashes"]
    assert result["cases"][0]["deleted_sources"][0]["id"] == reference["id"]


def test_archived_history_and_empty_current_choice_remain_valid_migration_references(tmp_path):
    store = new_store(tmp_path)
    project = upload(store, case_project(store))
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "save_requirement", {"title": "历史原文", "content": "source", "source_ids": [sid]})
    project = delete(store, project, sid)
    retained = stored_project(store, project["id"])
    preview = migration.inspect(retained)
    assert not any(item["code"] in {"dangling_source_reference", "dangling_source_selection"} for item in preview["blockers"])
    assert preview["convertible"] is True
    assert preview["files"][0]["status"] == "verified"
    retained["cases"][0]["source_selection"]["tech"] = sid
    assert any(item["code"] == "dangling_source_selection" for item in migration.inspect(retained)["blockers"])
