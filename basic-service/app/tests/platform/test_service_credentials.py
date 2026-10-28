"""Exercise saved credentials through settings, catalog and actual LLM request boundaries."""
import os
import json
import sqlite3
from copy import deepcopy

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jonhon_taskbook import llm_client as llm
from jonhon_taskbook.service_credentials import FIELDS, ServiceCredentialStore
from src.controller.service_credentials_controller import router as settings_router
from src.controller.taskbook_controller import router as taskbook_router

URL = "/api/settings/credentials"
HEADERS = {"X-Credential-Settings": "1"}


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith(("MODEL_", "AI_", "JTB_", "AZURE_", "OPENAI_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("MODEL_BASE_URL", "https://default.example/open/")
    monkeypatch.setenv("MODEL_APP_ID", "default-app")
    monkeypatch.setenv("MODEL_API_KEY", "default-secret")
    monkeypatch.setenv("MODEL_TENANT_ID", "default-tenant")
    monkeypatch.setenv("MODEL_NAME", "default-model")
    path = tmp_path / "credentials.sqlite3"
    monkeypatch.setenv("JTB_SERVICE_CREDENTIALS_DB", str(path))
    monkeypatch.setattr(llm, "_runtime_config", None)
    monkeypatch.setattr(llm, "_azure_client", None)
    monkeypatch.setattr(llm, "_azure_client_signature", None)
    app = FastAPI()
    app.include_router(settings_router)
    app.include_router(taskbook_router)
    return TestClient(app), path


def overrides(**values):
    return {provider: values.get(provider) for provider in FIELDS}


def gateway():
    return {"base_url": "https://saved.example/open/", "app_id": "saved-app",
            "api_key": "saved-secret", "tenant_id": "saved-tenant"}


def test_defaults_bootstrap_history_and_require_same_site(settings):
    client, path = settings
    for headers in ({}, {**HEADERS, "Sec-Fetch-Site": "cross-site"}):
        response = client.get(URL, headers=headers)
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"
        assert "default-secret" not in response.text
    response = client.get(URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["defaults"] == data["effective"]
    assert data["overridden"] == []
    assert set(data["defaults"]) == {"model"}
    assert data["defaults"]["model"]["base_url"] == "https://default.example/open/"
    assert data["defaults"]["model"]["api_key"] == "default-secret"
    assert path.exists()
    assert len(data["history"]) == 1
    assert data["history"][0]["name"] == "部署默认凭证"
    assert data["history"][0]["active"] is True
    assert "api_key" not in data["history"][0]
    assert ServiceCredentialStore(path).read() is None


def test_saved_gateway_survives_new_store_and_drives_catalog_and_chat(settings, monkeypatch, caplog):
    client, path = settings
    response = client.put(URL, headers=HEADERS, json=overrides(model=gateway()))
    assert response.status_code == 200
    assert response.json()["defaults"]["model"]["api_key"] == "default-secret"
    assert ServiceCredentialStore(path).read()["model"] == gateway()
    # A new service/store read uses persisted values without changing deployment defaults.
    monkeypatch.setattr(llm, "_runtime_config", None)
    assert llm.get_status()["source"] == "settings"
    requests = []

    def catalog(url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request("GET", url),
                              json={"data": [{"id": "123", "model": "saved-model"}]})

    def chat(url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]})

    monkeypatch.setattr(llm.httpx, "get", catalog)
    monkeypatch.setattr(llm.httpx, "post", chat)
    models = client.get("/api/models").json()
    assert any(item["model"] == "saved-model" for item in models["models"])
    with llm.model_scope("smartvision", "saved-model", "123"):
        assert llm.chat("system", "user") == "OK"
    assert [url for url, _ in requests] == [
        "https://saved.example/open/opi-maas/v1/chat/models",
        "https://saved.example/open/opi-maas/v1/chat/completions",
    ]
    for _, kwargs in requests:
        assert kwargs["headers"]["App-Id"] == "saved-app"
        assert kwargs["headers"]["Api-Key"] == "saved-secret"
        assert kwargs["headers"]["Tenant-Id"] == "saved-tenant"
    assert "saved-secret" not in client.get("/api/llm/status").text
    assert "saved-secret" not in str(models)
    assert "saved-secret" not in caplog.text


@pytest.mark.parametrize("gateway_result, error_code", [
    ("connect", "connection_failed"),
    ("unauthorized", "authentication_failed"),
    ("malformed", "invalid_response"),
])
def test_model_catalog_reports_gateway_failure_instead_of_successful_empty_list(
    settings, monkeypatch, caplog, gateway_result, error_code,
):
    client, _ = settings

    def catalog(url, **kwargs):
        request = httpx.Request("GET", url)
        if gateway_result == "connect":
            raise httpx.ConnectError("default-secret private transport details", request=request)
        if gateway_result == "unauthorized":
            return httpx.Response(403, request=request, text="default-secret private gateway details")
        return httpx.Response(200, request=request, json={"unexpected": "default-secret"})

    monkeypatch.setattr(llm.httpx, "get", catalog)
    response = client.get("/api/models")
    assert response.status_code in {502, 503}
    assert response.json()["success"] is False
    assert response.json()["models"] == []
    assert response.json()["error_code"] == error_code
    assert "default-secret" not in response.text + caplog.text


@pytest.mark.parametrize("provider,env,model,endpoint", [
    ("dashscope", {"AI_API_URL": "https://dash.example/v1/chat/completions", "AI_API_KEY": "other-key", "AI_MODEL": "qwen"}, "qwen", "https://dash.example/v1/chat/completions"),
    ("azure", {"AZURE_OPENAI_ENDPOINT": "https://azure.example", "AZURE_OPENAI_API_KEY": "other-key", "AZURE_OPENAI_DEPLOYMENT": "deploy"}, "deploy", "https://azure.example"),
    ("openai_compatible", {"OPENAI_BASE_URL": "https://compatible.example/v1", "OPENAI_API_KEY": "other-key", "OPENAI_MODEL": "model"}, "model", "https://compatible.example/v1/chat/completions"),
])
def test_model_settings_preserve_other_deployment_providers(settings, monkeypatch, provider, env, model, endpoint):
    client, _ = settings
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert client.put(URL, headers=HEADERS, json=overrides(model=gateway())).status_code == 200
    config = llm._resolve_model_config(llm.ModelSelection(provider, model))
    assert config.api_key == "other-key"
    assert config.endpoint == endpoint
    assert config.source == "environment"


def test_restore_defaults_tracks_rotated_deployment_values(settings, monkeypatch):
    client, path = settings
    client.put(URL, headers=HEADERS, json=overrides(model=gateway()))
    monkeypatch.setenv("MODEL_API_KEY", "rotated-default")
    response = client.put(URL, headers=HEADERS, json=overrides())
    assert response.status_code == 200
    assert response.json()["overridden"] == []
    assert response.json()["effective"]["model"]["api_key"] == "rotated-default"
    assert llm._resolve_model_config(llm.ModelSelection("smartvision", "any-model")).api_key == "rotated-default"
    assert ServiceCredentialStore(path).read() == {"model": None}


@pytest.mark.parametrize("url", ["", "file:///etc/passwd", "https://user:secret@example.com", "https://host:wrong/open", "https://host/open?key=secret", "https://host/open\n"])
def test_invalid_save_is_atomic_and_never_echoes_credentials(settings, url):
    client, path = settings
    payload = overrides(model=gateway())
    client.put(URL, headers=HEADERS, json=payload)
    changed = deepcopy(payload)
    changed["model"]["base_url"] = url
    changed["model"]["api_key"] = "private-invalid-secret"
    response = client.put(URL, headers=HEADERS, json=changed)
    assert response.status_code == 400
    assert "private-invalid-secret" not in response.text
    assert ServiceCredentialStore(path).read() == payload


def test_write_failure_does_not_clear_current_config_or_report_success(settings, monkeypatch):
    client, path = settings
    runtime = llm.make_config(provider="dashscope", endpoint="https://old.example/chat/completions",
                              api_key="runtime-secret", model="old-model")
    llm.configure_runtime(runtime, verify=False)

    def fail(*args):
        raise PermissionError("no permission")

    monkeypatch.setattr(ServiceCredentialStore, "save", fail)
    response = client.put(URL, headers=HEADERS, json=overrides(model=gateway()))
    assert response.status_code == 503
    assert llm.get_status()["source"] == "runtime"
    assert not path.exists()


def test_save_archives_default_and_deduplicates_only_identical_complete_credentials(settings):
    client, path = settings
    first = client.put(URL, headers=HEADERS, json=overrides(model=gateway())).json()
    assert len(first["history"]) == 2  # Saving before ever opening settings still archives defaults.
    second = client.put(URL, headers=HEADERS, json=overrides(model=gateway())).json()
    assert {row["id"] for row in first["history"]} == {row["id"] for row in second["history"]}
    rotated = {**gateway(), "api_key": "rotated-saved-secret"}
    third = client.put(URL, headers=HEADERS, json=overrides(model=rotated)).json()
    assert len(third["history"]) == 3
    assert sum(row["active"] for row in third["history"]) == 1
    assert not any(key in json.dumps(third["history"]) for key in ("default-secret", "saved-secret", "api_key"))
    assert ServiceCredentialStore(path).view(llm.get_service_credential_defaults())["history"] == third["history"]
    restored = client.put(URL, headers=HEADERS, json=overrides()).json()
    assert len(restored["history"]) == 3
    assert next(row for row in restored["history"] if row["active"])["source"] == "deployment"


def test_history_activation_switches_catalog_and_chat_and_clears_runtime(settings, monkeypatch, caplog):
    client, path = settings
    saved = client.put(URL, headers=HEADERS, json=overrides(model=gateway())).json()
    saved_id = next(row["id"] for row in saved["history"] if row["active"])
    client.put(URL, headers=HEADERS, json=overrides())
    llm.configure_runtime(llm.make_config(
        provider="dashscope", endpoint="https://old.example/v1/chat/completions",
        api_key="old-runtime-secret", model="stale-model",
    ), verify=False)
    response = client.post(f"{URL}/history/{saved_id}/activate", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["effective"]["model"] == gateway()
    assert response.json()["overridden"] == ["model"]
    assert next(row for row in response.json()["history"] if row["active"])["last_used_at"]
    assert ServiceCredentialStore(path).read() == overrides(model=gateway())
    assert llm.get_status()["source"] == "settings"
    calls = []

    def catalog(url, **kwargs):
        calls.append((url, kwargs["headers"]))
        return httpx.Response(200, request=httpx.Request("GET", url), json={
            "data": [{"id": "222", "model": "history-model"}],
        })

    def chat(url, **kwargs):
        calls.append((url, kwargs["headers"]))
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": "history response"}, "finish_reason": "stop"}],
        })

    monkeypatch.setattr(llm.httpx, "get", catalog)
    monkeypatch.setattr(llm.httpx, "post", chat)
    models = client.get("/api/models")
    assert any(model["model"] == "history-model" for model in models.json()["models"])
    with llm.model_scope("smartvision", "history-model", "222"):
        assert llm.chat("system", "user") == "history response"
    assert [url for url, _ in calls] == [
        "https://saved.example/open/opi-maas/v1/chat/models",
        "https://saved.example/open/opi-maas/v1/chat/completions",
    ]
    assert all(headers["Api-Key"] == "saved-secret" and headers["App-Id"] == "saved-app"
               and headers["Tenant-Id"] == "saved-tenant" for _, headers in calls)
    assert "saved-secret" not in models.text
    assert "saved-secret" not in client.get("/api/llm/status").text
    assert "saved-secret" not in caplog.text


def test_preset_import_survives_restart_and_deleted_presets_stay_deleted(settings, monkeypatch):
    client, path = settings
    monkeypatch.setenv("JTB_SERVICE_CREDENTIAL_PRESETS", json.dumps([
        {"name": "内网环境", "model": gateway()},
        {"name": "内网环境", "model": gateway()},
    ]))
    first = client.get(URL, headers=HEADERS).json()
    assert first["effective"] == first["defaults"]
    assert ServiceCredentialStore(path).read() is None
    assert len(first["history"]) == 2
    preset = next(row for row in first["history"] if row["source"] == "preset")
    assert preset["name"] == "内网环境"
    assert preset["active"] is False
    assert preset["last_used_at"] is None
    second = ServiceCredentialStore(path).view(llm.get_service_credential_defaults())
    assert second["history"] == first["history"]
    deleted = client.delete(f"{URL}/history/{preset['id']}", headers=HEADERS)
    assert deleted.status_code == 200
    assert len(deleted.json()["history"]) == 1
    restarted = ServiceCredentialStore(path).view(llm.get_service_credential_defaults())
    assert len(restarted["history"]) == 1
    assert client.post(f"{URL}/history/{preset['id']}/activate", headers=HEADERS).status_code == 404
    # A rotated secret is a new preset even when its visible fields and name are unchanged.
    monkeypatch.setenv("JTB_SERVICE_CREDENTIAL_PRESETS", json.dumps([
        {"name": "内网环境", "model": {**gateway(), "api_key": "new-preset-secret"}},
    ]))
    rotated = client.get(URL, headers=HEADERS).json()
    assert len(rotated["history"]) == 2
    assert next(row for row in rotated["history"] if row["source"] == "preset")["id"] != preset["id"]


def test_active_deletion_rejected_and_inactive_deletion_preserves_connection(settings):
    client, path = settings
    data = client.put(URL, headers=HEADERS, json=overrides(model=gateway())).json()
    active = next(row for row in data["history"] if row["active"])
    inactive = next(row for row in data["history"] if not row["active"])
    response = client.delete(f"{URL}/history/{active['id']}", headers=HEADERS)
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert "saved-secret" not in response.text
    assert client.delete(f"{URL}/history/{inactive['id']}", headers=HEADERS).status_code == 200
    assert ServiceCredentialStore(path).read() == overrides(model=gateway())
    assert len(client.get(URL, headers=HEADERS).json()["history"]) == 1


@pytest.mark.parametrize("method,suffix", [("post", "/activate"), ("delete", "")])
def test_history_mutations_require_same_site_and_do_not_echo_unknown_ids(settings, method, suffix):
    client, path = settings
    call = getattr(client, method)
    for headers in ({}, {**HEADERS, "Sec-Fetch-Site": "cross-site"}):
        response = call(f"{URL}/history/private-unknown-secret{suffix}", headers=headers)
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"
        assert "private-unknown-secret" not in response.text
    assert not path.exists()
    response = call(f"{URL}/history/private-unknown-secret{suffix}", headers=HEADERS)
    assert response.status_code == 404
    assert "private-unknown-secret" not in response.text


def test_legacy_single_row_migrates_without_losing_credentials(settings):
    client, path = settings
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE service_credentials (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        connection.execute("INSERT INTO service_credentials VALUES (1, ?)", (json.dumps(overrides(model=gateway())),))
    data = client.get(URL, headers=HEADERS).json()
    assert data["effective"]["model"] == gateway()
    assert len(data["history"]) == 2
    assert next(row for row in data["history"] if row["active"])["base_url"] == gateway()["base_url"]
    assert ServiceCredentialStore(path).read() == overrides(model=gateway())


def test_history_only_database_does_not_break_runtime_reads(settings):
    client, path = settings
    client.get(URL, headers=HEADERS)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE service_credentials")
    assert ServiceCredentialStore(path).read() is None
    assert llm._resolve_model_config(llm.ModelSelection("smartvision", "any-model")).api_key == "default-secret"
    assert len(client.get(URL, headers=HEADERS).json()["history"]) == 1


def test_save_and_activation_failure_roll_back_both_active_row_and_history(settings, monkeypatch):
    client, path = settings
    original = client.put(URL, headers=HEADERS, json=overrides(model=gateway())).json()
    default_id = next(row["id"] for row in original["history"] if not row["active"])
    real_snapshot = ServiceCredentialStore._snapshot

    def fail_after_write(connection, model, **kwargs):
        real_snapshot(connection, model, **kwargs)
        if kwargs.get("used"):
            raise sqlite3.OperationalError("synthetic transaction failure")

    monkeypatch.setattr(ServiceCredentialStore, "_snapshot", staticmethod(fail_after_write))
    response = client.put(URL, headers=HEADERS, json=overrides(model={**gateway(), "api_key": "failed-secret"}))
    assert response.status_code == 503
    assert "failed-secret" not in response.text
    assert ServiceCredentialStore(path).read() == overrides(model=gateway())
    assert client.get(URL, headers=HEADERS).json()["history"] == original["history"]
    response = client.post(f"{URL}/history/{default_id}/activate", headers=HEADERS)
    assert response.status_code == 503
    assert ServiceCredentialStore(path).read() == overrides(model=gateway())
    assert client.get(URL, headers=HEADERS).json()["history"] == original["history"]


def test_missing_default_credentials_allow_preset_history_without_activation(settings, monkeypatch):
    client, path = settings
    monkeypatch.delenv("MODEL_API_KEY")
    monkeypatch.setenv("JTB_SERVICE_CREDENTIAL_PRESETS", json.dumps([{"name": "内网环境", "model": gateway()}]))
    response = client.get(URL, headers=HEADERS)
    assert response.status_code == 200
    assert len(response.json()["history"]) == 1
    assert response.json()["history"][0]["active"] is False
    assert ServiceCredentialStore(path).read() is None


def test_activation_checks_runtime_compatibility_before_changing_active_credentials(settings, monkeypatch):
    client, path = settings
    initial = client.put(URL, headers=HEADERS, json=overrides(model=gateway())).json()
    target = next(row for row in initial["history"] if not row["active"])

    def incompatible(payload):
        assert payload["model"]["base_url"] == "https://default.example/open/"
        raise ValueError("synthetic invalid runtime config")

    monkeypatch.setattr(llm, "validate_service_credentials", incompatible)
    response = client.post(f"{URL}/history/{target['id']}/activate", headers=HEADERS)
    assert response.status_code == 503
    assert ServiceCredentialStore(path).read() == overrides(model=gateway())
    assert client.get(URL, headers=HEADERS).json()["history"] == initial["history"]


def test_runtime_reads_work_while_a_history_write_transaction_is_pending(settings):
    client, path = settings
    client.put(URL, headers=HEADERS, json=overrides(model=gateway()))
    with sqlite3.connect(path) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE service_credential_history SET name = name")
        assert ServiceCredentialStore(path).read() == overrides(model=gateway())
