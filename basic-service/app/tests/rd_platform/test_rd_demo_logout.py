"""Mock application logout must not silently recreate the default owner."""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.common.platform_auth import AuthSettings, PlatformAuthMiddleware, get_current_user
from src.controller import auth_controller, demo_controller


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("JTB_DEMO_MODE", "true")
    app = FastAPI()
    app.include_router(auth_controller.router)
    app.include_router(demo_controller.router)

    @app.get("/api/protected")
    async def protected(request: Request):
        user = get_current_user(request)
        return {"userid": user["userid"] if user else None}

    app.add_middleware(PlatformAuthMiddleware, settings=AuthSettings(enabled=False))
    with TestClient(app, follow_redirects=False) as result:
        yield result


def test_mock_logout_clears_identity_and_stays_logged_out_until_explicit_reentry(client):
    client.post("/api/demo/identity", json={"user_id": "demo-reviewer"})
    assert client.get("/api/protected").json()["userid"] == "demo-reviewer"
    response = client.post("/api/system/logout")
    assert response.json() == {"success": True}
    current = client.get("/api/current-user").json()
    assert current["authenticated"] is False and current["user"] is None
    assert current["demo_mode"] is True
    assert client.get("/api/protected").status_code == 401
    assert client.get("/api/settings/credentials", headers={"X-Credential-Settings": "1"}).status_code == 401
    assert client.get("/").headers["location"] == "/logged-out"
    page = client.get("/logged-out")
    assert page.status_code == 200 and 'href="/auth/login"' in page.text
    # Reading the logged-out page and identity never logs the browser back in.
    assert client.get("/api/current-user").json()["user"] is None
    login = client.get("/auth/login")
    assert login.status_code == 302 and login.headers["location"] == "/"
    assert client.get("/api/current-user").json()["user"]["userid"] == "demo-owner"


def test_explicit_role_selection_can_start_a_new_mock_session(client):
    client.post("/api/system/logout")
    assert client.get("/api/demo/status").json()["current_user_id"] is None
    assert client.post("/api/demo/identity", json={"user_id": "demo-engineer"}).status_code == 200
    assert client.get("/api/current-user").json()["user"]["userid"] == "demo-engineer"
