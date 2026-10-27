"""Exercise the supplied fluid connector template with synthetic source evidence."""

import json
from pathlib import Path

from docx import Document

from jonhon_taskbook.fill import fill
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks
from jonhon_taskbook.template_scanner import scan_template_tree


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "src/service"
PROFILE = SERVICE_ROOT / "jonhon_taskbook/liquid_cooling_connector_profile.yaml"
TEMPLATE = SERVICE_ROOT / "jonhon_taskbook/resources/templates/liquid_cooling_connector_taskbook.docx"
MAPPING = SERVICE_ROOT / "config/liquid_cooling_connector_requirement_categories.yaml"


def _generate(tmp_path, sections, *, spec_sections=()):
    tech_path, spec_path, output = (tmp_path / name for name in ("tech.docx", "spec.docx", "fluid.docx"))
    tech = Document()
    categories = {}
    for heading, category, evidence in sections:
        categories[heading] = category
        tech.add_heading(heading, level=1)
        tech.add_paragraph().add_run(evidence).bold = True
    tech.save(tech_path)
    spec = Document()
    for heading, text in spec_sections:
        spec.add_heading(heading, level=1)
        spec.add_paragraph(text)
    spec.save(spec_path)
    blocks = extract_source_blocks(str(tech_path), "tech")
    classification = {
        "source_blocks": blocks,
        "classifications": [
            {"source_id": block["id"], "category": categories[block["heading_text"]]}
            for block in blocks
        ],
    }
    fill(
        str(tech_path), str(spec_path), str(TEMPLATE), str(output), str(PROFILE),
        category_mapping_path=str(MAPPING), requirement_classification=classification,
        controlled_product_label="液冷产品-液冷连接器", controlled_product_domain="military",
        product_series="FLOW-SYNTHETIC-TEST", organization_scope="non_central_research",
        development_process="全新", preserve_unfilled_template=True, finalize=False,
    )
    return output, Document(output)


def _chapter_text(document, path, title):
    tree = scan_template_tree(str(path))
    section = next(node for node in tree if node["title"] == title)
    following = next((node for node in tree if node["paragraph_index"] > section["paragraph_index"]
                      and node["level"] <= section["level"]), None)
    stop = document.paragraphs[following["paragraph_index"]]._p if following else None
    element = document.paragraphs[section["paragraph_index"]]._p.getnext()
    texts = []
    while element is not None and element is not stop:
        texts.extend(element.xpath(".//w:t/text()"))
        element = element.getnext()
    return "\n".join(texts)


def test_fluid_metrics_fill_separate_real_template_rows_and_preserve_unrequested_blanks(tmp_path):
    values = {
        "工作压力": "2.7 MPa。", "工作流量": "12.4 L/min。", "流阻": "≤24 kPa。",
        "泄漏量": "≤0.02 mL/min。", "压力脉冲": "≥12000 次。", "流量脉冲": "≥8500 次。",
        "工作介质": "合成验证冷却液 A。", "工作介质温度": "-23℃～73℃。",
        "插合和分离力或扭矩": "插合力≤68 N，分离力≤72 N。",
        "贮存温度": "-45℃～83℃。", "泄压压力": "3.4 MPa。",
    }
    output, document = _generate(tmp_path, [
        (name, "performance_indicator", f"{name}：{value}") for name, value in values.items()
    ])
    table = next(table for table in document.tables if "用户要求指标" in "".join(cell.text for cell in table.rows[0].cells))
    rows = {"".join(row.cells[0].text.split()).rstrip("：:"): [cell.text.strip() for cell in row.cells]
            for row in table.rows[1:] if len(set(cell.text for cell in row.cells)) > 1}
    for name, value in values.items():
        assert rows[name][1] == value, (name, rows[name])
        assert rows[name][2] == value, (name, rows[name])
        assert "用户要求" in rows[name][3]
    for unrequested in ("密封检验方式", "机械寿命", "使用寿命", "重量"):
        assert rows[unrequested][1] in {"", "\\"}
        assert rows[unrequested][2] == ""
    assert not ({"工作电压", "插入损耗", "接触电阻"} & rows.keys())
    audit = json.loads(output.with_suffix(".indicator_audit.json").read_text(encoding="utf-8"))
    assert all(f"{name}：{value}" in {fact["source_value"] for fact in audit["input_indicator_facts"]}
               for name, value in values.items())


def test_fluid_interface_composition_and_customer_evidence_go_to_distinct_real_chapters(tmp_path):
    sections = [
        ("产品组成", "product_composition", "验证组件由阀芯 A、阀体 B 和密封件 C 组成。"),
        ("安装方式", "installation_method", "验证接口使用螺母固定，先定位后锁紧。"),
        ("安装尺寸", "installation_dimension", "验证安装孔距为 47 mm，安装限位间距为 65 mm。"),
        ("外形尺寸", "outline_dimension", "验证外形总长为 123 mm，最大直径为 28 mm。"),
        ("互换性", "interchangeability", "仅允许与验证型号 FLOW-MATE-A 配合，不与 FLOW-MATE-B 互换。"),
        ("需向用户提交的文件", "customer_documents", "应提交验证项目专用的压力脉冲试验报告。"),
        ("可靠性定量要求", "reliability_quantitative", "验证平均无故障时间不低于 23000 h。"),
    ]
    output, document = _generate(tmp_path, sections)
    chapter_texts = {heading: _chapter_text(document, output, heading) for heading, _, _ in sections}
    for heading, _, evidence in sections:
        assert evidence in chapter_texts[heading]
        assert all(evidence not in text for other, text in chapter_texts.items() if other != heading)
        copied = [paragraph for paragraph in document.paragraphs if paragraph.text == evidence]
        assert copied
        assert all(any(run.bold for run in paragraph.runs if run.text == evidence) for paragraph in copied)
    assert sections[1][2] in _chapter_text(document, output, "安装形式和方法")


def test_fluid_applicable_standards_merge_requirement_specification_and_template(tmp_path):
    output, document = _generate(tmp_path, [
        ("适用标准", "standards_reference", "适用标准：GB/T 98765-2026《合成验证流体接口规范》。"),
    ], spec_sections=[("引用文件", "ISO 98765:2026 合成验证接口试验方法")])
    text = _chapter_text(document, output, "适用的法律法规要求")
    assert "GB/T 98765-2026" in text
    assert "ISO 98765:2026" in text
    assert "GJB" in text  # Existing military-template references are retained.
    assert text.count("GB/T 98765-2026") == 1
    assert "GB/T 98765-2026" not in _chapter_text(document, output, "其他要求")
