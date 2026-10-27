from pathlib import Path

import pytest
from docx import Document

from jonhon_taskbook.fill import _fill_indicator_table
from jonhon_taskbook.indicator_identity import canonical_indicator_name


TEMPLATE = (Path(__file__).resolve().parents[1] / "src/service/jonhon_taskbook"
            / "resources/templates/rf_connector_taskbook.docx")


def _indicator_table(document):
    return next(table for table in document.tables
                if "用户要求" in "".join(cell.text for cell in table.rows[0].cells)
                and "拟采用" in "".join(cell.text for cell in table.rows[0].cells))


def test_rf_footnoted_template_rows_receive_values_without_duplicate_rows(tmp_path):
    document = Document(TEMPLATE)
    table = _indicator_table(document)
    original_count = len(table.rows)
    requirements = {
        "盐雾": "中性盐雾测试48h，镀层无腐蚀、起皮、生锈。",
        "工作温度": "-40℃～+85℃，全温度区间内电气、机械性能正常。",
        "振动": "频率10Hz～1000Hz扫频振动，振动时长4h。",
        "湿热": "温度85℃、湿度85%环境下持续放置96h。",
    }
    labels_before = [row.cells[0].text.strip() for row in table.rows]
    assert all(name + "※" in labels_before for name in requirements)

    written = _fill_indicator_table(document, [
        (name, value, "", value, "用户要求") for name, value in requirements.items()
    ])
    path = tmp_path / "rf-filled-footnotes.docx"
    document.save(path)
    result = _indicator_table(Document(path))
    assert written == 4
    assert len(result.rows) == original_count
    for name, value in requirements.items():
        rows = [row for row in result.rows
                if canonical_indicator_name(row.cells[0].text) == name]
        assert len(rows) == 1
        assert rows[0].cells[0].text == name + "※"
        assert rows[0].cells[1].text == value
        assert rows[0].cells[2].text == value


@pytest.mark.parametrize("label", ["盐雾※", "盐雾 ※ ", "盐雾 ※ ※ "])
def test_only_trailing_template_footnote_and_whitespace_are_ignored(label):
    assert canonical_indicator_name(label) == "盐雾"


@pytest.mark.parametrize("label", ["盐※雾", "盐雾★", "盐雾*", "盐雾※注", "盐雾（循环）"])
def test_other_indicator_name_details_are_not_erased(label):
    assert canonical_indicator_name(label) != "盐雾"
