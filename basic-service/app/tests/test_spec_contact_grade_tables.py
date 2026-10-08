"""CY input regression: bare-unit headers and explicitly paired contact grades."""
import json

import pytest
from docx import Document

from jonhon_taskbook.business_value_gate import audit_indicator_values
from jonhon_taskbook.extractor import parse_doc
from jonhon_taskbook.fill import _build_spec_table_ledger, _match_spec_table_indicator, build_content
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks
from jonhon_taskbook.spec_extractor import extract_spec_chapter3_tables


def spec_document(tmp_path):
    document = Document()
    for heading, header, values in [
        ("额定工作电流", "额定电流A", [("Ф1", "5"), ("16#(Φ1.6)", "15"), ("Φ0.5", "1")]),
        ("接触电阻", "接触电阻Ω", [("Ф1", "≤0.0045"), ("Ф1.5、16#(Ф1.6)", "≤0.0025"), ("Ф0.5", "≤0.015")]),
    ]:
        document.add_heading(heading, 1)
        table = document.add_table(rows=1, cols=3)
        for cell, value in zip(table.rows[0].cells, ["序号", "接触件规格mm", header]):
            cell.text = value
        for index, (grade, value) in enumerate(values, 1):
            for cell, text in zip(table.add_row().cells, [str(index), grade, value]):
                cell.text = text
    path = tmp_path / "spec.docx"
    document.save(path)
    return path, document


def test_bare_units_are_headers_and_contact_dimensions_never_become_metrics(tmp_path):
    path, _ = spec_document(tmp_path)
    items = extract_spec_chapter3_tables(str(path))
    assert [(item.item_name, item.spec, item.unit) for item in items] == [
        ("额定电流", "5", "A"), ("额定电流", "15", "A"), ("额定电流", "1", "A"),
        ("接触电阻", "≤0.0045", "Ω"), ("接触电阻", "≤0.0025", "Ω"), ("接触电阻", "≤0.015", "Ω"),
    ]
    assert items[4].qualifiers == {"接触件规格mm": "Ф1.5、16#(Ф1.6)"}


@pytest.mark.parametrize("name,user,expected", [
    ("工作电流", "16#接触件：15A；φ0.5接触件：1A", ["15", "1"]),
    ("接触电阻", "16#：≤2.5mΩ；φ0.5≤15mΩ", ["≤0.0025", "≤0.015"]),
])
def test_only_the_two_explicit_contact_grades_are_selected(tmp_path, name, user, expected):
    path, _ = spec_document(tmp_path)
    hit = _match_spec_table_indicator(_build_spec_table_ledger(str(path)),
        {"name": name, "related_kws": ["额定电流"] if name == "工作电流" else []},
        user_requirement=user, product_series="CY")
    assert not hit["manual_review_required"]
    assert [item["value"] for item in hit["items"]] == expected
    assert len(hit["grade_groups"]) == 2


def test_complete_known_grades_generate_guaranteed_rows_without_false_clarification(tmp_path):
    spec_path, spec = spec_document(tmp_path)
    tech = Document()
    tech.add_heading("电气技术要求", 1)
    table = tech.add_table(rows=1, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "项目", "指标"
    values = {"工作电流": "16#接触件：15A；φ0.5接触件：1A", "接触电阻": "16#：≤2.5mΩ；φ0.5≤15mΩ"}
    for name, value in values.items():
        cells = table.add_row().cells
        cells[0].text, cells[1].text = name, value
    tech_path = tmp_path / "tech.docx"
    tech.save(tech_path)
    blocks = extract_source_blocks(str(tech_path), "tech")
    classification = {"source_blocks": blocks, "classifications": [
        {"source_id": block["id"], "category": "performance_indicator"} for block in blocks]}
    profile = {"semantic_structures": {"performance_indicator": {"mode": "indicator_table"}},
        "indicator_sources": {"workbook": False, "reference_families": []},
        "indicator_map": {"电性能": [
            {"name": "工作电流", "related_kws": ["额定电流"]}, {"name": "接触电阻"}]}}
    result = build_content(profile, tech, spec, parse_doc(tech), parse_doc(spec), str(tech_path),
        str(spec_path), product_series="CY", requirement_classification=classification)["role:performance_indicator"]
    decisions = {item["indicator_name"]: item for item in result["indicator_comparison_audit"]}
    for name, original in values.items():
        assert decisions[name]["adopted_requirement"] == original
        assert decisions[name]["numeric_status"] == "equal"
        assert not decisions[name]["manual_review_required"]


@pytest.mark.parametrize("user", ["≤5mΩ", "16#：≤2.5mΩ；φ99：≤15mΩ", "16#与φ0.5接触件间≤2.5mΩ"])
def test_missing_or_unpaired_grade_information_remains_manual(tmp_path, user):
    path, _ = spec_document(tmp_path)
    hit = _match_spec_table_indicator(_build_spec_table_ledger(str(path)), {"name": "接触电阻"}, user_requirement=user, product_series="CY")
    assert hit["manual_review_required"]


@pytest.mark.parametrize("change,expected", [("marker_position", True), ("number", False), ("missing_marker", False)])
def test_value_gate_allows_only_marker_position_as_a_display_change(tmp_path, change, expected):
    path = tmp_path / "output.docx"
    document = Document()
    table = document.add_table(rows=2, cols=4)
    for cell, text in zip(table.rows[0].cells, ["项目", "用户要求指标", "拟采用指标", "拟采用指标和试验的依据"]):
        cell.text = text
    actual = "规范候选：规格#16（≤5mΩ）【人工填写】"
    if change == "number":
        actual = actual.replace("5mΩ", "4mΩ")
    if change == "missing_marker":
        actual = actual.replace("【人工填写】", "")
    for cell, text in zip(table.rows[1].cells, ["接触电阻", "≤5mΩ", actual, "待确认"]):
        cell.text = text
    document.save(path)
    path.with_suffix(".indicator_audit.json").write_text(json.dumps({"comparison_decisions": [{
        "indicator_name": "接触电阻", "user_requirement": "≤5mΩ",
        "adopted_requirement": "【人工填写】\n规范候选：规格#16（≤5mΩ）", "basis": "待确认"}]}), encoding="utf-8")
    assert audit_indicator_values(path, persist=False)["passed"] is expected
