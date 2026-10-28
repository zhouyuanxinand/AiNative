from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from src.application import factory as main, web
from src.utils.config_loader import get_config


def _client(monkeypatch, tmp_path) -> TestClient:
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><title>taskbook-spa</title>", encoding="utf-8")
    monkeypatch.setattr(web, "resolve_web_index", lambda: index)
    config = replace(get_config(), cors_origins=["*"], max_upload_bytes=1024,
                     logs_dir=tmp_path / "logs", output_dir=tmp_path / "outputs")
    return TestClient(main.create_app(config))


def test_public_entry_routes_serve_uncached_spa_and_keep_logs_private(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        responses = [client.get(path) for path in ("/", "/taskbook", "/rd", "/review/task-123")]
        log_responses = [client.get(path) for path in ("/log", "/logs")]

    assert {response.text for response in responses} == {
        "<!doctype html><title>taskbook-spa</title>"
    }
    for response in responses:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
        assert response.headers["pragma"] == "no-cache"
        assert response.headers["expires"] == "0"

    for response in log_responses:
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/json")
        assert response.headers["cache-control"] == "no-store"
        assert "管理员" in response.json()["error"]


def test_spa_entry_routes_do_not_capture_api_paths(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.get("/api/not-a-real-endpoint")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}
