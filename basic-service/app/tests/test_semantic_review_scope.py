"""Review-only observations do not become missing taskbook requirements."""
import pytest
import yaml
from docx import Document

from jonhon_taskbook.semantic_integrity_gate import run_semantic_integrity_gate
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks, extract_template_slots
from jonhon_taskbook.source_scope import review_reference_source_ids


@pytest.mark.parametrize("stale_decision", [True, False])
def test_review_only_sources_are_not_checked_or_required_in_body(tmp_path, stale_decision):
    source = Document()
    source.add_heading("测试设备及测试结果", 1)
    source.add_paragraph("第1批压力测试结果：")
    source.add_paragraph("测试内容：58psi氮气，保压30min，泄漏值＜3%。")
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    blocks = extract_source_blocks(str(source_path), "tech")
    classification = {"source_blocks": blocks, "classifications": [
        {"source_id": block["id"], "category": "testability"} for block in blocks
    ]}
    review_ids = review_reference_source_ids(classification)
    assert review_ids == {blocks[0]["id"]}
    output = Document()
    output.add_heading("测试性要求", 1)
    output.add_paragraph(blocks[1]["text"])
    path = tmp_path / "output.docx"
    output.save(path)
    slots = extract_template_slots(str(path))
    plan = {"slots": slots, "source_blocks": blocks, "decisions": [{
        "operation": "copy_exact", "target_slot": slots[0]["id"],
        "source_ids": [block["id"] for block in blocks if stale_decision or block["id"] not in review_ids],
    }]}
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(yaml.safe_dump({"categories": {"testability": {
        "target_heading_keywords": ["测试性"], "target_integrity": "exact",
    }}}, allow_unicode=True), encoding="utf-8")

    report = run_semantic_integrity_gate(path, plan, classification, mapping, require_complete_source_checks=True)

    assert report["passed"], report["violations"]
    assert {item["source_id"] for item in report["checked"]} == {blocks[1]["id"]}
    assert report["expected_source_ids"] == [blocks[1]["id"]]
