"""A browser cookie is a credential to verify, never proof of an OA identity."""
import asyncio
from types import SimpleNamespace
from urllib.parse import quote

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common import platform_auth as auth
from src.controller.auth_controller import router as auth_router
from src.controller.rd_controller import router as rd_router
from src.service.rd_platform.store import Store


def client_for(tmp_path, *, cache_seconds=60):
    settings = auth.AuthSettings(enabled=True, app_id=9086, platform_base_url="https://login.example",
                                 public_url="https://research.example", cache_seconds=cache_seconds)
    state = {"calls": [], "available": True, "valid": True}

    async def verify(userid, token, appid):
        state["calls"].append((userid, appid))
        if not state["available"]:
            raise auth.PlatformUnavailableError()
        if not state["valid"] or token != "synthetic-valid-credential":
            return None
        return {"code": 0, "data": {"sn": "服务端确认姓名"}}

    app = FastAPI()
    app.state.auth_settings = settings
    app.state.rd_store = Store(tmp_path / "rd.sqlite3", tmp_path / "assets")
    app.state.config = SimpleNamespace(logs_dir=tmp_path / "logs", max_upload_bytes=1024)
    app.include_router(rd_router)
    app.include_router(auth_router)
    app.add_middleware(auth.PlatformAuthMiddleware, settings=settings, verifier=verify)
    return TestClient(app, base_url="https://research.example", follow_redirects=False), state


def set_cookie_credentials(client, *, userid="engineer", token="synthetic-valid-credential", name="伪造管理员姓名"):
    for key, value in ((auth.COOKIE_APPID, "9086"), (auth.COOKIE_TOKEN, token),
                       (auth.COOKIE_USERID, userid), (auth.COOKIE_USERNAME, quote(name))):
        client.cookies.set(key, value, domain="research.example", path="/")


def test_unverified_cookie_cannot_impersonate_a_research_project_owner(tmp_path):
    client, state = client_for(tmp_path)
    project = client.app.state.rd_store.create_project("owner", "隔离的项目")
    set_cookie_credentials(client, userid="owner", token="synthetic-forged-credential")
    response = client.get(f"/api/rd/projects/{project['id']}")
    assert response.status_code == 401
    assert response.json()["auth_required"] is True
    assert state["calls"] == [("owner", 9086)]
    assert client.app.state.rd_store.get_project("owner", project["id"])["version"] == 1


def test_validated_cookie_uses_server_name_and_reuses_successful_verification(tmp_path):
    client, state = client_for(tmp_path)
    set_cookie_credentials(client)
    first = client.get("/api/current-user")
    assert first.status_code == 200
    assert first.json()["user"]["display_name"] == "服务端确认姓名"
    assert client.get("/api/rd/session").json()["actor_id"] == "engineer"
    assert client.get("/api/rd/projects").status_code == 200
    assert state["calls"] == [("engineer", 9086)]
    set_cookie_credentials(client, name="再次篡改显示姓名")
    assert client.get("/api/current-user").json()["user"]["display_name"] == "服务端确认姓名"
    assert state["calls"] == [("engineer", 9086)]


def test_changed_credential_cannot_borrow_a_cached_successful_identity(tmp_path):
    client, state = client_for(tmp_path)
    set_cookie_credentials(client)
    assert client.get("/api/rd/session").json()["actor_id"] == "engineer"
    set_cookie_credentials(client, token="synthetic-forged-credential")
    assert client.get("/api/rd/projects").status_code == 401
    assert len(state["calls"]) == 2
    set_cookie_credentials(client, userid="other-engineer")
    assert client.get("/api/rd/session").json()["actor_id"] == "other-engineer"
    assert state["calls"][-1] == ("other-engineer", 9086)


def test_callback_cache_survives_same_user_but_different_user_requires_verification(tmp_path):
    client, state = client_for(tmp_path)
    callback = client.get("/rd", params={"userid": "engineer", "token": "synthetic-valid-credential", "appid": "9086"})
    assert callback.status_code == 307 and "token" not in callback.headers["location"]
    assert client.get("/api/rd/session").json()["actor_id"] == "engineer"
    same = client.get("/rd", params={"userid": "engineer", "token": "synthetic-unrelated-query"})
    assert same.status_code == 307
    assert state["calls"] == [("engineer", 9086)]
    switch = client.get("/rd", params={"userid": "second-engineer", "token": "synthetic-valid-credential"})
    assert switch.status_code == 307
    assert client.get("/api/rd/session").json()["actor_id"] == "second-engineer"
    assert state["calls"] == [("engineer", 9086), ("second-engineer", 9086)]


def test_fresh_same_user_callback_can_replace_an_invalid_old_cookie(tmp_path):
    client, state = client_for(tmp_path)
    set_cookie_credentials(client, token="synthetic-expired-credential")
    callback = client.get("/rd", params={"userid": "engineer", "token": "synthetic-valid-credential"})
    assert callback.status_code == 307 and callback.headers["location"] == "https://research.example/rd"
    assert client.get("/api/rd/session").json()["actor_id"] == "engineer"
    assert state["calls"] == [("engineer", 9086), ("engineer", 9086)]


def test_expired_success_cache_rechecks_revoked_credential(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(auth, "time", SimpleNamespace(monotonic=lambda: now[0]))
    client, state = client_for(tmp_path)
    set_cookie_credentials(client)
    assert client.get("/api/rd/projects").status_code == 200
    state["valid"] = False
    now[0] = 161.0
    assert client.get("/api/rd/projects").status_code == 401
    assert state["calls"] == [("engineer", 9086), ("engineer", 9086)]


def test_unavailable_identity_is_not_authenticated_or_cached_and_can_retry(tmp_path):
    client, state = client_for(tmp_path)
    set_cookie_credentials(client)
    state["available"] = False
    assert client.get("/api/current-user").status_code == 503
    assert auth.COOKIE_TOKEN in client.cookies
    state["available"] = True
    response = client.get("/api/current-user")
    assert response.status_code == 200 and response.json()["user"]["display_name"] == "服务端确认姓名"
    assert len(state["calls"]) == 2


def test_disabling_cache_rechecks_each_private_request_and_logout_clears_session(tmp_path):
    client, state = client_for(tmp_path, cache_seconds=0)
    set_cookie_credentials(client)
    assert client.get("/api/rd/projects").status_code == 200
    assert client.get("/api/current-user").status_code == 200
    assert len(state["calls"]) == 2
    client.cookies.clear()
    client.get("/rd", params={"userid": "engineer", "token": "synthetic-valid-credential"})
    assert client.post("/api/system/logout").json() == {"success": True}
    assert client.get("/api/current-user").json()["authenticated"] is False
    assert client.get("/api/rd/projects").status_code == 401


def test_logout_removes_the_current_cached_verification(tmp_path):
    client, state = client_for(tmp_path)
    set_cookie_credentials(client)
    assert client.get("/api/current-user").status_code == 200
    assert len(state["calls"]) == 1
    assert client.post("/api/system/logout").status_code == 200
    assert client.get("/api/current-user").json()["authenticated"] is False
    set_cookie_credentials(client)
    assert client.get("/api/current-user").status_code == 200
    assert len(state["calls"]) == 2


def test_late_validation_cannot_repopulate_cache_after_logout():
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()
        state = {"calls": 0, "valid": True}

        async def verify(userid, token, appid):
            state["calls"] += 1
            accepted = state["valid"]
            if state["calls"] == 1:
                started.set()
                await release.wait()
            return {"code": 0, "data": {"sn": "服务端确认姓名"}} if accepted else None

        app = FastAPI()
        app.include_router(auth_router)
        app.add_middleware(auth.PlatformAuthMiddleware, settings=auth.AuthSettings(
            enabled=True, app_id=9086, public_url="https://research.example"), verifier=verify)
        cookie = "jtb_sv_userid=engineer; jtb_sv_token=synthetic-credential; jtb_sv_appid=9086"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://research.example") as client:
            pending = asyncio.create_task(client.get("/api/auth/me", headers={"Cookie": cookie}))
            await asyncio.wait_for(started.wait(), timeout=5)
            assert (await client.post("/api/system/logout", headers={"Cookie": cookie})).status_code == 200
            state["valid"] = False
            release.set()
            assert (await pending).status_code == 200
            assert (await client.get("/api/auth/me", headers={"Cookie": cookie})).status_code == 401
            assert state["calls"] == 2
    asyncio.run(exercise())


def test_all_research_endpoints_require_oa_identity_and_cannot_use_local_cookie(tmp_path):
    client, state = client_for(tmp_path)
    client.cookies.set("jtb_rd_local_client", "a" * 32)
    for route in rd_router.routes:
        path = route.path
        for name in route.param_convertors:
            path = path.replace("{" + name + "}", "missing")
        for method in route.methods:
            response = client.request(method, path, headers={"X-User": "owner", "X-User-Name": "forged-admin"})
            assert response.status_code == 401, (method, path, response.status_code)
    assert state["calls"] == []


def test_real_factory_protects_research_pages_and_binds_project_owner_to_oa(tmp_path, monkeypatch):
    monkeypatch.setenv("JTB_AUTH_SETTINGS_DB", str(tmp_path / "saved_auth.sqlite3"))
    monkeypatch.setenv("JTB_RD_DATA_DIR", str(tmp_path / "rd_data"))
    monkeypatch.setenv("JTB_AUTH_ENABLED", "true")
    monkeypatch.setenv("JTB_AUTH_APP_ID", "9086")
    monkeypatch.setenv("JTB_AUTH_PUBLIC_URL", "https://research.example")
    monkeypatch.setenv("JTB_AUTH_PLATFORM_BASE_URL", "https://login.example")

    async def verify(self, userid, token, appid):
        return {"code": 0, "data": {"sn": "服务端确认姓名"}} if token == "synthetic-valid-credential" else None

    monkeypatch.setattr(auth.PlatformTokenVerifier, "__call__", verify)
    from src.main import create_app
    client = TestClient(create_app(), base_url="https://research.example", follow_redirects=False)
    assert client.get("/rd").status_code == 307
    assert client.get("/rd/projects/missing").status_code == 307
    assert client.post("/api/rd/projects", json={"title": "研发项目"}).status_code == 401
    assert client.get("/rd", params={"userid": "engineer", "token": "synthetic-valid-credential"}).status_code == 307
    response = client.post("/api/rd/projects", json={"title": "研发项目"}, headers={"Idempotency-Key": "created"})
    assert response.status_code == 200
    assert response.json()["owner_id"] == "engineer"
    assert client.post("/api/system/logout").status_code == 200
    assert client.get("/api/rd/projects").status_code == 401
