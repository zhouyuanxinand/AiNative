"""Manual-review markers use the same indicator identities as the value ledger."""
import json

import pytest

from jonhon_taskbook.delivery_gate import _manual_review_gate_findings


def findings(expected, actual, **scan_fields):
    audit = {
        "manual_review_required": [{"indicator_name": name} for name in expected],
        "input_canonical_names": ["介质耐电压"],
        "output_canonical_names": ["介质耐电压"],
    }
    return _manual_review_gate_findings(
        {"manual_indicator_names": actual, **scan_fields}, audit
    )


@pytest.mark.parametrize("ledger,display", [
    ("介质耐电压", "耐电压"),
    ("耐电压", "介质耐电压"),
    ("机械寿命", "插拔寿命"),
])
def test_controlled_template_alias_is_the_same_manual_review_indicator(ledger, display):
    defects, warnings, manual_only = findings([ledger], [display])
    assert defects == []
    assert manual_only
    assert warnings == ["1 indicator(s) require human input and are visibly marked."]


@pytest.mark.parametrize("actual,expected_codes", [
    ([], {"MISSING_MANUAL_FILL_MARKER"}),
    (["绝缘电阻"], {"MISSING_MANUAL_FILL_MARKER", "UNEXPECTED_MANUAL_FILL_MARKER"}),
    (["耐电压", "介质耐电压"], {"UNEXPECTED_MANUAL_FILL_MARKER"}),
])
def test_missing_wrong_or_duplicate_marker_still_blocks(actual, expected_codes):
    defects, warnings, _ = findings(["介质耐电压"], actual)
    assert {item["code"] for item in defects} == expected_codes
    assert warnings == []


def test_alias_does_not_bypass_marker_style_validation():
    defects, warnings, _ = findings(["介质耐电压"], ["耐电压"], invalid_manual_marker_count=1)
    assert {item["code"] for item in defects} == {"INVALID_MANUAL_FILL_MARKER_STYLE"}
    assert warnings == []


def test_alias_matching_retains_the_required_number_of_rows():
    defects, warnings, _ = findings(["介质耐电压", "耐电压"], ["耐电压"])
    assert [item["code"] for item in defects] == ["MISSING_MANUAL_FILL_MARKER"]
    assert json.loads(defects[0]["text"]) == ["介质耐电压"]
    assert warnings == []
