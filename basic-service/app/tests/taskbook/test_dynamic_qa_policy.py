"""Published QA rules must govern the actual coverage/QA stage."""

import yaml
from docx import Document
from docx.shared import RGBColor
from jonhon_taskbook import qa_policy
from jonhon_taskbook.fill import run_coverage_and_qa


def _document_pair(tmp_path):
    source = tmp_path / "source.docx"
    output = tmp_path / "output.docx"
    doc = Document()
    doc.add_paragraph("本产品应满足本次设计输入的技术要求。")
    doc.save(source)
    doc.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 0, 0)
    table = doc.add_table(rows=2, cols=4)
    for cell, text in zip(table.rows[0].cells, ("项目", "用户要求", "拟采用指标", "依据")):
        cell.text = text
    for cell, text in zip(table.rows[1].cells, ("工作温度", "20 ℃", "20 ℃", "设计输入")):
        cell.text = text
    doc.save(output)
    return source, output


def test_profile_red_threshold_changes_actual_coverage_qa_verdict(tmp_path):
    source, output = _document_pair(tmp_path)
    assert not run_coverage_and_qa(str(source), str(output), {})
    profile = {"qa_gate": {"block_if": {"red_text_count_gt": 1}}}
    assert run_coverage_and_qa(str(source), str(output), profile)


def test_profile_critical_evidence_cannot_be_erased_by_common_qa_override(tmp_path):
    source, output = _document_pair(tmp_path)
    profile = {
        "qa_profile": {"required_phrases_all": ["来源要求的专项验证"]},
        "qa_gate": {"block_if": {"red_text_count_gt": 1, "required_phrases_all": []}},
    }
    assert not run_coverage_and_qa(str(source), str(output), profile)
    assert "来源要求的专项验证" in output.with_suffix(".qa_gate_report.md").read_text("utf-8")


def test_saved_common_rule_changes_actual_gate_without_restart(tmp_path, monkeypatch):
    source, output = _document_pair(tmp_path)
    policy_path = tmp_path / "qa_gate.yaml"
    policy = yaml.safe_load(qa_policy.DEFAULT_POLICY_PATH.read_text("utf-8"))
    policy_path.write_text(yaml.safe_dump(policy, allow_unicode=True), "utf-8")
    monkeypatch.setattr(qa_policy, "DEFAULT_POLICY_PATH", policy_path)
    assert not run_coverage_and_qa(str(source), str(output), {})

    policy["block_if"]["red_text_count_gt"] = 1
    policy_path.write_text(yaml.safe_dump(policy, allow_unicode=True), "utf-8")
    assert run_coverage_and_qa(str(source), str(output), {})

    policy["block_if"]["red_text_count_gt"] = 0
    policy_path.write_text(yaml.safe_dump(policy, allow_unicode=True), "utf-8")
    assert not run_coverage_and_qa(str(source), str(output), {})


def test_profile_override_and_domain_flags_share_one_policy(tmp_path):
    policy_path = tmp_path / "qa_gate.yaml"
    policy_path.write_text("block_if:\n  red_text_count_gt: 0\nwarn_if: {}\n", "utf-8")
    profile = {
        "qa_gate": {"block_if": {"red_text_count_gt": 2, "required_figure_captions": []}},
        "qa_profile": {"required_figure_captions": ["图1 接口示意图"]},
    }
    rules, flags, _ = qa_policy.load_configured_qa_policy(
        profile, preserve_template_guidance=False,
        selected_product_domain="civil_aviation", config_path=policy_path,
    )
    assert rules["block_if"]["red_text_count_gt"] == 2
    assert rules["block_if"]["required_figure_captions"] == ["图1 接口示意图"]
    assert flags["is_civil_aircraft"] is True
    assert profile["qa_gate"]["block_if"]["required_figure_captions"] == []


def test_format_relaxation_does_not_bypass_source_coverage(tmp_path):
    source, output = _document_pair(tmp_path)
    doc = Document(source)
    doc.add_paragraph("本次必须完整传递的接口防反插设计要求。")
    doc.save(source)
    profile = {"qa_gate": {"block_if": {"red_text_count_gt": 1}}}
    assert not run_coverage_and_qa(str(source), str(output), profile)
    assert "输入覆盖率未通过" in output.with_suffix(".qa_gate_report.md").read_text("utf-8")
