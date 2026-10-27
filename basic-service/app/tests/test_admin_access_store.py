from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from src.common import admin_access_store
from src.common.admin_access_store import (
    AdminAccessStore,
    AdminAlreadyExistsError,
    OwnerRemovalError,
    get_admin_access_store,
    normalize_admin_username,
)

CONTEXT = {
    "app_id": "9086",
    "base_url": "https://sv.dcsmartvision.com",
    "origin": "http://127.0.0.1:18131",
}


def session(store, username="wangxue", **kwargs):
    return store.create_session(
        username=username,
        userid="verified-user-id",
        display_name="已验证姓名",
        **{**CONTEXT, **kwargs},
    )


def test_bootstrap_owner_and_members_survive_reopen(tmp_path):
    path = tmp_path / "runtime" / "admin.sqlite3"
    store = AdminAccessStore(path)
    initial = store.list_admins()
    assert len(initial) == 1
    assert initial[0]["username"] == "wangxue"
    assert initial[0]["is_owner"] is True
    assert initial[0]["created_by"] == "system"
    new_admin = store.add_admin(" Alice.Name ", actor=" WANGXUE ")
    assert new_admin["username"] == "alice.name"
    assert new_admin["created_by"] == "wangxue"
    assert new_admin["is_owner"] is False
    reopened = AdminAccessStore(path)
    assert reopened.list_admins() == [initial[0], new_admin]
    assert reopened.is_admin("ALICE.NAME")
    assert not reopened.is_admin("outsider")


def test_only_owner_may_change_list_and_owner_cannot_be_deleted(tmp_path):
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    store.add_admin("alice", actor="wangxue")
    with pytest.raises(PermissionError):
        store.add_admin("bob", actor="alice")
    with pytest.raises(PermissionError):
        store.remove_admin("alice", actor="alice")
    with pytest.raises(OwnerRemovalError):
        store.remove_admin(" WANGXUE ", actor="wangxue")
    with pytest.raises(AdminAlreadyExistsError):
        store.add_admin("ALICE", actor="wangxue")
    with pytest.raises(AdminAlreadyExistsError):
        store.add_admin("wangxue", actor="wangxue")
    assert store.remove_admin("absent", actor="wangxue") is False
    assert [item["username"] for item in store.list_admins()] == ["wangxue", "alice"]


@pytest.mark.parametrize(
    "username",
    ["", " ", "a b", "a\nb", "张三", "wangxue'--", "ｗangxue", "Kate", "a" * 129, None],
)
def test_invalid_or_confusable_username_cannot_match_owner(tmp_path, username):
    with pytest.raises(ValueError):
        normalize_admin_username(username)
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    assert not store.is_admin(username)


def test_session_only_issued_after_membership_and_never_persists_raw_token(tmp_path):
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    with pytest.raises(PermissionError):
        session(store, "outsider")
    token = session(store)
    user = store.lookup_session(token, **CONTEXT)
    assert user["username"] == "wangxue"
    assert user["userid"] == "verified-user-id"
    assert user["display_name"] == "已验证姓名"
    assert user["is_owner"] is True
    assert "token" not in user
    with sqlite3.connect(store.path) as connection:
        persisted = "\n".join(connection.iterdump())
    assert token not in persisted
    assert hashlib.sha256(token.encode()).hexdigest() in persisted
    reopened = AdminAccessStore(store.path)
    assert reopened.lookup_session(token, **CONTEXT) == user


@pytest.mark.parametrize(
    "changed",
    [
        {"app_id": "127"},
        {"base_url": "http://172.23.255.36"},
        {"origin": "http://127.0.0.1:18130"},
    ],
)
def test_session_is_bound_to_verified_platform_and_admin_origin(tmp_path, changed):
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    token = session(store)
    assert store.lookup_session(token, **{**CONTEXT, **changed}) is None
    assert store.lookup_session(token, **CONTEXT) is not None
    assert store.lookup_session("wangxue", **CONTEXT) is None
    assert store.lookup_session("x" * 43, **CONTEXT) is None


def test_expiration_and_logout_revoke_access(tmp_path, monkeypatch):
    now = [1_800_000_000.0]
    monkeypatch.setattr(admin_access_store.time, "time", lambda: now[0])
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    expiring = session(store, ttl_seconds=10)
    second = session(store)
    assert expiring != second
    assert store.lookup_session(expiring, **CONTEXT)
    now[0] += 10
    assert store.lookup_session(expiring, **CONTEXT) is None
    assert store.lookup_session(second, **CONTEXT)
    assert store.revoke_session(second) is True
    assert store.revoke_session(second) is False
    assert store.lookup_session(second, **CONTEXT) is None
    session(store)
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute("SELECT count(*) FROM admin_sessions").fetchone()[0] == 1
        )


def test_removal_revokes_all_existing_sessions_even_after_readdition(tmp_path):
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    store.add_admin("alice", actor="wangxue")
    tokens = [session(store, "alice") for _ in range(2)]
    owner_token = session(store)
    assert store.remove_admin("alice", actor="wangxue") is True
    store.add_admin("alice", actor="wangxue")
    assert all(store.lookup_session(token, **CONTEXT) is None for token in tokens)
    assert store.lookup_session(owner_token, **CONTEXT) is not None
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute("SELECT count(*) FROM admin_sessions").fetchone()[0] == 1
        )


def test_concurrent_duplicate_add_has_one_winner_and_sessions_remain_distinct(tmp_path):
    store = AdminAccessStore(tmp_path / "admin.sqlite3")

    def add_same_user(_):
        try:
            return store.add_admin("alice", actor="wangxue")
        except AdminAlreadyExistsError:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        additions = list(executor.map(add_same_user, range(12)))
        tokens = list(executor.map(lambda _: session(store, "alice"), range(12)))
    assert sum(item is not None for item in additions) == 1
    assert len(set(tokens)) == 12
    assert all(store.lookup_session(token, **CONTEXT) for token in tokens)
    store.remove_admin("alice", actor="wangxue")
    assert all(store.lookup_session(token, **CONTEXT) is None for token in tokens)


def test_removal_cannot_race_session_creation_to_leave_an_authorized_session(tmp_path):
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    store.add_admin("alice", actor="wangxue")
    barrier = Barrier(8)

    def issue_or_remove(index):
        barrier.wait()
        if index == 0:
            store.remove_admin("alice", actor="wangxue")
            return None
        try:
            return session(store, "alice")
        except PermissionError:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        tokens = list(executor.map(issue_or_remove, range(8)))
    assert not store.is_admin("alice")
    assert all(
        store.lookup_session(token, **CONTEXT) is None for token in tokens if token
    )
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute("SELECT count(*) FROM admin_sessions").fetchone()[0] == 0
        )


@pytest.mark.parametrize(
    "changed", [{"app_id": None}, {"app_id": True}, {"base_url": None}, {"origin": ""}]
)
def test_missing_platform_context_cannot_issue_session(tmp_path, changed):
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    with pytest.raises(ValueError):
        session(store, **changed)


@pytest.mark.parametrize("ttl", [0, -1, True, 1.5])
def test_invalid_session_duration_is_rejected(tmp_path, ttl):
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    with pytest.raises(ValueError):
        session(store, ttl_seconds=ttl)


def test_database_path_is_configurable_without_using_service_cookie_store(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("JTB_ADMIN_ACCESS_DB", raising=False)
    assert (
        get_admin_access_store(tmp_path / "runtime").path
        == tmp_path / "runtime" / "admin_access.sqlite3"
    )
    monkeypatch.setenv(
        "JTB_ADMIN_ACCESS_DB", str(tmp_path / "shared" / "access.sqlite3")
    )
    assert (
        get_admin_access_store(tmp_path / "runtime").path
        == tmp_path / "shared" / "access.sqlite3"
    )


def test_login_state_is_persistent_hashed_and_consumable_only_once(tmp_path):
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    state = store.begin_login(**CONTEXT)
    with sqlite3.connect(store.path) as connection:
        persisted = "\n".join(connection.iterdump())
    assert state not in persisted
    assert hashlib.sha256(state.encode()).hexdigest() in persisted
    reopened = AdminAccessStore(store.path)
    assert reopened.consume_login(state, **CONTEXT) is True
    assert store.consume_login(state, **CONTEXT) is False
    assert store.consume_login("unissued-state", **CONTEXT) is False
    assert store.consume_login("x" * 43, **CONTEXT) is False


@pytest.mark.parametrize(
    "changed",
    [
        {"app_id": "127"},
        {"base_url": "http://172.23.255.36"},
        {"origin": "http://127.0.0.1:18130"},
    ],
)
def test_login_state_is_bound_to_the_requested_application_and_origin(
    tmp_path, changed
):
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    state = store.begin_login(**CONTEXT)
    assert store.consume_login(state, **{**CONTEXT, **changed}) is False
    assert store.consume_login(state, **CONTEXT) is True


def test_expired_login_state_is_rejected_and_next_login_prunes_it(
    tmp_path, monkeypatch
):
    now = [1_800_000_000.0]
    monkeypatch.setattr(admin_access_store.time, "time", lambda: now[0])
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    state = store.begin_login(**CONTEXT, ttl_seconds=10)
    now[0] += 10
    assert store.consume_login(state, **CONTEXT) is False
    new_state = store.begin_login(**CONTEXT)
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute("SELECT count(*) FROM admin_login_states").fetchone()[0]
            == 1
        )
    assert store.consume_login(new_state, **CONTEXT) is True


def test_simultaneous_callbacks_can_consume_a_login_state_only_once(tmp_path):
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    state = store.begin_login(**CONTEXT)
    other_connection = AdminAccessStore(store.path)
    barrier = Barrier(2)

    def callback(index):
        barrier.wait()
        current_store = store if index == 0 else other_connection
        return current_store.consume_login(state, **CONTEXT)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(callback, range(2)))
    assert sorted(results) == [False, True]


@pytest.mark.parametrize("ttl", [0, -1, True, 1.5])
def test_invalid_login_state_duration_is_rejected(tmp_path, ttl):
    store = AdminAccessStore(tmp_path / "admin.sqlite3")
    with pytest.raises(ValueError):
        store.begin_login(**CONTEXT, ttl_seconds=ttl)
