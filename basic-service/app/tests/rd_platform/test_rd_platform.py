"""Business behavior over a real, restartable SQLite store."""
from tests.support.rd_project import OWNER, ENGINEER, REVIEWER
from tests.support.rd_project import store as store
from tests.support.rd_project import command, project, prepared, capture, raises
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.service.rd_platform.store import RdError, RdStore


def test_restart_and_membership_isolation(store):
    d = prepared(store)
    reopened = RdStore(store.db_path, store.artifact_root)
    assert reopened.detail(d["project"]["id"], "reviewer")["tasks"][0]["status"] == "in_progress"
    assert reopened.list_projects("outsider")["total"] == 0
    raises(404, lambda: reopened.detail(d["project"]["id"], "outsider"))
    assert reopened.list_projects("engineer", q="连接器")["total"] == 1
    assert reopened.list_projects("engineer", q="absent")["total"] == 0


def test_idempotency_replays_original_result_and_rejects_changed_input(store):
    payload = {"name": "first", "customer": "customer", "product": "product"}
    d = store.create_project(OWNER, payload, "create-key")
    assert store.create_project(OWNER, payload, "create-key") == d
    raises(409, lambda: store.create_project(OWNER, {**payload, "name": "other"}, "create-key"))
    member = {**ENGINEER, "role": "engineer"}
    changed = command(store, d, "add_member", member, key="member-key")
    command(store, changed, "add_member", {**REVIEWER, "role": "reviewer"})
    assert command(store, d, "add_member", member, key="member-key") == changed
    assert len(store.detail(d["project"]["id"], "owner")["events"]) == 3
    raises(409, lambda: command(store, d, "add_member", {**member, "display_name": "changed"}, key="member-key"))


def test_concurrent_versions_commit_exactly_one_change(store):
    d = project(store)
    def write(n):
        try:
            command(store, d, "add_member", {"user_id": f"u{n}", "display_name": f"User {n}", "role": "viewer"})
            return 200
        except RdError as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, (1, 2))) == [200, 409]
    final = store.detail(d["project"]["id"], "owner")
    assert final["project"]["version"] == 2
    assert len(final["members"]) == 2


def test_baseline_requires_resolved_requirements_and_keeps_revision_history(store):
    d = project(store)
    raises(409, lambda: command(store, d, "confirm_baseline"))
    row = {"title": "需求", "content": "要求", "source": "协议", "acceptance": "试验", "clarification": "open", "required": True}
    d = command(store, d, "save_requirement", row)
    raises(409, lambda: command(store, d, "confirm_baseline"))
    d = command(store, d, "save_requirement", {**row, "id": d["requirements"][0]["id"], "clarification": "resolved"})
    d = command(store, d, "confirm_baseline")
    snapshot = d["baselines"][0]["requirements"][0]
    d = command(store, d, "save_requirement", {**row, "id": snapshot["id"], "content": "新要求", "clarification": "resolved"})
    assert d["baselines"][0]["requirements"][0]["content"] == "要求"
    assert d["requirements"][0]["revision"] == 3
    assert len(d["requirements"][0]["history"]) == 2


def test_permissions_assignment_and_self_approval(store):
    d = prepared(store)
    tid = d["tasks"][0]["id"]
    raises(403, lambda: command(store, d, "add_member", {"user_id": "x", "role": "viewer", "display_name": "X"}, ENGINEER))
    raises(422, lambda: command(store, d, "reassign_task", {"task_id": tid, "assignee_id": "engineer", "reviewer_id": "engineer"}))
    raises(403, lambda: command(store, d, "start_task", {"task_id": tid}, REVIEWER))
    raises(409, lambda: command(store, d, "remove_member", {"user_id": "owner"}))
    d = capture(store, d)
    d = command(store, d, "submit_review", {"task_id": tid, "artifact_id": d["artifacts"][0]["id"]}, ENGINEER)
    rid = d["reviews"][0]["id"]
    raises(403, lambda: command(store, d, "decide_review", {"review_id": rid, "decision": "approved", "comment": ""}, ENGINEER))
    raises(422, lambda: command(store, d, "decide_review", {"review_id": rid, "decision": "rejected", "comment": ""}, REVIEWER))


def test_quality_rejection_resubmission_approval_and_download_hash(store):
    d = capture(store, prepared(store), "unknown")
    tid = d["tasks"][0]["id"]
    raises(409, lambda: command(store, d, "submit_review", {"task_id": tid, "artifact_id": d["artifacts"][0]["id"]}, ENGINEER))
    d = capture(store, d)
    aid = d["artifacts"][-1]["id"]
    raises(409, lambda: store.artifact(d["project"]["id"], aid, "reviewer", approved=True))
    d = command(store, d, "submit_review", {"task_id": tid, "artifact_id": aid}, ENGINEER)
    rid = d["reviews"][-1]["id"]
    d = command(store, d, "decide_review", {"review_id": rid, "decision": "rejected", "comment": "补充试验条件"}, REVIEWER)
    assert d["tasks"][0]["status"] == "changes_requested"
    d = command(store, d, "start_task", {"task_id": tid}, ENGINEER)
    d = capture(store, d)
    new_aid = d["artifacts"][-1]["id"]
    d = command(store, d, "submit_review", {"task_id": tid, "artifact_id": new_aid}, ENGINEER)
    d = command(store, d, "decide_review", {"review_id": d["reviews"][-1]["id"], "decision": "approved", "comment": "同意"}, REVIEWER)
    assert d["tasks"][0]["status"] == "done"
    assert [r["status"] for r in d["reviews"]] == ["rejected", "approved"]
    artifact = store.artifact(d["project"]["id"], new_aid, "reviewer", approved=True)
    assert artifact["sha256"] == hashlib.sha256(b"fixed reviewed document").hexdigest()
    from pathlib import Path
    Path(artifact["file_ref"]).write_bytes(b"tampered")
    raises(409, lambda: store.artifact(d["project"]["id"], new_aid, "reviewer", approved=True))


def test_new_baseline_invalidates_pending_review_and_forces_new_generation(store):
    d = capture(store, prepared(store))
    tid, aid, jid = d["tasks"][0]["id"], d["artifacts"][0]["id"], d["artifacts"][0]["jid"]
    d = command(store, d, "submit_review", {"task_id": tid, "artifact_id": aid}, ENGINEER)
    rid = d["reviews"][0]["id"]
    d = command(store, d, "confirm_baseline")
    assert d["tasks"][0]["status"] == "needs_revalidation"
    assert d["reviews"][0]["status"] == "input_changed"
    raises(409, lambda: command(store, d, "decide_review", {"review_id": rid, "decision": "approved"}, REVIEWER))
    d = command(store, d, "adopt_baseline", {"task_id": tid})
    assert d["tasks"][0]["status"] == "in_progress"
    raises(409, lambda: command(store, d, "submit_review", {"task_id": tid, "artifact_id": aid}, ENGINEER))
    raises(409, lambda: store.bind_generation(d["project"]["id"], tid, ENGINEER, jid, {}))
    assert store.generation(jid)["baseline_id"] != d["project"]["current_baseline_id"]


def test_removal_and_reassignment_cancel_pending_authority(store):
    d = capture(store, prepared(store))
    tid = d["tasks"][0]["id"]
    d = command(store, d, "submit_review", {"task_id": tid, "artifact_id": d["artifacts"][0]["id"]}, ENGINEER)
    d = command(store, d, "remove_member", {"user_id": "reviewer"})
    assert d["reviews"][0]["status"] == "withdrawn"
    raises(404, lambda: store.authorize_generation(d["generations"][0]["jid"], "reviewer"))
    raises(404, lambda: store.artifact(d["project"]["id"], d["artifacts"][0]["id"], "reviewer"))
    d = command(store, d, "reassign_task", {"task_id": tid, "assignee_id": "engineer", "reviewer_id": "owner"})
    assert d["tasks"][0]["reviewer_id"] == "owner"


def test_generation_rechecks_uploaded_input_baseline_inside_binding_transaction(store):
    d = prepared(store)
    old_baseline = d["project"]["current_baseline_id"]
    d = command(store, d, "confirm_baseline")
    tid = d["tasks"][0]["id"]
    d = command(store, d, "adopt_baseline", {"task_id": tid})
    raises(409, lambda: store.bind_generation(d["project"]["id"], tid, ENGINEER, "stale-upload", {"rd_baseline_id": old_baseline}))
    assert store.generation("stale-upload") is None


@pytest.mark.parametrize("action,payload", [
    ("add_member", {"user_id": "u", "display_name": "U", "role": []}),
    ("save_requirement", {"title": "T", "content": "C", "clarification": {}}),
    ("create_task", {"title": "T", "assignee_id": [], "reviewer_id": "reviewer"}),
])
def test_malformed_command_fields_are_validation_errors(store, action, payload):
    d = prepared(store)
    raises(422, lambda: command(store, d, action, payload))


def test_reassignment_revokes_previous_generation_writer(store):
    d = capture(store, prepared(store))
    pid, tid, jid = d["project"]["id"], d["tasks"][0]["id"], d["generations"][0]["jid"]
    d = command(store, d, "add_member", {"user_id": "new", "display_name": "新执行人", "role": "engineer"})
    d = command(store, d, "reassign_task", {"task_id": tid, "assignee_id": "new", "reviewer_id": "reviewer"})
    raises(403, lambda: store.authorize_generation(jid, "engineer", write=True))
    raises(403, lambda: store.authorize_generation(jid, "new", write=True))
    assert store.authorize_generation(jid, "engineer")["actor_id"] == "engineer"


def test_done_task_revalidation_preserves_approved_history(store):
    d = capture(store, prepared(store))
    tid, aid = d["tasks"][0]["id"], d["artifacts"][0]["id"]
    d = command(store, d, "submit_review", {"task_id": tid, "artifact_id": aid}, ENGINEER)
    d = command(store, d, "decide_review", {"review_id": d["reviews"][0]["id"], "decision": "approved"}, REVIEWER)
    d = command(store, d, "confirm_baseline")
    assert d["tasks"][0]["status"] == "needs_revalidation"
    assert d["tasks"][0]["previous_status"] == "done"
    assert d["reviews"][0]["status"] == "approved"
    assert store.artifact(d["project"]["id"], aid, "reviewer", approved=True)["id"] == aid
    d = command(store, d, "adopt_baseline", {"task_id": tid})
    assert d["tasks"][0]["status"] == "in_progress"
    raises(409, lambda: command(store, d, "submit_review", {"task_id": tid, "artifact_id": aid}, ENGINEER))


def test_distinct_artifact_revisions_can_share_verified_content_addressed_bytes(store):
    d = capture(store, prepared(store))
    original = store.artifact(d["project"]["id"], d["artifacts"][0]["id"], "engineer")
    pid, tid = d["project"]["id"], d["tasks"][0]["id"]
    store.bind_generation(pid, tid, ENGINEER, "second-job", {})
    d = store.detail(pid, "engineer")
    payload = {k: original[k] for k in ("filename", "sha256", "file_ref", "quality_status")}
    payload["quality_evidence"] = {"revision_id": "revision-2", "sha256": payload["sha256"], "checks": {"status": "passed", "revision_id": "revision-2", "sha256": payload["sha256"], "scope": "revision_deterministic"}}
    d = store.register_artifact(pid, tid, ENGINEER, {**payload, "jid": "second-job", "source_revision_id": "revision-2"}, d["project"]["version"], "capture-second")
    assert len(d["artifacts"]) == 2
    assert d["artifacts"][0]["id"] != d["artifacts"][1]["id"]
    assert d["artifacts"][0]["source_revision_id"] == "revision-1"


def test_concurrent_approval_retry_records_one_decision_event(store):
    d = capture(store, prepared(store))
    tid = d["tasks"][0]["id"]
    d = command(store, d, "submit_review", {"task_id": tid, "artifact_id": d["artifacts"][0]["id"]}, ENGINEER)
    payload = {"review_id": d["reviews"][0]["id"], "decision": "approved", "comment": "同意"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: command(store, d, "decide_review", payload, REVIEWER, "same-decision"), (1, 2)))
    assert results[0] == results[1]
    final = store.detail(d["project"]["id"], "owner")
    assert final["project"]["version"] == d["project"]["version"] + 1
    assert len([e for e in final["events"] if e["action"] == "decide_review"]) == 1
    assert final["tasks"][0]["status"] == "done"


def test_owner_can_review_independent_work_after_withdrawal(store):
    d = capture(store, prepared(store))
    tid, aid = d["tasks"][0]["id"], d["artifacts"][0]["id"]
    d = command(store, d, "submit_review", {"task_id": tid, "artifact_id": aid}, ENGINEER)
    d = command(store, d, "withdraw_review", {"review_id": d["reviews"][0]["id"], "comment": "更换审核人"})
    assert d["tasks"][0]["status"] == "in_progress"
    assert d["reviews"][0]["status"] == "withdrawn"
    d = command(store, d, "reassign_task", {"task_id": tid, "assignee_id": "engineer", "reviewer_id": "owner"})
    d = command(store, d, "submit_review", {"task_id": tid, "artifact_id": aid}, ENGINEER)
    d = command(store, d, "decide_review", {"review_id": d["reviews"][-1]["id"], "decision": "approved"})
    assert d["tasks"][0]["status"] == "done"


def artifact_payload(store, d):
    """Use a genuine bound job and actual bytes for trusted registration tests."""
    pid, tid = d["project"]["id"], d["tasks"][0]["id"]
    store.bind_generation(pid, tid, ENGINEER, "evidence-job", {})
    d = store.detail(pid, "engineer")
    path = store.artifact_root / "evidence.docx"
    path.write_bytes(b"evidence document")
    digest = hashlib.sha256(b"evidence document").hexdigest()
    evidence = {"revision_id": "evidence-r1", "sha256": digest, "checks": {"status": "passed", "revision_id": "evidence-r1", "sha256": digest, "scope": "revision_deterministic", "checked_at": "first-check", "findings": []}, "rules_fingerprint": "rules-fixed", "generation_summary": {"delivery_status": "approved"}}
    return d, {"jid": "evidence-job", "source_revision_id": "evidence-r1", "filename": "evidence.docx", "sha256": digest, "file_ref": str(path), "quality_status": "passed", "quality_evidence": evidence}


def test_quality_evidence_survives_restart_and_public_detail_hides_disk_path(store):
    d, payload = artifact_payload(store, prepared(store))
    result = store.register_artifact(d["project"]["id"], d["tasks"][0]["id"], ENGINEER, payload, d["project"]["version"], "evidence-capture")
    payload["quality_evidence"]["checks"]["findings"].append("external mutation")
    reopened = RdStore(store.db_path, store.artifact_root)
    public = reopened.detail(d["project"]["id"], "reviewer")["artifacts"][0]
    assert public["quality_evidence"]["checks"]["findings"] == []
    assert public["quality_evidence"]["rules_fingerprint"] == "rules-fixed"
    assert str(store.artifact_root) not in str(result)
    assert str(store.artifact_root) not in str(public)
    assert reopened.artifact(d["project"]["id"], public["id"], "reviewer")["file_ref"] == payload["file_ref"]


@pytest.mark.parametrize("mismatch", ["missing", "revision", "hash", "check_revision", "check_hash", "failed_check"])
def test_passed_artifact_rejects_missing_or_mismatched_quality_evidence(store, mismatch):
    d, payload = artifact_payload(store, prepared(store))
    if mismatch == "missing":
        payload.pop("quality_evidence")
    elif mismatch == "revision":
        payload["quality_evidence"]["revision_id"] = "another-revision"
    elif mismatch == "hash":
        payload["quality_evidence"]["sha256"] = "0" * 64
    elif mismatch == "check_revision":
        payload["quality_evidence"]["checks"]["revision_id"] = "another-revision"
    elif mismatch == "check_hash":
        payload["quality_evidence"]["checks"]["sha256"] = "0" * 64
    else:
        payload["quality_evidence"]["checks"]["status"] = "failed"
    raises(409, lambda: store.register_artifact(d["project"]["id"], d["tasks"][0]["id"], ENGINEER, payload, d["project"]["version"], "bad-evidence"))
    assert store.detail(d["project"]["id"], "engineer")["artifacts"] == []


def test_capture_retry_preserves_first_evidence_when_same_revision_checks_are_rerun(store):
    d, payload = artifact_payload(store, prepared(store))
    args = (d["project"]["id"], d["tasks"][0]["id"], ENGINEER)
    first = store.register_artifact(*args, payload, d["project"]["version"], "capture-once")
    payload["quality_evidence"]["checks"]["checked_at"] = "later-check"
    assert store.register_artifact(*args, payload, d["project"]["version"], "capture-once") == first
    assert first["artifacts"][0]["quality_evidence"]["checks"]["checked_at"] == "first-check"


def test_api_requires_verified_identity_and_rejects_forged_actor(store, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.controller import rd_controller
    monkeypatch.setattr(rd_controller, "get_store", lambda: store)
    app = FastAPI()
    identity = {"value": None}
    @app.middleware("http")
    async def set_identity(request, call_next):
        request.state.current_user = identity["value"]
        return await call_next(request)
    app.include_router(rd_controller.router)
    client = TestClient(app)
    payload = {"name": "项目", "customer": "客户", "product": "产品"}
    assert client.post("/api/rd/projects", json=payload, headers={"Idempotency-Key": "key"}).status_code == 401
    identity["value"] = {"userid": "owner", "display_name": "真实用户", "verified": False}
    assert client.get("/api/rd/projects").status_code == 401
    identity["value"]["verified"] = True
    response = client.post("/api/rd/projects", json={**payload, "actor": {"user_id": "forged"}}, headers={"Idempotency-Key": "key"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    response = client.post("/api/rd/projects", json=payload, headers={"Idempotency-Key": "key"})
    assert response.status_code == 200
    assert response.json()["project"]["owner_id"] == "owner"
    assert response.json()["members"][0]["display_name"] == "真实用户"
    invalid = client.get("/api/rd/projects?page=0")
    assert invalid.status_code == 422
    assert isinstance(invalid.json()["detail"], str)
