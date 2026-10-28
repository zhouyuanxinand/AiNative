"""Shared project actors and restartable SQLite scenario builders."""
import hashlib
import uuid
import pytest
from src.service.rd_platform.store import RdError, RdStore

OWNER = {"user_id": "owner", "display_name": "项目负责人"}
ENGINEER = {"user_id": "engineer", "display_name": "工程师"}
REVIEWER = {"user_id": "reviewer", "display_name": "审核人"}


@pytest.fixture
def store(tmp_path):
    return RdStore(tmp_path / "rd.sqlite3", tmp_path / "artifacts")


def command(store, detail, action, payload=None, actor=OWNER, key=None):
    return store.execute(detail["project"]["id"], actor, action, payload or {},
                         detail["project"]["version"], key or uuid.uuid4().hex)


def project(store):
    return store.create_project(OWNER, {"name": "连接器研发", "customer": "客户A", "product": "产品A"}, uuid.uuid4().hex)


def prepared(store):
    d = project(store)
    for actor, role in ((ENGINEER, "engineer"), (REVIEWER, "reviewer")):
        d = command(store, d, "add_member", {**actor, "role": role})
    d = command(store, d, "save_requirement", {"title": "耐温", "content": "满足温度要求", "source": "客户技术协议第3条", "acceptance": "试验通过", "clarification": "resolved", "required": True})
    d = command(store, d, "confirm_baseline")
    d = command(store, d, "create_task", {"title": "研制任务书", "description": "编制", "assignee_id": "engineer", "reviewer_id": "reviewer"})
    return command(store, d, "start_task", {"task_id": d["tasks"][0]["id"]}, ENGINEER)


def capture(store, d, quality="passed", jid=None):
    pid, tid = d["project"]["id"], d["tasks"][0]["id"]
    jid = jid or uuid.uuid4().hex
    store.bind_generation(pid, tid, ENGINEER, jid, {"documents": ["customer-v1"], "confirmed": True})
    d = store.detail(pid, "engineer")
    path = store.artifact_root / f"{jid}.docx"
    path.write_bytes(b"fixed reviewed document")
    payload = {"jid": jid, "source_revision_id": "revision-1", "filename": "taskbook.docx", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "file_ref": str(path), "quality_status": quality}
    payload["quality_evidence"] = {"revision_id": "revision-1", "sha256": payload["sha256"], "checks": {"status": quality, "revision_id": "revision-1", "sha256": payload["sha256"], "scope": "revision_deterministic", "checked_at": "2026-10-28T00:00:00Z", "findings": []}, "rules_fingerprint": "controlled-rules-v1"}
    return store.register_artifact(pid, tid, ENGINEER, payload, d["project"]["version"], uuid.uuid4().hex)


def raises(status, fn):
    with pytest.raises(RdError) as caught:
        fn()
    assert caught.value.status == status
