"""Platform authentication contracts exercised without a live OA deployment."""
from __future__ import annotations

import importlib
import json
import os
from contextlib import ExitStack
from dataclasses import FrozenInstanceError
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

_ASYNC_CLIENT = httpx.AsyncClient


def settings_class():
    return importlib.import_module("src.common.platform_auth").AuthSettings


def test_local_auth_defaults_remain_disabled_without_an_oa_application_id():
    settings = settings_class().from_env({})
    assert not settings.enabled
    assert settings.app_id is None
    assert settings.platform_base_url == "https://sv.dcsmartvision.com"


def test_namespaced_settings_take_precedence_and_are_loaded_at_construction(monkeypatch, isolated_auth_layout):
    settings = settings_class().from_env({
        "JTB_AUTH_ENABLED": "true", "AUTH_ENABLED": "false",
        "JTB_AUTH_APP_ID": "137", "APP_ID": "84",
        "JTB_AUTH_PLATFORM_BASE_URL": "https://oa.example/", "PLATFORM_BASE_URL": "https://old.example",
        "JTB_AUTH_PUBLIC_URL": "https://taskbook.example/",
        "JTB_AUTH_TIMEOUT_SECONDS": "2.5", "JTB_AUTH_CACHE_SECONDS": "0",
        "JTB_AUTH_COOKIE_MAX_AGE": "3600",
    })
    assert settings.enabled and settings.app_id == 137
    assert settings.platform_base_url == "https://oa.example"
    assert settings.public_url == "https://taskbook.example"
    assert settings.timeout_seconds == 2.5 and settings.cache_seconds == 0
    assert settings.cookie_max_age == 3600
    monkeypatch.setenv("JTB_AUTH_ENABLED", "true")
    monkeypatch.setenv("JTB_AUTH_APP_ID", "138")
    monkeypatch.setenv("JTB_AUTH_PUBLIC_URL", "https://taskbook.example")
    assert settings_class().from_env().app_id == 138
    with pytest.raises(FrozenInstanceError):
        settings.app_id = 84


def test_legacy_auth_environment_still_works():
    settings = settings_class().from_env({
        "AUTH_ENABLED": "true", "APP_ID": "137", "PLATFORM_BASE_URL": "http://oa.internal",
        "JTB_AUTH_PUBLIC_URL": "https://taskbook.example",
    })
    assert settings.enabled and settings.app_id == 137
    assert settings.platform_base_url == "http://oa.internal"


@pytest.mark.parametrize("app_id", ["", "abc", "0", "-1", "1.5", "１２３"])
def test_enabled_auth_requires_a_positive_numeric_application_id(app_id):
    with pytest.raises(ValueError, match="APP_ID"):
        settings_class().from_env({"JTB_AUTH_ENABLED": "true", "JTB_AUTH_APP_ID": app_id})


@pytest.mark.parametrize("value", ["https://taskbook.example/other", "//evil.example", "javascript:alert(1)", "https://u:p@taskbook.example", "https://taskbook.example?x=1"])
def test_public_url_must_be_an_http_origin(value):
    with pytest.raises(ValueError, match="PUBLIC_URL"):
        settings_class().from_env({"JTB_AUTH_PUBLIC_URL": value})


def test_enabled_auth_requires_an_explicit_public_callback_origin():
    with pytest.raises(ValueError, match="JTB_AUTH_PUBLIC_URL"):
        settings_class().from_env({"JTB_AUTH_ENABLED": "true", "JTB_AUTH_APP_ID": "137"})


@pytest.mark.parametrize("name,value", [
    ("JTB_AUTH_TIMEOUT_SECONDS", "0"), ("JTB_AUTH_TIMEOUT_SECONDS", "nan"),
    ("JTB_AUTH_CACHE_SECONDS", "-1"), ("JTB_AUTH_COOKIE_MAX_AGE", "0"),
])
def test_invalid_timeout_cache_or_cookie_configuration_fails_clearly(name, value):
    with pytest.raises(ValueError, match=name):
        settings_class().from_env({name: value})


@pytest.fixture
def isolated_auth_layout(tmp_path, monkeypatch):
    auth = importlib.import_module("src.common.platform_auth")
    monkeypatch.setenv("JTB_AUTH_SETTINGS_DB", str(tmp_path / "auth_settings.sqlite3"))
    module_file = tmp_path / "project/basic-service/app/src/common/platform_auth.py"
    module_file.parent.mkdir(parents=True)
    baked_env = module_file.parents[1] / "service/.env"
    baked_env.parent.mkdir()
    project_env = module_file.parents[4] / ".env"
    monkeypatch.setattr(auth, "__file__", str(module_file))
    for key in (
        "JTB_AUTH_ENABLED", "AUTH_ENABLED", "JTB_AUTH_APP_ID", "APP_ID",
        "JTB_AUTH_PLATFORM_BASE_URL", "PLATFORM_BASE_URL", "JTB_AUTH_PUBLIC_URL",
        "JTB_AUTH_TIMEOUT_SECONDS", "JTB_AUTH_CACHE_SECONDS", "JTB_AUTH_COOKIE_MAX_AGE",
    ):
        monkeypatch.delenv(key, raising=False)
    return auth, project_env, baked_env


def write_baked_auth(path, *, appid=137):
    path.write_text(
        "# 合成镜像配置，不含真实凭据\n"
        f"JTB_AUTH_ENABLED=true\nJTB_AUTH_APP_ID={appid}\n"
        "JTB_AUTH_PLATFORM_BASE_URL=http://platform.internal\n"
        "JTB_AUTH_PUBLIC_URL='https://taskbook.example'\n"
        "JTB_AUTH_TIMEOUT_SECONDS=3\nJTB_AUTH_CACHE_SECONDS=0\nJTB_AUTH_COOKIE_MAX_AGE=3600\n"
        "MODEL_APP_ID=synthetic-file-model\nJTB_LLM_APP_ID=synthetic-file-llm\n"
        "AUTH_QA_UNRELATED=must-not-be-exported\n",
        encoding="utf-8-sig",
    )


def test_standalone_image_reads_auth_settings_from_its_actual_baked_dotenv(isolated_auth_layout, monkeypatch):
    auth, _, baked_env = isolated_auth_layout
    monkeypatch.setenv("MODEL_APP_ID", "synthetic-process-model")
    monkeypatch.delenv("JTB_LLM_APP_ID", raising=False)
    monkeypatch.delenv("AUTH_QA_UNRELATED", raising=False)
    write_baked_auth(baked_env)
    settings = auth.AuthSettings.from_env()
    assert settings.enabled and settings.app_id == 137
    assert settings.platform_base_url == "http://platform.internal"
    assert settings.public_url == "https://taskbook.example"
    assert settings.timeout_seconds == 3 and settings.cache_seconds == 0 and settings.cookie_max_age == 3600
    assert os.environ["MODEL_APP_ID"] == "synthetic-process-model"
    assert "JTB_LLM_APP_ID" not in os.environ and "AUTH_QA_UNRELATED" not in os.environ
    assert "JTB_AUTH_ENABLED" not in os.environ


@pytest.mark.parametrize("variable", ["JTB_AUTH_ENABLED", "AUTH_ENABLED"])
def test_process_can_disable_baked_auth_using_either_supported_switch(isolated_auth_layout, monkeypatch, variable):
    auth, _, baked_env = isolated_auth_layout
    write_baked_auth(baked_env)
    monkeypatch.setenv(variable, "false")
    settings = auth.AuthSettings.from_env()
    assert not settings.enabled
    assert settings.app_id == 137


def test_process_auth_app_id_overrides_the_baked_id(isolated_auth_layout, monkeypatch):
    auth, _, baked_env = isolated_auth_layout
    write_baked_auth(baked_env)
    monkeypatch.setenv("JTB_AUTH_APP_ID", "139")
    settings = auth.AuthSettings.from_env()
    assert settings.enabled and settings.app_id == 139


def test_project_dotenv_takes_precedence_over_baked_defaults(isolated_auth_layout):
    auth, project_env, baked_env = isolated_auth_layout
    write_baked_auth(baked_env)
    project_env.write_text("AUTH_ENABLED=false\nAPP_ID=140\n", encoding="utf-8")
    settings = auth.AuthSettings.from_env()
    assert not settings.enabled and settings.app_id == 140


def test_explicit_environment_mapping_never_reads_private_dotenv_files(isolated_auth_layout, monkeypatch):
    auth, _, baked_env = isolated_auth_layout
    write_baked_auth(baked_env)

    def forbidden_file_read(*args, **kwargs):
        pytest.fail("An explicit environment mapping must not read any dotenv file")

    monkeypatch.setattr(auth, "dotenv_values", forbidden_file_read, raising=False)
    settings = auth.AuthSettings.from_env({})
    assert not settings.enabled and settings.app_id is None


def test_baked_auth_configuration_is_read_fresh_for_each_application_construction(isolated_auth_layout):
    auth, _, baked_env = isolated_auth_layout
    write_baked_auth(baked_env)
    first = auth.AuthSettings.from_env()
    write_baked_auth(baked_env, appid=141)
    second = auth.AuthSettings.from_env()
    assert first.app_id == 137 and second.app_id == 141


def test_blank_process_switch_does_not_fall_back_to_baked_auth(isolated_auth_layout, monkeypatch):
    auth, _, baked_env = isolated_auth_layout
    write_baked_auth(baked_env)
    monkeypatch.setenv("JTB_AUTH_ENABLED", "")
    with pytest.raises(ValueError, match="AUTH_ENABLED"):
        auth.AuthSettings.from_env()


@pytest.fixture
def clients(monkeypatch):
    auth = importlib.import_module("src.common.platform_auth")
    calls = []
    platform = {"payload": {"code": 0, "data": {"name": "张工程师"}}, "status": 200, "error": None}

    def platform_handler(request):
        calls.append(request)
        if platform["error"]:
            raise platform["error"]
        return httpx.Response(platform["status"], json=platform["payload"])

    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kwargs: _ASYNC_CLIENT(
        transport=httpx.MockTransport(platform_handler), **kwargs,
    ))
    with ExitStack() as stack:
        def make(*, enabled=True, cache_seconds=60, public_url="https://taskbook.example", base_url="https://taskbook.example", verifier=None):
            app = FastAPI()
            settings = auth.AuthSettings(
                enabled=enabled, app_id=137 if enabled else None,
                platform_base_url="https://oa.example", public_url=public_url,
                cache_seconds=cache_seconds,
            )
            app.state.auth_settings = settings
            app.include_router(importlib.import_module("src.controller.auth_controller").router)

            @app.get("/")
            @app.get("/review/job")
            @app.get("/api/protected")
            async def protected(request: Request):
                user = auth.get_current_user(request)
                immutable = True
                if user:
                    try:
                        user["name"] = "client supplied"
                    except TypeError:
                        pass
                    else:
                        immutable = False
                return {"user": dict(user) if user else None, "immutable": immutable}

            @app.get("/api/health")
            @app.get("/assets/app.js")
            @app.get("/favicon.ico")
            async def public():
                return {"ok": True}

            @app.api_route("/api/review/{jid}/editor/{sid}/{operation}", methods=["GET", "POST", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"])
            async def document_signature_boundary(request: Request):
                return JSONResponse({"editor_signature_required": True, "has_browser_identity": auth.get_current_user(request) is not None}, status_code=403)

            app.add_middleware(auth.PlatformAuthMiddleware, settings=settings, verifier=verifier)
            return stack.enter_context(TestClient(app, base_url=base_url)), platform, calls

        yield make


def valid_cookies(client, *, token="valid-secret", userid="user-7", appid="137"):
    client.cookies.set("sv_token", token)
    client.cookies.set("sv_userid", userid)
    if appid is not None:
        client.cookies.set("sv_appid", appid)


def start_login(client, path="/auth/login"):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 302
    redirect_uri = parse_qs(urlsplit(response.headers["location"]).query)["redirect_uri"][0]
    state = parse_qs(urlsplit(redirect_uri).query)["_jtb_auth_state"][0]
    return response, state


def complete_callback(client, url):
    _, state = start_login(client)
    parsed = urlsplit(url)
    query = [*parse_qsl(parsed.query, keep_blank_values=True), ("_jtb_auth_state", state)]
    callback = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    return client.get(callback, follow_redirects=False)


def test_anonymous_pages_go_to_configured_oa_app_and_preserve_nonidentity_query(clients):
    client, _, calls = clients()
    response = client.get("/review/job?tag=1&tag=2&title=%E4%B8%AD%E6%96%87&name=spoof", follow_redirects=False)
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert (location.scheme, location.netloc, location.path) == ("https", "oa.example", "/oauth2/login")
    query = parse_qs(location.query)
    assert query["app_id"] == ["137"]
    redirect = urlsplit(query["redirect_uri"][0])
    assert (redirect.scheme, redirect.netloc, redirect.path) == ("https", "taskbook.example", "/review/job")
    redirect_query = parse_qs(redirect.query)
    state = redirect_query.pop("_jtb_auth_state")[0]
    assert redirect_query == {"tag": ["1", "2"], "title": ["中文"]}
    assert state == client.cookies.get("sv_login_state")
    assert not calls


def test_business_api_requires_login_without_trusting_identity_headers(clients):
    client, _, calls = clients()
    response = client.get("/api/protected", headers={"X-User": "admin", "X-User-Name": "管理员".encode().hex()})
    assert response.status_code == 401
    assert response.json()["auth_required"] is True
    assert response.json()["login_url"] == "/auth/login"
    assert "error" in response.json()
    assert not calls


@pytest.mark.parametrize("method,operation", [("GET", "file"), ("POST", "callback")])
@pytest.mark.parametrize("jid", ["a0a0137abc", "Job_01-x", "A" * 128])
def test_signed_document_server_routes_reach_their_own_validation_without_oa_checks(clients, method, operation, jid):
    client, _, calls = clients()
    sid = "a1b2c3d4" * 4
    response = client.request(method, f"/api/review/{jid}/editor/{sid}/{operation}", params={"token": "synthetic-editor-signature"})
    assert response.status_code == 403
    assert response.json() == {"editor_signature_required": True, "has_browser_identity": False}
    assert not calls


@pytest.mark.parametrize("method,operation", [
    ("POST", "file"), ("HEAD", "file"), ("PUT", "file"),
    ("GET", "callback"), ("DELETE", "callback"), ("OPTIONS", "callback"),
    ("GET", "save"), ("POST", "save"), ("GET", "file/"), ("POST", "callback/"),
    ("GET", "files"), ("POST", "callback-extra"),
])
def test_document_server_bypass_does_not_allow_other_methods_or_similar_routes(clients, method, operation):
    client, _, calls = clients()
    sid = "a1b2c3d4" * 4
    response = client.request(method, f"/api/review/a0a0137abc/editor/{sid}/{operation}", follow_redirects=False)
    assert response.status_code == 401
    assert not calls


@pytest.mark.parametrize("jid,sid", [
    ("A" * 129, "a" * 32), ("中文任务", "a" * 32),
    ("job-1", "a" * 31), ("job-1", "a" * 33),
    ("job-1", "F" * 32), ("job-1", "g" * 32),
])
def test_document_server_bypass_requires_exact_editor_identifier_formats(clients, jid, sid):
    client, _, calls = clients()
    assert client.get(f"/api/review/{jid}/editor/{sid}/file").status_code == 401
    assert not calls


@pytest.mark.parametrize("method,suffix", [("POST", ""), ("GET", "/" + "a" * 32), ("GET", "/status")])
def test_editor_open_and_session_routes_continue_to_require_browser_login(clients, method, suffix):
    client, _, calls = clients()
    response = client.request(method, "/api/review/a0a0137abc/editor" + suffix, follow_redirects=False)
    assert response.status_code == 401
    assert not calls


@pytest.mark.parametrize("path", ["/api/health", "/assets/app.js", "/favicon.ico"])
def test_health_and_static_assets_remain_public(clients, path):
    client, _, calls = clients()
    assert client.get(path).json() == {"ok": True}
    assert not calls


def test_disabled_auth_supports_local_use_and_exposes_no_claimed_identity(clients):
    client, _, calls = clients(enabled=False)
    valid_cookies(client)
    client.cookies.set("sv_username", "forged")
    assert client.get("/api/protected").json() == {"user": None, "immutable": True}
    current = client.get("/api/current-user")
    assert current.json() == {"auth_enabled": False, "authenticated": False, "user": None}
    assert current.headers["cache-control"] == "no-store"
    assert not calls


def test_current_user_can_report_anonymous_auth_status(clients):
    client, _, _ = clients()
    response = client.get("/api/current-user")
    assert response.status_code == 200
    assert response.json() == {"auth_enabled": True, "authenticated": False, "user": None, "login_url": "/auth/login"}


@pytest.mark.parametrize("cookie,value", [
    ("sv_token", "incomplete-secret"), ("sv_userid", "user-7"),
    ("sv_token", ""), ("sv_userid", ""), ("sv_username", "forged"),
])
def test_current_user_rejects_incomplete_credential_cookies(clients, cookie, value):
    client, _, calls = clients()
    client.cookies.set(cookie, value)
    response = client.get("/api/current-user")
    assert response.status_code == 401
    assert response.json()["auth_required"] is True
    assert not calls


def test_current_user_does_not_hide_an_invalid_session_as_anonymous(clients):
    client, platform, _ = clients()
    platform["payload"] = {"code": 401}
    valid_cookies(client)
    response = client.get("/api/current-user")
    assert response.status_code == 401
    assert response.json()["auth_required"] is True


def test_current_user_reports_validation_outage_instead_of_anonymous_mode(clients):
    client, platform, _ = clients()
    platform["error"] = httpx.ReadTimeout("secret")
    valid_cookies(client)
    assert client.get("/api/current-user").status_code == 503


def test_callback_checks_server_side_then_sets_secure_cookies_and_cleans_the_url(clients, caplog):
    client, _, calls = clients()
    response = complete_callback(client,
        "/review/job?userid=user-7&token=callback-secret&appid=137&name=forged&userName=forged"
        "&tag=1&tag=2&title=%E4%B8%AD%E6%96%87",
    )
    assert response.status_code == 302
    assert response.headers["location"] == "https://taskbook.example/review/job?tag=1&tag=2&title=%E4%B8%AD%E6%96%87"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert len(calls) == 1
    assert str(calls[0].url) == "https://oa.example/tenant-api/api/auth/check-app-token"
    assert json.loads(calls[0].content) == {"userid": "user-7", "token": "callback-secret", "appid": 137}
    for name in ("sv_appid", "sv_token", "sv_userid"):
        header = next(value for value in response.headers.get_list("set-cookie") if value.startswith(name + "="))
        assert "HttpOnly" in header and "Secure" in header and "SameSite=lax" in header and "Max-Age=28800" in header
    current = client.get("/api/current-user").json()
    assert current == {"auth_enabled": True, "authenticated": True, "user": {
        "userid": "user-7", "name": "张工程师", "display_name": "张工程师", "source": "smartvision", "verified": True,
    }}
    assert "callback-secret" not in caplog.text
    assert client.get("/api/protected").json()["immutable"] is True


def test_cookie_identity_is_verified_and_forged_display_name_is_ignored(clients):
    client, _, calls = clients()
    valid_cookies(client)
    client.cookies.set("sv_username", "%E7%AE%A1%E7%90%86%E5%91%98")
    response = client.get("/api/protected", headers={"X-User": "admin", "X-Username": "forged"})
    assert response.status_code == 200
    assert response.json()["user"]["name"] == "张工程师"
    assert response.json()["user"]["userid"] == "user-7"
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [{"code": 401}, {"code": "0"}, {"code": False}, {"code": 0, "data": None, "ignored": "accepted"}])
def test_only_an_integer_success_code_authenticates_the_session(clients, payload):
    client, platform, _ = clients()
    platform["payload"] = payload
    valid_cookies(client)
    response = client.get("/api/protected")
    if payload.get("code") == 0 and type(payload.get("code")) is int:
        assert response.status_code == 200
        assert response.json()["user"]["name"] == "user-7"
    else:
        assert response.status_code == 401


def test_invalid_cookie_never_reaches_protected_business_route(clients):
    client, platform, calls = clients()
    platform["payload"] = {"code": 401, "msg": "expired"}
    valid_cookies(client)
    response = client.get("/api/protected")
    assert response.status_code == 401 and response.json()["auth_required"] is True
    assert len(calls) == 1
    assert any("sv_token=" in value and "Max-Age=0" in value for value in response.headers.get_list("set-cookie"))


def test_name_query_and_legacy_cookie_never_supply_missing_verified_name(clients):
    client, platform, _ = clients()
    platform["payload"] = {"code": 0, "data": {}}
    client.cookies.set("sv_username", "forged")
    response = complete_callback(client, "/?userid=user-7&token=valid-secret&name=forged")
    assert response.status_code == 302
    assert client.get("/api/current-user").json()["user"]["name"] == "user-7"


@pytest.mark.parametrize("field", ["name", "username", "userName", "nickname", "realName", "real_name", "display_name"])
@pytest.mark.parametrize("nested", [True, False])
def test_platform_name_aliases_are_supported(clients, field, nested):
    client, platform, _ = clients()
    platform["payload"] = {"code": 0, **({"data": {field: " 李工程师 "}} if nested else {field: " 李工程师 "})}
    valid_cookies(client)
    assert client.get("/api/current-user").json()["user"]["display_name"] == "李工程师"


@pytest.mark.parametrize("kind", ["callback", "cookie"])
def test_other_application_ids_are_rejected_without_using_them_for_validation(clients, kind):
    client, _, calls = clients()
    if kind == "callback":
        response = client.get("/?userid=user-7&token=secret&appid=999", follow_redirects=False)
    else:
        valid_cookies(client, appid="999")
        response = client.get("/api/protected")
    assert response.status_code == 401
    assert not calls


@pytest.mark.parametrize("status", [401, 403, 302])
def test_http_success_is_required_even_if_body_says_success(clients, status):
    client, platform, _ = clients()
    platform["status"] = status
    valid_cookies(client)
    assert client.get("/api/protected").status_code == 401


@pytest.mark.parametrize("failure", ["timeout", "upstream500"])
def test_platform_outage_returns_redacted_503(clients, failure, caplog):
    client, platform, _ = clients()
    if failure == "timeout":
        platform["error"] = httpx.ConnectError("secret-token https://private.internal")
    else:
        platform["status"] = 500
    valid_cookies(client, token="secret-token")
    response = client.get("/api/protected")
    assert response.status_code == 503 and "error" in response.json()
    assert "secret-token" not in response.text + caplog.text
    assert "private.internal" not in response.text + caplog.text


def test_verified_cache_expires_and_cannot_be_reused_for_a_different_user_or_token(clients, monkeypatch):
    auth = importlib.import_module("src.common.platform_auth")
    now = [100.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    client, platform, calls = clients(cache_seconds=60)
    valid_cookies(client)
    assert client.get("/api/protected").status_code == 200
    platform["payload"] = {"code": 401}
    assert client.get("/api/protected").status_code == 200
    assert len(calls) == 1
    now[0] = 161.0
    assert client.get("/api/protected").status_code == 401
    assert len(calls) == 2
    valid_cookies(client, userid="other-user")
    assert client.get("/api/protected").status_code == 401
    valid_cookies(client, token="different-token")
    assert client.get("/api/protected").status_code == 401
    assert len(calls) == 4


def test_zero_cache_rechecks_existing_cookies_on_every_request(clients):
    client, platform, calls = clients(cache_seconds=0)
    valid_cookies(client)
    assert client.get("/api/protected").status_code == 200
    platform["payload"] = {"code": 401}
    assert client.get("/api/protected").status_code == 401
    assert len(calls) == 2


def test_verification_cache_evicts_oldest_session_at_its_bound(clients, monkeypatch):
    auth = importlib.import_module("src.common.platform_auth")
    monkeypatch.setattr(auth, "_CACHE_LIMIT", 2)
    client, platform, calls = clients()
    for userid in ("user-a", "user-b", "user-c"):
        valid_cookies(client, userid=userid)
        assert client.get("/api/protected").status_code == 200
    platform["payload"] = {"code": 401}
    valid_cookies(client, userid="user-a")
    assert client.get("/api/protected").status_code == 401
    assert len(calls) == 4


def test_custom_verifier_can_supply_verified_identity_without_a_network_request(clients):
    async def verifier(userid, token, appid):
        if (userid, token, appid) == ("user-7", "valid-secret", 137):
            return {"code": 0, "data": {"realName": "验证用户"}}
        return None

    client, _, calls = clients(verifier=verifier)
    valid_cookies(client)
    assert client.get("/api/current-user").json()["user"]["name"] == "验证用户"
    assert not calls


def test_public_origin_overrides_request_origin_and_forwarded_headers_are_not_trusted(clients):
    client, _, _ = clients(public_url="https://public.example", base_url="https://internal.example")
    response = complete_callback(client, "/?userid=user-7&token=secret")
    assert response.headers["location"] == "https://public.example/"
    assert all("Secure" in value for value in response.headers.get_list("set-cookie"))


def test_plain_http_local_callback_can_use_compatible_cookies(clients):
    client, _, _ = clients(public_url="http://taskbook.internal", base_url="http://taskbook.internal")
    response = complete_callback(client, "/?userid=user-7&token=secret")
    assert response.status_code == 302
    assert all("Secure" not in value for value in response.headers.get_list("set-cookie"))
    assert client.get("/api/current-user").json()["authenticated"] is True


def test_explicit_login_clears_cookies_and_uses_a_safe_root_return_url(clients):
    client, _, calls = clients()
    valid_cookies(client)
    response = client.get("/auth/login?return=https://evil.example", follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["app_id"] == ["137"]
    redirect = urlsplit(query["redirect_uri"][0])
    assert (redirect.scheme, redirect.netloc, redirect.path) == ("https", "taskbook.example", "/")
    assert parse_qs(redirect.query) == {"_jtb_auth_state": [client.cookies.get("sv_login_state")]}
    assert any("sv_token=" in value and "Max-Age=0" in value for value in response.headers.get_list("set-cookie"))
    assert not calls


def test_explicit_login_in_local_mode_returns_home(clients):
    client, _, _ = clients(enabled=False)
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 302 and response.headers["location"] == "/"


def test_login_state_is_unpredictable_and_held_in_a_short_lived_host_cookie(clients):
    client, _, calls = clients()
    first, first_state = start_login(client)
    _, second_state = start_login(client)
    assert len(first_state) >= 32 and first_state != second_state
    header = next(value for value in first.headers.get_list("set-cookie") if value.startswith("sv_login_state="))
    assert all(flag in header for flag in ("HttpOnly", "Secure", "SameSite=lax", "Max-Age=600", "Path=/"))
    assert "Domain=" not in header
    assert first.headers["cache-control"] == "no-store" and first.headers["referrer-policy"] == "no-referrer"
    assert not calls


def test_uninitiated_callback_cannot_write_an_attackers_session(clients):
    client, _, calls = clients()
    response = client.get("/?userid=attacker&token=attack-secret&name=forged", follow_redirects=False)
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert location.netloc == "oa.example" and location.path == "/oauth2/login"
    redirect_uri = parse_qs(location.query)["redirect_uri"][0]
    assert set(parse_qs(urlsplit(redirect_uri).query)) == {"_jtb_auth_state"}
    assert "attack-secret" not in response.headers["location"]
    assert not client.cookies.get("sv_token") and not client.cookies.get("sv_userid")
    assert not calls


@pytest.mark.parametrize("state", [None, "incorrect-state", "中文状态"])
def test_missing_or_invalid_callback_state_restarts_login_without_checking_token(clients, state):
    client, _, calls = clients()
    _, original_state = start_login(client)
    response = client.get("/review/job", params={
        "userid": "attacker", "token": "attack-secret", **({"_jtb_auth_state": state} if state is not None else {}),
    }, follow_redirects=False)
    assert response.status_code == 302 and urlsplit(response.headers["location"]).netloc == "oa.example"
    assert client.cookies.get("sv_login_state") != original_state
    assert not client.cookies.get("sv_token") and not calls


def test_callback_state_requires_the_matching_browser_cookie(clients):
    client, _, calls = clients()
    _, state = start_login(client)
    client.cookies.clear()
    response = client.get("/", params={"userid": "attacker", "token": "attack-secret", "_jtb_auth_state": state}, follow_redirects=False)
    assert response.status_code == 302 and urlsplit(response.headers["location"]).netloc == "oa.example"
    assert not calls


def test_successful_callback_consumes_state_and_replayed_link_restarts_login(clients):
    client, _, calls = clients()
    _, state = start_login(client)
    callback = "/review/job?" + urlencode([
        ("userid", "user-7"), ("token", "valid-secret"), ("_jtb_auth_state", state),
        ("tag", "first"), ("tag", "second"), ("title", "中文空 格"),
    ])
    response = client.get(callback, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://taskbook.example/review/job?tag=first&tag=second&title=%E4%B8%AD%E6%96%87%E7%A9%BA+%E6%A0%BC"
    assert client.cookies.get("sv_login_state") is None
    assert client.cookies.get("sv_token") == "valid-secret"
    replay = client.get(callback, follow_redirects=False)
    assert replay.status_code == 302 and urlsplit(replay.headers["location"]).netloc == "oa.example"
    assert len(calls) == 1


def test_enabled_login_ignores_untrusted_host_and_forwarding_headers(clients):
    client, _, _ = clients()
    response = client.get("/auth/login", headers={
        "Host": "evil.example", "X-Forwarded-Host": "other-evil.example", "X-Forwarded-Proto": "http",
    }, follow_redirects=False)
    redirect_uri = parse_qs(urlsplit(response.headers["location"]).query)["redirect_uri"][0]
    parsed = urlsplit(redirect_uri)
    assert (parsed.scheme, parsed.netloc, parsed.path) == ("https", "taskbook.example", "/")
