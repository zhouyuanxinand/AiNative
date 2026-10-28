"""Explicit model overrides and trial conditions must participate in comparison."""
import pytest
from docx import Document

from jonhon_taskbook.extractor import parse_doc
from jonhon_taskbook.fill import _build_spec_table_ledger, _match_spec_table_indicator, build_content
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks
from jonhon_taskbook.spec_applicability import compare_applicable_values


def _spec(tmp_path):
    doc = Document()
    doc.add_heading("要求", 1)
    doc.add_heading("绝缘电阻", 2)
    table = doc.add_table(rows=1, cols=3)
    for cell, value in zip(table.rows[0].cells, ["序号", "工作环境", "绝缘电阻MΩ"]):
        cell.text = value
    for row in [["1", "常温状态", "≥5000"], ["2", "湿热状态", "≥50"]]:
        for cell, value in zip(table.add_row().cells, row):
            cell.text = value
    doc.add_heading("介质耐电压", 2)
    doc.add_paragraph("OTHER18J连接器介质耐电压要求如下：")
    doc.add_paragraph("常温常压：900V，AC 测试时间60s；")
    doc.add_paragraph("CY43MZ6B1eJ、CY43MT6BPJ连接器介质耐电压要求如下：")
    doc.add_paragraph("常温常压：500V，AC 测试时间60s；")
    doc.add_paragraph("低气压（4.4Kpa），150V AC 测试时间60s。")
    doc.add_heading("质量保证规定", 1)
    doc.add_heading("检验方法", 2)
    doc.add_heading("机械寿命", 3)
    doc.add_paragraph("按GJB1217A-2009方法2016的规定进行试验，连接器插合和分离循环次数为1000次。（当型号为OTHER18J、OTHER30J时，循环次数为500次）")
    doc.add_heading("互换性", 3)
    doc.add_paragraph("检验抽样1000次，不是机械寿命要求。")
    path = tmp_path / "spec.docx"
    doc.save(path)
    return _build_spec_table_ledger(str(path))


def _hit(ledger, name, user, model="CY43MT6BPJ"):
    return _match_spec_table_indicator(ledger, {"name": name}, product_series="CY",
        model_context=model, user_requirement=user)


def test_work_environment_defaults_only_to_ambient_and_keeps_value(tmp_path):
    hit = _hit(_spec(tmp_path), "绝缘电阻", "≥1000MΩ")
    assert not hit["manual_review_required"]
    assert hit["default_conditions_applied"]
    assert [item["value"] for item in hit["items"]] == ["≥5000"]


def test_current_model_voltage_override_preserves_sixty_second_source(tmp_path):
    hit = _hit(_spec(tmp_path), "介质耐电压", "常温常压500V AC，测试时间5s")
    assert hit and hit["manual_review_required"]
    assert hit["status"] == "SPEC_CONDITION_MISMATCH"
    assert "60" in hit["reason"] and "5" in hit["reason"]
    candidates = hit["candidate_items"]
    assert len(candidates) == 2
    assert all("CY43MT6BPJ" in item["scope"] for item in candidates)
    assert all("60s" in item["source_evidence"]["_source_text"] for item in candidates)
    assert all(item["source_evidence"]["_body_index"] >= 0 for item in candidates)
    assert hit["value"] == ""


def test_equivalent_duration_and_pressure_select_exact_low_pressure_group(tmp_path):
    hit = _hit(_spec(tmp_path), "介质耐电压", "4.4kPa：150V AC，测试时间1min")
    assert not hit["manual_review_required"]
    assert len(hit["items"]) == 1
    assert "150V" in hit["value"]
    assert "500V" not in hit["value"]


@pytest.mark.parametrize("model,standard,manual", [
    ("CY43MT6BPJ", "1000次", True), ("OTHER18J", "500次", False),
])
def test_life_default_and_explicit_model_exception_remain_separate(tmp_path, model, standard, manual):
    hit = _hit(_spec(tmp_path), "机械寿命", "500次", model=model)
    assert hit and not hit["manual_review_required"]
    assert hit["value"] == standard
    comparison = compare_applicable_values("500次", ["机械寿命"], hit)
    assert comparison.manual_review_required is manual
    assert "GJB1217A-2009" in hit["items"][0]["test_method"]


def test_model_scoped_paragraphs_are_not_general_family_evidence(tmp_path):
    hit = _hit(_spec(tmp_path), "介质耐电压", "常温常压500V AC，测试时间60s", model="CY43UNKNOWN")
    assert hit and hit["inapplicable"]
    assert hit["value"] == ""


@pytest.mark.parametrize("prefix", ["仅对型号OTHER18J，", "不适用于CY43MT6BPJ，", "示例："])
def test_restricted_negated_or_example_life_prose_is_not_general_evidence(tmp_path, prefix):
    doc = Document()
    doc.add_heading("机械寿命", 1)
    doc.add_paragraph(prefix + "连接器插合和分离循环次数为1000次。")
    path = tmp_path / "scoped-life.docx"
    doc.save(path)
    assert _build_spec_table_ledger(str(path)) == {}


def test_input_models_crossing_life_exception_require_per_model_confirmation(tmp_path):
    hit = _hit(_spec(tmp_path), "机械寿命", "500次", model="OTHER18J、CY43MT6BPJ")
    assert hit["manual_review_required"]
    assert hit["status"] == "SPEC_MULTIPLE_MODELS"
    assert hit["value"] == ""


def test_series_without_exact_model_cannot_resolve_life_exception(tmp_path):
    hit = _hit(_spec(tmp_path), "机械寿命", "500次", model="CY")
    assert hit["manual_review_required"]
    assert hit["status"] == "SPEC_MODEL_UNSPECIFIED"
    assert hit["value"] == ""


def test_standards_and_hardware_in_identity_context_do_not_create_extra_models(tmp_path):
    hit = _hit(_spec(tmp_path), "机械寿命", "500次",
        model="OTHER18J；按GJB1217A-2009；GB/T1804-m；M2螺钉")
    assert not hit["manual_review_required"]
    assert hit["value"] == "500次"


def test_explicit_voltage_scope_cannot_cover_an_unlisted_second_product(tmp_path):
    hit = _hit(_spec(tmp_path), "介质耐电压", "常温常压500V AC，测试时间60s",
        model="CY43MT6BPJ、CY43UNKNOWN")
    assert hit["manual_review_required"]
    assert hit["status"] == "SPEC_MODEL_COVERAGE_UNRESOLVED"
    assert hit["value"] == ""


def test_both_explicitly_listed_voltage_models_share_the_same_requirement(tmp_path):
    hit = _hit(_spec(tmp_path), "介质耐电压", "常温常压500V AC，测试时间60s",
        model="CY43MT6BPJ、CY43MZ6B1eJ；GJB1217A-2009；M2螺钉")
    assert not hit["manual_review_required"]
    assert hit["value"] == "500V"


@pytest.mark.parametrize("parent,scope", [
    ("OTHER18J产品要求", ""), ("历史试验记录", ""),
    ("产品要求", "仅适用于OTHER18J。"),
])
def test_unparsed_parent_or_previous_scope_never_becomes_generic_life(tmp_path, parent, scope):
    doc = Document()
    doc.add_heading(parent, 1)
    doc.add_heading("机械寿命", 2)
    if scope:
        doc.add_paragraph(scope)
    doc.add_paragraph("连接器插合和分离循环次数为1000次。")
    path = tmp_path / "parent-scope.docx"
    doc.save(path)
    assert _build_spec_table_ledger(str(path)) == {}


def test_parent_scope_paragraph_survives_a_nested_metric_heading(tmp_path):
    doc = Document()
    doc.add_heading("产品要求", 1)
    doc.add_paragraph("仅适用于OTHER18J。")
    doc.add_heading("机械寿命", 2)
    doc.add_paragraph("连接器插合和分离循环次数为1000次。")
    path = tmp_path / "nested-scope.docx"
    doc.save(path)
    assert _build_spec_table_ledger(str(path)) == {}


def test_following_scope_note_cannot_leave_a_generic_life_candidate(tmp_path):
    doc = Document()
    doc.add_heading("机械寿命", 1)
    doc.add_paragraph("连接器插合和分离循环次数为1000次。")
    doc.add_paragraph("仅适用于OTHER18J。")
    path = tmp_path / "later-scope.docx"
    doc.save(path)
    assert _build_spec_table_ledger(str(path)) == {}


@pytest.mark.parametrize("title,models,explicit_short_model,status", [
    ("CY43-6连接器技术要求", "CY43MT6BPJ、CY43MZ6B1eJ", False, "SPEC_CONDITION_MISMATCH"),
    ("CY43-6连接器技术要求", "CY43MT6BPJ、CY43MZ6B1eJ、CY43UNKNOWN", False, "SPEC_MODEL_COVERAGE_UNRESOLVED"),
    ("CY43UNKNOWN连接器技术要求", "CY43MT6BPJ、CY43MZ6B1eJ", False, "SPEC_MODEL_COVERAGE_UNRESOLVED"),
    ("CY43-99连接器技术要求", "CY43MT6BPJ、CY43MZ6B1eJ", False, "SPEC_MODEL_COVERAGE_UNRESOLVED"),
    ("CY43-6连接器技术要求", "CY43MT6BPJ、CY43MZ6B1eJ", True, "SPEC_MODEL_COVERAGE_UNRESOLVED"),
])
def test_full_writer_distinguishes_document_family_title_from_explicit_products(
    tmp_path, title, models, explicit_short_model, status,
):
    """CY document's cover/title and product declarations reach real writer."""
    _spec(tmp_path)
    spec_path = tmp_path / "spec.docx"
    spec = Document(spec_path)
    tech = Document()
    for index in range(19):
        tech.add_paragraph("技术要求" if index == 3 else "变更记录" if index == 16 else "")
    tech.add_paragraph(title)
    tech.add_heading("1 概述", 1)
    tech.add_paragraph(f"本技术要求规定了{models}产品研制的相关要求。")
    if explicit_short_model:
        table = tech.add_table(rows=1, cols=2)
        table.cell(0, 0).text, table.cell(0, 1).text = "产品型号", "CY43-6"
    tech.add_heading("电气技术要求", 1)
    table = tech.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "项目", "指标"
    table.cell(1, 0).text = "介质耐电压"
    table.cell(1, 1).text = "常温常压：500V AC；低气压（4.4Kpa）：150V AC耐电压测试时间5s"
    tech_path = tmp_path / "tech.docx"
    tech.save(tech_path)
    blocks = extract_source_blocks(str(tech_path), "tech")
    classification = {"source_blocks": blocks, "classifications": [
        {"source_id": block["id"], "category": "performance_indicator"
            if block["type"] == "table" and "5s" in block["text"] else "source_and_function"}
        for block in blocks]}
    profile = {"semantic_structures": {"performance_indicator": {"mode": "indicator_table"}},
        "indicator_sources": {"workbook": False, "reference_families": []},
        "indicator_map": {"电性能": [{"name": "介质耐电压"}]}}
    result = build_content(profile, tech, spec, parse_doc(tech), parse_doc(spec), str(tech_path),
        str(spec_path), product_series="CY", requirement_classification=classification)["role:performance_indicator"]
    decision = next(item for item in result["indicator_comparison_audit"] if item["indicator_name"] == "介质耐电压")
    assert decision["status"] == status
    assert decision["manual_review_required"]
    if status == "SPEC_CONDITION_MISMATCH":
        assert "输入5 s" in decision["reason"] and "规范60 s" in decision["reason"]
