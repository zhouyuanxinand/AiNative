"""Source proposals are quoted evidence, never automatic business approval."""
import hashlib
import json
from copy import deepcopy

import pytest

from tests.rd_platform.test_http import make_client
from jonhon_taskbook import llm_client


def setup_case(tmp_path, source_text='工作压力：0.3 MPa。\n工作温度：5℃～70℃。',
               brief='液冷管路；军品；改型II；S阶段；YLZJ；非中央研究院产品'):
    client = make_client(tmp_path)
    project = client.post('/api/rd/projects', json={'title': '液冷资料分析', 'brief': brief}).json()
    project = command(client, project, 'create_case', scenario_id='taskbook', title='源资料确认')
    cid = project['cases'][0]['id']
    response = client.post(f"/api/rd/projects/{project['id']}/cases/{cid}/sources",
        data={'expected_version': project['version'], 'role': 'tech'},
        files={'file': ('原始要求.txt', source_text.encode())},
        headers={'Idempotency-Key': 'upload'})
    assert response.status_code == 200, response.text
    return client, response.json()


def command(client, project, name, **data):
    if project['cases']:
        data.setdefault('case_id', project['cases'][0]['id'])
    response = client.post(f"/api/rd/projects/{project['id']}/commands",
        json={'expected_version': project['version'], 'command': name, 'data': data},
        headers={'Idempotency-Key': f"{name}-{project['version']}"})
    assert response.status_code == 200, response.text
    return response.json()


def analyze(client, project, key='analyze'):
    cid = project['cases'][0]['id']
    return client.post(f"/api/rd/projects/{project['id']}/cases/{cid}/analysis",
        json={'expected_version': project['version']}, headers={'Idempotency-Key': key})


def install_model(monkeypatch, source_id):
    payload = {'context': {
        'product_type': {'value': 'liquid_cooling_pipeline', 'reason': '任务范围明确液冷管路',
                         'evidence': [{'source_id': 'project_brief', 'quote': '液冷管路'}]},
        'product_domain': {'value': 'military', 'reason': '任务范围明确军品',
                           'evidence': [{'source_id': 'project_brief', 'quote': '军品'}]},
    }, 'requirements': [{'title': '工作压力', 'content': '工作压力：0.3 MPa。',
                         'source_ids': [source_id], 'evidence': [{'source_id': source_id, 'quote': '工作压力：0.3 MPa。'}]}]}
    monkeypatch.setattr(llm_client, 'get_model_status', lambda *a, **k: {'configured': True, 'provider': 'smartvision', 'model': 'azure/gpt-5.4'})
    # Only transport is replaced: uploads, source extraction, quote checks and store are real.
    monkeypatch.setattr(llm_client, 'chat_json', lambda *a, **k: deepcopy(payload))
    from contextlib import nullcontext
    monkeypatch.setattr(llm_client, 'model_scope', lambda *a, **k: nullcontext(None))
    return payload


def test_analysis_requires_explicit_adoption_and_keeps_unresolved_fields(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    sid = project['cases'][0]['sources'][0]['id']
    install_model(monkeypatch, sid)
    response = analyze(client, project)
    assert response.status_code == 200, response.text
    proposed = response.json()
    case = proposed['cases'][0]
    assert case['context'] == {} and case['requirements'] == [] and case['decisions'] == []
    analysis = case['source_analysis']
    assert analysis['context']['cover_phase']['status'] == 'unresolved'
    assert 'requirement_id' not in analysis['requirements'][0]
    assert analysis['source_hashes'][sid] == case['sources'][0]['sha256']
    adopted = command(client, proposed, 'adopt_source_analysis', analysis_id=analysis['id'])['cases'][0]
    assert adopted['context']['product_type'] == 'liquid_cooling_pipeline'
    assert adopted['context_provenance']['product_type']['kind'] == 'source_analysis'
    assert adopted['requirements'][0]['content'] == '工作压力：0.3 MPa。'
    assert adopted['requirements'][0]['source_ids'] == [sid]
    assert adopted['decisions'] == [] and adopted['stage'] == 'input'
    assert adopted['source_analysis']['status'] == 'adopted'
    assert adopted['source_analysis']['requirements'][0]['requirement_id'] == adopted['requirements'][0]['id']


def test_parameter_declaration_ends_before_chinese_period_explanation(tmp_path, monkeypatch):
    brief = ('产品类型：液冷管路；产品领域：军品;研制流程：改型II\n'
             '封面阶段：S；产品系列：YLZJ-3.5/A；产品归属：非中央研究院产品。'
             '采用受控液冷管路模板。工作压力按需求文件0.3 MPa执行。')
    client, project = setup_case(tmp_path, source_text='产品系列：YLZJ-3.5/A。\n工作压力：0.3 MPa。\n工作温度：5℃～70℃。', brief=brief)
    install_model(monkeypatch, project['cases'][0]['sources'][0]['id'])
    response = analyze(client, project)
    assert response.status_code == 200, response.text
    proposed = response.json()
    case = proposed['cases'][0]
    proposal = case['source_analysis']
    scope = proposal['context']['organization_scope']
    assert scope['status'] == 'proposed'
    assert scope['value'] == 'non_central_research'
    assert scope['evidence'] == [{'source_id': 'project_brief', 'quote': '产品归属：非中央研究院产品'}]
    reference = scope['source_refs'][0]
    assert reference['kind'] == 'project_text'
    assert reference['sha256'] == hashlib.sha256(brief.encode()).hexdigest()
    assert brief[reference['location']['text_offset']:].startswith(scope['evidence'][0]['quote'])
    assert proposal['context']['product_series']['value'] == 'YLZJ-3.5/A'
    assert proposal['context']['development_process']['value'] == '改型II'
    assert proposal['context']['cover_phase']['value'] == 'S'
    assert case['context'] == {} and case['requirements'] == []

    adopted = command(client, proposed, 'adopt_source_analysis', analysis_id=proposal['id'])['cases'][0]
    assert adopted['context']['organization_scope'] == 'non_central_research'
    assert adopted['context']['product_series'] == 'YLZJ-3.5/A'
    assert adopted['requirements'][0]['content'] == '工作压力：0.3 MPa。'
    assert adopted['decisions'] == []


def test_adjacent_chinese_sentences_keep_conflicting_parameter_evidence():
    from src.service.rd_platform import analysis
    brief = '产品归属：非中央研究院产品。产品归属：中央研究院产品。采用受控模板。'
    proposal = analysis._parameter_proposal('organization_scope', {}, {}, {'project_brief': brief},
                                           {'organization_scope': analysis.allowed_organization_scopes()})
    assert proposal['status'] == 'conflict' and proposal['value'] == ''
    assert [item['value'] for item in proposal['candidates']] == ['non_central_research', 'central_research']
    assert [item['evidence'][0]['quote'] for item in proposal['candidates']] == [
        '产品归属：非中央研究院产品', '产品归属：中央研究院产品']
    assert all(item['controlled'] for item in proposal['candidates'])


def test_sentence_boundary_does_not_accept_uncontrolled_parameter_prefix():
    from src.service.rd_platform import analysis
    brief = '产品归属：非中央研究院产品（待确认）。采用受控模板。'
    proposal = analysis._parameter_proposal('organization_scope', {}, {}, {'project_brief': brief},
                                           {'organization_scope': analysis.allowed_organization_scopes()})
    assert proposal['status'] == 'unresolved' and proposal['value'] == ''
    assert proposal['candidates'][0]['raw_value'] == '非中央研究院产品（待确认）'
    assert proposal['candidates'][0]['controlled'] is False


def test_model_cannot_invent_quotes_or_product_domains(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    payload = install_model(monkeypatch, project['cases'][0]['sources'][0]['id'])
    payload['requirements'][0]['content'] = '耐压100MPa，已审批'
    response = analyze(client, project)
    assert response.status_code == 422
    current = client.get(f"/api/rd/projects/{project['id']}").json()
    assert not current['cases'][0].get('source_analysis')


def test_concurrent_changes_discard_analysis_without_overwriting(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    payload = install_model(monkeypatch, project['cases'][0]['sources'][0]['id'])
    def changed(*args, **kwargs):
        command(client, project, 'save_context', context={'product_series': '用户已确认系列'})
        return deepcopy(payload)
    monkeypatch.setattr(llm_client, 'chat_json', changed)
    response = analyze(client, project)
    assert response.status_code == 409
    current = client.get(f"/api/rd/projects/{project['id']}").json()
    assert current['cases'][0]['context']['product_series'] == '用户已确认系列'
    assert not current['cases'][0].get('source_analysis')


def test_source_change_stales_proposal_and_adoption_preserves_existing(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    project = command(client, project, 'save_context', context={'product_type': 'low_frequency_rectangular'})
    sid = project['cases'][0]['sources'][0]['id']
    project = command(client, project, 'save_requirement', title='已确认温度', content='工作温度：5℃～70℃。', source_ids=[sid])
    install_model(monkeypatch, sid)
    result = analyze(client, project).json()
    analysis = result['cases'][0]['source_analysis']
    assert analysis['context']['product_type']['status'] == 'already_confirmed'
    adopted = command(client, result, 'adopt_source_analysis', analysis_id=analysis['id'])
    assert adopted['cases'][0]['context']['product_type'] == 'low_frequency_rectangular'
    assert [r['title'] for r in adopted['cases'][0]['requirements']] == ['已确认温度', '工作压力']
    result = analyze(client, adopted, key='second-analysis').json()
    aid = result['cases'][0]['source_analysis']['id']
    changed = command(client, result, 'save_context', context={'product_series': '改版'})
    assert changed['cases'][0]['source_analysis']['status'] == 'stale'
    response = client.post(f"/api/rd/projects/{project['id']}/commands", json={
        'expected_version': changed['version'], 'command': 'adopt_source_analysis',
        'data': {'case_id': changed['cases'][0]['id'], 'analysis_id': aid}}, headers={'Idempotency-Key': 'stale-adopt'})
    assert response.status_code == 409


def test_missing_credentials_do_not_create_fake_analysis(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    monkeypatch.setattr(llm_client, 'get_model_status', lambda *a, **k: {'configured': False})
    response = analyze(client, project)
    assert response.status_code == 503
    assert '凭证' in response.text


def test_docx_extraction_retains_table_text_and_legacy_doc_warning(tmp_path, monkeypatch):
    from docx import Document
    from types import SimpleNamespace
    from src.service.rd_platform import analysis
    document = Document()
    document.add_paragraph('产品：液冷管路')
    cells = document.add_table(rows=1, cols=2).rows[0].cells
    cells[0].text, cells[1].text = '工作压力', '0.3 MPa'
    path = tmp_path / 'original.docx'
    document.save(path)
    source = {'id': 'original', 'name': path.name, 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    text, warnings = analysis._source_text(source, tmp_path / 'extracted')
    assert '产品：液冷管路' in text and '工作压力 | 0.3 MPa' in text and warnings == []
    legacy = tmp_path / 'original.doc'
    legacy.write_bytes(b'legacy-conversion-fixture')
    source.update(name=legacy.name, path=str(legacy), sha256=hashlib.sha256(legacy.read_bytes()).hexdigest())
    monkeypatch.setattr(analysis, 'normalize_input', lambda *a, **k: SimpleNamespace(path=path, requires_review=True, warnings=['旧版DOC已转换，须复核。']))
    text, warnings = analysis._source_text(source, tmp_path / 'converted')
    assert '0.3 MPa' in text and any('不表示' in warning for warning in warnings)


def test_replay_does_not_call_model_again_and_spec_is_not_requirement(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    sid = project['cases'][0]['sources'][0]['id']
    payload = install_model(monkeypatch, sid)
    response = analyze(client, project)
    assert response.status_code == 200
    monkeypatch.setattr(llm_client, 'chat_json', lambda *a, **k: pytest.fail('idempotency replay must not call model'))
    assert analyze(client, project).json() == response.json()
    from src.service.rd_platform import analysis
    original = tmp_path / 'spec.txt'
    original.write_text('工作压力：0.3 MPa。', encoding='utf-8')
    source = {'id': sid, 'role': 'spec', 'name': original.name, 'path': str(original), 'sha256': hashlib.sha256(original.read_bytes()).hexdigest()}
    install_model(monkeypatch, sid)
    from src.service.rd_platform.store import RdError
    with pytest.raises(RdError, match='不得改写或使用产品规范'):
        analysis.propose({'sources': [source], 'business_context': {'brief': '液冷管路；军品'}, 'context': {}}, tmp_path / 'proposal', 'local:test')


@pytest.mark.parametrize('adopted_content, proposed_content', [
    ('工作压力修订为：0.5 MPa。', '工作压力：0.3 MPa。'),
    ('工作压力修订为：0.5 MPa。', '工作压力：0.3MPa。'),
    ('工作压力：0.3 MPa。', '工作压力：0.3 MPa。'),
])
def test_reanalysis_keeps_adopted_clarification_and_only_adds_new_requirements(
        tmp_path, monkeypatch, adopted_content, proposed_content):
    client, project = setup_case(tmp_path)
    case = project['cases'][0]
    sid, cid = case['sources'][0]['id'], case['id']
    payload = install_model(monkeypatch, sid)
    project = analyze(client, project).json()
    project = command(client, project, 'adopt_source_analysis',
                      analysis_id=project['cases'][0]['source_analysis']['id'])
    rid = project['cases'][0]['requirements'][0]['id']
    response = client.post(f"/api/rd/projects/{project['id']}/cases/{cid}/sources",
        data={'expected_version': project['version'], 'role': 'reference'},
        files={'file': ('压力澄清答复.txt', adopted_content.encode())},
        headers={'Idempotency-Key': 'clarification-source'})
    assert response.status_code == 200, response.text
    project = response.json()
    reference_id = project['cases'][0]['sources'][-1]['id']
    project = command(client, project, 'open_clarification', requirement_id=rid,
                      question='确认实际工作压力', source_ids=[sid])
    clarification_id = project['cases'][0]['clarifications'][-1]['id']
    project = command(client, project, 'answer_clarification', clarification_id=clarification_id,
                      answer=adopted_content, source_ids=[reference_id])
    project = command(client, project, 'adopt_clarification', clarification_id=clarification_id,
                      requirement_content=adopted_content)
    confirmed = deepcopy(project['cases'][0]['requirements'][0])
    clarification = deepcopy(project['cases'][0]['clarifications'][-1])
    payload['requirements'][0]['content'] = proposed_content
    payload['requirements'][0]['evidence'][0]['quote'] = proposed_content
    payload['requirements'].append({'title': '工作温度', 'content': '工作温度：5℃～70℃。',
        'source_ids': [sid], 'evidence': [{'source_id': sid, 'quote': '工作温度：5℃～70℃。'}]})

    response = analyze(client, project, key='reanalysis-after-clarification')
    assert response.status_code == 200, response.text
    project = response.json()
    project = command(client, project, 'adopt_source_analysis',
                      analysis_id=project['cases'][0]['source_analysis']['id'])
    case = project['cases'][0]
    assert len(case['requirements']) == 2
    assert case['requirements'][0] == confirmed
    assert case['clarifications'][-1] == clarification
    assert case['requirements'][1]['content'] == '工作温度：5℃～70℃。'
    assert case['requirements'][1]['source_ids'] == [sid]
    assert case['decisions'] == []
    assert [row['requirement_id'] for row in case['source_analysis']['requirements']] == [
        rid, case['requirements'][1]['id']]


def test_ambiguous_source_candidate_does_not_choose_between_two_saved_requirements(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    sid = project['cases'][0]['sources'][0]['id']
    candidate = install_model(monkeypatch, sid)['requirements'][0]
    for _ in range(2):
        project = command(client, project, 'save_requirement', title=candidate['title'],
                          content=candidate['content'], source_ids=[sid])
    project = analyze(client, project).json()
    project = command(client, project, 'adopt_source_analysis', analysis_id=project['cases'][0]['source_analysis']['id'])
    case = project['cases'][0]
    assert len(case['requirements']) == 2
    assert not case['source_analysis']['requirements'][0].get('requirement_id')


def test_legacy_adopted_candidate_is_linked_on_read_without_changing_storage(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    sid = project['cases'][0]['sources'][0]['id']
    install_model(monkeypatch, sid)
    project = analyze(client, project).json()
    project = command(client, project, 'adopt_source_analysis', analysis_id=project['cases'][0]['source_analysis']['id'])
    rid = project['cases'][0]['requirements'][0]['id']
    project = command(client, project, 'save_requirement', id=rid, title='更新后的压力指标',
                      content='经澄清后验收。', source_ids=[sid])
    store = client.app.state.rd_store
    with store._connection() as db:
        row = db.execute('SELECT payload FROM projects WHERE id=?', (project['id'],)).fetchone()
        legacy = json.loads(row[0])
        proposal = legacy['cases'][0]['source_analysis']
        assert proposal['status'] == 'stale' and proposal['adopted_at']
        assert proposal['requirements'][0].pop('requirement_id') == rid
        legacy_json = json.dumps(legacy)
        db.execute('UPDATE projects SET payload=? WHERE id=?', (legacy_json, project['id']))
    for result in [client.get('/api/rd/projects/' + project['id']).json(),
                   client.get('/api/rd/projects').json()['projects'][0]]:
        assert result['cases'][0]['source_analysis']['requirements'][0]['requirement_id'] == rid
    with store._connection() as db:
        assert db.execute('SELECT payload FROM projects WHERE id=?', (project['id'],)).fetchone()[0] == legacy_json


def test_equal_acceptance_values_for_distinct_tests_survive_analysis_and_adoption(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path, '耐压测试：泄漏值＜3%\n58psi保压：泄漏值＜3%')
    sid = project['cases'][0]['sources'][0]['id']
    payload = install_model(monkeypatch, sid)
    payload['requirements'] = [
        {'title': title, 'content': '泄漏值＜3%', 'source_ids': [sid],
         'evidence': [{'source_id': sid, 'quote': '泄漏值＜3%'}]}
        for title in ('耐压测试', '58psi保压', '耐压测试')
    ]
    response = analyze(client, project)
    assert response.status_code == 200, response.text
    project = response.json()
    proposal = project['cases'][0]['source_analysis']
    assert [item['title'] for item in proposal['requirements']] == ['耐压测试', '58psi保压']

    project = command(client, project, 'adopt_source_analysis', analysis_id=proposal['id'])
    assert [item['title'] for item in project['cases'][0]['requirements']] == ['耐压测试', '58psi保压']
    assert all(item['content'] == '泄漏值＜3%' for item in project['cases'][0]['requirements'])


def test_requirement_history_does_not_hide_another_test_with_the_same_value(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path, '耐压测试：泄漏值＜3%\n58psi保压：泄漏值＜3%\n修订后的耐压测试：泄漏值＜1%')
    sid = project['cases'][0]['sources'][0]['id']
    project = command(client, project, 'save_requirement', title='耐压测试', content='泄漏值＜3%', source_ids=[sid])
    rid = project['cases'][0]['requirements'][0]['id']
    project = command(client, project, 'save_requirement', id=rid, title='耐压测试', content='泄漏值＜1%', source_ids=[sid])
    confirmed = deepcopy(project['cases'][0]['requirements'][0])
    payload = install_model(monkeypatch, sid)
    payload['requirements'] = [{'title': '58psi保压', 'content': '泄漏值＜3%', 'source_ids': [sid],
                                'evidence': [{'source_id': sid, 'quote': '泄漏值＜3%'}]}]
    response = analyze(client, project)
    assert response.status_code == 200, response.text
    project = response.json()
    project = command(client, project, 'adopt_source_analysis',
                      analysis_id=project['cases'][0]['source_analysis']['id'])
    requirements = project['cases'][0]['requirements']
    assert len(requirements) == 2
    assert requirements[0] == confirmed
    assert requirements[1]['title'] == '58psi保压'
    assert requirements[1]['content'] == '泄漏值＜3%'


def test_invalid_model_wording_gets_one_source_bound_correction_before_proposal(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    sid = project['cases'][0]['sources'][0]['id']
    correct = install_model(monkeypatch, sid)
    first = deepcopy(correct)
    first['requirements'][0]['content'] = '压力不得低于0.3 MPa。'
    prompts = []

    def respond(system, user, **kwargs):
        prompts.append(json.loads(user))
        return deepcopy(first if len(prompts) == 1 else correct)

    monkeypatch.setattr(llm_client, 'chat_json', respond)
    response = analyze(client, project)
    assert response.status_code == 200, response.text
    proposal = response.json()['cases'][0]['source_analysis']
    assert proposal['requirements'][0]['content'] == '工作压力：0.3 MPa。'
    assert response.json()['cases'][0]['requirements'] == []  # Still requires adoption.
    assert len(prompts) == 2
    assert prompts[1]['sources'] == prompts[0]['sources']
    assert prompts[1]['correction']['errors'][0]['location'] == 'requirements[0].content'
    assert proposal['validation']['correction_attempts'] == 1


def test_failed_correction_names_requirement_and_does_not_loop_or_adopt(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    payload = install_model(monkeypatch, project['cases'][0]['sources'][0]['id'])
    payload['requirements'][0]['content'] = '工作压力：99 MPa。'
    calls = []

    def respond(*args, **kwargs):
        calls.append(1)
        return deepcopy(payload)

    monkeypatch.setattr(llm_client, 'chat_json', respond)
    response = analyze(client, project)
    assert response.status_code == 422
    assert 'requirements[0].content' in response.text and '工作压力' in response.text
    assert len(calls) == 2
    current = client.get(f"/api/rd/projects/{project['id']}").json()['cases'][0]
    assert current['requirements'] == [] and not current['source_analysis']


def test_correction_cannot_drop_unresolved_requirement_to_claim_success(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    payload = install_model(monkeypatch, project['cases'][0]['sources'][0]['id'])
    payload['requirements'][0]['content'] = '工作压力：99 MPa。'
    answers = iter([payload, {'context': deepcopy(payload['context']), 'requirements': []}])
    monkeypatch.setattr(llm_client, 'chat_json', lambda *a, **k: deepcopy(next(answers)))
    response = analyze(client, project)
    assert response.status_code == 422
    assert '删除' in response.text or '数量' in response.text
    assert not client.get(f"/api/rd/projects/{project['id']}").json()['cases'][0]['source_analysis']


def test_correction_preserves_already_valid_requirement_even_if_new_value_exists(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path, '工作压力：0.3 MPa。\n极限压力：0.6 MPa。\n工作温度：5℃～70℃。')
    sid = project['cases'][0]['sources'][0]['id']
    payload = install_model(monkeypatch, sid)
    payload['requirements'].append({'title': '工作温度', 'content': '温度为5℃～70℃。',
        'evidence': [{'source_id': sid, 'quote': '工作温度：5℃～70℃。'}]})
    corrected = deepcopy(payload)
    corrected['requirements'][0].update(content='极限压力：0.6 MPa。',
        evidence=[{'source_id': sid, 'quote': '极限压力：0.6 MPa。'}])
    corrected['requirements'][1]['content'] = '工作温度：5℃～70℃。'
    answers = iter([payload, corrected])
    monkeypatch.setattr(llm_client, 'chat_json', lambda *a, **k: deepcopy(next(answers)))
    response = analyze(client, project)
    assert response.status_code == 422
    assert 'requirements[0]' in response.text
    assert not client.get(f"/api/rd/projects/{project['id']}").json()['cases'][0]['source_analysis']


def test_non_tech_quote_reports_role_and_stays_rejected_after_correction(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    cid = project['cases'][0]['id']
    response = client.post(f"/api/rd/projects/{project['id']}/cases/{cid}/sources",
        data={'expected_version': project['version'], 'role': 'spec'},
        files={'file': ('历史产品规范.txt', '工作压力：0.6 MPa。'.encode())},
        headers={'Idempotency-Key': 'upload-spec'})
    assert response.status_code == 200, response.text
    project = response.json()
    sid = project['cases'][0]['sources'][-1]['id']
    payload = install_model(monkeypatch, sid)
    payload['requirements'][0].update(content='工作压力：0.6 MPa。',
        evidence=[{'source_id': sid, 'quote': '工作压力：0.6 MPa。'}])
    response = analyze(client, project)
    assert response.status_code == 422
    assert 'requirements[0].evidence' in response.text and 'tech' in response.text
    assert not client.get(f"/api/rd/projects/{project['id']}").json()['cases'][0]['source_analysis']
