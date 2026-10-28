"""A private deployment dotenv seeds history without changing the active gateway."""
import json

from jonhon_taskbook import llm_client
from jonhon_taskbook.service_credentials import ServiceCredentialStore


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
