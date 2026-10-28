"""Spreadsheet rules exercised across extraction, selection and table writing."""
import pytest
from docx import Document
from jonhon_taskbook.fill import _fill_indicator_table, build_content, parse_doc


def generate(tmp_path, value, headers, spec_rows, *, clarification='', indicator='接触电阻'):
    tech = Document()
    tech.add_heading(indicator, level=1)
    if value:
        tech.add_paragraph(value)
    tech_path = tmp_path / '技术要求.docx'
    tech.save(tech_path)
    spec = Document()
    spec.add_paragraph('Q/JH 123-2026 产品规范')
    spec.add_heading('电气性能', level=1)
    table = spec.add_table(rows=1, cols=len(headers))
    for cell, text in zip(table.rows[0].cells, headers):
        cell.text = text
    for source in spec_rows:
        for cell, text in zip(table.add_row().cells, source):
            cell.text = text
    spec_path = tmp_path / '规范.docx'
    spec.save(spec_path)
    template = Document()
    table = template.add_table(rows=2, cols=5)
    for cell, text in zip(table.rows[0].cells, ['项目', '用户要求', '标准要求', '拟采用', '依据']):
        cell.text = text
    table.rows[1].cells[0].text = indicator
    cfg = {'semantic_structures': {'performance_indicator': {'mode': 'indicator_table'}},
           'indicator_sources': {'workbook': False, 'reference_families': []},
           'indicator_map': {'电性能': [{'name': indicator, 'tech_kws': [indicator]}]}}
    classification = {'source_blocks': [], 'classifications': []}
    if value:
        classification = {
            'source_blocks': [{'id': 'p1', 'type': 'paragraph', 'text': value,
                               'heading_text': indicator, 'body_index': 1}],
            'classifications': [{'source_id': 'p1', 'category': 'performance_indicator'}],
        }
    content = build_content(cfg, tech, spec, parse_doc(tech), parse_doc(spec), str(tech_path),
                            str(spec_path), template_doc=template, requirement_classification=classification,
                            indicator_clarifications={indicator: clarification} if clarification else None)
    result = content['role:performance_indicator']
    _fill_indicator_table(template, result['indicator_rows'])
    return result, table


def decision(result):
    return next(item for item in result['indicator_comparison_audit'] if item['indicator_name'] == '接触电阻')


def test_selected_contact_grade_compares_and_preserves_specification_basis(tmp_path):
    result, table = generate(tmp_path, '#20 接触件的接触电阻不超过8 mΩ。',
                             ['项目', '接触件规格', '要求'],
                             [['接触电阻', '#22D', '≤10 mΩ'], ['接触电阻', '#20', '≤5 mΩ']])
    chosen = decision(result)
    assert chosen['numeric_status'] == 'stricter_standard'
    assert not chosen['manual_review_required']
    assert '5 mΩ' in chosen['adopted_requirement']
    assert 'Q/JH' in table.rows[1].cells[4].text
    assert '#20' in table.rows[1].cells[1].text


def test_matching_temperature_is_context_not_an_extra_threshold(tmp_path):
    result, _ = generate(tmp_path, '在-55℃下接触电阻≤12 mΩ。', ['项目', '测试条件', '要求'],
                         [['接触电阻', '常温', '≤5 mΩ'], ['接触电阻', '-55℃', '≤10 mΩ']])
    assert decision(result)['numeric_status'] == 'stricter_standard'
    assert not decision(result)['manual_review_required']


def test_unspecified_grade_marker_and_all_candidates_remain_visible(tmp_path):
    result, table = generate(tmp_path, '接触电阻≤8 mΩ。', ['项目', '接触件规格', '要求'],
                             [['接触电阻', '#22D', '≤10 mΩ'], ['接触电阻', '#20', '≤5 mΩ']])
    chosen = decision(result)
    assert chosen['manual_review_required']
    assert len(chosen['candidate_comparisons']) == 2
    adopted = table.rows[1].cells[3]
    assert '#22D' in adopted.text and '#20' in adopted.text
    markers = [run for p in adopted.paragraphs for run in p.runs if run.text == '【人工填写】']
    assert markers and all(str(run.font.color.rgb) == 'FF0000' for run in markers)


def test_missing_user_value_uses_existing_template_indicator_spec_and_backslash(tmp_path):
    result, table = generate(tmp_path, '', ['项目', '要求'], [['接触电阻', '≤5 mΩ']])
    assert decision(result)['numeric_status'] == 'standard_only'
    assert table.rows[1].cells[1].text == '\\'
    assert '5 mΩ' in table.rows[1].cells[3].text
    assert 'Q/JH' in table.rows[1].cells[4].text


def test_clarification_selects_grade_without_rewriting_user_requirement(tmp_path):
    result, table = generate(tmp_path, '接触电阻≤8 mΩ。', ['项目', '接触件规格', '要求'],
                             [['接触电阻', '#22D', '≤10 mΩ'], ['接触电阻', '#20', '≤5 mΩ']],
                             clarification='规格：#20')
    assert not decision(result)['manual_review_required']
    assert table.rows[1].cells[1].text == '接触电阻≤8 mΩ。'
    assert decision(result)['clarification'] == '规格：#20'


def test_clarification_cannot_override_source_grade(tmp_path):
    with pytest.raises(ValueError, match='冲突'):
        generate(tmp_path, '#20 接触电阻≤8 mΩ。', ['项目', '接触件规格', '要求'],
                 [['接触电阻', '#22D', '≤10 mΩ'], ['接触电阻', '#20', '≤5 mΩ']],
                 clarification='规格：#22D')


def test_measured_pressure_is_not_misread_as_test_condition(tmp_path):
    result, _ = generate(tmp_path, '工作压力≥0.8 MPa', ['项目', '测试条件', '要求'],
                         [['工作压力', '常温', '≥1.0 MPa']], indicator='工作压力')
    chosen = result['indicator_comparison_audit'][0]
    assert chosen['status'] == 'SPEC_APPLICABLE'
    assert chosen['numeric_status'] == 'stricter_standard'


def test_equivalent_after_test_wording_is_comparable(tmp_path):
    result, _ = generate(tmp_path, '测试后接触电阻≤8 mΩ', ['项目', '测试条件', '要求'],
                         [['接触电阻', '试验后', '≤5 mΩ']])
    assert not decision(result)['manual_review_required']
    assert decision(result)['numeric_status'] == 'stricter_standard'


def test_equivalent_test_pressure_units_are_comparable(tmp_path):
    result, _ = generate(tmp_path, '在100 kPa下接触电阻≤8 mΩ', ['项目', '测试条件', '要求'],
                         [['接触电阻', '0.1 MPa', '≤5 mΩ']])
    assert not decision(result)['manual_review_required']
    assert decision(result)['numeric_status'] == 'stricter_standard'


def test_equal_test_pressure_and_measured_value_are_not_both_removed(tmp_path):
    result, _ = generate(tmp_path, '在0.5MPa下，额定压力0.5MPa', ['项目', '测试条件', '最小值'],
                         [['额定压力', '0.5MPa', '0.8MPa']], indicator='额定压力')
    chosen = result['indicator_comparison_audit'][0]
    assert chosen['manual_review_required']
    assert chosen['numeric_status'] == 'manual_review'


def test_frequency_condition_has_numeric_boundaries(tmp_path):
    result, _ = generate(tmp_path, '11MHz测试，接触电阻≤5mΩ', ['项目', '测试条件', '最大值'],
                         [['接触电阻', '1MHz', '4mΩ']])
    assert decision(result)['manual_review_required']
    assert decision(result)['status'] == 'SPEC_CONDITION_MISMATCH'
