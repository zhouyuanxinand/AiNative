from tests.support.paths import APP_ROOT
from pathlib import Path

from docx import Document

from jonhon_taskbook.fill import _fill_indicator_table


TEMPLATE = (APP_ROOT / "src/service/jonhon_taskbook"
            / "resources/templates/filter_connector_taskbook.docx")


def test_generated_indicator_rows_do_not_inherit_template_keep_with_next(tmp_path):
    document = Document(TEMPLATE)
    table = next(table for table in document.tables
                 if "用户要求" in "".join(cell.text for cell in table.rows[0].cells))
    original_styles = document.styles.element.xml
    other_tables = [other._tbl.xml for other in document.tables if other._tbl is not table._tbl]
    category = next(row for row in table.rows if row.cells[0].text == "机械性能")
    header_before = table.rows[0]._tr.xml
    category_before = category._tr.xml
    vibration = next(row for row in table.rows if row.cells[0].text == "振动")
    assert vibration.cells[0].paragraphs[0].style.paragraph_format.keep_with_next is True
    vibration_text = "10Hz～2000Hz扫频振动，每个方向持续2h，试验后滤波性能满足要求。"
    new_text = "通电连续运行1000h，电容量变化不超过初始值的±10%。"

    _fill_indicator_table(document, [
        ("【机械性能】", "", "", "", ""),
        ("振动", vibration_text, "", vibration_text, "用户要求"),
        ("【环境性能】", "", "", "", ""),
        ("长期通电可靠性", new_text, "", new_text, "用户要求"),
    ])
    output = tmp_path / "indicator-pagination.docx"
    document.save(output)
    result = Document(output)
    result_table = next(table for table in result.tables
                        if "用户要求" in "".join(cell.text for cell in table.rows[0].cells))
    rows = {row.cells[0].text: row for row in result_table.rows}
    for name in ("振动", "冲击", "盐雾", "长期通电可靠性"):
        # Covers filled existing rows, untouched template rows and new rows.
        assert all(paragraph.paragraph_format.keep_with_next is False
                   for cell in rows[name].cells for paragraph in cell.paragraphs)
    assert rows["振动"].cells[1].text == vibration_text
    assert rows["长期通电可靠性"].cells[2].text == new_text
    assert rows["冲击"].cells[1].text == "\\"
    assert result.styles.element.xml == original_styles
    assert result_table.rows[0]._tr.xml == header_before
    assert rows["机械性能"]._tr.xml == category_before
    assert [other._tbl.xml for other in result.tables
            if other._tbl is not result_table._tbl] == other_tables
