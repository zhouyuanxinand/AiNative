"""Reference sections keep their context through nested lists and tables."""
from docx import Document
from jonhon_taskbook.extractor import parse_doc
from jonhon_taskbook.fill import _collect_standards


def test_parent_reference_heading_applies_to_paragraphs_and_table_rows_only():
    doc = Document()
    doc.add_heading("执行标准", 1)
    doc.add_heading("产品标准", 2)
    doc.add_paragraph("接口依据：GB/T 11313.15-2018《SMA型射频同轴连接器》")
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "检验依据：GB/T 5095.2307-2021《屏蔽和滤波试验》"
    doc.add_heading("性能要求", 1)
    doc.add_paragraph("绝缘性能按GJB 360B的方法测量，试验后无击穿。")
    audit = {}
    lines = _collect_standards(doc, None, parse_doc(doc), [], [],
                              include_template=False, audit=audit)
    assert set(lines) == {"GB/T 11313.15-2018《SMA型射频同轴连接器》",
                          "GB/T 5095.2307-2021《屏蔽和滤波试验》"}
    assert {x["source"] for x in audit["source_references"]} == {"tech"}


def test_real_filter_standard_labels_all_reach_source_priority_merge():
    doc = Document()
    doc.add_heading("1.3 执行标准", 2)
    lines = ["通用基础标准：GB/T 11313.1-2013《射频连接器 第1部分：总规范》",
             "产品专用标准：GB/T 11313.15-2018《SMA型射频同轴连接器》",
             "滤波测试标准：GB/T 5095.2307-2021《屏蔽和滤波试验》",
             "可靠性试验标准：GJB 360B《电子及电气元件试验方法》"]
    for line in lines:
        doc.add_paragraph(line)
    audit = {}
    actual = _collect_standards(doc, None, parse_doc(doc), [], [],
                               include_template=False, audit=audit)
    assert set(actual) == {line.split("：", 1)[1] for line in lines}
    assert len(audit["source_references"]) == 4


def test_inline_body_in_next_heading_closes_reference_scope():
    doc = Document()
    doc.add_heading("1 执行标准", 1)
    doc.add_paragraph("接口依据：GB/T 11313.15-2018《SMA型射频同轴连接器》")
    doc.add_paragraph("2 检验依据：GB/T 5095.2307-2021《屏蔽和滤波试验》")
    doc.add_heading("2 性能要求：绝缘电阻≥1000MΩ。", 1)
    doc.add_paragraph("振动试验：GJB 360B 方法214，试验后无松动。")
    lines = _collect_standards(doc, None, parse_doc(doc), [], [],
                              include_template=False)
    assert set(lines) == {"GB/T 11313.15-2018《SMA型射频同轴连接器》",
                          "GB/T 5095.2307-2021《屏蔽和滤波试验》"}
