"""Series candidates distinguish requirement covers, filenames and engineering evidence."""
from contextlib import nullcontext
from copy import deepcopy
import hashlib

from docx import Document
import pytest

from src.service.rd_platform import analysis
from tests.rd_platform.test_http import make_client
from tests.rd_platform.test_source_analysis import analyze, command


def model(monkeypatch, payload=None):
    monkeypatch.setattr(analysis.llm_client, 'get_model_status', lambda *args: {'configured': True})
    monkeypatch.setattr(analysis.llm_client, 'model_scope', lambda *args: nullcontext(None))
    monkeypatch.setattr(analysis.llm_client, 'chat_json',
                        lambda *args, **kwargs: deepcopy(payload or {'context': {}, 'requirements': []}))


def file_case(tmp_path, name='需求.txt', text='工作压力：0.3 MPa。'):
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return {'context': {}, 'context_provenance': {}, 'business_context': {}, 'input_revision': 1,
            'sources': [{'id': 'tech', 'role': 'tech', 'name': name, 'path': str(path), 'version': 1,
                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}],
            'source_selection': {'tech': 'tech'}}


def upload(client, project, name, text, role='tech'):
    response = client.post(f"/api/rd/projects/{project['id']}/cases/{project['cases'][0]['id']}/sources",
        data={'expected_version': project['version'], 'role': role},
        files={'file': (name, text.encode('utf-8'))},
        headers={'Idempotency-Key': f"upload-{project['version']}"})
    assert response.status_code == 200, response.text
    return response.json()


def http_case(tmp_path, name='需求.txt', text='工作压力：0.3 MPa。'):
    client = make_client(tmp_path)
    response = client.post('/api/rd/projects', json={'title': '系列识别项目'})
    assert response.status_code == 200, response.text
    project = command(client, response.json(), 'create_case', scenario_id='taskbook', title='来源确认')
    return client, upload(client, project, name, text)


def requirement_payload(source_id):
    return {'context': {}, 'requirements': [{'title': '工作压力', 'content': '工作压力：0.3 MPa。',
        'source_ids': [source_id], 'evidence': [{'source_id': source_id, 'quote': '工作压力：0.3 MPa。'}]}]}


def test_filename_series_is_separate_evidence_and_survives_real_adoption(tmp_path, monkeypatch):
    name = 'YLZJ-3.5A技术要求.txt'
    client, project = http_case(tmp_path, name)
    source = project['cases'][0]['sources'][0]
    model(monkeypatch, requirement_payload(source['id']))
    response = analyze(client, project)
    assert response.status_code == 200, response.text
    project = response.json()
    proposal = project['cases'][0]['source_analysis']
    item = proposal['context']['product_series']
    assert item['status'] == 'proposed' and item['value'] == 'YLZJ-3.5A'
    assert item['evidence'] == [{'source_id': source['id'], 'kind': 'source_filename', 'quote': name}]
    reference = item['source_refs'][0]
    assert reference['kind'] == 'source_filename'
    assert reference['source_id'] == source['id'] and reference['sha256'] == source['sha256']
    assert reference['version'] == source['version']
    assert reference['name_sha256'] == hashlib.sha256(name.encode('utf-8')).hexdigest()
    assert reference['location'] == {'filename': name}
    assert proposal['requirements'][0]['content'] == '工作压力：0.3 MPa。'
    assert proposal['requirements'][0]['evidence'][0]['quote'] != name
    adopted = command(client, project, 'adopt_source_analysis', analysis_id=proposal['id'])['cases'][0]
    assert adopted['context']['product_series'] == 'YLZJ-3.5A'
    assert adopted['context_provenance']['product_series']['evidence'] == item['evidence']
    assert adopted['parameter_facts']['product_series']['source_refs'] == item['source_refs']
    assert adopted['parameter_facts']['product_series']['evidence_status'] == 'current'


@pytest.mark.parametrize('label', ['产品系列', '产品型号', '型号'])
def test_requirement_cover_labels_resolve_series_without_model_guess(tmp_path, monkeypatch, label):
    case = file_case(tmp_path, text=f'{label}：YLZJ-3.5/A\n工作压力：0.3 MPa。')
    model(monkeypatch)
    item = analysis.propose(case, tmp_path / 'analysis', 'local:test')['context']['product_series']
    assert item['value'] == 'YLZJ-3.5/A' and item['status'] == 'proposed'
    assert item['evidence'] == [{'source_id': 'tech', 'quote': f'{label}：YLZJ-3.5/A'}]
    assert item['source_refs'][0]['location']['line'] == 1


@pytest.mark.parametrize('values', [
    ['产品型号', 'ABC-123', '产品名称', '连接器'],
    ['产品名称', '连接器', '产品型号', 'ABC-123'],
])
def test_docx_cover_table_does_not_include_neighboring_fields_in_series(tmp_path, monkeypatch, values):
    document = Document()
    document.add_heading('连接器技术要求', level=0)
    cells = document.add_table(rows=1, cols=4).rows[0].cells
    for cell, text in zip(cells, values):
        cell.text = text
    path = tmp_path / '需求.docx'
    document.save(path)
    case = {'context': {}, 'context_provenance': {}, 'business_context': {}, 'input_revision': 1,
            'sources': [{'id': 'tech', 'role': 'tech', 'name': path.name, 'path': str(path),
                         'version': 1, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]}
    model(monkeypatch)
    item = analysis.propose(case, tmp_path / 'analysis', 'local:test')['context']['product_series']
    assert item['status'] == 'proposed' and item['value'] == 'ABC-123'
    assert '产品型号 | ABC-123' in item['evidence'][0]['quote']
    assert item['source_refs'][0]['source_id'] == 'tech'


@pytest.mark.parametrize('name', ['需求文件.txt', '技术要求_20261104_v2.txt', 'requirements_v2.txt',
                                 'TECHNICAL_REQUIREMENTS_V2.txt', '需求文件_copy2.txt', 'XX技术要求.txt',
                                 'GB1234技术要求.txt', 'requirements_20261104.txt',
                                 'TECHNICAL_REQUIREMENTS_20261104.txt', 'requirements-2026-11-04.txt',
                                 'scan001.txt', 'SCAN_20261104_002.txt', 'TBD.txt', 'UNKNOWN.txt', 'NONE.txt'])
def test_generic_or_revision_only_filenames_leave_series_unresolved(tmp_path, monkeypatch, name):
    case = file_case(tmp_path, name, '产品型号：待定\n工作压力：0.3 MPa。')
    model(monkeypatch)
    item = analysis.propose(case, tmp_path / 'analysis', 'local:test')['context']['product_series']
    assert item['value'] == '' and item['status'] == 'unresolved'


@pytest.mark.parametrize('series', ['YLZJ', 'CY', 'ICTS'])
def test_known_business_series_without_digits_remain_filename_candidates(tmp_path, monkeypatch, series):
    case = file_case(tmp_path, f'{series}技术要求.txt')
    model(monkeypatch)
    item = analysis.propose(case, tmp_path / 'analysis', 'local:test')['context']['product_series']
    assert item['value'] == series and item['status'] == 'proposed'
    assert item['evidence'][0]['kind'] == 'source_filename'


def test_specification_and_supplementary_series_do_not_become_requirement_identity(tmp_path, monkeypatch):
    case = file_case(tmp_path)
    for role in ('spec', 'reference'):
        path = tmp_path / f'OLD-500-{role}.txt'
        path.write_text('产品系列：OLD-500', encoding='utf-8')
        case['sources'].append({'id': role, 'role': role, 'document_category': 'tech', 'name': path.name,
            'path': str(path), 'version': 1, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    case['source_selection']['spec'] = 'spec'
    model(monkeypatch)
    item = analysis.propose(case, tmp_path / 'analysis', 'local:test')['context']['product_series']
    assert item['value'] == '' and item['status'] == 'unresolved'


@pytest.mark.parametrize('field', ['brief', 'product_name', 'customer_name', 'title'])
def test_project_text_cannot_supply_requirement_series_evidence(tmp_path, monkeypatch, field):
    case = file_case(tmp_path)
    case['business_context'][field] = '产品型号：MARKETING-900'
    model(monkeypatch)
    item = analysis.propose(case, tmp_path / 'analysis', 'local:test')['context']['product_series']
    assert item['value'] == '' and item['status'] == 'unresolved'
    assert item['candidates'] == [] and item['evidence'] == [] and item['source_refs'] == []


def test_model_cannot_use_specification_quote_as_requirement_series(tmp_path, monkeypatch):
    client, project = http_case(tmp_path)
    project = upload(client, project, '规范.txt', '产品系列：OLD-500', 'spec')
    tech_id = project['cases'][0]['source_selection']['tech']
    spec_id = project['cases'][0]['source_selection']['spec']
    payload = requirement_payload(tech_id)
    payload['context']['product_series'] = {'value': 'OLD-500', 'evidence': [
        {'source_id': spec_id, 'quote': '产品系列：OLD-500'}]}
    model(monkeypatch, payload)
    response = analyze(client, project)
    assert response.status_code == 422
    current = client.get(f"/api/rd/projects/{project['id']}").json()['cases'][0]
    assert current['source_analysis'] is None and current['context'] == {}


def test_conflicting_cover_and_filename_keep_candidates_for_confirmation(tmp_path, monkeypatch):
    case = file_case(tmp_path, 'DEF-456技术要求.txt', '产品型号：ABC-123\n工作压力：0.3 MPa。')
    model(monkeypatch)
    item = analysis.propose(case, tmp_path / 'analysis', 'local:test')['context']['product_series']
    assert item['status'] == 'conflict' and item['value'] == ''
    assert {candidate['value'] for candidate in item['candidates'] if candidate['eligible']} == {'ABC-123', 'DEF-456'}
    assert any(candidate['evidence'][0].get('kind') == 'source_filename' for candidate in item['candidates'])
    assert case['context'] == {}


def test_user_confirmed_series_is_never_replaced_by_a_filename(tmp_path, monkeypatch):
    case = file_case(tmp_path, 'ABC-123技术要求.txt')
    case['context']['product_series'] = 'USER-900'
    case['context_provenance']['product_series'] = {'kind': 'user', 'actor': 'local:owner'}
    model(monkeypatch)
    proposal = analysis.propose(case, tmp_path / 'analysis', 'local:test')
    item = proposal['context']['product_series']
    assert item['value'] == 'USER-900' and item['status'] == 'conflict'
    assert case['context']['product_series'] == 'USER-900'
    case['source_analysis'] = {**proposal, 'status': 'proposed'}
    fact = analysis.parameter_facts(case)['product_series']
    assert fact['value'] == 'USER-900' and fact['status'] == 'conflict'
    assert fact['decision_ref'] == {'kind': 'user_confirmation', 'actor': 'local:owner', 'created_at': None}


def test_filename_evidence_becomes_stale_when_the_name_changes(tmp_path, monkeypatch):
    case = file_case(tmp_path, 'ABC-123技术要求.txt')
    model(monkeypatch)
    item = analysis.propose(case, tmp_path / 'analysis', 'local:test')['context']['product_series']
    assert item['value'] == 'ABC-123'
    case['context']['product_series'] = item['value']
    case['context_provenance']['product_series'] = {**item, 'kind': 'source_analysis'}
    assert analysis.parameter_facts(case)['product_series']['evidence_status'] == 'current'
    case['sources'][0]['name'] = 'DEF-456技术要求.txt'
    fact = analysis.parameter_facts(case)['product_series']
    assert fact['evidence_status'] == 'stale' and fact['status'] == 'unresolved'
    assert fact['value'] == 'ABC-123'


def test_filename_cannot_be_used_as_an_engineering_requirement_quote(tmp_path, monkeypatch):
    name = 'ABC-123技术要求.txt'
    client, project = http_case(tmp_path, name)
    sid = project['cases'][0]['sources'][0]['id']
    payload = {'context': {}, 'requirements': [{'title': '伪造工程指标', 'content': name,
        'source_ids': [sid], 'evidence': [{'source_id': sid, 'kind': 'source_filename', 'quote': name}]}]}
    model(monkeypatch, payload)
    response = analyze(client, project)
    assert response.status_code == 422
    case = client.get(f"/api/rd/projects/{project['id']}").json()['cases'][0]
    assert case['requirements'] == [] and case['source_analysis'] is None


def test_missing_series_can_use_existing_explicit_user_confirmation(tmp_path):
    client, project = http_case(tmp_path)
    case = command(client, project, 'save_context', context={'product_series': 'CONFIRMED-1'})['cases'][0]
    fact = case['parameter_facts']['product_series']
    assert fact['value'] == 'CONFIRMED-1' and fact['status'] == 'adopted'
    assert fact['source_refs'] == [] and fact['decision_ref']['kind'] == 'user_confirmation'
