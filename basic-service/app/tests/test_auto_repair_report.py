import json
import copy
from pathlib import Path

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from jonhon_taskbook.auto_repair import run_auto_repair
from jonhon_taskbook.html_reporter import generate_report


def test_report_shows_repair_result_and_escapes_source_text(tmp_path):
    path = tmp_path / "taskbook.docx"
    doc = Document()
    doc.add_paragraph("环境温度：5℃～42℃")
    doc.save(path)
    path.with_suffix(".auto_repair.json").write_text(json.dumps({
        "accepted_rounds": 1, "stop_reason": "no_verified_repair",
        "rounds": [{"round": 1, "accepted": True, "reason": "verified_improvement",
                    "actions": [{"code": "REMOVE_VERIFIED_ENVIRONMENTAL_DUPLICATE",
                                 "source_id": "tech-p-example", "text": "<script>alert(1)</script>"}]}],
    }), encoding="utf-8")
    report = Path(generate_report(str(path))).read_text(encoding="utf-8")
    assert "自动修复记录" in report
    assert "tech-p-example" in report
    assert "&lt;script&gt;" in report
    assert "<script>alert(1)</script>" not in report
    assert "修复后仍以全部交付门禁结果为准" in report


@pytest.mark.parametrize("failure", ["rollback_verification", "candidate_rejected"])
def test_report_uses_retained_output_state_after_a_repair_failure(tmp_path, failure):
    path = tmp_path / "taskbook.docx"
    document = Document()
    run = document.add_paragraph("环境温度：5℃～42℃").runs[0]
    scale = OxmlElement("w:w")
    scale.set(qn("w:val"), "0")
    run._r.get_or_add_rPr().append(scale)
    document.save(path)
    original = path.read_bytes()
    path.with_suffix(".qa_gate_report.md").write_text("# QA\n✅ 通过\n", encoding="utf-8")
    old_delivery = {"passed": True, "deliverable": True, "blockers": [], "warnings": []}
    delivery_path = path.with_suffix(".delivery_gate.json")
    delivery_path.write_text(json.dumps(old_delivery), encoding="utf-8")
    delivery_bytes = delivery_path.read_bytes()
    original_snapshot = {
        "qa_ok": True, "delivery_gate_ok": True, "blocking_keys": [],
        "covered_source_ids": ["temperature"], "semantic_integrity": {"passed": True, "violations": []},
        "delivery_gate": copy.deepcopy(old_delivery),
        "result": {"meta": {"delivery_gate_result": copy.deepcopy(old_delivery)}},
    }
    public_checks = 0

    def evaluate(candidate):
        nonlocal public_checks
        if Path(candidate) == path:
            public_checks += 1
            if failure == "rollback_verification" and public_checks > 1:
                raise RuntimeError("verification unavailable")
        result = copy.deepcopy(original_snapshot)
        if failure == "candidate_rejected" and Path(candidate) != path:
            result.update(qa_ok=False, blocking_keys=["CANDIDATE_NEW_BLOCKER"])
        return result

    audit = run_auto_repair(path, None, None, evaluate=evaluate, cb=lambda _: None)
    report = Path(generate_report(str(path))).read_text(encoding="utf-8")

    assert path.read_bytes() == original
    assert delivery_path.read_bytes() == delivery_bytes
    assert original_snapshot["result"]["meta"]["delivery_gate_result"]["passed"] is True
    before = Path(audit["rounds"][0]["before"]).parent.parent / "before.json"
    assert json.loads(before.read_text(encoding="utf-8")) == original_snapshot
    current_delivery = audit["snapshot"]["result"]["meta"]["delivery_gate_result"]
    if failure == "rollback_verification":
        assert current_delivery["passed"] is False and current_delivery["deliverable"] is False
        assert audit["snapshot"]["delivery_gate"]["passed"] is False
        assert audit["snapshot"]["delivery_gate"]["deliverable"] is False
        assert any("ROLLBACK_VERIFICATION_FAILED" in str(issue) for issue in current_delivery["blockers"])
        assert "全部门禁通过" not in report
        assert "ROLLBACK_VERIFICATION_FAILED" in report
    else:
        assert audit["stop_reason"] == "new_blocker"
        assert audit["snapshot"]["qa_ok"] is True and audit["snapshot"]["delivery_gate_ok"] is True
        assert current_delivery == old_delivery
        assert "全部门禁通过" in report
        assert "ROLLBACK_VERIFICATION_FAILED" not in report


def test_manual_input_review_is_not_repeated_as_an_auto_repair_failure(tmp_path):
    path = tmp_path / "taskbook.docx"
    Document().save(path)
    path.with_suffix(".qa_gate_report.md").write_text("# QA\n✅ 通过\n", encoding="utf-8")
    message = "输入文档经过格式转换或 OCR，识别内容尚需逐页复核；请下载原件与识别证据，核对或修正后上传 DOCX 重新生成"
    path.with_suffix(".delivery_gate.json").write_text(json.dumps({
        "passed": False, "deliverable": False, "blockers": [message], "warnings": [],
    }, ensure_ascii=False), encoding="utf-8")
    path.with_suffix(".auto_repair.json").write_text(json.dumps({
        "accepted_rounds": 0, "rounds": [], "stop_reason": "no_verified_repair",
        "snapshot": {"qa_ok": True, "delivery_gate_ok": False, "blocking_keys": ["delivery:" + message]},
    }, ensure_ascii=False), encoding="utf-8")

    report = Path(generate_report(str(path))).read_text(encoding="utf-8")

    assert report.count(message) == 1
    assert "自动修复后检查" not in report
    assert "delivery:" not in report
    assert "全部门禁通过" not in report
