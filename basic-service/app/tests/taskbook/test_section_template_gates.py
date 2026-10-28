"""Chapter-based technical templates still require measured delivery evidence."""

import json
from pathlib import Path

import pytest
import yaml
from docx import Document
from docx.shared import RGBColor

from jonhon_taskbook.delivery_gate import run_delivery_gate
from jonhon_taskbook.fill import run_coverage_and_qa
from jonhon_taskbook.postprocess import postprocess
from jonhon_taskbook.semantic_integrity_gate import run_semantic_integrity_gate
from jonhon_taskbook.template_scanner import scan_template_tree
from jonhon_taskbook.template_variant_policy import (
    ROOT, allowed_organization_scopes, apply_template_variant_policy, load_template_variant_policy,
)
from pipeline_cli import _run_delivery_gate_stage


NO_BUDGET_POLICY = ROOT / "config/non_budget_template_variant_policy.yaml"
PROFILE = {"technical_requirements_mode": "sections", "delivery_gate": {
    "required_headings": ["绝缘电阻"], "min_indicator_rows": 0, "min_interface_fills": 0,
}}


def _save_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def section_artifact(tmp_path):
    source, output = (tmp_path / name for name in ("source.docx", "output.docx"))
    document = Document()
    document.add_heading("绝缘电阻", level=1)
    evidence = "施加DC 750V后，绝缘电阻不得小于47MΩ。"
    document.add_paragraph(evidence)
    document.save(source)
    document.save(output)
    postprocess(output)
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(yaml.safe_dump({"categories": {"insulation": {
        "target_heading_keywords": ["绝缘电阻"], "target_heading_level": 1,
        "target_integrity": "exact",
    }}}, allow_unicode=True), encoding="utf-8")
    slots = scan_template_tree(str(output))
    block = {"id": "source-insulation", "text": evidence, "heading_text": "绝缘电阻"}
    classification = {"source_blocks": [block], "classifications": [
        {"source_id": block["id"], "category": "insulation"},
    ]}
    plan = {"slots": slots, "source_blocks": [block], "decisions": [{
        "operation": "copy_exact", "source_ids": [block["id"]], "target_slot": slots[0]["id"],
    }]}
    assert run_coverage_and_qa(str(source), str(output), PROFILE)
    semantic = run_semantic_integrity_gate(
        output, plan, classification, mapping, require_complete_source_checks=True,
    )
    assert semantic["passed"]
    assert len(semantic["checked"]) == 1
    apply_template_variant_policy(Document(output), organization_scope="non_central_research",
                                  out_path=output, policy_path=NO_BUDGET_POLICY)
    _save_json(output.with_suffix(".standards_audit.json"), {"version_conflicts": []})
    _save_json(output.with_suffix(".process_rule_audit.json"), {"development_process": "改型II"})
    _save_json(output.with_suffix(".failure_mode_audit.json"), {
        "development_process": "改型II", "query_executed": False,
    })
    return source, output, plan, classification, mapping


def _delivery(output, classification):
    return _run_delivery_gate_stage(str(output), {"meta": {}}, PROFILE, classification)


def test_real_section_audits_replace_only_inapplicable_indicator_checks(section_artifact):
    _, output, _, classification, _ = section_artifact
    assert not output.with_suffix(".indicator_audit.json").exists()
    result = _delivery(output, classification)
    assert result["passed"], result["blockers"]
    assert result["pipeline_report"]["technical_requirements_mode"] == "sections"
    assert not output.with_suffix(".indicator_audit.json").exists()


@pytest.mark.parametrize("suffix,code", [
    (".semantic_integrity_gate.json", "SEMANTIC_INTEGRITY_AUDIT"),
    (".coverage_ledger.json", "SOURCE_COVERAGE_AUDIT"),
])
def test_section_delivery_blocks_missing_real_evidence(section_artifact, suffix, code):
    _, output, _, classification, _ = section_artifact
    output.with_suffix(suffix).unlink()
    result = _delivery(output, classification)
    assert not result["passed"]
    assert code in {blocker["code"] for blocker in result["blockers"]}


def test_section_delivery_rejects_audit_of_an_earlier_document(section_artifact):
    _, output, _, classification, _ = section_artifact
    document = Document(output)
    document.paragraphs[-1].text = "未通过核验的后续编辑。"
    document.save(output)
    result = _delivery(output, classification)
    assert "SEMANTIC_INTEGRITY_AUDIT" in {blocker["code"] for blocker in result["blockers"]}


def test_strict_semantic_gate_detects_classified_content_missing_from_route_plan(section_artifact):
    _, output, plan, classification, mapping = section_artifact
    plan["decisions"] = []
    semantic = run_semantic_integrity_gate(
        output, plan, classification, mapping, require_complete_source_checks=True,
    )
    assert not semantic["passed"]
    assert semantic["violations"][0]["code"] == "SOURCE_SEMANTIC_ROUTE_NOT_CHECKED"
    assert not _delivery(output, classification)["passed"]


def test_section_mode_does_not_relax_input_coverage(section_artifact):
    source, output, plan, classification, mapping = section_artifact
    document = Document(source)
    document.add_paragraph("接口必须具有独立的防反插设计。")
    document.save(source)
    assert not run_coverage_and_qa(str(source), str(output), PROFILE)
    # The first requirement is still correctly placed. The separate coverage
    # proof must catch the second requirement even when semantic checking passes.
    semantic = run_semantic_integrity_gate(
        output, plan, classification, mapping, require_complete_source_checks=True,
    )
    assert semantic["passed"]
    result = _delivery(output, classification)
    assert "SOURCE_COVERAGE_AUDIT" in {blocker["code"] for blocker in result["blockers"]}


def test_section_delivery_rejects_source_text_in_wrong_chapter(section_artifact):
    _, output, plan, classification, mapping = section_artifact
    document = Document(output)
    evidence = document.paragraphs[-1].text
    document.paragraphs[-1].text = "本章尚无适用内容。"
    document.add_heading("包装要求", level=1)
    document.add_paragraph(evidence)
    document.save(output)
    semantic = run_semantic_integrity_gate(
        output, plan, classification, mapping, require_complete_source_checks=True,
    )
    assert not semantic["passed"]
    assert semantic["violations"][0]["code"] == "SOURCE_EVIDENCE_MISSING_FROM_TARGET"
    result = _delivery(output, classification)
    assert "SEMANTIC_INTEGRITY_AUDIT" in {blocker["code"] for blocker in result["blockers"]}


def test_section_mode_keeps_other_qa_rules(section_artifact):
    source, output, _, _, _ = section_artifact
    document = Document(output)
    document.paragraphs[-1].runs[0].font.color.rgb = RGBColor(255, 0, 0)
    document.save(output)
    assert not run_coverage_and_qa(str(source), str(output), PROFILE)
    report = output.with_suffix(".qa_gate_report.md").read_text(encoding="utf-8")
    assert "残余红字" in report and "技术指标表缺失" not in report


def test_table_mode_still_requires_indicator_audit(section_artifact):
    _, output, _, _, _ = section_artifact
    result = run_delivery_gate(str(output), {"delivery_gate": PROFILE["delivery_gate"]}, {})
    assert "INDICATOR_AUDIT" in {blocker["code"] for blocker in result["blockers"]}


def test_empty_template_variant_groups_require_explicit_declaration(tmp_path):
    policy = tmp_path / "incomplete_policy.yaml"
    policy.write_text("fields: {}\nmutually_exclusive_groups: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mutually_exclusive_groups"):
        load_template_variant_policy(policy)
    assert set(allowed_organization_scopes(NO_BUDGET_POLICY)) == {
        "non_central_research", "central_research",
    }


def test_no_budget_policy_cannot_hide_existing_budget_sections(tmp_path):
    document = Document()
    document.add_heading("研制经费预算（适用于非中央研究院产品）", level=1)
    document.add_heading("研制经费预算及经济性分析（适用于中央研究院产品）", level=1)
    with pytest.raises(ValueError, match="实际模板不符"):
        apply_template_variant_policy(document, organization_scope="non_central_research",
                                      out_path=tmp_path / "out.docx", policy_path=NO_BUDGET_POLICY)
    assert len(document.paragraphs) == 2


def test_empty_successful_variant_audit_is_insufficient_without_controlled_policy(section_artifact):
    _, output, _, classification, _ = section_artifact
    _save_json(output.with_suffix(".template_variant_audit.json"), {
        "groups": [], "passed": True, "no_mutually_exclusive_sections": True,
    })
    result = _delivery(output, classification)
    assert "TEMPLATE_VARIANT_POLICY" in {blocker["code"] for blocker in result["blockers"]}
