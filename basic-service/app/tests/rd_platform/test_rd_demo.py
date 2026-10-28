"""Explicit demo mode uses persistent business data, never external identity."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.platform_auth import AuthSettings, PlatformAuthMiddleware
from src.controller import auth_controller, rd_controller
from src.service.rd_platform.store import RdStore


@pytest.fixture
def isolated_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("JTB_DEMO_MODE", "true")
    monkeypatch.setenv("JTB_RD_DB", str(tmp_path / "demo.sqlite3"))
    monkeypatch.setenv("JTB_RD_ARTIFACTS", str(tmp_path / "artifacts"))
    return RdStore(tmp_path / "demo.sqlite3", tmp_path / "artifacts")


def app_with_demo_routes():
    from src.controller.demo_controller import router
    app = FastAPI()
    app.include_router(auth_controller.router)
    app.include_router(rd_controller.router)
    app.include_router(router)
    async def never_verify(*_):
        pytest.fail("Demo mode must never call OA")
    app.add_middleware(PlatformAuthMiddleware, settings=AuthSettings(enabled=True, public_url="https://login.example"), verifier=never_verify)
    return app


def test_explicit_demo_identity_bypasses_enabled_oa_and_switches_cookie(isolated_demo):
    with TestClient(app_with_demo_routes(), follow_redirects=False) as client:
        current = client.get("/api/current-user").json()
        assert current["authenticated"] is True
        assert current["auth_enabled"] is False
        assert current["demo_mode"] is True
        assert current["user"]["userid"] == "demo-owner"
        assert current["user"]["source"] == "mock"
        assert current["user"]["verified"] is True
        login = client.get("/auth/login?userid=oa-user&token=untrusted")
        assert login.status_code == 302 and login.headers["location"] == "/"
        switched = client.post("/api/demo/identity", json={"user_id": "demo-reviewer"})
        assert switched.status_code == 200
        cookie = switched.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        assert client.get("/api/current-user").json()["user"]["userid"] == "demo-reviewer"
        assert client.post("/api/demo/identity", json={"user_id": "forged-admin"}).status_code == 422
        client.cookies.set("jtb_demo_user", "forged-admin")
        assert client.get("/api/demo/status").json()["current_user_id"] == "demo-owner"


def test_demo_off_preserves_disabled_auth_and_does_not_offer_impersonation(tmp_path, monkeypatch):
    monkeypatch.delenv("JTB_DEMO_MODE", raising=False)
    from src.controller.demo_controller import router
    app = FastAPI()
    app.include_router(auth_controller.router)
    app.include_router(router)
    app.add_middleware(PlatformAuthMiddleware, settings=AuthSettings(enabled=False))
    with TestClient(app) as client:
        assert client.get("/api/current-user").json() == {"auth_enabled": False, "authenticated": False, "user": None}
        assert client.get("/api/demo/status").json() == {"enabled": False, "users": [], "current_user_id": None}
        assert client.post("/api/demo/identity", json={"user_id": "demo-owner"}).status_code == 404


def test_seed_survives_restart_without_duplicates_or_overwriting_user_changes(isolated_demo):
    from src.service.rd_platform.demo import ensure_demo_workspace
    ensure_demo_workspace(isolated_demo)
    listing = isolated_demo.list_projects("demo-owner")
    assert listing["total"] == 3
    details = [isolated_demo.detail(p["id"], "demo-owner") for p in listing["items"]]
    statuses = {t["status"] for d in details for t in d["tasks"]}
    assert {"todo", "in_progress", "in_review", "changes_requested", "done"} <= statuses
    approved = next((d, a) for d in details for a in d["artifacts"] if a["status"] == "approved")
    doc, artifact = approved
    fixed = isolated_demo.artifact(doc["project"]["id"], artifact["id"], "demo-reviewer", approved=True)
    assert fixed["quality_evidence"]["source"] == "mock"
    from docx import Document
    assert "演示数据" in "\n".join(p.text for p in Document(fixed["file_ref"]).paragraphs)
    before_events = sum(len(d["events"]) for d in details)
    d = details[0]
    actor = {"user_id": "demo-owner", "display_name": "演示负责人"}
    isolated_demo.execute(d["project"]["id"], actor, "save_requirement", {"title": "用户新增", "content": "保留", "source": "本地", "acceptance": "核对", "clarification": "open", "required": False}, d["project"]["version"], "user-edit")
    reopened = RdStore(isolated_demo.db_path, isolated_demo.artifact_root)
    ensure_demo_workspace(reopened)
    again = [reopened.detail(p["id"], "demo-owner") for p in reopened.list_projects("demo-owner")["items"]]
    assert len(again) == 3
    assert sum(len(d["events"]) for d in again) == before_events + 1
    assert any(r["title"] == "用户新增" for d in again for r in d["requirements"])


def test_seed_concurrent_startup_creates_one_copy(isolated_demo):
    from src.service.rd_platform.demo import ensure_demo_workspace
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: ensure_demo_workspace(isolated_demo), (1, 2)))
    assert isolated_demo.list_projects("demo-owner")["total"] == 3


def test_workspace_and_role_switch_use_current_membership(isolated_demo):
    from src.service.rd_platform.demo import ensure_demo_workspace
    ensure_demo_workspace(isolated_demo)
    with TestClient(app_with_demo_routes()) as client:
        response = client.get("/api/rd/workspace")
        assert response.status_code == 200
        details = response.json()["projects"]
        assert len(details) == 3
        d = details[0]
        client.post("/api/demo/identity", json={"user_id": "demo-viewer"})
        forbidden = client.post(f"/api/rd/projects/{d['project']['id']}/commands", json={"action": "confirm_baseline", "expected_version": d["project"]["version"], "payload": {}}, headers={"Idempotency-Key": "viewer-cannot-write"})
        assert forbidden.status_code == 403
        assert all(p["project"]["role"] == "viewer" for p in client.get("/api/rd/workspace").json()["projects"])
    outsider = isolated_demo.create_project({"user_id": "outsider", "display_name": "外部人"}, {"name": "不可见项目", "customer": "客户", "product": "产品"}, "outsider-project")
    assert all(p["project"]["id"] != outsider["project"]["id"] for p in isolated_demo.workspace("demo-owner")["projects"])


def test_demo_default_database_is_separate_and_flag_does_not_seed_real_database(tmp_path, monkeypatch):
    monkeypatch.delenv("JTB_RD_DB", raising=False)
    monkeypatch.delenv("JTB_RD_ARTIFACTS", raising=False)
    monkeypatch.setenv("JTB_DEMO_MODE", "false")
    real = rd_controller.get_store()
    monkeypatch.setenv("JTB_DEMO_MODE", "true")
    demo = rd_controller.get_store()
    assert demo.db_path != real.db_path
    assert demo.artifact_root != real.artifact_root
    monkeypatch.setenv("JTB_DEMO_MODE", "false")
    from src.service.rd_platform.demo import ensure_demo_workspace
    empty = RdStore(tmp_path / "real.sqlite3")
    ensure_demo_workspace(empty)
    assert empty.list_projects("demo-owner")["total"] == 0


def test_disabled_demo_endpoints_keep_disabled_contract_with_real_auth_enabled(monkeypatch):
    monkeypatch.setenv("JTB_DEMO_MODE", "false")
    with TestClient(app_with_demo_routes()) as client:
        status = client.get("/api/demo/status")
        assert status.status_code == 200
        assert status.json()["enabled"] is False
        assert client.post("/api/demo/identity", json={"user_id": "demo-owner"}).status_code == 404


def test_saved_enabled_oa_profile_is_bypassed_in_demo(isolated_demo, tmp_path, monkeypatch):
    from src.common.auth_settings_store import AuthSettingsStore
    from src.controller.demo_controller import router
    path = tmp_path / "saved-auth.sqlite3"
    monkeypatch.setenv("JTB_AUTH_SETTINGS_DB", str(path))
    AuthSettingsStore(path).save({"enabled": True, "app_id": 127, "platform_base_url": "https://oa.example", "public_url": "https://saved.example"}, expected_version=0)
    app = FastAPI()
    app.include_router(auth_controller.router)
    app.include_router(router)
    async def never_verify(*_):
        pytest.fail("Saved real OA profile must not trigger network in demo")
    app.add_middleware(PlatformAuthMiddleware, verifier=never_verify)
    with TestClient(app, follow_redirects=False) as client:
        client.cookies.set("jtb_sv_userid", "real-employee")
        client.cookies.set("jtb_sv_token", "ignored-real-token")
        assert client.get("/api/current-user").json()["user"]["userid"] == "demo-owner"
        assert client.get("/auth/login").headers["location"] == "/"


def test_interrupted_seed_resumes_without_duplicate_business_records(isolated_demo, monkeypatch):
    from src.service.rd_platform.demo import ensure_demo_workspace
    original = isolated_demo.execute
    def interrupted(pid, actor, action, payload, expected_version, request_key):
        if action == "submit_review":
            raise RuntimeError("simulated startup interruption")
        return original(pid, actor, action, payload, expected_version, request_key)
    monkeypatch.setattr(isolated_demo, "execute", interrupted)
    with pytest.raises(RuntimeError, match="startup interruption"):
        ensure_demo_workspace(isolated_demo)
    monkeypatch.setattr(isolated_demo, "execute", original)
    ensure_demo_workspace(isolated_demo)
    details = isolated_demo.workspace("demo-owner")["projects"]
    assert len(details) == 3
    assert sum(len(d["tasks"]) for d in details) == 6
    assert sum(len(d["artifacts"]) for d in details) == 3


def test_legacy_admin_demo_identity_and_login_never_use_oa(isolated_demo):
    from src.common.admin_auth import AdminAuthMiddleware
    from src.controller.admin_auth_controller import router
    app = FastAPI()
    app.include_router(router)
    app.state.admin_auth_settings = AuthSettings(enabled=True, public_url="https://real-management.example")
    async def never_verify(*_):
        pytest.fail("Demo admin must not call OA")
    app.state.admin_token_verifier = never_verify
    # No admin store is provided: demo login/session must not even query the
    # real admin allowlist or establish a real opaque OA session.
    app.add_middleware(AdminAuthMiddleware)
    with TestClient(app, follow_redirects=False) as client:
        session = client.get("/api/admin/session")
        assert session.status_code == 200
        assert session.json()["demo_mode"] is True
        assert session.json()["user"]["userid"] == "demo-owner"
        assert session.json()["user"]["source"] == "mock"
        assert session.json()["can_manage_admins"] is True
        assert client.get("/admin/auth/login").headers["location"] == "/admin"
        assert client.get("/admin/auth/callback?userid=real&token=ignored").headers["location"] == "/admin"
        assert client.post("/api/admin/logout").status_code == 200
        client.cookies.set("jtb_demo_user", "demo-reviewer")
        assert client.get("/api/admin/session").json()["can_manage_admins"] is False
