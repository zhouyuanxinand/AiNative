"""Converted sources and adopted replies remain usable without implying approval."""
from copy import deepcopy
from pathlib import Path

from docx import Document

from src.service.rd_platform import completion


def test_legacy_word_conversion_retains_review_status_and_original_identity(tmp_path, monkeypatch):
    from jonhon_taskbook.input_normalizer import NormalizedInput
    original = tmp_path / "input.doc"
    original.write_bytes(b"legacy Word source")
    converted = tmp_path / "converted.docx"
    doc = Document()
    doc.add_paragraph("工作压力不低于0.3 MPa。")
    doc.save(converted)
    monkeypatch.setattr("jonhon_taskbook.input_normalizer.normalize_input", lambda *a: NormalizedInput(
        converted, original, "libreoffice", ("请复核转换排版",), True))
    source = {"id": "tech", "role": "tech", "name": original.name, "path": str(original),
              "sha256": completion.sha256(original), "version": 1}
    blocks = completion.evidence_blocks([source], tmp_path / "work")
    assert blocks[0]["quote"] == "工作压力不低于0.3 MPa。"
    assert blocks[0]["sha256"] == source["sha256"]
    assert blocks[0]["normalization"]["requires_review"] is True
    assert blocks[0]["normalization"]["normalized_sha256"] == completion.sha256(converted)
    assert original.read_bytes() == b"legacy Word source"


def adopted_reply_fixture(tmp_path):
    template = tmp_path / "template.docx"
    doc = Document()
    doc.add_heading("技术要求", 1)
    doc.add_paragraph("受控模板正文")
    doc.save(template)
    content = "贮存温度范围为-40℃至+85℃。"
    source = {"id": "reply", "sha256": "source-hash", "version": 2}
    req = {"id": "r10", "revision": 3, "title": "贮存温度", "content": content,
           "source_ids": ["reply"], "history": [{"revision": 3, "clarification_id": "cl1"}]}
    reply = {"id": "cl1", "requirement_id": "r10", "status": "adopted",
             "answer_source_ids": ["reply"], "answer_source_snapshots": [source],
             "adoption": {"requirement_revision": 3, "requirement_content": content}}
    block = {"source_id": "reply", "role": "reference", "sha256": "source-hash", "version": 2,
             "location": {"body_index": 2}, "quote": content, "heading": "贮存温度"}
    return template, req, reply, block


def test_adopted_clarification_proves_current_requirement_from_fixed_reference(tmp_path):
    template, req, reply, block = adopted_reply_fixture(tmp_path)
    ledger = completion.build_completion_ledger(template, {}, [block], requirements=[req], clarifications=[reply])
    entry = next(item for item in ledger if item["kind"] == "case_requirement")
    assert entry["status"] == "evidence_ready"
    assert entry["candidates"][0]["adopted"] is True
    assert entry["candidates"][0]["adoption"]["clarification_id"] == "cl1"


def test_unadopted_or_changed_reference_cannot_prove_requirement(tmp_path):
    template, req, reply, block = adopted_reply_fixture(tmp_path)
    for changes in ({"status": "answered"}, {"adoption": {"requirement_revision": 2, "requirement_content": req["content"]}},
                    {"answer_source_snapshots": [{"id": "reply", "version": 1, "sha256": "old"}]}):
        altered = {**deepcopy(reply), **changes}
        ledger = completion.build_completion_ledger(template, {}, [block], requirements=[req], clarifications=[altered])
        entry = next(item for item in ledger if item["kind"] == "case_requirement")
        assert entry["status"] == "blocked"
        assert entry["candidates"][0]["adopted"] is False
