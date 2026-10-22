"""The management listener serves feedback without exposing generation actions."""
import base64
import importlib
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.common.admin_access_store import AdminAccessStore
from src.common.platform_auth import AuthSettings
from src.utils.config_loader import get_config


@pytest.fixture
def admin_identity(tmp_path):
    store = AdminAccessStore(tmp_path / "admin-access.sqlite3")
    settings = AuthSettings(
        enabled=True,
        app_id=9086,
        platform_base_url="https://sv.dcsmartvision.com",
        callback_hosts=("testserver",),
    )
    return store, settings


@pytest.fixture
def admin_client(admin_identity):
    """Exercise management routes with a genuine server-side owner session."""
    store, settings = admin_identity

    def create_client(app, *, base_url="http://testserver"):
        session = store.create_session(
            username="wangxue",
            userid="oa-owner-1",
            display_name="王雪",
            app_id=settings.app_id,
            base_url=settings.platform_base_url,
            origin=base_url,
        )
        return TestClient(
            app,
            base_url=base_url,
            cookies={"jtb_admin_session": session},
            headers={"Origin": base_url},
        )

    return create_client


@pytest.fixture
def admin_app(tmp_path, monkeypatch, admin_identity):
    module = importlib.import_module("src.feedback_main")
    controller = importlib.import_module("src.controller.feedback_controller")
    store = importlib.import_module("jonhon_taskbook.feedback_store").FeedbackStore(tmp_path / "feedback.sqlite3")
    monkeypatch.setattr(controller, "get_feedback_store", lambda: store)
    index = tmp_path / "web" / "index.html"
    index.parent.mkdir()
    index.write_text("<!doctype html><title>feedback</title>", encoding="utf-8")
    assets = index.parent / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("window.feedback = true;", encoding="utf-8")
    monkeypatch.setattr(module, "_resolve_web_index", lambda: index)
    config = replace(get_config(), output_dir=tmp_path / "outputs", logs_dir=tmp_path / "logs")
    config.output_dir.mkdir()
    access_store, auth_settings = admin_identity
    return module.create_app(config, auth_settings=auth_settings, admin_store=access_store), config, store


def test_management_entry_redirects_and_serves_uncached_spa_and_assets(admin_app, admin_client):
    app, _, _ = admin_app
    with admin_client(app) as client:
        redirect = client.get("/", follow_redirects=False)
        page = client.get("/admin")
        asset = client.get("/assets/app.js")
    assert redirect.status_code in {302, 307} and redirect.headers["location"] == "/admin"
    assert page.status_code == 200 and "<title>feedback</title>" in page.text
    assert page.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert asset.status_code == 200 and asset.text == "window.feedback = true;"


@pytest.mark.parametrize("path,target", [
    ("/feedback?q=CY&status=open&page=2", "/admin?q=CY&status=open&page=2"),
    ("/log", "/admin?view=logs"),
    ("/logs?view=feedback&q=CY", "/admin?q=CY&view=logs"),
])
def test_legacy_management_links_keep_their_context(admin_app, admin_client, path, target):
    app, _, _ = admin_app
    with admin_client(app) as client:
        response = client.get(path, follow_redirects=False)
        page = client.get(target)
    assert response.status_code == 307
    assert response.headers["location"] == target
    assert page.status_code == 200


def test_management_logs_show_the_latest_main_platform_events(admin_app, admin_client):
    app, config, _ = admin_app
    admin_logs = config.logs_dir / "feedback-admin"
    admin_logs.mkdir(parents=True)
    (admin_logs / "app.log").write_text(json.dumps({"message": "admin-only-event"}), encoding="utf-8")
    (config.logs_dir / "app.log").write_text("\n".join(json.dumps({
        "timestamp": f"2026-10-22T01:00:0{i}+00:00", "level": "ERROR", "logger": "src.taskbook",
        "message": f"generation-failed-{i}", "job_id": "CY-job", "api_key": "synthetic-log-secret",
    }) for i in range(3)), encoding="utf-8")
    with admin_client(app) as client:
        response = client.get("/api/logs/latest?limit=1", headers={"X-Log-Viewer": "1"})
        denied = client.get("/api/logs/latest")
        cross_site = client.get("/api/logs/latest", headers={"X-Log-Viewer": "1", "Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["returned"] == 1
    assert response.json()["entries"][0]["message"] == "generation-failed-2"
    assert response.json()["entries"][0]["job_id"] == "CY-job"
    assert "synthetic-log-secret" not in response.text
    assert "admin-only-event" not in response.text
    assert denied.status_code == cross_site.status_code == 403


def test_management_health_reads_store_and_preserves_request_correlation(admin_app):
    app, config, store = admin_app
    with TestClient(app) as client:
        response = client.get("/api/health", headers={"X-Correlation-ID": "feedback-health-123"})
    assert app.state.config is config
    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "feedback-admin"}
    assert response.headers["X-Correlation-ID"] == "feedback-health-123"
    assert store.path.is_file()


def test_management_listener_cannot_submit_generation_or_public_feedback(admin_app, admin_client):
    app, _, _ = admin_app
    with admin_client(app) as client:
        for path in ("/api/submit", "/api/feedback", "/api/not-a-real-endpoint"):
            assert client.post(path, json={}).status_code == 404
        listed = client.get("/api/feedback-admin")
    assert listed.status_code == 200
    assert listed.json()["stats"]["total"] == 0


def test_management_create_looks_up_manifest_using_factory_configuration(admin_app, admin_client):
    app, config, _ = admin_app
    (config.output_dir / "persisted.job.json").write_text(json.dumps({
        "jid": "abcdef0123", "status": "error", "error": "质量核查未通过", "result": {},
        "replay": {"files": {"tech": {"original_name": "技术要求.docx"}}},
    }), encoding="utf-8")
    with admin_client(app) as client:
        response = client.post("/api/feedback-admin", json={
            "jid": "abcdef0123", "username": "张工", "rating": "poor", "comment": "待核查",
        })
    assert response.status_code == 200, response.text
    assert response.json()["record"]["snapshot"]["files"]["tech"] == "技术要求.docx"


@pytest.mark.parametrize("headers", [
    {"Origin": "https://other.example"},
    {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"},
])
def test_management_rejects_cross_site_mutations(admin_app, admin_client, headers):
    app, _, store = admin_app
    with admin_client(app) as client:
        response = client.post("/api/feedback-admin", json={}, headers=headers)
    assert response.status_code == 403
    assert store.search()["total"] == 0


def test_management_allows_same_origin_mutations_with_published_port(admin_app, admin_client):
    app, _, _ = admin_app
    with admin_client(app, base_url="http://127.0.0.1:18141") as client:
        response = client.post("/api/feedback-admin", json={}, headers={"Origin": "http://127.0.0.1:18141"})
    assert response.status_code == 400


_POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
_SERVICE_ROOT = Path(__file__).resolve().parents[3]


def _run_powershell(script, cwd):
    encoded = base64.b64encode(("$ErrorActionPreference = 'Stop'\n" + script).encode("utf-16-le")).decode("ascii")
    return subprocess.run([_POWERSHELL, "-NoProfile", "-EncodedCommand", encoded],
                          cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                          check=False)


@pytest.mark.skipif(os.name != "nt" or not _POWERSHELL, reason="Windows process control script")
def test_windows_start_refuses_occupied_feedback_port_before_starting_any_process(tmp_path):
    shutil.copyfile(_SERVICE_ROOT / "start.ps1", tmp_path / "start.ps1")
    result = _run_powershell("""
$env:JTB_PORT = '18130'
$env:JTB_FEEDBACK_PORT = '18131'
function Get-NetTCPConnection {
    param($LocalPort, $State, $ErrorAction)
    if ($LocalPort -eq 18131) { return @{ OwningProcess = 999 } }
}
function Start-Process { throw 'UNEXPECTED_PROCESS_START' }
function Stop-Process { throw 'UNEXPECTED_PROCESS_STOP' }
try {
    & './start.ps1'
    exit 2
} catch {
    if ($_.Exception.Message.Contains('18131')) { exit 0 }
    throw
}
""", tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "basic-service").exists()


@pytest.mark.skipif(os.name != "nt" or not _POWERSHELL, reason="Windows process control script")
def test_windows_stop_uses_saved_ports_and_never_stops_unrelated_process(tmp_path):
    shutil.copyfile(_SERVICE_ROOT / "stop.ps1", tmp_path / "stop.ps1")
    runtime = tmp_path / "basic-service" / "app" / "runtime"
    runtime.mkdir(parents=True)
    process_file = runtime / "local-services.json"
    process_file.write_text(json.dumps([
        {"pid": 301, "module": "src.main", "port": 19130},
        {"pid": 302, "module": "src.feedback_main", "port": 19131},
        {"pid": 303, "module": "src.feedback_main", "port": 19141},
    ]), encoding="utf-8")
    result = _run_powershell("""
$global:stoppedIds = @()
$global:projectPython = Join-Path $PWD 'basic-service\\.venv\\Scripts\\python.exe'
function Get-NetTCPConnection { param($LocalPort, $State, $ErrorAction) }
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($Filter -eq 'ProcessId=301') { return @{ CommandLine = "$global:projectPython -m src.main" } }
    if ($Filter -eq 'ProcessId=302') { return @{ CommandLine = "$global:projectPython -m src.feedback_main" } }
    return @{ CommandLine = 'C:\\other-project\\python.exe -m src.feedback_main' }
}
function Stop-Process { param($Id, [switch]$Force, $ErrorAction) $global:stoppedIds += $Id }
& './stop.ps1'
Write-Output ('STOPPED=' + (ConvertTo-Json -Compress @($global:stoppedIds)))
""", tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "STOPPED=[301,302]" in result.stdout
    assert not process_file.exists()
