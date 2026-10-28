"""Reference-compatible identity and local-session logout endpoints."""
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.platform_auth import AuthSettings, PlatformAuthMiddleware
from src.controller.auth_controller import router


@pytest.fixture
def session_client():
    calls = []

    async def verify(userid, token, appid):
        calls.append((userid, appid))
        return {"code": 0, "data": {"sn": "张工程师"}}

    app = FastAPI()
    app.include_router(router)
    app.add_middleware(PlatformAuthMiddleware, settings=AuthSettings(
        enabled=True, app_id=9086, platform_base_url="https://sv.dcsmartvision.com",
    ), verifier=verify)
    with TestClient(app, base_url="http://127.0.0.1:18130", follow_redirects=False) as client:
        yield client, calls


def test_reference_identity_endpoint_and_existing_probe_share_the_same_session(session_client):
    client, calls = session_client
    callback = client.get("/", params={"userid": "employee-007", "token": "synthetic-token", "appid": "9086"})
    assert callback.status_code == 307
    identity = client.get("/api/auth/me")
    assert identity.status_code == 200
    assert identity.json() == {
        "success": True, "userid": "employee-007", "username": "张工程师",
        "is_admin": False, "is_dev": False,
    }
    assert identity.headers["cache-control"] == "no-store"
    assert "synthetic-token" not in identity.text
    existing = client.get("/api/current-user").json()
    assert existing["authenticated"] is True
    assert existing["user"]["userid"] == identity.json()["userid"]
    assert existing["user"]["display_name"] == identity.json()["username"]
    assert calls == [("employee-007", 9086)]


def test_reference_identity_endpoint_requires_login(session_client):
    client, _ = session_client
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["success"] is False


def test_logout_clears_only_taskbook_session_and_is_repeatable(session_client):
    client, calls = session_client
    for name, value in {
        "jtb_sv_appid": "9086", "jtb_sv_userid": "employee-007",
        "jtb_sv_token": "synthetic-token", "jtb_sv_username": quote("张工程师"),
        "sv_appid": "9192", "sv_token": "old-token", "sv_userid": "old-user",
        "sv_username": "old-name", "sv_login_state": "old-state",
        "p02_sv_token": "other-application-token",
    }.items():
        client.cookies.set(name, value, domain="127.0.0.1", path="/")
    for _ in range(2):
        response = client.post("/api/system/logout")
        assert response.status_code == 200
        assert response.json() == {"success": True}
        assert response.headers["cache-control"] == "no-store"
        assert not any(cookie.name.startswith("jtb_sv_") or cookie.name.startswith("sv_") for cookie in client.cookies.jar)
        assert client.cookies.get("p02_sv_token") == "other-application-token"
    assert calls == []
    assert client.get("/api/current-user").json()["authenticated"] is False
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/system/logout").status_code != 200


def test_logged_out_page_remains_public_and_has_explicit_reentry_link(session_client):
    client, calls = session_client
    response = client.get("/logged-out")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "已退出本应用" in response.text
    assert 'href="/"' in response.text
    assert 'http-equiv="refresh"' not in response.text.lower()
    assert calls == []


def test_logout_does_not_depend_on_callback_host_configuration(session_client):
    client, calls = session_client
    response = client.post("http://unconfigured-host.example/api/system/logout")
    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert calls == []


def test_local_mode_does_not_invent_an_oa_identity():
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(PlatformAuthMiddleware, settings=AuthSettings(enabled=False))
    with TestClient(app) as client:
        assert client.get("/api/current-user").json()["auth_enabled"] is False
        assert client.get("/api/auth/me").status_code == 401
        assert client.post("/api/system/logout").json() == {"success": True}
        assert client.get("/logged-out").status_code == 200
