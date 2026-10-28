"""Help material is durable, readable on the main app, and managed only by admins."""
from __future__ import annotations

import base64
import io
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlencode, urlsplit
from zipfile import ZipFile

import pytest
from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.admin_access_store import AdminAccessStore
from src.common.admin_auth import ADMIN_COOKIE
from src.common.help_resource_store import HelpResourceError, HelpResourceStore
from src.common.platform_auth import AuthSettings
from src.controller import help_resources_controller
from src.feedback_main import create_app as create_admin_app
from src.main import create_app as create_main_app
from src.utils.config_loader import get_config

ADMIN_ORIGIN = "http://127.0.0.1:18131"
WRITE_HEADERS = {"X-Admin-Action": "1", "Origin": ADMIN_ORIGIN}
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + bytes(range(128))
PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=")


def _login(client):
    response = client.get("/admin/auth/login", follow_redirects=False)
    assert response.status_code == 302
    callback = parse_qs(urlsplit(response.headers["location"]).query)["redirect_uri"][0]
    parts = urlsplit(callback)
    values = {key: value[0] for key, value in parse_qs(parts.query).items()}
    values.update(userid="verified-oa-id", token="verified-test-token", appid="127")
    response = client.get(parts.path + "?" + urlencode(values), follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/admin"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.delenv("JTB_ADMIN_PUBLIC_URL", raising=False)
    monkeypatch.setenv("JTB_AUTH_ENABLED", "false")
    monkeypatch.setenv("JTB_AUTH_SETTINGS_DB", str(tmp_path / "auth-settings.sqlite3"))
    monkeypatch.setenv("JTB_REQUEST_LOG_DB", str(tmp_path / "requests.sqlite3"))
    config = replace(get_config(), logs_dir=tmp_path / "logs", output_dir=tmp_path / "outputs")
    settings = AuthSettings(enabled=False, app_id=127, platform_base_url="http://platform.internal")
    access = AdminAccessStore(tmp_path / "admins.sqlite3")

    async def verify(userid, token, appid):
        assert (userid, token, appid) == ("verified-oa-id", "verified-test-token", 127)
        return {"code": 0, "data": {"username": "wangxue", "sn": "王工"}}

    admin_app = create_admin_app(config, auth_settings=settings, admin_store=access, verifier=verify)
    with TestClient(create_main_app(config)) as public, TestClient(admin_app, base_url=ADMIN_ORIGIN) as admin:
        _login(admin)
        yield public, admin, admin_app, config


def _upload(client, *, kind="video", title="操作演示", filename="操作演示.mp4", content=MP4, media_type="video/mp4", headers=None):
    return client.post(
        "/api/help-resources-admin/upload",
        data={"kind": kind, "title": title},
        files={"file": (filename, content, media_type)},
        headers=WRITE_HEADERS if headers is None else headers,
    )


def _link(client, *, kind="manual", title="操作手册", url="https://docs.example.com/manual.pdf", headers=None):
    return client.post(
        "/api/help-resources-admin/links", json={"kind": kind, "title": title, "source_url": url},
        headers=WRITE_HEADERS if headers is None else headers,
    )


def test_admin_upload_is_shared_with_public_reader_and_can_be_deleted(api):
    public, admin, _, config = api
    response = _upload(admin)
    assert response.status_code == 201, response.text
    item = response.json()["item"]
    assert uuid.UUID(item["id"])
    assert item["kind"] == "video" and item["title"] == "操作演示"
    assert item["source_type"] == "file" and item["source_url"] is None
    assert item["filename"] == "操作演示.mp4" and item["size_bytes"] == len(MP4)
    assert item["media_type"] == "video/mp4" and item["created_by"] == "wangxue"
    assert item["created_at"] and item["updated_at"]
    assert item["preview_type"] == "video" and item["preview_url"] == item["content_url"]
    assert public.get("/api/help-resources", params={"kind": "video"}).json() == {"items": [item]}
    assert admin.get("/api/help-resources").json() == {"items": [item]}
    assert public.get("/api/help-resources", params={"kind": "manual"}).json() == {"items": []}
    root = config.logs_dir.parent / "data" / "help_resources"
    restarted = HelpResourceStore(root)
    assert restarted.get(item["id"]) == item
    stored_path = restarted.file_path(item)
    assert stored_path.is_file()
    response = public.get(item["content_url"])
    assert response.status_code == 200 and response.content == MP4
    assert response.headers["content-disposition"].startswith("inline")
    download = public.get(item["content_url"], params={"download": 1})
    assert download.content == MP4 and download.headers["content-disposition"].startswith("attachment")
    assert "操作演示.mp4" in unquote(download.headers["content-disposition"])
    assert admin.delete(f'/api/help-resources-admin/{item["id"]}', headers=WRITE_HEADERS).json() == {"ok": True}
    assert public.get("/api/help-resources").json() == {"items": []}
    assert public.get(item["content_url"]).status_code == 404
    assert not stored_path.exists()
    assert admin.delete(f'/api/help-resources-admin/{item["id"]}', headers=WRITE_HEADERS).status_code == 404


def test_admin_read_namespace_supports_files_and_word_without_main_login(api):
    _, admin, admin_app, _ = api
    video = _upload(admin).json()["item"]
    document = Document()
    document.add_paragraph("管理员操作手册")
    content = io.BytesIO()
    document.save(content)
    manual = _upload(admin, kind="manual", filename="manual.docx", content=content.getvalue(),
                     media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document").json()["item"]
    assert len(admin.get("/admin/api/help-resources").json()["items"]) == 2
    video_url = "/admin" + video["content_url"]
    response = admin.get(video_url, headers={"Range": "bytes=0-7"})
    assert response.status_code == 206 and response.content == MP4[:8]
    download = admin.get(video_url, params={"download": 1})
    assert download.content == MP4 and download.headers["content-disposition"].startswith("attachment")
    preview_url = "/admin" + manual["preview_url"]
    preview = admin.get(preview_url)
    assert preview.status_code == 200 and "管理员操作手册" in preview.text
    with TestClient(admin_app, base_url=ADMIN_ORIGIN) as anonymous:
        for path in ("/admin/api/help-resources", video_url, preview_url):
            denied = anonymous.get(path, headers={"Cookie": "jtb_sv_userid=wangxue; jtb_sv_token=synthetic-token; jtb_sv_appid=127"})
            assert denied.status_code == 401 and denied.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize("range_header,expected,content_range", [
    ("bytes=0-7", MP4[:8], f"bytes 0-7/{len(MP4)}"),
    ("bytes=12-", MP4[12:], f"bytes 12-{len(MP4) - 1}/{len(MP4)}"),
    ("bytes=-10", MP4[-10:], f"bytes {len(MP4) - 10}-{len(MP4) - 1}/{len(MP4)}"),
])
def test_video_byte_ranges_allow_seeking(api, range_header, expected, content_range):
    public, admin, _, _ = api
    item = _upload(admin).json()["item"]
    response = public.get(item["content_url"], headers={"Range": range_header})
    assert response.status_code == 206 and response.content == expected
    assert response.headers["content-range"] == content_range
    assert response.headers["accept-ranges"] == "bytes"


def test_unsatisfiable_range_returns_file_length(api):
    public, admin, _, _ = api
    item = _upload(admin).json()["item"]
    response = public.get(item["content_url"], headers={"Range": "bytes=999999-"})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(MP4)}"


@pytest.mark.parametrize("url,kind,preview_type", [
    ("https://docs.example.com/guide.PDF?version=2", "manual", "pdf"),
    ("https://media.example.com/tutorial.mp4?signature=example", "video", "video"),
    ("http://intranet.example.com/help", "manual", "link"),
    ("https://docs.example.com/guide.docx", "manual", "link"),
])
def test_links_preserve_url_and_preview_without_uploading_or_fetching_remote_files(api, url, kind, preview_type):
    public, admin, _, _ = api
    response = _link(admin, kind=kind, url=url)
    assert response.status_code == 201, response.text
    item = response.json()["item"]
    assert item["source_type"] == "link" and item["source_url"] == url
    assert item["filename"] is None and item["size_bytes"] is None
    assert item["preview_type"] == preview_type and item["preview_url"] == url
    assert item["content_url"] is None
    assert public.get("/api/help-resources").json()["items"] == [item]
    assert public.get(f'/api/help-resources/{item["id"]}/file').status_code == 404
    rejected = public.get(f'/api/help-resources/{item["id"]}/document')
    assert rejected.status_code == 400 and rejected.json().get("error")
    assert admin.delete(f'/api/help-resources-admin/{item["id"]}', headers=WRITE_HEADERS).status_code == 200


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:text/html,hello", "file:///C:/manual.pdf", "ftp://example.com/manual.pdf",
    "//example.com/manual.pdf", "https://", "https://example.com/guide\n.pdf", "https://user:password@example.com/manual.pdf",
])
def test_invalid_or_credential_bearing_urls_are_rejected(api, url):
    public, admin, _, _ = api
    response = _link(admin, url=url)
    assert response.status_code == 400 and response.json().get("error")
    assert public.get("/api/help-resources").json() == {"items": []}


def test_main_app_has_no_administrative_mutation_routes(api):
    public, admin, _, _ = api
    item = _link(admin).json()["item"]
    assert _link(public).status_code == 404
    assert _upload(public).status_code == 404
    assert public.delete(f'/api/help-resources-admin/{item["id"]}', headers=WRITE_HEADERS).status_code == 404
    assert len(public.get("/api/help-resources").json()["items"]) == 1


def test_anonymous_admin_mutations_cannot_forge_identity(api):
    public, admin, admin_app, _ = api
    item = _link(admin).json()["item"]
    with TestClient(admin_app, base_url=ADMIN_ORIGIN) as anonymous:
        anonymous.cookies.set(ADMIN_COOKIE, "forged-session")
        headers = {**WRITE_HEADERS, "X-User-Name": "wangxue"}
        assert _link(anonymous, headers=headers).status_code == 401
        assert _upload(anonymous, headers=headers).status_code == 401
        assert anonymous.delete(f'/api/help-resources-admin/{item["id"]}', headers=headers).status_code == 401
    assert len(public.get("/api/help-resources").json()["items"]) == 1


def test_admin_router_itself_requires_a_verified_admin_dependency(tmp_path):
    application = FastAPI()
    application.state.config = replace(get_config(), logs_dir=tmp_path / "logs")
    application.include_router(help_resources_controller.admin_router)
    with TestClient(application, base_url=ADMIN_ORIGIN) as client:
        response = _link(client)
        assert response.status_code in {401, 403} and response.json().get("error")


@pytest.mark.parametrize("headers", [
    {}, {"X-Admin-Action": "1", "Origin": "https://other.example"},
    {"X-Admin-Action": "1", "Sec-Fetch-Site": "cross-site"},
])
def test_admin_mutations_require_same_origin_action(api, headers):
    public, admin, _, _ = api
    response = _link(admin, headers=headers)
    assert response.status_code == 403 and response.json().get("error")
    assert public.get("/api/help-resources").json() == {"items": []}


@pytest.mark.parametrize("kind,filename,content,media_type", [
    ("video", "guide.exe", MP4, "application/octet-stream"),
    ("video", "guide.pdf", PDF, "application/pdf"),
    ("manual", "guide.mp4", MP4, "video/mp4"),
    ("video", "guide.mp4", b"not a video", "video/mp4"),
    ("manual", "guide.pdf", b"<html>fake PDF</html>", "application/pdf"),
    ("manual", "guide.docx", b"PK-not-a-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("manual", "guide.doc", b"not a word document", "application/msword"),
    ("video", "guide.mp4", b"", "video/mp4"),
    ("video", "../guide.mp4", MP4, "video/mp4"),
    ("video", "folder/guide.mp4", MP4, "video/mp4"),
])
def test_bad_uploads_reject_empty_content_wrong_format_and_paths(api, kind, filename, content, media_type):
    public, admin, _, config = api
    response = _upload(admin, kind=kind, filename=filename, content=content, media_type=media_type)
    assert response.status_code in {400, 415} and response.json().get("error"), response.text
    assert public.get("/api/help-resources").json() == {"items": []}
    root = config.logs_dir.parent / "data" / "help_resources"
    assert not list(root.rglob("*.mp4")) and not list(root.rglob("*.pdf")) and not list(root.rglob("*.docx"))


@pytest.mark.parametrize("kind", ["video", "manual"])
def test_oversized_uploads_are_rejected_and_partial_file_is_removed(api, monkeypatch, kind):
    from src.common import help_resource_store

    public, admin, _, config = api
    monkeypatch.setitem(help_resource_store.MAX_UPLOAD_BYTES, kind, 20)
    kwargs = {} if kind == "video" else {"filename": "guide.pdf", "content": PDF, "media_type": "application/pdf"}
    response = _upload(admin, kind=kind, **kwargs)
    assert response.status_code == 413 and response.json().get("error")
    assert public.get("/api/help-resources").json() == {"items": []}
    root = config.logs_dir.parent / "data" / "help_resources"
    assert not list(root.rglob("*.mp4")) and not list(root.rglob("*.pdf"))


def test_invalid_metadata_is_reported_in_chinese_without_creating_items(api):
    public, admin, _, _ = api
    for payload in ({"kind": "unknown", "title": "资料", "source_url": "https://example.com"},
                    {"kind": "manual", "title": " ", "source_url": "https://example.com"},
                    {"kind": "manual", "title": "资料", "source_url": 123},
                    {"kind": "manual"}):
        response = admin.post("/api/help-resources-admin/links", json=payload, headers=WRITE_HEADERS)
        assert response.status_code == 400 and response.json().get("error")
        assert any("\u4e00" <= char <= "\u9fff" for char in response.json()["error"])
    assert public.get("/api/help-resources", params={"kind": "unknown"}).status_code == 400
    assert public.get("/api/help-resources").json() == {"items": []}


def test_docx_preview_contains_paragraph_table_and_embedded_image(api):
    public, admin, _, _ = api
    document = Document()
    document.add_heading("平台操作指南", level=1)
    document.add_paragraph("选择产品并上传技术要求。")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "第一步"
    table.cell(0, 1).text = "上传文件"
    document.add_paragraph("操作截图").add_run().add_picture(io.BytesIO(PNG))
    buffer = io.BytesIO()
    document.save(buffer)
    payload = buffer.getvalue()
    response = _upload(admin, kind="manual", title="操作指南", filename="操作指南.docx", content=payload,
                       media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert response.status_code == 201, response.text
    item = response.json()["item"]
    assert item["preview_type"] == "document"
    assert item["preview_url"] == f'/api/help-resources/{item["id"]}/document'
    response = public.get(item["preview_url"])
    assert response.status_code == 200, response.text
    projected = response.json()
    assert projected["format"] == "docx" and projected["view_mode"] == "content"
    assert projected["outline"][0]["text"] == "平台操作指南"
    assert any(block.get("text") == "选择产品并上传技术要求。" for block in projected["blocks"])
    table_block = next(block for block in projected["blocks"] if block["kind"] == "table")
    assert table_block["rows"][0]["cells"][1]["blocks"][0]["text"] == "上传文件"
    images = [image for block in projected["blocks"] for image in block.get("images", [])]
    assert len(images) == 1 and images[0]["available"] and images[0]["src"].startswith("data:image/png;base64,")
    assert public.get(item["content_url"], params={"download": 1}).content == payload


def test_pdf_upload_uses_inline_file_preview(api):
    public, admin, _, _ = api
    response = _upload(admin, kind="manual", filename="操作手册.pdf", content=PDF, media_type="application/pdf")
    assert response.status_code == 201, response.text
    item = response.json()["item"]
    assert item["preview_type"] == "pdf" and item["preview_url"] == item["content_url"]
    response = public.get(item["preview_url"])
    assert response.status_code == 200 and response.content == PDF
    assert response.headers["content-type"].startswith("application/pdf")


def test_legacy_doc_is_converted_locally_for_preview_and_keeps_original_download(api, monkeypatch):
    public, admin, _, _ = api
    legacy = bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy Word fixture"
    normalized_calls = []

    def normalize(source, output_dir):
        assert source.read_bytes() == legacy
        normalized_calls.append(source)
        document = Document()
        document.add_paragraph("本地转换后的操作说明")
        path = Path(output_dir) / "normalized.docx"
        document.save(path)
        return SimpleNamespace(path=path, warnings=("旧版 DOC 已本地转换，请核对原文件。",))

    monkeypatch.setattr(help_resources_controller, "normalize_input", normalize)
    response = _upload(admin, kind="manual", filename="操作指南.doc", content=legacy, media_type="application/msword")
    assert response.status_code == 201, response.text
    item = response.json()["item"]
    preview = public.get(item["preview_url"])
    assert preview.status_code == 200, preview.text
    assert preview.json()["blocks"][0]["text"] == "本地转换后的操作说明"
    assert preview.json()["warnings"] == ["旧版 DOC 已本地转换，请核对原文件。"]
    assert len(normalized_calls) == 1
    assert public.get(item["content_url"], params={"download": 1}).content == legacy


def test_failed_legacy_preview_keeps_original_available(api, monkeypatch):
    public, admin, _, _ = api
    legacy = bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy Word fixture"

    def unavailable(*args):
        raise ValueError("旧版 DOC 转换不可用，请安装本地转换器。")

    monkeypatch.setattr(help_resources_controller, "normalize_input", unavailable)
    item = _upload(admin, kind="manual", filename="操作指南.doc", content=legacy, media_type="application/msword").json()["item"]
    response = public.get(item["preview_url"])
    assert response.status_code == 422 and "本地转换器" in response.json()["error"]
    assert public.get(item["content_url"], params={"download": 1}).content == legacy


def test_store_rejects_windows_paths_and_never_deletes_outside_managed_files(tmp_path):
    root = tmp_path / "help_resources"
    store = HelpResourceStore(root)
    with pytest.raises(HelpResourceError):
        store.create_file("video", "无效路径", "C:\\private\\guide.mp4", io.BytesIO(MP4), "wangxue")
    item = store.create_file("video", "原始视频", "guide.mp4", io.BytesIO(MP4), "wangxue")
    managed = store.file_path(item)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"unrelated data")
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("UPDATE help_resources SET stored_name = ? WHERE id = ?", (str(outside), item["id"]))
    with pytest.raises(HelpResourceError):
        store.delete(item["id"])
    assert managed.read_bytes() == MP4
    assert outside.read_bytes() == b"unrelated data"
    assert store.get(item["id"]) is not None


def test_independent_stores_share_persisted_items_and_concurrent_writes(tmp_path):
    root = tmp_path / "help_resources"
    first = HelpResourceStore(root)
    second = HelpResourceStore(root)

    def add(index):
        store = first if index % 2 else second
        return store.create_link(kind="manual", title=f"手册 {index}", source_url=f"https://example.com/manual-{index}.pdf", created_by="wangxue")

    with ThreadPoolExecutor(max_workers=4) as pool:
        items = list(pool.map(add, range(8)))
    fresh = HelpResourceStore(root)
    assert {item["id"] for item in fresh.list()} == {item["id"] for item in items}
    assert second.delete(items[0]["id"])
    assert first.get(items[0]["id"]) is None
    assert len(fresh.list()) == 7


def test_delete_database_lock_preserves_original_and_allows_retry(api, monkeypatch):
    public, admin, _, config = api
    item = _upload(admin).json()["item"]
    store = help_resources_controller._store(config.logs_dir.parent / "data" / "help_resources")
    stored_path = store.file_path(item)
    original_connection = store._connection

    @contextmanager
    def short_timeout_connection():
        with original_connection() as connection:
            connection.execute("PRAGMA busy_timeout = 50")
            yield connection

    monkeypatch.setattr(store, "_connection", short_timeout_connection)
    with sqlite3.connect(store.db_path) as other_writer:
        other_writer.execute("BEGIN IMMEDIATE")
        try:
            response = admin.delete(f'/api/help-resources-admin/{item["id"]}', headers=WRITE_HEADERS)
            assert response.status_code == 503 and response.json().get("error")
            assert store.get(item["id"]) == item
            assert stored_path.is_file(), "A rejected deletion must retain the original file."
            assert public.get(item["content_url"], params={"download": 1}).content == MP4
        finally:
            other_writer.rollback()
    response = admin.delete(f'/api/help-resources-admin/{item["id"]}', headers=WRITE_HEADERS)
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert store.get(item["id"]) is None and not stored_path.exists()


def test_delete_commit_failure_restores_original_and_allows_retry(api, monkeypatch):
    public, admin, _, config = api
    item = _upload(admin).json()["item"]
    store = help_resources_controller._store(config.logs_dir.parent / "data" / "help_resources")
    stored_path = store.file_path(item)
    fail_next_commit = {"enabled": True}

    class FailingCommitConnection(sqlite3.Connection):
        deleted_resource = False

        def execute(self, sql, *args, **kwargs):
            result = super().execute(sql, *args, **kwargs)
            if sql.lstrip().upper().startswith("DELETE FROM HELP_RESOURCES"):
                self.deleted_resource = True
            return result

        def __exit__(self, exc_type, exc_value, traceback):
            if exc_type is None and self.deleted_resource and fail_next_commit["enabled"]:
                fail_next_commit["enabled"] = False
                self.rollback()
                raise sqlite3.OperationalError("synthetic commit failure")
            return super().__exit__(exc_type, exc_value, traceback)

    @contextmanager
    def failing_connection():
        connection = sqlite3.connect(store.db_path, factory=FailingCommitConnection)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    monkeypatch.setattr(store, "_connection", failing_connection)
    response = admin.delete(f'/api/help-resources-admin/{item["id"]}', headers=WRITE_HEADERS)
    assert response.status_code == 503 and response.json().get("error")
    assert "synthetic" not in response.text
    assert store.get(item["id"]) == item
    assert stored_path.is_file(), "A failed database commit must restore the original file."
    assert public.get(item["content_url"], params={"download": 1}).content == MP4
    response = admin.delete(f'/api/help-resources-admin/{item["id"]}', headers=WRITE_HEADERS)
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert store.get(item["id"]) is None and not stored_path.exists()


def test_malformed_docx_styles_return_preview_error_and_keep_original_download(api):
    public, admin, _, _ = api
    document = Document()
    document.add_paragraph("原始文档仍可下载。")
    original = io.BytesIO()
    document.save(original)
    corrupt = io.BytesIO()
    with ZipFile(original) as source, ZipFile(corrupt, "w") as target:
        for member in source.infolist():
            target.writestr(member, b"not valid styles XML" if member.filename == "word/styles.xml" else source.read(member.filename))
    payload = corrupt.getvalue()
    response = _upload(admin, kind="manual", filename="样式损坏的手册.docx", content=payload,
                       media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert response.status_code == 201, response.text
    item = response.json()["item"]
    with TestClient(public.app, raise_server_exceptions=False) as reader:
        response = reader.get(item["preview_url"])
        assert response.status_code == 422, response.text
        assert any("\u4e00" <= char <= "\u9fff" for char in response.json()["error"])
        assert reader.get(item["content_url"], params={"download": 1}).content == payload
