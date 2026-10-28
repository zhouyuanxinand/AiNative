from tests.support.paths import APP_ROOT
from pathlib import Path

import pytest
from docx import Document
from jonhon_taskbook.extractor import parse_doc
from jonhon_taskbook.fill import _runtime_indicator_map, build_content
from jonhon_taskbook.indicator_profile_validator import validate_indicator_profile
from jonhon_taskbook.product_router import load_profile

PROFILE_DIR = APP_ROOT / "src/service/jonhon_taskbook"
PRODUCT_IDS = (
    "low_frequency_circular",
    "low_frequency_twist_pin",
    "high_speed_backplane",
    "high_speed_io",
    "end_contact_pogo",
    "end_contact_finger",
    "separation_connector",
    "watertight_connector",
)


@pytest.mark.parametrize("product_id", PRODUCT_IDS)
def test_candidate_profile_requires_controlled_source_evidence(product_id):
    profile_path = PROFILE_DIR / f"{product_id}_profile.yaml"
    profile, loaded_path, _ = load_profile("", explicit_profile=str(profile_path))
    validate_indicator_profile(profile, source=loaded_path)
    assert profile["profile_id"] == product_id

    blocks = [
        {
            "id": "current",
            "heading_text": "额定电流",
            "section": "技术指标 / 额定电流",
            "text": "额定电流：17 A。",
        },
        {
            "id": "weight",
            "heading_text": "重量",
            "section": "技术指标 / 重量",
            "text": "产品重量不大于50 g。",
        },
        {
            "id": "unsupported",
            "heading_text": "特殊指标",
            "section": "技术指标 / 特殊指标",
            "text": "频率范围：1 GHz；端面质量：无划伤；耐压深度：100 m。",
        },
    ]
    tech = Document()
    for block in blocks:
        tech.add_paragraph(block["text"])
    tech_paras = parse_doc(tech)
    classification = {
        "source_blocks": blocks,
        "classifications": [
            {"source_id": block["id"], "category": "performance_indicator"}
            for block in blocks
        ],
    }

    runtime = _runtime_indicator_map(profile, tech_paras, classification)
    names = {item["name"] for items in runtime.values() for item in items}
    assert "重量" in names  # 有原文证据时，受控 common 参考词表可以补充名称。
    assert not names.intersection({"频率范围", "端面质量", "耐压深度"})

    content = build_content(
        profile,
        tech,
        None,
        tech_paras,
        [],
        "",
        requirement_classification=classification,
    )
    rows = content["role:performance_indicator"]["indicator_rows"]
    source_rows = {row[0]: row for row in rows if not row[0].startswith("【")}
    assert set(source_rows) == {"额定电流", "重量", "频率范围", "端面质量", "耐压深度"}
    # C12/C50 retain explicit qualitative requirements as well as measurements.
    # This source has no electrical/mechanical/environmental parent, so its
    # new indicators need category confirmation, without becoming vocabulary.
    decisions = {row["indicator_name"]: row for row in content["role:performance_indicator"]["indicator_comparison_audit"]}
    for name in ("频率范围", "端面质量", "耐压深度"):
        assert source_rows[name][3] == "【人工填写】"
        assert decisions[name]["manual_review_required"] is True
        assert decisions[name]["status"] == "SOURCE_INDICATOR_ADDED"
    assert "耐压深度" not in source_rows["频率范围"][1]
    assert source_rows["端面质量"][1] == "无划伤；"
    assert decisions["端面质量"]["user_requirement"] == "端面质量：无划伤；"
    assert "端面质量" not in source_rows["耐压深度"][1]
    assert "17 A" in source_rows["额定电流"][1]
    assert "50 g" in source_rows["重量"][1]
    assert all(not row[2] for row in source_rows.values())

    # 相同正文若只是标准引用，不得补充参考指标或凭 Profile 词表生成要求。
    standards_only = {
        "source_blocks": blocks,
        "classifications": [
            {"source_id": block["id"], "category": "standards_reference"}
            for block in blocks
        ],
    }
    runtime_without_evidence = _runtime_indicator_map(
        profile, tech_paras, standards_only
    )
    assert "重量" not in {
        item["name"] for items in runtime_without_evidence.values() for item in items
    }
    without_evidence = build_content(
        profile,
        tech,
        None,
        tech_paras,
        [],
        "",
        requirement_classification=standards_only,
    )
    assert all(
        row[0].startswith("【")
        for row in without_evidence["role:performance_indicator"]["indicator_rows"]
    )
