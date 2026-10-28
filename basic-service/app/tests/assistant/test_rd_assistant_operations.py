"""Assistant confirmations reuse real domain guards and durable idempotency."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.service.assistant import operations
from src.service.rd_platform.store import RdStore
from tests.support.rd_project import OWNER, ENGINEER, REVIEWER, command, prepared, project, raises, store
from tests.support.taskbook_release import planned, submit


REQUIREMENT = {"title": "补充需求", "content": "接口要求", "source": "协议2", "acceptance": "检查", "clarification": "resolved"}


def prepare(store, d, action="save_requirement", payload=None, actor=OWNER):
    return operations.prepare_operation(store, actor, d["project"]["id"], action, REQUIREMENT if payload is None else payload)


def test_prepare_is_read_only_and_confirmation_is_durable_and_idempotent(store):
    d = project(store)
    proposal = prepare(store, d)
    assert proposal["requires_confirmation"] is True
    assert proposal["payload"] == REQUIREMENT
    assert proposal["expected_version"] == d["project"]["version"]
    assert proposal["fields"] and proposal["summary"]
    assert store.detail(d["project"]["id"], "owner") == d
    reopened = RdStore(store.db_path, store.artifact_root)
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: operations.confirm_operation(reopened, OWNER, proposal["id"]), range(2)))
    assert receipts[0] == receipts[1]
    assert receipts[0]["status"] == "executed"
    assert receipts[0]["project_version"] == d["project"]["version"] + 1
    saved = store.detail(d["project"]["id"], "owner")
    assert len(saved["requirements"]) == 1
    assert saved["events"][-1]["detail"]["request_key"] == f"assistant:{proposal['id']}"
    assert operations.confirm_operation(store, OWNER, proposal["id"]) == receipts[0]


def test_prepare_updates_exact_requirement_without_modifying_original_draft(store):
    d = prepared(store)
    req = d["requirements"][0]
    payload = {**{k: req[k] for k in ("id", "title", "content", "source", "acceptance", "clarification", "required")}, "content": "新增接口核验"}
    proposal = prepare(store, d, payload=payload, actor=ENGINEER)
    assert any(change["before"] == req["content"] and change["after"] == payload["content"] for change in proposal["changes"])
    assert store.detail(d["project"]["id"], "owner")["requirements"][0]["content"] == req["content"]
    operations.confirm_operation(store, ENGINEER, proposal["id"])
    assert store.detail(d["project"]["id"], "owner")["requirements"][0]["content"] == payload["content"]


def test_partial_requirement_edit_keeps_unspecified_source_and_acceptance_visible(store):
    d = prepared(store)
    req = d["requirements"][0]
    proposal = prepare(store, d, payload={"id": req["id"], "title": req["title"], "content": "局部修改"})
    assert proposal["payload"]["source"] == req["source"]
    assert proposal["payload"]["acceptance"] == req["acceptance"]
    assert any(field["value"] == req["source"] for field in proposal["fields"])
    operations.confirm_operation(store, OWNER, proposal["id"])
    saved = store.detail(d["project"]["id"], "owner")["requirements"][0]
    assert saved["source"] == req["source"] and saved["acceptance"] == req["acceptance"]


def test_title_only_edit_preserves_long_requirement_from_authoritative_store(store):
    d = project(store)
    long_content = "长需求完整内容" * 1000
    d = command(store, d, "save_requirement", {**REQUIREMENT, "content": long_content})
    req = d["requirements"][0]
    proposal = prepare(store, d, payload={"id": req["id"], "title": "仅修改标题"})
    assert proposal["payload"]["content"] == long_content
    assert proposal["payload"]["source"] == req["source"]
    assert store.detail(d["project"]["id"], "owner")["requirements"][0]["title"] == req["title"]
    operations.confirm_operation(store, OWNER, proposal["id"])
    saved = store.detail(d["project"]["id"], "owner")["requirements"][0]
    assert saved["title"] == "仅修改标题"
    assert saved["content"] == long_content
    assert saved["history"][0]["content"] == long_content


def test_identity_isolation_viewer_rejection_and_unknown_commands(store):
    d = command(store, project(store), "add_member", {**ENGINEER, "role": "engineer"})
    d = command(store, d, "add_member", {"user_id": "viewer", "display_name": "只读", "role": "viewer"})
    proposal = prepare(store, d)
    raises(404, lambda: operations.confirm_operation(store, ENGINEER, proposal["id"]))
    raises(403, lambda: prepare(store, d, actor={"user_id": "viewer"}))
    assert operations.capabilities(store.detail(d["project"]["id"], "viewer"), {"user_id": "viewer"}) == []
    for action in ("shell", "powershell", "skill:delete", "run_script", "add_member"):
        raises(422, lambda: prepare(store, d, action, {"command": "whoami"}))
    raises(422, lambda: prepare(store, d, payload={**REQUIREMENT, "expected_version": 1}))


def test_expiry_and_cas_never_silently_refresh_the_fixed_proposal(store, monkeypatch):
    d = project(store)
    fixed_time = operations._utcnow()
    monkeypatch.setattr(operations, "_utcnow", lambda: fixed_time)
    expired = prepare(store, d)
    from datetime import timedelta
    monkeypatch.setattr(operations, "_utcnow", lambda: fixed_time + timedelta(minutes=11))
    raises(410, lambda: operations.confirm_operation(store, OWNER, expired["id"]))
    monkeypatch.setattr(operations, "_utcnow", lambda: fixed_time)
    stale = prepare(store, d)
    d = command(store, d, "save_requirement", {**REQUIREMENT, "title": "别处修改"})
    raises(409, lambda: operations.confirm_operation(store, OWNER, stale["id"]))
    assert len(store.detail(d["project"]["id"], "owner")["requirements"]) == 1


def test_model_context_version_cannot_prepare_over_a_newer_project_snapshot(store):
    d = project(store)
    model_version = d["project"]["version"]
    changed = command(store, d, "save_requirement", {**REQUIREMENT, "content": "模型等待期间人工更新"})
    raises(409, lambda: operations.prepare_operation(store, OWNER, d["project"]["id"], "save_requirement", REQUIREMENT, expected_version=model_version))
    assert store.detail(d["project"]["id"], "owner") == changed
    with store._connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assistant_operation_proposals").fetchone()[0] == 0
    current = operations.prepare_operation(store, OWNER, d["project"]["id"], "save_requirement", REQUIREMENT, expected_version=changed["project"]["version"])
    assert current["expected_version"] == changed["project"]["version"]


def test_permissions_are_rechecked_at_confirmation_and_completed_replay(store):
    d = prepared(store)
    proposal = prepare(store, d, actor=ENGINEER)
    d = command(store, d, "add_member", {**ENGINEER, "role": "viewer"})
    raises(403, lambda: operations.confirm_operation(store, ENGINEER, proposal["id"]))
    d = command(store, d, "add_member", {**ENGINEER, "role": "engineer"})
    proposal = prepare(store, d, actor=ENGINEER)
    operations.confirm_operation(store, ENGINEER, proposal["id"])
    d = store.detail(d["project"]["id"], "owner")
    d = command(store, d, "add_member", {**ENGINEER, "role": "viewer"})
    raises(403, lambda: operations.confirm_operation(store, ENGINEER, proposal["id"]))


@pytest.mark.parametrize("decision,comment,status", [("approved", "同意", "done"), ("rejected", "补充试验", "changes_requested")])
def test_native_review_confirmation_keeps_fixed_snapshot_and_independent_reviewer(store, decision, comment, status):
    d = submit(store, planned(store))
    rid = d["reviews"][-1]["id"]
    payload = {"review_id": rid, "decision": decision, "comment": comment}
    raises(403, lambda: prepare(store, d, "decide_review", payload, ENGINEER))
    raises(403, lambda: prepare(store, d, "decide_review", payload, OWNER))
    proposal = prepare(store, d, "decide_review", payload, REVIEWER)
    assert proposal["warnings"]
    assert store.detail(d["project"]["id"], "reviewer")["reviews"][-1]["status"] == "pending"
    receipt = operations.confirm_operation(store, REVIEWER, proposal["id"])
    saved = store.detail(d["project"]["id"], "reviewer")
    assert saved["reviews"][-1]["status"] == decision
    assert saved["reviews"][-1]["taskbook_snapshot"] == d["reviews"][-1]["taskbook_snapshot"]
    assert saved["tasks"][0]["status"] == status
    assert len(saved["taskbook_releases"]) == (1 if decision == "approved" else 0)
    assert "detail" not in receipt


def test_review_rejects_empty_rejection_and_modified_file_before_confirm(store):
    d = submit(store, planned(store))
    rid = d["reviews"][-1]["id"]
    raises(422, lambda: prepare(store, d, "decide_review", {"review_id": rid, "decision": "rejected", "comment": ""}, REVIEWER))
    proposal = prepare(store, d, "decide_review", {"review_id": rid, "decision": "approved"}, REVIEWER)
    from pathlib import Path
    artifact = store.artifact(d["project"]["id"], d["artifacts"][-1]["id"], "reviewer")
    Path(artifact["file_ref"]).write_bytes(b"tampered")
    raises(409, lambda: operations.confirm_operation(store, REVIEWER, proposal["id"]))
    assert store.detail(d["project"]["id"], "reviewer")["reviews"][-1]["status"] == "pending"


def test_publish_requires_real_current_approval_and_creates_one_release(store):
    d = planned(store)
    raises(404, lambda: prepare(store, d, "publish_plan", {"task_id": d["tasks"][0]["id"], "release_id": "fabricated"}))
    d = submit(store, d)
    d = command(store, d, "decide_review", {"review_id": d["reviews"][-1]["id"], "decision": "approved"}, REVIEWER)
    payload = {"task_id": d["tasks"][0]["id"], "release_id": d["taskbook_releases"][0]["id"]}
    raises(403, lambda: prepare(store, d, "publish_plan", payload, ENGINEER))
    proposal = prepare(store, d, "publish_plan", payload)
    assert proposal["warnings"]
    assert store.detail(d["project"]["id"], "owner")["plan_releases"] == []
    first = operations.confirm_operation(store, OWNER, proposal["id"])
    assert operations.confirm_operation(store, OWNER, proposal["id"]) == first
    saved = store.detail(d["project"]["id"], "owner")
    assert len(saved["plan_releases"]) == len(saved["handoffs"]) == 1


def test_baseline_preflight_cannot_skip_existing_required_input_rules(store):
    d = project(store)
    raises(409, lambda: prepare(store, d, "confirm_baseline", {}))
    d = command(store, d, "save_requirement", REQUIREMENT)
    proposal = prepare(store, d, "confirm_baseline", {})
    assert proposal["warnings"]
    operations.confirm_operation(store, OWNER, proposal["id"])
    assert store.detail(d["project"]["id"], "owner")["project"]["current_baseline_id"]


def test_crash_after_domain_commit_recovers_receipt_without_duplicate_write(store, monkeypatch):
    d = project(store)
    proposal = prepare(store, d)
    saved = store.execute(d["project"]["id"], OWNER, "save_requirement", proposal["payload"], proposal["expected_version"], f"assistant:{proposal['id']}")
    from datetime import timedelta
    now = operations._utcnow()
    monkeypatch.setattr(operations, "_utcnow", lambda: now + timedelta(minutes=11))
    receipt = operations.confirm_operation(store, OWNER, proposal["id"])
    assert receipt["project_version"] == saved["project"]["version"]
    assert len(store.detail(d["project"]["id"], "owner")["requirements"]) == 1


def test_capability_schemas_are_fixed_and_do_not_grant_extra_project_roles(store):
    d = prepared(store)
    rows = operations.capabilities(d, OWNER)
    assert {r["id"] for r in rows} == {"save_requirement", "create_task", "reassign_task", "confirm_baseline", "decide_review", "publish_plan", "record_selection", "record_delivery", "start_task"}
    assert all(r["kind"] == "domain_command" and r["requires_confirmation"] and r["schema"]["additionalProperties"] is False for r in rows)
    assert all(r["action"] == r["id"] and r["schema"]["type"] == "object" for r in rows)
    assert {r["id"] for r in operations.capabilities(store.detail(d["project"]["id"], "engineer"), ENGINEER)} == {"save_requirement", "start_task"}


def test_trusted_registered_skill_dispatches_only_after_confirmation_and_replays_receipt(store, monkeypatch):
    # Registration is trusted application code, not a chat text, executable path,
    # shell string, package download, or an API-created ability.
    monkeypatch.setattr(operations, "_REGISTRY", dict(operations._REGISTRY))
    d = command(store, project(store), "add_member", {**ENGINEER, "role": "engineer"})
    executions = []
    def preflight(domain_store, doc, actor, payload):
        domain_store._apply(doc, actor, "save_requirement", payload)
    def execute(domain_store, actor, pid, payload, expected_version, request_key):
        executions.append(request_key)
        return domain_store.execute(pid, actor, "save_requirement", payload, expected_version, request_key)
    operations.register_capability(operations.OperationCapability(
        id="skill.synthetic_requirement", kind="skill", label="整理合成需求", description="测试用可信需求整理处理器",
        schema={"type": "object", "properties": {"title": {"type": "string", "description": "需求标题"}, "content": {"type": "string", "description": "需求内容"}}, "required": ["title", "content"], "additionalProperties": False},
        permissions=("owner",), prepare_handler=preflight, execute_handler=execute,
    ))
    payload = {"title": "处理器合成需求", "content": "仅用于本地测试的接口检查项"}
    capability = next(row for row in operations.capabilities(d, OWNER) if row["id"] == "skill.synthetic_requirement")
    assert capability["kind"] == "skill" and capability["requires_confirmation"] is True
    raises(422, lambda: prepare(store, d, "skill.synthetic_requirement", {**payload, "shell": "whoami"}))
    raises(403, lambda: prepare(store, d, "skill.synthetic_requirement", payload, ENGINEER))
    assert "skill.synthetic_requirement" not in {row["id"] for row in operations.capabilities(store.detail(d["project"]["id"], "engineer"), ENGINEER)}
    proposal = prepare(store, d, "skill.synthetic_requirement", payload)
    assert proposal["kind"] == "skill" and proposal["payload"] == payload
    assert executions == []
    assert store.detail(d["project"]["id"], "owner") == d
    receipt = operations.confirm_operation(store, OWNER, proposal["id"])
    assert receipt["status"] == "executed"
    assert executions == [f"assistant:{proposal['id']}"]
    assert operations.confirm_operation(store, OWNER, proposal["id"]) == receipt
    assert executions == [f"assistant:{proposal['id']}"]
    saved = store.detail(d["project"]["id"], "owner")
    assert len(saved["requirements"]) == 1 and saved["requirements"][0]["content"] == payload["content"]
    assert saved["events"][-1]["detail"]["request_key"] == executions[0]
