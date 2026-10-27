"""真实 DOCX 回归：工作簿 Sheet1 C3:C6、B7 与开发逻辑 C51。"""

from pathlib import Path

import pytest
from docx import Document
from jonhon_taskbook.spec_extractor import extract_spec_chapter3_tables


def _extract(
    tmp_path: Path, headings: list[str], rows: list[list[str]], title="9.8 电性能"
):
    document = Document()
    document.add_heading(title, level=1)
    table = document.add_table(rows=1, cols=len(headings))
    for cell, value in zip(table.rows[0].cells, headings):
        cell.text = value
    for values in rows:
        for cell, value in zip(table.add_row().cells, values):
            cell.text = value
    path = tmp_path / "规范.docx"
    document.save(path)
    return extract_spec_chapter3_tables(str(path))


def test_contact_sizes_remain_separate_and_never_become_values(tmp_path):
    items = _extract(
        tmp_path,
        ["项目", "接触件规格", "要求"],
        [
            ["接触电阻", "#22D", "≤10 mΩ"],
            ["接触电阻", "#20", "≤8 mΩ"],
            ["接触电阻", "#16", "≤5 mΩ"],
        ],
    )
    assert [item.spec for item in items] == ["≤10 mΩ", "≤8 mΩ", "≤5 mΩ"]
    assert [item.qualifiers for item in items] == [
        {"接触件规格": "#22D"},
        {"接触件规格": "#20"},
        {"接触件规格": "#16"},
    ]
    assert all(item.qualifiers["接触件规格"] in item.standard_text for item in items)


def test_numeric_unit_and_bound_columns_are_independent_candidates(tmp_path):
    items = _extract(
        tmp_path,
        ["项目", "min（mΩ）", "typ（mΩ）", "max（mΩ）"],
        [
            ["接触电阻", "1", "3", "5"],
        ],
    )
    assert [(item.value_kind, item.spec, item.unit) for item in items] == [
        ("min", "1", "mΩ"),
        ("typ", "3", "mΩ"),
        ("max", "5", "mΩ"),
    ]
    assert all(
        item.value_kind in item.standard_text and "mΩ" in item.standard_text
        for item in items
    )


def test_inline_typical_and_max_values_do_not_merge(tmp_path):
    items = _extract(tmp_path, ["项目", "要求"], [["接触电阻", "max ≤5 mΩ；typ 3 mΩ"]])
    assert [(item.value_kind, item.spec) for item in items] == [
        ("max", "≤5 mΩ"),
        ("typ", "3 mΩ"),
    ]
    assert all(item.raw_row["要求"] == "max ≤5 mΩ；typ 3 mΩ" for item in items)


def test_model_shell_and_positions_are_preserved_as_distinct_scope(tmp_path):
    items = _extract(
        tmp_path,
        ["项目", "适用型号", "壳体号", "位数", "要求"],
        [
            ["额定电流", "J599A", "11", "6", "5 A"],
            ["额定电流", "J599B", "13", "8", "7 A"],
        ],
    )
    assert [item.applicable_model for item in items] == ["J599A", "J599B"]
    assert [item.qualifiers for item in items] == [
        {"壳体号": "11", "位数": "6"},
        {"壳体号": "13", "位数": "8"},
    ]
    assert [item.spec for item in items] == ["5 A", "7 A"]


def test_multiple_test_conditions_are_kept_with_their_values(tmp_path):
    items = _extract(
        tmp_path,
        ["项目", "测试条件", "要求", "试验方法"],
        [
            ["绝缘电阻", "常温、试验前", "≥5000 MΩ", "方法 A"],
            ["绝缘电阻", "-55℃、试验后", "≥1000 MΩ", "方法 B"],
        ],
    )
    assert [item.condition for item in items] == ["常温、试验前", "-55℃、试验后"]
    assert [item.spec for item in items] == ["≥5000 MΩ", "≥1000 MΩ"]
    assert [item.test_method for item in items] == ["方法 A", "方法 B"]
    assert all(item.condition in item.standard_text for item in items)


@pytest.mark.parametrize(
    ("headers", "expected_qualifiers", "expected_scopes", "expected_conditions"),
    [
        (
            ["项目", "#22D", "#20", "#16"],
            [{"接触件规格": "#22D"}, {"接触件规格": "#20"}, {"接触件规格": "#16"}],
            ["", "", ""],
            ["", "", ""],
        ),
        (
            ["项目", "AWG 22", "AWG 20", "AWG 16"],
            [{"线规": "AWG 22"}, {"线规": "AWG 20"}, {"线规": "AWG 16"}],
            ["", "", ""],
            ["", "", ""],
        ),
        (
            ["项目", "J599A", "J599B", "J599C"],
            [{}, {}, {}],
            ["J599A", "J599B", "J599C"],
            ["", "", ""],
        ),
        (
            ["项目", "常温", "-55℃", "试验后"],
            [{}, {}, {}],
            ["", "", ""],
            ["常温", "-55℃", "试验后"],
        ),
    ],
)
def test_parallel_columns_preserve_each_candidate(
    tmp_path, headers, expected_qualifiers, expected_scopes, expected_conditions
):
    items = _extract(tmp_path, headers, [["绝缘电阻", "5000 MΩ", "3000 MΩ", "1000 MΩ"]])
    assert [item.spec for item in items] == ["5000 MΩ", "3000 MΩ", "1000 MΩ"]
    assert [item.qualifiers for item in items] == expected_qualifiers
    assert [item.applicable_model for item in items] == expected_scopes
    assert [item.condition for item in items] == expected_conditions


def test_indicator_heading_provides_metric_for_awg_table(tmp_path):
    items = _extract(
        tmp_path,
        ["线规（AWG）", "电流（A）"],
        [["22", "3"], ["20", "5"]],
        "8.4 额定电流",
    )
    assert [item.item_name for item in items] == ["额定电流", "额定电流"]
    assert [item.spec for item in items] == ["3", "5"]
    assert [item.unit for item in items] == ["A", "A"]
    assert [item.qualifiers for item in items] == [
        {"线规（AWG）": "22"},
        {"线规（AWG）": "20"},
    ]


def test_merged_multilevel_header_keeps_units_and_vertical_qualifiers(tmp_path):
    document = Document()
    document.add_heading("11.2 接触电阻", level=2)
    table = document.add_table(rows=4, cols=4)
    table.cell(0, 0).merge(table.cell(1, 0)).text = "接触件规格"
    table.cell(0, 1).merge(table.cell(0, 3)).text = "接触电阻（mΩ）"
    for cell, value in zip(table.rows[1].cells[1:], ["min", "typ", "max"]):
        cell.text = value
    table.cell(2, 0).merge(table.cell(3, 0)).text = "#22D"
    for row, values in zip(table.rows[2:], [["1", "3", "5"], ["2", "4", "6"]]):
        for cell, value in zip(row.cells[1:], values):
            cell.text = value
    path = tmp_path / "merged.docx"
    document.save(path)
    items = extract_spec_chapter3_tables(str(path))
    assert len(items) == 6
    assert [item.value_kind for item in items] == ["min", "typ", "max"] * 2
    assert all(item.item_name == "接触电阻" and item.unit == "mΩ" for item in items)
    assert all(item.qualifiers == {"接触件规格": "#22D"} for item in items)


def test_specification_without_requirement_never_becomes_indicator_value(tmp_path):
    items = _extract(
        tmp_path, ["项目", "规格", "适用型号"], [["额定电流", "0.51 mm", "J599A"]]
    )
    assert items == []


def test_semantic_sections_not_chapter_numbers_control_extraction(tmp_path):
    document = Document()
    for title, value in [("3.1 变更记录", "错误改后值"), ("12.4 电性能", "≤5 mΩ")]:
        document.add_heading(title, level=1)
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text, table.cell(0, 1).text = "项目", "要求"
        table.cell(1, 0).text, table.cell(1, 1).text = "接触电阻", value
    path = tmp_path / "context.docx"
    document.save(path)
    items = extract_spec_chapter3_tables(str(path))
    assert [item.spec for item in items] == ["≤5 mΩ"]
    assert items[0].source_section == "电性能"


def test_condition_parameters_remain_attached_to_voltage_requirement(tmp_path):
    items = _extract(
        tmp_path,
        ["项目", "电压（V）", "DC/AC", "频率", "测试时间", "漏电流值"],
        [
            ["介质耐电压", "1000", "AC", "50 Hz", "1 min", "≤2 mA"],
        ],
    )
    assert len(items) == 1
    assert items[0].spec == "1000" and items[0].unit == "V"
    assert all(text in items[0].condition for text in ["AC", "50 Hz", "1 min", "≤2 mA"])
    assert all(
        text in items[0].standard_text for text in ["AC", "50 Hz", "1 min", "≤2 mA"]
    )


def test_environment_temperature_is_a_value_when_it_is_the_named_metric(tmp_path):
    items = _extract(tmp_path, ["项目", "环境温度"], [["环境温度", "-55℃～125℃"]])
    assert len(items) == 1
    assert items[0].spec == "-55℃～125℃" and items[0].condition == ""


def test_condition_in_heading_scopes_each_table(tmp_path):
    document = Document()
    document.add_heading("13.4 绝缘电阻", level=1)
    for condition, value in [("常温", "≥5000 MΩ"), ("-55℃", "≥1000 MΩ")]:
        document.add_heading(condition, level=2)
        table = document.add_table(rows=2, cols=1)
        table.cell(0, 0).text, table.cell(1, 0).text = "要求", value
    path = tmp_path / "conditions.docx"
    document.save(path)
    items = extract_spec_chapter3_tables(str(path))
    assert [item.item_name for item in items] == ["绝缘电阻", "绝缘电阻"]
    assert [item.condition for item in items] == ["常温", "-55℃"]
    assert [item.spec for item in items] == ["≥5000 MΩ", "≥1000 MΩ"]


def test_compound_force_columns_remain_one_requirement(tmp_path):
    items = _extract(
        tmp_path,
        ["项目", "规格", "插入力", "拔出力"],
        [["插拔力", "#22D", "≤5 N", "≥1 N"]],
    )
    assert len(items) == 1
    assert items[0].spec == "插入力：≤5 N；拔出力：≥1 N"
    assert items[0].qualifiers == {"规格": "#22D"}


def test_random_vibration_named_rows_are_not_collapsed_into_one_matrix(tmp_path):
    items = _extract(
        tmp_path,
        ["项目", "测试条件", "要求"],
        [
            ["随机振动", "等级 A", "5 g"],
            ["随机振动", "等级 B", "10 g"],
        ],
    )
    assert [item.item_name for item in items] == ["随机振动", "随机振动"]
    assert [item.condition for item in items] == ["等级 A", "等级 B"]
    assert [item.spec for item in items] == ["5 g", "10 g"]


def test_vibration_matrix_keeps_levels_and_only_local_supplement(tmp_path):
    document = Document()
    document.add_heading("3.1 其他试验", level=1)
    document.add_paragraph("配重为错误的前章条件。")
    document.add_heading("12.2 振动", level=1)
    table = document.add_table(rows=1, cols=3)
    for cell, value in zip(table.rows[0].cells, ["振动等级", "频率", "功率谱密度"]):
        cell.text = value
    for values in [
        ["A", "10～100 Hz", "0.1 g²/Hz"],
        ["A", "100～200 Hz", "0.2 g²/Hz"],
        ["B", "10～100 Hz", "0.3 g²/Hz"],
    ]:
        for cell, value in zip(table.add_row().cells, values):
            cell.text = value
    document.add_paragraph("配重由本组试验装置确定。")
    path = tmp_path / "vibration.docx"
    document.save(path)
    items = extract_spec_chapter3_tables(str(path))
    assert len(items) == 2
    assert [item.condition for item in items] == ["振动等级：A", "振动等级：B"]
    assert "0.2 g²/Hz" in items[0].spec and "0.3 g²/Hz" not in items[0].spec
    assert all(
        "错误" not in item.standard_text and "本组试验装置" in item.standard_text
        for item in items
    )
