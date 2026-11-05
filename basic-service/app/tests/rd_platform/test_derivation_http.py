"""Governance HTTP tests use synthetic assets, never enterprise qualification."""
import io
import json
from types import SimpleNamespace

from docx import Document
from PIL import Image
import yaml

from tests.rd_platform.test_http import make_client
from src.controller import rd_derivation_controller as controller
from jonhon_taskbook.template_onboarding import load_taxonomy
from jonhon_taskbook.template_derivation import digest, file_hash
from jonhon_taskbook.template_outline_editor import get_template_outline


def client_for(tmp_path, monkeypatch, *, prepare=True, review=True):
    client = make_client(tmp_path)
    client.app.include_router(controller.router)
    actor = client.get('/api/rd/session').json()['actor_id']
    monkeypatch.setenv('JTB_RD_TEMPLATE_PUBLISHERS', actor if prepare else '')
    monkeypatch.setenv('JTB_RD_TEMPLATE_REVIEWERS', actor if review else '')
    return client


def post(client, path, body, key):
    return client.post('/api/rd/' + path, json=body, headers={'Idempotency-Key': key})


def fixture_rule(client, tmp_path):
    baseline = tmp_path / 'fixture-baseline.docx'
    doc = Document()
    doc.add_heading('技术指标', 1)
    doc.add_heading('其他要求', 1)
    doc.save(baseline)
    operations = [{'operation': 'add_after', 'anchor_slot': get_template_outline(str(baseline))[0]['id'], 'new_title': '专业试验方法', 'reason': '测试夹具差异'}]
    taxonomy = load_taxonomy()
    mapping = {group: {key: {'label': key, 'target_heading_keywords': ['技术指标' if key == 'performance_indicator' else '其他要求'], 'target_heading_level': 1}
                        for key in taxonomy.get(group, {})} for group in ('semantic_roles', 'categories')}
    profile = {'product_type': 'low_frequency_rectangular', 'indicator_map': {'测试': [{'name': '测试频率', 'tech_kws': ['测试频率']}]},
               'indicator_sources': {'workbook': False, 'reference_families': []},
               'professional_evidence_contract': {'indicators': {'labels': ['指标']}, 'methods': {'labels': ['方法']}, 'criteria': {'labels': ['判据']}},
               'semantic_routing': {'copy_source_text_only': True}, 'delivery_gate': {'required_headings': ['技术指标', '专业试验方法'], 'min_indicator_rows': 1},
               'qa_profile': {'required_headings': ['技术指标']}}
    payload = {'target': {'product_type': 'low_frequency_rectangular', 'domain': 'military'}, 'operations': operations, 'reason': 'synthetic fixture'}
    response = client.post('/api/rd/template-rules', data={'payload': json.dumps(payload)}, files={
        'target_profile': ('profile.yaml', yaml.safe_dump(profile, allow_unicode=True).encode()),
        'target_mapping': ('mapping.yaml', yaml.safe_dump(mapping, allow_unicode=True).encode())}, headers={'Idempotency-Key': 'rule-create'})
    assert response.status_code == 200, response.text
    return response.json(), baseline


def fixture_project(client):
    context = {'product_type': 'low_frequency_rectangular', 'product_domain': 'military', 'development_process': '全新',
               'cover_phase': 'S', 'product_series': 'FIXTURE', 'organization_scope': 'non_central_research'}
    project = client.post('/api/rd/projects', json={'title': 'synthetic fixture', 'context': context}).json()
    response = post(client, 'projects/' + project['id'] + '/commands', {'expected_version': project['version'], 'command': 'create_case',
                    'data': {'scenario_id': 'taskbook', 'title': 'fixture'}}, 'case')
    assert response.status_code == 200, response.text
    project = response.json()
    cid = project['cases'][0]['id']
    response = client.post('/api/rd/projects/' + project['id'] + '/cases/' + cid + '/sources',
                           data={'expected_version': str(project['version']), 'role': 'tech'},
                           files={'file': ('fixture.txt', '指标：测试频率 10GHz\n方法：测试方法 A\n判据：测试偏差 1dB\n'.encode())}, headers={'Idempotency-Key': 'source'})
    assert response.status_code == 200, response.text
    return response.json()


def test_rule_upload_roles_server_identity_separate_approval_and_publication(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    rule, _ = fixture_rule(client, tmp_path)
    assert rule['status'] == 'draft' and 'approval' not in rule
    assert client.get('/api/rd/template-rules').json()['total'] == 1
    denied = post(client, 'template-rules/' + rule['id'] + '/review', {'approved': True, 'reason': 'x', 'expected_digest': rule['digest'], 'reviewer': 'forged'}, 'forged')
    assert denied.status_code == 422
    response = post(client, 'template-rules/' + rule['id'] + '/publish', {'expected_digest': rule['digest']}, 'early')
    assert response.status_code == 422
    approved = post(client, 'template-rules/' + rule['id'] + '/review', {'approved': True, 'reason': 'fixture review', 'expected_digest': rule['digest']}, 'review')
    assert approved.status_code == 200, approved.text
    published = post(client, 'template-rules/' + rule['id'] + '/publish', {'expected_digest': approved.json()['digest']}, 'publish')
    assert published.status_code == 200, published.text
    assert post(client, 'template-rules/' + rule['id'] + '/publish', {'expected_digest': approved.json()['digest']}, 'publish').json() == published.json()
    monkeypatch.setenv('JTB_RD_TEMPLATE_REVIEWERS', '')
    assert post(client, 'template-rules/' + rule['id'] + '/review', {'approved': False}, 'denied').status_code == 403
    monkeypatch.setenv('JTB_RD_TEMPLATE_PUBLISHERS', '')
    assert client.get('/api/rd/template-rules').status_code == 403
    assert client.get('/api/rd/template-derivations').status_code == 403


def test_positive_fixture_candidate_uses_real_uploads_governed_rule_and_fixed_project_sources(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    rule, baseline = fixture_rule(client, tmp_path)
    approved = post(client, 'template-rules/' + rule['id'] + '/review', {'approved': True, 'reason': 'synthetic fixture review', 'expected_digest': rule['digest']}, 'review').json()
    published = post(client, 'template-rules/' + rule['id'] + '/publish', {'expected_digest': approved['digest']}, 'publish').json()
    project = fixture_project(client)
    case = project['cases'][0]
    source = case['sources'][0]
    monkeypatch.setattr(controller, 'resolve_template_selection', lambda *_: SimpleNamespace(template_path=baseline))
    quotes = ['指标：测试频率 10GHz', '方法：测试方法 A', '判据：测试偏差 1dB']
    citations = [{'source_id': source['id'], 'version': source['version'], 'sha256': source['sha256'],
                  'location': {'line': index + 1, 'body_index': index}, 'quote': quote} for index, quote in enumerate(quotes)]
    payload = {'baseline_product_type': 'low_frequency_rectangular', 'baseline_domain': 'military',
               'target': {'product_type': 'low_frequency_rectangular', 'product_label': '测试夹具产品', 'domain': 'military', 'domain_label': '测试领域', 'version': 'fixture_v1'},
               'project_id': project['id'], 'case_id': case['id'], 'source_ids': [source['id']], 'rule_id': published['id'],
               'professional_evidence': {key: [citation] for key, citation in zip(('indicators', 'methods', 'criteria'), citations)}}
    response = post(client, 'template-derivations', payload, 'derive')
    assert response.status_code == 200, response.text
    candidate = response.json()
    assert candidate['status'] == 'validated' and candidate['validation']['passed'] is True
    assert candidate['asset_manifest']['files']
    assert post(client, 'template-derivations', payload, 'derive').json() == candidate
    cid = candidate['candidate_id']
    assert client.get('/api/rd/template-derivations/' + cid).json()['candidate_id'] == cid
    # No production evidence or enterprise high-frequency qualification is faked.
    response = post(client, 'template-derivations/' + cid + '/regression', {'project_id': project['id'], 'case_id': case['id'],
        'expected_input_revision': case['input_revision']}, 'regression')
    assert response.status_code == 422
    assert post(client, 'template-derivations/' + cid + '/publish', {'expected_target_digest': candidate['target_digest']}, 'publish-candidate').status_code == 422
    assert client.get('/api/rd/template-derivations/' + cid + '/assets/../../../../rd.sqlite3').status_code in {404, 422}
    # Cross-project requests cannot read a source even with a template role.
    stranger = client_for(tmp_path / 'stranger', monkeypatch)
    assert post(stranger, 'template-derivations', payload, 'foreign').status_code in {403, 404}


def test_malformed_asset_objects_fail_as_validation_errors(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    response = client.post('/api/rd/template-rules', data={'payload': json.dumps({'target': {'product_type': 'x', 'domain': 'military'},
        'operations': [{'operation': 'rename', 'target_slot': 'x', 'new_title': 'y'}], 'reason': 'fixture'})}, files={
        'target_profile': ('profile.yaml', b'semantic_routing: []\nindicator_map: []\ndelivery_gate: []\nqa_profile: []'),
        'target_mapping': ('mapping.yaml', b'categories: []')}, headers={'Idempotency-Key': 'bad'})
    assert response.status_code == 422
    assert post(client, 'template-derivations', {'target': []}, 'bad-target').status_code == 422


def test_legacy_candidate_version_and_rule_writes_share_governance_guards(tmp_path, monkeypatch):
    from src.controller import taskbook_controller
    client = client_for(tmp_path, monkeypatch, prepare=False, review=False)
    client.app.include_router(taskbook_controller.router)
    assert client.get('/api/templates/candidates').status_code == 403
    assert client.post('/api/templates/candidates/missing/review', data={'approved': 'true', 'reviewer': 'forged', 'reason': 'forged',
        'regression_passed': 'true', 'visual_review_passed': 'true'}).status_code == 403
    assert client.post('/api/templates/candidates/missing/publish', data={'publisher': 'forged'}).status_code == 403
    assert client.post('/api/templates/candidates/missing/rollback', data={'actor': 'forged', 'reason': 'x'}).status_code == 403
    assert client.post('/api/templates/versions/missing/activate', data={'expected_revision': 'x', 'actor': 'forged'}).status_code == 403
    assert client.put('/api/rules/template_catalog', json={'expected_revision': 'x', 'changes': []}).status_code == 403


def test_missing_regression_and_visual_evidence_do_not_raise_server_errors(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    lifecycle = controller._lifecycle(SimpleNamespace(app=client.app))
    candidate = lifecycle.candidate_root / 'candidate'
    candidate.mkdir(parents=True)
    report = {'machine_validation_passed': True, 'product_type': 'fixture', 'domain': 'military',
              'files': {'template': 'tpl.docx', 'profile': 'profile.yaml', 'mapping': 'mapping.yaml', 'catalog_patch': 'catalog_patch.yaml'}}
    for filename in report['files'].values():
        (candidate / filename).write_text('fixture', encoding='utf-8')
    (candidate / 'onboarding_report.json').write_text(json.dumps(report), encoding='utf-8')
    response = post(client, 'template-derivations/candidate/review', {'approved': True, 'reason': 'fixture', 'expected_manifest_digest': 'missing'}, 'approve')
    assert response.status_code in {404, 422}
    image = io.BytesIO()
    Image.new('RGB', (10, 10)).save(image, format='PNG')
    response = client.post('/api/rd/template-derivations/candidate/visual-review', data={'expected_asset_digest': controller.core_asset_digest(candidate),
        'conclusion': 'passed', 'reason': 'fixture'}, files=[('pages', ('page.png', image.getvalue()))], headers={'Idempotency-Key': 'visual'})
    assert response.status_code in {404, 422}


def test_known_failed_mutation_can_retry_same_key_with_retained_attempt(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    from fastapi import Request
    attempts = []
    @client.app.post('/retry-fixture')
    async def retry(request: Request):
        def operation():
            attempts.append(len(attempts) + 1)
            if len(attempts) == 1:
                raise ValueError('known fixture failure')
            return {'fixture_attempt': attempts[-1]}
        return await controller._mutate(request, {'fixture': True}, operation)
    # The standalone route has normal FastAPI HTTPException handling.
    assert client.post('/retry-fixture', headers={'Idempotency-Key': 'retry'}).status_code == 422
    success = client.post('/retry-fixture', headers={'Idempotency-Key': 'retry'})
    assert success.status_code == 200 and success.json() == {'fixture_attempt': 2}
    assert client.post('/retry-fixture', headers={'Idempotency-Key': 'retry'}).json() == success.json()
    assert attempts == [1, 2]


def test_legacy_onboarding_candidate_has_complete_authorized_evidence_and_publish_path(tmp_path, monkeypatch):
    """Synthetic engine stub verifies HTTP compatibility, not enterprise QA."""
    from src.controller import taskbook_controller
    from jonhon_taskbook.template_onboarding import prepare_template_candidate
    client = client_for(tmp_path, monkeypatch)
    lifecycle = controller._lifecycle(SimpleNamespace(app=client.app))
    state = taskbook_controller._RuntimeState()
    state.asset_lifecycle, state.template_candidate_dir, state.max_upload_bytes = lifecycle, lifecycle.candidate_root, 2_000_000
    monkeypatch.setattr(taskbook_controller, '_STATE', state)
    client.app.include_router(taskbook_controller.router)
    def mapper(_, payload):
        body = json.loads(payload)
        slots = {s['title']: s['id'] for s in body['slots']}
        return {'mappings': [{'category': c['category'], 'target_slot': slots['技术指标' if c['category'] == 'performance_indicator' else '其他要求'],
                             'confidence': 1, 'reason': 'synthetic legacy compatibility fixture'} for c in body['categories']]}
    def prepare(*args, **kwargs):
        return prepare_template_candidate(*args, **kwargs, chat_json_fn=mapper)
    monkeypatch.setattr(taskbook_controller, 'prepare_template_candidate', prepare)
    doc, content = Document(), io.BytesIO()
    doc.add_heading('技术指标', 1)
    doc.add_heading('其他要求', 1)
    doc.save(content)
    response = client.post('/api/templates/onboard', data={'product_type': 'low_frequency_rectangular', 'product_label': '兼容测试夹具',
        'domain': 'military', 'domain_label': '测试领域', 'version': 'legacy_fixture'}, files={'template': ('legacy.docx', content.getvalue())})
    assert response.status_code == 200, response.text
    cid = response.json()['candidate_id']
    listed = client.get('/api/rd/template-derivations').json()['items']
    old = next(c for c in listed if c['candidate_id'] == cid)
    assert old['kind'] == 'template_onboarding' and old['project_binding'] is None
    project = fixture_project(client)
    case = project['cases'][0]
    binding = {'project_id': project['id'], 'case_id': case['id'], 'source_ids': [s['id'] for s in case['sources']],
               'expected_input_revision': case['input_revision'], 'expected_manifest_digest': old['asset_manifest']['digest']}
    stale = post(client, 'template-derivations/' + cid + '/bind-project', {**binding, 'expected_manifest_digest': 'stale'}, 'stale-bind')
    assert stale.status_code == 409
    bound = post(client, 'template-derivations/' + cid + '/bind-project', binding, 'bind')
    assert bound.status_code == 200, bound.text
    assert post(client, 'template-derivations/' + cid + '/bind-project', binding, 'bind').json() == bound.json()
    def synthetic_runner(**_):
        def run(candidate, case):
            output = candidate / 'synthetic_legacy_regression.docx'
            document = Document()
            document.add_paragraph('Synthetic compatibility fixture; no enterprise validation claimed.')
            document.save(output)
            return {'engine': 'src.pipeline_cli.run_pipeline', 'checks': [{'id': 'synthetic_contract', 'passed': True}],
                    'outputs': [{'file': output.name}]}
        return run
    monkeypatch.setattr(controller, 'OriginalPipelineRegressionRunner', synthetic_runner)
    regression = post(client, 'template-derivations/' + cid + '/regression', {'project_id': project['id'], 'case_id': case['id'],
        'expected_input_revision': case['input_revision']}, 'regression')
    assert regression.status_code == 200, regression.text
    detail = client.get('/api/rd/template-derivations/' + cid).json()
    page = io.BytesIO()
    Image.new('RGB', (20, 20), 'white').save(page, format='PNG')
    visual = client.post('/api/rd/template-derivations/' + cid + '/visual-review', data={'expected_asset_digest': detail['asset_digest'],
        'conclusion': 'passed', 'reason': 'synthetic compatibility fixture review'}, files=[('pages', ('page.png', page.getvalue()))], headers={'Idempotency-Key': 'visual'})
    assert visual.status_code == 200, visual.text
    detail = client.get('/api/rd/template-derivations/' + cid).json()
    approved = post(client, 'template-derivations/' + cid + '/review', {'approved': True, 'reason': 'synthetic lifecycle test',
        'expected_manifest_digest': detail['asset_manifest']['digest']}, 'approve')
    assert approved.status_code == 200, approved.text
    published = post(client, 'template-derivations/' + cid + '/publish', {'expected_target_digest': approved.json()['target_digest']}, 'publish-candidate')
    assert published.status_code == 200 and published.json()['status'] == 'published', published.text
    rolled_back = post(client, 'template-derivations/' + cid + '/rollback', {'reason': 'synthetic lifecycle fixture cleanup'}, 'rollback')
    assert rolled_back.status_code == 200 and rolled_back.json()['status'] == 'rolled_back'
