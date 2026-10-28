"""Feedback preserves the verified submitter independently of editable display text."""
from __future__ import annotations

import importlib
import json
import sqlite3
import uuid
from types import MappingProxyType, SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def fields(**changes):
    return {"jid": "123456789a", "rating": "good", "comment": "参数完整", **changes}


def verified_user(**changes):
    return MappingProxyType({
        "userid": "employee-007", "name": "张工程师", "display_name": "张工程师",
        "source": "smartvision", "verified": True, **changes,
    })


@pytest.fixture
def feedback(tmp_path, monkeypatch):
    controller = importlib.import_module("src.controller.feedback_controller")
    taskbook = importlib.import_module("src.controller.taskbook_controller")
    store_module = importlib.import_module("jonhon_taskbook.feedback_store")
    store = store_module.FeedbackStore(tmp_path / "feedback.sqlite3")
    monkeypatch.setattr(controller, "get_feedback_store", lambda: store)
    runtime = taskbook._RuntimeState()
    runtime.output_dir = tmp_path / "outputs"
    runtime.output_dir.mkdir()
    runtime.jobs["123456789a"] = {"status": "done", "result": {}}
    monkeypatch.setattr(taskbook, "_STATE", runtime)
    trusted = {"enabled": True, "user": verified_user()}
    app = FastAPI()
    app.include_router(controller.public_router)
    app.include_router(controller.admin_router)

    @app.middleware("http")
    async def trusted_identity(request, call_next):
        request.state.auth_settings = SimpleNamespace(enabled=trusted["enabled"])
        request.state.current_user = trusted["user"]
        return await call_next(request)

    with TestClient(app) as client:
        yield client, store, trusted


@pytest.mark.parametrize("claim", [{}, {"username": "冒名用户"}, {"username": {"name": "冒名用户"}}])
def test_public_feedback_uses_verified_identity_instead_of_client_username(feedback, claim):
    client, store, trusted = feedback
    trusted["user"] = verified_user(token="synthetic-secret", appid=137, raw_cookie="synthetic-cookie")
    response = client.post("/api/feedback", json=fields(**claim), headers={"X-User": "admin", "X-User-Name": "forged"})
    assert response.status_code == 200, response.text
    record = response.json()["record"]
    assert record["username"] == "张工程师"
    assert record["identity"] == {"userid": "employee-007", "name": "张工程师", "source": "smartvision", "verified": True}
    assert store.get(record["id"]) == record
    with sqlite3.connect(store.path) as con:
        saved = con.execute("SELECT identity, request_payload FROM feedback").fetchone()
    assert "synthetic-secret" not in "".join(saved)
    assert "synthetic-cookie" not in "".join(saved)
    assert "appid" not in "".join(saved)


@pytest.mark.parametrize("name,display_name,expected", [
    ("原始姓名", "展示姓名", "展示姓名"), ("原始姓名", "", "原始姓名"), ("", "", "employee-007"),
])
def test_display_name_fallback_preserves_original_identity_name(feedback, name, display_name, expected):
    client, _, trusted = feedback
    trusted["user"] = verified_user(name=name, display_name=display_name)
    response = client.post("/api/feedback", json=fields())
    assert response.status_code == 200, response.text
    record = response.json()["record"]
    assert record["username"] == expected
    assert record["identity"]["name"] == (name or expected)


@pytest.mark.parametrize("user", [None, {}, verified_user(verified=False), verified_user(verified="true")])
def test_enabled_auth_does_not_accept_a_manual_name_without_verified_identity(feedback, user):
    client, store, trusted = feedback
    trusted["user"] = user
    response = client.post("/api/feedback", json=fields(username="手填绕过"), headers={"X-User": "admin"})
    assert response.status_code == 401
    assert response.json()["auth_required"] is True
    assert response.json()["login_url"] == "/auth/login"
    assert "error" in response.json()
    assert store.search()["total"] == 0


def test_local_feedback_keeps_manual_names_and_marks_them_unverified(feedback):
    client, _, trusted = feedback
    trusted["enabled"] = False
    response = client.post("/api/feedback", json=fields(username=" 本地张工 "))
    assert response.status_code == 200, response.text
    record = response.json()["record"]
    assert record["username"] == "本地张工"
    assert record["identity"] == {"userid": "", "name": "本地张工", "source": "manual", "verified": False}
    assert client.post("/api/feedback", json=fields()).status_code == 400


def test_admin_can_record_a_manual_report_without_a_logged_in_submitter(feedback):
    client, _, trusted = feedback
    trusted["user"] = None
    response = client.post("/api/feedback-admin", json=fields(username="线下反馈用户", status="in_progress"))
    assert response.status_code == 200, response.text
    record = response.json()["record"]
    assert record["username"] == "线下反馈用户"
    assert record["identity"] == {"userid": "", "name": "线下反馈用户", "source": "manual", "verified": False}


@pytest.mark.parametrize("endpoint", ["/api/feedback", "/api/feedback-admin"])
def test_client_cannot_supply_server_owned_identity(feedback, endpoint):
    client, store, _ = feedback
    response = client.post(endpoint, json=fields(username="张工", identity={
        "userid": "admin", "name": "管理员", "source": "smartvision", "verified": True,
    }))
    assert response.status_code == 400
    assert store.search()["total"] == 0


def test_admin_edit_cannot_replace_stable_identity_or_its_original_name(feedback):
    client, store, _ = feedback
    response = client.post("/api/feedback", json=fields())
    assert response.status_code == 200, response.text
    original = response.json()["record"]
    endpoint = f'/api/feedback-admin/{original["id"]}'
    changed = client.put(endpoint, json={"username": "更正显示文本", "comment": "已安排核查", "expected_version": 1})
    assert changed.status_code == 200, changed.text
    assert changed.json()["record"]["identity"] == original["identity"]
    for q in ("employee-007", "张工程师"):
        result = client.get("/api/feedback-admin", params={"q": q}).json()
        assert result["total"] == 1
        assert result["items"][0]["id"] == original["id"]
    rejected = client.put(endpoint, json={"identity": {"userid": "other"}, "expected_version": 2})
    assert rejected.status_code == 400
    reopened = type(store)(store.path)
    assert reopened.get(original["id"])["identity"] == original["identity"]


def test_identical_display_names_cannot_share_another_accounts_idempotency_key(feedback):
    client, store, trusted = feedback
    payload = fields(request_id=str(uuid.uuid4()))
    first = client.post("/api/feedback", json=payload)
    assert first.status_code == 200, first.text
    trusted["user"] = verified_user(userid="employee-008")
    second = client.post("/api/feedback", json=payload)
    assert second.status_code == 409
    assert store.search()["total"] == 1
    trusted["user"] = verified_user()
    assert client.post("/api/feedback", json=payload).json()["record"]["id"] == first.json()["record"]["id"]


def test_same_account_retry_survives_name_changes_and_retains_original_identity(feedback):
    client, store, trusted = feedback
    payload = fields(request_id=str(uuid.uuid4()))
    first = client.post("/api/feedback", json=payload)
    assert first.status_code == 200, first.text
    record = first.json()["record"]
    store.update(record["id"], {"username": "管理员更正文本", "expected_version": 1})
    trusted["user"] = verified_user(name="平台更新姓名", display_name="平台更新姓名")
    retry = client.post("/api/feedback", json=payload)
    assert retry.status_code == 200, retry.text
    assert retry.json()["record"]["id"] == record["id"]
    assert retry.json()["record"]["username"] == "管理员更正文本"
    assert retry.json()["record"]["identity"] == record["identity"]
    assert store.search()["total"] == 1


def test_internal_identity_allowlist_drops_tokens_and_binds_idempotency_to_identity(tmp_path):
    module = importlib.import_module("jonhon_taskbook.feedback_store")
    store = module.FeedbackStore(tmp_path / "feedback.sqlite3")
    identity = {"userid": "employee-007", "name": "张工程师", "source": "smartvision", "verified": True,
                "token": "synthetic-secret", "raw_cookie": "synthetic-cookie"}
    payload = fields(username="张工程师", request_id=str(uuid.uuid4()))
    record = store.create(payload, snapshot={"jid": "123456789a"}, identity=identity)
    assert record["identity"] == {"userid": "employee-007", "name": "张工程师", "source": "smartvision", "verified": True}
    for changes in ({"userid": "employee-008"}, {"source": "another-platform"}, {"verified": False}):
        with pytest.raises(module.FeedbackConflictError):
            store.create(payload, snapshot={"jid": "123456789a"}, identity={**identity, **changes})


def test_old_database_migrates_without_inventing_identity_or_breaking_manual_retries(tmp_path):
    module = importlib.import_module("jonhon_taskbook.feedback_store")
    path = tmp_path / "old-feedback.sqlite3"
    request_id = "7a5687bc-b364-4a11-9ec6-965ece76552d"
    legacy_request = json.dumps({
        "jid": "123456789a", "username": "旧用户", "rating": "good", "comment": "旧反馈",
        "status": "open", "handling_note": "", "request_id": request_id,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT, version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            username TEXT NOT NULL, rating TEXT NOT NULL, comment TEXT NOT NULL,
            status TEXT NOT NULL, handling_note TEXT NOT NULL,
            snapshot TEXT NOT NULL, search_text TEXT NOT NULL,
            request_id TEXT UNIQUE, request_payload TEXT NOT NULL, deleted_at TEXT
        )""")
        con.execute("""INSERT INTO feedback
            (created_at,updated_at,username,rating,comment,status,handling_note,snapshot,search_text,request_id,request_payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                "2026-10-15T00:00:00+00:00", "2026-10-15T00:00:00+00:00", "旧用户", "good", "旧反馈", "open", "",
                '{"jid":"123456789a"}', "旧用户\n旧反馈", request_id, legacy_request,
            ))
    store = module.FeedbackStore(path)
    assert store.get(1)["identity"] == {}
    retry = store.create(fields(username="旧用户", comment="旧反馈", request_id=request_id), snapshot={"jid": "123456789a"})
    assert retry["id"] == 1 and retry["identity"] == {}
    edited = store.update(1, {"comment": "补充核查", "expected_version": 1})
    assert edited["identity"] == {}
    new = store.create(fields(username="新用户"), snapshot={"jid": "123456789a"})
    assert new["identity"] == {"userid": "", "name": "新用户", "source": "manual", "verified": False}
    assert module.FeedbackStore(path).search()["total"] == 2
