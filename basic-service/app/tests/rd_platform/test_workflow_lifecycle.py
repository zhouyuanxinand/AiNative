"""Workflow configuration drafts and governed history stay separate from execution."""
from copy import deepcopy

import pytest

from test_store import new_store, case_project, issue
from test_workflow_templates import EDITOR, PUBLISHER, save_template
from tests.rd_platform.test_http import make_client


def command(store, fixed, operation, key, **extra):
    return store.workflow_templates.save('publisher', PUBLISHER, {
        'id': fixed['id'], 'version': fixed['version'], 'operation': operation,
        'expected_version': int(fixed['head_version']),
        'expected_state_revision': fixed['publication_revision'], **extra,
    }, key)


def test_incomplete_connections_are_saved_but_preview_and_publication_reject(tmp_path):
    store = new_store(tmp_path)
    original = store.workflow_templates.detail('owner', 'taskbook-selection-v2', '2')
    graph = deepcopy(original['graph'])
    graph['edges'].pop()
    draft = store.workflow_templates.save('editor', EDITOR, {
        'id': 'unfinished', 'expected_version': 0, 'category': 'selection',
        'title': '尚未连完的流程', 'graph': graph, 'change_note': '调整最后一个节点的前置关系',
    }, 'draft')
    assert draft['status'] == 'draft' and draft['graph'] == graph
    before = store.workflow_templates.history('editor', draft['id'], EDITOR, management=True)
    result = store.workflow_templates.validate('editor', EDITOR, {
        'category': 'selection', 'graph': graph})
    assert result['valid'] is False and result['errors']
    assert store.workflow_templates.history('editor', draft['id'], EDITOR, management=True) == before
    with pytest.raises(Exception) as error:
        command(store, draft, 'publish', 'invalid-publish')
    assert error.value.status == 422
    assert store.workflow_templates.detail('editor', draft['id'], '1', EDITOR, management=True)['status'] == 'draft'


def test_fixed_validation_is_audited_and_replay_has_one_event(tmp_path):
    store = new_store(tmp_path)
    first = save_template(store)
    result = command(store, first, 'validate', 'validate')
    assert result['validation']['valid'] is True
    assert result['status'] == 'draft' and result['digest'] == first['digest']
    assert command(store, first, 'validate', 'validate') == result
    history = store.workflow_templates.history('editor', first['id'], EDITOR, management=True)
    assert [e['operation'] for e in history['events']].count('validate') == 1
    assert history['items'][0]['validation']['valid'] is True
    with pytest.raises(Exception) as error:
        command(store, first, 'publish', 'validate')
    assert error.value.status == 409


def test_publication_rechecks_current_resource_authorization_after_validation(tmp_path):
    from test_workspace import grant
    store = new_store(tmp_path)
    base = store.workflow_templates.detail('owner', 'taskbook-new-v1', '1')
    draft = store.workflow_templates.save('editor', EDITOR, {'id': 'authorization-recheck',
        'expected_version': 0, 'category': 'research', 'product_route': 'new',
        'title': '需重新核对动作授权', 'graph': base['graph']}, 'new-draft')
    checked = command(store, draft, 'validate', 'checked')
    assert checked['validation']['valid']
    grant(store, 'taskbook-authoring-team', revision=1, operation='revoke', key='revoked')
    with pytest.raises(Exception) as error:
        command(store, checked, 'publish', 'publish-after-revoke')
    assert error.value.status == 422
    assert store.workflow_templates.detail('editor', draft['id'], '1', EDITOR, management=True)['status'] == 'draft'


def test_lifecycle_retirement_and_history_restore_create_new_immutable_version(tmp_path):
    store = new_store(tmp_path)
    first = save_template(store)
    published = command(store, first, 'publish', 'publish')
    with pytest.raises(Exception) as error:
        command(store, published, 'publish', 'publish-again')
    assert error.value.status == 409
    retired = command(store, published, 'retire', 'retire', change_note='由新规范替代')
    with pytest.raises(Exception) as error:
        command(store, retired, 'publish', 'reactivate')
    assert error.value.status == 409
    restored = store.workflow_templates.save('editor', EDITOR, {
        'id': first['id'], 'expected_version': 1, 'category': 'selection',
        'title': '重新评审历史流程', 'graph': first['graph'],
        'based_on': {'id': first['id'], 'version': '1', 'digest': first['digest']},
        'change_note': '基于停用版本重新编排',
    }, 'restore')
    assert restored['version'] == '2' and restored['status'] == 'draft'
    assert restored['based_on']['digest'] == first['digest']
    old = store.workflow_templates.detail('editor', first['id'], '1', EDITOR, management=True)
    assert old['graph'] == first['graph'] and old['digest'] == first['digest'] and old['status'] == 'retired'
    history = new_store(tmp_path).workflow_templates.history('editor', first['id'], EDITOR, management=True, page=1, page_size=1)
    assert history['total'] == 2 and history['total_pages'] == 2
    assert history['items'][0]['version'] == '2' and all(e['version'] == '2' for e in history['events'])
    assert history['items'][0]['change_note'] == '基于停用版本重新编排'


def test_untrusted_baseline_and_stale_save_do_not_create_versions(tmp_path):
    store = new_store(tmp_path)
    first = save_template(store)
    payload = {'id': first['id'], 'expected_version': 1, 'category': 'selection',
        'title': '变更', 'graph': first['graph'],
        'based_on': {'id': first['id'], 'version': '1', 'digest': 'forged'}}
    with pytest.raises(Exception) as error:
        store.workflow_templates.save('editor', EDITOR, payload, 'bad-reference')
    assert error.value.status == 409
    payload['based_on']['digest'] = first['digest']
    second = store.workflow_templates.save('editor', EDITOR, payload, 'saved')
    assert second['version'] == '2'
    with pytest.raises(Exception) as error:
        store.workflow_templates.save('editor', EDITOR, payload, 'stale')
    assert error.value.status == 409
    assert store.workflow_templates.history('editor', first['id'], EDITOR, management=True)['total'] == 2


def test_history_references_only_authorized_projects_and_keeps_adoption_after_retirement(tmp_path):
    store = new_store(tmp_path)
    template = store.workflow_templates.detail('owner', 'taskbook-selection-v2', '2')
    project = case_project(store)
    project = issue(store, project, 'adopt_workflow_template', {'template_id': template['id'],
        'template_version': template['version'], 'template_digest': template['digest']})
    before = deepcopy(project['cases'][0]['workflow_templates']['selection'])
    owner_history = store.workflow_templates.history('owner', template['id'], EDITOR, management=True)
    assert owner_history['usages'][0]['project_id'] == project['id']
    assert owner_history['usages'][0]['current'] is True
    assert store.workflow_templates.history('outsider', template['id'], EDITOR, management=True)['usages'] == []
    command(store, template, 'retire', 'retire-seed')
    assert store.get_project('owner', project['id'])['cases'][0]['workflow_templates']['selection'] == before
    after = store.workflow_templates.history('owner', template['id'], EDITOR, management=True)
    assert after['usages'][0]['template_version'] == '2'


def test_preview_rejects_arbitrary_config_and_cannot_claim_authorization(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    actor = client.get('/api/rd/session').json()['actor_id']
    graph = client.get('/api/rd/workflow-templates/taskbook-selection-v2/2').json()['graph']
    assert client.post('/api/rd/workflow-templates/validate', json={'category': 'selection', 'graph': graph}).status_code == 403
    assert client.get('/api/rd/workflow-templates/taskbook-selection-v2/history?management=true').status_code == 403
    monkeypatch.setenv('JTB_RD_WORKFLOW_PUBLISHERS', actor)
    result = client.post('/api/rd/workflow-templates/validate', json={'category': 'selection', 'graph': graph})
    assert result.status_code == 200 and result.json()['valid']
    graph['edges'][0]['condition'] = 'eval("user code")'
    invalid = client.post('/api/rd/workflow-templates/validate', json={'category': 'selection', 'graph': graph})
    assert invalid.status_code == 200 and not invalid.json()['valid']
    assert client.post('/api/rd/workflow-templates/validate', json={'category': 'selection', 'graph': graph, 'actor': 'admin'}).status_code == 422
    assert client.post('/api/rd/workflow-templates/validate', json={'category': 'selection', 'graph': graph}, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    history = client.get('/api/rd/workflow-templates/taskbook-selection-v2/history?management=true&page=1&page_size=5')
    assert history.status_code == 200 and history.json()['items'][0]['version'] == '2'
