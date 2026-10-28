"""C50 source-only indicators retain pictured table rows and user clarifications."""
import base64
from io import BytesIO

from docx import Document
from jonhon_taskbook.fill import _fill_indicator_table, build_content, parse_doc
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks


def generate_dynamic(tmp_path, *, with_image=False, clarification=None):
    indicator = "自定义压接电阻"
    technical_path = tmp_path / "technical.docx"
    spec_path = tmp_path / "spec.docx"
    source = Document()
    source.add_heading("电气性能", 1)
    source_table = source.add_table(rows=2, cols=2)
    for cell, value in zip(source_table.rows[0].cells, ["项目", "要求"]):
        cell.text = value
    source_table.cell(1, 0).text = indicator
    source_table.cell(1, 1).text = "≤8mΩ"
    if with_image:
        source_table.cell(1, 1).paragraphs[0].add_run().add_picture(BytesIO(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5Wk3kAAAAASUVORK5CYII="
        )))
    source.save(technical_path)
    spec = Document()
    spec.add_paragraph("Q/JH 999-2026 产品规范")
    spec.add_heading("电气性能", 1)
    table = spec.add_table(rows=1, cols=3)
    for cell, value in zip(table.rows[0].cells, ["项目", "接触件规格", "要求"]):
        cell.text = value
    for values in [(indicator, "#20", "≤5mΩ"), (indicator, "#22D", "≤10mΩ")]:
        for cell, value in zip(table.add_row().cells, values):
            cell.text = value
    spec.save(spec_path)
    blocks = extract_source_blocks(str(technical_path), "tech")
    classification = {
        "source_blocks": blocks,
        "classifications": [{"source_id": block["id"], "category": "performance_indicator"} for block in blocks],
    }
    config = {
        "semantic_structures": {"performance_indicator": {"mode": "indicator_table"}},
        "indicator_sources": {"workbook": False, "reference_families": []},
        "indicators": {},
    }
    output = Document()
    target_table = output.add_table(rows=2, cols=5)
    for cell, value in zip(target_table.rows[0].cells, ["项目", "用户要求", "标准要求", "拟采用", "依据"]):
        cell.text = value
    target_table.cell(1, 0).text = "已有模板指标"
    content = build_content(
        config, source, spec, parse_doc(source), parse_doc(spec),
        str(technical_path), str(spec_path), template_doc=output,
        requirement_classification=classification,
        indicator_clarifications={indicator: clarification} if clarification else None,
    )["role:performance_indicator"]
    _fill_indicator_table(output, content["indicator_rows"])
    return content, target_table


def test_c50_pictured_source_table_still_adds_explicit_new_indicator(tmp_path):
    content, table = generate_dynamic(tmp_path, with_image=True)
    rows = [row for row in table.rows if row.cells[0].text == "自定义压接电阻"]
    assert len(rows) == 1
    assert rows[0].cells[1].text == "≤8mΩ"
    audit = content["dynamic_indicator_audit"]
    assert len(audit) == 1
    assert audit[0]["indicator_name"] == "自定义压接电阻"
    assert audit[0]["category"] == "电性能"
    assert audit[0]["user_source_ids"]
    assert audit[0]["manual_review_required"]  # 图不能使未澄清的两档规范被自动选择。


def test_c51_new_indicator_clarification_reaches_applicability_comparison(tmp_path):
    content, table = generate_dynamic(tmp_path, clarification="规格：#20")
    row = next(row for row in table.rows if row.cells[0].text == "自定义压接电阻")
    audit = content["dynamic_indicator_audit"][0]
    assert audit["numeric_status"] == "stricter_standard"
    assert not audit["manual_review_required"]
    assert row.cells[1].text == "≤8mΩ"
    assert "5mΩ" in row.cells[3].text
    assert "10mΩ" not in row.cells[3].text
    assert "Q/JH 999-2026" in row.cells[4].text
    assert "【人工填写】" not in row.cells[3].text
