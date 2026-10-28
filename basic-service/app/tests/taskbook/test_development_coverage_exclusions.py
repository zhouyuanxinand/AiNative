import base64
from copy import deepcopy
from io import BytesIO

import yaml
from docx import Document
from jonhon_taskbook.coverage_ledger import (
    CoverageLedger,
    exclude_preserved_template_sources,
    parse_docx_to_ledger,
)
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks


def make_case(tmp_path):
    path = tmp_path / "requirements.docx"
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(yaml.safe_dump({"categories": {
        "schedule": {"write_mode": "preserve_template", "rule_ref": "开发逻辑!C26/D46"},
        "other": {},
    }}), encoding="utf-8")
    document = Document()
    document.add_heading("进度要求", 1)
    document.add_paragraph("样件必须按计划交付。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "里程碑"
    table.cell(0, 1).text = "时间"
    table.cell(1, 0).text = "样件交付"
    table.cell(1, 1).text = "2099年1月"
    image = BytesIO(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5Wk3kAAAAASUVORK5CYII="))
    table.cell(1, 0).paragraphs[0].add_run().add_picture(image)
    document.add_heading("其他要求", 1)
    document.add_paragraph("样件必须按计划交付。")
    document.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    classification = {
        "source_blocks": blocks,
        "classifications": [{"source_id": block["id"], "category": "schedule" if block["heading_text"] == "进度要求" else "other"} for block in blocks],
    }
    return path, mapping, classification


def test_rule_exclusion_tracks_source_position_and_keeps_raw_table_image_evidence(tmp_path):
    path, mapping, classification = make_case(tmp_path)
    ledger = parse_docx_to_ledger(str(path))
    assert all(block.source_body_index >= 0 for block in ledger.blocks)
    excluded = exclude_preserved_template_sources(ledger, classification, mapping)
    assert {block["block_type"] for block in excluded} == {"paragraph", "table", "image"}
    assert len(excluded) == 3
    image = next(block for block in excluded if block["block_type"] == "image")
    assert image["artifact_hash"]
    table = next(block for block in excluded if block["block_type"] == "table")
    assert "2099年1月" in table["raw_text"]
    assert table["source_body_index"] == image["source_body_index"]
    assert all(block["action"] == "excluded_by_business_rule" and not block["covered"] for block in excluded)
    # 相同文字的另一位置仍须真实搬运，不能借用进度排除规则。
    assert len(ledger.blocks) == 1
    assert ledger.blocks[0].raw_text == "样件必须按计划交付。"
    assert ledger.blocks[0].source_section == "其他要求"
    assert not ledger.passed()
    assert ledger.covered_count == 0
    assert "业务规则保留模板" in ledger.coverage_report_md()
    restored = CoverageLedger.from_json(ledger.to_json())
    assert restored.excluded_rule_sources == excluded
    assert exclude_preserved_template_sources(ledger, classification, mapping) == []


def test_same_body_index_from_another_source_cannot_exempt_current_source(tmp_path):
    path, mapping, classification = make_case(tmp_path)
    for block in classification["source_blocks"]:
        block["source_path"] = str(tmp_path / "other-input.docx")
    ledger = parse_docx_to_ledger(str(path))
    before = ledger.total
    assert exclude_preserved_template_sources(ledger, classification, mapping) == []
    assert ledger.total == before


def test_mixed_or_missing_assignment_cannot_exempt_a_whole_source_block(tmp_path):
    path, mapping, classification = make_case(tmp_path)
    first = classification["classifications"][0]
    classification["classifications"].append({**first, "category": "other"})
    ledger = parse_docx_to_ledger(str(path))
    excluded = exclude_preserved_template_sources(ledger, classification, mapping)
    assert all(block["block_type"] != "paragraph" for block in excluded)
    assert sum(block.raw_text == "样件必须按计划交付。" for block in ledger.blocks) == 2


def test_missing_position_and_partial_fragment_do_not_exclude_unverified_remainder(tmp_path):
    path, mapping, classification = make_case(tmp_path)
    partial = deepcopy(classification)
    source = partial["source_blocks"][0]
    source.update({"parent_source_id": "full-source", "source_span_start": 0, "source_span_end": 2, "text": "样件"})
    ledger = parse_docx_to_ledger(str(path))
    excluded = exclude_preserved_template_sources(ledger, partial, mapping)
    assert all(block["block_type"] != "paragraph" for block in excluded)
    for source in classification["source_blocks"]:
        source.pop("body_index", None)
    untouched = parse_docx_to_ledger(str(path))
    assert exclude_preserved_template_sources(untouched, classification, mapping) == []
