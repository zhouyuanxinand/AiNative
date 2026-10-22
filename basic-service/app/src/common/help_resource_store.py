"""Shared SQLite catalogue and locally owned files for operating instructions."""
from __future__ import annotations

import logging
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, ZipFile

MAX_UPLOAD_BYTES = {"video": 500 * 1024 * 1024, "manual": 50 * 1024 * 1024}
CHUNK_BYTES = 1024 * 1024
MEDIA_TYPES = {
    ".mp4": "video/mp4", ".webm": "video/webm", ".ogg": "video/ogg",
    ".pdf": "application/pdf", ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
EXTENSIONS = {"video": {".mp4", ".webm", ".ogg"}, "manual": {".pdf", ".doc", ".docx"}}
_ID = re.compile(r"^[0-9a-f]{32}$")
logger = logging.getLogger(__name__)


class HelpResourceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def validate_kind(kind: str) -> str:
    if kind not in EXTENSIONS:
        raise HelpResourceError("资料分类须为操作视频或操作手册。")
    return kind


def _title(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise HelpResourceError("资料名称不能为空，且最多为 200 个字符。")
    if any(ord(char) < 32 for char in value):
        raise HelpResourceError("资料名称不能包含控制字符。")
    return value.strip()


def _source_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise HelpResourceError("请填写有效的 HTTP 或 HTTPS 资料链接。")
    value = value.strip()
    if any(ord(char) <= 32 for char in value) or "\\" in value:
        raise HelpResourceError("资料链接不能包含空格、控制字符或反斜杠。")
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        parsed.port  # Validate malformed or out-of-range ports as well.
    except ValueError as exc:
        raise HelpResourceError("资料链接须为不含账号密码的 HTTP 或 HTTPS 地址。") from exc
    return value


def _filename(value: str, kind: str) -> tuple[str, str]:
    if (not isinstance(value, str) or not value or len(value) > 240
            or any(char in value for char in '/\\:<>"|?*')
            or any(ord(char) < 32 for char in value) or value in {".", ".."}):
        raise HelpResourceError("文件名不正确，请使用不含路径的普通文件名。")
    extension = Path(value).suffix.lower()
    if extension not in EXTENSIONS[kind]:
        formats = "MP4、WebM、OGG" if kind == "video" else "PDF、DOC、DOCX"
        raise HelpResourceError(f"该分类仅支持 {formats} 文件。")
    return value, extension


def _validate_file(path: Path, extension: str) -> None:
    with path.open("rb") as stream:
        header = stream.read(16)
    signatures = {
        ".mp4": header[4:8] == b"ftyp", ".webm": header.startswith(b"\x1aE\xdf\xa3"),
        ".ogg": header.startswith(b"OggS"), ".pdf": header.startswith(b"%PDF-"),
        ".doc": header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
    }
    if extension == ".docx":
        try:
            with ZipFile(path) as archive:
                names = archive.namelist()
                valid = "word/document.xml" in names and "[Content_Types].xml" in names
                valid = valid and len(names) == len(set(names))
                # Bound archive expansion before the document preview reads XML.
                valid = valid and sum(item.file_size for item in archive.infolist()) <= 200 * 1024 * 1024
        except (BadZipFile, OSError):
            valid = False
    else:
        valid = signatures.get(extension, False)
    if not valid:
        raise HelpResourceError("文件内容与扩展名不符，或文件已经损坏。")


class HelpResourceStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.files_dir = self.root / "files"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "catalogue.sqlite3"
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS help_resources (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
                    source_type TEXT NOT NULL, source_url TEXT, filename TEXT,
                    stored_name TEXT, size_bytes INTEGER, media_type TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by TEXT NOT NULL
                )
            """)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _item(row) -> dict:
        item = dict(row)
        item.pop("stored_name", None)
        if item["source_type"] == "file":
            extension = Path(item["filename"]).suffix.lower()
            item["content_url"] = f"/api/help-resources/{item['id']}/file"
            preview_type = "video" if item["kind"] == "video" else "pdf" if extension == ".pdf" else "document"
            preview_url = f"/api/help-resources/{item['id']}/document" if preview_type == "document" else item["content_url"]
        else:
            extension = Path(unquote(urlsplit(item["source_url"]).path)).suffix.lower()
            preview_type = "video" if extension in EXTENSIONS["video"] else "pdf" if extension == ".pdf" else "link"
            item["content_url"] = None
            preview_url = item["source_url"]
        return dict(item, preview_type=preview_type, preview_url=preview_url)

    def list(self, kind: str | None = None) -> list[dict]:
        if kind is not None:
            validate_kind(kind)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM help_resources" + (" WHERE kind = ?" if kind else "") + " ORDER BY created_at DESC, id DESC",
                (kind,) if kind else (),
            ).fetchall()
        return [self._item(row) for row in rows]

    def _row(self, resource_id: str):
        if not _ID.fullmatch(resource_id):
            return None
        with self._connection() as connection:
            return connection.execute("SELECT * FROM help_resources WHERE id = ?", (resource_id,)).fetchone()

    def get(self, resource_id: str) -> dict | None:
        row = self._row(resource_id)
        return self._item(row) if row is not None else None

    def _insert(self, values: dict) -> dict:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO help_resources (" + ",".join(values) + ") VALUES (" + ",".join("?" for _ in values) + ")",
                tuple(values.values()),
            )
        return self._item(values)

    def _base(self, kind: str, title: str, created_by: str) -> dict:
        stamp = datetime.now(timezone.utc).isoformat()
        return {"id": uuid.uuid4().hex, "kind": validate_kind(kind), "title": _title(title),
                "created_by": created_by, "created_at": stamp, "updated_at": stamp}

    def create_link(self, kind: str, title: str, source_url: str, created_by: str) -> dict:
        item = self._base(kind, title, created_by)
        return self._insert(dict(item, source_type="link", source_url=_source_url(source_url),
                                 filename=None, stored_name=None, size_bytes=None, media_type=None))

    def create_file(self, kind: str, title: str, filename: str, stream: BinaryIO, created_by: str) -> dict:
        item = self._base(kind, title, created_by)
        filename, extension = _filename(filename, kind)
        stored_name = item["id"] + extension
        destination = self.files_dir / stored_name
        size = 0
        created = False
        try:
            with destination.open("xb") as output:
                created = True
                while chunk := stream.read(CHUNK_BYTES):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES[kind]:
                        raise HelpResourceError(f"文件超过 {MAX_UPLOAD_BYTES[kind] // (1024 * 1024)} MB 上传限制。", 413)
                    output.write(chunk)
            if not size:
                raise HelpResourceError("不能上传空文件。")
            _validate_file(destination, extension)
            return self._insert(dict(item, source_type="file", source_url=None, filename=filename,
                                     stored_name=stored_name, size_bytes=size, media_type=MEDIA_TYPES[extension]))
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise

    def _owned_path(self, row) -> Path:
        name = row["stored_name"]
        extension = Path(row["filename"]).suffix.lower()
        if (not _ID.fullmatch(row["id"]) or extension not in EXTENSIONS.get(row["kind"], ())
                or name != row["id"] + extension):
            raise HelpResourceError("资料文件记录不正确，无法读取或删除。", 409)
        path = self.files_dir / name
        if path.resolve().parent != self.files_dir.resolve() or path.is_symlink():
            raise HelpResourceError("资料文件路径不正确，无法读取或删除。", 409)
        return path

    def file_path(self, item: dict) -> Path:
        row = self._row(item["id"])
        if row is None or row["source_type"] != "file":
            raise HelpResourceError("资料文件不存在。", 404)
        path = self._owned_path(row)
        if not path.is_file():
            raise HelpResourceError("资料文件不存在。", 404)
        return path

    def delete(self, resource_id: str) -> bool:
        if not _ID.fullmatch(resource_id):
            return False
        path = staged = None
        try:
            with self._connection() as connection:
                # Acquire the writer lock before touching a file, then read the
                # current record under that lock so competing deletions serialize.
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute("SELECT * FROM help_resources WHERE id = ?", (resource_id,)).fetchone()
                if row is None:
                    return False
                path = self._owned_path(row) if row["source_type"] == "file" else None
                if path is not None and path.exists():
                    pending = self.files_dir / f"{resource_id}.delete-{uuid.uuid4().hex}"
                    path.rename(pending)
                    staged = pending
                connection.execute("DELETE FROM help_resources WHERE id = ?", (resource_id,))
        except BaseException:
            if staged is not None:
                staged.replace(path)
            raise
        if staged is not None:
            try:
                staged.unlink()
            except OSError:
                # The catalogue deletion has committed. A temporary cleanup
                # failure must not report that the now-deleted item still exists.
                logger.exception("help_resource_deleted_file_cleanup_failed", extra={"resource_id": resource_id})
        return True
