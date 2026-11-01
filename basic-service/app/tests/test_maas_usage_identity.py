"""Verify OA attribution at the outbound MaaS boundary, including workers."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Lock
from urllib.parse import quote

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.testclient import TestClient

from jonhon_taskbook import llm_client as llm, model_probe, semantic_retrieval
from jonhon_taskbook.usage_context import model_user_id_var, model_user_scope
from src.common import platform_auth as auth
from src.controller.service_credentials_controller import router as credentials_router


CONFIG = llm.LLMConfig(
    provider="smartvision", api_key="synthetic-api-key", app_id="synthetic-model-app",
    endpoint="https://maas.example/open/opi-maas/v1/chat/completions",
    model="test-model", model_id="chat-model-id",
)
ORIGIN = "http://127.0.0.1:18130"


def completed():
    return {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}


def cookie_header(userid):
    return "; ".join(f"{key}={value}" for key, value in {
        auth.COOKIE_USERID: userid,
        auth.COOKIE_TOKEN: "synthetic-oa-token",
        auth.COOKIE_APPID: "9086",
        auth.COOKIE_USERNAME: quote("显示姓名不用于算力归属"),
    }.items())


def complete(text="request", config=CONFIG):
    return llm._request_compatible(config, "system", text, temperature=0, max_tokens=32)


@pytest.fixture
def outbound(monkeypatch):
    calls = []
    lock = Lock()

    def post(url, **kwargs):
        body = kwargs["json"]
        with lock:
            calls.append((url, body))
        result = completed()
        if url.endswith("/embeddings"):
            result = {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}
        elif url.endswith("/rerank"):
            result = {"results": [{"index": 0, "relevance_score": 0.9}]}
        return httpx.Response(200, json=result, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", post)
    return calls


def application(*, enabled=True, barrier=None):
    app = FastAPI()
    verified = []

    async def verifier(userid, token, appid):
        verified.append((userid, appid))
        return {"code": 0, "data": {"sn": "OA 显示姓名"}}

    @app.get("/")
    async def root():
        return {"ok": True}

    @app.post("/api/complete")
    def direct():
        complete()
        return {"ok": True}

    @app.post("/api/background")
    async def background(request: Request, tasks: BackgroundTasks):
        text = request.query_params.get("case", "background")

        def run():
            def nested():
                if barrier is not None:
                    barrier.wait(timeout=5)
                complete(text)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(nested).result()
        tasks.add_task(run)
        return {"accepted": True}

    @app.get("/api/fail")
    async def fail():
        complete("failing-request")
        raise RuntimeError("synthetic request failure")

    @app.get("/api/current-user")
    async def anonymous_identity():
        # This path is deliberately allowed without cookies by the real auth
        # middleware; inspect only context, without an anonymous model call.
        return {"model_user_id": model_user_id_var.get()}

    app.include_router(credentials_router)
    app.add_middleware(
        auth.PlatformAuthMiddleware,
        settings=auth.AuthSettings(enabled=enabled, app_id=9086,
                                   platform_base_url="https://sv.dcsmartvision.com"),
        verifier=verifier,
    )
    return app, verified


@pytest.mark.parametrize("path", ["/api/complete", "/api/background"])
def test_cookie_user_reaches_sync_and_nested_background_calls(outbound, path):
    app, _ = application()
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            path, params={"user_id": "forged-query", "user_name": "forged-name"},
            headers={"Cookie": cookie_header("employee-007"), "X-User-Id": "forged-header"},
            json={"extra_parameters": {"user_id": "forged-body"}},
        )
    assert response.status_code == 200
    assert len(outbound) == 1
    body = outbound[0][1]
    assert body["extra_parameters"] == {
        "model_id": "chat-model-id", "user_id": "employee-007", "user_name": "employee-007",
    }
    assert "user" not in body
    assert model_user_id_var.get() == ""


def test_overlapping_users_keep_own_identity_in_background_thread_pools(outbound):
    app, _ = application(barrier=Barrier(2))

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            return await asyncio.gather(*(
                client.post("/api/background", params={"case": userid},
                            headers={"Cookie": cookie_header(userid)})
                for userid in ("employee-A", "employee-B")
            ))

    responses = asyncio.run(run())
    assert all(response.status_code == 200 for response in responses)
    assert len(outbound) == 2
    for _, body in outbound:
        submitted_by = body["messages"][-1]["content"]
        assert body["extra_parameters"]["user_id"] == submitted_by
        assert body["extra_parameters"]["user_name"] == submitted_by
    assert model_user_id_var.get() == ""


def test_local_mode_ignores_stale_context_and_unverified_cookie(outbound):
    app, _ = application(enabled=False)
    with model_user_scope("parent-scope-user"):
        with TestClient(app, base_url=ORIGIN) as client:
            response = client.post("/api/complete", headers={"Cookie": cookie_header("unverified")})
        assert model_user_id_var.get() == "parent-scope-user"
    assert response.status_code == 200
    assert outbound[0][1]["extra_parameters"] == {"model_id": "chat-model-id"}
    assert model_user_id_var.get() == ""


def test_exception_does_not_leave_identity_for_next_anonymous_request(outbound):
    app, _ = application()
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        assert client.get("/api/fail", headers={"Cookie": cookie_header("employee-A")}).status_code == 500
        assert client.get("/api/current-user").json() == {"model_user_id": ""}
    assert outbound[0][1]["extra_parameters"]["user_id"] == "employee-A"
    assert model_user_id_var.get() == ""


def test_same_account_and_verified_account_switch_update_model_attribution(outbound):
    app, verified = application()
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        for segment in cookie_header("employee-A").split("; "):
            key, value = segment.split("=", 1)
            client.cookies.set(key, value, domain="127.0.0.1", path="/")
        assert client.get("/?userid=employee-A&token=synthetic-new-token").status_code == 307
        assert client.post("/api/complete").status_code == 200
        assert verified == [("employee-A", 9086)]
        assert client.get("/?userid=employee-B&token=synthetic-other-token").status_code == 307
        assert verified == [("employee-A", 9086), ("employee-B", 9086)]
        assert client.post("/api/complete").status_code == 200
    assert [body["extra_parameters"]["user_id"] for _, body in outbound] == ["employee-A", "employee-B"]
    assert [body["extra_parameters"]["user_name"] for _, body in outbound] == ["employee-A", "employee-B"]


@pytest.mark.parametrize("model_id", ["selected-model-id", ""])
def test_settings_completion_probe_reports_authenticated_user(monkeypatch, model_id):
    app, _ = application()
    bodies = []
    original = httpx.AsyncClient

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=completed())

    def client_factory(**kwargs):
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(model_probe.httpx, "AsyncClient", client_factory)
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post("/api/settings/credentials/test", headers={
            "Cookie": cookie_header("employee-probe"), "X-Credential-Settings": "1",
        }, json={
            "credentials": {"model": {"base_url": "https://maas.example/open/",
                "app_id": "synthetic-model-app", "api_key": "synthetic-key", "tenant_id": "synthetic-tenant"}},
            "model": "test-model", "model_id": model_id,
        })
    assert response.status_code == 200 and response.json()["success"] is True
    expected = {"user_id": "employee-probe", "user_name": "employee-probe"}
    if model_id:
        expected["model_id"] = model_id
    assert len(bodies) == 1 and bodies[0]["extra_parameters"] == expected


def test_optional_embedding_and_reranking_keep_model_ids_and_user(outbound, monkeypatch):
    retrieval = semantic_retrieval.RetrievalConfig(
        embedding_url="https://maas.example/embeddings", embedding_model_id="embedding-id",
        rerank_url="https://maas.example/rerank", rerank_model_id="rerank-id",
    )
    monkeypatch.setattr(semantic_retrieval, "_active_pair", lambda: (CONFIG, retrieval))
    with model_user_scope("employee-retrieval"):
        assert semantic_retrieval.embed_texts("semantic description") == [[0.1, 0.2]]
        assert semantic_retrieval.rerank_documents("query", ["document"])[0]["index"] == 0
    assert [body["extra_parameters"] for _, body in outbound] == [
        {"model_id": model_id, "user_id": "employee-retrieval", "user_name": "employee-retrieval"}
        for model_id in ("embedding-id", "rerank-id")
    ]


@pytest.mark.parametrize("provider,app_id", [("openai_compatible", ""), ("dashscope", "")])
def test_other_provider_payloads_do_not_receive_oa_identity(outbound, provider, app_id):
    config = replace(CONFIG, provider=provider, app_id=app_id)
    with model_user_scope("employee-007"):
        complete(config=config)
    assert outbound[0][1]["extra_parameters"] == {"model_id": "chat-model-id"}


@pytest.mark.parametrize("provider", ["smartvision", "openai_compatible"])
def test_maas_attribution_without_optional_model_id(outbound, provider):
    config = replace(CONFIG, provider=provider, model_id="")
    with model_user_scope("employee-007"):
        complete(config=config)
    assert outbound[0][1]["extra_parameters"] == {"user_id": "employee-007", "user_name": "employee-007"}
