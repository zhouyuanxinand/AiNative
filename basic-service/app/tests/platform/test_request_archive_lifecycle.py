"""Request archives outlive the HTTP response and include the background job."""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.common.logger import RequestArchiveHandler
from src.common.request_archive import (
    RequestArchiveMiddleware,
    bind_archive_job,
    update_archive_metadata,
)
from src.common.request_log_store import RequestLogStore
from src.application.middleware import CorrelationIdMiddleware, UploadContentLengthLimitMiddleware


@pytest.fixture
def archived_app(tmp_path):
    store = RequestLogStore(tmp_path / "requests.sqlite3")
    app = FastAPI()
    app.state.config = SimpleNamespace(max_upload_bytes=256)
    app.add_middleware(UploadContentLengthLimitMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(RequestArchiveMiddleware, store=store)
    handler = RequestArchiveHandler(store)
    logger = logging.getLogger("archive-test")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield app, store, logger
    logger.removeHandler(handler)
    handler.close()


@pytest.mark.parametrize("terminal,expected", [("done", "success"), ("blocked", "failed"), ("cancelled", "failed")])
def test_capture_runs_through_background_completion(archived_app, terminal, expected):
    app, store, logger = archived_app

    @app.post("/api/submit")
    async def submit(background_tasks: BackgroundTasks):
        update_archive_metadata({"files": {"tech": "需求.docx"}, "model": "test-model"})
        job = {"status": "queued", "result": {"meta": {}}, "error": ""}
        bind_archive_job("job-123", job)

        def run():
            logger.info("model call", extra={"event": "llm_call_completed", "completion_tokens": 123})
            job.update(status=terminal, error="质量检查未通过" if terminal == "blocked" else "")
            job["result"] = {"out": "/outputs/result.docx", "meta": {"llm_model": "effective-model"}}
        background_tasks.add_task(run)
        return {"jid": "job-123"}

    with TestClient(app) as client:
        assert client.post("/api/submit").status_code == 200
    item = store.list_requests()["items"][0]
    assert item["status"] == expected
    assert item["job_id"] == "job-123"
    assert item["files"]["output"] == "result.docx"
    assert item["model"] == "effective-model"
    entries = store.detail(item["request_id"])["entries"]
    assert entries[0]["event"] == "generation_request_started"
    assert any(row.get("completion_tokens") == 123 for row in entries)
    assert entries[-1]["event"] == "generation_request_finished"


def test_validation_failure_and_exception_are_archived(archived_app):
    app, store, _ = archived_app

    @app.post("/api/submit")
    async def submit():
        return JSONResponse({"error": "缺少产品规范"}, status_code=400)

    @app.post("/api/submit_local")
    async def local():
        raise RuntimeError("failed api_key=synthetic-secret")

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/api/submit").status_code == 400
        assert client.post("/api/submit_local").status_code == 500
        assert client.get("/api/status/123").status_code == 404
    items = store.list_requests()["items"]
    assert len(items) == 2 and all(item["status"] == "failed" for item in items)
    assert any(item["error_summary"] == "缺少产品规范" for item in items)
    assert "synthetic-secret" not in str([store.detail(item["request_id"]) for item in items])


def test_rejected_upload_and_fastapi_validation_are_archived(archived_app):
    app, store, _ = archived_app

    @app.post("/api/submit")
    async def submit(required_number: int):
        return {"accepted": required_number}

    with TestClient(app) as client:
        assert client.post("/api/submit", content=b"x" * 300).status_code == 413
        assert client.post("/api/submit").status_code == 422
    assert len(store.list_requests()["items"]) == 2
    assert store.list_requests()["stats"]["failed"] == 2


def test_verified_identity_is_recorded_without_request_header_impersonation(archived_app):
    app, store, _ = archived_app

    @app.middleware("http")
    async def trusted_user(request, call_next):
        request.state.current_user = {"userid": "employee-007", "name": "测试用户", "verified": True}
        return await call_next(request)

    @app.post("/api/submit")
    async def submit():
        return JSONResponse({"error": "验证失败"}, status_code=400)

    with TestClient(app) as client:
        response = client.post("/api/submit", headers={"X-User-Name": "forged-user"})
    item = store.list_requests()["items"][0]
    assert item["username"] == "测试用户" and item["userid"] == "employee-007"
    assert response.headers["x-request-log-id"] == item["request_id"]


def test_concurrent_requests_and_child_threads_do_not_mix(archived_app):
    app, store, logger = archived_app

    @app.post("/api/submit")
    async def submit(background_tasks: BackgroundTasks, name: str):
        update_archive_metadata({"product_series": name})
        job = {"status": "queued", "result": {"meta": {}}}
        bind_archive_job(name, job)

        async def run():
            await asyncio.sleep(0.01)
            # Production model helpers propagate context into nested executors.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lambda: logger.info(name, extra={"event": "model-test"})).result()
            job["status"] = "done"
        background_tasks.add_task(run)
        return {"jid": name}

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=3) as callers:
        responses = list(callers.map(lambda name: client.post("/api/submit", params={"name": name}), ["CY", "YLZJ", "J599"]))
    assert all(response.status_code == 200 for response in responses)
    items = store.list_requests()["items"]
    assert len(items) == 3
    for item in items:
        messages = [row["message"] for row in store.detail(item["request_id"])["entries"] if row.get("event") == "model-test"]
        assert messages == [item["product_series"]]
