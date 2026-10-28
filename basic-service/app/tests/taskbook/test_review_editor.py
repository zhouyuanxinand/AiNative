"""The optional editor must save real revisions, not acknowledge lost updates."""
import hashlib
import json
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from docx import Document

from jonhon_taskbook.review_editor import EditorConfig, EditorError, ReviewEditor, sign_token, verify_token


class Store:
    def __init__(self, root):
        self.root = root
        self.current = "baseline"
        self.paths = {"baseline": root / "baseline.docx"}
        document = Document()
        document.add_paragraph("原始要求：接触电阻不大于 5 mΩ。")
        document.save(self.paths["baseline"])

    def get_review(self, jid):
        return {"current_revision_id": self.current, "title": "审阅样例"}

    def revision_path(self, jid, rid):
        return self.paths[rid]

    def save_revision(self, jid, expected, path, **kwargs):
        if expected != self.current:
            raise EditorError("版本已更新", 409)
        Document(path)
        self.current = "r" + str(len(self.paths))
        self.paths[self.current] = self.root / (self.current + ".docx")
        shutil.copy2(path, self.paths[self.current])
        return self.get_review(jid)


@pytest.fixture
def setup_editor(tmp_path):
    config = EditorConfig("http://localhost:18160", "http://document-editor", "http://taskbook", "test-only-secret-" * 4)
    store = Store(tmp_path)
    editor = ReviewEditor(store, tmp_path / "reviews", config)
    opened = editor.open("task1", "baseline")
    return editor, store, opened


def callback_token(editor, opened, status=6, **extra):
    sid = opened["session_id"]
    session_path = editor._session_path("task1", sid)
    session = json.loads(session_path.read_text(encoding="utf-8"))
    request_id = extra.pop("userdata", "test-save-1")
    session["requested_save_id"] = request_id
    session_path.write_text(json.dumps(session), encoding="utf-8")
    payload = {"key": opened["config"]["document"]["key"], "status": status,
               "url": "http://document-editor/cache/files/output.docx", "filetype": "docx", "userdata": request_id}
    return sign_token({"payload": payload | extra}, editor.config.secret)


def test_editor_file_capability_is_bound_to_session_and_cannot_change_body(setup_editor):
    editor, store, opened = setup_editor
    config = opened["config"]
    assert verify_token(config["token"], editor.config.secret)["document"]["key"] == config["document"]["key"]
    token = parse_qs(urlsplit(config["document"]["url"]).query)["token"][0]
    assert editor.file("task1", opened["session_id"], token) == store.paths["baseline"]
    with pytest.raises(EditorError, match="无效"):
        editor.file("task2", opened["session_id"], token)
    header, body, signature = token.split(".")
    with pytest.raises(EditorError, match="签名"):
        verify_token(header + "." + body + "." + signature[::-1], editor.config.secret)
    with pytest.raises(EditorError, match="过期"):
        verify_token(sign_token({"exp": time.time() - 1}, editor.config.secret), editor.config.secret)


def test_force_save_persists_docx_without_touching_baseline_and_deduplicates(setup_editor, tmp_path, monkeypatch):
    editor, store, opened = setup_editor
    baseline_hash = hashlib.sha256(store.paths["baseline"].read_bytes()).hexdigest()
    edit = tmp_path / "edited.docx"
    doc = Document(store.paths["baseline"])
    doc.add_paragraph("用户补充的交付要求。")
    doc.save(edit)
    monkeypatch.setattr(editor, "_download", lambda url, destination: shutil.copy2(edit, destination))
    token = callback_token(editor, opened)
    assert editor.callback("task1", opened["session_id"], token) == {"error": 0}
    assert store.current == "r1"
    assert Document(store.paths["r1"]).paragraphs[-1].text == "用户补充的交付要求。"
    assert hashlib.sha256(store.paths["baseline"].read_bytes()).hexdigest() == baseline_hash
    editor.callback("task1", opened["session_id"], token)
    assert store.current == "r1"
    assert editor.state("task1", opened["session_id"])["status"] == "saved"


def test_old_editor_cannot_overwrite_later_content_revision(setup_editor, tmp_path, monkeypatch):
    editor, store, opened = setup_editor
    edited = tmp_path / "edited.docx"
    doc = Document(store.paths["baseline"])
    doc.add_paragraph("内容编辑器的新版本")
    doc.save(edited)
    store.save_revision("task1", "baseline", edited)
    doc.add_paragraph("旧窗口里未保存的内容")
    doc.save(edited)
    monkeypatch.setattr(editor, "_download", lambda url, destination: shutil.copy2(edited, destination))
    with pytest.raises(EditorError):
        editor.callback("task1", opened["session_id"], callback_token(editor, opened))
    assert store.current == "r1"
    assert editor.state("task1", opened["session_id"])["status"] == "error"


def test_callback_file_downloads_are_confined_to_editor_origin(setup_editor):
    editor, _, _ = setup_editor
    assert editor._download_url("http://localhost:18160/cache/files/doc?token=x") == "http://document-editor/cache/files/doc?token=x"
    for url in ("http://example.org/document.docx", "http://document-editor:8080/file", "file:///etc/passwd", "http://user@document-editor/file"):
        with pytest.raises(EditorError):
            editor._download_url(url)


def test_unsigned_or_other_session_callback_cannot_save(setup_editor):
    editor, store, opened = setup_editor
    with pytest.raises(EditorError):
        editor.callback("task1", opened["session_id"], "")
    with pytest.raises(EditorError, match="不一致"):
        editor.callback("task1", opened["session_id"], callback_token(editor, opened, key="different"))
    assert store.current == "baseline"


def test_unconfigured_editor_does_not_expose_secret(monkeypatch):
    for key in ("JTB_REVIEW_EDITOR_URL", "JTB_REVIEW_PUBLIC_URL", "JTB_REVIEW_EDITOR_SECRET"):
        monkeypatch.setenv(key, "")
    with pytest.raises(EditorError, match="正文编辑"):
        EditorConfig.from_env()


def test_restore_previous_text_is_new_save_not_stale_callback(setup_editor, tmp_path, monkeypatch):
    editor, store, opened = setup_editor
    first = tmp_path / "first.docx"
    second = tmp_path / "second.docx"
    doc = Document(store.paths["baseline"])
    doc.add_paragraph("人工修订A")
    doc.save(first)
    doc.add_paragraph("人工修订B")
    doc.save(second)
    selected = [first]
    monkeypatch.setattr(editor, "_download", lambda url, destination: shutil.copy2(selected[0], destination))
    first_token = callback_token(editor, opened, userdata="request-a")
    editor.callback("task1", opened["session_id"], first_token)
    selected[0] = second
    editor.callback("task1", opened["session_id"], callback_token(editor, opened, userdata="request-b"))
    # A replayed callback cannot roll back B.
    editor.callback("task1", opened["session_id"], first_token)
    assert store.current == "r2"
    selected[0] = first
    editor.callback("task1", opened["session_id"], callback_token(editor, opened, userdata="request-c"))
    assert store.current == "r3"
    assert Document(store.paths["r3"]).paragraphs[-1].text == "人工修订A"
    assert editor.state("task1", opened["session_id"])["saved_request_id"] == "request-c"
