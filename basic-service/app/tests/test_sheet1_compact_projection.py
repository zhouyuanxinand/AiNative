"""Sheet1 回归：正式指标表只投影适用且可判定的规范值。

本文件刻意走真实链路：DOCX 多层表头 -> 规范台账 -> 适用性选择。
Sheet1 允许完整候选留在审计数据里，但正式表格中的 ``display_value``
必须按档位归组，不能逐单元格重复档位，也不能把 typ 混入保证值。
"""

from docx import Document
from jonhon_taskbook.fill import (
    _build_spec_table_ledger,
    _fill_indicator_table,
    _match_spec_table_indicator,
    build_content,
    parse_doc,
)


def _multi_grade_spec(tmp_path):
    document = Document()
    document.add_heading("11.2 接触电阻", level=2)
    table = document.add_table(rows=2, cols=4)
    table.cell(0, 0).merge(table.cell(1, 0)).text = "接触件规格"
    table.cell(0, 1).merge(table.cell(0, 3)).text = "接触电阻（mΩ）"
    for cell, text in zip(table.rows[1].cells[1:], ("min", "typ", "max")):
        cell.text = text
    for values in (
        ("#22D", "1", "3", "10"),
        ("#20", "1", "3", "8"),
        ("#16", "1", "3", "5"),
    ):
        for cell, text in zip(table.add_row().cells, values):
            cell.text = text
    path = tmp_path / "multi-grade-spec.docx"
    document.save(path)
    return _build_spec_table_ledger(str(path))


def _series_condition_spec(tmp_path):
    document = Document()
    document.add_heading("13.4 绝缘电阻", level=2)
    table = document.add_table(rows=1, cols=6)
    for cell, text in zip(
        table.rows[0].cells,
        ("项目", "适用型号", "测试条件", "min（MΩ）", "typ（MΩ）", "max（MΩ）"),
    ):
        cell.text = text
    for values in (
        ("绝缘电阻", "J599A", "常温、试验前", "5000", "6000", "7000"),
        ("绝缘电阻", "J599A", "-55℃、试验后", "1000", "2000", "3000"),
        ("绝缘电阻", "J599B", "常温、试验前", "4000", "5000", "6000"),
    ):
        for cell, text in zip(table.add_row().cells, values):
            cell.text = text
    path = tmp_path / "series-condition-spec.docx"
    document.save(path)
    return _build_spec_table_ledger(str(path))


def _select(ledger, requirement, *, indicator="接触电阻", **contexts):
    return _match_spec_table_indicator(
        ledger,
        {"name": indicator},
        user_requirement=requirement,
        **contexts,
    )


def test_selected_grade_is_projected_once_without_typ_or_other_grades(tmp_path):
    decision = _select(
        _multi_grade_spec(tmp_path),
        "#20 接触件的接触电阻不超过 9 mΩ。",
    )

    assert decision["status"] == "SPEC_APPLICABLE"
    assert decision["manual_review_required"] is False
    assert decision["value"] == "min: 1 mΩ；max: 8 mΩ"

    # Sheet1 C3/C4：只投影本次档位的保证值；档位只写一次。
    display = decision["display_value"]
    assert display.count("#20") == 1
    assert "#22D" not in display and "#16" not in display
    assert "typ" not in display.lower()


def test_missing_grade_lists_each_grade_once_and_keeps_typ_out_of_formal_value(tmp_path):
    decision = _select(
        _multi_grade_spec(tmp_path),
        "接触电阻不超过 9 mΩ。",
    )

    assert decision["status"] == "SPEC_GRADE_UNSPECIFIED"
    assert decision["manual_review_required"] is True

    # Sheet1 C3/B7：缺档位时逐档展示并澄清，而不是把每个 min/typ/max
    # 单元格连成长串，造成档位与参考值重复进入正式指标表。
    display = decision["display_value"]
    assert all(display.count(grade) == 1 for grade in ("#22D", "#20", "#16"))
    assert "typ" not in display.lower()


def test_shared_series_and_test_condition_are_each_projected_once(tmp_path):
    decision = _select(
        _series_condition_spec(tmp_path),
        "在-55℃、试验后，绝缘电阻不低于 1200 MΩ。",
        indicator="绝缘电阻",
        model_context="产品型号：J599A",
    )

    assert decision["status"] == "SPEC_APPLICABLE"
    assert decision["manual_review_required"] is False
    display = decision["display_value"]
    assert display.count("J599A") == 1
    assert display.count("-55℃、试验后") == 1
    assert "J599B" not in display and "常温" not in display
    assert "typ" not in display.lower()


def test_unmatched_test_condition_does_not_project_unrelated_candidate_values(tmp_path):
    decision = _select(
        _series_condition_spec(tmp_path),
        "在 85℃ 下，绝缘电阻不低于 1200 MΩ。",
        indicator="绝缘电阻",
        model_context="产品型号：J599A",
    )

    assert decision["status"] == "SPEC_CONDITION_MISMATCH"
    assert decision["manual_review_required"] is True
    assert "条件不符，不可比" in decision["reason"]
    # 不匹配候选保留在 candidate_items/rejected_items 供审计，不能作为
    # 本次产品规范要求继续写入正式指标表。
    assert decision["display_value"] == ""


def test_build_content_does_not_rebuild_raw_candidates_after_condition_mismatch(tmp_path):
    technical = Document()
    technical.add_heading("绝缘电阻", level=1)
    requirement = "在 85℃ 下，绝缘电阻不低于 1200 MΩ。"
    technical.add_paragraph(requirement)
    technical_path = tmp_path / "technical.docx"
    technical.save(technical_path)

    specification = Document()
    specification.add_heading("绝缘电阻", level=1)
    table = specification.add_table(rows=1, cols=3)
    for cell, text in zip(table.rows[0].cells, ("项目", "测试条件", "要求")):
        cell.text = text
    for values in (
        ("绝缘电阻", "常温", "≥5000 MΩ"),
        ("绝缘电阻", "-55℃", "≥1000 MΩ"),
    ):
        for cell, text in zip(table.add_row().cells, values):
            cell.text = text
    specification_path = tmp_path / "specification.docx"
    specification.save(specification_path)

    template = Document()
    target = template.add_table(rows=2, cols=5)
    for cell, text in zip(
        target.rows[0].cells,
        ("项目", "用户要求", "标准要求", "拟采用", "依据"),
    ):
        cell.text = text
    target.cell(1, 0).text = "绝缘电阻"
    config = {
        "semantic_structures": {
            "performance_indicator": {"mode": "indicator_table"}
        },
        "indicator_sources": {"workbook": False, "reference_families": []},
        "indicator_map": {
            "电性能": [{"name": "绝缘电阻", "tech_kws": ["绝缘电阻"]}]
        },
    }
    classification = {
        "source_blocks": [
            {
                "id": "requirement-1",
                "type": "paragraph",
                "text": requirement,
                "heading_text": "绝缘电阻",
                "body_index": 1,
            }
        ],
        "classifications": [
            {"source_id": "requirement-1", "category": "performance_indicator"}
        ],
    }

    content = build_content(
        config,
        technical,
        specification,
        parse_doc(technical),
        parse_doc(specification),
        str(technical_path),
        str(specification_path),
        template_doc=template,
        requirement_classification=classification,
    )["role:performance_indicator"]
    _fill_indicator_table(template, content["indicator_rows"])

    rendered = target.rows[1].cells
    assert rendered[2].text == ""
    assert rendered[3].text == "【人工填写】"
    assert "规范候选" not in rendered[3].text
    decision = content["indicator_comparison_audit"][0]
    assert decision["status"] == "SPEC_CONDITION_MISMATCH"
    assert len(decision["candidate_comparisons"]) == 2
