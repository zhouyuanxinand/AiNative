"""Real system taskbooks keep their native history columns through delivery."""
from pathlib import Path

import pytest
import yaml
from docx import Document
from openpyxl import Workbook

from jonhon_taskbook import failure_database
from jonhon_taskbook.delivery_gate import scan_document_completeness
from jonhon_taskbook.failure_database import FailureDatabase
from jonhon_taskbook.failure_table_schema import has_ordered_failure_fields, is_failure_table
from jonhon_taskbook.fill import fill, run_coverage_and_qa, _find_failure_mode_table
from jonhon_taskbook.postprocess import postprocess
from jonhon_taskbook.semantic_integrity_gate import run_semantic_integrity_gate
from jonhon_taskbook.semantic_orchestrator import (
    extract_source_blocks, extract_template_slots, _backfill_classified_routes, apply_semantic_plan,
)
from jonhon_taskbook.template_registry import resolve_template_selection
from pipeline_cli import _run_delivery_gate_stage


SYSTEM_HEADERS = ["数据所属产品名称", "失效部位", "失效模式", "失效分析", "可靠性设计方法"]


@pytest.mark.parametrize("headers", [
    SYSTEM_HEADERS,
    ["数据所属产品的产品名称", "失效部位", "失效模式（故障现象）", "失效分析", "可靠性设计方法（设计改进措施）"],
    ["产品型号", "故障部位", "故障现象", "失效机理", "预防措施"],
])
def test_semantic_history_headers_are_compatible(headers):
    assert is_failure_table(headers)
    assert has_ordered_failure_fields(headers)


@pytest.mark.parametrize("mutation", ["missing_identity", "missing_location", "missing_mode", "missing_analysis", "missing_method", "swapped", "extra", "merged_body"])
def test_history_schema_rejects_missing_duplicate_reordered_or_merged_fields(tmp_path, mutation):
    headers = list(SYSTEM_HEADERS)
    field_names = ("identity", "location", "mode", "analysis", "method")
    if mutation.startswith("missing_"):
        headers[field_names.index(mutation.removeprefix("missing_"))] = "待确认字段"
    elif mutation == "swapped":
        headers[3], headers[4] = headers[4], headers[3]
    elif mutation == "extra":
        headers.append("可靠性设计方法")
    document = Document()
    table = document.add_table(rows=2, cols=len(headers))
    for cell, header in zip(table.rows[0].cells, headers):
        cell.text = header
    if mutation == "merged_body":
        table.cell(1, 3).merge(table.cell(1, 4))
    output = tmp_path / "schema.docx"
    document.save(output)
    scan = scan_document_completeness(str(output), [])
    assert "FAILURE_TABLE_SCHEMA" in {defect["code"] for defect in scan["defects"]}


def test_potential_fmea_is_not_a_history_table():
    headers = ["序号", "可能发生的失效模式", "失效模式机理", "失效模式后果/影响", "可考虑的解决办法"]
    assert not is_failure_table(headers)
    assert not has_ordered_failure_fields(headers)


def test_real_system_template_history_passes_final_delivery_with_causes_intact(tmp_path, monkeypatch):
    selected = resolve_template_selection("mounting_frame", "military")
    profile = yaml.safe_load(Path(selected.profile_path).read_text(encoding="utf-8"))
    seed = tmp_path / "failure-seed.xlsx"
    workbook = Workbook()
    workbook.active.append(["数据所属产品的产品名称", "所属型号", "故障描述", "故障原因", "设计改进措施"])
    workbook.active.append(["安装架-支撑件", "TEST-01", "固定件脱落", "固定结构不足\n局部应力集中", "增加限位\n完成装配验证"])
    workbook.save(seed)
    workbook.close()
    database = FailureDatabase(tmp_path / "failures.sqlite3", seed_path=seed)
    monkeypatch.setattr(failure_database, "get_failure_database", lambda: database)

    tech, spec, output = (tmp_path / filename for filename in ("tech.docx", "spec.docx", "output.docx"))
    document = Document()
    # Real source text replaces the template's blank illustration guidance;
    # missing figures remain subject to the ordinary document quality gate.
    requirements = {
        "insulation_resistance": ("绝缘电阻", "施加DC 750V后，绝缘电阻不得小于47MΩ。"),
        "product_composition": ("产品组成", "安装架由框架、支撑件和固定件组成。"),
        "vibration": ("振动", "安装架应承受50Hz振动30分钟，试验后固定件不得松脱。"),
    }
    categories_by_heading = {}
    for category, (heading, text) in requirements.items():
        document.add_heading(heading, 1)
        document.add_paragraph(text)
        categories_by_heading[heading] = category
    document.save(tech)
    Document().save(spec)
    blocks = extract_source_blocks(str(tech), "tech")
    classification = {"source_blocks": blocks, "classifications": [
        {"source_id": block["id"], "category": categories_by_heading[block["heading_text"]], "confidence": 1.0}
        for block in blocks
    ]}
    slots = extract_template_slots(selected.template_path)
    decisions, _ = _backfill_classified_routes([], slots, blocks, classification, selected.category_mapping_path)
    plan = {"slots": slots, "source_blocks": blocks, "decisions": decisions}
    fill(str(tech), str(spec), selected.template_path, str(output), selected.profile_path,
         finalize=False, requirement_classification=classification, category_mapping_path=selected.category_mapping_path,
         controlled_product_label=selected.product_type_label, controlled_product_domain="military",
         development_process="改型I", product_series="TEST", organization_scope="non_central_research")
    assert apply_semantic_plan(str(output), plan, only_empty=True)["passed"]
    postprocess(output, preserve_template_guidance=True, selected_product_domain="military")
    assert run_coverage_and_qa(str(tech), str(output), profile, preserve_template_guidance=True,
                               template_path=selected.template_path, selected_product_domain="military")
    semantic = run_semantic_integrity_gate(output, plan, classification, selected.category_mapping_path,
                                         require_complete_source_checks=True)
    assert semantic["passed"], semantic["violations"]
    gate = _run_delivery_gate_stage(str(output), {"meta": {
        "preserve_unfilled_template": True, "template_path": selected.template_path,
    }}, profile, classification)
    assert gate["passed"], gate["blockers"]
    history = _find_failure_mode_table(Document(output))
    assert [cell.text for cell in history.rows[0].cells] == SYSTEM_HEADERS
    assert len(history.rows[1].cells) == 5
    assert history.cell(1, 3).text == "固定结构不足\n局部应力集中"
    assert history.cell(1, 4).text == "增加限位\n完成装配验证"
