"""7-22 C12/C50/C51: preserve source facts before comparing their values."""
import pytest
from docx import Document

from jonhon_taskbook.extractor import parse_doc
from jonhon_taskbook.fill import build_content
from jonhon_taskbook.indicator_facts import extract_indicator_facts
from jonhon_taskbook.indicator_comparison import compare_indicator_values
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks


def generate(tmp_path, document, *, role="performance_indicator", indicator_map=None):
    path = tmp_path / "requirements.docx"
    document.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    classification = {"source_blocks": blocks, "classifications": [
        {"source_id": block["id"], "category": role} for block in blocks]}
    profile = {"semantic_structures": {"performance_indicator": {"mode": "indicator_table"}},
               "indicator_sources": {"workbook": False, "reference_families": []},
               "indicator_map": indicator_map or {}}
    return build_content(profile, document, None, parse_doc(document), [], str(path),
                         requirement_classification=classification)["role:performance_indicator"]


def test_new_numeric_and_qualitative_indicators_use_source_when_spec_absent(tmp_path):
    document = Document()
    document.add_heading("核心电气技术指标", 1)
    capacitance = "寄生电容：≤3.5pF，容值一致性偏差≤±0.3pF；"
    document.add_paragraph(capacitance)
    document.add_heading("机械性能指标", 1)
    document.add_heading("抗扭转性能", 2)
    torsion = "抗扭转性能：可承受常规装配扭转力矩，内部无松动、无脱焊、无失效。"
    document.add_paragraph(torsion)
    document.add_heading("锁紧力矩", 2)
    torque = "锁紧力矩：0.8～1.15N·m；判据：无滑丝、脱扣。"
    document.add_paragraph(torque)
    content = generate(tmp_path, document)
    decisions = {item["indicator_name"]: item for item in content["indicator_comparison_audit"]}
    assert set(decisions) == {"寄生电容", "抗扭转性能", "锁紧力矩"}
    for name, source, category in [("寄生电容", capacitance, "电性能"),
                                   ("抗扭转性能", torsion, "机械性能"),
                                   ("锁紧力矩", torque, "机械性能")]:
        decision = decisions[name]
        assert decision["user_requirement"] == decision["adopted_requirement"] == source
        assert decision["category"] == category
        assert decision["basis"] == "用户要求"
        assert not decision["manual_review_required"]


def test_narrative_environment_compound_keeps_four_metrics_and_conditions(tmp_path):
    document = Document()
    document.add_heading("工作环境条件", 1)
    clauses = ["工作温度：-40℃～+85℃；", "存储温度：-55℃～+100℃；",
               "工作湿度：5%～95%RH（无凝露）；", "防护等级：IP65，防尘、防水、防油污侵入。"]
    document.add_paragraph("".join(clauses))
    content = generate(tmp_path, document, role="usage_environment",
                       indicator_map={"环境性能": [{"name": "工作温度"}]})
    facts = content["input_indicator_facts"]
    assert [f["indicator_name"] for f in facts] == ["工作温度", "存储温度", "工作湿度", "防护等级"]
    assert [f["source_value"] for f in facts] == clauses
    assert all(f["category"] == "环境性能" for f in facts)


def test_qualitative_paragraph_under_explicit_performance_heading_is_retained(tmp_path):
    document = Document()
    document.add_heading("电磁兼容要求", 1)
    clauses = ["产品应抑制传导干扰和辐射干扰。", "屏蔽结构应避免内外信号串扰。"]
    for text in clauses:
        document.add_paragraph(text)
    content = generate(tmp_path, document)
    assert [f["source_value"] for f in content["input_indicator_facts"]] == clauses
    rows = [r for r in content["indicator_rows"] if not r[0].startswith("【")]
    assert len(rows) == 1
    assert rows[0][1] == rows[0][3] == "\n".join(clauses)


def test_trial_method_and_tolerance_remain_attached_to_table_metric(tmp_path):
    document = Document()
    document.add_heading("电气性能", 1)
    table = document.add_table(rows=2, cols=5)
    for cell, text in zip(table.rows[0].cells, ["项目", "要求", "允许偏差", "试验方法", "试验条件"]):
        cell.text = text
    for cell, text in zip(table.rows[1].cells, ["寄生电容", "≤3.5pF", "≤±0.3pF", "按协议附录A测量", "常温"]):
        cell.text = text
    content = generate(tmp_path, document)
    value = content["input_indicator_facts"][0]["source_value"]
    assert "≤3.5pF" in value and "允许偏差：≤±0.3pF" in value
    assert "试验方法：按协议附录A测量" in value and "试验条件：常温" in value


def test_qualifier_and_broad_heading_do_not_become_indicators():
    classification = {"source_blocks": [{"id": "x", "type": "paragraph", "heading_text": "技术要求",
                     "text": "判据：试验后应正常工作。"}],
                     "classifications": [{"source_id": "x", "category": "performance_indicator"}]}
    assert extract_indicator_facts(classification, {}) == []


def _extract_one(text, heading, role, indicators=None):
    return extract_indicator_facts({"source_blocks": [{"id": "p", "type": "paragraph",
        "text": text, "heading_text": heading}],
        "classifications": [{"source_id": "p", "category": role}]}, indicators or {})


def test_test_equipment_and_acceptance_remain_with_their_metric():
    text = "盐雾：中性盐雾48h；试验设备：盐雾箱；合格判据：镀层无腐蚀。"
    facts = _extract_one(text, "环境性能", "performance_indicator")
    assert len(facts) == 1
    assert facts[0]["source_value"] == text
    assert facts[0]["indicator_name"] == "盐雾"


def test_modified_container_heading_is_not_an_indicator_identity():
    assert _extract_one("产品应满足以下约定。", "通用射频电气指标（通带性能）",
                        "performance_indicator") == []


def test_installation_fields_in_environment_narrative_are_not_new_metrics():
    text = "安装方式：板装穿墙式；使用部位：密闭机箱内部；安装尺寸：≤10mm。"
    assert _extract_one(text, "工作环境条件", "usage_environment") == []


@pytest.mark.parametrize("user,standard,status", [
    ("≤3.5pF", "≤0.003nF", "stricter_standard"),
    ("≥2μH", "≥0.003mH", "stricter_standard"),
    ("≤3.5pF", "≤3.5pH", "manual_review"),
])
def test_capacitance_and_inductance_comparison_respects_units(user, standard, status):
    assert compare_indicator_values(user, standard).status == status
