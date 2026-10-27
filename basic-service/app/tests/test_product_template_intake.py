"""Exercise the supplied templates through catalog selection and real fill."""
import json
from pathlib import Path

import pytest
import yaml
from docx import Document
from fastapi.testclient import TestClient
from jonhon_taskbook.fill import fill
from jonhon_taskbook.product_router import load_profile
from jonhon_taskbook.requirement_classifier import (
    build_requirement_classification,
    load_category_mapping,
)
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks
from jonhon_taskbook.template_registry import (
    list_product_catalog,
    resolve_template_selection,
)
from jonhon_taskbook.template_scanner import scan_template_tree

NEW_PRODUCTS = (
    'low_frequency_circular', 'low_frequency_twist_pin',
    'rf_contact', 'rf_hybrid', 'rf_standard_interface', 'filter_connector',
    'cable_assembly', 'liquid_cooling_pipeline', 'liquid_cooling_chassis',
    'high_speed_backplane', 'high_speed_io', 'end_contact_pogo',
    'end_contact_finger', 'separation_connector', 'watertight_connector',
    'optical_connector', 'printed_board_assembly', 'chassis', 'mounting_plate',
    'optical_distribution_box', 'mounting_frame', 'equipment_cabinet', 'display_console',
    'optical_cable_assembly', 'liquid_cooling_connector',
)
SPECIAL_CASES = (
    ('rf_contact', 'rf_connector_taskbook.docx', '阻抗', '阻抗：50 Ω。', '50 Ω。'),
    ('rf_hybrid', 'rf_connector_taskbook.docx', '工作频率', '工作频率：3 GHz。', '3 GHz。'),
    ('rf_standard_interface', 'rf_connector_taskbook.docx', '电压驻波比', '电压驻波比：1.25。', '1.25。'),
    ('filter_connector', 'filter_connector_taskbook.docx', '截止频率', '截止频率：12 MHz。', '12 MHz。'),
    ('cable_assembly', 'cable_assembly_taskbook.docx', '屏蔽要求', '屏蔽要求：屏蔽层完整连续。', '屏蔽层完整连续。'),
    ('liquid_cooling_pipeline', 'liquid_cooling_pipeline_taskbook.docx', '最大工作压力', '最大工作压力：0.8 MPa。', '0.8 MPa。'),
    ('liquid_cooling_chassis', 'liquid_cooling_chassis_taskbook.docx', '流阻', '流阻：0.05 MPa。', '0.05 MPa。'),
)


def test_catalog_api_publishes_all_products_with_supplied_templates(monkeypatch):
    monkeypatch.delenv('JTB_CATALOG_ALLOW_DISABLED', raising=False)
    from src.main import create_app

    response = TestClient(create_app()).get('/api/product_catalog')
    assert response.status_code == 200
    products = response.json()['product_types']
    assert len(products) == 27
    assert {p['value'] for p in products if p['enabled']} == {
        'low_frequency_rectangular', 'end_contact_spring_pin',
    } | set(NEW_PRODUCTS)
    for product in products:
        if product['value'] in NEW_PRODUCTS:
            assert product['configured_enabled']
            assert product['integration_status'] == 'available'
            assert not product['unavailable_reason']
    assert all(product['enabled'] for product in products)


def test_existing_fluid_selection_alias_resolves_new_controlled_assets():
    expected = resolve_template_selection('liquid_cooling_connector', 'military')
    assert resolve_template_selection('fluid_connector', 'military') == expected
    assert Path(expected.template_path).name == 'liquid_cooling_connector_taskbook.docx'


@pytest.mark.parametrize('product', NEW_PRODUCTS)
def test_each_enabled_product_resolves_real_assets_and_unambiguous_slots(product, monkeypatch):
    monkeypatch.delenv('JTB_CATALOG_ALLOW_DISABLED', raising=False)
    entry = next(p for p in list_product_catalog() if p['value'] == product)
    for domain in entry['domains']:
        selected = resolve_template_selection(product, domain['value'])
        profile, _, _ = load_profile('', explicit_profile=selected.profile_path)
        assert profile['profile_id'] == product
        mapping = load_category_mapping(selected.category_mapping_path)
        slots = scan_template_tree(selected.template_path)
        by_id = {slot['id']: slot for slot in slots}
        for role, rule in {**mapping['semantic_roles'], **mapping['categories']}.items():
            if rule.get('container_only'):
                assert rule['block_target_categories']
                assert rule['block_fallback_category'] in rule['block_target_categories']
                assert all(target in mapping['categories']
                           for target in rule['block_target_categories'])
                continue
            headings = rule.get('target_heading_keywords', [])
            matches = [slot for slot in slots
                       if any(heading in slot['title'] for heading in headings)
                       and (not rule.get('target_heading_level')
                            or rule['target_heading_level'] == slot['level'])
                       and (not rule.get('target_parent_heading')
                            or rule['target_parent_heading'] == by_id.get(slot['parent_id'], {}).get('title'))]
            assert len(matches) == 1, (product, domain['value'], role, matches)


@pytest.mark.parametrize('product,template_name,indicator,source_text,display_value', SPECIAL_CASES)
def test_specialized_indicator_survives_real_template_fill(
    product, template_name, indicator, source_text, display_value, tmp_path, monkeypatch,
):
    monkeypatch.delenv('JTB_CATALOG_ALLOW_DISABLED', raising=False)
    selected = resolve_template_selection(product, 'military')
    # The catalog may point to an uploaded revision of the supplied template.
    # Its product rules and the actual fill below define compatibility.
    profile, _, _ = load_profile('', explicit_profile=selected.profile_path)
    assert profile['profile_id'] == product
    source = Document()
    source.add_heading(indicator, level=1)
    source.add_paragraph(source_text)
    tech_path = tmp_path / 'technical_requirements.docx'
    source.save(tech_path)
    spec_path = tmp_path / 'product_specification.docx'
    Document().save(spec_path)
    output = tmp_path / 'review.docx'
    classification = {
        'source_blocks': [{
            'id': 'indicator-evidence', 'kind': 'paragraph',
            'heading_text': indicator, 'section': indicator, 'text': source_text,
        }],
        'classifications': [{'source_id': 'indicator-evidence', 'category': 'performance_indicator'}],
    }
    fill(
        str(tech_path), str(spec_path), selected.template_path, str(output), selected.profile_path,
        finalize=False, requirement_classification=classification,
        category_mapping_path=selected.category_mapping_path,
        preserve_unfilled_template=True, controlled_product_label=selected.product_type_label,
        controlled_product_domain='military', product_series='产品接入合成验证',
    )
    document = Document(output)
    rows = [tuple(cell.text for cell in row.cells)
            for table in document.tables for row in table.rows]
    matching = [row for row in rows if row and row[0] == indicator]
    assert len(matching) == 1, (indicator, matching)
    assert matching[0][1] == matching[0][2] == display_value
    assert '用户要求' in matching[0][3]
    # Template example values must not become extra source-derived requirements.
    source_rows = [row for row in rows if len(row) == 4 and display_value == row[1]]
    assert len(source_rows) == 1
    audit = json.loads(output.with_suffix('.indicator_audit.json').read_text(encoding='utf-8'))
    assert any(fact['source_value'] == source_text for fact in audit['input_indicator_facts'])


def test_new_templates_use_their_own_interface_chapters(monkeypatch):
    monkeypatch.delenv('JTB_CATALOG_ALLOW_DISABLED', raising=False)
    selected = resolve_template_selection('cable_assembly', 'military')
    mapping = yaml.safe_load(Path(selected.category_mapping_path).read_text(encoding='utf-8'))
    assert 'interface_definition' not in mapping['categories']
    assert mapping['categories']['wiring_connections']['target_heading_keywords'] == ['接线关系']
    assert mapping['categories']['connector_potting']['target_parent_heading'] == '线缆处理要求'
    # This source template has no dimensional interchangeability slot to reuse.
    assert 'interchangeability' not in mapping['categories']


def test_cable_wiring_table_and_potting_text_reach_their_own_chapters(tmp_path, monkeypatch):
    monkeypatch.delenv('JTB_CATALOG_ALLOW_DISABLED', raising=False)
    selected = resolve_template_selection('cable_assembly', 'military')
    tech_path, spec_path, output = (tmp_path / name for name in ('tech.docx', 'spec.docx', 'out.docx'))
    source = Document()
    source.add_heading('接线关系', level=1)
    table = source.add_table(rows=2, cols=2)
    table.cell(0, 0).text = '源端'
    table.cell(0, 1).text = '目的端'
    table.cell(1, 0).text = '合成输入 J1-01'
    table.cell(1, 1).text = '合成输入 J2-09'
    source.add_heading('连接器端面灌胶', level=1)
    evidence = '灌胶后端面应平整，不允许出现气泡。'
    source.add_paragraph().add_run(evidence).bold = True
    source.save(tech_path)
    Document().save(spec_path)
    blocks = extract_source_blocks(str(tech_path), 'tech')
    roles = {'接线关系': 'wiring_connections', '连接器端面灌胶': 'connector_potting'}
    classification = {
        'source_blocks': blocks,
        'classifications': [
            {'source_id': block['id'], 'category': roles[block['heading_text']]}
            for block in blocks
        ],
    }
    fill(
        str(tech_path), str(spec_path), selected.template_path, str(output), selected.profile_path,
        finalize=False, requirement_classification=classification,
        category_mapping_path=selected.category_mapping_path, preserve_unfilled_template=True,
    )
    result = Document(output)
    slots = scan_template_tree(str(output))

    def section_elements(title):
        slot = next(slot for slot in slots if slot['title'] == title)
        heading = result.paragraphs[slot['paragraph_index']]
        next_heading = next(
            (s for s in slots if s['paragraph_index'] > slot['paragraph_index']
             and s['level'] <= slot['level']), None,
        )
        stop = result.paragraphs[next_heading['paragraph_index']]._p if next_heading else None
        element = heading._p.getnext()
        elements = []
        while element is not None and element is not stop:
            elements.append(element)
            element = element.getnext()
        return elements

    wiring = section_elements('接线关系')
    potting = section_elements('连接器端面灌胶')
    assert any('合成输入 J1-01' in ''.join(el.itertext()) for el in wiring)
    assert any('合成输入 J2-09' in ''.join(el.itertext()) for el in wiring)
    assert not any(evidence in ''.join(el.itertext()) for el in wiring)
    assert any(evidence in ''.join(el.itertext()) for el in potting)
    copied = [p for p in result.paragraphs if p.text == evidence]
    assert len(copied) == 1
    assert copied[0].runs[0].bold


@pytest.mark.parametrize('product,heading,container,target,fallback,evidence', [
    ('cable_assembly', '线缆处理要求', 'cable_processing', 'wire_bundling', 'other', '导线每隔十厘米捆扎一次。'),
    ('liquid_cooling_chassis', '接口尺寸', 'interface_definition', 'aperture_dimension', 'interface_other', '开孔尺寸为十毫米。'),
])
def test_container_chapters_classify_members_and_preserve_unspecified_requirements(
    product, heading, container, target, fallback, evidence, tmp_path, monkeypatch,
):
    monkeypatch.delenv('JTB_CATALOG_ALLOW_DISABLED', raising=False)
    selected = resolve_template_selection(product, 'military')
    source = Document()
    source.add_heading(heading, level=1)
    source.add_paragraph(evidence)
    source.add_paragraph('特殊约定见配套图纸。')
    source_path = tmp_path / 'requirements.docx'
    source.save(source_path)

    def classify(_system, user):
        payload = json.loads(user)
        if payload['node'] == 'source_structure':
            return {'headings': []}
        assert payload['node'] == 'requirement_classification'
        return {'classifications': [
            {
                'source_id': block['source_id'],
                'category': (container if block['type'] == 'chapter'
                             else target if block['text'] == evidence else 'other'),
                'confidence': 0.99,
            }
            for block in payload['blocks']
        ]}

    result = build_requirement_classification(
        str(source_path), selected.category_mapping_path, chat_json_fn=classify,
    )
    assert result['passed']
    assert [item['category'] for item in result['classifications']] == [target, fallback]
    assert [block['text'] for block in result['source_blocks']] == [evidence, '特殊约定见配套图纸。']
