import json

import pytest
from docx import Document

from jonhon_taskbook.coverage_ledger import (
    CoverageLedger, InputBlock, mark_covered_from_output,
    mark_structured_indicator_coverage, mark_exact_fragment_coverage,
)
from jonhon_taskbook.semantic_integrity_gate import _evidence_in_target
from jonhon_taskbook.source_scope import normalize_source_display_text


@pytest.mark.parametrize("source,rendered", [
    ("7.1 外观检验：逐件检查镀层、螺纹、结构尺寸，无缺陷即为合格；", "外观检验：逐件检查镀层、螺纹、结构尺寸，无缺陷即为合格。"),
    ("7.5 验收依据：本技术协议、行业国家标准、出厂检测报告，三者一致即为验收通过。", "验收依据：本技术协议、行业国家标准、出厂检测报告，三者一致即为验收通过。"),
    ("8.1 产品质保期：自验收合格之日起24个月，非人为损坏免费更换。", "产品质保期：自验收合格之日起24个月，非人为损坏免费更换。"),
])
def test_numbered_inline_requirement_survives_controlled_rendering(tmp_path, source, rendered):
    output = tmp_path / "output.docx"
    doc = Document()
    doc.add_heading("条件保障要求", 1)
    doc.add_paragraph(rendered)
    doc.save(output)
    ledger = CoverageLedger("input.docx", [InputBlock("source", "paragraph", "", source, source)])
    mark_covered_from_output(ledger, str(output))
    assert ledger.covered_count == 1
    assert _evidence_in_target(source, rendered)[0]


@pytest.mark.parametrize("rendered", [
    "产品质保期：自验收合格之日起12个月，非人为损坏免费更换。",
    "产品质保期：自验收合格之日起24个月，免费更换。",
])
def test_display_number_removal_never_drops_conditions_or_values(rendered):
    source = "8.1 产品质保期：自验收合格之日起24个月，非人为损坏免费更换。"
    assert not _evidence_in_target(source, rendered)[0]


@pytest.mark.parametrize("value", ["0.5 N·m", "3.5 毫米", "24 个月", "1000 V AC 50Hz", "-40℃～+85℃"])
def test_technical_prefix_is_not_a_display_number(value):
    assert normalize_source_display_text(value) == value.replace(" ", "")


SOURCE = "（1）插拔寿命：常规插拔≥1000次，高频使用款≥2000次，插拔后电气性能无衰减、结构无松动；"


@pytest.mark.parametrize("change,expected", [
    ("presentation", True), ("template_footnote", True), ("threshold", False), ("condition", False),
    ("coordinate", False), ("wrong_row", False), ("unconsumed", False),
])
def test_generic_chapter_indicator_requires_complete_audited_source_row(tmp_path, change, expected):
    output = tmp_path / "output.docx"
    rendered = SOURCE.rstrip("；")
    if change == "threshold":
        rendered = rendered.replace("2000", "1000")
    if change == "condition":
        rendered = rendered.replace("插拔后电气性能无衰减、结构无松动", "插拔后结构无松动")
    doc = Document()
    doc.add_heading("技术指标", 1)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "指标"
    table.cell(0, 1).text = "用户要求"
    table.cell(1, 0).text = "盐雾" if change == "wrong_row" else "机械寿命"
    if change == "template_footnote":
        table.cell(1, 0).text = "机械寿命※"
    table.cell(1, 1).text = rendered
    doc.save(output)
    audit = {
        "passed": True,
        "input_indicator_names": ["机械寿命"], "output_indicator_names": ["机械寿命"],
        "input_indicator_facts": [{
            "fact_id": "life-fact", "indicator_name": "机械寿命", "source_value": SOURCE,
            "source_coordinates": {"body_index": 25 if change == "coordinate" else 24},
        }],
        "comparison_decisions": [{
            "indicator_name": "机械寿命", "user_requirement": SOURCE,
            "user_fact_ids": [] if change == "unconsumed" else ["life-fact"],
        }],
    }
    output.with_suffix(".indicator_audit.json").write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    block = InputBlock("life", "paragraph", "4.2 机械性能指标", SOURCE, SOURCE, source_body_index=24)
    ledger = CoverageLedger("source.docx", [block])
    mark_structured_indicator_coverage(ledger, str(output))
    assert block.covered is expected
    if expected:
        assert block.output_evidence_hash
        assert block.output_body_indices


def test_missing_emc_paragraph_cannot_be_proved_by_other_indicator_values(tmp_path):
    output = tmp_path / "output.docx"
    doc = Document()
    doc.add_heading("技术指标", 1)
    doc.add_paragraph("工作温度：-40℃～+85℃。")
    doc.save(output)
    source = "产品具备良好的电磁屏蔽性能，可有效抑制射频信号泄露，工作过程中无信号串扰、杂波干扰。"
    block = InputBlock("emc", "paragraph", "6.3 电磁兼容要求", source, source, source_body_index=50)
    ledger = CoverageLedger("source.docx", [block])
    mark_covered_from_output(ledger, str(output))
    mark_structured_indicator_coverage(ledger, str(output))
    assert not block.covered


@pytest.mark.parametrize("change,expected", [("complete", True), ("missing_clause", False), ("changed_percent", False), ("broken_spans", False)])
def test_indicator_typed_acceptance_paragraph_requires_all_exact_fragments(tmp_path, change, expected):
    output = tmp_path / "output.docx"
    fragments = ["7.4 可靠性检验：批次抽样开展环境、盐雾、振动测试，", "抽样合格率100%，", "批次验收合格。"]
    source = "".join(fragments)
    doc = Document()
    for i in (1, 2, 0):
        if change == "missing_clause" and i == 2:
            continue
        doc.add_heading(("环境适应性要求", "顾客特殊要求", "验收要求")[i], 1)
        doc.add_paragraph(fragments[i].replace("100%", "99%") if change == "changed_percent" else fragments[i])
    doc.save(output)
    blocks = []
    cursor = 0
    for i, text in enumerate(fragments):
        blocks.append({"id": f"fragment-{i}", "body_index": 55, "text": text,
                       "source_span_start": cursor, "source_span_end": cursor + len(text)})
        cursor += len(text)
    if change == "broken_spans":
        blocks[1]["source_span_start"] += 1
    audit = {"source_blocks": blocks, "fragment_partitions": [{
        "reconstructed_exactly": True, "fragment_source_ids": [block["id"] for block in blocks],
    }]}
    output.with_suffix(".requirement_classification.json").write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    source_block = InputBlock("acceptance", "indicator", "7.4 可靠性检验", source, source, source_body_index=55)
    ledger = CoverageLedger("source.docx", [source_block])
    mark_exact_fragment_coverage(ledger, str(output))
    assert source_block.covered is expected
    if expected:
        assert len(source_block.output_body_indices) == 3
        assert source_block.output_evidence_hash
