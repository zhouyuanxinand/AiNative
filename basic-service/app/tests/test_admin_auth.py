"""Admin privileges originate in an OA-verified account and a current allowlist."""
from __future__ import annotations

import sqlite3
from dataclasses import replace
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient

from src.common.admin_access_store import AdminAccessStore
from src.common.admin_auth import ADMIN_COOKIE, STATE_COOKIE
from src.common.platform_auth import AuthSettings, PlatformUnavailableError
from src.feedback_main import create_app
from src.utils.config_loader import get_config

ORIGIN = "http://127.0.0.1:18131"
WRITE_HEADERS = {"X-Admin-Action": "1", "Origin": ORIGIN}


@pytest.fixture
def admin(tmp_path, monkeypatch):
    from jonhon_taskbook.feedback_store import FeedbackStore

    from src.controller import feedback_controller

    monkeypatch.delenv("JTB_ADMIN_PUBLIC_URL", raising=False)
    monkeypatch.setenv("JTB_AUTH_SETTINGS_DB", str(tmp_path / "auth-settings.sqlite3"))
    monkeypatch.setenv("JTB_REQUEST_LOG_DB", str(tmp_path / "requests.sqlite3"))
    monkeypatch.setattr(feedback_controller, "get_feedback_store", lambda: FeedbackStore(tmp_path / "feedback.sqlite3"))
    upstream = {"username": "wangxue", "display_name": "王工", "calls": [], "denied": False, "error": False, "extra": {}}

    async def verify(userid, token, appid):
        upstream["calls"].append((userid, token, appid))
        if upstream["error"]:
            raise PlatformUnavailableError()
        if upstream["denied"]:
            return None
        account = {"username": upstream["username"]} if upstream["username"] is not None else {}
        return {"code": 0, "data": {**account, "sn": upstream["display_name"], **upstream["extra"]}}

    settings = AuthSettings(enabled=False, app_id=127, platform_base_url="http://platform.internal", public_url="http://main.example:9999")
    store = AdminAccessStore(tmp_path / "admins.sqlite3")
    config = replace(get_config(), logs_dir=tmp_path / "logs", output_dir=tmp_path / "outputs")
    application = create_app(config, auth_settings=settings, admin_store=store, verifier=verify)
    return application, upstream, store


def oa_login(client, *, userid="oa-id-1", token="test-oa-token", changes=None):
    login = client.get("/admin/auth/login", follow_redirects=False)
    assert login.status_code == 302
    callback_url = parse_qs(urlsplit(login.headers["location"]).query)["redirect_uri"][0]
    parts = urlsplit(callback_url)
    values = {key: value[0] for key, value in parse_qs(parts.query).items()}
    values.update({"userid": userid, "token": token, "appid": "127", **(changes or {})})
    return client.get(parts.path + "?" + urlencode(values), follow_redirects=False)


@pytest.mark.parametrize("path", [
    "/api/admin/session", "/api/admin/members", "/api/feedback-admin", "/api/logs/latest",
    "/api/logs/requests", "/api/settings/auth", "/docs", "/openapi.json",
])
def test_anonymous_cannot_read_management_data_even_with_forged_main_cookies(admin, path):
    app, upstream, _ = admin
    with TestClient(app, base_url=ORIGIN) as client:
        for key, value in {"jtb_sv_appid": "127", "jtb_sv_userid": "wangxue", "jtb_sv_token": "fake", "jtb_sv_username": "wangxue", ADMIN_COOKIE: "fake-admin-session"}.items():
            client.cookies.set(key, value)
        response = client.get(path, headers={"X-Log-Viewer": "1", "X-User-Name": "wangxue"})
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"
    assert response.headers["cache-control"] == "no-store"
    assert upstream["calls"] == []


def test_owner_login_uses_admin_published_port_and_never_the_main_fixed_origin(admin):
    app, upstream, _ = admin
    assert app.state.admin_auth_settings.enabled
    with TestClient(app, base_url=ORIGIN) as client:
        login = client.get("/admin/auth/login", follow_redirects=False)
        query = parse_qs(urlsplit(login.headers["location"]).query)
        assert query["app_id"] == ["127"]
        assert query["redirect_uri"][0].startswith(ORIGIN + "/admin/auth/callback?")
        assert "HttpOnly" in login.headers["set-cookie"]
        response = oa_login(client)
        assert response.status_code == 303 and response.headers["location"] == "/admin"
        assert STATE_COOKIE not in client.cookies
        assert "test-oa-token" not in response.headers["set-cookie"]
        info = client.get("/api/admin/session")
        assert info.status_code == 200
        assert info.json() == {"authenticated": True, "user": {"username": "wangxue", "userid": "oa-id-1", "display_name": "王工"}, "can_manage_admins": True}
        assert client.get("/api/feedback-admin").status_code == 200
    assert upstream["calls"] == [("oa-id-1", "test-oa-token", 127)]


@pytest.mark.parametrize("mode", ["wrong_token", "display_name_only", "conflicting_userid", "injected_query"])
def test_unverified_or_nonmember_cannot_claim_owner(admin, mode):
    app, upstream, _ = admin
    upstream["display_name"] = "wangxue"
    upstream["username"] = "ordinary-user"
    userid = "ordinary-id"
    if mode == "wrong_token":
        upstream["denied"] = True
    elif mode == "display_name_only":
        upstream["username"] = None
    elif mode == "conflicting_userid":
        userid = "wangxue"
    with TestClient(app, base_url=ORIGIN) as client:
        response = oa_login(client, userid=userid, changes={"username": "wangxue", "sn": "wangxue"})
        assert response.status_code == 303
        assert response.headers["location"].startswith("/admin/auth/error?")
        assert client.get(response.headers["location"]).status_code == 403
        assert ADMIN_COOKIE not in client.cookies
        assert client.get("/api/admin/members").status_code == 401


def test_verified_account_userid_is_used_only_without_explicit_login_name(admin):
    app, upstream, _ = admin
    upstream["username"] = None
    with TestClient(app, base_url=ORIGIN) as client:
        assert oa_login(client, userid="wangxue").headers["location"] == "/admin"
        assert client.get("/api/admin/session").json()["user"]["username"] == "wangxue"


@pytest.mark.parametrize("changes", [{"state": "incorrect"}, {"appid": "9086"}, {"token": ""}])
def test_invalid_callback_never_calls_oa_and_clears_credentials_from_redirect(admin, changes):
    app, upstream, _ = admin
    with TestClient(app, base_url=ORIGIN) as client:
        response = oa_login(client, changes=changes)
        assert response.status_code == 303
        assert "token" not in response.headers["location"] and "userid" not in response.headers["location"]
        assert STATE_COOKIE not in client.cookies and ADMIN_COOKIE not in client.cookies
        assert client.get(response.headers["location"]).status_code == 400
    assert upstream["calls"] == []


def test_non_ascii_state_cookie_is_rejected_without_server_error(admin):
    app, upstream, _ = admin
    with TestClient(app, base_url=ORIGIN) as client:
        login = client.get("/admin/auth/login", follow_redirects=False)
        callback = parse_qs(urlsplit(login.headers["location"]).query)["redirect_uri"][0]
        response = client.get(
            callback + "&userid=owner-id&token=test-token&appid=127",
            headers={"Cookie": STATE_COOKIE + '="' + r"\344" * 43 + '"'},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].endswith("reason=state")
        assert client.get("/api/admin/session").status_code == 401
    assert upstream["calls"] == []


def test_outage_fails_closed_and_callback_cannot_be_replayed(admin):
    app, upstream, _ = admin
    with TestClient(app, base_url=ORIGIN) as client:
        upstream["error"] = True
        failure = oa_login(client)
        assert client.get(failure.headers["location"]).status_code == 503
        assert client.get("/api/admin/session").status_code == 401
        upstream["error"] = False
        login = client.get("/admin/auth/login", follow_redirects=False)
        callback = parse_qs(urlsplit(login.headers["location"]).query)["redirect_uri"][0] + "&userid=owner-id&token=test-token&appid=127"
        state = client.cookies.get(STATE_COOKIE)
        assert client.get(callback, follow_redirects=False).headers["location"] == "/admin"
        # Even a client that restores the old state cookie cannot replay it.
        client.cookies.set(STATE_COOKIE, state, path="/admin/auth")
        assert client.get(callback, follow_redirects=False).headers["location"].endswith("reason=state")


def test_owner_can_grant_and_revoke_other_oa_users_without_granting_owner_rights(admin):
    app, upstream, store = admin
    with TestClient(app, base_url=ORIGIN) as owner, TestClient(app, base_url=ORIGIN) as other:
        oa_login(owner)
        response = owner.post("/api/admin/members", json={"username": " LiGong "}, headers=WRITE_HEADERS)
        assert response.status_code == 201 and response.json()["member"]["username"] == "ligong"
        assert owner.post("/api/admin/members", json={"username": "LIGONG"}, headers=WRITE_HEADERS).status_code == 409
        upstream["username"] = "ligong"
        assert oa_login(other).headers["location"] == "/admin"
        assert not other.get("/api/admin/session").json()["can_manage_admins"]
        assert other.get("/api/logs/requests", headers={"X-Log-Viewer": "1"}).status_code == 200
        assert other.post("/api/admin/members", json={"username": "third"}, headers=WRITE_HEADERS).status_code == 403
        assert other.delete("/api/admin/members/wangxue", headers=WRITE_HEADERS).status_code == 403
        assert other.put("/api/settings/auth", json={}, headers=WRITE_HEADERS).status_code == 403
        assert not other.get("/api/settings/auth").json()["can_edit"]
        assert owner.get("/api/settings/auth").json()["can_edit"]
        assert owner.delete("/api/admin/members/wangxue", headers=WRITE_HEADERS).status_code == 409
        assert owner.delete("/api/admin/members/ligong", headers=WRITE_HEADERS).status_code == 200
        assert other.get("/api/logs/requests", headers={"X-Log-Viewer": "1"}).status_code == 401
        assert [item["username"] for item in store.list_admins()] == ["wangxue"]


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Action": "1", "Origin": "http://evil.example"}, {"X-Admin-Action": "1", "Sec-Fetch-Site": "cross-site"}])
def test_membership_and_logout_reject_cross_site_or_missing_action_header(admin, headers):
    app, _, store = admin
    with TestClient(app, base_url=ORIGIN) as client:
        oa_login(client)
        assert client.post("/api/admin/members", json={"username": "someone"}, headers=headers).status_code == 403
        assert client.post("/api/admin/logout", headers=headers).status_code == 403
        assert client.get("/api/admin/session").status_code == 200
        assert len(store.list_admins()) == 1


def test_logout_revokes_cookie_and_other_ports_cannot_reuse_it(admin):
    app, _, _ = admin
    with TestClient(app, base_url=ORIGIN) as client:
        oa_login(client)
        cookie = client.cookies.get(ADMIN_COOKIE)
        with TestClient(app, base_url="http://127.0.0.1:18132") as other:
            other.cookies.set(ADMIN_COOKIE, cookie)
            assert other.get("/api/admin/session").status_code == 401
        assert client.post("/api/admin/logout", headers=WRITE_HEADERS).status_code == 200
        client.cookies.set(ADMIN_COOKIE, cookie)
        assert client.get("/api/admin/session").status_code == 401


def test_session_database_failure_does_not_open_access(admin, monkeypatch):
    app, _, store = admin
    with TestClient(app, base_url=ORIGIN) as client:
        oa_login(client)

        def unavailable(*args, **kwargs):
            raise sqlite3.OperationalError("synthetic storage error")

        monkeypatch.setattr(store, "lookup_session", unavailable)
        response = client.get("/api/feedback-admin")
        assert response.status_code == 503
        assert "synthetic storage error" not in response.text


def test_public_main_has_no_log_api_bypass(tmp_path, monkeypatch):
    from src.main import create_app as create_main

    monkeypatch.setenv("JTB_AUTH_SETTINGS_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("JTB_AUTH_ENABLED", "false")
    monkeypatch.setenv("JTB_REQUEST_LOG_DB", str(tmp_path / "logs.sqlite3"))
    app = create_main(replace(get_config(), logs_dir=tmp_path / "logs"))
    with TestClient(app) as client:
        assert client.get("/api/logs/requests", headers={"X-Log-Viewer": "1"}).status_code == 404
        assert client.get("/api/logs/latest", headers={"X-Log-Viewer": "1"}).status_code == 404
        assert client.get("/log").status_code == 403
        assert not client.get("/api/settings/auth").json()["can_edit"]
        assert client.put("/api/settings/auth", json={}, headers={"X-Credential-Settings": "1", "Origin": "http://testserver"}).status_code == 403
