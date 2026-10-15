"""The real taskbook factory binds verified login identity to feedback."""
import logging
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from src.common.logger import UvicornSafePathFilter
from src.common.platform_auth import PlatformTokenVerifier
from src.controller import feedback_controller, taskbook_controller
from src.main import create_app


def test_actual_factory_callback_identity_and_feedback_are_bound(tmp_path, monkeypatch):
    from jonhon_taskbook.feedback_store import FeedbackStore

    monkeypatch.setenv("JTB_AUTH_ENABLED", "true")
    monkeypatch.setenv("JTB_AUTH_APP_ID", "137")
    monkeypatch.setenv("JTB_AUTH_PUBLIC_URL", "https://taskbook.example")
    monkeypatch.setenv("JTB_AUTH_PLATFORM_BASE_URL", "https://login.example")
    verified_calls = []

    async def verify(self, userid, token, appid):
        verified_calls.append((userid, appid))
        assert token == "synthetic-login-token"
        return {"code": 0, "data": {"name": "张工程师"}}

    monkeypatch.setattr(PlatformTokenVerifier, "__call__", verify)
    state = taskbook_controller._RuntimeState()
    state.output_dir = tmp_path / "outputs"
    state.output_dir.mkdir()
    state.jobs["123456789a"] = {"status": "done", "result": {"meta": {"product_series": "CY"}}}
    monkeypatch.setattr(taskbook_controller, "_STATE", state)
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    monkeypatch.setattr(feedback_controller, "get_feedback_store", lambda: store)
    client = TestClient(create_app(), base_url="https://taskbook.example", follow_redirects=False)

    assert client.get("/api/current-user").json()["authenticated"] is False
    denied = client.post("/api/feedback", json={"username": "冒名用户"})
    assert denied.status_code == 401 and denied.json()["auth_required"] is True
    redirect = client.get("/")
    assert redirect.status_code == 302
    return_uri = parse_qs(urlsplit(redirect.headers["location"]).query)["redirect_uri"][0]
    nonce = parse_qs(urlsplit(return_uri).query)["_jtb_auth_state"][0]
    callback = client.get("/", params={"userid": "employee007", "token": "synthetic-login-token", "_jtb_auth_state": nonce})
    assert callback.status_code == 302 and callback.headers["location"] == "https://taskbook.example/"
    assert "token" not in callback.headers["location"]
    identity = client.get("/api/current-user")
    assert identity.status_code == 200 and identity.headers["cache-control"] == "no-store"
    assert identity.json()["user"]["display_name"] == "张工程师"
    submitted = client.post("/api/feedback", json={"jid": "123456789a", "rating": "good", "username": "冒名用户"},
                            headers={"X-User-Name": "forged-admin"})
    assert submitted.status_code == 200, submitted.text
    record = submitted.json()["record"]
    assert record["username"] == "张工程师"
    assert record["identity"] == {"userid": "employee007", "name": "张工程师", "source": "smartvision", "verified": True}
    assert record["snapshot"]["parameters"]["product_series"] == "CY"
    assert verified_calls == [("employee007", 137)]
    assert client.get("/api/feedback-admin").status_code == 404


def test_factory_disabled_identity_probe_and_manual_feedback_remain_local(monkeypatch):
    monkeypatch.setenv("JTB_AUTH_ENABLED", "false")
    client = TestClient(create_app(), follow_redirects=False)
    response = client.get("/api/current-user")
    assert response.status_code == 200
    assert response.json() == {"auth_enabled": False, "authenticated": False, "user": None}
    assert client.get("/auth/login").headers["location"] == "/"


def test_document_server_callbacks_keep_their_own_signature_verification(tmp_path, monkeypatch):
    from jonhon_taskbook.review_editor import EditorConfig, ReviewEditor

    from src.controller import review_editor_controller

    monkeypatch.setenv("JTB_AUTH_ENABLED", "true")
    monkeypatch.setenv("JTB_AUTH_APP_ID", "9192")
    monkeypatch.setenv("JTB_AUTH_PUBLIC_URL", "https://taskbook.example")
    editor = ReviewEditor(None, tmp_path, EditorConfig("http://editor.example", "http://editor.example",
                                                    "https://taskbook.example", "synthetic-editor-secret-with-32-characters"))
    monkeypatch.setattr(review_editor_controller, "_editor", lambda: editor)
    client = TestClient(create_app(), base_url="https://taskbook.example")
    prefix = "/api/review/123456789a/editor/" + "a" * 32
    file_response = client.get(prefix + "/file", params={"token": "invalid-signature"})
    callback = client.post(prefix + "/callback", json={"token": "invalid-signature"})
    assert file_response.status_code == 403 and "签名" in file_response.json()["detail"]
    assert callback.status_code == 403 and "签名" in callback.json()["message"]
    assert client.get(prefix).status_code == 401
    assert client.post(prefix + "/save").status_code == 401


def test_settings_save_is_staged_until_restart_and_private_manager_can_recover(tmp_path, monkeypatch):
    from src.feedback_main import create_app as create_management_app

    monkeypatch.setenv("JTB_AUTH_SETTINGS_DB", str(tmp_path / "auth_settings.sqlite3"))
    monkeypatch.setenv("JTB_AUTH_ENABLED", "false")
    monkeypatch.setenv("JTB_AUTH_APP_ID", "9192")
    monkeypatch.delenv("JTB_AUTH_PUBLIC_URL", raising=False)
    client = TestClient(create_app(), base_url="https://taskbook.example")
    settings = client.get("/api/settings/auth").json()
    assert settings["settings"]["public_url"] is None and settings["settings"]["app_id"] == 9192
    saved = client.put("/api/settings/auth", json={**settings["settings"], "enabled": True,
                       "public_url": "https://taskbook.example", "expected_version": settings["version"]},
                       headers={"X-Credential-Settings": "1", "Origin": "https://taskbook.example"})
    assert saved.status_code == 200 and saved.json()["requires_restart"] is True
    assert client.get("/api/current-user").json()["auth_enabled"] is False
    restarted = TestClient(create_app(), base_url="https://taskbook.example")
    assert restarted.get("/api/current-user").json()["auth_enabled"] is True
    assert restarted.put("/api/settings/auth", json={}).status_code == 401
    manager = TestClient(create_management_app(), base_url="http://manager.example")
    managed = manager.get("/api/settings/auth").json()
    assert managed["active"] is None and managed["can_edit"] is True
    recovered = manager.put("/api/settings/auth", json={**managed["settings"], "enabled": False,
                            "public_url": None, "expected_version": managed["version"]},
                            headers={"X-Credential-Settings": "1", "Origin": "http://manager.example"})
    assert recovered.status_code == 200
    assert TestClient(create_app()).get("/api/current-user").json()["auth_enabled"] is False


def test_uvicorn_access_log_omits_callback_query_but_keeps_diagnostic_path():
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:4242", "GET", "/review/123456789a?userid=test-user&token=synthetic-secret&_jtb_auth_state=nonce", "1.1", 302), None)
    assert UvicornSafePathFilter().filter(record)
    line = record.getMessage()
    assert "/review/123456789a" in line and "302" in line
    assert "synthetic-secret" not in line and "test-user" not in line and "nonce" not in line
