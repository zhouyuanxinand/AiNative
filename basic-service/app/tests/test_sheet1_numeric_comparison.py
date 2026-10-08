"""7-22 C51 and Sheet1 C4: compare guaranteed bounds, never typical values."""

import pytest
from jonhon_taskbook.indicator_comparison import compare_indicator_values


@pytest.mark.parametrize(
    ("user", "standard", "expected"),
    [
        ("≤5mΩ", "≤4MΩ", "≤5mΩ"),
        ("≥5mΩ", "≥5MΩ", "≥5MΩ"),
        ("≤500mV", "≤0.4V", "≤0.4V"),
        ("≥1000小时", "≥60min", "≥1000小时"),
        ("≤0.8MPa", "≤700kPa", "≤700kPa"),
        ("≥1MHz", "≥900kHz", "≥1MHz"),
        ("≥20次", "≥25次", "≥25次"),
        ("≥-20℃", "≥-10℃", "≥-10℃"),
        ("≤5N", "<5N", "<5N"),
        (">5N", "≥5N", ">5N"),
        ("≥3V且≤6V", "≥4V且≤5V", "≥4V且≤5V"),
        ("min 3V, max 6V", "min 4V, max 5V", "min 4V, max 5V"),
        ("≤4mΩ", "max ≤5mΩ、typ 3mΩ", "≤4mΩ"),
        ("≤6mΩ", "max ≤5mΩ、typ 3mΩ", "max ≤5mΩ、typ 3mΩ"),
        ("≤6mΩ", "typ 3mΩ，max 5mΩ", "typ 3mΩ，max 5mΩ"),
        ("min 3V，typ 4V，max 6V", "min 4V，typ 4.5V，max 5V", "min 4V，typ 4.5V，max 5V"),
        ("验收范围 3～6V", "验收区间 4V～5V", "验收区间 4V～5V"),
        ("≥3V且≤6V", "验收范围 4～5V", "验收范围 4～5V"),
        ("接触电阻≤5mΩ", "接触电阻≤4mΩ", "接触电阻≤4mΩ"),
        ("≥1e3mV", "≥1.1V", "≥1.1V"),
        ("最大值5mΩ，典型值3mΩ", "≤4mΩ", "≤4mΩ"),
    ],
)
def test_guaranteed_bounds_choose_only_an_original_source_value(user, standard, expected):
    result = compare_indicator_values(user, standard)
    assert result.adopted == expected
    assert result.manual_review_required is False
    assert result.status in {"equal", "stricter_user", "stricter_standard"}


@pytest.mark.parametrize(
    ("user", "standard"),
    [
        ("≤5mΩ", "≤4mA"),
        ("≤5mΩ", "≤4mohm"),
        ("≤5mΩ", "typ 3mΩ"),
        ("typ 3mΩ", "typ 3mΩ"),
        ("≥3V且≤5V", "≥4V且≤6V"),
        ("≥5N", "≤10N"),
        ("常温≤5mΩ", "试验后≤4mΩ"),
        ("≤5mΩ，振动10g", "≤4mΩ，振动20g"),
        ("常温≤5mΩ；低温≤8mΩ", "常温≤4mΩ；低温≤10mΩ"),
        ("A组 min 3V max 5V；B组 min 4V max 6V", "A组 min 4V max 5V；B组 min 3V max 6V"),
        ("min 6V, max 3V", "min 4V, max 5V"),
        ("≤5mΩ 或 ≥10mΩ", "≤4mΩ 或 ≥11mΩ"),
        ("-40～85℃", "-55～125℃"),
        ("≤5mΩ", "≤4mΩ，试验后不得损坏"),
        ("5V", "4V"),
        ("≤5g", "≤0.004kg"),
        ("min ≤5mΩ", "max ≤4mΩ"),
        ("typ 3～5mΩ", "max 4mΩ"),
        ("≤5mΩ，振动10g", "≤4mΩ，振动10g"),
        ("3～6V", "4～5V"),
        ("≤5mΩ/s", "≤4mΩ/s"),
    ],
)
def test_incomparable_or_incomplete_requirements_retain_user_and_require_review(user, standard):
    result = compare_indicator_values(user, standard)
    assert result.adopted == user
    assert result.manual_review_required is True
    assert result.status == "manual_review"
    assert "人工复核" in result.audit_note


def test_equivalent_units_and_boundaries_prefer_user_source():
    result = compare_indicator_values("≤500mV", "≤0.5V")
    assert result.adopted == "≤500mV"
    assert result.manual_review_required is False
    assert result.status == "equal"


def test_typical_reference_is_explicit_in_audit_even_when_maximum_is_comparable():
    result = compare_indicator_values("≤6mΩ", "max ≤5mΩ、typ 3mΩ")
    assert result.adopted == "max ≤5mΩ、typ 3mΩ"
    assert "typ" in result.audit_note
    assert "参考" in result.audit_note


def test_equal_guarantees_with_different_typical_references_prefer_user():
    result = compare_indicator_values("max 5mΩ，typ 4mΩ", "max 5mΩ，typ 3mΩ")
    assert result.adopted == "max 5mΩ，typ 4mΩ"
    assert result.status == "equal"
    assert result.manual_review_required is False


def test_no_user_value_uses_standard_guaranteed_value():
    result = compare_indicator_values("", "max 5mΩ、typ 3mΩ")
    assert result.adopted == "max 5mΩ、typ 3mΩ"
    assert result.manual_review_required is False
    assert result.status == "standard_only"


def test_no_user_value_does_not_promote_only_a_typical_value_to_guarantee():
    result = compare_indicator_values("", "typ 3mΩ")
    assert result.adopted == ""
    assert result.manual_review_required is True


def test_plain_equal_qualitative_requirements_do_not_need_numeric_inference():
    result = compare_indicator_values("不得漏液", "不得漏液")
    assert result.adopted == "不得漏液"
    assert result.manual_review_required is False
    assert result.status == "equal"


def test_user_only_and_empty_values_keep_original_policy():
    assert compare_indicator_values("≥20次", "").status == "user_only"
    assert compare_indicator_values("", "").status == "empty"
