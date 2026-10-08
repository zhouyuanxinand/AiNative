"""Exercise supplied optical-cable template using this run's own evidence."""
from pathlib import Path

from docx import Document

from jonhon_taskbook.fill import fill
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks, _configured_category_slots
from jonhon_taskbook.template_registry import resolve_template_selection
from jonhon_taskbook.template_scanner import scan_template_tree
from jonhon_taskbook.requirement_classifier import load_category_mapping
from jonhon_taskbook.template_versions import validate_replacement


def _generate(tmp_path, items):
    selected = resolve_template_selection("optical_cable_assembly", "military")
    source = Document()
    for title, text, _category in items:
        source.add_heading(title, level=1)
        source.add_paragraph().add_run(text).bold = True
        if title == "标识及接线表":
            table = source.add_table(rows=2, cols=2)
            table.cell(0, 0).text = "光缆端点"
            table.cell(0, 1).text = "对应通道"
            table.cell(1, 0).text = "OPT-CABLE-END-A17"
            table.cell(1, 1).text = "本次来源通道B23"
    tech, spec, output = (tmp_path / name for name in ("tech.docx", "spec.docx", "result.docx"))
    source.save(tech)
    Document().save(spec)
    blocks = extract_source_blocks(str(tech), "tech")
    categories = {title: category for title, _, category in items}
    classification = {
        "source_blocks": blocks,
        "classifications": [{"source_id": block["id"], "category": categories[block["heading_text"]]} for block in blocks],
    }
    fill(
        str(tech), str(spec), selected.template_path, str(output), selected.profile_path,
        category_mapping_path=selected.category_mapping_path,
        requirement_classification=classification,
        controlled_product_label=selected.product_type_label,
        controlled_product_domain="military", product_series="光缆独立合成验证系列",
        organization_scope="non_central_research", preserve_unfilled_template=True,
        finalize=False,
    )
    return selected, Document(output), output


def _section_body(doc, path, title_prefix):
    tree = scan_template_tree(str(path))
    node = next(item for item in tree if item["title"].startswith(title_prefix))
    end = next((item for item in tree if item["paragraph_index"] > node["paragraph_index"] and item["level"] <= node["level"]), None)
    stop = doc.paragraphs[end["paragraph_index"]]._p if end else None
    element = doc.paragraphs[node["paragraph_index"]]._p.getnext()
    texts = []
    while element is not None and element is not stop:
        texts.extend(element.xpath(".//w:t/text()"))
        element = element.getnext()
    return "\n".join(texts)


def test_optical_cable_template_routes_every_configured_destination():
    selected = resolve_template_selection("optical_cable_assembly", "military")
    mapping = load_category_mapping(selected.category_mapping_path)
    slots = _configured_category_slots(scan_template_tree(selected.template_path), selected.category_mapping_path)
    expected = {key for key, rule in mapping["categories"].items() if rule.get("target_heading_keywords")}
    assert expected == set(slots)
    validation = validate_replacement(Path(selected.template_path), Path(selected.category_mapping_path), Path(selected.template_path))
    assert validation["passed"], validation["problems"]


def test_optical_cable_wiring_table_and_installation_evidence_keep_distinct_sections(tmp_path):
    items = [
        ("标识及接线表", "本次光缆采用A17至B23端点编号，并按来源表逐通道核对。", "contact_arrangement"),
        ("尾部光缆弯曲空间", "机箱尾部应预留83毫米安装空间，光缆以弧形限位夹固定。", "installation_dimension"),
        ("开口尺寸", "安装开口尺寸为17毫米，公差正负0.1毫米。", "aperture_dimension"),
        ("操作要求", "本次分支安装必须先拆卸保护帽，再按通道顺序插接。", "operation_requirement"),
        ("工艺要求", "本次装配使用定位治具CABLE-17，完成后检查端面清洁度。", "process_requirement"),
    ]
    _selected, doc, output = _generate(tmp_path, items)
    for title, evidence, _category in items:
        target = _section_body(doc, output, title)
        assert evidence in target
        paragraphs = [p for p in doc.paragraphs if p.text == evidence]
        assert len(paragraphs) == 1
        assert any(run.bold for run in paragraphs[0].runs if run.text)
    wiring = _section_body(doc, output, "标识及接线表")
    assert "OPT-CABLE-END-A17" in wiring and "本次来源通道B23" in wiring
    assert "OPT-CABLE-END-A17" not in _section_body(doc, output, "技术指标")


def test_optical_cable_static_dynamic_and_optical_values_are_not_template_examples(tmp_path):
    items = [
        ("插入损耗", "插入损耗：≤0.37 dB。", "performance_indicator"),
        ("工作波长", "工作波长：1550 nm。", "performance_indicator"),
        ("带状光缆最小弯曲半径（静态）", "带状光缆最小弯曲半径（静态）：30 mm。", "performance_indicator"),
        ("带状光缆最小弯曲半径（动态）", "带状光缆最小弯曲半径（动态）：60 mm。", "performance_indicator"),
    ]
    _selected, doc, _output = _generate(tmp_path, items)
    table = next(table for table in doc.tables if "用户要求指标" in "".join(cell.text for cell in table.rows[0].cells))
    rows = {row.cells[0].text.strip(): [cell.text.strip() for cell in row.cells] for row in table.rows[1:]}
    for title, source, _category in items:
        value = source.split("：", 1)[1]
        assert rows[title][1] == rows[title][2]
        assert rows[title][1] in (value, source)
        assert "用户要求" in rows[title][3]
    assert "1310" not in rows["工作波长"][1]
