"""Regress the annotated RF protocol using its original measured clauses."""
from tests.support.paths import APP_ROOT
import json
from pathlib import Path

import yaml
import pytest
from docx import Document

from jonhon_taskbook.business_value_gate import audit_indicator_values
from jonhon_taskbook.extractor import parse_doc
from jonhon_taskbook.fill import build_content
from jonhon_taskbook.indicator_facts import extract_indicator_facts
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks


PROFILE = APP_ROOT / "src/service/jonhon_taskbook/rf_standard_interface_profile.yaml"
EMC_REQUIREMENT = "产品具备良好的电磁屏蔽性能，可有效抑制射频信号泄露，抗外界电磁干扰，适配整机EMC电磁兼容设计要求，工作过程中无信号串扰、杂波干扰。"
CLAUSES = {
    "电气性能指标": [
        "（1）特性阻抗：标准50Ω±1Ω 或 75Ω±1Ω（按需匹配），全程阻抗均匀，无突变偏差；",
        "（2）工作频率：DC～6GHz（常规款），高频款可支持DC～18GHz，全频段内电气性能稳定；",
        "（3）电压驻波比（VSWR）：≤1.15（DC～3GHz），≤1.25（3GHz～18GHz），无异常驻波峰值；",
        "（4）插入损耗：≤0.1dB@3GHz，≤0.3dB@18GHz，信号传输损耗极低；",
        "（5）回波损耗：≥20dB@DC～3GHz，≥18dB@3GHz～18GHz；",
        "（6）绝缘电阻：≥1000MΩ（常态环境），介质绝缘性能优异；",
        "（7）接触电阻：内导体≤2mΩ，外导体≤1mΩ，接触导通性良好；",
        "（8）耐电压：常态下可承受1000V AC 50Hz耐压测试，无击穿、飞弧现象。",
    ],
    "机械性能指标": [
        "（1）插拔寿命：常规插拔≥1000次，高频使用款≥2000次，插拔后电气性能无衰减、结构无松动；",
        "（2）锁紧力矩：螺纹式连接器标准锁紧力矩0.5～1.2N·m，锁紧牢固、拆卸顺畅；",
        "（3）保持力：线缆与连接器连接牢固，轴向拉力≥50N，无脱落、松动、移位；",
        "（4）同轴度：内、外导体同轴偏差≤0.05mm，保证对接精度。",
    ],
    "环境工作条件": [
        "（1）工作温度：-40℃～+85℃，全温度区间内电气、机械性能正常，无性能衰减；",
        "（2）存储温度：-55℃～+100℃，长期存储无老化、失效、变形；",
        "（3）工作湿度：相对湿度5%～95%（无凝露），防潮防霉变；",
        "（4）防护等级：常规IP65，户外款可达IP67，有效防尘、防水、防油污侵入。",
    ],
    "6.3 电磁兼容要求": [EMC_REQUIREMENT],
    "可靠性测试要求": [
        "（1）高低温循环测试：经过-40℃～+85℃高低温循环100次（单次循环2h），产品结构完好，电气指标偏差≤5%；",
        "（2）湿热老化测试：温度85℃、湿度85%环境下持续放置96h，无锈蚀、绝缘老化、性能失效问题；",
        "（3）振动测试：频率10Hz～1000Hz扫频振动，振动时长4h，产品无松动、脱落，电气性能正常；",
        "（4）盐雾测试：中性盐雾测试48h，镀层无腐蚀、起皮、生锈，满足户外使用防腐要求；",
        "（5）长期工作可靠性：连续通电工作1000h无故障，信号传输稳定，满足设备长期运行需求。",
    ],
}


def _generate(tmp_path):
    document = Document()
    for heading, clauses in CLAUSES.items():
        document.add_heading(heading, level=1)
        for text in clauses:
            document.add_paragraph(text)
    document.add_heading("双方签字", level=1)
    document.add_paragraph("代表人签字：20260917")
    path = tmp_path / "requirements.docx"
    document.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    classification = {
        "source_blocks": blocks,
        "classifications": [
            {"source_id": b["id"], "category": "usage_environment" if "环境工作条件" in b.get("heading_text", "")
             else "reliability" if "可靠性" in b.get("heading_text", "") else "performance_indicator"}
            for b in blocks
        ],
    }
    # Completeness must survive an upstream missed body paragraph.
    classification["source_blocks"] = [b for b in blocks if "存储温度：" not in b.get("text", "")]
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    content = build_content(profile, document, None, parse_doc(document), [], str(path),
                            requirement_classification=classification)
    return content["role:performance_indicator"], document, classification, profile


def _save_output(tmp_path, decisions, facts):
    document = Document()
    table = document.add_table(rows=1, cols=5)
    for cell, label in zip(table.rows[0].cells, ("项目", "用户要求指标", "标准要求", "拟采用指标", "依据")):
        cell.text = label
    fields = ("indicator_name", "user_requirement", "standard_requirement", "adopted_requirement", "basis")
    for row in decisions:
        for cell, field in zip(table.add_row().cells, fields):
            cell.text = row.get("display_values", {}).get(field, row.get(field, ""))
    path = tmp_path / "result.docx"
    document.save(path)
    path.with_suffix(".indicator_audit.json").write_text(json.dumps({
        "input_indicator_facts": facts, "comparison_decisions": decisions,
    }, ensure_ascii=False), encoding="utf-8")
    return audit_indicator_values(path, persist=False)


def test_real_rf_clauses_are_individual_facts_across_narrative_categories(tmp_path):
    content, _, _, _ = _generate(tmp_path)
    rows = {row[0]: row for row in content["indicator_rows"] if not row[0].startswith("【")}
    assert len(rows) == 22
    assert len(content["input_indicator_facts"]) == 22
    assert rows["电磁兼容"][1] == rows["电磁兼容"][3] == EMC_REQUIREMENT
    assert not {"电气性能指标", "机械性能指标"} & rows.keys()
    for name, values in {
        "工作温度": ("-40℃", "+85℃"), "存储温度": ("-55℃", "+100℃"),
        "工作湿度": ("5%", "95%"), "防护等级": ("IP65", "IP67"),
        "盐雾": ("48h",), "机械寿命": ("1000次", "2000次"),
        "插入损耗": ("0.1dB", "0.3dB"), "长期工作可靠性": ("1000h",),
    }.items():
        assert all(value in rows[name][1] for value in values), (name, rows[name])
        assert rows[name][3] == rows[name][1]
    assert "回波损耗" not in rows["插入损耗"][1]
    result = _save_output(tmp_path, content["indicator_comparison_audit"], content["input_indicator_facts"])
    assert result["passed"], result["blockers"]


def test_gate_detects_source_fact_missing_from_both_ledger_rows_and_word(tmp_path):
    content, _, _, _ = _generate(tmp_path)
    decisions = [d for d in content["indicator_comparison_audit"] if d["indicator_name"] != "盐雾"]
    result = _save_output(tmp_path, decisions, content["input_indicator_facts"])
    assert not result["passed"]
    assert any(b["code"] == "MISSING_SOURCE_INDICATOR" and b["indicator"] == "盐雾" for b in result["blockers"])


def test_gate_detects_same_source_fact_reused_under_another_row_name(tmp_path):
    content, _, _, _ = _generate(tmp_path)
    decisions = content["indicator_comparison_audit"]
    decisions.append({**decisions[0], "indicator_name": "电气性能指标"})
    result = _save_output(tmp_path, decisions, content["input_indicator_facts"])
    assert not result["passed"]
    assert {"DUPLICATE_INDICATOR_FACT", "INDICATOR_FACT_IDENTITY_MISMATCH"} <= {b["code"] for b in result["blockers"]}


def test_styled_inline_measurement_and_unclassified_original_body_are_retained(tmp_path):
    document = Document()
    document.add_heading("环境工作条件", level=1)
    document.add_heading("工作温度：-40℃～+85℃", level=2)
    facts = extract_indicator_facts({"source_blocks": [], "classifications": []},
        {"环境性能": [{"name": "工作温度"}]}, source_document=document)
    assert [f["indicator_name"] for f in facts] == ["工作温度"]
    assert facts[0]["source_value"] == "工作温度：-40℃～+85℃"


@pytest.mark.parametrize("profile_name", ("rf_standard_interface", "rf_contact", "rf_hybrid"))
def test_rf_governed_qualitative_indicator_needs_no_number_or_colon(tmp_path, profile_name):
    document = Document()
    document.add_heading("6.3 电磁兼容要求", level=2)
    document.add_paragraph(EMC_REQUIREMENT)
    path = tmp_path / "electromagnetic-compatibility.docx"
    document.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    classification = {"source_blocks": blocks, "classifications": [
        {"source_id": block["id"], "category": "performance_indicator"} for block in blocks]}
    profile = yaml.safe_load(PROFILE.with_name(f"{profile_name}_profile.yaml").read_text(encoding="utf-8"))
    facts = extract_indicator_facts(classification, profile["indicator_map"], source_document=document)
    assert len(facts) == 1
    assert facts[0]["indicator_name"] == "电磁兼容"
    assert facts[0]["source_value"] == EMC_REQUIREMENT
    assert facts[0]["governed_name"]
    content = build_content(profile, document, None, parse_doc(document), [], str(path),
                            requirement_classification=classification)["role:performance_indicator"]
    rows = [row for row in content["indicator_rows"] if not row[0].startswith("【")]
    assert len(rows) == 1
    assert rows[0][0] == "电磁兼容"
    assert rows[0][1] == rows[0][3] == EMC_REQUIREMENT
    assert _save_output(tmp_path, content["indicator_comparison_audit"], facts)["passed"]


def test_table_row_conditions_scopes_and_units_stay_bound_to_each_measurement(tmp_path):
    document = Document()
    document.add_heading("电气性能", level=1)
    table = document.add_table(rows=1, cols=7)
    headers = ("项目", "试验条件", "适用型号", "环境", "状态", "指标", "单位")
    for cell, value in zip(table.rows[0].cells, headers):
        cell.text = value
    source_rows = (
        ("接触电阻", "常态", "SMA-A", "常温", "插合", "≤2", "mΩ"),
        ("接触电阻", "盐雾试验后", "SMA-B", "高湿", "插合", "≤5", "mΩ"),
    )
    for values in source_rows:
        for cell, value in zip(table.add_row().cells, values):
            cell.text = value
    path = tmp_path / "conditions.docx"
    document.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    classification = {"source_blocks": blocks, "classifications": [
        {"source_id": b["id"], "category": "performance_indicator"} for b in blocks]}
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    facts = extract_indicator_facts(classification, profile["indicator_map"], source_document=document)
    assert len(facts) == 2
    assert facts[0]["source_value"] == "试验条件：常态；适用型号：SMA-A；环境：常温；状态：插合；≤2；单位：mΩ"
    assert facts[1]["source_value"] == "试验条件：盐雾试验后；适用型号：SMA-B；环境：高湿；状态：插合；≤5；单位：mΩ"
    content = build_content(profile, document, None, parse_doc(document), [], str(path),
                            requirement_classification=classification)["role:performance_indicator"]
    row = next(row for row in content["indicator_rows"] if row[0] == "接触电阻")
    assert row[1] == "\n".join(fact["source_value"] for fact in facts)
    assert row[3] == row[1]
    assert len(content["indicator_comparison_audit"][0]["user_fact_ids"]) == 2
    assert _save_output(tmp_path, content["indicator_comparison_audit"], facts)["passed"]


def test_semicolon_acceptance_criteria_conditions_and_notes_remain_with_metric(tmp_path):
    document = Document()
    document.add_heading("可靠性测试要求", level=1)
    source = "盐雾测试：中性盐雾48h；判据：镀层无腐蚀、起皮、生锈；试验条件：温度35℃；备注：试验后2h内检查。"
    document.add_paragraph(source)
    path = tmp_path / "salt-spray.docx"
    document.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    classification = {"source_blocks": blocks, "classifications": [
        {"source_id": b["id"], "category": "reliability"} for b in blocks]}
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    facts = extract_indicator_facts(classification, profile["indicator_map"], source_document=document)
    assert len(facts) == 1
    assert facts[0]["indicator_name"] == "盐雾"
    assert facts[0]["source_value"] == source
    content = build_content(profile, document, None, parse_doc(document), [], str(path),
                            requirement_classification=classification)["role:performance_indicator"]
    row = next(row for row in content["indicator_rows"] if row[0] == "盐雾")
    assert row[1] == row[3] == "中性盐雾48h；判据：镀层无腐蚀、起皮、生锈；试验条件：温度35℃；备注：试验后2h内检查。"
    assert content["indicator_comparison_audit"][0]["user_requirement"] == source
