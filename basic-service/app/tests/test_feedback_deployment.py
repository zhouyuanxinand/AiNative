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

from src.utils.config_loader import get_config


@pytest.fixture
def admin_app(tmp_path, monkeypatch):
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
    return module.create_app(config), config, store


def test_management_entry_redirects_and_serves_uncached_spa_and_assets(admin_app):
    app, _, _ = admin_app
    with TestClient(app) as client:
        redirect = client.get("/", follow_redirects=False)
        page = client.get("/feedback")
        asset = client.get("/assets/app.js")
    assert redirect.status_code in {302, 307} and redirect.headers["location"] == "/feedback"
    assert page.status_code == 200 and "<title>feedback</title>" in page.text
    assert page.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert asset.status_code == 200 and asset.text == "window.feedback = true;"


def test_management_health_reads_store_and_preserves_request_correlation(admin_app):
    app, config, store = admin_app
    with TestClient(app) as client:
        response = client.get("/api/health", headers={"X-Correlation-ID": "feedback-health-123"})
    assert app.state.config is config
    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "feedback-admin"}
    assert response.headers["X-Correlation-ID"] == "feedback-health-123"
    assert store.path.is_file()


def test_management_listener_cannot_submit_generation_or_public_feedback(admin_app):
    app, _, _ = admin_app
    with TestClient(app) as client:
        for path in ("/api/submit", "/api/feedback", "/api/not-a-real-endpoint"):
            assert client.post(path, json={}).status_code == 404
        listed = client.get("/api/feedback-admin")
    assert listed.status_code == 200
    assert listed.json()["stats"]["total"] == 0


def test_management_create_looks_up_manifest_using_factory_configuration(admin_app):
    app, config, _ = admin_app
    (config.output_dir / "persisted.job.json").write_text(json.dumps({
        "jid": "abcdef0123", "status": "error", "error": "质量核查未通过", "result": {},
        "replay": {"files": {"tech": {"original_name": "技术要求.docx"}}},
    }), encoding="utf-8")
    with TestClient(app) as client:
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
def test_management_rejects_cross_site_mutations(admin_app, headers):
    app, _, store = admin_app
    with TestClient(app) as client:
        response = client.post("/api/feedback-admin", json={}, headers=headers)
    assert response.status_code == 403
    assert store.search()["total"] == 0


def test_management_allows_same_origin_mutations_with_published_port(admin_app):
    app, _, _ = admin_app
    with TestClient(app, base_url="http://127.0.0.1:18141") as client:
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
