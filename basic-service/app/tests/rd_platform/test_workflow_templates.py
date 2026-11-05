"""Business workflow publication and adoption are separate from resources/runs."""
from copy import deepcopy
import pytest
from test_store import new_store, issue, case_project, evidence_project

EDITOR = {'can_edit_workflows': True}
PUBLISHER = {'can_publish_workflows': True}


def save_template(store, *, rid='custom-selection'):
    base = store.workflow_templates.detail('owner', 'taskbook-selection-v2', '2')
    return store.workflow_templates.save('editor', EDITOR, {'id': rid, 'expected_version': 0,
        'category': 'selection', 'title': '受控选型模板', 'graph': base['graph']}, 'save-' + rid)


def test_separate_roles_immutable_revisions_publish_cas_and_restart(tmp_path):
    store = new_store(tmp_path)
    first = save_template(store)
    assert first['status'] == 'draft'
    with pytest.raises(Exception) as error:
        store.workflow_templates.detail('owner', first['id'], '1')
    assert error.value.status == 404
    with pytest.raises(Exception) as error:
        store.workflow_templates.save('workspace-publisher', {'can_publish_resources': True}, {
            'id': first['id'], 'operation': 'publish', 'expected_version': 1, 'expected_state_revision': 1}, 'denied')
    assert error.value.status == 403
    published = store.workflow_templates.save('publisher', PUBLISHER, {'id': first['id'], 'operation': 'publish',
        'expected_version': 1, 'expected_state_revision': 1}, 'publish')
    assert published['digest'] == first['digest']
    second = store.workflow_templates.save('editor', EDITOR, {'id': first['id'], 'expected_version': 1,
        'category': 'selection', 'title': '新版', 'graph': first['graph']}, 'save-v2')
    assert second['version'] == '2'
    assert store.workflow_templates.detail('owner', first['id'])['version'] == '1'
    assert new_store(tmp_path).workflow_templates.detail('owner', first['id'], '1')['digest'] == first['digest']
    assert store.workflow_templates.list('owner', category='selection', q='受控')['total'] == 1
    with pytest.raises(Exception) as error:
        store.workflow_templates.save('publisher', PUBLISHER, {'id': first['id'], 'operation': 'retire',
            'expected_version': 2, 'version': '1', 'expected_state_revision': 1}, 'stale')
    assert error.value.status == 409


def test_cannot_publish_missing_gate_loop_or_arbitrary_expression(tmp_path):
    store = new_store(tmp_path)
    base = store.workflow_templates.detail('owner', 'taskbook-selection-v2', '2')
    missing = deepcopy(base['graph'])
    missing['nodes'] = [n for n in missing['nodes'] if n['id'] != 'selection_decision']
    missing['edges'] = [e for e in missing['edges'] if 'selection_decision' not in (e['source'], e['target'])]
    loop = deepcopy(base['graph'])
    loop['edges'].append({'id': 'cycle', 'source': 'rd_start', 'target': 'input'})
    expression = deepcopy(base['graph'])
    expression['edges'][0]['condition'] = 'eval(user_value)'
    for i, graph in enumerate((missing, loop)):
        # An incomplete configuration can be saved for later editing, but it
        # remains unavailable for adoption until the full publication check.
        draft = store.workflow_templates.save('editor', EDITOR, {'expected_version': 0, 'category': 'selection',
            'title': '待完善图', 'graph': graph}, str(i))
        with pytest.raises(Exception) as error:
            store.workflow_templates.save('publisher', PUBLISHER, {'id': draft['id'], 'version': '1',
                'operation': 'publish', 'expected_version': 1, 'expected_state_revision': 1}, 'publish-' + str(i))
        assert error.value.status == 422
    with pytest.raises(Exception) as error:
        store.workflow_templates.save('editor', EDITOR, {'expected_version': 0, 'category': 'selection',
            'title': '任意表达式始终不能保存', 'graph': expression}, 'expression')
    assert error.value.status == 422


def test_selection_adoption_has_no_research_package_or_engineering_approval(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    template = store.workflow_templates.detail('owner', 'taskbook-selection-v2', '2')
    project = issue(store, project, 'adopt_workflow_template', {'template_id': template['id'],
        'template_version': template['version'], 'template_digest': template['digest']})
    case = project['cases'][0]
    assert case['workpackages'] == []
    assert case['workflow_templates']['selection']['node_states']['selection_decision'] == 'pending_decision'
    assert not case['business_lifecycle']['current_selection_decision_id']
    assert new_store(tmp_path).get_project('owner', project['id']) == project


def test_direct_selection_cannot_adopt_research_template(tmp_path):
    store = new_store(tmp_path)
    project = evidence_project(store, product_route='direct', stop_at_planning=True)
    template = store.workflow_templates.detail('owner', 'taskbook-new-v1', '1')
    with pytest.raises(Exception) as error:
        issue(store, project, 'adopt_workflow_template', {'template_id': template['id'],
            'template_version': template['version'], 'template_digest': template['digest']})
    assert error.value.status == 422
    assert project['cases'][0]['workpackages'] == []


def test_adopted_business_graph_team_version_and_added_actions_reach_worker(tmp_path):
    from test_workspace import PUBLISHER as RESOURCE_PUBLISHER, publish, grant
    from service.rd_platform.runtime import Worker
    store = new_store(tmp_path)
    team = store.workspace.management_detail('publisher', RESOURCE_PUBLISHER, 'taskbook-authoring-team', 1)
    config = deepcopy(team['configuration'])
    config['members'].append({'resource_id': 'consistency', 'resource_version': 1})
    config['execution_graph']['nodes'].append({'id': 'consistency', 'resource_id': 'consistency', 'resource_version': 1})
    config['execution_graph']['edges'] = [e for e in config['execution_graph']['edges'] if not (e['source'] == 'content_completion' and e['target'] == 'generate')]
    config['execution_graph']['edges'].extend([{'id': 'to-check', 'source': 'content_completion', 'target': 'consistency'},
        {'id': 'from-check', 'source': 'consistency', 'target': 'generate'}])
    revised = store.workspace.save_resource('publisher', RESOURCE_PUBLISHER, {'id': team['id'], 'kind': 'team',
        'name': team['name'], 'expected_version': 1, 'configuration': config}, 'team-v2')
    publish(store, revised, 'publish-team-v2')
    grant(store, team['id'], version=2, key='grant-team-v2')
    workflow = store.workflow_templates.detail('owner', 'taskbook-new-v1', '1')
    graph = deepcopy(workflow['graph'])
    taskbook_node = next(n for n in graph['nodes'] if n['id'] == 'taskbook')
    taskbook_node['action_resource']['resource_version'] = 2
    graph['nodes'].append({'id': 'extra-check', 'title': '额外一致性', 'role': '质量工程师', 'deliverables': ['检查记录'],
        'position': {'x': 100, 'y': 120}, 'action_resource': {'resource_id': 'consistency-team', 'resource_version': 1},
        'workpackage_definition_id': 'taskbook'})
    graph['edges'] = [e for e in graph['edges'] if not (e['source'] == 'taskbook' and e['target'] == 'taskbook_scope')]
    graph['edges'].extend([{'id': 'to-extra', 'source': 'taskbook', 'target': 'extra-check'},
        {'id': 'from-extra', 'source': 'extra-check', 'target': 'taskbook_scope'}])
    workflow = store.workflow_templates.save('editor', EDITOR, {'id': 'custom-research', 'expected_version': 0,
        'category': 'research', 'product_route': 'new', 'title': '实际采用固定专家团', 'graph': graph}, 'business-v1')
    workflow = store.workflow_templates.save('publisher', PUBLISHER, {'id': workflow['id'], 'operation': 'publish',
        'expected_version': 1, 'expected_state_revision': 1}, 'publish-business')
    project = evidence_project(store, stop_at_planning=True)
    project = issue(store, project, 'adopt_taskbook_flow', {'workflow_id': workflow['id'], 'workflow_version': '1',
        'scope': '实际采用图', 'rationale': '测试固定版团队和附加节点'})
    assert project['cases'][0]['workflow_templates']['research']['template_id'] == workflow['id']
    source_id = project['cases'][0]['sources'][0]['id']
    project = issue(store, project, 'advance_stage', {'stage': 'planning', 'verdict': 'approved', 'rationale': '历史政策设计准入', 'source_ids': [source_id]})
    project = issue(store, project, 'pull_workpackage', {'definition_id': 'taskbook'})
    wid = project['cases'][0]['workpackages'][-1]['id']
    project = issue(store, project, 'create_flow_draft', {'workpackage_id': wid})
    draft = project['cases'][0]['flow_drafts'][-1]
    assert {n['business_node_id'] for n in draft['graph']['nodes']} == {'taskbook', 'extra-check'}
    project = issue(store, project, 'prepare_execution_bundle', {'draft_id': draft['id']})
    candidate = project['cases'][0]['execution_candidates'][-1]
    assert len(candidate['compiled_plan']) == 7
    assert any(l['resource_id'] == team['id'] and l['resource_version'] == 2 for l in candidate['resource_locks'])
    assert {m['business_node_id'] for m in candidate['mapping']} == {'taskbook', 'extra-check'}
    project = issue(store, project, 'adopt_execution_bundle', {'candidate_id': candidate['id'], 'candidate_digest': candidate['digest']})
    project = issue(store, project, 'submit_workpackage', {'workpackage_id': wid})
    calls = []
    def execute(action, *args):
        calls.append(action)
        return {'status': 'completed', 'result': {}}
    worker = Worker(store, execute)
    while worker.tick():
        pass
    assert calls == ['resolve_context', 'template_plan', 'content_completion', 'consistency', 'generate', 'verify', 'consistency']
    completed_case = store.get_project('owner', project['id'])['cases'][0]
    view = completed_case['workflow_templates']['research']
    assert view['node_states']['taskbook'] == view['node_states']['extra-check'] == 'completed'
    assert view['node_states']['taskbook_scope'] == 'pending_decision'
    assert view['node_execution_refs']['extra-check']['run_id'] == completed_case['workpackages'][0]['run_id']
    history = store.workflow_templates.history('owner', workflow['id'], EDITOR, management=True)
    assert any(item['reference_type'] == 'run' and item['run_id'] == completed_case['workpackages'][0]['run_id']
               for item in history['usages'])
    assert store.workflow_templates.history('outsider', workflow['id'], EDITOR, management=True)['usages'] == []
    assert store.workspace.catalog_detail(team['id'], 1)['version'] == 1
    # Retiring V1 application consent must not make an explicitly adopted V2
    # silently fall back to V1 or prevent its otherwise authorized next package.
    grant(store, team['id'], revision=1, operation='revoke', key='revoke-team-v1')
    project = store.get_project('owner', project['id'])
    project = issue(store, project, 'pull_workpackage', {'definition_id': 'taskbook'})
    project = issue(store, project, 'create_flow_draft', {'workpackage_id': project['cases'][0]['workpackages'][-1]['id']})
    assert next(n for n in project['cases'][0]['flow_drafts'][-1]['graph']['nodes'] if n['business_node_id'] == 'taskbook')['resource_version'] == 2
    replacement_id = project['cases'][0]['workpackages'][-1]['id']
    draft = project['cases'][0]['flow_drafts'][-1]
    project = issue(store, project, 'prepare_execution_bundle', {'draft_id': draft['id']})
    candidate = project['cases'][0]['execution_candidates'][-1]
    project = issue(store, project, 'adopt_execution_bundle', {'candidate_id': candidate['id'], 'candidate_digest': candidate['digest']})
    project = issue(store, project, 'submit_workpackage', {'workpackage_id': replacement_id})
    assert project['cases'][0]['workflow_templates']['research']['node_states']['taskbook'] == 'submitted'
    assert store.claim_node()
    project = store.get_project('owner', project['id'])
    assert project['cases'][0]['workflow_templates']['research']['node_states']['taskbook'] == 'running'
    assert project['cases'][0]['workflow_templates']['research']['node_execution_refs']['taskbook']['workpackage_id'] == replacement_id
    project = issue(store, project, 'cancel_workpackage', {'workpackage_id': replacement_id})
    assert project['cases'][0]['workflow_templates']['research']['node_states']['taskbook'] == 'cancelled'
    newer = store.workflow_templates.save('editor', EDITOR, {'id': workflow['id'], 'expected_version': 1,
        'category': 'research', 'product_route': 'new', 'title': '下一业务修订', 'graph': graph}, 'business-v2')
    newer = store.workflow_templates.save('publisher', PUBLISHER, {'id': workflow['id'], 'operation': 'publish',
        'expected_version': 2, 'version': '2', 'expected_state_revision': newer['publication_revision']}, 'publish-business-v2')
    project = issue(store, project, 'adopt_workflow_template', {'template_id': newer['id'], 'template_version': '2', 'template_digest': newer['digest']})
    assert project['cases'][0]['taskbook_binding']['status'] == 'stale'
    assert project['cases'][0]['workflow_templates']['research']['node_states']['taskbook'] == 'pending'
    assert project['cases'][0]['workflow_templates']['research']['node_states']['extra-check'] == 'pending'
    assert not project['cases'][0]['workflow_templates']['research']['node_execution_refs']
    stale = deepcopy(completed_case)
    stale['input_revision'] += 1
    store.workflow_templates.project_projection(stale)
    assert stale['workflow_templates']['research']['node_states']['taskbook'] == 'pending'
    assert stale['workflow_templates']['research']['node_states']['extra-check'] == 'pending'
    assert not stale['workflow_templates']['research']['node_execution_refs']
    mismatched = deepcopy(completed_case)
    mismatched['execution_candidates'][0]['digest'] = 'different-candidate'
    store.workflow_templates.project_projection(mismatched)
    assert mismatched['workflow_templates']['research']['node_states']['taskbook'] == 'pending'
    assert not mismatched['workflow_templates']['research']['node_execution_refs']


def test_business_taskbook_cannot_replace_full_contract_or_bind_future_phase(tmp_path):
    store = new_store(tmp_path)
    original = store.workflow_templates.detail('owner', 'taskbook-new-v1', '1')['graph']
    for index, node_id in enumerate(('taskbook', 'scheme')):
        graph = deepcopy(original)
        node = next(n for n in graph['nodes'] if n['id'] == node_id)
        node['action_resource'] = {'resource_id': 'consistency-team', 'resource_version': 1}
        draft = store.workflow_templates.save('editor', EDITOR, {'id': 'invalid-' + str(index), 'expected_version': 0,
            'category': 'research', 'product_route': 'new', 'title': '不允许假绑定', 'graph': graph}, 'invalid-' + str(index))
        with pytest.raises(Exception) as error:
            store.workflow_templates.save('publisher', PUBLISHER, {'id': draft['id'], 'operation': 'publish',
                'expected_version': 1, 'expected_state_revision': 1}, 'publish-invalid-' + str(index))
        assert error.value.status == 422


def test_technical_execution_cannot_complete_business_approval_gate(tmp_path):
    store = new_store(tmp_path)
    template = store.workflow_templates.detail('owner', 'taskbook-selection-v2', '2')
    graph = deepcopy(template['graph'])
    node = next(n for n in graph['nodes'] if n['id'] == 'confirm_requirements')
    node['action_resource'] = {'resource_id': 'consistency-team', 'resource_version': 1}
    with pytest.raises(Exception) as error:
        store.workflow_templates.save('editor', EDITOR, {'id': 'invalid-approval', 'expected_version': 0,
            'category': 'selection', 'title': '技术成功不能代签', 'graph': graph}, 'invalid-approval')
    assert error.value.status == 422
    case = {'input_revision': 1, 'sources': [], 'source_selection': {}, 'workpackages': [], 'execution_candidates': [],
        'business_lifecycle': {}, 'workflow_templates': {'selection': {'id': 'adoption', 'input_revision': 1,
            'template_id': template['id'], 'template_version': template['version'], 'template_digest': template['digest'], 'graph': graph}}}
    store.workflow_templates.project_projection(case)
    assert case['workflow_templates']['selection']['node_states']['confirm_requirements'] == 'pending_decision'
