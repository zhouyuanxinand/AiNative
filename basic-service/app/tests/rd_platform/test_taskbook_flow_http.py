"""Public commands carry the adopted business baseline into the real worker queue."""
import json

from tests.rd_platform.test_http import make_client


def prepared_case(client):
    client.app.state.rd_store.local_review_enabled = True
    project = client.post('/api/rd/projects', json={'title': 'HTTP验收项目', 'customer_name': '验收客户'}).json()
    def command(name, **data):
        nonlocal project
        if project['cases'] and name != 'save_project_profile':
            data.setdefault('case_id', project['cases'][0]['id'])
        response = client.post(f"/api/rd/projects/{project['id']}/commands",
            json={'expected_version': project['version'], 'command': name, 'data': data},
            headers={'Idempotency-Key': f"http-{project['version']}-{name}"})
        assert response.status_code == 200, response.text
        project = response.json()
        return project
    command('create_case', scenario_id='taskbook', title='任务书业务案例')
    command('save_context', context={'product_type': 'low_frequency_rectangular', 'product_domain': 'military',
        'development_process': '全新', 'cover_phase': 'S', 'product_series': 'HTTP-TEST', 'organization_scope': 'non_central_research'})
    cid = project['cases'][0]['id']
    for role in ('tech', 'spec'):
        response = client.post(f"/api/rd/projects/{project['id']}/cases/{cid}/sources",
            data={'expected_version': project['version'], 'role': role}, files={'file': (role + '.txt', b'HTTP test evidence')},
            headers={'Idempotency-Key': 'upload-' + role})
        assert response.status_code == 200, response.text
        project = response.json()
    sid = project['cases'][0]['sources'][0]['id']
    command('save_requirement', title='试验条件', content='按上传资料中的条件核对', source_ids=[sid])
    command('confirm_requirements', expected_input_revision=project['cases'][0]['input_revision'], scope='本次需求', source_ids=[sid])
    for axis, kind, route in (('product', 'product', 'new'), ('composition', 'document', 'direct')):
        rid = project['cases'][0]['requirements'][0]['id']
        command('save_comparison', kind=kind, title='HTTP逐项比对', source_ids=[sid],
            rows=[{'requirement_id': rid, 'assessment': 'match', 'candidate_value': '按上传资料', 'reason': '依据原资料核对', 'source_ids': [sid]}])
        comparison_id = project['cases'][0]['comparisons'][-1]['id']
        command('record_route_decision', axis=axis, value=route, rationale='本次业务范围依据', source_ids=[sid], comparison_id=comparison_id)
    command('prepare_selection_review', expected_input_revision=project['cases'][0]['input_revision'])
    bundle = project['cases'][0]['review_bundles'][-1]
    command('record_selection_decision', bundle_id=bundle['id'], bundle_digest=bundle['digest'], verdict='approved', scope='当前选型报告', rationale='负责人核对固定版本')
    command('authorize_rd_start', selection_decision_id=project['cases'][0]['business_lifecycle']['current_selection_decision_id'], scope='本次新研范围', rationale='承接选型差异')
    command('adopt_taskbook_flow', workflow_id='taskbook-new-v1', workflow_version='1', scope='本项目新研任务书', rationale='按当前需求与两类比对采用')
    return project, command, sid


def test_http_flow_freezes_two_templates_and_business_baseline(tmp_path):
    client = make_client(tmp_path)
    project, command, sid = prepared_case(client)
    binding = project['cases'][0]['taskbook_binding']
    assert binding['workflow']['id'] == 'taskbook-new-v1'
    assert binding['document_template']['template_sha256']
    assert binding['business_context']['customer_name'] == '验收客户'
    assert '"path"' not in json.dumps(binding)
    project = command('pull_workpackage', definition_id='taskbook')
    wid = project['cases'][0]['workpackages'][-1]['id']
    project = command('create_flow_draft', workpackage_id=wid)
    draft = project['cases'][0]['flow_drafts'][-1]
    project = command('prepare_execution_bundle', draft_id=draft['id'])
    candidate = project['cases'][0]['execution_candidates'][-1]
    project = command('adopt_execution_bundle', candidate_id=candidate['id'], candidate_digest=candidate['digest'])
    project = command('submit_workpackage', workpackage_id=wid)
    package = project['cases'][0]['workpackages'][-1]
    assert package['status'] == 'submitted'
    assert package['stage'] == 'planning' and package['definition_version'] == '2'
    assert package['snapshot']['taskbook_binding']['fingerprint'] == binding['fingerprint']
    assert all(node['status'] == 'submitted' for node in package['nodes'])
    outsider = make_client(tmp_path)
    assert outsider.get(f"/api/rd/projects/{project['id']}").status_code == 404


def test_http_profile_change_does_not_silently_reuse_adoption(tmp_path):
    client = make_client(tmp_path)
    project, command, _ = prepared_case(client)
    original = project['cases'][0]['taskbook_binding']['fingerprint']
    project = command('save_project_profile', title='HTTP验收项目', customer_name='变更后的客户', brief='', product_name='')
    case = project['cases'][0]
    assert case['taskbook_binding']['status'] == 'stale'
    assert case['taskbook_binding_history'][0]['fingerprint'] == original
    assert case['stage'] == 'input'
