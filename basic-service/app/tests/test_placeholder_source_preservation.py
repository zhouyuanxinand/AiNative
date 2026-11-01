"""Final cleanup must not rewrite copied source data as template blanks."""

from docx import Document
from docx.oxml.ns import qn

from jonhon_taskbook.placeholder_cleanup import final_placeholder_sweep_docx


def _barcode_table(document):
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "序号"
    table.cell(0, 1).text = "表示方法"
    table.cell(1, 0).text = "..."
    table.cell(1, 1).text = "00Y00Z..."
    return table


def test_copied_source_table_keeps_literal_ellipsis_while_template_blank_is_cleaned(tmp_path):
    source = tmp_path / "requirement.docx"
    source_doc = Document()
    _barcode_table(source_doc)
    source_doc.save(source)

    output = tmp_path / "taskbook.docx"
    output_doc = Document()
    original_table = _barcode_table(output_doc)
    original_table.style = "Table Grid"  # Presentation may change after copy.
    placeholder_table = output_doc.add_table(rows=2, cols=2)
    placeholder_table.cell(0, 0).text = "项目"
    placeholder_table.cell(0, 1).text = "值"
    placeholder_table.cell(1, 0).text = "型号"
    placeholder_table.cell(1, 1).text = "..."
    output_doc.save(output)

    changed = final_placeholder_sweep_docx(output, source_paths=[source])
    result = Document(output)
    assert changed == 1
    assert result.tables[0].cell(1, 0).text == "..."
    assert result.tables[0].cell(1, 1).text == "00Y00Z..."
    assert result.tables[1].cell(1, 1).text == "【人工填写】"


def test_missing_template_prose_is_not_asserted_to_have_no_requirements(tmp_path):
    output = tmp_path / "taskbook.docx"
    document = Document()
    document.add_heading("使用环境和部位", 2)
    paragraph = document.add_paragraph("……")
    paragraph.paragraph_format.keep_with_next = True
    document.add_heading("环境适应性", 2)
    document.add_paragraph("工作温度5℃～70℃。")
    document.add_paragraph("无")  # An explicit existing statement is not a placeholder.
    document.save(output)

    assert final_placeholder_sweep_docx(output) == 1
    result = Document(output)
    assert result.paragraphs[1].text == "【人工填写】"
    assert result.paragraphs[1].paragraph_format.keep_with_next is True
    assert result.paragraphs[3].text == "工作温度5℃～70℃。"
    assert result.paragraphs[4].text == "无"
    marker = result.paragraphs[1].runs[0]
    assert marker._r.find(qn("w:rPr")).find(qn("w:color")).get(qn("w:val")) == "FF0000"
    assert marker.bold is True
    assert final_placeholder_sweep_docx(output) == 0


def test_partial_template_prose_retains_context_around_missing_value(tmp_path):
    output = tmp_path / "taskbook.docx"
    document = Document()
    document.add_paragraph("使用部位：……")
    document.add_paragraph("项目承担单位为 XX，具体职责待确认。")
    document.save(output)

    assert final_placeholder_sweep_docx(output) == 2
    result = Document(output)
    assert result.paragraphs[0].text == "使用部位：【人工填写】"
    assert result.paragraphs[1].text == "项目承担单位为 【人工填写】，具体职责待确认。"


def test_partial_placeholder_preserves_scientific_notation_in_surrounding_runs(tmp_path):
    output = tmp_path / "taskbook.docx"
    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("使用部位：XX；泄漏率 10")
    paragraph.add_run("-6").font.superscript = True
    paragraph.add_run(" Pa.m")
    paragraph.add_run("3").font.superscript = True
    paragraph.add_run("/s")
    document.save(output)

    assert final_placeholder_sweep_docx(output) == 1
    result = Document(output).paragraphs[0]
    assert result.text == "使用部位：【人工填写】；泄漏率 10-6 Pa.m3/s"
    assert "".join(run.text for run in result.runs if run.font.superscript) == "-63"
    marker = next(run for run in result.runs if "【人工填写】" in run.text)
    assert marker.font.superscript is not True
