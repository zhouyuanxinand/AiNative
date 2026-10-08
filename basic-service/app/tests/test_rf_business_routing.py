"""RF review cases: governed source modules and exact interface evidence reuse."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from docx import Document

from jonhon_taskbook.fill import _merge_classified_content, fill
from jonhon_taskbook.requirement_classifier import build_requirement_classification


APP = Path(__file__).resolve().parents[1]
PACKAGE = APP / "src/service/jonhon_taskbook"
MAPPING = APP / "src/service/config/rf_connector_requirement_categories.yaml"


def _unreliable_classifier(calls):
    """Deliberately misclassify chapters; governed business rules must prevail."""
    def respond(_system, user):
        payload = json.loads(user)
        calls.append(payload)
        if payload["node"] == "source_structure":
            return {"headings": []}
        if payload["node"] == "requirement_exact_fragment_routing":
            return {"partitions": []}
        assert payload["node"] == "requirement_classification"
        return {"classifications": [
            {"source_id": item["source_id"], "category": "other",
             "confidence": 0.9, "reason": "broad chapter classification"}
            for item in payload["blocks"]
        ]}
    return respond


@pytest.fixture
def routed_requirement(tmp_path):
    source = Document()
    source.add_heading("射频连接器技术协议", level=1)
    source.add_heading("应用背景与使用场景", level=1)
    source.add_heading("应用领域", level=2)
    environment = "产品安装在设备上，面向无线通信和测试测量场景，长期连续传输射频信号。"
    source.add_paragraph(environment)
    source.add_heading("功能定位", level=2)
    function = "实现模块之间的可靠射频连接与传输，满足整机长期不间断运行需求。"
    source.add_paragraph(function)
    source.add_heading("产品型号与结构形式", level=1)
    source.add_heading("结构形式", level=2)
    structure = "直式/弯式可选，公头/母头适配，螺纹锁紧/卡扣式固定，适配标准射频同轴电缆对接"
    source.add_paragraph(structure)
    source.add_heading("适配线缆", level=2)
    cable = "匹配对应规格50Ω/75Ω射频同轴电缆（根据型号适配RG174、RG58、RG213等常规线缆）"
    source.add_paragraph(cable)
    source.add_heading("外形尺寸", level=1)
    dimensions = "产品外形尺寸符合对应型号国标标准尺寸，具体适配安装孔位、对接尺寸严格匹配行业通用规格。"
    source.add_paragraph(dimensions)
    source.add_heading("外观要求", level=1)
    appearance = "产品表面光洁无毛刺，无划痕、无锈蚀。"
    source.add_paragraph(appearance)
    source.add_heading("结构材质要求", level=1)
    materials = [
        "（1）内外导体：采用优质黄铜/磷铜材质，表面镀金（镀层厚度≥0.76μm）；",
        "（2）绝缘介质：采用PTFE聚四氟乙烯材质，耐高温、低介电损耗；",
        "（3）外壳壳体：黄铜镀镍，硬度高、抗磨损、防电磁干扰；",
        "（4）密封件：采用耐高温硅橡胶密封圈，保证连接处密封性。",
    ]
    for item in materials:
        source.add_paragraph(item)
    source.add_heading("制造工艺", level=1)
    manufacturing = "装配后按工艺规程检查紧固情况。"
    source.add_paragraph(manufacturing)
    source.add_heading("总则", level=1)
    introduction = "本协议用于明确供需双方技术要求。"
    source.add_paragraph(introduction)
    standards = "适用标准：GB/T 11313《射频同轴连接器通用规范》、GJB 6815《军用射频连接器通用规范》。"
    source.add_paragraph(standards)
    source_path = tmp_path / "requirement.docx"
    source.save(source_path)
    calls = []
    report = build_requirement_classification(
        str(source_path), str(MAPPING), chat_json_fn=_unreliable_classifier(calls)
    )
    return source_path, source, report, calls, {
        "environment": environment, "function": function,
        "structure": structure, "cable": cable, "dimensions": dimensions,
        "appearance": appearance,
        "materials": materials, "manufacturing": manufacturing,
        "standards": standards, "introduction": introduction,
    }


def _category_by_text(report):
    categories = {item["source_id"]: item["category"] for item in report["classifications"]}
    return {block["text"]: categories[block["id"]] for block in report["source_blocks"]}


def test_rf_complete_modules_survive_content_override_and_fragment_stage(routed_requirement):
    _, _, report, calls, texts = routed_requirement
    categories = _category_by_text(report)
    assert report["passed"]
    assert categories[texts["environment"]] == "usage_environment"
    assert categories[texts["function"]] == "usage_environment"
    assert categories[texts["structure"]] == "product_composition"
    assert categories[texts["cable"]] == "product_composition"
    assert all(categories[text] == "material_selection" for text in texts["materials"])
    assert categories[texts["manufacturing"]] == "process_requirement"
    assert categories[texts["standards"]] == "standards_reference"
    assert categories[texts["appearance"]] == "appearance_requirement"
    assert categories[texts["introduction"]] == "other"
    fragmented_texts = {
        item["text"] for call in calls
        if call["node"] == "requirement_exact_fragment_routing"
        for item in call["blocks"]
    }
    atomic_texts = {texts[key] for key in ("environment", "function", "structure", "cable")}
    atomic_texts.update(texts["materials"])
    assert not atomic_texts.intersection(fragmented_texts)


def test_rf_interfaces_reuse_only_exact_evidence_and_keep_composition(routed_requirement):
    _, source, report, _, texts = routed_requirement
    content = {}
    _merge_classified_content(content, report, str(MAPPING), source)
    def slot_texts(role):
        item = content[f"role:{role}"]
        return item["lines"] + [entry["text"] for entry in item["ordered_elements"]
                                if entry["kind"] == "paragraph"]

    assert texts["structure"] in slot_texts("product_composition")
    assert texts["cable"] in slot_texts("product_composition")
    assert texts["dimensions"] in slot_texts("outline_dimension")
    expected = {
        "mating_interface": "直式/弯式可选，公头/母头适配",
        "installation_method": "螺纹锁紧/卡扣式固定",
        "termination_method": "适配标准射频同轴电缆对接",
        "connected_coaxial_cable": texts["cable"],
        "installation_dimension": "具体适配安装孔位、对接尺寸严格匹配行业通用规格",
    }
    for role, text in expected.items():
        assert text in content[f"role:{role}"]["lines"]
        for evidence in content[f"role:{role}"]["projection_audit"]:
            original = next(block["text"] for block in report["source_blocks"]
                            if block["id"] == evidence["source_id"])
            assert evidence["text"] in original
    assert slot_texts("material_selection") == texts["materials"]
    assert slot_texts("process_requirement") == [texts["manufacturing"]]


def test_rf_filled_document_places_materials_in_design_other_section(routed_requirement, tmp_path):
    source_path, _, report, _, texts = routed_requirement
    spec_path = tmp_path / "spec.docx"
    specification = Document()
    specification.add_heading("射频连接器产品规范", level=1)
    specification.save(spec_path)
    output = tmp_path / "filled.docx"
    fill(
        str(source_path), str(spec_path),
        str(PACKAGE / "resources/templates/rf_connector_taskbook.docx"),
        str(output), str(PACKAGE / "rf_standard_interface_profile.yaml"),
        category_mapping_path=str(MAPPING), requirement_classification=report,
        preserve_unfilled_template=True, finalize=False,
    )
    paragraphs = [paragraph.text for paragraph in Document(output).paragraphs]
    material_heading = next(i for i, text in enumerate(paragraphs)
                            if "设计开发所需其他要求" in text)
    process_heading = next(i for i, text in enumerate(paragraphs) if text.strip() == "工艺要求")
    material_positions = [paragraphs.index(text) for text in texts["materials"]]
    assert all(index > material_heading for index in material_positions)
    assert all(index > paragraphs.index(texts["manufacturing"]) for index in material_positions)
    assert paragraphs.index(texts["manufacturing"]) > process_heading
    assert all(paragraphs.count(text) == 1 for text in texts["materials"])
    appearance_position = paragraphs.index(texts["appearance"])
    composition_heading = next(i for i, text in enumerate(paragraphs)
                               if text.strip() == "产品组成")
    assert appearance_position < composition_heading
    interface_values = {
        "界面形式": "直式/弯式可选，公头/母头适配",
        "安装方式": "螺纹锁紧/卡扣式固定",
        "安装尺寸": "具体适配安装孔位、对接尺寸严格匹配行业通用规格",
        "外形尺寸": texts["dimensions"],
        "端接电缆形式": "适配标准射频同轴电缆对接",
        "所接同轴电缆型号": texts["cable"],
    }
    heading_positions = {
        label: next(i for i, text in enumerate(paragraphs)
                    if text.strip().rstrip("：:") == label)
        for label in interface_values
    }
    for label, expected in interface_values.items():
        start = heading_positions[label]
        end = min((i for i in heading_positions.values() if i > start),
                  default=next(i for i, text in enumerate(paragraphs)
                               if "条件保障要求" in text))
        assert expected in paragraphs[start + 1:end], (label, paragraphs[start:end])
