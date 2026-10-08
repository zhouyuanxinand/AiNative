"""Mixed source tables require evidence for every original requirement cell."""
import json

import pytest
from docx import Document

from jonhon_taskbook.coverage_ledger import (
    mark_covered_from_output, mark_structured_indicator_coverage, parse_docx_to_ledger,
)
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks


@pytest.fixture
def mixed_table_case(tmp_path):
    source = Document()
    source.add_heading("机械与环境性能要求", 1)
    table = source.add_table(rows=5, cols=2)
    values = [("项目", "指标"), ("冲击", "加速度980m/s 2，持续11ms"),
              ("振动", "10Hz～2000Hz，加速度147m/s 2"),
              ("工作温度", "-55℃～125℃"), ("机械寿命", "500次")]
    for row, texts in zip(table.rows, values):
        for cell, text in zip(row.cells, texts):
            cell.text = text
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    source_block = extract_source_blocks(str(source_path), "tech")[0]
    output = Document()
    output.add_heading("技术指标", 1)
    target_table = output.add_table(rows=2, cols=3)
    for cell, text in zip(target_table.rows[0].cells, ["项目", "用户要求指标", "拟采用指标"]):
        cell.text = text
    for cell, text in zip(target_table.rows[1].cells, ["机械寿命", "500次", "1000次"]):
        cell.text = text
    output.add_heading("环境适应性要求", 1)
    for name, value in values[1:4]:
        output.add_paragraph(name + "：" + value + "。")
    path = tmp_path / "output.docx"
    output.save(path)
    audit = {"input_indicator_facts": [{
        "fact_id": "life", "indicator_name": "机械寿命", "source_value": "500次",
        "source_coordinates": {"body_index": source_block["body_index"], "table_row": 4,
                               "label_column": 0, "value_columns": [1]},
        "source_ids": [source_block["id"]],
    }], "comparison_decisions": [{
        "indicator_name": "机械寿命", "user_requirement": "500次",
        "user_fact_ids": ["life"], "user_source_ids": [source_block["id"]],
    }]}
    path.with_suffix(".indicator_audit.json").write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    path.with_suffix(".requirement_classification.json").write_text(json.dumps({
        "source_blocks": [source_block],
    }, ensure_ascii=False), encoding="utf-8")
    return source_path, path, audit


def _coverage(case):
    source, output, _ = case
    ledger = parse_docx_to_ledger(str(source))
    mark_covered_from_output(ledger, str(output))
    mark_structured_indicator_coverage(ledger, str(output))
    return ledger


def test_all_cells_are_proved_by_environmental_prose_and_the_identified_user_column(mixed_table_case):
    ledger = _coverage(mixed_table_case)
    assert ledger.passed()
    assert len(ledger.blocks[0].output_body_indices) == 4
    assert ledger.blocks[0].output_evidence_hash


@pytest.mark.parametrize("change", [
    "missing_non_environmental_row", "missing_environmental_row", "missing_condition",
    "wrong_value", "only_adopted_column", "wrong_coordinate", "wrong_label_coordinate",
    "wrong_source_id", "missing_consumption", "extra_source_condition", "duplicate_output_row",
])
def test_partial_or_unanchored_evidence_does_not_cover_the_whole_table(mixed_table_case, change):
    source_path, path, audit = mixed_table_case
    output = Document(path)
    source = Document(source_path)
    if change == "missing_non_environmental_row":
        output.tables[0].cell(1, 1).text = ""
    elif change == "missing_environmental_row":
        output.paragraphs[-1].text = ""
    elif change == "missing_condition":
        output.paragraphs[-3].text = "冲击：加速度980m/s 2。"
    elif change == "wrong_value":
        output.paragraphs[-1].text = "工作温度：-50℃～125℃。"
    elif change == "only_adopted_column":
        output.tables[0].cell(1, 1).text = ""
        output.tables[0].cell(1, 2).text = "500次"
    elif change == "wrong_coordinate":
        audit["input_indicator_facts"][0]["source_coordinates"]["table_row"] = 3
    elif change == "wrong_label_coordinate":
        audit["input_indicator_facts"][0]["source_coordinates"]["label_column"] = 1
    elif change == "wrong_source_id":
        audit["input_indicator_facts"][0]["source_ids"] = ["unrelated"]
        audit["comparison_decisions"][0]["user_source_ids"] = ["unrelated"]
    elif change == "missing_consumption":
        audit["comparison_decisions"][0]["user_fact_ids"] = []
    elif change == "extra_source_condition":
        source.tables[0].cell(4, 1).text = "500次，接触电阻变化不超过5mΩ"
        source.save(source_path)
    elif change == "duplicate_output_row":
        row = output.tables[0].add_row()
        row.cells[0].text = "机械寿命"
        row.cells[1].text = "500次"
    output.save(path)
    path.with_suffix(".indicator_audit.json").write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    ledger = _coverage(mixed_table_case)
    assert not ledger.passed()
    assert ledger.blocks[0].output_evidence_hash == ""


def test_environment_only_table_needs_no_indicator_audit_but_every_cell(mixed_table_case):
    source_path, path, _ = mixed_table_case
    source = Document(source_path)
    row = source.tables[0].rows[-1]._tr
    row.getparent().remove(row)
    source.save(source_path)
    path.with_suffix(".indicator_audit.json").unlink()
    assert _coverage(mixed_table_case).passed()


def test_non_environmental_content_inside_a_projected_cell_is_not_silently_covered(mixed_table_case):
    source_path, path, _ = mixed_table_case
    source = Document(source_path)
    source.tables[0].cell(3, 1).text += "；工作电压：60V"
    source.save(source_path)
    assert not _coverage(mixed_table_case).passed()


@pytest.mark.parametrize("omit_header", [False, True])
def test_environmental_column_meanings_must_survive_as_source_header_evidence(mixed_table_case, omit_header):
    source_path, path, _ = mixed_table_case
    source = Document()
    table = source.add_table(rows=2, cols=5)
    for row, values in zip(table.rows, [
        ["项目", "试验要求", "耐受阈值", "考核标准", "环境适配约束条件"],
        ["工业干扰环境", "80 MHz～1 GHz，10 V/m", "功能不得中断", "按用户试验规程C", "屏蔽壳体闭合后考核"],
    ]):
        for cell, value in zip(row.cells, values):
            cell.text = value
    source.save(source_path)
    output = Document()
    output.add_heading("环境适应性要求", 1)
    text = "工业干扰环境：试验要求：80 MHz～1 GHz，10 V/m；耐受阈值：功能不得中断；考核标准：按用户试验规程C；环境适配约束条件：屏蔽壳体闭合后考核。"
    output.add_paragraph(text.replace("考核标准：", "") if omit_header else text)
    output.save(path)
    path.with_suffix(".indicator_audit.json").unlink()
    ledger = _coverage(mixed_table_case)
    assert ledger.passed() is not omit_header
    if not omit_header:
        evidence = ledger.blocks[0].output_fragment_evidence
        assert [header["text"] for header in evidence[0]["source_headers"]] == [
            "试验要求", "耐受阈值", "考核标准", "环境适配约束条件",
        ]


@pytest.mark.parametrize("source_type", ["table", "paragraph"])
@pytest.mark.parametrize("replacement", ["1500次", "0.500次", "-500次", "≥500次", "500次/s"])
def test_source_fact_is_not_a_substring_of_a_changed_numeric_or_unit_token(mixed_table_case, source_type, replacement):
    source_path, path, audit = mixed_table_case
    if source_type == "paragraph":
        source = Document()
        source.add_paragraph("500次")
        source.save(source_path)
        block = extract_source_blocks(str(source_path), "tech")[0]
        fact = audit["input_indicator_facts"][0]
        fact["source_coordinates"] = {"body_index": block["body_index"], "start": 0, "end": 4}
        fact["source_ids"] = [block["id"]]
        audit["comparison_decisions"][0]["user_source_ids"] = [block["id"]]
        path.with_suffix(".requirement_classification.json").write_text(json.dumps({
            "source_blocks": [block],
        }, ensure_ascii=False), encoding="utf-8")
    output = Document(path)
    output.tables[0].cell(1, 1).text = replacement
    output.save(path)
    audit["comparison_decisions"][0]["user_requirement"] = replacement
    path.with_suffix(".indicator_audit.json").write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    ledger = _coverage(mixed_table_case)
    assert not ledger.passed()
    assert not ledger.blocks[0].output_evidence_hash
