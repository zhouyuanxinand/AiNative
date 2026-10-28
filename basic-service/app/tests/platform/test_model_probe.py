"""Exercise settings probes at the HTTP boundary without calling a real model."""
import asyncio
import json
import os

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jonhon_taskbook import llm_client as llm, model_probe as probe
from jonhon_taskbook.service_credentials import ServiceCredentialStore
from src.controller.service_credentials_controller import router

URL = "/api/settings/credentials/test"
HEADERS = {"X-Credential-Settings": "1"}


def credentials(host="draft", *, key=None):
    return {"model": {"base_url": f"https://{host}.example/open/", "app_id": f"{host}-app",
                      "api_key": key or f"{host}-secret", "tenant_id": f"{host}-tenant"}}


def completed(content="OK", finish="stop"):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}]}


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith(("MODEL_", "AI_", "JTB_", "AZURE_", "OPENAI_")):
            monkeypatch.delenv(name)
    for key, value in credentials("default")["model"].items():
        monkeypatch.setenv(f"MODEL_{key.upper()}", value)
    monkeypatch.setenv("MODEL_NAME", "default-model")
    monkeypatch.setenv("MODEL_ID", "deployment-model-id")
    monkeypatch.setenv("JTB_LLM_MODELS_API_URL", "https://wrong-environment.example/catalog")
    path = tmp_path / "credentials.sqlite3"
    monkeypatch.setenv("JTB_SERVICE_CREDENTIALS_DB", str(path))
    active = llm.make_config(provider="smartvision", api_key="active-secret", app_id="active-app",
                             endpoint="https://active.example/open/opi-maas/v1/chat/completions", model="active")
    monkeypatch.setattr(llm, "_runtime_config", active)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), path, active


@pytest.fixture
def transport(monkeypatch):
    original = httpx.AsyncClient

    def install(handler):
        calls = []

        def factory(**kwargs):
            calls.append(kwargs)
            return original(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(probe.httpx, "AsyncClient", factory)
        return calls

    return install


@pytest.mark.parametrize("suffix", ["", "/models"])
@pytest.mark.parametrize("headers", [{}, {**HEADERS, "Sec-Fetch-Site": "cross-site"}])
def test_requires_same_site_header(settings, transport, suffix, headers):
    client, path, _ = settings
    calls = transport(lambda _: pytest.fail("blocked request must not call gateway"))
    response = client.post(URL + suffix, headers=headers, json={"credentials": credentials(), "model": "qwen3.8"})
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert not path.exists() and not calls


@pytest.mark.parametrize("model", ["deepseek-v4-flash", "qwen3.6", "qwen3.8"])
def test_draft_probe_uses_exact_model_and_headers_without_mutating_settings(settings, transport, caplog, model):
    client, path, active = settings
    ServiceCredentialStore(path).save(credentials("saved"), llm.get_service_credential_defaults())
    before = path.read_bytes()
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://draft.example/open/opi-maas/v1/chat/completions"
        assert request.headers["App-Id"] == "draft-app"
        assert request.headers["Api-Key"] == "draft-secret"
        assert request.headers["Tenant-Id"] == "draft-tenant"
        body = json.loads(request.content)
        assert body["model"] == model
        assert body["extra_parameters"] == {"model_id": "selected-id"}
        assert body["max_tokens"] == 1024 and body["stream"] is False
        assert len(body["messages"]) == 1 and "连通性测试" in body["messages"][0]["content"]
        return httpx.Response(200, json=completed("private-model-output"))

    calls = transport(handler)
    response = client.post(URL, headers=HEADERS,
                           json={"credentials": credentials(), "model": model, "model_id": "selected-id"})
    data = response.json()
    assert response.status_code == 200 and data["success"] is True
    assert data["model"] == model and data["response_time_ms"] >= 0
    assert data["checked_at"].endswith("+00:00")
    assert response.headers["cache-control"] == "no-store"
    assert len(requests) == 1 and calls == [{"timeout": 45.0, "follow_redirects": False}]
    assert before == path.read_bytes() and llm._runtime_config is active
    for sensitive in ("draft-secret", "private-model-output", "saved-secret", "active-secret"):
        assert sensitive not in response.text and sensitive not in caplog.text


def test_null_uses_deployment_defaults_ignoring_saved_active_and_global_catalog(settings, transport):
    client, path, active = settings
    ServiceCredentialStore(path).save(credentials("saved"), llm.get_service_credential_defaults())
    before = path.read_bytes()
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://default.example/open/opi-maas/v1/chat/models"
        assert request.headers["Api-Key"] == "default-secret"
        return httpx.Response(200, json={"data": {"list": [{"id": 123, "model": "qwen3.8", "vendor": "Qwen"}]}})

    calls = transport(handler)
    response = client.post(URL + "/models", headers=HEADERS, json={"credentials": {"model": None}})
    assert response.status_code == 200 and response.json()["success"] is True
    assert response.json()["models"] == [{"model": "qwen3.8", "id": "123", "vendor": "Qwen", "provider": "smartvision", "configured": True}]
    assert len(requests) == 1 and calls == [{"timeout": 10.0, "follow_redirects": False}]
    assert before == path.read_bytes() and llm._runtime_config is active


def test_no_selected_id_does_not_reuse_deployment_id(settings, transport):
    client, path, _ = settings

    def handler(request):
        assert "extra_parameters" not in json.loads(request.content)
        return httpx.Response(200, json=completed())

    transport(handler)
    assert client.post(URL, headers=HEADERS, json={"credentials": {"model": None}, "model": "qwen3.8"}).json()["success"]
    assert not path.exists()


@pytest.mark.parametrize("status,code", [(401, "authentication_failed"), (403, "authentication_failed"),
    (302, "redirect"), (404, "not_found"), (429, "rate_limited"), (503, "service_unavailable"), (400, "request_rejected")])
@pytest.mark.parametrize("suffix", ["", "/models"])
def test_http_failure_is_safe_and_not_retried(settings, transport, status, code, suffix, caplog):
    client, _, _ = settings
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="draft-secret private authentication error", headers={"Location": "https://elsewhere.example/"})

    transport(handler)
    payload = {"credentials": credentials()}
    if not suffix:
        payload["model"] = "qwen3.8"
    response = client.post(URL + suffix, headers=HEADERS, json=payload)
    assert response.status_code == 200 and response.json()["success"] is False
    assert response.json()["error_code"] == code and len(requests) == 1
    assert "draft-secret" not in response.text + caplog.text
    assert "private authentication error" not in response.text + caplog.text


@pytest.mark.parametrize("body,code", [([], "invalid_response"), ({}, "invalid_response"),
    (completed(""), "empty_response"), (completed(None), "empty_response"),
    (completed("   "), "empty_response"), (completed({"unexpected": "value"}), "invalid_response"),
    (completed([{"text": {"unexpected": "value"}}]), "invalid_response"),
    (completed("partial", "length"), "truncated_response"),
    (completed("blocked", "content_filter"), "response_rejected"),
    (completed("partial", None), "incomplete_response")])
def test_incomplete_or_malformed_chat_is_not_reported_as_success(settings, transport, body, code):
    client, _, _ = settings
    transport(lambda _: httpx.Response(200, json=body))
    response = client.post(URL, headers=HEADERS, json={"credentials": credentials(), "model": "qwen3.8"})
    assert response.status_code == 200 and response.json()["error_code"] == code
    assert response.json()["success"] is False


@pytest.mark.parametrize("body,code", [({}, "invalid_response"), ({"data": []}, "empty_models"),
    ({"success": False, "message": "draft-secret"}, "request_rejected")])
def test_catalog_error_never_falls_back_to_another_environment(settings, transport, body, code):
    client, _, _ = settings
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "draft.example"
        return httpx.Response(200, json=body)

    transport(handler)
    response = client.post(URL + "/models", headers=HEADERS, json={"credentials": credentials()})
    assert response.json()["error_code"] == code and response.json()["models"] == []
    assert len(requests) == 1 and "draft-secret" not in response.text


@pytest.mark.parametrize("suffix", ["", "/models"])
def test_network_and_read_timeout_safe(settings, transport, suffix):
    client, _, _ = settings
    for error, code in [(httpx.ConnectError, "connection_failed"), (httpx.ReadTimeout, "timeout")]:
        def handler(request):
            raise error("draft-secret internal details", request=request)
        transport(handler)
        payload = {"credentials": credentials(), **({"model": "qwen3.8"} if not suffix else {})}
        response = client.post(URL + suffix, headers=HEADERS, json=payload)
        assert response.json()["error_code"] == code
        assert "draft-secret" not in response.text


@pytest.mark.parametrize("suffix,timeout_name", [("", "COMPLETION_TIMEOUT_SECONDS"), ("/models", "CATALOG_TIMEOUT_SECONDS")])
def test_hard_deadline_cancels_request_even_if_transport_has_no_timeout(settings, transport, monkeypatch, suffix, timeout_name):
    client, _, _ = settings
    monkeypatch.setattr(probe, timeout_name, 0.02)
    cancelled = []

    async def handler(request):
        try:
            await asyncio.sleep(2)
        finally:
            cancelled.append(True)

    transport(handler)
    payload = {"credentials": credentials(), **({"model": "qwen3.8"} if not suffix else {})}
    response = client.post(URL + suffix, headers=HEADERS, json=payload)
    assert response.json()["error_code"] == "timeout" and cancelled == [True]
    assert 10 <= response.json()["response_time_ms"] < 1500


def test_elapsed_time_includes_complete_response_body(settings, transport):
    client, _, _ = settings

    class DelayedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"choices":'
            await asyncio.sleep(0.03)
            yield json.dumps(completed()["choices"]).encode() + b"}"

    transport(lambda _: httpx.Response(200, stream=DelayedBody()))
    response = client.post(URL, headers=HEADERS, json={"credentials": credentials(), "model": "qwen3.8"})
    assert response.json()["success"] and response.json()["response_time_ms"] >= 25


def test_compatible_text_blocks_count_as_a_complete_response(settings, transport):
    client, _, _ = settings
    transport(lambda _: httpx.Response(200, json=completed([{"type": "text", "text": "OK"}])))
    response = client.post(URL, headers=HEADERS, json={"credentials": credentials(), "model": "qwen3.8"})
    assert response.json()["success"] is True


@pytest.mark.parametrize("suffix", ["", "/models"])
def test_non_json_response_is_safe(settings, transport, suffix, caplog):
    client, _, _ = settings
    transport(lambda _: httpx.Response(200, text="<html>draft-secret authentication details</html>"))
    payload = {"credentials": credentials(), **({"model": "qwen3.8"} if not suffix else {})}
    response = client.post(URL + suffix, headers=HEADERS, json=payload)
    assert response.status_code == 200 and response.json()["error_code"] == "invalid_response"
    assert "draft-secret" not in response.text + caplog.text


def test_concurrent_drafts_do_not_leak_headers_or_model_selection(settings, transport):
    _, path, active = settings
    requests = []

    async def handler(request):
        await asyncio.sleep(0.01)
        requests.append(request)
        expected = request.url.host.split(".")[0]
        assert request.headers["Api-Key"] == f"{expected}-secret"
        assert json.loads(request.content)["model"] == f"{expected}-model"
        return httpx.Response(200, json=completed())

    transport(handler)

    async def run():
        return await asyncio.gather(*[
            probe.run_probe({"credentials": credentials(host), "model": f"{host}-model"})
            for host in ("first", "second")
        ])

    assert all(result["success"] for result in asyncio.run(run()))
    assert len(requests) == 2 and not path.exists() and llm._runtime_config is active


@pytest.mark.parametrize("payload", [{}, {"credentials": {"model": None}},
    {"credentials": {"model": None}, "model": ""},
    {"credentials": {"model": None}, "model": "qwen\nsecret"},
    {"credentials": {"model": None}, "model": "qwen", "model_id": 123},
    {"credentials": {"model": None}, "model": "qwen", "prompt": "unexpected"},
    {"credentials": {"model": {"base_url": "https://example.com"}}, "model": "qwen"},
    {"credentials": {"model": {**credentials()["model"], "base_url": "https://example.com/?key=secret"}}, "model": "qwen"}])
def test_invalid_request_is_400_and_does_not_reach_gateway(settings, transport, payload):
    client, path, _ = settings
    calls = transport(lambda _: pytest.fail("invalid inputs must not call gateway"))
    response = client.post(URL, headers=HEADERS, json=payload)
    assert response.status_code == 400 and not calls and not path.exists()
    assert response.headers["cache-control"] == "no-store"


def test_incomplete_deployment_default_gives_actionable_result(settings, transport, monkeypatch):
    client, path, _ = settings
    monkeypatch.delenv("MODEL_API_KEY")
    calls = transport(lambda _: pytest.fail("incomplete default must not call gateway"))
    response = client.post(URL, headers=HEADERS, json={"credentials": {"model": None}, "model": "qwen3.8"})
    assert response.status_code == 200 and response.json()["error_code"] == "not_configured"
    assert not calls and not path.exists()


def _probe_log_records(caplog):
    return [
        record
        for record in caplog.records
        if record.name == llm.__name__
        and record.getMessage().startswith("llm_call_")
    ]


def test_connectivity_probe_logs_structured_completion_without_response_content(
    settings, transport, caplog
):
    client, _, _ = settings
    private_output = "private-probe-output"
    body = completed(private_output)
    body["usage"] = {
        "completion_tokens": 11,
        "completion_tokens_details": {"reasoning_tokens": 4},
    }
    transport(lambda _: httpx.Response(200, json=body))
    caplog.set_level("INFO", logger=llm.__name__)

    response = client.post(
        URL,
        headers=HEADERS,
        json={"credentials": credentials(), "model": "qwen3.8"},
    )

    assert response.json()["success"] is True
    records = _probe_log_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.getMessage() == "llm_call_completed"
    assert record.provider == "smartvision"
    assert record.model == "qwen3.8"
    assert record.operation == "model_connectivity_probe"
    assert record.attempt == record.max_attempts == 1
    assert record.status_code == 200
    assert record.error_type == ""
    assert record.finish_reason == "stop"
    assert record.completion_tokens == 11
    assert record.reasoning_tokens == 4
    assert record.content_chars == len(private_output)
    logged = json.dumps(record.__dict__, ensure_ascii=False, default=str)
    for sensitive in (
        "draft-secret",
        "draft-app",
        "draft-tenant",
        private_output,
        "https://draft.example/open/",
    ):
        assert sensitive not in logged


def test_catalog_probe_logs_safe_http_failure(settings, transport, caplog):
    client, _, _ = settings
    transport(
        lambda _: httpx.Response(
            503,
            text="draft-secret draft-app draft-tenant private-response-body",
        )
    )
    caplog.set_level("INFO", logger=llm.__name__)

    response = client.post(
        URL + "/models",
        headers=HEADERS,
        json={"credentials": credentials()},
    )

    assert response.json()["error_code"] == "service_unavailable"
    records = _probe_log_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.getMessage() == "llm_call_failed"
    assert record.provider == "smartvision"
    assert record.operation == "model_catalog_probe"
    assert record.attempt == record.max_attempts == 1
    assert record.status_code == 503
    assert record.error_type == "service_unavailable"
    assert record.finish_reason == ""
    assert record.completion_tokens == record.reasoning_tokens == 0
    assert record.content_chars == 0
    logged = json.dumps(record.__dict__, ensure_ascii=False, default=str)
    for sensitive in (
        "draft-secret",
        "draft-app",
        "draft-tenant",
        "private-response-body",
    ):
        assert sensitive not in logged
