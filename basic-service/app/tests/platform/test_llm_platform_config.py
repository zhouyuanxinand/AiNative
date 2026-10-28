"""Platform configuration is shared without changing native generation tuning."""
from dataclasses import replace
from types import SimpleNamespace

from jonhon_taskbook import llm_client as llm


def test_project_model_environment_loads_without_startup_wrapper(tmp_path, monkeypatch):
    module = tmp_path / "project/basic-service/app/src/service/jonhon_taskbook/llm_client.py"
    module.parent.mkdir(parents=True)
    packaged = module.parents[1] / ".env"
    packaged.write_text("MODEL_API_KEY=packaged-key\nMODEL_NAME=packaged-model\n", encoding="utf-8")
    (module.parents[5] / ".env").write_text(
        "MODEL_API_KEY=project-key\nMODEL_NAME=project-model\n"
        "MODEL_APP_ID=project-app\nJTB_AUTH_ENABLED=true\nUNRELATED_PRIVATE=not-a-model-setting\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(llm, "__file__", str(module))
    for key in ("MODEL_API_KEY", "MODEL_NAME", "MODEL_APP_ID", "JTB_SHARED_ENV_FILE", "JTB_AUTH_ENABLED", "UNRELATED_PRIVATE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MODEL_NAME", "process-model")
    llm._load_local_env_once()
    import os
    assert os.environ["MODEL_API_KEY"] == "project-key"
    assert os.environ["MODEL_APP_ID"] == "project-app"
    assert os.environ["MODEL_NAME"] == "process-model"
    assert "JTB_AUTH_ENABLED" not in os.environ
    assert "UNRELATED_PRIVATE" not in os.environ


def test_project_relative_shared_model_config_remains_resolvable(tmp_path, monkeypatch):
    module = tmp_path / "project/basic-service/app/src/service/jonhon_taskbook/llm_client.py"
    module.parent.mkdir(parents=True)
    root = module.parents[5]
    (root / ".env").write_text("JTB_SHARED_ENV_FILE=shared-model.env\n", encoding="utf-8")
    (root / "shared-model.env").write_text("MODEL_API_KEY=shared-key\n", encoding="utf-8")
    monkeypatch.setattr(llm, "__file__", str(module))
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("JTB_SHARED_ENV_FILE", raising=False)
    llm._load_local_env_once()
    import os
    assert os.environ["MODEL_API_KEY"] == "shared-key"


def test_assistant_timeout_is_local_to_one_request(monkeypatch):
    config = llm.LLMConfig(
        provider="smartvision", api_key="synthetic-key", endpoint="https://model.test/chat/completions",
        model="test-model", timeout_seconds=600,
    )
    calls = []
    monkeypatch.setattr(llm, "_active_config", lambda: config)

    def request(active, *args, **kwargs):
        calls.append((active, kwargs))
        return "OK"

    monkeypatch.setattr(llm, "_request_with_retry", request)
    assert llm.chat("system", "user", retries=0, timeout_seconds=60) == "OK"
    assert calls[0][0] == replace(config, timeout_seconds=60)
    assert calls[0][1]["retries"] == 0
    assert llm.chat("system", "user") == "OK"
    assert calls[1][0] is config
    assert config.timeout_seconds == 600


def test_azure_assistant_timeout_reaches_cached_client_request(monkeypatch):
    config = llm.LLMConfig(
        provider="azure", api_key="synthetic-key", endpoint="https://azure.test",
        model="test-model", timeout_seconds=600,
    )
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(model_dump=lambda: {
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
        })

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "_active_config", lambda: config)
    monkeypatch.setattr(llm, "_get_azure_client", lambda active: client)
    assert llm.chat("system", "user", retries=0, timeout_seconds=60) == "OK"
    assert calls[0]["timeout"] == 60
