from pathlib import Path

import pytest
from openpyxl import Workbook

from jonhon_taskbook.failure_mode_matcher import match_failure_modes_with_audit


HEADERS = ["数据所属产品的产品名称", "所属型号", "故障描述", "故障原因", "设计改进措施"]
PRODUCT = "低频连接器-圆形低频"


def database(tmp_path, rows, *, intro=False):
    path = tmp_path / "failures.xlsx"
    book = Workbook()
    sheet = book.active
    if intro:
        sheet.title = "说明"
        sheet.append(["受控故障库使用说明"])
        sheet = book.create_sheet("现场故障信息导入")
    sheet.append(HEADERS)
    for model, description in rows:
        sheet.append([PRODUCT + "-插针", model, description, "接触件松动", "改进装配"])
    book.save(path)
    book.close()
    return path


def test_second_model_in_real_database_list_is_not_dropped(tmp_path):
    # Actual database row 88 lists these two distinct series in one cell.
    path = database(tmp_path, [("JY27467T25F14SN-H、JY27656T25F14PN-H", "插针故障")])
    records, audit = match_failure_modes_with_audit(PRODUCT, "JY27656", path)
    assert len(records) == audit["accepted_count"] == 1
    assert records[0]["product_series"] == "JY27467T25F14SN-H、JY27656T25F14PN-H"
    assert records[0]["matched_models"] == ["JY27656T25F14PN-H"]


@pytest.mark.parametrize("model,series", [("J5990-01", "J599"), ("J599LM-01", "J599L"),
                                          ("ICTS-BGA4720-01", "ICTS-BGA472")])
def test_series_prefix_does_not_extend_last_letter_or_number_group(tmp_path, model, series):
    records, audit = match_failure_modes_with_audit(PRODUCT, series, database(tmp_path, [(model, "失效")]))
    assert records == []
    assert audit["rejected_counts"]["series_mismatch"] == 1


def test_database_sheet_is_identified_by_schema_not_tab_position(tmp_path):
    records, audit = match_failure_modes_with_audit(PRODUCT, "ICG", database(tmp_path, [("ICG-08", "失效")], intro=True))
    assert len(records) == 1
    assert records[0]["source_sheet"] == "现场故障信息导入"


def test_export_wrapping_removed_but_quoted_source_words_and_lines_preserved(tmp_path):
    original = '"失效部位为“插针”，标记为"A"。\n第二行说明。"\n'
    records, _ = match_failure_modes_with_audit(PRODUCT, "ICG", database(tmp_path, [("ICG-08", original)]))
    assert records[0]["failure_mode"] == '失效部位为“插针”，标记为"A"。\n第二行说明。'


def test_approved_distinct_series_are_not_implicitly_aliased(tmp_path):
    path = database(tmp_path, [("J599/20FC04PNL5104G", "电容故障"), ("J599/21MTAE32PFNL1-01", "接地故障")])
    records, _ = match_failure_modes_with_audit(PRODUCT, "J599L", path)
    assert records == []
    records, _ = match_failure_modes_with_audit(PRODUCT, "J599", path)
    assert len(records) == 2


@pytest.mark.parametrize("model,series", [
    ("OTHER-01；ICG-08", "ICG"), ("OTHER-01\nICG-08", "ICG"),
    ("SMA-KY1/SMP-KY2", "SMP"), ("HDA/YBM26-01", "HDA"),
    ("J599/20FC04PNL5104G", "J599/20"), ("ＩＣＧ－08", "ICG"),
    ("J30J-9(2,5)、ICG-08", "J30J-9(2,5)"),
])
def test_model_lists_preserve_model_punctuation(tmp_path, model, series):
    records, _ = match_failure_modes_with_audit(PRODUCT, series, database(tmp_path, [(model, "失效")]))
    assert len(records) == 1


def test_duplicate_content_keeps_every_original_row_and_model(tmp_path):
    path = database(tmp_path, [("ICG-08", "同一失效"), ("ICG-09", "同一失效")])
    records, audit = match_failure_modes_with_audit(PRODUCT, "ICG", path)
    assert len(records) == 1
    assert [source["product_series"] for source in records[0]["source_records"]] == ["ICG-08", "ICG-09"]
    assert [source["source_row"] for source in records[0]["source_records"]] == [2, 3]
    assert audit["rejected_counts"]["duplicate"] == 1


def test_all_event_sheets_are_read_without_treating_dictionary_as_events(tmp_path):
    path = tmp_path / "multi.xlsx"
    book = Workbook()
    book.active.title = "故障分类词典"
    book.active.append(["密封失效"])
    for name in ["历史", "新增"]:
        sheet = book.create_sheet(name)
        sheet.append(HEADERS)
        sheet.append([PRODUCT + "-插针", "ICG-08", name + "故障", "原因", "措施"])
    book.save(path)
    book.close()
    records, audit = match_failure_modes_with_audit(PRODUCT, "ICG", path)
    assert {record["source_sheet"] for record in records} == {"历史", "新增"}
    assert audit["candidate_count"] == 2


def test_incomplete_source_remains_empty_and_marked_for_review(tmp_path):
    records, audit = match_failure_modes_with_audit(PRODUCT, "ICG", database(tmp_path, [("ICG-08", "")]))
    assert records[0]["failure_mode"] == ""
    assert records[0]["missing_fields"] == ["故障描述"]
    assert audit["human_review_required"] is True


def test_failure_writer_keeps_explicit_line_breaks(tmp_path):
    from docx import Document
    from docx.oxml.ns import qn
    from jonhon_taskbook.fill import _fill_failure_mode_table

    document = Document()
    table = document.add_table(rows=2, cols=5)
    for cell, name in zip(table.rows[0].cells, ["数据所属产品", "失效部位", "失效模式", "失效分析", "可靠性设计方法"]):
        cell.text = name
    _fill_failure_mode_table(document, [{"product_name": PRODUCT,
        "failure_mode": '第一项：标记"A"。\n第二项：脱落。', "failure_analysis": "原因1\n原因2"}])
    path = tmp_path / "failure.docx"
    document.save(path)
    result = Document(path).tables[0]
    assert result.cell(1, 2).text == '第一项：标记"A"。\n第二项：脱落。'
    # A literal newline in w:t is collapsed by Word; w:br carries the visible
    # line break when the generated document is rendered.
    assert len(result.cell(1, 2)._tc.findall('.//' + qn('w:br'))) == 1
