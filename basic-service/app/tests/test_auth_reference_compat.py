"""Exercise the production reference login flow without a live platform."""
import asyncio
from urllib.parse import parse_qs, quote, urlsplit

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.common import platform_auth as auth
from src.controller.auth_controller import router


@pytest.fixture
def reference_client():
    calls = []
    upstream = {"payload": {"code": 0, "data": {"sn": "平台姓名", "name": "备用姓名"}}, "error": None}

    async def verifier(userid, token, appid):
        calls.append((userid, token, appid))
        if upstream["error"]:
            raise upstream["error"]
        return upstream["payload"]

    app = FastAPI()
    settings = auth.AuthSettings(enabled=True, app_id=127, platform_base_url="http://172.23.255.36")
    app.state.auth_settings = settings
    app.include_router(router)

    @app.get("/")
    @app.get("/api/protected")
    async def protected(request: Request):
        user = auth.get_current_user(request)
        return {"user": dict(user) if user else None}

    @app.get("/logged-out")
    async def logged_out():
        return {"logged_out": True}

    @app.post("/api/system/logout")
    async def logout():
        return {"success": True}

    app.add_middleware(auth.PlatformAuthMiddleware, settings=settings, verifier=verifier)
    with TestClient(app, base_url="http://172.23.255.36:32253", follow_redirects=False) as client:
        yield client, calls, upstream


def session_cookies(client, *, username="平台姓名", appid="127", prefix="jtb_sv"):
    cookies = {f"{prefix}_appid": appid, f"{prefix}_userid": "synthetic-user", f"{prefix}_token": "synthetic-token"}
    if username is not None:
        cookies[f"{prefix}_username"] = quote(username)
    for key, value in cookies.items():
        client.cookies.set(key, value, domain="172.23.255.36", path="/")


def test_login_uses_auto_mode_and_original_query_without_state(reference_client):
    client, calls, _ = reference_client
    response = client.get("/?appid=127&tag=one&tag=two&name=business")
    assert response.status_code == 307
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query == {
        "app_id": ["127"], "login_mode": ["auto"],
        "redirect_uri": ["http://172.23.255.36:32253/?appid=127&tag=one&tag=two&name=business"],
    }
    assert not calls
    assert not client.cookies.get("sv_login_state")


def test_direct_callback_checks_platform_then_sets_namespaced_session_cookies(reference_client):
    client, calls, _ = reference_client
    response = client.get("/?userid=synthetic-user&token=synthetic-token&appid=127&sn=business&tag=one&tag=two")
    assert response.status_code == 307
    assert response.headers["location"] == "http://172.23.255.36:32253/?appid=127&sn=business&tag=one&tag=two"
    assert calls == [("synthetic-user", "synthetic-token", 127)]
    assert client.cookies.get("jtb_sv_username") == quote("平台姓名")
    assert client.cookies.get("jtb_sv_appid") == "127"
    session_headers = [value for value in response.headers.get_list("set-cookie") if value.startswith("jtb_sv_")]
    assert len(session_headers) == 4
    assert all("HttpOnly" in value and "Max-Age" not in value and "expires=" not in value for value in session_headers)
    assert all("Secure" not in value for value in session_headers)
    assert client.get("/api/current-user").json()["user"]["name"] == "平台姓名"
    assert len(calls) == 1


def test_complete_application_cookies_are_used_without_platform_revalidation(reference_client):
    client, calls, upstream = reference_client
    upstream["error"] = auth.PlatformUnavailableError()
    session_cookies(client, username="已有会话姓名")
    response = client.get("/api/protected")
    assert response.status_code == 200
    assert response.json()["user"]["name"] == "已有会话姓名"
    assert response.json()["user"]["userid"] == "synthetic-user"
    assert not calls


def test_existing_session_precedes_callback_query_like_reference(reference_client):
    client, calls, _ = reference_client
    session_cookies(client)
    response = client.get("/?userid=another-user&token=another-synthetic-token")
    assert response.status_code == 307
    assert response.headers["location"] == "http://172.23.255.36:32253/"
    assert client.get("/").json()["user"]["userid"] == "synthetic-user"
    assert not calls


def test_missing_name_is_backfilled_after_serving_the_existing_session(reference_client):
    client, calls, _ = reference_client
    session_cookies(client, username=None)
    response = client.get("/api/protected")
    assert response.status_code == 200
    assert response.json()["user"]["name"] == "synthetic-user"
    assert client.cookies.get("jtb_sv_username") == quote("平台姓名")
    assert calls == [("synthetic-user", "synthetic-token", 127)]
    assert client.get("/api/protected").json()["user"]["name"] == "平台姓名"
    assert len(calls) == 1


def test_name_backfill_failure_keeps_session_and_cools_down(reference_client, monkeypatch):
    client, calls, upstream = reference_client
    now = [100.0]
    monkeypatch.setattr(auth.time, "time", lambda: now[0])
    upstream["error"] = auth.PlatformUnavailableError()
    session_cookies(client, username=None)
    assert client.get("/api/protected").status_code == 200
    assert client.get("/api/protected").status_code == 200
    assert len(calls) == 1
    now[0] = 161.0
    assert client.get("/api/protected").status_code == 200
    assert len(calls) == 2


@pytest.mark.parametrize("prefix", ["sv", "p02_sv"])
def test_other_application_cookie_names_do_not_authenticate(reference_client, prefix):
    client, calls, _ = reference_client
    session_cookies(client, prefix=prefix)
    response = client.get("/")
    assert response.status_code == 307
    assert urlsplit(response.headers["location"]).path == "/oauth2/login"
    assert not calls
    if prefix == "sv":
        assert not client.cookies.get("sv_token")
    else:
        assert client.cookies.get("p02_sv_token") == "synthetic-token"


@pytest.mark.parametrize("appid", [None, "", "9086"])
def test_session_cookie_requires_matching_application_id(reference_client, appid):
    client, calls, _ = reference_client
    session_cookies(client, appid=appid or "")
    if appid is None:
        client.cookies.delete("jtb_sv_appid", domain="172.23.255.36", path="/")
    response = client.get("/api/protected")
    assert response.status_code == 401
    assert response.json() == {
        "success": False, "error": "未登录或登录已失效", "auth_required": True, "login_url": "/auth/login",
    }
    assert not calls


def test_wrong_callback_application_restarts_login_with_normalized_appid(reference_client):
    client, calls, _ = reference_client
    response = client.get("/?userid=synthetic-user&token=synthetic-token&appid=9086&tag=one")
    assert response.status_code == 307
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["app_id"] == ["127"]
    assert query["redirect_uri"] == ["http://172.23.255.36:32253/?appid=127&tag=one"]
    assert not calls


@pytest.mark.parametrize("unavailable", [False, True])
def test_failed_callback_reenters_platform_login(reference_client, unavailable):
    client, calls, upstream = reference_client
    upstream["payload"] = None
    if unavailable:
        upstream["error"] = auth.PlatformUnavailableError()
    response = client.get("/?userid=synthetic-user&token=synthetic-token&appid=127")
    assert response.status_code == 307
    assert urlsplit(response.headers["location"]).path == "/oauth2/login"
    assert len(calls) == 1
    assert not client.cookies.get("jtb_sv_token")


def test_anonymous_identity_probe_stays_compatible(reference_client):
    client, calls, _ = reference_client
    response = client.get("/api/current-user")
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert not calls


def test_logout_routes_reach_controller_without_session(reference_client):
    client, calls, _ = reference_client
    assert client.post("/api/system/logout").status_code == 200
    assert client.get("/logged-out").status_code == 200
    assert not calls


def test_platform_check_ignores_environment_proxy_configuration(monkeypatch):
    real_client = httpx.AsyncClient
    observed = []
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "data": {"sn": "平台姓名"}})

    def client_factory(**kwargs):
        observed.append(kwargs.get("trust_env", True))
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(auth.httpx, "AsyncClient", client_factory)
    verifier = auth.PlatformTokenVerifier(auth.AuthSettings(enabled=True))
    payload = asyncio.run(verifier("synthetic-user", "synthetic-token", 127))
    assert payload["data"]["sn"] == "平台姓名"
    assert str(requests[0].url) == "http://172.23.255.36/tenant-api/api/auth/check-app-token"
    assert observed == [False]
