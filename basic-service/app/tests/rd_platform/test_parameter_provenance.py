"""Six-parameter proposals retain evidence and never acquire approval authority."""
from contextlib import nullcontext
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from src.service.rd_platform import analysis
from src.service.rd_platform.store import RdError
from tests.rd_platform.test_source_analysis import analyze, command, setup_case


def case_with_text(tmp_path, text):
    path = tmp_path / 'requirements.txt'
    path.write_text(text, encoding='utf-8')
    source = {'id': 'tech', 'name': path.name, 'role': 'tech', 'path': str(path),
              'version': 2, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return {'context': {}, 'sources': [source], 'business_context': {}, 'context_provenance': {}}


def proposal_model(monkeypatch, context=None):
    monkeypatch.setattr(analysis.llm_client, 'get_model_status', lambda *args: {'configured': True})
    monkeypatch.setattr(analysis.llm_client, 'model_scope', lambda *args: nullcontext(None))
    monkeypatch.setattr(analysis.llm_client, 'chat_json',
                        lambda *args, **kwargs: {'context': deepcopy(context or {}), 'requirements': []})


def test_explicit_source_parameters_show_current_refs_without_retyping(tmp_path, monkeypatch):
    case = case_with_text(tmp_path, '产品类型：液冷产品-液冷管路\n质量管理体系：军品\n'
                                   '研制流程：改型II\n封面阶段：S\n产品系列：YLZJ\n产品归属：非中央研究院产品')
    proposal_model(monkeypatch)
    result = analysis.propose(case, tmp_path / 'analysis', 'local:test')
    expected = {'product_type': 'liquid_cooling_pipeline', 'product_domain': 'military',
                'development_process': '改型II', 'cover_phase': 'S', 'product_series': 'YLZJ',
                'organization_scope': 'non_central_research'}
    assert {field: item['value'] for field, item in result['context'].items()} == expected
    for field, item in result['context'].items():
        assert item['status'] == 'proposed'
        assert item['source_refs'][0]['source_id'] == 'tech'
        assert item['source_refs'][0]['sha256'] == case['sources'][0]['sha256']
        assert item['source_refs'][0]['version'] == 2
        assert item['source_refs'][0]['location']['line'] > 0
        assert item['evidence'][0]['quote'] in Path(case['sources'][0]['path']).read_text(encoding='utf-8')
        assert item['decision_ref'] is None
    assert result['context']['product_type']['rule_refs']
    assert len(result['context']['product_type']['rule_refs'][0]['sha256']) == 64
    assert case['context'] == {}


def test_absent_cover_phase_stays_unresolved_and_unsupported_model_guess_is_rejected(tmp_path, monkeypatch):
    case = case_with_text(tmp_path, '工作压力：0.3MPa。')
    proposal_model(monkeypatch)
    item = analysis.propose(case, tmp_path / 'analysis', 'local:test')['context']['cover_phase']
    assert item['value'] == '' and item['status'] == 'unresolved'
    proposal_model(monkeypatch, {'cover_phase': {'value': 'S', 'evidence': [
        {'source_id': 'tech', 'quote': '工作压力：0.3MPa。'}]}})
    with pytest.raises(RdError, match='阶段|参数'):
        analysis.propose(case, tmp_path / 'second', 'local:test')


def test_conflicting_source_values_remain_candidates_despite_model_confidence(tmp_path, monkeypatch):
    case = case_with_text(tmp_path, '封面阶段：S\n封面阶段：D')
    proposal_model(monkeypatch, {'cover_phase': {'value': 'S', 'confidence': 0.99, 'evidence': [
        {'source_id': 'tech', 'quote': '封面阶段：S'}]}})
    item = analysis.propose(case, tmp_path / 'analysis', 'local:test')['context']['cover_phase']
    assert item['status'] == 'conflict' and item['value'] == ''
    assert {candidate['value'] for candidate in item['candidates']} == {'S', 'D'}
    assert all(candidate['source_refs'][0]['sha256'] == case['sources'][0]['sha256']
               for candidate in item['candidates'])


def test_product_alias_cannot_silently_become_a_different_template_identity(tmp_path, monkeypatch):
    case = case_with_text(tmp_path, '产品类型：fluid_connector')
    proposal_model(monkeypatch, {'product_type': {'value': 'liquid_cooling_connector', 'evidence': [
        {'source_id': 'tech', 'quote': '产品类型：fluid_connector'}]}})
    item = analysis.propose(case, tmp_path / 'analysis', 'local:test')['context']['product_type']
    assert item['value'] == '' and item['status'] == 'unresolved'
    assert item['candidates'][0]['value'] == 'fluid_connector'
    assert '身份' in item['reason'] or '受控' in item['reason']


def test_parameter_facts_are_read_only_and_stale_sources_do_not_remain_current(tmp_path):
    case = case_with_text(tmp_path, '封面阶段：S')
    case['context'] = {'cover_phase': 'S'}
    reference = {key: case['sources'][0][key] for key in ('version', 'sha256')}
    reference['source_id'] = 'tech'
    case['context_provenance']['cover_phase'] = {
        'kind': 'source_analysis', 'source_refs': [reference],
        'evidence': [{'source_id': 'tech', 'quote': '封面阶段：S'}], 'analysis_id': 'analysis-1',
    }
    before = deepcopy(case)
    facts = analysis.parameter_facts(case)
    assert case == before
    assert facts['cover_phase']['status'] == 'adopted'
    assert facts['cover_phase']['evidence_status'] == 'current'
    assert facts['cover_phase']['source_refs'] == [reference]
    case['sources'][0]['version'] = 3
    case['sources'][0]['sha256'] = 'changed-source-hash'
    facts = analysis.parameter_facts(case)
    assert facts['cover_phase']['status'] == 'unresolved'
    assert facts['cover_phase']['evidence_status'] == 'stale'
    assert facts['cover_phase']['value'] == 'S'  # The historical adopted value is not erased.


def test_model_proposal_does_not_project_engineering_signature_authority(tmp_path, monkeypatch):
    case = case_with_text(tmp_path, '封面阶段：S')
    proposal_model(monkeypatch, {'cover_phase': {'value': 'S', 'approved': True,
        'decision_ref': {'kind': 'formal_review', 'actor': 'invented-signer'},
        'evidence': [{'source_id': 'tech', 'quote': '封面阶段：S'}]}})
    case['source_analysis'] = analysis.propose(case, tmp_path / 'analysis', 'local:test')
    fact = analysis.parameter_facts(case)['cover_phase']
    assert fact['status'] == 'proposed'
    assert fact['decision_ref'] is None
    assert 'approved' not in fact
    assert case['context'] == {}


def test_previously_adopted_source_is_stale_when_another_version_is_selected(tmp_path):
    case = case_with_text(tmp_path, '封面阶段：S')
    original = case['sources'][0]
    case['context'] = {'cover_phase': 'S'}
    case['context_provenance'] = {'cover_phase': {'source_refs': [
        {'source_id': 'tech', 'version': original['version'], 'sha256': original['sha256']}],
        'kind': 'source_analysis'}}
    case['sources'].append({**original, 'id': 'replacement', 'version': 3, 'sha256': 'replacement-hash'})
    case['source_selection'] = {'tech': 'replacement'}
    fact = analysis.parameter_facts(case)['cover_phase']
    assert fact['evidence_status'] == 'stale'
    assert fact['status'] == 'unresolved'
    assert fact['value'] == 'S'


def test_confirmed_value_is_preserved_but_new_source_conflict_remains_visible(tmp_path, monkeypatch):
    case = case_with_text(tmp_path, '封面阶段：D')
    case['context'] = {'cover_phase': 'S'}
    case['context_provenance']['cover_phase'] = {'kind': 'user', 'actor': 'local:test'}
    proposal_model(monkeypatch)
    result = analysis.propose(case, tmp_path / 'analysis', 'local:test')
    item = result['context']['cover_phase']
    assert item['status'] == 'conflict'
    assert item['value'] == 'S'
    assert item['candidates'][0]['value'] == 'D'
    case['source_analysis'] = {**result, 'status': 'proposed'}
    fact = analysis.parameter_facts(case)['cover_phase']
    assert fact['status'] == 'conflict' and fact['value'] == 'S'
    assert case['context']['cover_phase'] == 'S'


@pytest.mark.parametrize(('replacement_text', 'expected_status'), [
    ('封面阶段：S\n修订说明：新版沿用原阶段。', 'proposed'),
    ('工作压力：0.3 MPa。\n修订说明：新版未声明封面阶段。', 'unresolved'),
    ('封面阶段：D\n修订说明：新版调整阶段。', 'conflict'),
])
def test_replaced_source_requires_explicit_supported_readoption_and_preserves_history(
        tmp_path, monkeypatch, replacement_text, expected_status):
    client, project = setup_case(tmp_path, '封面阶段：S\n修订说明：原始版本。')
    proposal_model(monkeypatch)
    response = analyze(client, project)
    assert response.status_code == 200, response.text
    project = response.json()
    original_analysis = deepcopy(project['cases'][0]['source_analysis'])
    project = command(client, project, 'adopt_source_analysis', analysis_id=original_analysis['id'])
    original_provenance = deepcopy(project['cases'][0]['context_provenance']['cover_phase'])
    assert project['cases'][0]['parameter_facts']['cover_phase']['evidence_status'] == 'current'

    response = client.post(f"/api/rd/projects/{project['id']}/cases/{project['cases'][0]['id']}/sources",
        data={'expected_version': project['version'], 'role': 'tech'},
        files={'file': ('原始要求.txt', replacement_text.encode())},
        headers={'Idempotency-Key': 'upload-replacement'})
    assert response.status_code == 200, response.text
    project = response.json()
    case = project['cases'][0]
    replacement_id = case['source_selection']['tech']
    assert case['context']['cover_phase'] == 'S'
    assert case['context_provenance']['cover_phase'] == original_provenance
    assert case['parameter_facts']['cover_phase']['evidence_status'] == 'stale'

    response = analyze(client, project, key='analyze-replacement')
    assert response.status_code == 200, response.text
    project = response.json()
    case = project['cases'][0]
    proposal = case['source_analysis']['context']['cover_phase']
    assert proposal['status'] == expected_status
    assert case['context']['cover_phase'] == 'S'
    assert case['context_provenance']['cover_phase'] == original_provenance
    assert case['parameter_facts']['cover_phase']['evidence_status'] == 'stale'
    archived = next(item for item in case['source_analysis_history'] if item['id'] == original_analysis['id'])
    assert archived['context']['cover_phase'] == original_analysis['context']['cover_phase']
    assert archived['adopted_by'] == original_provenance['actor']

    if expected_status == 'proposed':
        assert proposal['value'] == 'S'
        assert proposal['source_refs'][0]['source_id'] == replacement_id
        assert proposal['source_refs'][0]['version'] == 2
    adopted = command(client, project, 'adopt_source_analysis', analysis_id=case['source_analysis']['id'])['cases'][0]
    assert adopted['context']['cover_phase'] == 'S'
    assert adopted['source_analysis_history'] == case['source_analysis_history']
    if expected_status == 'proposed':
        assert adopted['context_provenance']['cover_phase']['source_refs'] == proposal['source_refs']
        assert adopted['parameter_facts']['cover_phase']['status'] == 'adopted'
        assert adopted['parameter_facts']['cover_phase']['evidence_status'] == 'current'
    else:
        assert adopted['context_provenance']['cover_phase'] == original_provenance
        assert adopted['parameter_facts']['cover_phase']['evidence_status'] == 'stale'
