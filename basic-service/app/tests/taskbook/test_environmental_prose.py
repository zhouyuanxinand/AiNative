"""Environmental chapters project requirement evidence into prose only."""
from tests.support.paths import APP_ROOT
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from jonhon_taskbook.fill import _merge_classified_content
from jonhon_taskbook.environmental_prose import project_environmental_evidence
from jonhon_taskbook.semantic_orchestrator import (
    apply_semantic_plan, extract_source_blocks, extract_template_slots,
)

MAPPING = APP_ROOT / "src/service/config/connector_requirement_categories.yaml"

ENVIRONMENT_SCOPE = [
    ("高低温循环", "-40℃～85℃，循环10次"),
    ("湿热交变", "25℃～55℃交变，95%RH，6个周期"),
    ("盐雾腐蚀", "5%盐溶液，持续48 h"),
    ("霉菌生长", "培养28 d，生长等级不超过1级"),
    ("淋雨浸水", "淋雨30 min后浸入1 m水深30 min"),
    ("沙尘冲击", "沙尘浓度10 g/m³，持续6 h"),
    ("振动冲击", "扫频10Hz～2000Hz，冲击持续11 ms"),
    ("力学过载", "150 m/s²，三个正交轴分别施加"),
    ("低气压", "4.4 kPa下保持1 h"),
    ("高原环境", "适用海拔5000 m以内"),
    ("海洋环境", "适用于潮湿含盐海洋气氛"),
    ("工业干扰环境", "电场强度10 V/m，频率80 MHz～1 GHz"),
    ("老化耐受", "70℃下持续168 h"),
    ("长期环境稳定性", "-20℃～60℃运行1000 h，漂移不超过1%"),
]


def _mixed_source(tmp_path):
    source = Document()
    source.add_heading("性能指标", 1)
    table = source.add_table(rows=6, cols=2)
    for row, values in zip(table.rows, [
        ("项目", "指标"), ("工作电压", "60 V DC"),
        ("工作温度", "-40℃～+85℃"), ("盐雾", "持续48 h，试验后无影响功能的腐蚀"),
        ("机械寿命", "500次"), ("介质耐电压", "低气压（4.4 kPa）：150 V AC"),
    ]):
        for cell, value in zip(row.cells, values):
            cell.text = value
    path = tmp_path / "source.docx"
    source.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    return source, next(block for block in blocks if block["type"] == "table")


@pytest.mark.parametrize("category", ["performance_indicator", "environmental_adaptability", "both"])
def test_environmental_fill_projects_only_relevant_table_rows(tmp_path, category):
    source, block = _mixed_source(tmp_path)
    content = {}
    assignments = ["performance_indicator", "environmental_adaptability"] if category == "both" else [category]
    _merge_classified_content(content, {
        "source_blocks": [block], "classifications": [{"source_id": block["id"], "category": item} for item in assignments],
    }, str(MAPPING), source)
    env = content["role:environmental_adaptability"]
    assert env["tables"] == []
    assert all(item["kind"] == "paragraph" for item in env["ordered_elements"])
    text = "".join(env["lines"]) + "".join(item.get("text", "") for item in env["ordered_elements"])
    assert "工作温度" in text and "-40℃～+85℃" in text
    assert "盐雾" in text and "持续48 h，试验后无影响功能的腐蚀" in text
    assert "工作电压" not in text and "60 V" not in text and "500次" not in text
    assert "介质耐电压" not in text and "150 V" not in text


def test_semantic_executor_does_not_recopy_mixed_table_into_environment(tmp_path):
    _, block = _mixed_source(tmp_path)
    output = Document()
    output.add_heading("环境适应性要求", 1)
    path = tmp_path / "output.docx"
    output.save(path)
    slots = extract_template_slots(str(path))
    result = apply_semantic_plan(str(path), {
        "slots": slots, "source_blocks": [block],
        "decisions": [{"target_slot": slots[0]["id"], "source_ids": [block["id"]],
                       "operation": "copy_exact", "confidence": .99}],
    })
    document = Document(path)
    assert not document.tables
    text = "".join(p.text for p in document.paragraphs)
    assert "工作温度" in text and "盐雾" in text
    assert "工作电压" not in text and "机械寿命" not in text
    assert result["passed"]


@pytest.mark.parametrize("existing,passed", [
    (["工作温度：-40℃～+85℃。", "盐雾：持续48 h，试验后无影响功能的腐蚀。"], True),
    (["工作温度：-40℃～+85℃。"], False),
    (["工作温度：-40℃～+85℃。", "盐雾：持续24 h，试验后无影响功能的腐蚀。"], False),
])
def test_low_confidence_projection_requires_every_correct_source_value(tmp_path, existing, passed):
    _, block = _mixed_source(tmp_path)
    output = Document()
    output.add_heading("环境适应性要求", 1)
    for text in existing:
        output.add_paragraph(text)
    path = tmp_path / "output.docx"
    output.save(path)
    slots = extract_template_slots(str(path))
    result = apply_semantic_plan(str(path), {
        "slots": slots, "source_blocks": [block],
        "decisions": [{"target_slot": slots[0]["id"], "source_ids": [block["id"]],
                       "operation": "copy_exact", "confidence": .2}],
    })
    assert result["passed"] is passed
    assert result["counts"]["inserted"] == 0
    assert result["counts"]["verified_present"] == int(passed)
    assert not Document(path).tables
    if passed:
        assert len(result["verified_present"][0]["projections"]) == 2


def test_projection_does_not_bypass_source_hash_check(tmp_path):
    source, block = _mixed_source(tmp_path)
    source.tables[0].cell(2, 1).text = "-10℃～+20℃"
    source.save(block["source_path"])
    output = Document()
    output.add_heading("环境适应性要求", 1)
    path = tmp_path / "out.docx"
    output.save(path)
    slots = extract_template_slots(str(path))
    evidence = apply_semantic_plan(str(path), {
        "slots": slots, "source_blocks": [block],
        "decisions": [{"target_slot": slots[0]["id"], "source_ids": [block["id"]],
                       "operation": "copy_exact", "confidence": .99}],
    })
    assert not evidence["passed"]
    assert evidence["blocking_skipped"][0]["reason"] == "source_hash_mismatch"
    assert len(Document(path).paragraphs) == 1


def test_mixed_paragraph_keeps_environmental_requirements_and_conditions_without_list():
    text = "a) 工作电压：60 V；工作温度：-55℃～125℃；高温运行后检查密封垫。盐雾：中性盐雾192 h；机械寿命：500次。"
    projected = project_environmental_evidence({"id": "mixed", "type": "paragraph", "text": text})
    result = "".join(item["text"] for item in projected)
    assert result == "工作温度：-55℃～125℃；高温运行后检查密封垫。盐雾：中性盐雾192 h；"
    assert all(fragment in text for item in projected for fragment in item["source_fragments"])


@pytest.mark.parametrize("text", [
    "介质耐电压：低气压（4.4 kPa）时150 V AC。",
    "绝缘电阻：湿热后不小于100 MΩ。",
    "机械寿命：低温下500次。", "冲击电流：150 A。",
    "内外导体：黄铜镀金，耐腐蚀，导电性能良好。",
    "介质耐电压：常温常压：500V AC；低气压（4.4 kPa）：150 V AC，耐电压测试时间5s。",
])
def test_environmental_test_conditions_do_not_reclassify_other_metrics(text):
    assert project_environmental_evidence({"id": "electric", "type": "paragraph", "text": text,
                                           "heading_text": "环境适应性要求"}) == []


def test_parallel_metric_columns_are_not_joined_into_one_requirement():
    projected = project_environmental_evidence({
        "id": "table", "type": "table", "table_rows": [
            ["项目", "指标", "项目", "指标"],
            ["工作温度", "-55℃～125℃", "工作电压", "60 V DC"],
        ],
    })
    assert [item["text"] for item in projected] == ["工作温度：-55℃～125℃。"]


def test_only_requirement_document_values_can_enter_environmental_prose(tmp_path):
    _, block = _mixed_source(tmp_path)
    assert project_environmental_evidence({**block, "source": "spec"}) == []


def test_environmental_projection_leaves_other_target_table_intact(tmp_path):
    _, block = _mixed_source(tmp_path)
    output = Document()
    output.add_heading("技术指标", 1)
    output.add_heading("环境适应性要求", 1)
    path = tmp_path / "output.docx"
    output.save(path)
    slots = extract_template_slots(str(path))
    result = apply_semantic_plan(str(path), {
        "slots": slots, "source_blocks": [block],
        "decisions": [{"target_slot": slot["id"], "source_ids": [block["id"]],
                       "operation": "copy_exact", "confidence": .99} for slot in slots],
    })
    document = Document(path)
    assert len(document.tables) == 1
    assert document.tables[0].cell(1, 1).text == "60 V DC"
    assert document.tables[0].cell(4, 1).text == "500次"
    assert result["passed"]


def test_existing_whole_table_is_not_verified_as_environmental_prose(tmp_path):
    import copy

    source, block = _mixed_source(tmp_path)
    output = Document()
    output.add_heading("环境适应性要求", 1)
    output.element.body.insert(-1, copy.deepcopy(source.tables[0]._tbl))
    path = tmp_path / "output.docx"
    output.save(path)
    slots = extract_template_slots(str(path))
    result = apply_semantic_plan(str(path), {
        "slots": slots, "source_blocks": [block],
        "decisions": [{"target_slot": slots[0]["id"], "source_ids": [block["id"]],
                       "operation": "copy_exact", "confidence": .2}],
    })
    assert not result["passed"]
    assert result["counts"]["verified_present"] == 0
    assert result["counts"]["inserted"] == 0


def test_source_xml_owns_paragraph_values_even_if_classification_text_differs(tmp_path):
    source = Document()
    source.add_heading("环境性能要求", 1)
    source.add_paragraph("工作温度：-55℃～125℃。")
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    block = extract_source_blocks(str(source_path), "tech")[0]
    block["text"] = "工作温度：-10℃～20℃。"
    output = Document()
    output.add_heading("环境适应性要求", 1)
    path = tmp_path / "output.docx"
    output.save(path)
    slots = extract_template_slots(str(path))
    result = apply_semantic_plan(str(path), {
        "slots": slots, "source_blocks": [block],
        "decisions": [{"target_slot": slots[0]["id"], "source_ids": [block["id"]],
                       "operation": "copy_exact", "confidence": .99}],
    })
    assert result["passed"]
    assert Document(path).paragraphs[-1].text == "工作温度：-55℃～125℃。"


@pytest.mark.parametrize("prefix", ["a. ", "b) ", "（1）", "• "])
def test_environmental_prose_has_no_literal_list_prefix(prefix):
    projected = project_environmental_evidence({"id": "p", "type": "paragraph", "text": prefix + "耐腐蚀，应通过盐雾试验。"})
    assert projected[0]["text"] == "耐腐蚀，应通过盐雾试验。"


@pytest.mark.parametrize("writer", ["fill", "semantic"])
def test_environmental_table_units_preserve_source_superscript_and_subscript(tmp_path, writer):
    source = Document()
    source.add_heading("性能指标", 1)
    table = source.add_table(rows=4, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "项目", "指标"
    for index, label, prefix, alignment in [
        (1, "冲击", "峰值加速度为980m/s ", "superscript"),
        (2, "振动", "加速度147m/s ", "superscript"),
        (3, "湿热", "试验介质H", "subscript"),
    ]:
        table.cell(index, 0).text = label
        paragraph = table.cell(index, 1).paragraphs[0]
        paragraph.add_run(prefix)
        run = paragraph.add_run("2")
        setattr(run.font, alignment, True)
        paragraph.add_run("O。" if alignment == "subscript" else "。")
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    block = extract_source_blocks(str(source_path), "tech")[0]
    if writer == "fill":
        content = {}
        _merge_classified_content(content, {
            "source_blocks": [block], "classifications": [{"source_id": block["id"], "category": "environmental_adaptability"}],
        }, str(MAPPING), source)
        paragraphs = [item["element"] for item in content["role:environmental_adaptability"]["ordered_elements"]]
    else:
        output = Document()
        output.add_heading("环境适应性要求", 1)
        path = tmp_path / "output.docx"
        output.save(path)
        slots = extract_template_slots(str(path))
        result = apply_semantic_plan(str(path), {
            "slots": slots, "source_blocks": [block],
            "decisions": [{"target_slot": slots[0]["id"], "source_ids": [block["id"]],
                           "operation": "copy_exact", "confidence": .99}],
        })
        assert result["passed"]
        paragraphs = [paragraph._p for paragraph in Document(path).paragraphs[1:]]
    assert len(paragraphs) == 3
    texts = ["".join(t.text or "" for t in paragraph.iter(qn("w:t"))) for paragraph in paragraphs]
    assert "980m/s 2" in texts[0] and "147m/s 2" in texts[1]
    assert "H2O" in texts[2]
    for paragraph, expected in zip(paragraphs, ["superscript", "superscript", "subscript"]):
        styled = [(run, run.find(f"{qn('w:rPr')}/{qn('w:vertAlign')}")) for run in paragraph.iter(qn("w:r"))]
        styled = [(run, alignment) for run, alignment in styled if alignment is not None]
        assert len(styled) == 1
        run, alignment = styled[0]
        assert alignment.get(qn("w:val")) == expected
        assert "".join(t.text or "" for t in run.iter(qn("w:t"))) == "2"


@pytest.mark.parametrize("subject,condition", ENVIRONMENT_SCOPE)
@pytest.mark.parametrize("source_kind", ["paragraph", "table"])
def test_full_environmental_scope_retains_thresholds_assessment_and_constraints(subject, condition, source_kind):
    value = f"试验要求：{condition}；耐受阈值：试验后外壳不得开裂；考核标准：按用户提供的专项试验规程A考核；环境适配约束条件：安装后保持密封，试验结束不得出现功能失效。"
    if source_kind == "paragraph":
        expected = f"{subject}：{value}"
        block = {"id": "scope", "type": "paragraph", "text": expected + "工作电压：60 V；机械寿命：500次。"}
    else:
        expected = f"{subject}：{value}"
        block = {"id": "scope", "type": "table", "table_rows": [
            ["项目", "指标"], ["工作电压", "60 V"], [subject, value], ["机械寿命", "500次"],
        ]}
    projected = project_environmental_evidence(block)
    assert [item["text"] for item in projected] == [expected]
    assert all(fragment in (expected if source_kind == "paragraph" else subject + value)
               for item in projected for fragment in item["source_fragments"])


def test_environmental_test_parameter_continuations_are_not_general_product_metrics():
    text = "振动试验：按用户试验规程B进行；频率范围：10 Hz～2000 Hz；加速度：147 m/s²；持续时间：2 h；考核标准：各方向试验后功能正常；工作频率：50 MHz；工作电流：15 A。"
    projected = project_environmental_evidence({"id": "vibration", "type": "paragraph", "text": text})
    assert [item["text"] for item in projected] == [text[:text.index("工作频率")]]


def test_environment_table_column_headings_keep_threshold_and_assessment_meaning():
    block = {"id": "environment-table", "type": "table", "table_rows": [
        ["项目", "试验要求", "耐受阈值", "考核标准", "环境适配约束条件"],
        ["工业干扰环境", "80 MHz～1 GHz，10 V/m", "功能不得中断", "按用户试验规程C", "屏蔽壳体闭合后考核"],
        ["工作电压", "60 V", "不低于55 V", "按电气试验规程", "常温"],
    ]}
    projected = project_environmental_evidence(block)
    assert [item["text"] for item in projected] == [
        "工业干扰环境：试验要求：80 MHz～1 GHz，10 V/m；耐受阈值：功能不得中断；考核标准：按用户试验规程C；环境适配约束条件：屏蔽壳体闭合后考核。"
    ]
    assert [item["text"] for item in projected[0]["source_headers"]] == block["table_rows"][0][1:]


def test_environmental_assessment_column_keeps_its_electrical_acceptance_criterion():
    projected = project_environmental_evidence({"id": "assessment", "type": "table", "table_rows": [
        ["项目", "试验要求", "考核标准"],
        ["盐雾腐蚀", "中性盐雾192 h", "接触电阻增量≤5 mΩ，密封件不得开裂"],
        ["工作电压", "60 V DC", "电压降≤2 V"],
    ]})
    assert [item["text"] for item in projected] == [
        "盐雾腐蚀：试验要求：中性盐雾192 h；考核标准：接触电阻增量≤5 mΩ，密封件不得开裂。"
    ]


def test_electrical_overload_is_not_mechanical_environmental_overload():
    assert project_environmental_evidence({"id": "overload", "type": "paragraph", "text": "电气过载：125%额定电流持续1 min。"}) == []


@pytest.mark.parametrize("heading,text", [
    ("介质耐电压", "常温常压：500 V AC；低气压（4.4 kPa）：150 V AC，试验时间5 s。"),
    ("性能指标", "介质耐电压：500 V AC；试验条件：低气压4.4 kPa；考核标准：持续5 s无击穿。"),
])
def test_non_environmental_subject_keeps_ownership_of_its_test_details(heading, text):
    assert project_environmental_evidence({"id": "electric-conditions", "type": "paragraph", "text": text,
                                           "heading_text": heading}) == []
