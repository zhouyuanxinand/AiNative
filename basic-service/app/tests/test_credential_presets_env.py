"""A private deployment dotenv seeds history without changing the active gateway."""
import json

from jonhon_taskbook import llm_client
from jonhon_taskbook.service_credentials import ServiceCredentialStore


def isolate_env_tree(tmp_path, monkeypatch):
    for key in llm_client._LOCAL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    module = tmp_path / "basic-service/app/src/service/jonhon_taskbook/llm_client.py"
    module.parent.mkdir(parents=True)
    monkeypatch.setattr(llm_client, "__file__", str(module))
    return module


def test_service_root_dotenv_populates_settings_and_history(tmp_path, monkeypatch):
    isolate_env_tree(tmp_path, monkeypatch)
    model = {"base_url": "https://external.example/open/", "app_id": "root-app",
             "api_key": "synthetic-root-secret", "tenant_id": "root-tenant"}
    (tmp_path / ".env").write_text("\n".join(f"MODEL_{key.upper()}={value}" for key, value in model.items()), encoding="utf-8")
    llm_client._load_local_env_once()
    defaults = llm_client.get_service_credential_defaults()
    assert defaults["model"] == model
    view = ServiceCredentialStore(tmp_path / "runtime/credentials.sqlite3").view(defaults)
    assert view["effective"]["model"] == model
    assert len(view["history"]) == 1
    assert view["history"][0]["active"] is True


def test_process_and_legacy_dotenv_keep_precedence_over_service_root(tmp_path, monkeypatch):
    module = isolate_env_tree(tmp_path, monkeypatch)
    (tmp_path / ".env").write_text("MODEL_APP_ID=root-app\nMODEL_API_KEY=root-secret\nMODEL_TENANT_ID=root-tenant\n", encoding="utf-8")
    (module.parents[1] / ".env").write_text("MODEL_APP_ID=legacy-app\nMODEL_API_KEY=legacy-secret\n", encoding="utf-8")
    monkeypatch.setenv("MODEL_API_KEY", "process-secret")
    llm_client._load_local_env_once()
    defaults = llm_client.get_service_credential_defaults()["model"]
    assert defaults["app_id"] == "legacy-app"
    assert defaults["api_key"] == "process-secret"
    assert defaults["tenant_id"] == "root-tenant"


def test_root_shared_env_is_resolved_relative_to_declaring_file(tmp_path, monkeypatch):
    isolate_env_tree(tmp_path, monkeypatch)
    (tmp_path / ".env").write_text("JTB_SHARED_ENV_FILE=private/shared.env\nMODEL_APP_ID=root-app\n", encoding="utf-8")
    shared = tmp_path / "private/shared.env"
    shared.parent.mkdir()
    shared.write_text("MODEL_APP_ID=shared-app\nMODEL_TENANT_ID=shared-tenant\nUNRELATED_SETTING=ignore\n", encoding="utf-8")
    llm_client._load_local_env_once()
    defaults = llm_client.get_service_credential_defaults()["model"]
    assert defaults["app_id"] == "root-app"
    assert defaults["tenant_id"] == "shared-tenant"
    assert "UNRELATED_SETTING" not in llm_client._read_env_file(shared)


def test_dotenv_preset_survives_fresh_deployment_and_restart(tmp_path, monkeypatch):
    variable = "JTB_SERVICE_CREDENTIAL_PRESETS"
    preset = {"name": "内网环境", "model": {
        "base_url": "http://internal.example/open/", "app_id": "internal-app",
        "api_key": "synthetic-internal-secret", "tenant_id": "internal-tenant",
    }}
    env_file = tmp_path / ".env"
    env_file.write_text(variable + "='" + json.dumps([preset], ensure_ascii=False) + "'\n", encoding="utf-8")
    monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(variable, llm_client._read_env_file(env_file)[variable])
    defaults = {"model": {"base_url": "https://external.example/open/", "app_id": "external-app",
                          "api_key": "synthetic-external-secret", "tenant_id": "external-tenant"}}
    path = tmp_path / "runtime" / "service_credentials.sqlite3"
    view = ServiceCredentialStore(path).view(defaults)
    assert view["effective"] == defaults
    assert len(view["history"]) == 2
    internal = next(item for item in view["history"] if item["name"] == "内网环境")
    assert internal["active"] is False
    assert "api_key" not in internal
    restarted = ServiceCredentialStore(path).view(defaults)
    assert {item["id"] for item in restarted["history"]} == {item["id"] for item in view["history"]}
