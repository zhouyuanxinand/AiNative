"""Local ONLYOFFICE integration; saved files always become review revisions.

The editor is optional. Content editing and review storage do not depend on this
service. Editor callbacks authenticate their payload before fetching a file and
use the same optimistic revision check as the built-in content editor.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from filelock import FileLock
from jonhon_taskbook.review_store import ReviewConflictError


class EditorError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise EditorError("文档编辑服务地址配置无效。", 503)
    return value


@dataclass(frozen=True)
class EditorConfig:
    browser_url: str
    internal_url: str
    public_url: str
    secret: str

    @classmethod
    def from_env(cls):
        from dotenv import dotenv_values
        # Development uses the service root; packaged deployments keep their
        # private env alongside the service package. Process values win.
        values = {}
        module = Path(__file__).resolve()
        for path in (module.parents[1] / ".env", module.parents[5] / ".env"):
            if path.is_file():
                values.update(dotenv_values(path, interpolate=False))
        setting = lambda key: os.environ.get(key, values.get(key) or "")
        browser = setting("JTB_REVIEW_EDITOR_URL").strip()
        public = setting("JTB_REVIEW_PUBLIC_URL").strip()
        secret = setting("JTB_REVIEW_EDITOR_SECRET")
        if not browser or not public or len(secret) < 32:
            raise EditorError("版式编辑服务尚未配置，可使用正文编辑。", 503)
        return cls(_url(browser), _url(setting("JTB_REVIEW_EDITOR_INTERNAL_URL") or browser), _url(public), secret)

    @property
    def script_url(self):
        return self.browser_url + "/web-apps/apps/api/documents/api.js"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_token(payload: dict, secret: str) -> str:
    header = _b64(b'{"alg":"HS256","typ":"JWT"}')
    body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    message = f"{header}.{body}"
    return message + "." + _b64(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest())


def verify_token(token: str, secret: str) -> dict:
    try:
        header, body, signature = token.split(".")
        decode = lambda value: json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if decode(header).get("alg") != "HS256":
            raise ValueError("algorithm")
        expected = _b64(hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            raise ValueError("signature")
        claims = decode(body)
        if not isinstance(claims, dict) or ("exp" in claims and float(claims["exp"]) <= time.time()):
            raise ValueError("expired")
        return claims
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise EditorError("文档编辑服务签名无效或已过期。", 403) from exc


def _write_json(path: Path, data: dict):
    temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ReviewEditor:
    def __init__(self, store, root: Path, config: EditorConfig):
        self.store = store
        self.root = Path(root)
        self.config = config

    def _session_path(self, jid: str, sid: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", jid) or not re.fullmatch(r"[a-f0-9]{32}", sid):
            raise EditorError("编辑会话不存在。", 404)
        return self.root / jid / "editor_sessions" / f"{sid}.json"

    def _session(self, jid: str, sid: str) -> dict:
        path = self._session_path(jid, sid)
        if not path.is_file():
            raise EditorError("编辑会话不存在，请重新打开版式编辑。", 404)
        session = json.loads(path.read_text(encoding="utf-8"))
        if session["expires_at"] < time.time():
            raise EditorError("编辑会话已过期，请重新打开版式编辑。", 410)
        return session

    def open(self, jid: str, revision_id: str, mode: str = "edit") -> dict:
        bundle = self.store.get_review(jid)
        if mode not in {"edit", "view"}:
            raise EditorError("无效的编辑模式。")
        if mode == "edit" and revision_id != bundle["current_revision_id"]:
            raise EditorError("当前版本已更新，请刷新后再编辑。", 409)
        source = self.store.revision_path(jid, revision_id)
        sid = uuid.uuid4().hex
        expires = int(time.time()) + 86400
        session = {
            "id": sid, "jid": jid, "initial_revision_id": revision_id,
            "revision_id": revision_id, "key": f"review-{sid}", "mode": mode,
            "status": "opened", "message": "已打开", "created_at": time.time(),
            "expires_at": expires, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
        session["accepted_callbacks"] = []
        path = self._session_path(jid, sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(path, session)
        capability = sign_token({"jid": jid, "sid": sid, "purpose": "editor-file", "exp": expires}, self.config.secret)
        prefix = f"{self.config.public_url}/api/review/{jid}/editor/{sid}"
        config = {
            "documentType": "word", "type": "desktop", "width": "100%", "height": "100%",
            "document": {
                "fileType": "docx", "key": session["key"],
                "title": Path(str(bundle.get("title") or "研制任务书.docx")).stem + ".docx",
                "url": prefix + "/file?" + urlencode({"token": capability}),
                "permissions": {"edit": mode == "edit", "download": False, "print": True, "comment": mode == "edit"},
            },
            "editorConfig": {
                "mode": mode, "lang": "zh-CN", "callbackUrl": prefix + "/callback",
                "user": {"id": "taskbook-" + sid, "name": "任务书审阅用户"},
                "customization": {"forcesave": False, "compactHeader": True, "compactToolbar": True},
            },
        }
        config["token"] = sign_token(config, self.config.secret)
        return {"session_id": sid, "script_url": self.config.script_url, "config": config}

    def state(self, jid: str, sid: str) -> dict:
        session = self._session(jid, sid)
        return {key: session.get(key) for key in ("id", "status", "revision_id", "message", "saved_at", "saved_request_id")}

    def file(self, jid: str, sid: str, token: str) -> Path:
        claims = verify_token(token, self.config.secret)
        if claims.get("jid") != jid or claims.get("sid") != sid or claims.get("purpose") != "editor-file":
            raise EditorError("无效的文档访问凭证。", 403)
        session = self._session(jid, sid)
        return self.store.revision_path(jid, session["initial_revision_id"])

    def _download_url(self, url: str) -> str:
        parsed = urlsplit(url)
        origins = [urlsplit(value) for value in (self.config.browser_url, self.config.internal_url)]
        def origin(parts):
            return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
        if parsed.username or parsed.password or parsed.fragment:
            raise EditorError("文档编辑服务返回了无效的文件地址。", 502)
        for allowed in origins:
            if origin(parsed) == origin(allowed) and (parsed.path.startswith(allowed.path.rstrip("/") + "/")):
                suffix = parsed.path[len(allowed.path.rstrip("/")):]
                return self.config.internal_url + suffix + ("?" + parsed.query if parsed.query else "")
        raise EditorError("文档编辑服务返回的文件地址不属于配置的服务。", 502)

    def _download(self, url: str, destination: Path):
        with httpx.Client(timeout=45, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", self._download_url(url)) as response:
                response.raise_for_status()
                size = 0
                with destination.open("wb") as output:
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 100 * 1024 * 1024:
                            raise EditorError("编辑后的文件超过 100 MB。", 413)
                        output.write(chunk)

    def callback(self, jid: str, sid: str, token: str) -> dict:
        signed = verify_token(token, self.config.secret)
        payload = signed.get("payload", signed)
        if not isinstance(payload, dict):
            raise EditorError("无效的编辑回调。", 400)
        path = self._session_path(jid, sid)
        with FileLock(str(path) + ".lock", timeout=60):
            session = self._session(jid, sid)
            if payload.get("key") != session["key"]:
                raise EditorError("回调文档与编辑会话不一致。", 403)
            status = payload.get("status")
            callback_id = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if callback_id in session["accepted_callbacks"]:
                return {"error": 0}
            if status in {6, 7} and payload.get("userdata") != session.get("requested_save_id"):
                raise EditorError("该保存回调不属于当前保存请求，请重新保存。", 409)
            if status in {3, 7}:
                session.update(status="error", message="文档编辑服务保存失败，请在编辑器中重试保存。")
            elif status == 4:
                session.update(status="closed", message="已关闭编辑")
            elif status in {2, 6}:
                if session["mode"] != "edit":
                    raise EditorError("只读会话不能保存修改。", 403)
                if payload.get("filetype", "docx") != "docx":
                    raise EditorError("编辑器必须返回 DOCX 文件。")
                try:
                    with tempfile.TemporaryDirectory(prefix="taskbook-editor-") as temp:
                        downloaded = Path(temp) / "edited.docx"
                        self._download(str(payload.get("url") or ""), downloaded)
                        digest = hashlib.sha256(downloaded.read_bytes()).hexdigest()
                        if digest != session["sha256"]:
                            bundle = self.store.save_revision(jid, session["revision_id"], downloaded, actor="web-user", reason="版式编辑")
                            session.update(revision_id=bundle["current_revision_id"], sha256=digest)
                    session.update(status="saved", message="修订版已保存", saved_at=time.time())
                    session["saved_request_id"] = payload.get("userdata") if status == 6 else None
                    session["accepted_callbacks"].append(callback_id)
                except Exception as exc:
                    session.update(status="error", message="修订版未保存：版本可能已更新，或编辑服务回传失败。请保留编辑器并重试。")
                    _write_json(path, session)
                    if isinstance(exc, EditorError):
                        raise
                    raise EditorError(session["message"], 409 if isinstance(exc, ReviewConflictError) else 502) from exc
            elif status != 1:
                raise EditorError("无效的编辑回调状态。")
            _write_json(path, session)
        return {"error": 0}

    def save(self, jid: str, sid: str) -> dict:
        path = self._session_path(jid, sid)
        with FileLock(str(path) + ".lock", timeout=60):
            session = self._session(jid, sid)
            if session["mode"] != "edit":
                raise EditorError("只读会话不能保存修改。")
            request_id = uuid.uuid4().hex
            session.update(requested_save_id=request_id, status="opened", message="正在保存")
            _write_json(path, session)
        payload = {"c": "forcesave", "key": session["key"], "userdata": request_id}
        payload["token"] = sign_token(payload, self.config.secret)
        try:
            with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
                response = client.post(self.config.internal_url + "/coauthoring/CommandService.ashx", json=payload)
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EditorError("无法联系文档编辑服务，请稍后重试保存。", 502) from exc
        if result.get("error") == 4:
            return {"status": "unchanged", "message": "编辑器暂无可保存的新内容。"}
        if result.get("error") != 0:
            raise EditorError("文档编辑服务未接受保存请求，请在编辑器内重试。", 502)
        return {"status": "pending", "save_request_id": request_id, "message": "正在保存，收到文件后将更新修订版。"}
