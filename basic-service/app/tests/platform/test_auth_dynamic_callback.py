"""Dynamic deployment ports must survive the complete verified login round trip."""
import asyncio
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from src.common.platform_auth import AuthSettings, PlatformAuthMiddleware
from src.controller.auth_controller import router


def make_client(origin, *, external=False, extra_env=None):
    settings = AuthSettings.from_env({
        "JTB_AUTH_ENABLED": "true",
        **({"JTB_AUTH_APP_ID": "9086", "JTB_AUTH_PLATFORM_BASE_URL": "https://sv.dcsmartvision.com"} if external else {}),
        **(extra_env or {}),
    })
    calls = []

    async def verify(userid, token, appid):
        calls.append((userid, token, appid))
        return {"code": 0, "data": {"sn": "平台姓名", "name": "备用姓名"}}

    app = FastAPI()
    app.state.auth_settings = settings
    app.add_middleware(PlatformAuthMiddleware, settings=settings, verifier=verify)
    app.include_router(router)
    return TestClient(app, base_url=origin, follow_redirects=False), calls


@pytest.mark.parametrize("origin,external,appid", [
    ("http://172.23.255.36:32253", False, 127),
    ("http://172.23.255.36:32689", False, 127),
    ("http://127.0.0.1:18130", True, 9086),
    ("http://localhost:18132", True, 9086),
    ("https://sv.dcsmartvision.com:32401", True, 9086),
])
def test_auto_origin_round_trip_uses_current_port_and_verified_sn(origin, external, appid):
    client, calls = make_client(origin, external=external)
    with client:
        response = client.get(f"/?accept_language=zh-CN&appid={appid}&tag=一&tag=二")
        assert response.status_code == 307
        login = urlsplit(response.headers["location"])
        assert login.netloc == ("sv.dcsmartvision.com" if external else "172.23.255.36")
        assert login.path == "/oauth2/login"
        assert parse_qs(login.query)["app_id"] == [str(appid)]
        assert parse_qs(login.query)["login_mode"] == ["auto"]
        callback = urlsplit(parse_qs(login.query)["redirect_uri"][0])
        assert f"{callback.scheme}://{callback.netloc}" == origin
        pairs = parse_qsl(callback.query)
        assert parse_qs(callback.query)["tag"] == ["一", "二"]
        assert dict(pairs)["appid"] == str(appid)
        assert "_jtb_auth_state" not in dict(pairs)
        completed = client.get(urlunsplit((callback.scheme, callback.netloc, callback.path, urlencode([
            *pairs, ("userid", "synthetic-user"), ("token", "synthetic-token"),
            ("sn", "伪造姓名"),
        ]), "")))
        assert completed.status_code == 307
        cleaned = urlsplit(completed.headers["location"])
        assert f"{cleaned.scheme}://{cleaned.netloc}" == origin
        assert parse_qs(cleaned.query) == {
            "accept_language": ["zh-CN"], "appid": [str(appid)], "tag": ["一", "二"], "sn": ["伪造姓名"],
        }
        assert calls == [("synthetic-user", "synthetic-token", appid)]
        assert all(("; Secure" in cookie) == origin.startswith("https:") for cookie in completed.headers.get_list("set-cookie"))
        identity = client.get("/api/current-user").json()
        assert identity["user"]["name"] == "平台姓名"
        assert identity["authenticated"] is True


def test_auto_origin_does_not_accept_client_forwarding_headers():
    client, _ = make_client("http://172.23.255.36:32253")
    with client:
        response = client.get("/auth/login", headers={
            "X-Forwarded-Host": "evil.example:7777", "X-Forwarded-Proto": "https",
            "Forwarded": "proto=https;host=evil.example",
        })
        callback = parse_qs(urlsplit(response.headers["location"]).query)["redirect_uri"][0]
        assert callback == "http://172.23.255.36:32253/"


def test_ipv6_host_retains_brackets_and_port():
    # This version of Starlette TestClient cannot use an IPv6 base_url.
    client, _ = make_client("http://127.0.0.1:18130", external=True)
    with client:
        response = client.get("/auth/login", headers={"Host": "[::1]:18130"})
        callback = parse_qs(urlsplit(response.headers["location"]).query)["redirect_uri"][0]
        assert callback == "http://[::1]:18130/"


def test_auto_origin_rejects_unapproved_host_before_leaking_a_login_return_url():
    client, calls = make_client("http://172.23.255.36:32253")
    with client:
        response = client.get("/auth/login", headers={"Host": "evil.example:9999"})
        assert response.status_code == 400
        assert "location" not in response.headers and calls == []


def test_switching_preset_reauthenticates_an_old_application_cookie():
    client, calls = make_client("http://127.0.0.1:18130", external=True)
    with client:
        for key, value in {"sv_appid": "9192", "sv_userid": "old-user", "sv_token": "old-synthetic-token"}.items():
            client.cookies.set(key, value, domain="127.0.0.1", path="/")
        response = client.get("/")
        assert response.status_code == 307
        assert parse_qs(urlsplit(response.headers["location"]).query)["app_id"] == ["9086"]
        assert calls == []
        assert not client.cookies.get("sv_token")


def test_explicit_callback_host_can_keep_its_dynamic_port():
    client, _ = make_client("https://taskbook.example:32502", extra_env={"JTB_AUTH_CALLBACK_HOSTS": "taskbook.example"})
    with client:
        response = client.get("/auth/login")
        callback = parse_qs(urlsplit(response.headers["location"]).query)["redirect_uri"][0]
        assert callback == "https://taskbook.example:32502/"


def test_fixed_origin_remains_available_for_custom_proxy_deployments():
    client, _ = make_client("http://internal.example:18130", extra_env={"JTB_AUTH_PUBLIC_URL": "https://fixed.example:9443"})
    with client:
        response = client.get("/auth/login")
        callback = parse_qs(urlsplit(response.headers["location"]).query)["redirect_uri"][0]
        assert callback == "https://fixed.example:9443/"


@pytest.mark.parametrize("peer,expected_scheme", [("127.0.0.1", "https"), ("192.0.2.1", "http")])
def test_https_gateway_protocol_only_applies_from_the_trusted_proxy(peer, expected_scheme):
    client, _ = make_client("http://sv.dcsmartvision.com:32401", external=True)
    proxied_app = ProxyHeadersMiddleware(client.app, trusted_hosts="127.0.0.1")

    async def request():
        transport = httpx.ASGITransport(app=proxied_app, client=(peer, 44321))
        async with httpx.AsyncClient(transport=transport, base_url="http://sv.dcsmartvision.com:32401") as browser:
            return await browser.get("/auth/login", headers={
                "X-Forwarded-Proto": "https", "X-Forwarded-Host": "evil.example",
            })

    response = asyncio.run(request())
    assert response.status_code == 307
    callback = parse_qs(urlsplit(response.headers["location"]).query)["redirect_uri"][0]
    assert callback == f"{expected_scheme}://sv.dcsmartvision.com:32401/"
    assert all(("; Secure" in cookie) == (expected_scheme == "https") for cookie in response.headers.get_list("set-cookie"))
