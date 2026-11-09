"""The model may find specification evidence, but cannot replace adopted requirements."""
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json

import pytest

from jonhon_taskbook import llm_client
from service.rd_platform.requirement_recommendations import propose
from service.rd_platform.store import RdError


PRESSURE = '工作压力：0.3 MPa，保压时间不少于 15 秒。'
SPEC_TEXT = '\n'.join([PRESSURE, '工作压力：0.5 MPa。', '工作压力：0.3 kPa。',
                       '工作压力：高温时 0.3 MPa。', '库存数量：15 件。'])


@pytest.fixture
def case(tmp_path):
    def source(sid, role, text):
        path = tmp_path / f'{sid}.txt'
        path.write_text(text, encoding='utf-8')
        return {'id': sid, 'role': role, 'name': path.name, 'path': str(path), 'version': 1,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return {'sources': [source('spec', 'spec', SPEC_TEXT), source('old', 'spec', '旧版规范不可引用'),
                        source('tech', 'tech', '需求：0.3 MPa。'), source('reference', 'reference', '补充资料不可代替主规范')],
            'source_selection': {'spec': 'spec', 'tech': 'tech'}, 'context': {}, 'model_selection': {},
            'requirements': [{'id': 'r1', 'revision': 2, 'title': '工作压力', 'content': '工作压力：0.3 MPa。', 'source_ids': ['tech']},
                             {'id': 'r2', 'revision': 1, 'title': '密封要求', 'content': '密封要求：待澄清。', 'source_ids': ['tech']}]}


def matched():
    return {'requirement_id': 'r1', 'status': 'matched', 'text': '补充保压时间', 'proposed_value': PRESSURE,
            'evidence': [{'source_id': 'spec', 'quote': PRESSURE}]}


def install_model(monkeypatch, payload):
    calls = []
    monkeypatch.setattr(llm_client, 'get_model_status', lambda *a: {'configured': True, 'provider': 'smartvision', 'model': 'azure/gpt-5.4'})
    monkeypatch.setattr(llm_client, 'model_scope', lambda *a: nullcontext(None))
    def chat(system, data, **kwargs):
        calls.append(json.loads(data))
        return payload(calls[-1]) if callable(payload) else deepcopy(payload)
    monkeypatch.setattr(llm_client, 'chat_json', chat)
    return calls


def response(first=None):
    return {'items': [first or matched(), {'requirement_id': 'r2', 'status': 'not_found', 'evidence': []}]}


def test_selected_spec_quotations_are_proposed_without_mutating_adopted_requirements(case, tmp_path, monkeypatch):
    original = deepcopy(case)
    calls = install_model(monkeypatch, response())
    proposal = propose(case, tmp_path / 'analysis', 'local:test')
    assert case == original
    row = proposal['items'][0]
    assert row['status'] == 'matched' and row['can_accept']
    assert row['proposed_value'] == PRESSURE
    assert row['requirement_revision'] == 2
    assert row['evidence'] == [{'source_id': 'spec', 'quote': PRESSURE}]
    assert row['source_refs'][0]['sha256'] == case['sources'][0]['sha256']
    assert row['source_refs'][0]['location']['line'] == 1
    assert proposal['items'][1]['status'] == 'not_found'
    assert 'proposed_value' not in proposal['items'][1]
    assert calls[0]['specification']['source_id'] == 'spec'
    assert '旧版规范不可引用' not in json.dumps(calls, ensure_ascii=False)
    assert '补充资料不可代替主规范' not in json.dumps(calls, ensure_ascii=False)


@pytest.mark.parametrize('clause', ['工作压力：0.5 MPa。', '工作压力：0.3 kPa。', '工作压力：高温时 0.3 MPa。'])
def test_changed_value_unit_or_condition_is_clarification_never_acceptance(case, tmp_path, monkeypatch, clause):
    item = matched()
    item.update(proposed_value=clause, evidence=[{'source_id': 'spec', 'quote': clause}])
    install_model(monkeypatch, response(item))
    row = propose(case, tmp_path / 'analysis', 'local:test')['items'][0]
    assert row['status'] == 'difference'
    assert row['evidence'][0]['quote'] == clause
    assert not row['can_accept'] and 'proposed_value' not in row
    assert case['requirements'][0]['content'] == '工作压力：0.3 MPa。'


@pytest.mark.parametrize('evidence', [
    [{'source_id': 'old', 'quote': '旧版规范不可引用'}],
    [{'source_id': 'ontology', 'quote': PRESSURE}],
    [{'source_id': 'spec', 'quote': '15 秒'}],
    [{'source_id': 'spec', 'quote': '工作压力：99 MPa。'}],
])
def test_invented_unselected_or_truncated_evidence_has_no_adoptable_value(case, tmp_path, monkeypatch, evidence):
    item = matched()
    item['evidence'] = evidence
    install_model(monkeypatch, response(item))
    result = propose(case, tmp_path / 'analysis', 'local:test')
    row = result['items'][0]
    assert row['status'] == 'needs_review' and not row['can_accept']
    assert row['evidence'] == [] and 'proposed_value' not in row
    assert result['warnings']
    assert len(result['items']) == len(case['requirements'])


def test_unrelated_metric_and_fabricated_value_cannot_be_accepted(case, tmp_path, monkeypatch):
    item = matched()
    item.update(proposed_value='工作压力：99 MPa。', evidence=[{'source_id': 'spec', 'quote': '库存数量：15 件。'}])
    install_model(monkeypatch, response(item))
    row = propose(case, tmp_path / 'analysis', 'local:test')['items'][0]
    assert row['status'] == 'needs_review' and not row['can_accept']
    assert 'proposed_value' not in row


@pytest.mark.parametrize('items', [[matched()], [matched(), matched()], [matched(), {'requirement_id': 'unknown', 'status': 'not_found'}]])
def test_missing_duplicate_or_extra_requirements_reject_partial_batch(case, tmp_path, monkeypatch, items):
    install_model(monkeypatch, {'items': items})
    before = deepcopy(case)
    with pytest.raises(RdError) as error:
        propose(case, tmp_path / 'analysis', 'local:test')
    assert error.value.status == 422
    assert case == before


def test_large_requirement_list_is_fully_covered_in_order(case, tmp_path, monkeypatch):
    case['requirements'] = [{'id': f'r{i}', 'revision': 1, 'title': f'指标{i}', 'content': f'指标{i}：待澄清。'} for i in range(32)]
    calls = install_model(monkeypatch, lambda data: {'items': [
        {'requirement_id': r['requirement_id'], 'status': 'not_found', 'evidence': []} for r in data['requirements']]})
    result = propose(case, tmp_path / 'analysis', 'local:test')
    assert [r['requirement_id'] for r in result['items']] == [r['id'] for r in case['requirements']]
    assert [len(call['requirements']) for call in calls] == [15, 15, 2]


def test_second_batch_transport_failure_leaves_adopted_values_intact(case, tmp_path, monkeypatch):
    case['requirements'] *= 8
    case['requirements'] = [{**row, 'id': str(index)} for index, row in enumerate(case['requirements'])]
    before = deepcopy(case)
    def reply(data):
        if data['requirements'][0]['requirement_id'] == '15':
            raise TimeoutError('model service')
        return {'items': [{'requirement_id': row['requirement_id'], 'status': 'not_found', 'evidence': []} for row in data['requirements']]}
    install_model(monkeypatch, reply)
    with pytest.raises(RdError) as error:
        propose(case, tmp_path / 'analysis', 'local:test')
    assert error.value.status == 502
    assert case == before


def test_missing_main_spec_does_not_fall_back_to_historical_file(case, tmp_path, monkeypatch):
    case['source_selection']['spec'] = ''
    calls = install_model(monkeypatch, response())
    with pytest.raises(RdError) as error:
        propose(case, tmp_path / 'analysis', 'local:test')
    assert error.value.status == 422 and '主产品规范' in error.value.detail
    assert calls == []


def test_changed_spec_file_fails_before_model_call(case, tmp_path, monkeypatch):
    (tmp_path / 'spec.txt').write_text('工作压力：9 MPa。', encoding='utf-8')
    calls = install_model(monkeypatch, response())
    with pytest.raises(RdError) as error:
        propose(case, tmp_path / 'analysis', 'local:test')
    assert error.value.status == 409
    assert calls == []


def replace_spec(case, tmp_path, text):
    path = tmp_path / 'spec.txt'
    path.write_text(text, encoding='utf-8')
    case['sources'][0]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()


def test_heading_and_complete_value_paragraph_keep_exact_evidence_and_value(case, tmp_path, monkeypatch):
    clause = '工作压力\n0.3 MPa，保压时间不少于 15 秒。'
    replace_spec(case, tmp_path, clause)
    item = matched()
    item.update(proposed_value=clause, evidence=[{'source_id': 'spec', 'quote': clause}])
    install_model(monkeypatch, response(item))
    row = propose(case, tmp_path / 'analysis', 'local:test')['items'][0]
    assert row['status'] == 'matched' and row['can_accept']
    assert row['evidence'][0]['quote'] == clause
    assert row['proposed_value'] == clause
    assert row['source_refs'][0]['location'] == {'text_offset': 0, 'line': 1}


@pytest.mark.parametrize('quote', ['工作压力\n0.3 MPa，保压时间不少于 15 秒。', '0.3 MPa，保压时间不少于 15 秒。', '15 秒。'])
def test_multiline_evidence_cannot_omit_an_applicable_condition(case, tmp_path, monkeypatch, quote):
    replace_spec(case, tmp_path, '工作压力\n高温时 0.3 MPa，保压时间不少于 15 秒。')
    item = matched()
    item.update(proposed_value=quote, evidence=[{'source_id': 'spec', 'quote': quote}])
    install_model(monkeypatch, response(item))
    row = propose(case, tmp_path / 'analysis', 'local:test')['items'][0]
    assert row['status'] == 'needs_review' and not row['can_accept']
    assert not row['evidence'] and 'proposed_value' not in row


def test_multiline_different_threshold_stays_a_difference(case, tmp_path, monkeypatch):
    clause = '工作压力\n0.5 MPa，保压时间不少于 15 秒。'
    replace_spec(case, tmp_path, clause)
    item = matched()
    item.update(proposed_value=clause, evidence=[{'source_id': 'spec', 'quote': clause}])
    install_model(monkeypatch, response(item))
    row = propose(case, tmp_path / 'analysis', 'local:test')['items'][0]
    assert row['status'] == 'difference' and not row['can_accept']
    assert row['evidence'][0]['quote'] == clause and 'proposed_value' not in row


def test_complete_multisentence_paragraph_is_available_for_review(case, tmp_path, monkeypatch):
    quote = '按试验方法检验。产品应无裂纹；所有紧固件齐全，并有防松措施。'
    replace_spec(case, tmp_path, quote)
    item = {'requirement_id': 'r1', 'status': 'needs_review', 'evidence': [{'source_id': 'spec', 'quote': quote}]}
    install_model(monkeypatch, response(item))
    row = propose(case, tmp_path / 'analysis', 'local:test')['items'][0]
    assert row['status'] == 'needs_review' and not row['can_accept']
    assert row['evidence'][0]['quote'] == quote
