"""Regressions from the six accepted corrections in the 102422 review."""
import json
from pathlib import Path

import pytest
from docx import Document

from jonhon_taskbook.business_value_gate import audit_indicator_values
from jonhon_taskbook.coverage_ledger import parse_docx_to_ledger, mark_structured_indicator_coverage
from jonhon_taskbook.extractor import parse_doc
from jonhon_taskbook.fill import build_content, _collect_standards, _fill_indicator_table
from jonhon_taskbook.postprocess import postprocess
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks

GUIDANCE = "（此条要求将所有技术指标要求和试验方法详细列出）"
VALUE = "50Ω±1Ω，通带内阻抗均匀无突变；"
SOURCE = "（1）特性阻抗：" + VALUE


def indicator_template(columns=4):
    document = Document()
    document.add_heading("技术要求", 1)
    document.add_paragraph(GUIDANCE)
    document.add_heading("技术指标", 2)
    table = document.add_table(rows=2, cols=columns)
    headers = ["项目", "用户要求指标", "拟采用指标", "拟采用指标和试验的依据"]
    if columns == 5:
        headers.insert(2, "标准要求")
    for cell, header in zip(table.rows[0].cells, headers):
        cell.text = header
    table.cell(1, 0).text = "特性阻抗"
    return document


@pytest.mark.parametrize("filled", [False, True])
def test_authoring_instruction_removed_only_for_filled_indicator_section(tmp_path, filled):
    document = indicator_template()
    if filled:
        document.tables[0].cell(1, 1).text = VALUE
        document.tables[0].cell(1, 2).text = VALUE
        document.tables[0].cell(1, 3).text = "用户要求"
    document.add_heading("其他编写说明", 1)
    document.add_paragraph(GUIDANCE)
    path = tmp_path / "guidance.docx"
    document.save(path)
    postprocess(path, preserve_template_guidance=True)
    texts = [p.text for p in Document(path).paragraphs]
    assert texts.count(GUIDANCE) == (1 if filled else 2)
    assert "技术指标" in texts


@pytest.mark.parametrize("answer", ["", "无要求", "使用孔位1、2。"])
def test_unanswered_question_headings_mark_the_customer_other_parent(tmp_path, answer):
    document = Document()
    for parent in ["产品的功能用途", "顾客的特殊要求"]:
        document.add_heading(parent, 1)
        document.add_heading("其他要求", 2)
        document.add_heading("是否使用在交流电源上（如有注明使用孔位，没有请删除）；", 3)
        if answer:
            document.add_paragraph(answer)
    path = tmp_path / "questions.docx"
    document.save(path)
    postprocess(path)
    postprocess(path)
    others = [p for p in Document(path).paragraphs if p.text.startswith("其他要求")]
    assert others[0].text == "其他要求"
    assert others[1].text == ("其他要求【人工填写】" if not answer else "其他要求")


def test_contract_administration_is_excluded_but_technical_agreements_and_standards_survive(tmp_path):
    document = Document()
    document.add_heading("其他约定", 1)
    excluded = "10.1 本协议未尽事宜，双方可协商签订补充协议，补充协议与本协议具有同等法律效力。"
    keep = [
        "10.2 如需定制滤波截止频率、防护等级、安装结构，供方需提供改型方案，经需方确认后生产交付。",
        "10.3 适用标准：GJB 360B《电子及电气元件试验方法》。",
        "10.4 补充协议须明确试验电压1000V和交付要求，并具有同等法律效力。",
    ]
    for text in [excluded, *keep]:
        document.add_paragraph(text)
    path = tmp_path / "source.docx"
    document.save(path)
    assert [b["text"] for b in extract_source_blocks(str(path), "tech")] == keep
    ledger = parse_docx_to_ledger(str(path))
    assert [b.raw_text for b in ledger.blocks] == keep


@pytest.mark.parametrize("tech_codes,spec_codes,template_codes,expected,conflict", [
    (["GJB 360B"], [], ["GJB 360B-2009"], ["GJB360B"], False),
    (["GJB 360B-2009"], [], ["GJB 360B"], ["GJB360B-2009"], False),
    (["GJB 360B", "GJB 360B-2009"], [], [], ["GJB360B", "GJB360B-2009"], False),
    (["GJB 360B-2009", "GJB 360B-2024"], [], [], ["GJB360B-2009", "GJB360B-2024"], True),
    (["GJB 360B-2009"], ["GJB 360B-2024"], [], ["GJB360B-2009"], False),
])
def test_unspecified_year_is_not_a_conflicting_explicit_version(tech_codes, spec_codes, template_codes, expected, conflict):
    def doc(codes):
        result = Document()
        result.add_heading("适用标准", 1)
        for code in codes:
            result.add_paragraph(code + "《电子及电气元件试验方法》")
        return result
    tech, spec, template = map(doc, [tech_codes, spec_codes, template_codes])
    audit = {}
    _collect_standards(tech, spec, parse_doc(tech), parse_doc(spec), [], template_doc=template, audit=audit)
    assert [r["code"] for r in audit["source_references"]] == expected
    assert bool(audit["version_conflicts"]) is conflict


@pytest.mark.parametrize("columns", [4, 5])
def test_display_values_keep_raw_source_evidence_and_detect_changed_conditions(tmp_path, columns):
    tech = Document()
    tech.add_heading("电性能", 1)
    tech.add_paragraph(SOURCE)
    tech_path = tmp_path / "tech.docx"
    tech.save(tech_path)
    source = {"id": "impedance", "type": "paragraph", "source": "tech", "body_index": 1,
              "text": SOURCE, "heading_text": "电性能", "source_path": str(tech_path)}
    classification = {"source_blocks": [source], "classifications": [
        {"source_id": "impedance", "category": "performance_indicator"}]}
    cfg = {
        "semantic_structures": {"performance_indicator": {"mode": "indicator_table"}},
        "indicator_map": {"电性能": [{"name": "特性阻抗", "tech_kws": ["特性阻抗"], "std_kws": ["特性阻抗"]}]},
        "indicator_sources": {"workbook": False, "reference_families": []},
        "standards_policy": "source_only",
    }
    document = indicator_template(columns)
    spec = Document()
    content = build_content(cfg, tech, spec, parse_doc(tech), parse_doc(spec), str(tech_path),
                            template_doc=document, requirement_classification=classification)
    indicators = content["role:performance_indicator"]
    _fill_indicator_table(document, indicators["indicator_rows"])
    row = document.tables[0].rows[1]
    adopted_column = 3 if columns == 5 else 2
    assert row.cells[1].text == row.cells[adopted_column].text == VALUE
    decision = indicators["indicator_comparison_audit"][0]
    assert decision["user_requirement"] == SOURCE
    assert indicators["input_indicator_facts"][0]["source_value"] == SOURCE
    output = tmp_path / "output.docx"
    document.save(output)
    output.with_suffix(".indicator_audit.json").write_text(json.dumps({
        "input_indicator_facts": indicators["input_indicator_facts"],
        "comparison_decisions": indicators["indicator_comparison_audit"],
    }, ensure_ascii=False), encoding="utf-8")
    output.with_suffix(".requirement_classification.json").write_text(json.dumps(classification, ensure_ascii=False), encoding="utf-8")
    assert audit_indicator_values(output)["passed"]
    ledger = parse_docx_to_ledger(str(tech_path))
    mark_structured_indicator_coverage(ledger, str(output))
    assert ledger.covered_count == len(ledger.blocks) == 1
    for changed in [VALUE.replace("±1Ω", "±2Ω"), VALUE.replace("，通带内阻抗均匀无突变", "")]:
        row.cells[1].text = changed
        document.save(output)
        assert not audit_indicator_values(output)["passed"]
        ledger = parse_docx_to_ledger(str(tech_path))
        mark_structured_indicator_coverage(ledger, str(output))
    assert ledger.covered_count == 0


@pytest.mark.parametrize("name,aliases,source,expected", [
    ("机械寿命", ["插拔寿命"], "6.2 插拔寿命：≥1000次，试验后无松动。", "≥1000次，试验后无松动。"),
    ("阻带衰减", ["阻带衰减性能"], "（2）阻带衰减性能：2GHz≥20dB、3GHz≥30dB；", "2GHz≥20dB、3GHz≥30dB；"),
    ("高低温循环", ["高低温循环试验"], "（2）高低温循环试验：-40℃～+85℃循环100次；", "-40℃～+85℃循环100次；"),
    ("锁紧力矩", [], "0.5 N·m", "0.5 N·m"),
    ("额定电流", ["额定电流(A)"], "额定电流(A)：3", "额定电流(A)：3"),
    ("接触电阻", ["初始接触电阻"], "初始接触电阻：≤5mΩ", "初始接触电阻：≤5mΩ"),
    ("接触电阻", [], "试验后接触电阻：≤10mΩ", "试验后接触电阻：≤10mΩ"),
    ("特性阻抗", [], "工作温度：-40℃～+85℃", "工作温度：-40℃～+85℃"),
])
def test_indicator_display_never_discards_units_conditions_or_different_labels(name, aliases, source, expected):
    from jonhon_taskbook.indicator_identity import indicator_display_value
    assert indicator_display_value(source, name, aliases) == expected
