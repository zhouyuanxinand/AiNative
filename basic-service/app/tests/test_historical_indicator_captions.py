"""Empty historical result labels must not become design indicator values."""

from copy import deepcopy
from pathlib import Path

import pytest
from docx import Document
from jonhon_taskbook.coverage_ledger import (
    exclude_review_reference_sources,
    parse_docx_to_ledger,
)
from jonhon_taskbook.html_reporter import generate_report
from jonhon_taskbook.indicator_facts import extract_indicator_facts
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks
from jonhon_taskbook.source_scope import (
    is_unvalued_historical_result_caption,
    review_reference_source_ids,
)


@pytest.mark.parametrize(
    ("text", "context", "expected"),
    [
        ("不同流量下流阻结果：", "测试设备及测试结果 / 流阻", True),
        ("冷板重量（包含支架、小螺钉）测试数据：", "测试设备及测试结果 / 重量", True),
        ("流阻测试结果：", "技术规格 / 流阻", False),
        ("流阻要求：", "测试设备及测试结果 / 流阻", False),
        ("流阻测试结果：15kPa±8%@0.8L/min", "测试设备及测试结果 / 流阻", False),
        ("泄漏测试：介质氦气，压力5.5bar，泄漏值≤5×10-6Pa.m3/s", "测试设备及测试结果 / 泄漏测试", False),
        ("测试结果：不合格，压降超过2kPa", "测试设备及测试结果", False),
    ],
)
def test_empty_historical_result_caption_is_not_design_value(text, context, expected):
    assert is_unvalued_historical_result_caption(text, context) is expected


def test_historical_captions_do_not_replace_design_values_or_hide_limits(tmp_path):
    document = Document()
    document.add_heading("技术规格", level=1)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "指标"
    table.cell(1, 0).text = "流阻"
    table.cell(1, 1).text = "15kPa±8%@0.8L/min"
    document.add_heading("测试设备及测试结果", level=1)
    document.add_heading("流阻", level=2)
    document.add_paragraph("不同流量下流阻结果：")
    document.add_heading("重量", level=2)
    document.add_paragraph("冷板重量（包含支架、小螺钉）测试数据：")
    document.add_heading("泄漏测试", level=2)
    document.add_paragraph("泄漏测试：介质氦气，压力5.5bar，泄漏值≤5×10-6Pa.m3/s")
    source = tmp_path / "technical.docx"
    document.save(source)
    blocks = extract_source_blocks(str(source), "tech")
    classification = {
        "source_blocks": blocks,
        "classifications": [
            {"source_id": block["id"], "category": "performance_indicator"}
            for block in blocks
        ],
    }
    facts = extract_indicator_facts(
        classification,
        {"密封性能": [{"name": "流阻"}, {"name": "泄漏测试"}], "其他": [{"name": "重量"}]},
        source_document=document,
    )
    values = {fact["indicator_name"]: fact["source_value"] for fact in facts}
    assert values["流阻"] == "15kPa±8%@0.8L/min"
    assert "重量" not in values
    assert "5.5bar" in values["泄漏测试"]
    assert "≤5×10-6Pa.m3/s" in values["泄漏测试"]


def test_empty_result_caption_and_raw_table_are_review_references(tmp_path):
    document = Document()
    document.add_heading("测试设备及测试结果", level=1)
    document.add_heading("重量", level=2)
    caption = "冷板重量（包含支架、小螺钉）测试数据："
    document.add_paragraph(caption)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "序号"
    table.cell(0, 1).text = "重量/g"
    table.cell(1, 0).text = "1"
    table.cell(1, 1).text = "523.8"
    requirement = "重量验收要求：产品重量应≤650g。"
    document.add_paragraph(requirement)
    source = tmp_path / "technical.docx"
    document.save(source)
    blocks = extract_source_blocks(str(source), "tech")
    classification = {
        "source_blocks": blocks,
        "classifications": [
            {"source_id": block["id"], "category": "performance_indicator"}
            for block in blocks
        ],
    }
    caption_id = next(block["id"] for block in blocks if block["text"] == caption)
    assert caption_id in review_reference_source_ids(classification)
    ledger = parse_docx_to_ledger(str(source))
    references = exclude_review_reference_sources(ledger, classification)
    assert {reference["block_type"] for reference in references} == {"paragraph", "table"}
    assert any(reference["raw_text"] == caption for reference in references)
    assert [block.raw_text for block in ledger.blocks] == [requirement]
    output = tmp_path / "taskbook.docx"
    Document().save(output)
    ledger.save(output.with_suffix(".coverage_ledger.json"))
    html = Path(generate_report(str(output))).read_text(encoding="utf-8")
    assert caption in html
    assert caption_id in html

    mixed = deepcopy(classification)
    mixed["classifications"].append({"source_id": caption_id, "category": "technical_support"})
    assert caption_id in review_reference_source_ids(mixed)
    requirement_id = next(block["id"] for block in blocks if block["text"] == requirement)
    assert requirement_id not in review_reference_source_ids(mixed)
