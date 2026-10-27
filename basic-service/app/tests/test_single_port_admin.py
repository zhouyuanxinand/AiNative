"""Exercise the shipped nginx routes against both real FastAPI applications.

Set JTB_TEST_NGINX to an nginx executable (or install nginx on PATH). The suite
uses ephemeral listeners, isolated stores and synthetic OA responses/files; it
does not require a running platform, Docker or an external OA account.
"""
from __future__ import annotations

import io
import os
import shutil
import socket
import subprocess
import threading
import time
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
import uvicorn


@contextmanager
def _listener():
    listener = socket.socket()
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        yield listener
    finally:
        listener.close()


@contextmanager
def _serve(application):
    with _listener() as listener:
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(
            application, log_config=None, access_log=False,
            lifespan="off", timeout_graceful_shutdown=3,
        ))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline, "uvicorn failed to start"
                time.sleep(0.02)
            yield port
        finally:
            server.should_exit = True
            thread.join(timeout=6)
            if thread.is_alive():
                server.force_exit = True
                thread.join(timeout=4)
            assert not thread.is_alive(), "test uvicorn listener did not stop"


def _unused_port():
    with _listener() as listener:
        return listener.getsockname()[1]


@pytest.fixture(scope="module")
def single_port(tmp_path_factory):
    configured = os.environ.get("JTB_TEST_NGINX")
    executable = shutil.which(configured or "nginx")
    if not executable:
        if configured:
            pytest.fail("JTB_TEST_NGINX does not name an executable")
        pytest.skip("install nginx or set JTB_TEST_NGINX to run live proxy integration tests")
    root = tmp_path_factory.mktemp("single-port-admin")
    with ExitStack() as stack:
        patch = stack.enter_context(pytest.MonkeyPatch.context())
        for key, value in {
            "JTB_AUTH_ENABLED": "true", "JTB_AUTH_APP_ID": "127",
            "JTB_AUTH_PLATFORM_BASE_URL": "http://oa.example.test",
            "JTB_AUTH_PUBLIC_URL": "", "JTB_ADMIN_PUBLIC_URL": "",
            "JTB_AUTH_CALLBACK_HOSTS": "",
            "JTB_AUTH_SETTINGS_DB": str(root / "auth-settings.sqlite3"),
            "JTB_ADMIN_ACCESS_DB": str(root / "admin-access.sqlite3"),
            "JTB_REQUEST_LOG_DB": str(root / "request-logs.sqlite3"),
            "JTB_FEEDBACK_DB": str(root / "feedback.sqlite3"),
        }.items():
            patch.setenv(key, value)

        from src.common.admin_access_store import AdminAccessStore
        from src.common.platform_auth import AuthSettings, PlatformTokenVerifier
        from src.feedback_main import create_app as create_admin
        from src.main import create_app as create_main
        from src.utils.config_loader import get_config

        calls = []

        async def verify(userid, token, appid):
            calls.append((userid, token, appid))
            if token != "synthetic-oa-token" or appid != 127:
                return None
            return {"code": 0, "data": {"username": userid, "sn": "Synthetic tester"}}

        async def verify_main(_self, userid, token, appid):
            return await verify(userid, token, appid)

        patch.setattr(PlatformTokenVerifier, "__call__", verify_main)
        config = replace(get_config(), logs_dir=root / "app-logs", output_dir=root / "outputs")
        admin = create_admin(
            config, auth_settings=AuthSettings.from_env(),
            admin_store=AdminAccessStore(root / "admins.sqlite3"), verifier=verify,
        )
        main_port = stack.enter_context(_serve(create_main(config)))
        admin_port = stack.enter_context(_serve(admin))
        external_port, legacy_port = _unused_port(), _unused_port()
        while legacy_port == external_port:
            legacy_port = _unused_port()
        origin, legacy = f"http://127.0.0.1:{external_port}", f"http://127.0.0.1:{legacy_port}"
        for directory in ("logs", "html", "temp", "trusted-proxies"):
            (root / directory).mkdir()
        (root / "html" / "assets").mkdir()
        (root / "html" / "assets" / "probe.txt").write_text("synthetic static asset", encoding="ascii")
        source = Path(__file__).resolve().parents[3] / "web" / "nginx" / "nginx.conf"
        routes = source.read_text(encoding="utf-8")
        # Only deployment-specific addresses/paths change. All locations, body
        # limits, headers, redirects and matching precedence remain production.
        for before, after in {
            "listen 80;": f"listen 127.0.0.1:{external_port};",
            "listen 81;": f"listen 127.0.0.1:{legacy_port};",
            "127.0.0.1:18130": f"127.0.0.1:{main_port}",
            "127.0.0.1:18131": f"127.0.0.1:{admin_port}",
            "/dev/stdout": "logs/access.log", "/dev/stderr": "logs/error.log",
            "/opt/local/agent-develop-task-doc/basic-service/app/web/dist": "html",
            "/etc/nginx/taskbook-trusted-proxies.d/": "trusted-proxies/",
        }.items():
            routes = routes.replace(before, after)
        (root / "nginx.conf").write_text(
            "daemon off;\nmaster_process off;\npid logs/nginx.pid;\nerror_log logs/error.log;\n"
            "events { worker_connections 128; }\nhttp {\n" + routes + "\n}\n",
            encoding="utf-8",
        )
        command = [executable, "-p", "./", "-c", "nginx.conf"]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        validation = subprocess.run(
            [*command, "-t"], cwd=root, capture_output=True, timeout=10, creationflags=flags,
        )
        assert validation.returncode == 0, validation.stderr.decode(errors="replace")
        diagnostics = stack.enter_context((root / "logs" / "process.log").open("wb"))
        process = subprocess.Popen(command, cwd=root, stdout=diagnostics, stderr=diagnostics, creationflags=flags)

        def stop_nginx():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        stack.callback(stop_nginx)
        with httpx.Client(base_url=origin, timeout=2, trust_env=False) as probe:
            deadline = time.monotonic() + 10
            while True:
                assert process.poll() is None, (root / "logs" / "error.log").read_text(errors="replace")
                try:
                    if probe.get("/api/history").status_code == 401:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "nginx did not expose the main application"
                time.sleep(0.05)
        yield SimpleNamespace(origin=origin, legacy=legacy, calls=calls)


@contextmanager
def _client(origin):
    with httpx.Client(base_url=origin, timeout=10, trust_env=False, follow_redirects=False) as client:
        yield client


def _login(client, userid="wangxue"):
    from src.common.admin_auth import ADMIN_COOKIE, STATE_COOKIE

    response = client.get("/admin/auth/login")
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["app_id"] == ["127"]
    callback = urlsplit(query["redirect_uri"][0])
    assert f"{callback.scheme}://{callback.netloc}" == str(client.base_url).rstrip("/")
    assert callback.path == "/admin/auth/callback"
    assert STATE_COOKIE in client.cookies
    values = {key: value[0] for key, value in parse_qs(callback.query).items()}
    values.update(userid=userid, token="synthetic-oa-token", appid="127")
    response = client.get(callback.path + "?" + urlencode(values))
    assert response.status_code == 303 and response.headers["location"] == "/admin"
    assert ADMIN_COOKIE in client.cookies and STATE_COOKIE not in client.cookies
    assert "synthetic-oa-token" not in response.headers["set-cookie"]


def _main_cookies(client):
    for key, value in {
        "jtb_sv_appid": "127", "jtb_sv_userid": "main-user",
        "jtb_sv_token": "synthetic-main-cookie", "jtb_sv_username": "Main User",
    }.items():
        client.cookies.set(key, value)


def _write_headers(client):
    return {"X-Admin-Action": "1", "Origin": str(client.base_url).rstrip("/")}


def test_same_port_exposes_admin_without_sharing_main_authentication(single_port):
    with _client(single_port.origin) as client:
        assert client.get("/admin").status_code == 200
        home = client.get("/")
        assert home.status_code == 307 and "oa.example.test" in home.headers["location"]
        assert client.get("/assets/probe.txt").text == "synthetic static asset"
        protected = ["/api/admin/session", "/api/admin/members", "/api/feedback-admin",
                     "/api/logs/requests", "/admin/api/settings/auth", "/admin/api/help-resources"]
        for path in protected:
            assert client.get(path).status_code == 401, path
        _main_cookies(client)
        assert client.get("/").status_code == 200
        assert client.get("/api/current-user").json()["user"]["userid"] == "main-user"
        settings = client.get("/api/settings/auth")
        assert settings.status_code == 200 and settings.json()["can_edit"] is False
        assert settings.json()["active"]["enabled"] is True
        assert client.put("/api/settings/auth", json={}, headers={
            "X-Credential-Settings": "1", "Origin": single_port.origin,
        }).status_code == 403
        for path in protected:
            assert client.get(path).status_code == 401, path
        # Similar prefixes must stay on the main listener, not be caught by the
        # privileged-route regex; the real main app reports its normal 404.
        assert client.get("/api/admin-extra").status_code == 404
        assert client.get("/api/help-resources").status_code == 200


def test_owner_login_management_apis_and_revocation_use_one_origin(single_port):
    with _client(single_port.origin) as owner, _client(single_port.origin) as member:
        _login(owner)
        assert owner.get("/api/admin/session").json()["can_manage_admins"] is True
        assert owner.get("/api/feedback-admin").status_code == 200
        for path in ("/api/logs/latest", "/api/logs/requests"):
            assert owner.get(path, headers={"X-Log-Viewer": "1"}).status_code == 200
        settings = owner.get("/admin/api/settings/auth").json()
        assert settings["can_edit"] is True
        saved = owner.put("/admin/api/settings/auth", json={
            **settings["settings"], "expected_version": settings["version"],
        }, headers={"X-Credential-Settings": "1", "Origin": single_port.origin})
        assert saved.status_code == 200 and saved.json()["version"] == settings["version"] + 1
        response = owner.post("/api/admin/members", json={"username": "proxy-member"}, headers=_write_headers(owner))
        assert response.status_code == 201, response.text
        _login(member, "proxy-member")
        assert member.get("/api/admin/session").json()["can_manage_admins"] is False
        assert member.get("/admin/api/settings/auth").json()["can_edit"] is False
        assert member.put("/admin/api/settings/auth", json={}, headers=_write_headers(member)).status_code == 403
        assert member.post("/api/admin/members", json={"username": "intruder"}, headers=_write_headers(member)).status_code == 403
        assert owner.delete("/api/admin/members/proxy-member", headers=_write_headers(owner)).status_code == 200
        assert member.get("/api/feedback-admin").status_code == 401
        assert owner.get("/api/current-user").json()["authenticated"] is False
        assert owner.get("/api/help-resources").status_code == 401


def test_admin_only_session_uploads_previews_ranges_and_downloads(single_port):
    from docx import Document

    video = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"v" * (140 * 1024)
    doc = Document()
    doc.add_paragraph("Synthetic operating instructions")
    word = io.BytesIO()
    doc.save(word)
    with _client(single_port.origin) as admin, _client(single_port.origin) as main:
        _login(admin)
        headers = _write_headers(admin)
        uploaded = []
        for kind, name, payload, media_type in (
            ("video", "guide.mp4", video, "video/mp4"),
            ("manual", "guide.docx", word.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ):
            response = admin.post("/api/help-resources-admin/upload", data={"kind": kind, "title": "Synthetic guide"},
                                  files={"file": (name, payload, media_type)}, headers=headers)
            assert response.status_code == 201, response.text
            uploaded.append(response.json()["item"])
        listing = admin.get("/admin/api/help-resources")
        assert listing.status_code == 200
        assert {item["id"] for item in uploaded} <= {item["id"] for item in listing.json()["items"]}
        video_url = "/admin" + uploaded[0]["content_url"]
        assert admin.get(video_url).content == video
        partial = admin.get(video_url, headers={"Range": "bytes=0-23"})
        assert partial.status_code == 206 and partial.content == video[:24]
        assert partial.headers["content-range"] == f"bytes 0-23/{len(video)}"
        downloaded = admin.get(video_url + "?download=1")
        assert downloaded.status_code == 200 and downloaded.headers["content-disposition"].startswith("attachment")
        projection = admin.get("/admin" + uploaded[1]["preview_url"])
        assert projection.status_code == 200 and "Synthetic operating instructions" in projection.text
        assert admin.get("/api/help-resources").status_code == 401
        _main_cookies(main)
        assert main.get(uploaded[0]["content_url"]).content == video
        assert main.get("/admin/api/help-resources").status_code == 401
        # Only the exact upload route is exempt from the 128 KiB admin cap.
        oversized = admin.post("/api/help-resources-admin/links", content=b"x" * (129 * 1024), headers=headers)
        assert oversized.status_code == 413
        assert admin.post("/api/help-resources-admin/upload/", content=b"x" * (129 * 1024), headers=headers).status_code == 413
        for item in uploaded:
            assert admin.delete("/api/help-resources-admin/" + item["id"], headers=headers).status_code == 200
            assert admin.get("/admin" + item["content_url"]).status_code == 404


def test_relative_navigation_retains_dynamic_port_and_legacy_listener_works(single_port):
    from src.common.admin_auth import ADMIN_COOKIE

    with _client(single_port.origin) as primary, _client(single_port.legacy) as legacy:
        response = primary.get("/admin/home")
        assert response.status_code == 303 and response.headers["location"] == "/"
        response = primary.get("/admin/?view=logs")
        assert response.status_code == 308 and response.headers["location"] == "/admin?view=logs"
        assert legacy.get("/admin").status_code == 200
        assert legacy.get("/api/health").json() == {"ok": True, "service": "feedback-admin"}
        _login(primary)
        legacy.cookies.set(ADMIN_COOKIE, primary.cookies.get(ADMIN_COOKIE))
        assert legacy.get("/api/admin/session").status_code == 401
        legacy.cookies.clear()
        _login(legacy)
        assert legacy.get("/api/admin/session").json()["user"]["username"] == "wangxue"
        assert legacy.get("/api/help-resources").status_code == 200
