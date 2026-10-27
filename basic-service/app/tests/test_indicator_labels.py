"""Indicator item labels omit separator colons without altering source values."""
from docx import Document
from docx.oxml.ns import qn

from jonhon_taskbook.postprocess import _normalize_indicator_table_formatting, postprocess


HEADERS = ["项目", "用户要求指标", "拟采用指标", "拟采用指标和试验的依据"]


def _indicator(document):
    table = document.add_table(rows=4, cols=4)
    for cell, text in zip(table.rows[0].cells, HEADERS):
        cell.text = text
    table.cell(1, 0).merge(table.cell(1, 3)).text = "环境性能："
    label = table.cell(2, 0).paragraphs[0]
    label.add_run("贮存温").bold = True
    label.add_run("度")
    label.add_run("：")
    label.add_run("  ")
    table.cell(2, 1).text = "贮存温度：-40℃～70℃；注意事项："
    table.cell(2, 2).text = "试验条件："
    table.cell(2, 3).text = "依据：产品规范第 4.1 条"
    table.cell(3, 0).text = "工作温度:"
    table.cell(3, 1).text = "5℃～70℃"
    return table


def test_indicator_label_colons_are_removed_across_runs_only():
    document = Document()
    table = _indicator(document)
    other_cells = [cell.text for cell in table.rows[2].cells[1:]]
    category_properties = [(node.tag, dict(node.attrib), node.text)
                           for node in table.cell(1, 0)._tc.tcPr.iter()]
    stats = {}

    _normalize_indicator_table_formatting(document._element.body, stats)

    assert table.cell(2, 0).text == "贮存温度  "
    assert table.cell(3, 0).text == "工作温度"
    assert table.cell(2, 0).paragraphs[0].runs[0].bold is True
    assert [cell.text for cell in table.rows[2].cells[1:]] == other_cells
    assert table.cell(1, 0).text == "环境性能："
    assert [(node.tag, dict(node.attrib), node.text)
            for node in table.cell(1, 0)._tc.tcPr.iter()] == category_properties
    assert stats["indicator_label_colons_removed"] == 2


def test_final_postprocess_only_changes_indicator_item_labels(tmp_path):
    document = Document()
    document.add_heading("技术要求", 1)
    paragraph = document.add_paragraph("贮存温度：")
    table = _indicator(document)
    source_table = document.add_table(rows=2, cols=2)
    source_table.cell(0, 0).text = "项目"
    source_table.cell(0, 1).text = "要求"
    source_table.cell(1, 0).text = "贮存温度："
    source_table.cell(1, 1).text = "试验条件：-40℃"
    path = tmp_path / "labels.docx"
    document.save(path)

    postprocess(str(path), preserve_template_guidance=True)
    result = Document(path)

    assert result.tables[0].cell(2, 0).text == "贮存温度  "
    assert result.tables[0].cell(3, 0).text == "工作温度"
    assert result.tables[0].cell(2, 1).text == table.cell(2, 1).text
    assert result.tables[0].cell(1, 0)._tc.tcPr.find(qn("w:gridSpan")).get(qn("w:val")) == "4"
    assert paragraph.text in [p.text for p in result.paragraphs]
    assert result.tables[1].cell(1, 0).text == "贮存温度："
    assert result.tables[1].cell(1, 1).text == "试验条件：-40℃"
