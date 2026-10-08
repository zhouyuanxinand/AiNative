"""Filter template routing and facts from the reviewed SMA filter protocol."""
import json
from pathlib import Path

import pytest
import yaml
from docx import Document

from jonhon_taskbook.fill import _merge_classified_content
from jonhon_taskbook.indicator_facts import extract_indicator_facts
from jonhon_taskbook.requirement_classifier import build_requirement_classification
from jonhon_taskbook.source_scope import normalize_source_display_text


APP = Path(__file__).resolve().parents[1]
PROFILE = APP / "src/service/jonhon_taskbook/filter_connector_profile.yaml"
MAPPING = APP / "src/service/config/filter_connector_requirement_categories.yaml"
MATERIALS = [
    "（1）内外导体：优质黄铜材质，表面镀金，镀金层厚度≥0.76μm，导电性能优异、抗氧化、耐腐蚀、接触电阻稳定；",
    "（2）外壳壳体：黄铜镀镍，硬度高、抗磨损、电磁屏蔽性能优良；",
    "（3）绝缘介质：聚四氟乙烯（PTFE），耐高温、低介电损耗、绝缘性能稳定；",
    "（4）滤波元件：高频低损耗陶瓷电容，温度稳定性高、滤波特性一致性好；",
    "（5）密封结构：耐高温硅胶密封件，防尘防水，杜绝水汽、粉尘侵入内部滤波结构。",
]
STRUCTURE = "3.1 产品类型：SMA型50Ω射频低通滤波连接器，板装穿墙式/线缆对接式可选，公头/母头适配通用SMA对接界面，可与标准SMA连接器完全互换兼容。"
BASIC = "3.3 基础规格：特性阻抗50Ω，螺纹规格1/4-36UNS，外导体内径4.13mm，完全匹配国标SMA界面尺寸。"
DIMENSION = "4.1 外形尺寸：产品整体外形、安装孔位、对接界面、螺纹尺寸严格符合GB/T 11313.15-2018标准尺寸，尺寸公差≤±0.05mm，与标准SMA连接器100%互换，无需改板、改结构即可直接替换安装。"
COMPOUND = "（1）工作温度：-40℃～+85℃；存储温度：-55℃～+100℃；工作湿度：5%～95%RH（无凝露）；防护等级：IP65，防尘、防水、防油污侵入。"
EMC = [
    "8.1 产品具备优异的EMI抑制能力，可有效滤除电源杂波、高频谐波、脉冲干扰，解决设备传导干扰、辐射干扰超标问题。",
    "8.2 连接器屏蔽性能优良，可阻断内外电磁信号串扰，避免射频信号泄露对外产生干扰，同时抵御外界电磁噪声影响整机射频精度。",
    "8.3 整机配套后可协助设备满足常规EMC电磁兼容测试标准，适配军工、工业、通信设备电磁环境要求。",
]
METRICS = {
    "特性阻抗": "（1）特性阻抗：50Ω±1Ω，通带内阻抗均匀无突变；",
    "阻带衰减": "（2）阻带衰减性能：2GHz≥20dB、3GHz≥30dB、6GHz≥40dB、10GHz≥50dB，高频干扰大幅抑制；",
    "寄生电容": "（3）寄生电容：≤3.5pF，容值一致性偏差≤±0.3pF；",
    "电磁屏蔽效能": "（4）电磁屏蔽效能：≥60dB@1GHz，有效抑制射频信号泄露与外界电磁串扰；",
    "滤波稳定性": "（5）滤波稳定性：高低温、湿热、振动试验后，滤波衰减指标偏移≤3dB，无滤波失效、容值漂移问题。",
    "锁紧力矩": "6.1 锁紧力矩：标准螺纹锁紧力矩0.8～1.15N·m，锁紧牢固、拆卸顺畅，无滑丝、脱扣现象；",
    "机械寿命": "6.2 插拔寿命：标准插拔≥1000次，插拔后射频电气指标、滤波性能无衰减、结构无松动；",
    "线缆保持力": "6.3 线缆保持力：轴向拉力≥50N，连接器与线缆、板端连接牢固，无脱落、移位；",
    "抗扭转性能": "6.4 抗扭转性能：可承受常规装配扭转力矩，内部滤波结构无松动、无脱焊、无失效；",
    "结构牢固性": "6.5 结构牢固性：一体式封装结构，无松动元器件，抗机械冲击、抗形变。",
    "高低温循环": "（2）高低温循环试验：-40℃～+85℃循环100次，单次循环2h，试验后通带电气指标正常，滤波衰减偏移≤3dB，结构完好无开裂；",
    "湿热": "（3）湿热老化试验：85℃、85%RH环境持续96h，无锈蚀、绝缘老化、滤波容值漂移、性能失效问题；",
    "振动": "（4）振动试验：10Hz～1000Hz扫频振动，持续4h，产品无松动、无内部元件脱落，射频及滤波性能正常；",
    "盐雾": "（5）盐雾试验：中性盐雾48h，镀层无腐蚀、起皮、生锈，屏蔽及滤波性能不受影响；",
    "长期通电可靠性": "（6）长期通电可靠性：连续通电1000h无故障，信号传输稳定、滤波性能持续达标；",
    "密封性": "（7）气密性要求：穿墙密封款满足微漏标准，无漏气、渗水问题，适配密闭机箱使用。",
}


@pytest.fixture
def classified(tmp_path):
    document = Document()
    for heading, paragraphs in [
        ("产品结构要求", [STRUCTURE, BASIC]), ("外形尺寸", [DIMENSION]),
        ("材质与表面处理", MATERIALS),
        ("通用射频电气指标（通带性能）", list(METRICS.values())[:5]),
        ("机械性能指标", list(METRICS.values())[5:10]),
        ("工作环境条件", [COMPOUND, *list(METRICS.values())[10:]]),
        ("电磁兼容（EMC）要求", EMC),
    ]:
        document.add_heading(heading, 1)
        for text in paragraphs:
            document.add_paragraph(text)
    path = tmp_path / "source.docx"
    document.save(path)
    calls = []
    def respond(_system, user):
        payload = json.loads(user)
        calls.append(payload)
        if payload["node"] == "source_structure":
            return {"headings": []}
        if payload["node"] == "requirement_exact_fragment_routing":
            return {"partitions": []}
        return {"classifications": [{"source_id": b["source_id"], "category": "other", "confidence": 0.9}
                                    for b in payload["blocks"]]}
    report = build_requirement_classification(str(path), str(MAPPING), chat_json_fn=respond)
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    return document, report, calls, profile


def test_filter_explicit_metrics_are_complete_distinct_governed_facts(classified):
    document, report, _, profile = classified
    facts = extract_indicator_facts(report, profile["indicator_map"], source_document=document)
    by_name = {}
    for fact in facts:
        by_name.setdefault(fact["indicator_name"], []).append(fact)
    for name, original in METRICS.items():
        assert name in by_name, name
        assert any(f["source_value"] == original and f["governed_name"] for f in by_name[name]), name
    assert "电容或电感量" not in by_name
    assert by_name["寄生电容"][0]["category"] == "电性能"
    assert by_name["抗扭转性能"][0]["category"] == "机械性能"
    assert by_name["盐雾"][0]["category"] == "环境性能"
    assert {f["source_value"] for f in by_name["电磁兼容"]} == set(EMC)
    assert "基础规格" not in by_name


def test_filter_compound_environment_is_four_independent_facts(classified):
    document, report, _, profile = classified
    facts = extract_indicator_facts(report, profile["indicator_map"], source_document=document)
    selected = {f["indicator_name"]: f for f in facts if f["indicator_name"] in {"工作温度", "存储温度", "工作湿度", "防护等级"}}
    assert set(selected) == {"工作温度", "存储温度", "工作湿度", "防护等级"}
    assert "存储温度" not in selected["工作温度"]["source_value"]
    assert selected["防护等级"]["source_value"] == "防护等级：IP65，防尘、防水、防油污侵入。"
    assert all(f["source_value"] in COMPOUND for f in selected.values())


def test_filter_materials_remain_whole_in_template_process_section(classified):
    document, report, calls, _ = classified
    classes = {x["source_id"]: x["category"] for x in report["classifications"]}
    by_text = {b["text"]: classes[b["id"]] for b in report["source_blocks"]}
    assert all(by_text[m] == "process_requirement" for m in MATERIALS)
    offered = {b["text"] for c in calls if c["node"] == "requirement_exact_fragment_routing" for b in c["blocks"]}
    assert not set(MATERIALS) & offered
    content = {}
    _merge_classified_content(content, report, str(MAPPING), document)
    actual = content["role:process_requirement"]
    texts = actual["lines"] + [e["text"] for e in actual["ordered_elements"] if e["kind"] == "paragraph"]
    assert all(m in texts for m in MATERIALS)
    assert "role:material_selection" not in content


def test_labelled_reliability_overrides_environment_heading_without_changing_materials(classified):
    document, report, _, profile = classified
    facts = extract_indicator_facts(report, profile["indicator_map"], source_document=document)
    life = next(f for f in facts if f["indicator_name"] == "长期通电可靠性")
    assert life["category"] == "可靠性"
    assignments = {a["source_id"]: a["category"] for a in report["classifications"]}
    block = next(b for b in report["source_blocks"] if b["text"] == METRICS["长期通电可靠性"])
    assert assignments[block["id"]] == "reliability"
    content = {}
    _merge_classified_content(content, report, str(MAPPING), document)
    reliable = content["role:reliability"]
    assert METRICS["长期通电可靠性"] in reliable["lines"] + [
        e["text"] for e in reliable["ordered_elements"] if e["kind"] == "paragraph"]
    environmental = content["role:environmental_adaptability"]
    assert METRICS["长期通电可靠性"] not in environmental["lines"] + [
        e["text"] for e in environmental["ordered_elements"] if e["kind"] == "paragraph"]


def test_filter_interface_projections_preserve_original_structure(classified):
    document, report, _, _ = classified
    content = {}
    _merge_classified_content(content, report, str(MAPPING), document)
    assert normalize_source_display_text(STRUCTURE) in [normalize_source_display_text(e["text"])
        for e in content["role:product_composition"]["ordered_elements"] if e["kind"] == "paragraph"]
    for role, expected in {
        "installation_method": "板装穿墙式/线缆对接式可选",
        "installation_dimension": "螺纹规格1/4-36UNS，外导体内径4.13mm",
    }.items():
        assert expected in content[f"role:{role}"]["lines"]
        for evidence in content[f"role:{role}"]["projection_audit"]:
            source = next(b["text"] for b in report["source_blocks"] if b["id"] == evidence["source_id"])
            assert evidence["text"] in source


@pytest.mark.parametrize("name", ["高低温循环", "湿热", "振动", "盐雾"])
def test_filter_test_and_trial_wording_resolve_to_same_complete_requirement(name):
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    for wording in ("试验", "测试"):
        source = METRICS[name].replace("试验", wording)
        report = {
            "source_blocks": [{"id": "test-clause", "type": "paragraph", "text": source,
                               "heading_text": "工作环境条件"}],
            "classifications": [{"source_id": "test-clause", "category": "environmental_adaptability"}],
        }
        facts = extract_indicator_facts(report, profile["indicator_map"])
        assert len(facts) == 1
        assert facts[0]["indicator_name"] == name
        assert facts[0]["source_value"] == source
