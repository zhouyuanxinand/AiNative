"""A formal source specification table must be accounted for by the fact ledger."""

import json

from docx import Document
from jonhon_taskbook.business_value_gate import audit_indicator_values


def _case(tmp_path, *, include_pressure=False, heading="技术规格"):
    source = tmp_path / "tech.docx"
    document = Document()
    document.add_heading(heading, 1)
    table = document.add_table(rows=0, cols=2)
    for left, right in (
        ("技术特性类型", "特性描述"),
        ("组件流阻", "15kPa±8%@0.8L/min"),
        ("工作压力", "0.3MPa"),
    ):
        cells = table.add_row().cells
        cells[0].text, cells[1].text = left, right
    document.save(source)

    output = tmp_path / "taskbook.docx"
    document = Document()
    table = document.add_table(rows=0, cols=4)
    rows = [
        ("项目", "用户要求指标", "拟采用指标", "依据"),
        ("流阻", "15kPa±8%@0.8L/min", "15kPa±8%@0.8L/min", "用户要求"),
    ]
    if include_pressure:
        rows.append(("工作压力", "0.3MPa", "0.3MPa", "用户要求"))
    for cells_text in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, cells_text):
            cell.text = value
    document.save(output)

    facts = [{
        "fact_id": "flow", "indicator_name": "流阻", "source_label": "组件流阻",
        "source_value": "15kPa±8%@0.8L/min", "source_ids": ["source-table"],
    }]
    decisions = [{
        "indicator_name": "流阻", "user_requirement": "15kPa±8%@0.8L/min",
        "adopted_requirement": "15kPa±8%@0.8L/min", "basis": "用户要求",
        "user_fact_ids": ["flow"],
    }]
    if include_pressure:
        facts.append({
            "fact_id": "pressure", "indicator_name": "工作压力",
            "source_label": "工作压力", "source_value": "0.3MPa",
            "source_ids": ["source-table"],
        })
        decisions.append({
            "indicator_name": "工作压力", "user_requirement": "0.3MPa",
            "adopted_requirement": "0.3MPa", "basis": "用户要求",
            "user_fact_ids": ["pressure"],
        })
    ledger = {"input_indicator_facts": facts, "comparison_decisions": decisions}
    output.with_suffix(".indicator_audit.json").write_text(
        json.dumps(ledger, ensure_ascii=False), encoding="utf-8"
    )
    classification = {
        "source_blocks": [{
            "id": "source-table", "source": "tech", "source_path": str(source),
            "type": "table", "body_index": 1, "heading_text": heading, "section": heading,
        }],
        "classifications": [{
            "source_id": "source-table", "category": "performance_indicator",
        }],
    }
    output.with_suffix(".effective_requirement_classification.json").write_text(
        json.dumps(classification, ensure_ascii=False), encoding="utf-8"
    )
    return output


def test_missing_formal_spec_row_blocks_even_if_fact_ledger_is_self_consistent(tmp_path):
    output = _case(tmp_path)
    audit = audit_indicator_values(output, persist=False)
    assert not audit["passed"]
    missing = [item for item in audit["blockers"] if item["code"] == "UNEXTRACTED_SOURCE_INDICATOR_ROW"]
    assert len(missing) == 1
    assert missing[0]["indicator"] == "工作压力"
    assert missing[0]["source_id"] == "source-table"
    assert missing[0]["table_row"] == 2


def test_complete_formal_spec_table_passes_source_row_check(tmp_path):
    output = _case(tmp_path, include_pressure=True)
    audit = audit_indicator_values(output, persist=False)
    assert audit["passed"], audit["blockers"]


def test_historical_result_table_is_not_treated_as_a_design_specification(tmp_path):
    output = _case(tmp_path, heading="技术规格历史测试结果")
    audit = audit_indicator_values(output, persist=False)
    assert audit["passed"], audit["blockers"]
