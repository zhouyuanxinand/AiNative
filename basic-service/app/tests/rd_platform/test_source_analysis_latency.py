"""Bound analysis latency without discarding or rewriting verified requirements."""
from copy import deepcopy
import json

import pytest

from jonhon_taskbook import llm_client
from tests.rd_platform.test_source_analysis import analyze, install_model, setup_case


def correction_case(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    sid = project['cases'][0]['sources'][0]['id']
    initial = install_model(monkeypatch, sid)
    fixed = {'title': '工作温度', 'content': '工作温度：5℃～70℃。',
             'source_ids': [sid], 'evidence': [{'source_id': sid, 'quote': '工作温度：5℃～70℃。'}]}
    initial['requirements'].append({**deepcopy(fixed), 'content': '温度为5℃～70℃。'})
    return client, project, initial, fixed


def test_partial_correction_preserves_other_rows_and_shares_request_budget(tmp_path, monkeypatch):
    client, project, initial, fixed = correction_case(tmp_path, monkeypatch)
    calls = []

    def respond(system, user, **kwargs):
        calls.append((system, json.loads(user), kwargs))
        if len(calls) == 1:
            return deepcopy(initial)
        return {'context': {}, 'requirement_corrections': [{'index': 1, 'requirement': fixed}]}

    monkeypatch.setattr(llm_client, 'chat_json', respond)
    response = analyze(client, project)
    assert response.status_code == 200, response.text
    case = response.json()['cases'][0]
    rows = case['source_analysis']['requirements']
    assert len(rows) == 2
    assert rows[0]['content'] == initial['requirements'][0]['content']
    assert rows[0]['evidence'] == initial['requirements'][0]['evidence']
    assert rows[1]['content'] == fixed['content']
    assert case['requirements'] == []  # A proposal still needs explicit adoption.
    assert len(calls) == 2
    assert 'requirement_corrections' in calls[1][0]
    assert calls[0][2]['deadline'] == calls[1][2]['deadline']
    assert all(call[2]['timeout_seconds'] == 120 and call[2]['retries'] == 2 for call in calls)
    assert calls[1][1]['correction']['previous_proposal'] == initial


@pytest.mark.parametrize('patch_kind', ['valid_row', 'duplicate', 'missing', 'invented_quote'])
def test_partial_correction_rejects_invalid_patch_without_saving(tmp_path, monkeypatch, patch_kind):
    client, project, initial, fixed = correction_case(tmp_path, monkeypatch)
    corrections = [{'index': 1, 'requirement': deepcopy(fixed)}]
    if patch_kind == 'valid_row':
        corrections.append({'index': 0, 'requirement': deepcopy(initial['requirements'][0])})
    elif patch_kind == 'duplicate':
        corrections.append(deepcopy(corrections[0]))
    elif patch_kind == 'missing':
        corrections = []
    else:
        corrections[0]['requirement'].update(content='工作温度：100℃。',
            evidence=[{'source_id': fixed['source_ids'][0], 'quote': '工作温度：100℃。'}])
    answers = iter([initial, {'context': {}, 'requirement_corrections': corrections}])
    monkeypatch.setattr(llm_client, 'chat_json', lambda *a, **k: deepcopy(next(answers)))
    response = analyze(client, project)
    assert response.status_code == 422, response.text
    current = client.get(f"/api/rd/projects/{project['id']}").json()['cases'][0]
    assert not current['source_analysis'] and current['requirements'] == []


def test_correction_timeout_returns_specific_failure_without_saving(tmp_path, monkeypatch):
    client, project, initial, _ = correction_case(tmp_path, monkeypatch)
    calls = []

    def respond(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return deepcopy(initial)
        raise TimeoutError('request deadline exhausted')

    monkeypatch.setattr(llm_client, 'chat_json', respond)
    response = analyze(client, project)
    assert response.status_code == 504, response.text
    assert '超时' in response.text
    assert len(calls) == 2
    assert calls[0]['deadline'] == calls[1]['deadline']
    assert not client.get(f"/api/rd/projects/{project['id']}").json()['cases'][0]['source_analysis']


@pytest.mark.parametrize('bad_context', [None, []])
def test_partial_patch_cannot_repair_invalid_proposal_structure(tmp_path, monkeypatch, bad_context):
    client, project, initial, _ = correction_case(tmp_path, monkeypatch)
    initial['context'] = bad_context
    answers = iter([initial, {'context': {}, 'requirement_corrections': []}])
    monkeypatch.setattr(llm_client, 'chat_json', lambda *a, **k: deepcopy(next(answers)))
    response = analyze(client, project)
    assert response.status_code == 422, response.text
    assert not client.get(f"/api/rd/projects/{project['id']}").json()['cases'][0]['source_analysis']


def test_correction_timeout_preserves_previous_saved_proposal(tmp_path, monkeypatch):
    client, project, invalid, _ = correction_case(tmp_path, monkeypatch)
    valid = deepcopy(invalid)
    valid['requirements'][1]['content'] = '工作温度：5℃～70℃。'
    monkeypatch.setattr(llm_client, 'chat_json', lambda *a, **k: deepcopy(valid))
    first = analyze(client, project, key='initial-proposal')
    assert first.status_code == 200, first.text
    saved = first.json()
    calls = []

    def respond(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return deepcopy(invalid)
        raise TimeoutError('request deadline exhausted')

    monkeypatch.setattr(llm_client, 'chat_json', respond)
    response = analyze(client, saved, key='timed-out-reanalysis')
    assert response.status_code == 504, response.text
    latest = client.get(f"/api/rd/projects/{project['id']}").json()
    assert latest['version'] == saved['version']
    assert latest['cases'][0] == saved['cases'][0]
