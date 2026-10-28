from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.controller.runtime_logs_controller import router
from src.application.middleware import CorrelationIdMiddleware

HEADERS = {"X-Log-Viewer": "1"}


def _client(logs_dir):
    app = FastAPI()
    app.state.config = SimpleNamespace(logs_dir=logs_dir)
    app.include_router(router)
    return TestClient(app)


def _line(index: int, **extra) -> str:
    return json.dumps(
        {
            "timestamp": f"2026-09-21T08:00:{index:02d}+00:00",
            "level": "INFO",
            "logger": "src.test",
            "message": f"event-{index}",
            **extra,
        },
        ensure_ascii=False,
    )


def test_latest_endpoint_requires_platform_header_and_never_caches(tmp_path):
    client = _client(tmp_path)
    for headers in ({}, {**HEADERS, "Sec-Fetch-Site": "cross-site"}):
        response = client.get("/api/logs/latest", headers=headers)
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"

    response = client.get("/api/logs/latest", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "entries": [],
        "returned": 0,
        "limit": 200,
        "source": "app.log",
        "updated_at": None,
        "truncated": False,
        "filtered_transport": 0,
    }


def test_returns_only_requested_tail_in_chronological_order(tmp_path):
    (tmp_path / "app.log").write_text(
        "\n".join(_line(index) for index in range(20)) + "\n",
        encoding="utf-8",
    )
    response = _client(tmp_path).get("/api/logs/latest?limit=3", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert [entry["message"] for entry in data["entries"]] == ["event-17", "event-18", "event-19"]
    assert data["returned"] == data["limit"] == 3
    assert data["source"] == "app.log"
    assert data["updated_at"]
    assert data["truncated"] is True
    assert _client(tmp_path).get("/api/logs/latest?limit=0", headers=HEADERS).status_code == 422
    assert _client(tmp_path).get("/api/logs/latest?limit=501", headers=HEADERS).status_code == 422


def test_redacts_structured_and_free_form_credentials(tmp_path):
    secrets = [
        "stored-secret-value",
        "plain-secret-value",
        "bearer-secret-value",
        "query-secret-value",
        "sk_synthetic_test_credential_0000000000000000000",
    ]
    rows = [
        _line(
            1,
            api_key=secrets[0],
            source_text="historical-requirement-body",
            nested={"access_token": "nested-secret"},
        ),
        _line(
            2,
            message=(
                f"api_key={secrets[1]} Authorization: Bearer {secrets[2]} "
                f"https://example.test?token={secrets[3]} key={secrets[4]} "
                'CLIENT_SECRET=client-secret-value payload={"api_key":"json-secret-value"}'
            ),
        ),
        "not-json password='password-secret'",
    ]
    (tmp_path / "app.log").write_text("\n".join(rows), encoding="utf-8")
    response = _client(tmp_path).get("/api/logs/latest?limit=10", headers=HEADERS)
    assert response.status_code == 200
    body = response.text
    for secret in [
        *secrets,
        "nested-secret",
        "password-secret",
        "client-secret-value",
        "json-secret-value",
        "historical-requirement-body",
    ]:
        assert secret not in body
    assert response.json()["entries"][0]["api_key"] == "***"
    assert response.json()["entries"][0]["nested"]["access_token"] == "***"
    assert response.json()["entries"][0]["source_text"] == "***"
    assert "Authorization: ***" in response.json()["entries"][1]["message"]


def test_path_query_cannot_select_another_file_and_scan_is_bounded(tmp_path):
    outside = tmp_path.parent / "outside-secret.log"
    outside.write_text("outside-file-secret", encoding="utf-8")
    huge_prefix = ("old-entry\n" * 300_000)
    (tmp_path / "app.log").write_text(huge_prefix + _line(9), encoding="utf-8")
    response = _client(tmp_path).get(
        "/api/logs/latest",
        params={"limit": 1, "path": str(outside)},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["entries"][0]["message"] == "event-9"
    assert "outside-file-secret" not in response.text
    assert response.json()["truncated"] is True


def test_transport_debug_noise_does_not_hide_actionable_job_events(tmp_path):
    actionable = _line(
        1,
        level="ERROR",
        logger="src.controller.taskbook",
        message="taskbook_job_failed",
        job_id="job-visible",
        stage="quality_gate",
        error_type="DeliveryGateBlocked",
    )
    noise = [
        _line(
            index % 60,
            level="DEBUG",
            logger="httpcore.http11",
            message="receive_response_body.complete",
        )
        for index in range(300)
    ]
    (tmp_path / "app.log").write_text(
        "\n".join([actionable, *noise]) + "\n", encoding="utf-8"
    )

    response = _client(tmp_path).get("/api/logs/latest?limit=200", headers=HEADERS)

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [entry["message"] for entry in entries] == ["taskbook_job_failed"]
    assert entries[0]["job_id"] == "job-visible"
    assert response.json()["filtered_transport"] == 300


def test_log_view_polling_does_not_emit_request_completed(caplog, tmp_path):
    (tmp_path / "app.log").write_text(_line(1), encoding="utf-8")
    app = FastAPI()
    app.state.config = SimpleNamespace(logs_dir=tmp_path)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(router)

    caplog.set_level(logging.INFO, logger="src.main")
    with TestClient(app) as client:
        response = client.get("/api/logs/latest", headers=HEADERS)
        assert response.status_code == 200
    assert not any(
        record.name == "src.main" and record.getMessage() == "request_completed"
        for record in caplog.records
    )


def test_request_completed_keeps_the_response_correlation_id(caplog, tmp_path):
    app = FastAPI()
    app.state.config = SimpleNamespace(logs_dir=tmp_path)
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    caplog.set_level(logging.INFO, logger="src.main")
    with TestClient(app) as client:
        response = client.get("/ping", headers={"X-Correlation-ID": "trace-123"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "trace-123"
    completed = [
        record
        for record in caplog.records
        if record.name == "src.main" and record.getMessage() == "request_completed"
    ]
    assert len(completed) == 1
    assert completed[0].correlation_id == "trace-123"


def test_unhandled_request_failure_logs_type_duration_and_traceback(caplog, tmp_path):
    app = FastAPI()
    app.state.config = SimpleNamespace(logs_dir=tmp_path)
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("synthetic request failure")

    caplog.set_level(logging.INFO, logger="src.main")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom", headers={"X-Correlation-ID": "trace-failed"})

    assert response.status_code == 500
    failed = [
        record
        for record in caplog.records
        if record.name == "src.main" and record.getMessage() == "request_failed"
    ]
    assert len(failed) == 1
    assert failed[0].correlation_id == "trace-failed"
    assert failed[0].error_type == "RuntimeError"
    assert failed[0].duration_ms >= 0
    assert failed[0].exc_info and failed[0].exc_info[2] is not None


def test_failed_log_view_access_is_still_logged(caplog, tmp_path):
    app = FastAPI()
    app.state.config = SimpleNamespace(logs_dir=tmp_path)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(router)

    caplog.set_level(logging.INFO, logger="src.main")
    with TestClient(app) as client:
        response = client.get("/api/logs/latest")
        assert response.status_code == 403
    records = [
        record
        for record in caplog.records
        if record.name == "src.main" and record.getMessage() == "request_completed"
    ]
    assert len(records) == 1
    assert records[0].status_code == 403
    assert records[0].levelno == logging.WARNING
