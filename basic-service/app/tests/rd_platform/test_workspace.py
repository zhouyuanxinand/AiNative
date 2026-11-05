"""Workspace content, publication and application consent are independent facts."""
from datetime import datetime, timedelta, timezone

import pytest

from service.rd_platform.store import Store, RdError

PUBLISHER = {"can_edit_resources": True, "can_publish_resources": True}
GRANTER = {"can_manage_application_grants": True}


def store_at(tmp_path, app="rd-platform-local"):
    return Store(tmp_path / "rd.sqlite3", tmp_path / "assets", application_id=app)


def save(store, rid="custom", **extra):
    return store.workspace.save_resource("publisher", PUBLISHER, {
        "id": rid, "kind": "skill", "name": rid, "configuration": {}, "expected_version": 0, **extra}, "save-" + rid)


def publish(store, resource, key="publish"):
    return store.workspace.save_resource("publisher", PUBLISHER, {
        "id": resource["id"], "version": resource["version"], "operation": "publish",
        "expected_version": resource["head_version"], "expected_state_revision": resource["publication_revision"],
        "expected_control_revision": resource["control_revision"]}, key)


def grant(store, rid, version=1, revision=0, operation="grant", key="grant", **extra):
    return store.workspace.set_grant("granter", GRANTER, {
        "id": rid, "version": version, "operation": operation, "expected_revision": revision, **extra}, key)


def test_publication_is_not_content_or_consent_and_replay_precedes_cas(tmp_path):
    store = store_at(tmp_path)
    draft = save(store)
    published = publish(store, draft)
    assert published["version"] == draft["version"] == 1
    assert published["content_digest"] == draft["content_digest"]
    assert published["publication_revision"] == draft["publication_revision"] + 1
    assert publish(store, draft) == published
    assert not store.workspace.capability_available("custom", 1)
    with pytest.raises(RdError) as error:
        store.workspace.catalog_detail("custom", 1)
    assert error.value.status == 404
    receipt = grant(store, "custom")
    assert receipt["revision"] == 1
    assert store.workspace.capability_available("custom", 1)
    summary = store.workspace.catalog_detail("custom", 1)
    assert not ({"configuration", "actor", "created_at", "grant", "publication_revision"} & summary.keys())
    with pytest.raises(RdError) as error:
        grant(store, "custom", operation="revoke")
    assert error.value.status == 409


def test_separate_roles_keys_and_compare_and_swap(tmp_path):
    store = store_at(tmp_path)
    with pytest.raises(RdError) as error:
        store.workspace.save_resource("granter", GRANTER, {"kind": "skill"}, "denied")
    assert error.value.status == 403
    draft = save(store)
    publish(store, draft)
    with pytest.raises(RdError) as error:
        store.workspace.set_grant("publisher", PUBLISHER, {"id": "custom", "version": 1}, "denied")
    assert error.value.status == 403
    with pytest.raises(RdError) as error:
        store.workspace.save_resource("publisher", PUBLISHER, {"id": "custom", "operation": "retire", "expected_version": 1, "expected_state_revision": 1}, "stale")
    assert error.value.status == 409
    with pytest.raises(RdError) as error:
        store.workspace.save_resource("publisher", PUBLISHER, {"kind": "skill"}, None)
    assert error.value.status == 422


def test_revocation_expiration_restart_and_application_isolation(tmp_path):
    store = store_at(tmp_path)
    grant(store, "generate", revision=1, operation="revoke")
    assert not store_at(tmp_path).workspace.capability_available("generate", 1)
    assert not store_at(tmp_path, "other-app").workspace.capability_available("verify", 1)
    save(store)
    publish(store, store.workspace.management_detail("publisher", PUBLISHER, "custom", 1))
    grant(store, "custom", expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), key="expired")
    assert not store.workspace.capability_available("custom", 1)
    assert store.workspace.catalog_list(q="custom")["total"] == 0


def test_catalog_groups_fixed_versions_and_filters_before_pagination(tmp_path):
    store = store_at(tmp_path)
    draft = save(store)
    publish(store, draft)
    grant(store, "custom")
    v2 = store.workspace.save_resource("publisher", PUBLISHER, {"id": "custom", "kind": "skill", "name": "new", "configuration": {}, "expected_version": 1}, "save-v2")
    publish(store, v2, "publish-v2")
    assert store.workspace.catalog_detail("custom", 1)["name"] == "custom"
    assert store.workspace.catalog_list(q="custom")["items"][0]["version"] == 1
    grant(store, "custom", 2, key="grant-v2")
    item = store.workspace.catalog_list(q="new")["items"][0]
    assert item["version"] == 2 and item["available_versions"] == [2, 1]
    page = store.workspace.catalog_list(page=99)
    assert page["items"] == [] and page["total"] == 11 and page["page_size"] == 5
    assert len(store.workspace.catalog_list()["items"]) == 5


def test_team_closure_requires_member_publication_and_application_consent(tmp_path):
    store = store_at(tmp_path)
    team = save(store, "team", kind="team", configuration={"members": [{"resource_id": "generate", "resource_version": 1}]})
    publish(store, team)
    grant(store, "team")
    assert store.workspace.capability_available("team", 1)
    grant(store, "generate", revision=1, operation="revoke", key="revoke-member")
    assert not store.workspace.capability_available("team", 1)
    assert "team" not in {item["id"] for item in store.workspace.catalog_list(q="team")["items"]}
    with pytest.raises(RdError):
        grant(store, "team", revision=1, key="grant-team-again")


def test_adoption_and_live_leases_recheck_consent_without_hashing(tmp_path, monkeypatch):
    from test_store import issue, taskbook
    store = store_at(tmp_path)
    project = taskbook(store)
    wid = project["cases"][0]["workpackages"][0]["id"]
    project = issue(store, project, "submit_workpackage", {"workpackage_id": wid})
    claim = store.claim_node()
    assert claim["snapshot"]["application_id"] == "rd-platform-local"
    assert claim["snapshot"]["actions"][0]["content_digest"]
    grant(store, "generate", revision=1, operation="revoke")
    monkeypatch.setattr(store, "_checked_path", lambda item: pytest.fail("lease checks must not hash files"))
    assert not store.is_claim_active(claim)
    assert not store.renew_claim(claim)
    assert not store.complete_node(claim, {"status": "completed", "result": {}})
    with pytest.raises(RdError):
        issue(store, project, "create_case", {"scenario_id": "taskbook", "title": "no consent"})


def test_content_digest_is_stored_and_management_reads_fixed_versions(tmp_path):
    import json
    store = store_at(tmp_path)
    first = save(store)
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM resource_versions WHERE id='custom' AND version=1").fetchone()[0])
    assert raw["content_digest"] == first["content_digest"]
    publish(store, first)
    store.workspace.save_resource("publisher", PUBLISHER, {"id": "custom", "kind": "skill", "name": "new", "configuration": {}, "expected_version": 1}, "v2")
    fixed = store.workspace.management_detail("granter", GRANTER, "custom", 1)
    assert fixed["available_versions"] == [2, 1] and fixed["head_version"] == 2
    with pytest.raises(RdError) as error:
        store.workspace.management_detail("ordinary", {}, "custom", 1)
    assert error.value.status == 403


def test_project_dto_hides_configuration_but_run_keeps_execution_binding(tmp_path):
    import json
    from test_store import issue, taskbook
    store = store_at(tmp_path)
    project = taskbook(store)
    wid = project["cases"][0]["workpackages"][0]["id"]
    project = issue(store, project, "submit_workpackage", {"workpackage_id": wid})
    assert "configuration" not in project["cases"][0]["workpackages"][0]["snapshot"]["actions"][0]
    claim = store.claim_node()
    assert claim["snapshot"]["actions"][0]["configuration"]["action_id"] == "resolve_context"
    assert "configuration" not in store.get_project("owner", project["id"])["cases"][0]["workpackages"][0]["snapshot"]["actions"][0]


def test_catalog_prunes_optional_nodes_and_required_workflows(tmp_path):
    store = store_at(tmp_path)
    grant(store, "consistency", revision=1, operation="revoke", key="optional")
    catalog = store.catalog()
    assert "consistency" not in {item["id"] for item in catalog["actions"]}
    assert all("consistency" not in item["optional_actions"] for item in catalog["workpackage_definitions"])
    assert store.workspace.catalog_items("workpackages")["total"] == 4
    grant(store, "generate", revision=1, operation="revoke", key="required")
    assert not store.catalog()["research_workflow_templates"]
    assert store.workspace.catalog_items("research")["total"] == 0
    assert all(item["id"] != "taskbook" for item in store.catalog()["workpackage_definitions"])


def test_legacy_runs_always_use_explicit_local_application_and_keep_completed_results(tmp_path):
    import json
    from test_runtime import submitted, completed
    store, project = submitted(tmp_path)
    with store._connection() as db:
        run = db.execute("SELECT id,snapshot FROM runs").fetchone()
        snapshot = json.loads(run["snapshot"])
        snapshot.pop("application_id")
        snapshot.pop("authorization_policy")
        for action in snapshot["actions"]:
            action.pop("content_digest")
        db.execute("UPDATE runs SET snapshot=? WHERE id=?", (json.dumps(snapshot), run["id"]))
    other = store_at(tmp_path, "new-deployment")
    claim = other.claim_node()
    assert claim is not None
    assert other.complete_node(claim, completed(result={"historical": "retained"}))
    grant(store, "generate", revision=1, operation="revoke")
    assert other.claim_node() is None
    historic = other.get_project("owner", project["id"])["cases"][0]["workpackages"][0]
    assert historic["nodes"][0]["result"]["historical"] == "retained"


def test_legacy_retirement_migrates_without_changing_content_or_project(tmp_path):
    import json
    import sqlite3
    from service.rd_platform import catalog
    path = tmp_path / "rd.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE resource_versions(id TEXT,version INTEGER,payload TEXT,PRIMARY KEY(id,version));CREATE TABLE resource_heads(id TEXT PRIMARY KEY,version INTEGER);")
    original = {"id": "generate", "version": 1, "kind": "skill", "name": "generate", "configuration": {}, "execution_mode": "local_real", "executable": True, "status": "published"}
    retired = {**original, "version": 2, "status": "retired"}
    draft = {**original, "version": 3, "status": "draft"}
    for value in (original, retired, draft):
        db.execute("INSERT INTO resource_versions VALUES(?,?,?)", ("generate", value["version"], json.dumps(value)))
    db.execute("INSERT INTO resource_heads VALUES('generate',3)")
    db.commit()
    db.close()
    store = store_at(tmp_path)
    assert not store.workspace.capability_available("generate", 1)
    store.workspace.save_resource("publisher", PUBLISHER, {"id": "generate", "kind": "skill", "name": "next", "configuration": {}, "expected_version": 3}, "next")
    assert not store_at(tmp_path).workspace.capability_available("generate", 1)
    with store._connection() as db:
        assert json.loads(db.execute("SELECT payload FROM resource_versions WHERE id='generate' AND version=1").fetchone()[0]) == original


@pytest.mark.parametrize("members", [[], [{"resource_id": "missing", "resource_version": 1}], [{"resource_id": "team", "resource_version": 1}]])
def test_invalid_team_members_never_publish(tmp_path, members):
    store = store_at(tmp_path)
    with pytest.raises(RdError):
        team = save(store, "team", kind="team", configuration={"members": members})
        publish(store, team)


def test_concurrent_grant_writers_use_independent_revision_cas(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = store_at(tmp_path)
    def write(index):
        try:
            result = store.workspace.set_grant(f"granter-{index}", GRANTER,
                {"id": "verify", "version": 1, "operation": "revoke", "expected_revision": 1}, f"revoke-{index}")
            return result["revision"]
        except RdError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, (1, 2))) == [2, 409]
    assert store_at(tmp_path).workspace.management_detail("granter", GRANTER, "verify", 1)["grant"]["revision"] == 2


@pytest.mark.parametrize("command", ["pull_workpackage", "save_plan", "submit_workpackage"])
def test_workpackage_commands_refuse_revoked_required_fixed_capability(tmp_path, command):
    from test_store import taskbook, issue
    store = store_at(tmp_path)
    project = taskbook(store)
    package = project["cases"][0]["workpackages"][0]
    grant(store, "generate", revision=1, operation="revoke")
    with pytest.raises(RdError) as error:
        issue(store, project, command, {"definition_id": "taskbook", "workpackage_id": package["id"], "nodes": package["nodes"]})
    assert error.value.status == 422 and "授权" in error.value.detail
    assert store.get_project("owner", project["id"])["version"] == project["version"]


def test_flow_adoption_refuses_revoked_required_capability(tmp_path):
    from test_store import evidence_project, issue
    store = store_at(tmp_path)
    project = evidence_project(store, stop_at_planning=True)
    grant(store, "generate", revision=1, operation="revoke")
    with pytest.raises(RdError) as error:
        issue(store, project, "adopt_taskbook_flow", {"workflow_id": "taskbook-new-v1", "workflow_version": "1", "scope": "current", "rationale": "reviewed"})
    assert error.value.status == 422 and "授权" in error.value.detail


def test_expiration_stops_active_claim_and_historical_artifact_remains_readable(tmp_path):
    from pathlib import Path
    from test_runtime import submitted, completed
    store, project = submitted(tmp_path)
    claim = store.claim_node()
    file = Path(claim["work_dir"]) / "retained.txt"
    file.write_text("retained", encoding="utf-8")
    assert store.complete_node(claim, completed(artifacts=[{"id": "retained", "name": "retained.txt", "kind": "txt", "path": str(file)}]))
    next_claim = store.claim_node()
    assert next_claim
    grant(store, "generate", revision=1, expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    assert not store.renew_claim(next_claim)
    assert not store.complete_node(next_claim, completed())
    assert store.artifact_path("owner", project["id"], claim["case_id"], claim["workpackage_id"], "retained").read_text() == "retained"


def test_audit_revisions_and_durable_idempotency_do_not_reapply_commands(tmp_path):
    import json
    store = store_at(tmp_path)
    draft = save(store)
    published = publish(store, draft)
    granted = grant(store, "custom")
    restarted = store_at(tmp_path)
    assert publish(restarted, draft) == published
    assert grant(restarted, "custom") == granted
    with store._connection() as db:
        audit = db.execute("SELECT operation,before_state,after_state,revision FROM workspace_audit ORDER BY rowid").fetchall()
        assert [row["operation"] for row in audit] == ["save", "publish", "grant"]
        assert [row["revision"] for row in audit] == [1, 2, 1]
        assert json.loads(audit[1]["before_state"])["status"] == "draft"
        assert json.loads(audit[1]["after_state"])["status"] == "published"


def test_non_json_resource_configuration_is_rejected_as_validation_error(tmp_path):
    store = store_at(tmp_path)
    with pytest.raises(RdError) as error:
        save(store, configuration={"value": float("nan")})
    assert error.value.status == 422


def test_old_upload_receipt_cannot_reintroduce_execution_configuration(tmp_path):
    import json
    from test_runtime import submitted
    store, project = submitted(tmp_path)
    cid = project["cases"][0]["id"]
    result = store.add_source("owner", project["id"], cid, project["version"], "old-upload", "reference", "memo.txt", b"memo")
    result["cases"][0]["workpackages"][0]["snapshot"]["actions"][0]["configuration"] = {"private_reference": "old"}
    with store._connection() as db:
        db.execute("UPDATE receipts SET response=? WHERE actor='owner' AND project_id=? AND key='old-upload'", (json.dumps(result), project["id"]))
    replay = store.add_source("owner", project["id"], cid, project["version"], "old-upload", "reference", "memo.txt", b"memo")
    assert "configuration" not in replay["cases"][0]["workpackages"][0]["snapshot"]["actions"][0]


def test_cross_version_stale_publish_cannot_override_newer_resource_retirement(tmp_path):
    store = store_at(tmp_path)
    head = store.workspace.save_resource("publisher", PUBLISHER, {"id": "generate", "kind": "skill", "name": "new draft", "configuration": {}, "expected_version": 1}, "generate-v2")
    old = store.workspace.management_detail("publisher", PUBLISHER, "generate", 1)
    retired = store.workspace.save_resource("publisher", PUBLISHER, {
        "id": "generate", "version": 2, "operation": "retire", "expected_version": 2,
        "expected_state_revision": head["publication_revision"], "expected_control_revision": head["control_revision"]}, "retire-v2")
    assert not store.workspace.capability_available("generate", 1)
    with pytest.raises(RdError) as error:
        publish(store, old, "stale-v1-publish")
    assert error.value.status == 409
    assert not store.workspace.capability_available("generate", 1)
    assert retired["control_revision"] == head["control_revision"] + 1


def test_control_revision_is_required_for_untrusted_state_commands(tmp_path):
    store = store_at(tmp_path)
    draft = save(store)
    with pytest.raises(RdError) as error:
        store.workspace.save_resource("publisher", PUBLISHER, {"id": "custom", "version": 1, "operation": "publish", "expected_version": 1,
            "expected_state_revision": draft["publication_revision"]}, "missing-control-revision")
    assert error.value.status == 409


def test_controls_schema_migration_and_restarts_preserve_retired_status_and_revision(tmp_path):
    store = store_at(tmp_path)
    save(store)
    with store._connection() as db:
        db.executescript("DROP TABLE workspace_controls; CREATE TABLE workspace_controls(id TEXT PRIMARY KEY, retired INTEGER NOT NULL); INSERT INTO workspace_controls VALUES('generate',1);")
    migrated = store_at(tmp_path)
    first = migrated.workspace.management_detail("publisher", PUBLISHER, "generate", 1)
    assert first["control_revision"] == 1
    assert not migrated.workspace.capability_available("generate", 1)
    assert migrated.workspace.management_detail("publisher", PUBLISHER, "custom", 1)["control_revision"] == 1
    retired = migrated.workspace.save_resource("publisher", PUBLISHER, {"id": "generate", "version": 1, "operation": "retire", "expected_version": 1,
        "expected_state_revision": first["publication_revision"], "expected_control_revision": first["control_revision"]}, "retire-again")
    restarted = store_at(tmp_path)
    assert restarted.workspace.management_detail("publisher", PUBLISHER, "generate", 1)["control_revision"] == retired["control_revision"] == 2
    assert not restarted.workspace.capability_available("generate", 1)


def test_concurrent_cross_version_state_writers_share_control_revision_cas(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = store_at(tmp_path)
    head = store.workspace.save_resource("publisher", PUBLISHER, {"id": "generate", "kind": "skill", "name": "new", "configuration": {}, "expected_version": 1}, "new-head")
    old = store.workspace.management_detail("publisher", PUBLISHER, "generate", 1)
    def write(operation):
        resource = old if operation == "publish" else head
        try:
            result = store.workspace.save_resource(f"publisher-{operation}", PUBLISHER, {
                "id": "generate", "version": resource["version"], "operation": operation, "expected_version": 2,
                "expected_state_revision": resource["publication_revision"], "expected_control_revision": resource["control_revision"]}, operation)
            return operation, result["control_revision"]
        except RdError as error:
            return operation, error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = dict(pool.map(write, ("publish", "retire")))
    assert sorted(outcomes.values()) == [2, 409]
    assert store.workspace.capability_available("generate", 1) is (outcomes["publish"] == 2)
    fixed = store_at(tmp_path).workspace.management_detail("publisher", PUBLISHER, "generate", 1)
    assert fixed["control_revision"] == 2
    with store._connection() as db:
        import json
        audit = db.execute("SELECT before_state,after_state FROM workspace_audit WHERE operation IN ('publish','retire')").fetchall()
        assert len(audit) == 1
        assert json.loads(audit[0]["before_state"])["control"]["revision"] == 1
        assert json.loads(audit[0]["after_state"])["control"]["revision"] == 2
