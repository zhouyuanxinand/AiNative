"""Template structure must not masquerade as missing project engineering facts."""
from pathlib import Path

from docx import Document
from docx.shared import RGBColor
import yaml

from src.service.rd_platform.completion import build_completion_ledger


ROOT = Path(__file__).resolve().parents[2] / "src/service/jonhon_taskbook"
CONTEXT = {
    "product_type": "liquid_cooling_pipeline", "product_domain": "military",
    "development_process": "改型II", "organization_scope": "non_central_research",
    "cover_phase": "S", "product_series": "YLZJ",
}


def pipeline_ledger():
    return build_completion_ledger(
        ROOT / "resources/templates/liquid_cooling_pipeline_taskbook.docx",
        CONTEXT, [],
        profile=yaml.safe_load((ROOT / "liquid_cooling_pipeline_profile.yaml").read_text(encoding="utf-8")),
    )


def test_controlled_history_cells_are_deferred_to_history_rebuild():
    entries = [item for item in pipeline_ledger() if item.get("field_label") in {"A", "B", "C"}]
    assert entries
    assert all(item["status"] == "deferred_to_generation" for item in entries)
    assert all(item["generation_handler"] == "change_record" for item in entries)
    assert all(item["verification_required"] for item in entries)


def test_modification_and_domain_exclusions_use_generation_section_rules():
    ledger = pipeline_ledger()
    assert not any("失效模式" in item["semantic_path"] for item in ledger)
    assert not any("附 录A" in item["semantic_path"] or "产品运行场景识别" in item["semantic_path"] for item in ledger)
    assert not any("适航要求" in item["semantic_path"] for item in ledger)


def test_indicator_cells_are_pending_engine_output_not_evidence_ready():
    entries = [item for item in pipeline_ledger()
               if item["kind"] == "empty_table_cell" and item["title"] == "技术指标"]
    assert entries
    assert all(item["status"] == "deferred_to_generation" for item in entries)
    assert all(item["generation_handler"] == "indicator_table" for item in entries)
    assert all(not any(c.get("adopted") for c in item["candidates"]) for item in entries)


def test_pure_instruction_cleanup_does_not_discard_real_manual_fields(tmp_path):
    doc = Document()
    doc.add_heading("安全性要求", 1)
    instruction = doc.add_paragraph("（内容要求：根据具体情况填写产品安全要求。）")
    instruction.runs[0].font.color.rgb = RGBColor(255, 0, 0)
    doc.add_paragraph("【人工填写】防火温度要求")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "项目", "要求"
    table.cell(1, 0).text = "防火要求"
    path = tmp_path / "manual.docx"
    doc.save(path)
    entries = build_completion_ledger(path, {**CONTEXT, "development_process": "全新"}, [])
    guidance = next(item for item in entries if item["kind"] == "template_guidance")
    assert guidance["status"] == "deferred_to_generation"
    assert guidance["generation_handler"] == "template_instruction_cleanup"
    assert all(item["status"] == "blocked" for item in entries if item["kind"] in {"manual_marker", "empty_table_cell"})


def test_progress_dates_remain_missing_but_blank_remarks_are_not_required():
    entries = [item for item in pipeline_ledger() if item["title"] == "任务进度要求"]
    remarks = [item for item in entries if item.get("column_label") == "备注" and not item.get("template_text")]
    dates = [item for item in entries if item.get("column_label") in {"进度", "进度要求"}]
    assert remarks and dates
    assert all(item["status"] == "deferred_to_generation" for item in remarks)
    assert any(item["status"] == "blocked" for item in dates)
    assert any("20xx" in item.get("template_text", "").lower() and item["status"] == "blocked" for item in dates)


def test_template_is_never_changed_by_completion_inspection():
    path = ROOT / "resources/templates/liquid_cooling_pipeline_taskbook.docx"
    original = path.read_bytes()
    pipeline_ledger()
    assert path.read_bytes() == original


def test_document_title_and_compilation_basis_are_engine_owned_not_missing_facts():
    entries = [item for item in pipeline_ledger() if item["title"] in {"研制任务书", "任务书编制依据"}]
    assert entries
    assert all(item["status"] == "deferred_to_generation" for item in entries)
    assert {item["generation_handler"] for item in entries} == {"document_title", "compilation_basis"}


def test_red_engineering_text_is_not_assumed_to_be_disposable_instruction(tmp_path):
    doc = Document()
    doc.add_heading("防火性能", 1)
    paragraph = doc.add_paragraph("耐受温度不低于200℃。")
    paragraph.runs[0].font.color.rgb = RGBColor(255, 0, 0)
    path = tmp_path / "engineering.docx"
    doc.save(path)
    entry = build_completion_ledger(path, CONTEXT, [])[0]
    assert entry["status"] == "blocked"
    assert "generation_handler" not in entry


def test_failure_policy_matches_heading_not_mentions_or_display_number(tmp_path):
    doc = Document()
    doc.add_heading("初步的失效模式分析试验方法", 1)
    doc.add_paragraph("【人工填写】试验方法")
    doc.add_heading("5. 初步的失效模式分析", 1)
    doc.add_paragraph("【人工填写】本流程不适用")
    doc.add_heading("6. 任务进度要求", 1)
    doc.add_paragraph("【人工填写】实际日期")
    path = tmp_path / "process.docx"
    doc.save(path)
    entries = build_completion_ledger(path, CONTEXT, [])
    titles = {item["title"] for item in entries}
    assert "初步的失效模式分析" not in titles
    assert {"初步的失效模式分析试验方法", "任务进度要求"} <= titles
