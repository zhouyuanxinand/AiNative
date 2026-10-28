"""Development logic B56/B57 preserve originals without accepting new pollution."""

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import RGBColor
from jonhon_taskbook.delivery_gate import run_delivery_gate, scan_document_completeness
from jonhon_taskbook.qa_gate import QAGate


def _gate(template):
    return QAGate(
        {"block_if": {"red_text_count_gt": 0, "highlight_count_gt": 0, "change_record_data_rows_gt": 1,
                      "template_phrases_exist": ["请在此处", "适用时保留"], "forbidden_phrases_exist": ["历史项目示例"]}},
        {"preserve_template_guidance": True, "template_path": str(template)},
    )


def _red_marker(paragraph, color="FF0000"):
    run = paragraph.add_run("【人工填写】")
    run.font.color.rgb = RGBColor.from_string(color)
    return run


def test_existing_template_red_highlight_and_placeholder_are_preserved(tmp_path):
    template = tmp_path / "template.docx"
    document = Document()
    run = document.add_paragraph().add_run("请在此处填写历史项目示例")
    run.font.color.rgb = RGBColor(255, 0, 0)
    run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    document.save(template)
    _red_marker(document.paragraphs[0])
    result = _gate(template).check(document.element)
    assert result["blocked"] is False, result["block_reasons"]


def test_new_duplicate_template_text_does_not_gain_unlimited_exemptions(tmp_path):
    template = tmp_path / "template.docx"
    document = Document()
    document.add_paragraph("请在此处填写")
    document.save(template)
    document.add_paragraph("请在此处填写")
    result = _gate(template).check(document.element)
    assert result["blocked"] is True
    assert any("模板词" in reason for reason in result["block_reasons"])


def test_new_forbidden_text_is_blocked_even_if_phrase_exists_in_template(tmp_path):
    template = tmp_path / "template.docx"
    document = Document()
    document.add_paragraph("历史项目示例：原模板说明")
    document.save(template)
    document.add_paragraph("本项目沿用历史项目示例的数值")
    result = _gate(template).check(document.element)
    assert any("污染词" in reason for reason in result["block_reasons"])


def test_new_red_on_existing_black_template_text_is_not_preserved(tmp_path):
    template = tmp_path / "template.docx"
    document = Document()
    document.add_paragraph("模板原有正文")
    document.save(template)
    document.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 0, 0)
    result = _gate(template).check(document.element)
    assert result["red_count"] > 0
    assert result["blocked"] is True


def test_new_highlight_is_not_allowed_by_existing_highlight_count(tmp_path):
    template = tmp_path / "template.docx"
    document = Document()
    document.add_paragraph("原有高亮").runs[0].font.highlight_color = WD_COLOR_INDEX.YELLOW
    document.add_paragraph("原无高亮")
    document.save(template)
    document.paragraphs[0].runs[0].font.highlight_color = None
    document.paragraphs[1].runs[0].font.highlight_color = WD_COLOR_INDEX.YELLOW
    result = _gate(template).check(document.element)
    assert result["hl_count"] > 0
    assert result["blocked"] is True


def test_added_change_record_rows_are_blocked_against_actual_baseline(tmp_path):
    template = tmp_path / "template.docx"
    document = Document()
    table = document.add_table(rows=4, cols=2)
    table.cell(0, 0).text = "版本"
    table.cell(0, 1).text = "章条"
    document.save(template)
    assert _gate(template).check(document.element)["blocked"] is False
    table.add_row().cells[0].text = "未经确认的变更"
    assert any("变更记录" in reason for reason in _gate(template).check(document.element)["block_reasons"])


def test_preserve_without_readable_baseline_fails_closed(tmp_path):
    document = Document()
    document.add_paragraph("正文")
    result = _gate(tmp_path / "missing.docx").check(document.element)
    assert result["blocked"] is True
    assert any("模板基线" in reason for reason in result["block_reasons"])


def test_legal_marker_on_template_heading_does_not_trigger_template_residue(tmp_path):
    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"
    document = Document()
    document.add_heading("研制经费预算（适用时保留）", level=1)
    document.save(template)
    _red_marker(document.paragraphs[0])
    document.save(output)
    result = scan_document_completeness(str(output), [], preserve_template_guidance=True, template_path=str(template))
    assert not any(defect["code"] == "INCOMPLETE" for defect in result["defects"])
    assert result["manual_marker_count"] == 1
    assert result["invalid_manual_marker_count"] == 0


def test_italic_new_pollution_is_not_automatically_preserved(tmp_path):
    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"
    document = Document()
    document.add_paragraph("正常模板正文")
    document.save(template)
    document.add_paragraph("待人工复核，适用时保留").runs[0].italic = True
    document.save(output)
    result = scan_document_completeness(str(output), [], preserve_template_guidance=True, template_path=str(template))
    assert any(defect["code"] == "INCOMPLETE" for defect in result["defects"])


def test_delivery_duplicate_original_paragraph_is_not_globally_allowed(tmp_path):
    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"
    document = Document()
    document.add_paragraph("适用时保留")
    document.save(template)
    document.add_paragraph("适用时保留")
    document.save(output)
    result = scan_document_completeness(str(output), [], preserve_template_guidance=True, template_path=str(template))
    assert sum(defect["code"] == "INCOMPLETE" for defect in result["defects"]) == 1


def test_manual_marker_color_and_count_cover_body_and_tables_once(tmp_path):
    output = tmp_path / "output.docx"
    document = Document()
    _red_marker(document.add_paragraph("章节待填"))
    _red_marker(document.add_paragraph("错误颜色"), "000000")
    table = document.add_table(rows=1, cols=1)
    _red_marker(table.cell(0, 0).paragraphs[0])
    document.save(output)
    result = scan_document_completeness(str(output), [])
    assert result["manual_marker_count"] == 3
    assert result["invalid_manual_marker_count"] == 1
    assert result["invalid_manual_marker_locations"][0].startswith("paragraph#")


def test_marker_split_across_red_runs_is_still_correctly_colored(tmp_path):
    output = tmp_path / "output.docx"
    document = Document()
    paragraph = document.add_paragraph()
    for text in ("【人工", "填写】"):
        paragraph.add_run(text).font.color.rgb = RGBColor(255, 0, 0)
    document.save(output)
    result = scan_document_completeness(str(output), [])
    assert result["manual_marker_count"] == 1
    assert result["invalid_manual_marker_count"] == 0


def test_formal_delivery_preserves_original_template_with_valid_marker(tmp_path):
    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"
    document = Document()
    document.add_heading("研制经费预算（适用时保留）", level=1)
    document.save(template)
    _red_marker(document.paragraphs[0])
    document.save(output)
    result = run_delivery_gate(str(output), {
        "meta": {"formal_output": True, "preserve_unfilled_template": True, "template_path": str(template)},
        "delivery_gate": {"required_headings": [], "min_images": 0},
    }, {})
    assert not any(defect["code"] == "INCOMPLETE" for defect in result["scan"]["defects"])


def test_new_zone_is_not_exempted_just_because_heading_exists_in_template(tmp_path):
    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"
    document = Document()
    document.add_heading("研制经费预算", level=1)
    document.add_paragraph("原模板完整正文")
    document.save(template)
    document.save(output)
    zone = {"zone_type": "TEMPLATE_INSTRUCTION", "heading": "研制经费预算", "snippet": "新增待人工确认的输入",
            "location": "paragraph#new", "severity": "BLOCKER"}
    result = run_delivery_gate(str(output), {
        "meta": {"formal_output": False, "preserve_unfilled_template": True, "template_path": str(template)},
        "delivery_gate": {"required_headings": [], "min_images": 0},
        "zone_scan": {"zones": [zone], "blockers": [zone]},
    }, {})
    assert any(defect["code"] == "FILL_ZONE" and defect["location"] == "paragraph#new" for defect in result["defects"])
