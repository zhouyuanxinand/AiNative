import base64
from copy import deepcopy
from io import BytesIO
from pathlib import Path

from docx import Document

from jonhon_taskbook.coverage_ledger import (
    CoverageLedger,
    exclude_review_reference_sources,
    parse_docx_to_ledger,
)
from jonhon_taskbook.html_reporter import generate_report
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks
from jonhon_taskbook.indicator_facts import extract_indicator_facts


def case(tmp_path):
    source = tmp_path / "液冷组件规格书.docx"
    doc = Document()
    doc.add_heading("技术要求", 1)
    required = doc.add_table(rows=1, cols=2)
    required.cell(0, 0).text = "工作压力"
    required.cell(0, 1).text = "必须满足 200 kPa"
    doc.add_heading("测试设备及测试结果", 1)
    doc.add_heading("泄漏测试", 2)
    doc.add_paragraph("必须在 200 kPa 下保持 300 s。")
    result = doc.add_table(rows=2, cols=2)
    result.cell(0, 0).text = "样品编号"
    result.cell(0, 1).text = "实测压力/kPa"
    result.cell(1, 0).text = "YLZJ-01"
    result.cell(1, 1).text = "199.9"
    image = BytesIO(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5Wk3kAAAAASUVORK5CYII="))
    doc.add_picture(image)
    doc.save(source)
    blocks = extract_source_blocks(str(source), "tech")
    classification = {
        "source_blocks": blocks,
        "classifications": [{"source_id": b["id"], "category": "performance_indicator"} for b in blocks],
    }
    return source, classification


def test_review_only_results_leave_required_text_and_tables_in_coverage(tmp_path):
    source, classification = case(tmp_path)
    ledger = parse_docx_to_ledger(str(source))
    references = exclude_review_reference_sources(ledger, classification)
    assert len(references) == 2
    assert {b["block_type"] for b in references} == {"table", "image"}
    assert all(b["action"] == "review_reference_only" and not b["covered"] for b in references)
    assert all(b["semantic_source_ids"] and b["source_body_index"] >= 0 for b in references)
    assert "199.9" in next(b["raw_text"] for b in references if b["block_type"] == "table")
    assert next(b["artifact_hash"] for b in references if b["block_type"] == "image")
    assert len(ledger.blocks) == 2
    assert "必须满足" in ledger.blocks[0].raw_text
    assert "200 kPa" in ledger.blocks[1].raw_text
    assert not ledger.passed()
    assert ledger.covered_count == 0
    assert CoverageLedger.from_json(ledger.to_json()).review_only_sources == references
    assert "仅供审阅" in ledger.coverage_report_md()
    assert exclude_review_reference_sources(ledger, classification) == []


def test_source_coordinates_control_review_scope_independently_of_categories(tmp_path):
    source, classification = case(tmp_path)
    other = deepcopy(classification)
    for b in other["source_blocks"]:
        b["source_path"] = str(tmp_path / "other.docx")
    assert exclude_review_reference_sources(parse_docx_to_ledger(str(source)), other) == []
    for item in list(classification["classifications"]):
        classification["classifications"].append({**item, "category": "testability"})
    ledger = parse_docx_to_ledger(str(source))
    references = exclude_review_reference_sources(ledger, classification)
    assert len(references) == 2
    assert all("必须" in block.raw_text for block in ledger.blocks)


def test_quality_report_retains_every_reference_and_escapes_source_text(tmp_path):
    source, classification = case(tmp_path)
    ledger = parse_docx_to_ledger(str(source))
    references = exclude_review_reference_sources(ledger, classification)
    references[0]["summary"] = '<script>alert("test")</script>'
    output = tmp_path / "taskbook.docx"
    Document().save(output)
    ledger.save(output.with_suffix(".coverage_ledger.json"))
    report = Path(generate_report(str(output))).read_text(encoding="utf-8")
    assert "仅供审阅" in report
    assert "不计入正文覆盖率" in report
    assert source.name in report
    assert "199.9" in report
    assert '<script>alert("test")</script>' not in report
    for reference in references:
        assert reference["block_id"] in report
        assert reference["semantic_source_ids"][0] in report
        if reference["artifact_hash"]:
            assert reference["artifact_hash"] in report


def test_historical_measurements_cannot_become_design_indicator_values(tmp_path):
    source, _ = case(tmp_path)
    doc = Document(source)
    doc.tables[1].cell(0, 0).text = "项目"
    doc.tables[1].cell(0, 1).text = "参数"
    doc.tables[1].cell(1, 0).text = "工作压力"
    doc.tables[1].cell(1, 1).text = "199.9 kPa"
    doc.save(source)
    blocks = extract_source_blocks(str(source), "tech")
    classification = {
        "source_blocks": blocks,
        "classifications": [{"source_id": b["id"], "category": "performance_indicator"} for b in blocks],
    }
    facts = extract_indicator_facts(classification, {"机械性能": [{"name": "工作压力"}]}, source_document=doc)
    assert any("200 kPa" in f["source_value"] for f in facts)
    assert all("199.9" not in f["source_value"] for f in facts)
