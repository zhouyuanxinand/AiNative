"""A two-column technical specification is an indicator source, not prose."""

from pathlib import Path

import yaml
from docx import Document
from jonhon_taskbook.extractor import parse_doc
from jonhon_taskbook.fill import build_content
from jonhon_taskbook.indicator_facts import extract_indicator_facts
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks

PROFILE = Path(__file__).resolve().parents[1] / "src/service/jonhon_taskbook/liquid_cooling_pipeline_profile.yaml"


def _case(tmp_path):
    source = tmp_path / "requirements.docx"
    document = Document()
    document.add_heading("技术规格", level=1)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "技术特性类型"
    table.cell(0, 1).text = "特性描述"
    values = (
        ("工作压力", "0.3MPa"),
        ("环境温度", "5℃~42℃"),
        ("工作介质", "纯水、PG25"),
        ("流量", "0.8L/min（串联）"),
        ("组件流阻", "15kPa±8%@0.8L/min@去离子水（包含快接头）"),
        ("产品重量", "冷板重量（包含支架和紧固件）＜650g"),
        ("散热方式", "被动"),
        ("冷板材质", "紫铜T2"),
        ("快接头选型", "红色插座/UQD04-Z03RSSJE；蓝色插座/UQD04-Z03BSSJE"),
        ("硅脂型号", "迈图MT7000-A"),
        ("安装方案", "待设计确认"),
    )
    for label, value in values:
        table.add_row().cells[0].text = label
        table.rows[-1].cells[1].text = value
    document.add_heading("出厂测试结果", level=1)
    result = document.add_table(rows=1, cols=2)
    result.cell(0, 0).text = "技术特性类型"
    result.cell(0, 1).text = "特性描述"
    result.add_row().cells[0].text = "工作压力"
    result.rows[-1].cells[1].text = "0.27MPa（历史实测）"
    document.save(source)
    blocks = extract_source_blocks(str(source), "tech")
    classification = {
        "source_blocks": blocks,
        "classifications": [
            {
                "source_id": block["id"],
                "category": "testability" if "出厂测试结果" in block.get("heading_text", "")
                else "performance_indicator",
            }
            for block in blocks
        ],
    }
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    return source, document, classification, profile, dict(values)


def test_feature_description_table_keeps_each_value_and_ignores_test_results(tmp_path):
    source, document, classification, profile, expected = _case(tmp_path)
    facts = extract_indicator_facts(
        classification, profile["indicator_map"], source_document=document,
    )
    actual = {fact["source_label"]: fact["source_value"] for fact in facts}
    assert actual == expected
    assert all(fact["is_table"] for fact in facts)

    content = build_content(
        profile, document, None, parse_doc(document), [], str(source),
        requirement_classification=classification,
    )["role:performance_indicator"]
    rows = {row[0]: row for row in content["indicator_rows"] if not row[0].startswith("【")}
    target_names = {"组件流阻": "流阻", "产品重量": "重量"}
    for source_label, value in expected.items():
        row = rows[target_names.get(source_label, source_label)]
        assert row[1] == value
        assert "历史实测" not in row[1]
    assert "最大工作压力" not in rows
    for source_label in (
        "工作压力", "组件流阻", "流量", "产品重量", "散热方式",
        "冷板材质", "快接头选型", "硅脂型号",
    ):
        assert rows[target_names.get(source_label, source_label)][3] == expected[source_label]
    assert rows["安装方案"][3] == "【人工填写】"


def test_feature_description_header_requires_a_value_column_and_performance_role(tmp_path):
    _, document, classification, profile, expected = _case(tmp_path)
    for assignment in classification["classifications"]:
        assignment["category"] = "testability"
    facts = extract_indicator_facts(
        classification, profile["indicator_map"], source_document=document,
    )
    assert not {fact["source_label"] for fact in facts} & expected.keys()

    document.tables[0].cell(0, 1).text = "备注"
    for block, assignment in zip(classification["source_blocks"], classification["classifications"]):
        assignment["category"] = (
            "testability" if "出厂测试结果" in block.get("heading_text", "")
            else "performance_indicator"
        )
    facts = extract_indicator_facts(
        classification, profile["indicator_map"], source_document=document,
    )
    assert not {fact["source_label"] for fact in facts} & expected.keys()


def test_historical_result_caption_cannot_be_an_indicator_value(tmp_path):
    source = tmp_path / "historical-results.docx"
    document = Document()
    document.add_heading("测试设备及测试结果", level=1)
    document.add_heading("流阻", level=2)
    document.add_paragraph("不同流量下流阻结果：")
    document.add_paragraph("流阻：≤15kPa（设计验收要求）")
    document.save(source)
    blocks = extract_source_blocks(str(source), "tech")
    classification = {
        "source_blocks": blocks,
        "classifications": [
            {"source_id": block["id"], "category": "performance_indicator"}
            for block in blocks
        ],
    }
    facts = extract_indicator_facts(
        classification, {"密封性能": [{"name": "流阻"}]}, source_document=document,
    )
    assert [fact["source_value"] for fact in facts] == ["流阻：≤15kPa（设计验收要求）"]


def test_conflicting_descriptive_rows_still_require_manual_review(tmp_path):
    source = tmp_path / "conflicting-requirements.docx"
    document = Document()
    document.add_heading("技术规格", level=1)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "技术特性类型"
    table.cell(0, 1).text = "特性描述"
    for value in ("被动", "主动"):
        cells = table.add_row().cells
        cells[0].text = "散热方式"
        cells[1].text = value
    document.save(source)
    blocks = extract_source_blocks(str(source), "tech")
    classification = {
        "source_blocks": blocks,
        "classifications": [
            {"source_id": block["id"], "category": "performance_indicator"}
            for block in blocks
        ],
    }
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    content = build_content(
        profile, document, None, parse_doc(document), [], str(source),
        requirement_classification=classification,
    )["role:performance_indicator"]
    row = next(row for row in content["indicator_rows"] if row[0] == "散热方式")
    assert row[1] == "被动\n主动"
    assert row[3] == "【人工填写】"
