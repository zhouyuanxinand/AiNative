from pathlib import Path
from zipfile import ZipFile
import copy
import hashlib
import json
import re

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PIL import Image

from jonhon_taskbook.auto_repair import propose_repairs, run_auto_repair
from jonhon_taskbook.semantic_orchestrator import extract_template_slots


def _case(tmp_path, *, missing_image=False, missing_destination=False, mixed=False, duplicate_number=28):
    source = Document()
    text = "冷板防尘盖采用透明片材，按产品包装方案装配。"
    source.add_paragraph(text)
    image = tmp_path / "source.png"
    Image.new("RGB", (8, 8), "#5588bb").save(image)
    source.add_picture(str(image))
    source.add_paragraph("图23 冷板防尘盖示意图")
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    blocks = [
        {"id": "packaging", "source": "tech", "type": "paragraph", "body_index": 0, "text": text},
        {"id": "image", "source": "tech", "type": "paragraph", "body_index": 1, "text": "[图片对象 body=1]",
         "has_drawing": True, "media_group_id": "g1"},
        {"id": "caption", "source": "tech", "type": "paragraph", "body_index": 2, "text": "图23 冷板防尘盖示意图",
         "media_group_id": "g1"},
    ]
    for block in blocks:
        block["source_path"] = str(source_path)
    output = Document()
    output.add_heading("条件保障要求", 1)
    if not missing_destination:
        output.add_paragraph(text)
    if not missing_image:
        output.add_picture(str(image))
    output.add_paragraph("图1 冷板防尘盖示意图")
    output.add_heading("环境适应性要求", 1)
    output.add_paragraph(text + ("运输温度为-40℃～85℃。" if mixed else ""))
    duplicate_caption = f"图{duplicate_number} 冷板防尘盖示意图"
    output.add_paragraph(duplicate_caption)
    out_path = tmp_path / "taskbook.docx"
    output.save(out_path)
    slots = extract_template_slots(str(out_path))
    correct = next(slot["id"] for slot in slots if "条件保障" in slot["heading"])
    wrong = next(slot["id"] for slot in slots if "环境适应性" in slot["heading"])
    plan = {"slots": slots, "source_blocks": blocks, "decisions": [
        {"operation": "copy_exact", "source_ids": [block["id"] for block in blocks],
         "target_slot": correct, "confidence": 0.99},
    ]}
    classification = {"source_blocks": blocks, "classifications": [
        {"source_id": block["id"], "category": "technical_support"} for block in blocks
    ]}

    def evaluate(path):
        doc = Document(path)
        paragraphs = [paragraph.text for paragraph in doc.paragraphs]
        violations = []
        for source_id, bad in (("packaging", text), ("caption", duplicate_caption)):
            limit = 1 if source_id == "packaging" else 0
            if paragraphs.count(bad) > limit:
                violations.append({"code": "ENVIRONMENTAL_UNEXPECTED_CONTENT", "source_ids": [source_id],
                                   "target_slot": wrong})
        return {
            "qa_ok": not violations, "delivery_gate_ok": False,
            "semantic_integrity": {"violations": violations},
            "covered_source_ids": ["packaging", "image", "caption"],
            "blocking_keys": ["SOURCE_REVIEW_REQUIRED"] + [v["source_ids"][0] for v in violations],
            "result": {"meta": {"input_review_required": True}},
        }
    return out_path, source_path, plan, classification, evaluate


def test_verified_duplicate_and_orphan_caption_repaired_without_removing_original_group(tmp_path):
    path, source, plan, classification, evaluate = _case(tmp_path)
    source_bytes = source.read_bytes()
    with ZipFile(path) as z:
        media = {name: z.read(name) for name in z.namelist() if name.startswith("word/media/")}
    assert len(evaluate(path)["semantic_integrity"]["violations"]) == 2

    report = run_auto_repair(path, plan, classification, evaluate=evaluate, cb=lambda _: None)

    assert report["accepted_rounds"] == 1
    assert report["snapshot"]["qa_ok"]
    assert not report["snapshot"]["delivery_gate_ok"]
    assert report["snapshot"]["blocking_keys"] == ["SOURCE_REVIEW_REQUIRED"]
    assert report["snapshot"]["result"]["meta"]["input_review_required"] is True
    assert source.read_bytes() == source_bytes
    assert Path(report["rounds"][0]["before"]).is_file()
    assert Path(report["audit_path"]).is_file()
    paragraphs = [paragraph.text for paragraph in Document(path).paragraphs]
    assert paragraphs.count(plan["source_blocks"][0]["text"]) == 1
    assert "图1 冷板防尘盖示意图" in paragraphs
    with ZipFile(path) as z:
        assert media == {name: z.read(name) for name in z.namelist() if name.startswith("word/media/")}


def test_caption_is_not_removed_when_correct_destination_has_no_image(tmp_path):
    path, _, plan, classification, evaluate = _case(tmp_path, missing_image=True)
    actions = propose_repairs(path, plan, classification, evaluate(path)["semantic_integrity"])
    assert not any(action.get("source_id") == "caption" for action in actions)


def test_removing_duplicate_caption_keeps_remaining_numbering_continuous(tmp_path):
    path, _, plan, classification, evaluate = _case(tmp_path, duplicate_number=2)
    document = Document(path)
    document.add_heading("后续要求", 1)
    document.add_picture(str(tmp_path / "source.png"))
    document.add_paragraph("图3 后续安装示意图")
    document.save(path)

    def check(candidate):
        snapshot = evaluate(candidate)
        numbers = [int(match.group(1)) for p in Document(candidate).paragraphs
                   if (match := re.match(r"^图(\d+)", p.text))]
        if numbers != list(range(1, len(numbers) + 1)):
            snapshot["blocking_keys"].append("FIGURE_NUMBER_SEQUENCE")
        return snapshot

    audit = run_auto_repair(path, plan, classification, evaluate=check, cb=lambda _: None)

    assert audit["accepted_rounds"] == 1
    assert audit["snapshot"]["blocking_keys"] == ["SOURCE_REVIEW_REQUIRED"]
    assert "图2 后续安装示意图" in [p.text for p in Document(path).paragraphs]


def test_caption_without_source_group_cannot_be_auto_deleted(tmp_path):
    path, _, plan, classification, evaluate = _case(tmp_path, missing_image=True)
    for block in plan["source_blocks"]:
        block.pop("media_group_id", None)
    actions = propose_repairs(path, plan, classification, evaluate(path)["semantic_integrity"])
    assert not any(action.get("source_id") == "caption" for action in actions)


def test_approved_executor_confidence_is_used_without_accepting_low_confidence(tmp_path):
    path, _, plan, classification, evaluate = _case(tmp_path)
    plan["decisions"][0]["confidence"] = 0.74
    actions = propose_repairs(path, plan, classification, evaluate(path)["semantic_integrity"])
    assert {a.get("source_id") for a in actions} >= {"packaging", "caption"}
    plan["decisions"][0]["confidence"] = 0.59
    actions = propose_repairs(path, plan, classification, evaluate(path)["semantic_integrity"])
    assert not any(action.get("source_id") for action in actions)


def test_only_copy_is_not_removed_and_mixed_requirements_are_not_erased(tmp_path):
    path, _, plan, classification, evaluate = _case(tmp_path, missing_destination=True, mixed=True)
    finding = {"violations": [{"code": "ENVIRONMENTAL_UNEXPECTED_CONTENT", "source_ids": ["packaging"],
                               "target_slot": plan["slots"][-1]["id"]}]}
    actions = propose_repairs(path, plan, classification, finding)
    assert not any(action.get("source_id") == "packaging" for action in actions)


def test_new_blocker_rejects_candidate_and_preserves_download(tmp_path):
    path, _, plan, classification, evaluate = _case(tmp_path)
    original = path.read_bytes()
    def regressing(candidate):
        snapshot = evaluate(candidate)
        if Path(candidate) != path:
            snapshot["blocking_keys"].append("NEW_MISSING_VALUE")
        return snapshot
    report = run_auto_repair(path, plan, classification, evaluate=regressing, cb=lambda _: None)
    assert path.read_bytes() == original
    assert report["accepted_rounds"] == 0
    assert report["stop_reason"] == "new_blocker"
    assert len(report["rounds"]) == 1


def test_coverage_regression_rejects_candidate(tmp_path):
    path, _, plan, classification, evaluate = _case(tmp_path)
    original = path.read_bytes()
    def losing_evidence(candidate):
        snapshot = evaluate(candidate)
        if Path(candidate) != path:
            snapshot["covered_source_ids"].remove("image")
        return snapshot
    report = run_auto_repair(path, plan, classification, evaluate=losing_evidence, cb=lambda _: None)
    assert path.read_bytes() == original
    assert report["stop_reason"] == "source_coverage_regressed"


def test_publishing_check_failure_restores_previous_document(tmp_path):
    path, _, plan, classification, evaluate = _case(tmp_path)
    original = path.read_bytes()
    public_checks = 0
    def fails_after_publish(candidate):
        nonlocal public_checks
        if Path(candidate) != path:
            Path(candidate).with_suffix(".candidate-only.json").write_text('{"passed": true}')
        if Path(candidate) == path:
            public_checks += 1
            if public_checks == 2:
                raise RuntimeError("verification failed after copying candidate")
        return evaluate(candidate)
    report = run_auto_repair(path, plan, classification, evaluate=fails_after_publish, cb=lambda _: None)
    assert path.read_bytes() == original
    assert report["accepted_rounds"] == 0
    assert report["stop_reason"] == "repair_failed"
    assert not path.with_suffix(".candidate-only.json").exists()


def test_persistent_rollback_verification_failure_preserves_before_and_persists_blocked_audit(tmp_path):
    path, _, plan, classification, evaluate = _case(tmp_path)
    original = path.read_bytes()
    previous_report = path.with_suffix(".existing-report.json")
    previous_report.write_text('{"original": true}', encoding="utf-8")
    original_report = previous_report.read_bytes()
    initial_snapshot = evaluate(path)
    expected_snapshot = copy.deepcopy(initial_snapshot)
    public_checks = 0

    def failing_checks(candidate):
        nonlocal public_checks
        if Path(candidate) != path:
            Path(candidate).with_suffix(".candidate-only.json").write_text('{"passed": true}')
            return evaluate(candidate)
        public_checks += 1
        if public_checks == 1:
            return initial_snapshot
        previous_report.write_text('{"partial": true}', encoding="utf-8")
        path.with_suffix(".partial-check.json").write_text('{"complete": false}')
        raise RuntimeError("verification service unavailable")

    report = run_auto_repair(path, plan, classification, evaluate=failing_checks, cb=lambda _: None)

    assert path.read_bytes() == original
    assert previous_report.read_bytes() == original_report
    assert not path.with_suffix(".candidate-only.json").exists()
    assert not path.with_suffix(".partial-check.json").exists()
    assert initial_snapshot == expected_snapshot
    assert report["accepted_rounds"] == 0
    assert report["stop_reason"] == "rollback_verification_failed"
    assert report["output_sha256"] == hashlib.sha256(original).hexdigest()
    snapshot = report["snapshot"]
    assert snapshot["qa_ok"] is False and snapshot["delivery_gate_ok"] is False
    assert snapshot["covered_source_ids"] == expected_snapshot["covered_source_ids"]
    assert snapshot["semantic_integrity"] == expected_snapshot["semantic_integrity"]
    assert set(expected_snapshot["blocking_keys"]).issubset(snapshot["blocking_keys"])
    assert "auto_repair:ROLLBACK_VERIFICATION_FAILED" in snapshot["blocking_keys"]
    assert snapshot["result"]["meta"]["input_review_required"] is True
    round_directory = Path(report["rounds"][0]["before"]).parent.parent
    assert json.loads((round_directory / "before.json").read_text(encoding="utf-8")) == expected_snapshot
    decision = json.loads((round_directory / "decision.json").read_text(encoding="utf-8"))
    assert decision["accepted"] is False and decision["rollback_restored"] is True
    assert "verification service unavailable" in decision["rollback_error"]
    assert json.loads(Path(report["audit_path"]).read_text(encoding="utf-8"))["stop_reason"] == "rollback_verification_failed"


def test_format_repair_is_bounded_and_does_not_clear_manual_review(tmp_path):
    path = tmp_path / "bad-format.docx"
    doc = Document()
    properties = doc.add_paragraph("保持原技术值 1 MPa").runs[0]._r.get_or_add_rPr()
    for tag, value in (("lang", "zh-CN"), ("sz", "21"), ("w", "0")):
        element = OxmlElement("w:" + tag)
        element.set(qn("w:val"), value)
        properties.append(element)
    doc.save(path)
    calls = []
    def evaluate(candidate):
        calls.append(str(candidate))
        return {"qa_ok": True, "delivery_gate_ok": False, "blocking_keys": ["SOURCE_REVIEW_REQUIRED"],
                "covered_source_ids": ["p1"], "semantic_integrity": {"violations": []}}
    report = run_auto_repair(path, None, None, evaluate=evaluate, max_rounds=99, cb=lambda _: None)
    assert report["max_rounds"] == 2
    assert report["accepted_rounds"] == 1
    assert len(calls) == 3
    assert report["snapshot"]["blocking_keys"] == ["SOURCE_REVIEW_REQUIRED"]
    assert Document(path).paragraphs[0].text == "保持原技术值 1 MPa"
