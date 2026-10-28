from __future__ import annotations
from tests.support.paths import APP_ROOT

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.request_log_store import RequestLogStore, get_request_log_store
from src.controller.runtime_logs_controller import router


def test_retention_keeps_latest_fifty_complete_requests_and_running(tmp_path):
    store = RequestLogStore(tmp_path / "requests.sqlite3")
    store.begin("active", {"username": "测试用户"})
    store.append("active", {"message": "still working"})
    for index in range(51):
        request_id = f"request-{index:02d}"
        store.begin(request_id, {"job_id": request_id})
        store.append(request_id, {"message": f"event-{index}"})
        store.finish(request_id, "success")
    result = store.list_requests()
    assert result["retention"] == 50
    assert result["stats"] == {"running": 1, "success": 50, "failed": 0, "total": 51}
    assert store.detail("request-00") is None
    assert store.detail("active")["entries"][0]["message"] == "still working"
    assert store.append("request-00", {"message": "late log"}) is False
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute("SELECT count(*) FROM request_log_entries").fetchone()[0]
            == 51
        )


def test_order_uses_start_time_not_completion_and_preserves_existing_begin(tmp_path):
    store = RequestLogStore(tmp_path / "requests.sqlite3")
    store.begin("old-running", {"username": "first"})
    for index in range(50):
        store.begin(f"new-{index}", {})
        store.finish(f"new-{index}", "success")
    store.begin("old-running", {"username": "must not replace"})
    assert store.detail("old-running")["request"]["username"] == "first"
    store.finish("old-running", "failed")
    assert store.detail("old-running") is None
    assert len(store.list_requests()["items"]) == 50


def test_complete_event_history_is_persisted_and_cursor_paged(tmp_path):
    path = tmp_path / "requests.sqlite3"
    store = RequestLogStore(path)
    store.begin(
        "job-1", {"username": "张三", "files": {"tech": "D:/uploads/需求.docx"}}
    )
    for index in range(601):
        store.append("job-1", {"message": f"event-{index}", "stage": "generation"})
    store.finish(
        "job-1",
        "success",
        metadata={"files": {"output": "结果.docx"}, "model": "gateway/model"},
    )
    reopened = RequestLogStore(path)
    first = reopened.detail("job-1")
    second = reopened.detail("job-1", after=first["next_cursor"])
    assert len(first["entries"]) == 500
    assert first["has_more"] is True
    assert len(second["entries"]) == 101
    assert second["has_more"] is False
    assert [item["message"] for item in first["entries"] + second["entries"]] == [
        f"event-{index}" for index in range(601)
    ]
    assert first["request"]["event_count"] == 601
    assert first["request"]["files"] == {
        "tech": "需求.docx",
        "spec": "",
        "output": "结果.docx",
    }
    assert first["request"]["duration_ms"] >= 0


def test_metadata_and_entries_are_redacted_before_persistence(tmp_path):
    store = RequestLogStore(tmp_path / "requests.sqlite3")
    store.begin(
        "safe",
        {
            "username": "user",
            "api_key": "secret-value",
            "prompt": "document-private-text",
            "files": {"tech": "C:\\secret\\需求.docx"},
        },
    )
    store.append(
        "safe",
        {
            "message": "token=private-token",
            "nested": {"prompt": "private-prompt", "source_document": "private-source"},
            "raw_response": "raw-private",
            "api_key": "private-key",
        },
    )
    store.finish("safe", "failed", error_summary="password=private-password")
    data = store.detail("safe")
    content = json.dumps(data, ensure_ascii=False)
    for secret in (
        "secret-value",
        "document-private-text",
        "private-token",
        "private-prompt",
        "private-source",
        "raw-private",
        "private-key",
        "private-password",
    ):
        assert secret not in content
    assert data["request"]["files"]["tech"] == "需求.docx"
    with sqlite3.connect(store.path) as connection:
        persisted = "\n".join(connection.iterdump())
    assert "private-prompt" not in persisted
    assert "document-private-text" not in persisted


def test_parallel_writers_keep_all_entries_and_single_completion(tmp_path):
    path = tmp_path / "requests.sqlite3"
    store = RequestLogStore(path)
    store.begin("parallel", {})

    def append_batch(worker):
        writer = RequestLogStore(path)
        for index in range(30):
            assert writer.append("parallel", {"message": f"{worker}:{index}"})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(append_batch, range(8)))
    store.finish("parallel", "success")
    store.finish("parallel", "failed", error_summary="late duplicate")
    detail = store.detail("parallel")
    assert detail["request"]["status"] == "success"
    assert (
        len(detail["entries"])
        == len({entry["id"] for entry in detail["entries"]})
        == 240
    )


def test_recovery_marks_running_as_failed_and_keeps_diagnostic(tmp_path):
    store = RequestLogStore(tmp_path / "requests.sqlite3")
    store.begin("interrupted", {"job_id": "j1"})
    store.begin("complete", {})
    store.finish("complete", "success")
    assert store.recover_interrupted() == 1
    recovered = store.detail("interrupted")
    assert recovered["request"]["status"] == "failed"
    assert recovered["request"]["finished_at"]
    assert recovered["entries"][-1]["error_type"] == "Interrupted"
    assert store.recover_interrupted() == 0
    assert store.detail("complete")["request"]["status"] == "success"


def test_independent_service_processes_can_share_database(tmp_path):
    path = tmp_path / "shared.sqlite3"
    store = RequestLogStore(path)
    store.begin("shared", {})
    program = (
        "import sys; from src.common.request_log_store import RequestLogStore; "
        "store=RequestLogStore(sys.argv[1]); "
        "[store.append('shared', {'message':sys.argv[2] + ':' + str(i)}) for i in range(15)]"
    )
    children = [
        subprocess.Popen(
            [sys.executable, "-c", program, str(path), str(index)],
            cwd=APP_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for index in range(4)
    ]
    for child in children:
        _, errors = child.communicate(timeout=30)
        assert child.returncode == 0, errors.decode(errors="replace")
    assert store.detail("shared")["request"]["event_count"] == 60


def test_search_filters_safe_summary_fields_and_stats_are_global(tmp_path):
    store = RequestLogStore(tmp_path / "requests.sqlite3")
    store.begin(
        "a",
        {
            "username": "王五",
            "product_series": "CY",
            "files": {"tech": "矩形技术要求.docx"},
        },
    )
    store.finish("a", "failed", "quality gate blocked")
    store.begin("b", {"username": "李四"})
    store.finish("b", "success")
    assert [
        row["request_id"]
        for row in store.list_requests(status="failed", q="CY")["items"]
    ] == ["a"]
    assert len(store.list_requests(q="矩形")["items"]) == 1
    assert store.list_requests(q="missing")["items"] == []
    assert store.list_requests(status="failed")["stats"]["success"] == 1
    with pytest.raises(ValueError):
        store.list_requests(status="unknown")


def _client(tmp_path, monkeypatch):
    path = tmp_path / "api.sqlite3"
    monkeypatch.setenv("JTB_REQUEST_LOG_DB", str(path))
    app = FastAPI()
    app.state.config = SimpleNamespace(logs_dir=tmp_path / "logs")
    app.include_router(router)
    return TestClient(app), RequestLogStore(path)


def test_factory_uses_shared_runtime_location_and_override(tmp_path, monkeypatch):
    monkeypatch.delenv("JTB_REQUEST_LOG_DB", raising=False)
    assert (
        get_request_log_store(tmp_path / "logs").path
        == tmp_path / "runtime" / "request_logs.sqlite3"
    )
    monkeypatch.setenv("JTB_REQUEST_LOG_DB", str(tmp_path / "override.sqlite3"))
    assert (
        get_request_log_store(tmp_path / "logs").path == tmp_path / "override.sqlite3"
    )


def test_api_empty_state_header_access_and_no_cache(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    for path in ("/api/logs/requests", "/api/logs/requests/missing"):
        for headers in ({}, {"X-Log-Viewer": "1", "Sec-Fetch-Site": "cross-site"}):
            response = client.get(path, headers=headers)
            assert response.status_code == 403
            assert response.headers["Cache-Control"] == "no-store"
    response = client.get("/api/logs/requests", headers={"X-Log-Viewer": "1"})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["retention"] == 50
    assert response.headers["Cache-Control"] == "no-store"
    assert (
        client.get(
            "/api/logs/requests/missing", headers={"X-Log-Viewer": "1"}
        ).status_code
        == 404
    )


def test_api_detail_pagination_filters_and_invalid_parameters(tmp_path, monkeypatch):
    client, store = _client(tmp_path, monkeypatch)
    store.begin("api-job", {"username": "用户"})
    for index in range(3):
        store.append("api-job", {"message": f"row-{index}"})
    store.finish("api-job", "failed", "blocked")
    headers = {"X-Log-Viewer": "1"}
    response = client.get("/api/logs/requests/api-job?limit=2", headers=headers)
    assert response.status_code == 200
    assert response.json()["has_more"] is True
    cursor = response.json()["next_cursor"]
    response = client.get(f"/api/logs/requests/api-job?after={cursor}", headers=headers)
    assert [entry["message"] for entry in response.json()["entries"]] == ["row-2"]
    assert response.json()["has_more"] is False
    assert response.headers["Cache-Control"] == "no-store"
    assert (
        len(
            client.get(
                "/api/logs/requests?status=failed&q=用户", headers=headers
            ).json()["items"]
        )
        == 1
    )
    for path in (
        "/api/logs/requests?status=bad",
        "/api/logs/requests/api-job?limit=501",
        "/api/logs/requests/api-job?after=-1",
    ):
        assert client.get(path, headers=headers).status_code in (400, 422)
