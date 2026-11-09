"""Word COM receives short temporary names even for deep RD asset paths."""
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document

from jonhon_taskbook import input_normalizer as normalizer


def install_word(monkeypatch, *, returns_none=False, close_raises=False):
    observed = {'initialized': 0, 'uninitialized': 0, 'quit': 0, 'closed': 0}
    def initialize():
        observed['initialized'] += 1
    def uninitialize():
        observed['uninitialized'] += 1
    def save(path, **kwargs):
        observed['destination'] = Path(path)
        assert len(path) < 240
        document = Document()
        document.add_paragraph('转换后的真实文件结构')
        document.save(path)
    def close(*args):
        observed['closed'] += 1
        if close_raises:
            raise RuntimeError('close failure')
    def open_document(path, **kwargs):
        observed['source'] = Path(path)
        observed['source_bytes'] = Path(path).read_bytes()
        assert len(path) < 240
        assert kwargs['ReadOnly'] is True and kwargs['AddToRecentFiles'] is False
        return None if returns_none else SimpleNamespace(SaveAs2=save, Close=close)
    def quit_word():
        observed['quit'] += 1
    def invoke_open(dispid, lcid, flags, result, path, confirm, readonly, recent, *optional):
        return open_document(path, ReadOnly=readonly, AddToRecentFiles=recent,
                             ConfirmConversions=confirm, Visible=optional[-1])
    documents = SimpleNamespace(GetIDsOfNames=lambda name: 19, Invoke=invoke_open)
    word = SimpleNamespace(Documents=SimpleNamespace(_oleobj_=documents), Quit=quit_word,
                           Options=SimpleNamespace(UpdateLinksAtOpen=True))
    monkeypatch.setitem(sys.modules, 'pythoncom', SimpleNamespace(
        CoInitialize=initialize, CoUninitialize=uninitialize, VT_ERROR=10, DISPATCH_METHOD=1))
    monkeypatch.setitem(sys.modules, 'winerror', SimpleNamespace(DISP_E_PARAMNOTFOUND=-2147352572))
    client = SimpleNamespace(dynamic=SimpleNamespace(Dispatch=lambda obj, name: obj), VARIANT=lambda *args: args)
    monkeypatch.setitem(sys.modules, 'win32com', SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, 'win32com.client', client)
    monkeypatch.setattr(normalizer, '_create_word_application', lambda: word)
    monkeypatch.setattr(normalizer, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(normalizer.shutil, 'which', lambda name: None)
    return observed, word


def deep_paths(tmp_path):
    directory = tmp_path / ('project-' + 'a' * 60) / ('case-' + 'b' * 60) / ('analysis-' + 'c' * 60)
    directory.mkdir(parents=True)
    source = directory / ('input-' + 'd' * 60 + '.doc')
    source.write_bytes(b'immutable-original-DOC')
    destination = directory / 'normalized' / ('e' * 40) / 'normalized.docx'
    destination.parent.mkdir(parents=True)
    assert len(str(source)) > 260 and len(str(destination)) > 260
    return source, destination


def test_word_receives_short_staged_paths_and_original_is_unchanged(tmp_path, monkeypatch):
    source, destination = deep_paths(tmp_path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    observed, word = install_word(monkeypatch)
    assert normalizer._convert_legacy_doc(source, destination) == 'word_com'
    assert observed['source_bytes'] == source.read_bytes()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert Document(destination).paragraphs[0].text == '转换后的真实文件结构'
    assert observed['source'] != source and observed['destination'] != destination
    assert observed['closed'] == observed['quit'] == observed['uninitialized'] == 1
    assert word.Options.UpdateLinksAtOpen is True
    assert not observed['source'].parent.exists()


def test_word_none_open_result_still_quits_and_removes_only_own_staging(tmp_path, monkeypatch):
    source, destination = deep_paths(tmp_path)
    observed, _ = install_word(monkeypatch, returns_none=True)
    with pytest.raises(normalizer.InputNormalizationError):
        normalizer._convert_legacy_doc(source, destination)
    assert observed['quit'] == observed['uninitialized'] == 1
    assert not observed['source'].parent.exists()
    assert source.exists() and not destination.exists()


def test_word_close_error_does_not_skip_quit_and_com_release(tmp_path, monkeypatch):
    source, destination = deep_paths(tmp_path)
    observed, _ = install_word(monkeypatch, close_raises=True)
    normalizer._convert_legacy_doc(source, destination)
    assert observed['quit'] == observed['uninitialized'] == 1
    assert source.exists() and destination.is_file()
