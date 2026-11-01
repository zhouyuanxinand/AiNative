from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from src import main


def _client(monkeypatch, tmp_path) -> TestClient:
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><title>taskbook-spa</title>", encoding="utf-8")
    monkeypatch.setattr(main, "_resolve_web_index", lambda: index)
    monkeypatch.setenv("JTB_AUTH_ENABLED", "false")
    monkeypatch.setenv("JTB_AUTH_SETTINGS_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("JTB_RD_DATA_DIR", str(tmp_path / "rd"))
    config = SimpleNamespace(cors_origins=["*"], max_upload_bytes=1024, logs_dir=tmp_path / "logs")
    return TestClient(main.create_app(config))


def test_business_entry_routes_serve_the_same_uncached_spa(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        responses = [client.get(path) for path in ("/", "/rd", "/rd/projects/project-123", "/taskbook", "/review/task-123")]

    assert {response.text for response in responses} == {
        "<!doctype html><title>taskbook-spa</title>"
    }
    for response in responses:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
        assert response.headers["pragma"] == "no-cache"
        assert response.headers["expires"] == "0"


def test_private_logs_stay_behind_admin(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        assert client.get("/log").status_code == 403
        assert client.get("/logs").status_code == 403


def test_spa_entry_routes_do_not_capture_api_paths(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.get("/api/not-a-real-endpoint")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}
