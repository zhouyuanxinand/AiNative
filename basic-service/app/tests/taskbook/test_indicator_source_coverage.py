"""Source preservation and adoption approval are independent workbook rules."""
from tests.support.paths import FIXTURE_ROOT
import json
import copy
from pathlib import Path

import pytest

from docx import Document

from jonhon_taskbook.coverage_ledger import (
    CoverageLedger, InputBlock, mark_structured_indicator_coverage, mark_covered_from_output,
)


SOURCE = "（1）特性阻抗：50Ω±1Ω，通带内阻抗均匀无突变；"


def indicator_fixture(tmp_path, *, passed=False):
    output = tmp_path / "output.docx"
    doc = Document()
    doc.add_heading("技术指标", 1)
    table = doc.add_table(rows=2, cols=4)
    for cell, text in zip(table.rows[0].cells, ("项目", "用户要求指标", "拟采用指标", "依据")):
        cell.text = text
    for cell, text in zip(table.rows[1].cells, ("特性阻抗", SOURCE, "【人工填写】", "需设计确认")):
        cell.text = text
    doc.save(output)
    audit = {
        "passed": passed,
        "input_indicator_names": ["特性阻抗"],
        "output_indicator_names": ["特性阻抗"],
        "input_indicator_facts": [{
            "fact_id": "impedance-1", "indicator_name": "特性阻抗", "source_value": SOURCE,
            "source_coordinates": {"body_index": 31, "start": 0, "end": len(SOURCE)},
            "source_ids": ["tech-impedance"],
        }],
        "comparison_decisions": [{
            "indicator_name": "特性阻抗", "user_requirement": SOURCE,
            "user_fact_ids": ["impedance-1"], "user_source_ids": ["tech-impedance"],
            "manual_review_required": True, "adopted_requirement": "【人工填写】",
        }],
    }
    output.with_suffix(".indicator_audit.json").write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    output.with_suffix(".requirement_classification.json").write_text(json.dumps({"source_blocks": [{
        "id": "tech-impedance", "body_index": 31, "text": SOURCE,
    }]}, ensure_ascii=False), encoding="utf-8")
    block = InputBlock("TR-IND-005", "indicator", "电气性能", SOURCE, SOURCE, source_body_index=31)
    return output, audit, CoverageLedger("input.docx", [block])


def test_original_indicator_is_covered_while_adoption_needs_confirmation(tmp_path):
    output, audit, ledger = indicator_fixture(tmp_path)
    mark_structured_indicator_coverage(ledger, str(output))
    assert ledger.passed(), "The complete original requirement is present in its identified user row."
    assert ledger.blocks[0].output_evidence_hash
    saved = json.loads(output.with_suffix(".indicator_audit.json").read_text(encoding="utf-8"))
    assert saved == audit
    assert saved["passed"] is False
    assert saved["comparison_decisions"][0]["manual_review_required"] is True


def test_user_requirement_basis_is_data_not_a_new_column_header(tmp_path):
    output, _, ledger = indicator_fixture(tmp_path)
    doc = Document(output)
    doc.tables[0].cell(1, 3).text = "用户要求"
    doc.save(output)
    mark_structured_indicator_coverage(ledger, str(output))
    assert ledger.passed()


@pytest.mark.parametrize("change", [
    "threshold", "condition", "wrong_identity", "only_adopted_column", "duplicate_output_row",
    "wrong_coordinate", "wrong_source_span", "missing_source_anchor", "wrong_source_anchor",
    "wrong_decision_identity", "missing_consumption", "duplicate_consumption", "duplicate_fact",
])
@pytest.mark.parametrize("passed", [False, True])
def test_each_fact_requires_original_source_identity_and_unique_output_evidence(tmp_path, change, passed):
    output, audit, ledger = indicator_fixture(tmp_path, passed=passed)
    doc = Document(output)
    table = doc.tables[0]
    fact = audit["input_indicator_facts"][0]
    decision = audit["comparison_decisions"][0]
    if change == "threshold":
        table.cell(1, 1).text = SOURCE.replace("50", "75")
    elif change == "condition":
        table.cell(1, 1).text = SOURCE.replace("，通带内阻抗均匀无突变", "")
    elif change == "wrong_identity":
        table.cell(1, 0).text = "盐雾"
    elif change == "only_adopted_column":
        table.cell(1, 1).text = ""
        table.cell(1, 2).text = SOURCE
    elif change == "duplicate_output_row":
        table._tbl.append(copy.deepcopy(table.rows[1]._tr))
    elif change == "wrong_coordinate":
        fact["source_coordinates"]["body_index"] += 1
    elif change == "wrong_source_span":
        fact["source_coordinates"]["end"] -= 2
    elif change == "missing_source_anchor":
        output.with_suffix(".requirement_classification.json").unlink()
    elif change == "wrong_source_anchor":
        fact["source_ids"] = ["another-source"]
        decision["user_source_ids"] = ["another-source"]
    elif change == "wrong_decision_identity":
        decision["indicator_name"] = "盐雾"
    elif change == "missing_consumption":
        decision["user_fact_ids"] = []
    elif change == "duplicate_consumption":
        audit["comparison_decisions"].append(copy.deepcopy(decision))
    elif change == "duplicate_fact":
        audit["input_indicator_facts"].append(copy.deepcopy(fact))
    doc.save(output)
    output.with_suffix(".indicator_audit.json").write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    mark_structured_indicator_coverage(ledger, str(output))
    assert not ledger.passed()
    assert not ledger.blocks[0].output_evidence_hash


def test_numeric_tokens_in_other_rows_do_not_prove_original_conditions(tmp_path):
    output = tmp_path / "output.docx"
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "用户要求指标"
    table.cell(1, 0).text = "轴向力"
    table.cell(1, 1).text = "常态≤2N；盐雾后≤5N"
    doc.save(output)
    original = "插拔力：常态≤2N，盐雾后≤5N，无腐蚀。"
    ledger = CoverageLedger("source.docx", [InputBlock(
        "force-1", "indicator", "机械性能", original, original, source_body_index=12,
    )])
    mark_covered_from_output(ledger, str(output))
    mark_structured_indicator_coverage(ledger, str(output))
    assert not ledger.passed()


def test_seven_real_filter_source_passages_are_covered_without_adoption_approval(tmp_path):
    fixture = json.loads((FIXTURE_ROOT / "filter_indicator_coverage_193016.json").read_text(encoding="utf-8"))
    output = tmp_path / "filter.docx"
    doc = Document()
    doc.add_heading("技术指标", 1)
    table = doc.add_table(rows=0, cols=4)
    for row in fixture["output_rows"]:
        for cell, text in zip(table.add_row().cells, row):
            cell.text = text
    doc.save(output)
    output.with_suffix(".indicator_audit.json").write_text(json.dumps(fixture["audit"], ensure_ascii=False), encoding="utf-8")
    output.with_suffix(".requirement_classification.json").write_text(json.dumps({"source_blocks": fixture["source_blocks"]}, ensure_ascii=False), encoding="utf-8")
    ledger = CoverageLedger("filter.docx", [InputBlock(**block) for block in fixture["ledger_blocks"]])
    assert ledger.covered_count == 0
    mark_covered_from_output(ledger, str(output))
    mark_structured_indicator_coverage(ledger, str(output))
    assert {block.block_id for block in ledger.blocks if block.covered} == {
        "TR-IND-003", "TR-IND-005", "TR-PARA-017", "TR-IND-006",
        "TR-PARA-019", "TR-PARA-020", "TR-PARA-021",
    }
    assert ledger.passed()
    assert fixture["audit"]["passed"] is False


@pytest.mark.parametrize("change,covered", [("complete", True), ("missing_fact", False), ("missing_condition", False), ("reused_fact", False)])
def test_a_split_paragraph_requires_every_original_clause_in_its_own_indicator_row(tmp_path, change, covered):
    output, audit, ledger = indicator_fixture(tmp_path)
    first = "工作温度：-40℃～+85℃；"
    second = "存储温度：-55℃～+100℃，无凝露。"
    original = first + second
    block = ledger.blocks[0]
    block.raw_text = block.summary = original
    audit["input_indicator_facts"] = []
    audit["comparison_decisions"] = []
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "用户要求指标"
    cursor = 0
    for i, (name, text) in enumerate((("工作温度", first), ("存储温度", second))):
        if change == "missing_fact" and i == 1:
            continue
        row = table.add_row()
        row.cells[0].text = name
        row.cells[1].text = text.replace("，无凝露", "") if change == "missing_condition" else text
        fact_id = f"temperature-{i}"
        audit["input_indicator_facts"].append({
            "fact_id": fact_id, "indicator_name": name, "source_value": text,
            "source_coordinates": {"body_index": 31, "start": cursor, "end": cursor + len(text)},
        })
        audit["comparison_decisions"].append({"indicator_name": name, "user_requirement": text, "user_fact_ids": [fact_id]})
        cursor += len(text)
    if change == "reused_fact":
        audit["comparison_decisions"][1]["user_fact_ids"] = ["temperature-0"]
    doc.save(output)
    output.with_suffix(".indicator_audit.json").write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    mark_structured_indicator_coverage(ledger, str(output))
    assert ledger.passed() is covered


def test_one_user_cell_occurrence_cannot_cover_two_distinct_original_facts(tmp_path):
    output, audit, ledger = indicator_fixture(tmp_path)
    second = copy.deepcopy(audit["input_indicator_facts"][0])
    second["fact_id"] = "impedance-2"
    second["source_coordinates"]["body_index"] = 32
    second["source_ids"] = []
    audit["input_indicator_facts"].append(second)
    audit["comparison_decisions"][0]["user_fact_ids"].append("impedance-2")
    ledger.blocks.append(InputBlock("TR-IND-006", "indicator", "电气性能", SOURCE, SOURCE, source_body_index=32))
    output.with_suffix(".indicator_audit.json").write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    mark_structured_indicator_coverage(ledger, str(output))
    assert ledger.covered_count == 1
    assert not ledger.passed()


@pytest.mark.parametrize("section,expected", [("2 执行标准", True), ("试验方法", False), ("标准试验方法", False)])
def test_reference_label_is_removed_only_in_an_explicit_reference_section(tmp_path, section, expected):
    output = tmp_path / "output.docx"
    reference = "GB/T 5095.2307-2021《电子设备用机电元件 基本试验规程及测量方法 第23-7部分：屏蔽和滤波试验》"
    original = "滤波相关：" + reference
    doc = Document()
    doc.add_paragraph(reference)
    doc.save(output)
    ledger = CoverageLedger("source.docx", [InputBlock("standard-1", "paragraph", section, original, original)])
    mark_covered_from_output(ledger, str(output))
    assert ledger.passed() is expected
