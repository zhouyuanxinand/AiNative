"""Exercise the September optical, board, chassis and system templates without an LLM."""

import json
from pathlib import Path

import pytest
import yaml
from docx import Document
from docx.oxml.ns import qn

from jonhon_taskbook.fill import fill
from jonhon_taskbook.postprocess import postprocess
from jonhon_taskbook.product_router import load_profile
from jonhon_taskbook.requirement_classifier import load_category_mapping
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks
from jonhon_taskbook.template_registry import list_product_catalog, resolve_template_selection
from jonhon_taskbook.template_scanner import scan_template_tree


ADDITIONAL_PRODUCTS = (
    ("optical_connector", "光连接器", "optical_connector"),
    ("printed_board_assembly", "印制板组件", "printed_board_assembly"),
    ("chassis", "机箱", "chassis"),
    ("mounting_plate", "安装板", "chassis"),
    ("optical_distribution_box", "光布线箱", "chassis"),
    ("mounting_frame", "安装架", "system_integration"),
    ("equipment_cabinet", "设备柜", "system_integration"),
    ("display_console", "显控台", "system_integration"),
    ("optical_cable_assembly", "光缆组件", "optical_cable_assembly"),
    ("liquid_cooling_connector", "液冷产品-液冷连接器", "liquid_cooling_connector"),
)
TEMPLATE_FAMILIES = (
    "optical_connector", "printed_board_assembly", "chassis", "mounting_frame",
    "optical_cable_assembly", "liquid_cooling_connector",
)


@pytest.mark.parametrize("product,label,family", ADDITIONAL_PRODUCTS)
def test_additional_products_use_supplied_template_and_distinct_product_profile(product, label, family):
    selected = resolve_template_selection(product, "military")
    profile, _, _ = load_profile("", explicit_profile=selected.profile_path)
    assert selected.product_type == product
    assert selected.product_type_label == label
    assert Path(selected.template_path).name == f"{family}_taskbook.docx"
    assert Path(selected.category_mapping_path).name == f"{family}_requirement_categories.yaml"
    assert Path(selected.profile_path).name == f"{product}_profile.yaml"
    assert profile["profile_id"] == product
    assert profile["product_type"] == label
    entry = next(entry for entry in list_product_catalog() if entry["value"] == product)
    assert entry["enabled"] and entry["configured_enabled"]
    assert entry["integration_status"] == "available"
    assert entry["domains"] == [{"value": "military", "label": "军品"}]


@pytest.mark.parametrize("product,reason", [
    ("optical_cable_assembly", "光缆"), ("liquid_cooling_connector", "流体"),
])
@pytest.mark.parametrize("allow_disabled", ("false", "true"))
def test_missing_template_cannot_be_enabled_or_fall_back_to_another_family(
    tmp_path, monkeypatch, product, reason, allow_disabled,
):
    monkeypatch.setenv("JTB_CATALOG_ALLOW_DISABLED", allow_disabled)
    # Exercise the missing-asset policy independently of the supplied products,
    # which are now all integrated. A generic fallback must not bypass it.
    catalog = tmp_path / "missing-template.yaml"
    catalog.write_text(yaml.safe_dump({"product_types": {product: {
        "label": reason, "enabled": False, "integration_status": "missing_template",
        "unavailable_reason": f"尚未提供{reason}模板",
        "domains": {"military": {"label": "军品", "template": "connector_taskbook.docx"}},
    }}}, allow_unicode=True), encoding="utf-8")
    entry = next(entry for entry in list_product_catalog(catalog) if entry["value"] == product)
    assert entry["integration_status"] == "missing_template"
    assert not entry["enabled"]
    assert reason in entry["unavailable_reason"]
    with pytest.raises(ValueError, match=reason):
        resolve_template_selection(product, "military", catalog)


@pytest.mark.parametrize("old_product,old_template,new_product", [
    ("high_speed_backplane", "connector_taskbook.docx", "printed_board_assembly"),
    ("liquid_cooling_chassis", "liquid_cooling_chassis_taskbook.docx", "chassis"),
    ("cable_assembly", "cable_assembly_taskbook.docx", "mounting_frame"),
    ("cable_assembly", "cable_assembly_taskbook.docx", "optical_cable_assembly"),
    ("optical_connector", "optical_connector_taskbook.docx", "optical_cable_assembly"),
    ("liquid_cooling_pipeline", "liquid_cooling_pipeline_taskbook.docx", "liquid_cooling_connector"),
])
def test_related_existing_products_keep_their_original_template(old_product, old_template, new_product):
    existing = resolve_template_selection(old_product, "military")
    new = resolve_template_selection(new_product, "military")
    assert Path(existing.template_path).name == old_template
    assert existing.template_path != new.template_path
    assert existing.profile_path != new.profile_path
    assert existing.category_mapping_path != new.category_mapping_path


def _empty_sources(tmp_path):
    tech, spec = (tmp_path / name for name in ("tech.docx", "spec.docx"))
    Document().save(tech)
    Document().save(spec)
    return tech, spec


def _fill(selected, tech, spec, output, classification, **options):
    fill(
        str(tech), str(spec), selected.template_path, str(output), selected.profile_path,
        category_mapping_path=selected.category_mapping_path,
        requirement_classification=classification,
        controlled_product_label=selected.product_type_label,
        controlled_product_domain="military", product_series="新增类型合成验证系列",
        organization_scope="non_central_research",
        preserve_unfilled_template=True, finalize=False, **options,
    )


def _process_sections(document):
    paragraphs = ["".join(paragraph.text.split()) for paragraph in document.paragraphs]
    return {
        "qfd": any("QFD质量功能分解" in paragraph for paragraph in paragraphs),
        "scene": any(paragraph.startswith("产品运行场景识别") for paragraph in paragraphs),
        "appendix_a": any(paragraph.startswith("附录A") for paragraph in paragraphs),
    }


@pytest.mark.parametrize("product", TEMPLATE_FAMILIES)
@pytest.mark.parametrize("process", ("全新", "改型I", "改型II", "改型III"))
def test_additional_template_process_rules_preserve_following_sections_and_page_setup(tmp_path, product, process):
    selected = resolve_template_selection(product, "military")
    template = Document(selected.template_path)
    original = _process_sections(template)
    assert original["scene"] and original["appendix_a"]
    tech, spec = _empty_sources(tmp_path)
    output = tmp_path / "filled.docx"
    _fill(selected, tech, spec, output, {"source_blocks": [], "classifications": []}, development_process=process)
    filled = Document(output)
    assert filled.element.body.find(qn("w:sectPr")) is not None
    assert filled.sections[-1].page_width == template.sections[-1].page_width
    postprocess(output, preserve_template_guidance=True, selected_product_domain="military")
    document = Document(output)
    assert _process_sections(document) == {
        "qfd": original["qfd"] and process == "全新",
        "scene": process in {"全新", "改型I"},
        "appendix_a": process in {"全新", "改型I"},
    }
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "任务书编制依据" in text
    assert "以前类似设计提供的信息" in text
    assert "工艺要求" in text
    if product in {"optical_cable_assembly", "liquid_cooling_connector"}:
        # These supplied appendices place a guidance paragraph after the
        # heading. Deleting only the heading must not leave that paragraph.
        appendix_instruction = "应对技术协议、技术要求等用户文件中的全部环境性能指标逐条进行场景识别"
        assert (appendix_instruction in text) == (process in {"全新", "改型I"})
    assert document.element.body.find(qn("w:sectPr")) is not None
    audit = json.loads(output.with_suffix(".process_rule_audit.json").read_text(encoding="utf-8"))
    assert ("附录A" in audit["deleted_semantic_headings"]) == (process in {"改型II", "改型III"})


@pytest.mark.parametrize("product,indicator,source_text,value", [
    ("optical_connector", "插入损耗", "插入损耗：≤0.37 dB。", "≤0.37 dB。"),
    ("chassis", "散热性能", "散热性能：散热功率不低于270 W。", "散热功率不低于270 W。"),
])
def test_new_indicator_tables_use_requirement_values_not_template_examples(tmp_path, product, indicator, source_text, value):
    selected = resolve_template_selection(product, "military")
    tech, spec = _empty_sources(tmp_path)
    source = Document()
    source.add_heading(indicator, level=1)
    source.add_paragraph(source_text)
    source.save(tech)
    output = tmp_path / "filled.docx"
    _fill(selected, tech, spec, output, {
        "source_blocks": [{"id": "performance-evidence", "kind": "paragraph",
                           "heading_text": indicator, "section": indicator, "text": source_text}],
        "classifications": [{"source_id": "performance-evidence", "category": "performance_indicator"}],
    })
    rows = [[cell.text.strip() for cell in row.cells] for table in Document(output).tables for row in table.rows]
    matches = [row for row in rows if row[0] == indicator]
    assert len(matches) == 1, matches
    assert matches[0][1] == matches[0][2] == value
    assert "用户要求" in matches[0][3]
    audit = json.loads(output.with_suffix(".indicator_audit.json").read_text(encoding="utf-8"))
    assert any(fact["source_value"] == source_text for fact in audit["input_indicator_facts"])


def _section_text(document, output, title):
    tree = scan_template_tree(str(output))
    section = next(node for node in tree if node["title"] == title)
    next_section = next((node for node in tree
                         if node["paragraph_index"] > section["paragraph_index"]
                         and node["level"] <= section["level"]), None)
    stop = document.paragraphs[next_section["paragraph_index"]]._p if next_section else None
    element = document.paragraphs[section["paragraph_index"]]._p.getnext()
    texts = []
    while element is not None and element is not stop:
        texts.extend(element.xpath(".//w:t/text()"))
        element = element.getnext()
    return "\n".join(texts)


@pytest.mark.parametrize("product,heading,neighbor,evidence", [
    ("printed_board_assembly", "信号定义", "接口及键位要求", "接口 B9 的数据通道定义为 TEST-DATA47。"),
    ("mounting_frame", "绝缘电阻", "电气连续性", "绝缘电阻：施加 DC 750V 时应不小于 47MΩ。"),
])
def test_templates_without_indicator_grid_copy_source_text_and_tables_to_matching_chapter(
    tmp_path, product, heading, neighbor, evidence,
):
    selected = resolve_template_selection(product, "military")
    template = Document(selected.template_path)
    assert not any("用户要求指标" in "".join(cell.text for cell in table.rows[0].cells)
                   for table in template.tables)
    mapping = load_category_mapping(selected.category_mapping_path)
    roles = [category for category, rule in mapping["categories"].items()
             if not rule.get("container_only")
             and any(keyword in heading for keyword in rule.get("target_heading_keywords", []))]
    assert len(roles) == 1, (heading, roles)
    tech, spec = _empty_sources(tmp_path)
    source = Document()
    source.add_heading(heading, level=1)
    source.add_paragraph().add_run(evidence).bold = True
    table = source.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "测试点"
    table.cell(0, 1).text = "本次要求"
    table.cell(1, 0).text = "新模板合成试验点 B9"
    table.cell(1, 1).text = "保留本次来源测试表格"
    source.save(tech)
    blocks = extract_source_blocks(str(tech), "tech")
    output = tmp_path / "filled.docx"
    _fill(selected, tech, spec, output, {
        "source_blocks": blocks,
        "classifications": [{"source_id": block["id"], "category": roles[0]} for block in blocks],
    })
    document = Document(output)
    target = _section_text(document, output, heading)
    assert evidence in target
    assert "新模板合成试验点 B9" in target
    assert "保留本次来源测试表格" in target
    assert evidence not in _section_text(document, output, neighbor)
    copied = [paragraph for paragraph in document.paragraphs if paragraph.text == evidence]
    assert len(copied) == 1
    assert any(run.bold for run in copied[0].runs if run.text == evidence)
    assert sum("新模板合成试验点 B9" in cell.text
               for table in document.tables for row in table.rows for cell in row.cells) == 1
