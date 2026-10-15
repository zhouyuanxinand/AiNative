"""Persist desired login configuration without changing the active middleware."""
from __future__ import annotations

import importlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

URL = "/api/settings/auth"
HEADERS = {"X-Credential-Settings": "1", "Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}
DEFAULTS = {"enabled": False, "app_id": 9192, "platform_base_url": "http://platform.internal", "public_url": None}


def fields(**changes):
    return {**DEFAULTS, "expected_version": 0, **changes}


@pytest.fixture
def api(tmp_path, monkeypatch):
    auth = importlib.import_module("src.common.platform_auth")
    store_module = importlib.import_module("src.common.auth_settings_store")
    controller = importlib.import_module("src.controller.auth_settings_controller")
    path = tmp_path / "auth_settings.sqlite3"
    monkeypatch.setenv("JTB_AUTH_SETTINGS_DB", str(path))
    monkeypatch.setattr(auth, "_auth_environment", lambda: {
        "JTB_AUTH_ENABLED": "false", "JTB_AUTH_APP_ID": "9192",
        "JTB_AUTH_PLATFORM_BASE_URL": "http://platform.internal",
    })
    with ExitStack() as stack:
        def make(*, enabled=False, admin=False):
            active = auth.AuthSettings(**{**DEFAULTS, "enabled": enabled, "public_url": "https://active.example" if enabled else None})
            application = FastAPI()
            application.state.auth_settings = active
            application.state.auth_settings_admin = admin
            application.include_router(controller.router)
            return stack.enter_context(TestClient(application))

        yield make, store_module, path, auth


def test_initial_get_reports_environment_defaults_without_creating_a_profile_or_database(api):
    make, _, path, _ = api
    response = make().get(URL)
    assert response.status_code == 200
    assert response.json() == {"settings": DEFAULTS, "active": DEFAULTS, "version": 0, "can_edit": True, "requires_restart": False}
    assert response.headers["cache-control"] == "no-store"
    assert not path.exists()


def test_disabled_profile_accepts_unknown_deployment_address_and_persists_across_stores(api):
    make, store_module, path, _ = api
    client = make()
    response = client.put(URL, json=fields(public_url=""), headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json() == {"settings": DEFAULTS, "active": DEFAULTS, "version": 1, "can_edit": True, "requires_restart": False}
    assert store_module.AuthSettingsStore(path).read() == {"settings": DEFAULTS, "version": 1}
    assert client.get(URL).json()["version"] == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM auth_settings").fetchone()[0] == 1


def test_disabled_profile_can_clear_the_application_id_until_deployment_is_ready(api):
    make, _, _, auth = api
    response = make().put(URL, json=fields(app_id=None), headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["settings"] == {**DEFAULTS, "app_id": None}
    loaded = auth.AuthSettings.from_env()
    assert loaded.enabled is False and loaded.app_id is None and loaded.public_url is None


@pytest.mark.parametrize("public_url", [None, "", "//evil.example", "https://example.test/path", "javascript:alert(1)"])
def test_enabling_auth_rejects_a_missing_or_invalid_origin_before_any_write(api, public_url):
    make, _, path, _ = api
    response = make().put(URL, json=fields(enabled=True, public_url=public_url), headers=HEADERS)
    assert response.status_code == 400 and "error" in response.json()
    assert not path.exists()


@pytest.mark.parametrize("app_id", [None, "", 0])
def test_enabling_auth_requires_a_positive_application_id(api, app_id):
    make, _, path, _ = api
    response = make().put(URL, json=fields(enabled=True, app_id=app_id, public_url="https://taskbook.example"), headers=HEADERS)
    assert response.status_code == 400
    assert not path.exists()


def test_saving_enabled_profile_requires_restart_and_preserves_the_active_local_mode(api):
    make, _, _, auth = api
    client = make()
    response = client.put(URL, json=fields(enabled=True, app_id="9192", public_url="https://taskbook.example/"), headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["settings"] == {**DEFAULTS, "enabled": True, "public_url": "https://taskbook.example"}
    assert body["active"] == DEFAULTS and body["requires_restart"] is True
    assert client.app.state.auth_settings.enabled is False
    restarted = auth.AuthSettings.from_env()
    assert restarted.enabled and restarted.app_id == 9192 and restarted.public_url == "https://taskbook.example"


def test_enabled_public_application_cannot_disable_login_even_with_valid_write_headers(api):
    make, _, path, _ = api
    client = make(enabled=True)
    response = client.get(URL)
    assert response.status_code == 200 and response.json()["can_edit"] is False
    denied = client.put(URL, json=fields(), headers=HEADERS)
    assert denied.status_code == 403
    assert not path.exists()


def test_private_management_can_save_but_does_not_claim_the_main_app_active_state(api):
    make, _, _, _ = api
    client = make(enabled=True, admin=True)
    initial = client.get(URL).json()
    assert initial["active"] is None and initial["can_edit"] is True and initial["requires_restart"] is False
    response = client.put(URL, json=fields(), headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["active"] is None and response.json()["requires_restart"] is True


@pytest.mark.parametrize("headers", [
    {}, {"Origin": "http://testserver"}, {"X-Credential-Settings": "1"},
    {**HEADERS, "Origin": "https://evil.example"}, {**HEADERS, "Origin": "null"},
    {**HEADERS, "Sec-Fetch-Site": "cross-site"},
])
def test_setting_mutations_require_the_settings_marker_and_same_origin(api, headers):
    make, _, path, _ = api
    response = make().put(URL, json=fields(), headers=headers)
    assert response.status_code == 403 and "error" in response.json()
    assert not path.exists()


@pytest.mark.parametrize("change", [
    {"token": "synthetic-secret"}, {"enabled": "true"}, {"app_id": "invalid"},
    {"app_id": True}, {"platform_base_url": "file:///private"},
    {"expected_version": True}, {"expected_version": -1}, {"expected_version": "0"},
])
def test_invalid_or_unknown_configuration_fields_are_rejected_before_writing(api, change):
    make, _, path, _ = api
    response = make().put(URL, json=fields(**change), headers=HEADERS)
    assert response.status_code == 400 and "error" in response.json()
    assert "synthetic-secret" not in response.text
    assert not path.exists()


def test_invalid_json_or_incomplete_profile_is_reported_as_chinese_400(api):
    make, _, _, _ = api
    client = make()
    for arguments in ({"content": "{"}, {"json": []}, {"json": {"enabled": False}}):
        response = client.put(URL, headers=HEADERS, **arguments)
        assert response.status_code == 400
        assert any("\u4e00" <= char <= "\u9fff" for char in response.json()["error"])


def test_excessively_nested_json_is_rejected_as_invalid_settings_without_writing(api):
    make, _, path, _ = api
    response = make().put(URL, headers=HEADERS, content="[" * 20000 + "0" + "]" * 20000)
    assert response.status_code == 400
    assert any("\u4e00" <= char <= "\u9fff" for char in response.json()["error"])
    assert not path.exists()


def test_version_conflict_does_not_overwrite_the_saved_profile(api):
    make, _, _, _ = api
    client = make()
    assert client.put(URL, json=fields(), headers=HEADERS).status_code == 200
    conflict = client.put(URL, json=fields(app_id=9999), headers=HEADERS)
    assert conflict.status_code == 409 and "error" in conflict.json()
    assert client.get(URL).json()["settings"]["app_id"] == 9192


def test_simultaneous_writers_cannot_both_replace_version_zero(api):
    _, store_module, path, _ = api

    def save(app_id):
        try:
            store_module.AuthSettingsStore(path).save({**DEFAULTS, "app_id": app_id}, expected_version=0)
            return "saved"
        except store_module.AuthSettingsConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(save, [9192, 9193])) == ["conflict", "saved"]
    assert store_module.AuthSettingsStore(path).read()["version"] == 1


def test_saved_profile_overrides_environment_but_keeps_runtime_tuning_from_environment(api, monkeypatch):
    _, store_module, path, auth = api
    store_module.AuthSettingsStore(path).save({**DEFAULTS, "enabled": True, "public_url": "https://saved.example"}, expected_version=0)
    monkeypatch.setattr(auth, "_auth_environment", lambda: {
        "JTB_AUTH_ENABLED": "false", "JTB_AUTH_APP_ID": "123",
        "JTB_AUTH_PLATFORM_BASE_URL": "http://old.example", "JTB_AUTH_TIMEOUT_SECONDS": "4.5", "JTB_AUTH_CACHE_SECONDS": "0",
    })
    loaded = auth.AuthSettings.from_env()
    assert loaded.enabled and loaded.app_id == 9192 and loaded.platform_base_url == "http://platform.internal"
    assert loaded.public_url == "https://saved.example" and loaded.timeout_seconds == 4.5 and loaded.cache_seconds == 0


def test_saved_local_choice_can_disable_incomplete_deployment_auth_defaults(api, monkeypatch):
    _, store_module, path, auth = api
    store_module.AuthSettingsStore(path).save(DEFAULTS, expected_version=0)
    monkeypatch.setattr(auth, "_auth_environment", lambda: {"JTB_AUTH_ENABLED": "true"})
    loaded = auth.AuthSettings.from_env()
    assert loaded.enabled is False and loaded.app_id == 9192 and loaded.public_url is None


def test_explicit_environment_dictionary_never_reads_saved_configuration(api, monkeypatch):
    _, store_module, _, auth = api

    def forbidden_read():
        pytest.fail("Explicit environment dictionaries must not read the settings database")

    monkeypatch.setattr(store_module, "get_auth_settings_store", forbidden_read)
    assert auth.AuthSettings.from_env({}).enabled is False


def test_corrupt_database_produces_redacted_storage_error(api):
    make, _, path, _ = api
    path.write_bytes(b"not a SQLite database")
    response = make().get(URL)
    assert response.status_code == 503 and "error" in response.json()
    assert str(path) not in response.text
    denied_save = make().put(URL, json=fields(), headers=HEADERS)
    assert denied_save.status_code == 503 and str(path) not in denied_save.text
