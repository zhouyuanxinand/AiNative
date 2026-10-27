"""Final cleanup must not rewrite copied source data as template blanks."""

from docx import Document

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
    assert result.tables[1].cell(1, 1).text == "无"
