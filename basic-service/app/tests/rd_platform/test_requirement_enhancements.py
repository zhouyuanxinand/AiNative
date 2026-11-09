"""Extraction cannot publish specification recommendations, even with real quotes."""
from copy import deepcopy

import pytest

from jonhon_taskbook import llm_client
from tests.rd_platform.test_source_analysis import analyze, command, install_model, setup_case


PRESSURE_CLAUSE = '工作压力：0.3 MPa，保压时间不少于 15 秒。'


def test_extraction_drops_self_citation_instead_of_publishing_a_spec_suggestion(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    sid = project['cases'][0]['sources'][0]['id']
    model = install_model(monkeypatch, sid)
    original = deepcopy(model['requirements'][0])
    model['requirements'][0]['recommendation'] = {
        'text': '请核对所引条款的适用条件',
        'proposed_value': original['content'],
        'evidence': deepcopy(original['evidence']),
    }
    response = analyze(client, project)
    assert response.status_code == 200, response.text
    case = response.json()['cases'][0]
    row = case['source_analysis']['requirements'][0]
    assert row['content'] == original['content']
    assert row['evidence'] == original['evidence']
    assert 'recommendation' not in row
    assert not case.get('requirement_recommendations')


def supplied_documents(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    case = project['cases'][0]
    tech = case['sources'][0]['id']
    response = client.post(f"/api/rd/projects/{project['id']}/cases/{case['id']}/sources",
        data={'expected_version': project['version'], 'role': 'spec'},
        files={'file': ('验证规范.txt', '\n'.join([PRESSURE_CLAUSE, '库存数量：15 件。', '工作压力：高温时 0.3 MPa。', '工作压力：0.5 MPa。', '工作压力：0.3 kPa。']).encode())},
        headers={'Idempotency-Key': 'spec'})
    assert response.status_code == 200, response.text
    project = response.json()
    spec = next(s['id'] for s in project['cases'][0]['sources'] if s['role'] == 'spec')
    model = install_model(monkeypatch, tech)
    model['requirements'][0]['recommendation'] = {
        'text': '补充保压时间', 'proposed_value': PRESSURE_CLAUSE,
        'evidence': [{'source_id': spec, 'quote': PRESSURE_CLAUSE}],
    }
    return client, project, model


def test_spec_citation_from_extraction_waits_for_independent_spec_review(tmp_path, monkeypatch):
    client, project, model = supplied_documents(tmp_path, monkeypatch)
    project = analyze(client, project).json()
    proposal = project['cases'][0]['source_analysis']
    row = proposal['requirements'][0]
    assert row['content'] == '工作压力：0.3 MPa。'
    assert 'recommendation' not in row
    assert row['evidence'] == model['requirements'][0]['evidence']
    adopted = command(client, project, 'adopt_source_analysis', analysis_id=proposal['id'])['cases'][0]
    assert adopted['requirements'][0]['content'] == '工作压力：0.3 MPa。'
    assert 'recommendation' not in adopted['source_analysis']['requirements'][0]
    assert not adopted.get('requirement_recommendations')
    assert not adopted['requirements'][0].get('review')


def test_retain_eight_channels_without_adopting_extra_circuits_from_extraction(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path, source_text='连接路数：8 路。\n连接路数：8 路，采用独立回路。')
    sid = project['cases'][0]['sources'][0]['id']
    model = install_model(monkeypatch, sid)
    text = '连接路数：8 路。'
    rec = {'text': '补充独立回路', 'proposed_value': '8 路',
           'evidence': [{'source_id': sid, 'quote': '连接路数：8 路，采用独立回路。'}]}
    model['requirements'] = [{'title': '连接路数', 'content': text, 'evidence': [{'source_id': sid, 'quote': text}],
                              'recommendation': rec}]
    row = analyze(client, project).json()['cases'][0]['source_analysis']['requirements'][0]
    assert row['content'] == text and row['evidence'] == [{'source_id': sid, 'quote': text}]
    assert 'recommendation' not in row


@pytest.mark.parametrize('variant', ['made_up_value', 'incomplete_limit', 'invented_source', 'project_text', 'truncated_quote',
                                    'different_metric', 'different_condition', 'different_threshold', 'different_unit'])
def test_unverified_enhancement_is_omitted_without_losing_original_row(tmp_path, monkeypatch, variant):
    client, project, model = supplied_documents(tmp_path, monkeypatch)
    rec = model['requirements'][0]['recommendation']
    if variant == 'made_up_value':
        rec['proposed_value'] = '保压时间：不少于 50 秒。'
    elif variant == 'incomplete_limit':
        rec['proposed_value'] = '15 秒'
    elif variant == 'invented_source':
        rec['evidence'][0]['source_id'] = 'k-box-profile'
    elif variant == 'project_text':
        rec.update(proposed_value='军品', evidence=[{'source_id': 'project_brief', 'quote': '军品'}])
    elif variant == 'truncated_quote':
        rec.update(proposed_value='15 秒', evidence=[{**rec['evidence'][0], 'quote': '15 秒'}])
    else:
        clause = {'different_metric': '库存数量：15 件。', 'different_condition': '工作压力：高温时 0.3 MPa。',
                  'different_threshold': '工作压力：0.5 MPa。', 'different_unit': '工作压力：0.3 kPa。'}[variant]
        rec.update(proposed_value=clause, evidence=[{**rec['evidence'][0], 'quote': clause}])
    response = analyze(client, project)
    assert response.status_code == 200, response.text
    proposal = response.json()['cases'][0]['source_analysis']
    assert 'recommendation' not in proposal['requirements'][0]
    assert proposal['requirements'][0]['content'] == '工作压力：0.3 MPa。'
    assert any('增强建议' in warning for warning in proposal['warnings'])


def test_correction_keeps_verified_originals_and_drops_out_of_stage_suggestions(tmp_path, monkeypatch):
    client, project, model = supplied_documents(tmp_path, monkeypatch)
    row = model['requirements'][0]
    model['requirements'].append({'title': '工作温度', 'content': '5–70度',
        'evidence': [{**row['evidence'][0], 'quote': '工作温度：5℃～70℃。'}]})
    corrected = deepcopy(model)
    corrected['requirements'][1]['content'] = '工作温度：5℃～70℃。'
    del corrected['requirements'][0]['recommendation']
    responses = iter([model, corrected])
    monkeypatch.setattr(llm_client, 'chat_json', lambda *a, **k: next(responses))
    response = analyze(client, project)
    assert response.status_code == 200, response.text
    proposal = response.json()['cases'][0]['source_analysis']
    assert [item['content'] for item in proposal['requirements']] == ['工作压力：0.3 MPa。', '工作温度：5℃～70℃。']
    assert proposal['requirements'][0]['evidence'] == row['evidence']
    assert all('recommendation' not in item for item in proposal['requirements'])
    assert proposal['validation']['correction_attempts'] == 1
    assert response.json()['cases'][0]['requirements'] == []
