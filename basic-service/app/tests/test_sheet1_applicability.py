"""Workbook Sheet1 C3:C6/B7: select the applicable specification before comparing."""
import pytest
from jonhon_taskbook.fill import _match_spec_table_indicator


def row(value, *, qualifiers=None, condition='', scope='', kind=''):
    return {
        'name': '接触电阻', 'value': value, 'display_value': value,
        'qualifiers': qualifiers or {}, 'condition': condition,
        'scope': scope, 'value_kind': kind, 'section': '技术要求', 'caption': '电性能',
    }


def select(items, text='', **kwargs):
    return _match_spec_table_indicator(
        {'接触电阻': items}, {'name': '接触电阻'}, user_requirement=text, **kwargs,
    )


def test_only_requested_contact_grade_is_selected():
    result = select([
        row('≤10 mΩ', qualifiers={'接触件规格': '#22D'}),
        row('≤5 mΩ', qualifiers={'接触件规格': '#20'}),
    ], '#20 接触件的接触电阻不超过8 mΩ。')
    assert result['value'] == '≤5 mΩ'
    assert not result['manual_review_required']


def test_unspecified_contact_grade_requires_clarification_with_all_candidates():
    items = [row('≤10 mΩ', qualifiers={'接触件规格': '#22D'}),
             row('≤5 mΩ', qualifiers={'接触件规格': '#20'})]
    result = select(items, '接触电阻不超过8 mΩ。')
    assert result['manual_review_required']
    assert result['value'] == ''
    assert result['candidate_items'] == items
    assert result['status'] == 'SPEC_GRADE_UNSPECIFIED'


def test_unmentioned_environment_uses_only_normal_before_test_conditions():
    result = select([
        row('≤5 mΩ', condition='常温，试验前'),
        row('≤10 mΩ', condition='-55℃，试验后'),
    ], '接触电阻不超过8 mΩ。')
    assert result['value'] == '≤5 mΩ'
    assert result['default_conditions_applied']


def test_explicit_test_condition_beats_normal_default():
    result = select([
        row('≤5 mΩ', condition='常温'), row('≤10 mΩ', condition='-55℃'),
    ], '在-55℃下接触电阻≤12 mΩ。')
    assert result['value'] == '≤10 mΩ'
    assert not result['manual_review_required']


def test_absent_matching_condition_is_not_comparable():
    result = select([row('≤5 mΩ', condition='常温')], '在-55℃下接触电阻≤12 mΩ。')
    assert result['manual_review_required']
    assert result['status'] == 'SPEC_CONDITION_MISMATCH'
    assert result['value'] == ''


def test_typical_value_is_reference_and_maximum_is_used():
    result = select([row('3 mΩ', kind='typ'), row('5 mΩ', kind='max')], '接触电阻≤8 mΩ。')
    assert '5 mΩ' in result['value']
    assert '3 mΩ' not in result['value']
    assert result['reference_items'][0]['value_kind'] == 'typ'


def test_unrecognized_condition_is_not_lost_next_to_normal_temperature():
    result = select([row('≤5 mΩ', condition='常温，耐油试验等级B')], '接触电阻≤8 mΩ。')
    assert result['manual_review_required']
    assert result['value'] == ''


def test_source_exact_model_is_selected_without_prefix_collision():
    result = select([row('≤5 mΩ', scope='J599A'), row('≤10 mΩ', scope='J599A-20')],
                    '接触电阻≤12 mΩ。', model_context='产品型号：J599A-20')
    assert result['value'] == '≤10 mΩ'


def test_multiple_models_in_source_require_matching_indicator_clarification():
    result = select([row('≤5 mΩ', scope='J599A'), row('≤10 mΩ', scope='J599B')],
                    '接触电阻≤12 mΩ。', model_context='适用型号：J599A、J599B')
    assert result['manual_review_required']
    assert result['status'] == 'SPEC_MULTIPLE_MODELS'


def test_clarification_cannot_change_existing_test_temperature():
    with pytest.raises(ValueError, match='冲突'):
        select([row('≤5 mΩ', condition='常温'), row('≤10 mΩ', condition='-55℃')],
               '在-55℃下接触电阻≤12 mΩ。', clarification='条件：常温')


def test_clarification_can_select_one_of_several_models_but_not_override_one():
    candidates = [row('≤5 mΩ', scope='J599A'), row('≤10 mΩ', scope='J599B')]
    clarified = select(candidates, '接触电阻≤12 mΩ。', model_context='适用型号：J599A、J599B', clarification='型号：J599B')
    assert clarified['value'] == '≤10 mΩ'
    with pytest.raises(ValueError, match='冲突'):
        select(candidates, '接触电阻≤12 mΩ。', model_context='型号：J599A', clarification='型号：J599B')


@pytest.mark.parametrize('context,condition', [
    ('电性能（0.1MPa,0.9MPa）', '0.1MPa,0.5MPa'),
    ('非干态试验', '干态'),
    ('试验前和试验后', '试验前'),
])
def test_multiple_or_negated_conditions_never_auto_adopt_first_group(context, condition):
    result = select([row('≤4mΩ', condition=condition)], '接触电阻≤5mΩ', source_context=context)
    assert result['manual_review_required']
    assert result['value'] == ''


def test_general_row_cannot_hide_missing_grade_but_exact_grade_takes_precedence():
    candidates = [row('≤10mΩ'), row('≤5mΩ', qualifiers={'接触件规格': '#20'})]
    unknown = select(candidates, '接触电阻≤8mΩ')
    assert unknown['manual_review_required']
    known = select(candidates, '#20接触电阻≤8mΩ')
    assert not known['manual_review_required']
    assert known['value'] == '≤5mΩ'


@pytest.mark.parametrize('field,text', [('线规', 'AWG20'), ('壳体号', '壳体号20')])
def test_dimension_number_is_not_confused_with_requirement_value(field, text):
    items = [row('≤5 mΩ', qualifiers={field: '20'}), row('≤8 mΩ', qualifiers={field: '22'})]
    unknown = select(items, '接触电阻≤20 mΩ。')
    assert unknown['manual_review_required']
    chosen = select(items, f'{text}，接触电阻≤20 mΩ。')
    assert chosen['value'] == '≤5 mΩ'
