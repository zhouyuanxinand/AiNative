"""Input conversion is connected before routing and cannot bypass delivery review."""

import hashlib
import json
from pathlib import Path

import pymupdf
from docx import Document
from jonhon_taskbook import delivery_gate, requirement_classifier

from src.pipeline_cli import _run_delivery_gate_stage, run_pipeline


def test_pdf_is_normalized_before_semantic_classification(tmp_path, monkeypatch):
    tech = tmp_path / "technical.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Contact resistance: max 5 mOhm")
    pdf.save(tech)
    pdf.close()
    before = hashlib.sha256(tech.read_bytes()).hexdigest()
    spec = tmp_path / "spec.docx"
    document = Document()
    document.add_paragraph("规范：接触电阻 ≤5 mΩ")
    document.save(spec)
    received = []

    def classifier(path, *args, **kwargs):
        received.append(path)
        assert Path(path).suffix == ".docx"
        assert "Contact resistance" in " ".join(
            p.text for p in Document(path).paragraphs
        )
        raise RuntimeError("测试在语义分类入口停止，不调用外部模型")

    monkeypatch.setattr(
        requirement_classifier, "build_requirement_classification", classifier
    )
    result = run_pipeline(
        str(tech),
        str(spec),
        str(spec),
        str(tmp_path / "result.docx"),
        profile_path="explicit.yaml",
        category_mapping_path="explicit.yaml",
        cb=lambda message: None,
    )
    assert len(received) == 1
    normalization = result["meta"]["input_normalization"]
    assert normalization["tech"]["requires_review"] is True
    assert normalization["spec"]["requires_review"] is False
    assert result["meta"]["source_review_required"] is True
    assert Path(normalization["tech"]["evidence_path"]).is_file()
    assert hashlib.sha256(tech.read_bytes()).hexdigest() == before
    assert result["ok"] is False


def test_unreviewed_conversion_blocks_an_otherwise_passing_delivery(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        delivery_gate,
        "run_delivery_gate",
        lambda *args, **kwargs: {"passed": True, "deliverable": True,
                                "approved_for_delivery": True, "blocker_count": 0, "blockers": []},
    )
    output = tmp_path / "review.docx"
    result = {"meta": {"source_review_required": True}}
    gate = _run_delivery_gate_stage(str(output), result, {}, {}, {"passed": True})
    assert gate["passed"] is False and gate["deliverable"] is False
    assert any("逐页复核" in item for item in gate["blockers"])
    saved = json.loads(
        output.with_suffix(".delivery_gate.json").read_text(encoding="utf-8")
    )
    assert saved["passed"] is False
    assert saved["approved_for_delivery"] is False
    assert saved["blocker_count"] == len(saved["blockers"]) == 1
