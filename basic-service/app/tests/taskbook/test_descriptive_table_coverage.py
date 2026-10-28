"""Source table labels remain provable when controlled display names differ."""

import json

import pytest
from docx import Document

from jonhon_taskbook.coverage_ledger import (
    mark_covered_from_output, mark_structured_indicator_coverage, parse_docx_to_ledger,
)
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks


def _case(tmp_path, *, flow_label="组件流阻"):
    source = Document()
    source.add_heading("技术规格", 1)
    table = source.add_table(rows=4, cols=2)
    rows = [("技术特性类型", "特性描述"), ("环境温度", "5℃~42℃"),
            (flow_label, "15kPa±8%@0.8L/min@去离子水（包含快接头）"),
            ("产品重量", "包含支架＜650g")]
    for row, values in zip(table.rows, rows):
        for cell, value in zip(row.cells, values):
            cell.text = value
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    block = next(item for item in extract_source_blocks(str(source_path), "tech") if item["type"] == "table")
    output = Document()
    output.add_heading("技术指标", 1)
    target = output.add_table(rows=3, cols=2)
    target.cell(0, 0).text, target.cell(0, 1).text = "项目", "用户要求指标"
    facts, decisions = [], []
    for index, name in enumerate(("流阻", "重量"), start=2):
        label, value = rows[index]
        target.cell(index - 1, 0).text, target.cell(index - 1, 1).text = name, value
        facts.append({
            "fact_id": f"fact-{index}", "indicator_name": name, "source_label": label,
            "source_value": value, "source_ids": [block["id"]], "governed_name": True,
            "source_coordinates": {"body_index": block["body_index"], "table_row": index,
                                   "label_column": 0, "value_columns": [1]},
        })
        decisions.append({"indicator_name": name, "user_requirement": value,
                          "user_fact_ids": [f"fact-{index}"], "user_source_ids": [block["id"]]})
    output.add_heading("环境适应性要求", 1)
    output.add_paragraph("环境温度：5℃~42℃。")
    output_path = tmp_path / "output.docx"
    output.save(output_path)
    audit = {"input_indicator_facts": facts, "comparison_decisions": decisions}
    output_path.with_suffix(".requirement_classification.json").write_text(json.dumps({
        "source_blocks": [block],
    }, ensure_ascii=False), encoding="utf-8")
    return source_path, output_path, audit


def _check(source, output, audit):
    output.with_suffix(".indicator_audit.json").write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    ledger = parse_docx_to_ledger(str(source))
    mark_covered_from_output(ledger, str(output))
    mark_structured_indicator_coverage(ledger, str(output))
    return ledger


def test_descriptive_table_requires_complete_cells_despite_controlled_label_aliases(tmp_path):
    source, output, audit = _case(tmp_path)
    ledger = _check(source, output, audit)
    assert ledger.passed()
    evidence = ledger.blocks[0].output_fragment_evidence
    assert {item["fact_id"] for item in evidence if item.get("fact_id")} == {"fact-2", "fact-3"}
    assert ledger.blocks[0].action == "structured_table_cell_evidence"
    assert ledger.blocks[0].output_evidence_hash


def test_same_identity_keeps_existing_extractor_label_punctuation_handling(tmp_path):
    source, output, audit = _case(tmp_path, flow_label="流阻：")
    fact = audit["input_indicator_facts"][0]
    # The extractor strips surrounding punctuation from source_label, while
    # the ledger retains the source cell verbatim. Their identity is unchanged.
    fact["source_label"] = "流阻"
    fact["governed_name"] = False
    assert _check(source, output, audit).passed()


@pytest.mark.parametrize("mutation", [
    "wrong_source_label", "wrong_coordinate", "ungoverned_alias", "missing_fact",
    "missing_condition", "extra_source_column", "unpaired_descriptive_header",
])
def test_descriptive_table_does_not_credit_missing_or_unanchored_cells(tmp_path, mutation):
    source, output, audit = _case(tmp_path)
    fact = audit["input_indicator_facts"][0]
    if mutation == "wrong_source_label":
        fact["source_label"] = "盐雾"
    elif mutation == "wrong_coordinate":
        fact["source_coordinates"]["table_row"] = 3
    elif mutation == "ungoverned_alias":
        fact["governed_name"] = False
    elif mutation == "missing_fact":
        audit["input_indicator_facts"].pop()
    elif mutation == "missing_condition":
        document = Document(output)
        document.tables[0].cell(1, 1).text = "15kPa±8%@0.8L/min@去离子水"
        document.save(output)
    elif mutation == "extra_source_column":
        document = Document(source)
        from docx.shared import Inches
        document.tables[0].add_column(Inches(1))
        document.tables[0].cell(0, 2).text = "考核标准"
        document.tables[0].cell(2, 2).text = "按产品试验规程验证"
        document.save(source)
    elif mutation == "unpaired_descriptive_header":
        document = Document(source)
        document.tables[0].cell(0, 1).text = "特性描述及验收要求"
        document.save(source)
    ledger = _check(source, output, audit)
    assert not ledger.passed()
    assert not ledger.blocks[0].output_evidence_hash
