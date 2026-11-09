"""Published project flows start cases and finish only with current verified output."""
from copy import deepcopy
from pathlib import Path

import pytest

from service.rd_platform.runtime import Worker
from service.rd_platform.store import RdError
from designer_fixture import adopt_plan
from test_requirement_confirmation import confirm, clarify_requirement
from test_selection_activation import CONTEXT, activate, decide, local_store, prepare
from test_store import fixture_comparison, issue
from test_workflow_templates import EDITOR, PUBLISHER
from test_workspace import grant


PROJECT_NODES = ['input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start', 'taskbook']


def project_template(store):
    return store.workflow_templates.detail('owner', 'taskbook-generation', '1')


def template_ref(template):
    return {key: template[key] for key in ('id', 'version', 'digest')}


def start(store, template=None, *, key='start-flow'):
    template = template or project_template(store)
    project = store.create_project('owner', '任务书生成项目')
    return issue(store, project, 'create_case', {
        'workflow_template': template_ref(template), 'title': '按已发布流程办理'}, key=key)


def operation(store, template, name, key):
    return store.workflow_templates.save('publisher', PUBLISHER, {
        'id': template['id'], 'version': template['version'], 'operation': name,
        'expected_version': int(template['head_version']),
        'expected_state_revision': template['publication_revision'],
    }, key)


def save_project_template(store, template, *, rid='custom-project-flow', graph=None):
    return store.workflow_templates.save('editor', EDITOR, {
        'id': rid, 'expected_version': 0, 'category': 'project',
        'title': '定制任务书生成流程', 'graph': graph or template['graph'],
    }, 'save-' + rid)


def activated(store, template=None):
    project = start(store, template)
    project = issue(store, project, 'save_context', {'context': CONTEXT})
    cid = project['cases'][0]['id']
    for role in ('tech', 'spec'):
        project = store.add_source('owner', project['id'], cid, project['version'],
            'source-' + role, role, role + '.txt', b'0.3 MPa source evidence')
    sid = project['cases'][0]['sources'][0]['id']
    project = issue(store, project, 'save_requirement', {
        'title': '压力', 'content': '0.3 MPa', 'source_ids': [sid]})
    project = confirm(store, clarify_requirement(store, project))
    for axis, value in (('product', 'modification'), ('composition', 'direct')):
        project, comparison_id = fixture_comparison(store, project, axis)
        project = issue(store, project, 'record_route_decision', {
            'axis': axis, 'value': value, 'rationale': '按实际来源分别核对',
            'source_ids': [sid], 'comparison_id': comparison_id})
    return activate(store, decide(store, prepare(store, project)))


def bind(store, project, template=None):
    template = template or project_template(store)
    return issue(store, project, 'adopt_taskbook_flow', {
        'workflow_id': template['id'], 'workflow_version': template['version'],
        'scope': '生成任务书为止', 'rationale': '采用项目创建时固定的流程'})


def submitted(store):
    project = bind(store, activated(store))
    project = issue(store, project, 'pull_workpackage', {'definition_id': 'taskbook'})
    wid = project['cases'][0]['workpackages'][-1]['id']
    project = adopt_plan(store, project, wid)
    return issue(store, project, 'submit_workpackage', {'workpackage_id': wid})


def finish(store, *, quality=True, document=True, blocked_action=None):
    calls = []
    def execute(action, snapshot, previous, work_dir, progress, cancelled):
        calls.append(action)
        if action == blocked_action:
            return {'status': 'blocked', 'result': {}, 'blocked_reasons': ['真实依据不足']}
        result = {'execution_mode': 'local_real'}
        artifacts = []
        if action == 'generate' and document:
            path = Path(work_dir) / '任务书.docx'
            path.write_bytes(b'controlled generated document fixture')
            artifacts.append({'id': 'taskbook-output', 'name': path.name, 'kind': 'docx', 'path': str(path)})
        if action == 'verify':
            result['delivery_approved'] = quality
        return {'status': 'completed', 'result': result, 'artifacts': artifacts}
    worker = Worker(store, execute)
    while worker.tick():
        pass
    return calls


def test_project_seed_stops_at_full_taskbook_action(tmp_path):
    store = local_store(tmp_path)
    template = project_template(store)
    assert template['category'] == 'project' and template['status'] == 'published'
    assert template['title'] == '研制任务书生成流程'
    assert [node['id'] for node in template['graph']['nodes']] == PROJECT_NODES
    taskbook = next(node for node in template['graph']['nodes'] if node['id'] == 'taskbook')
    assert taskbook['title'] == '研制任务书生成'
    assert taskbook['action_resource'] == {'resource_id': 'taskbook-authoring-team', 'resource_version': 1}
    assert not any(edge['source'] == 'taskbook' for edge in template['graph']['edges'])
    assert store.workflow_templates.list('owner', category='project')['items'][0]['digest'] == template['digest']


def test_create_case_freezes_published_project_graph_without_approving_business_gates(tmp_path):
    store = local_store(tmp_path)
    template = project_template(store)
    project = start(store, template)
    case = project['cases'][0]
    adoption = case['workflow_templates']['project']
    assert adoption['template_id'] == template['id']
    assert adoption['template_version'] == template['version']
    assert adoption['template_digest'] == template['digest']
    assert adoption['title'] == template['title'] and adoption['graph'] == template['graph']
    assert case['stage'] == 'input' and case['workpackages'] == [] and case['decisions'] == []
    assert case['business_lifecycle']['rd_activation_state'] == 'not_started'
    assert case['project_workflow_status']['status'] == 'pending'
    assert local_store(tmp_path).get_project('owner', project['id']) == project


def test_create_case_requires_an_explicit_fixed_version_instead_of_latest(tmp_path):
    store = local_store(tmp_path)
    template = project_template(store)
    project = store.create_project('owner', '不能隐式采用最新版')
    with pytest.raises(RdError) as error:
        issue(store, project, 'create_case', {'title': '固定版本缺失',
            'workflow_template': {**template_ref(template), 'version': None}})
    assert error.value.status == 422
    assert store.get_project('owner', project['id']) == project


@pytest.mark.parametrize('invalid', ['wrong-digest', 'research', 'draft', 'retired', 'revoked'])
def test_new_case_rejects_unavailable_or_wrong_template_without_writing(tmp_path, invalid):
    store = local_store(tmp_path)
    template = project_template(store)
    if invalid == 'wrong-digest':
        template = {**template, 'digest': 'wrong'}
    elif invalid == 'research':
        template = store.workflow_templates.detail('owner', 'taskbook-modification-v1', '1')
    elif invalid == 'draft':
        template = save_project_template(store, template)
    elif invalid == 'retired':
        operation(store, template, 'retire', 'retire-project-flow')
    elif invalid == 'revoked':
        grant(store, 'taskbook-authoring-team', revision=1, operation='revoke', key='revoke-authoring')
    project = store.create_project('owner', '不可采用无效流程')
    with pytest.raises(RdError) as error:
        issue(store, project, 'create_case', {
            'workflow_template': template_ref(template), 'title': '不能写入'})
    assert error.value.status in ({409} if invalid == 'wrong-digest' else {404, 422})
    assert store.get_project('owner', project['id']) == project


def test_new_versions_and_retirement_do_not_replace_existing_project_graph(tmp_path):
    store = local_store(tmp_path)
    original = project_template(store)
    project = start(store, original)
    before = deepcopy(project['cases'][0]['workflow_templates']['project'])
    changed = deepcopy(original['graph'])
    changed['nodes'][0]['title'] = '新版资料登记'
    second = store.workflow_templates.save('editor', EDITOR, {
        'id': original['id'], 'expected_version': 1, 'category': 'project',
        'title': '修订任务书流程', 'graph': changed}, 'project-flow-v2')
    operation(store, second, 'publish', 'publish-v2')
    original = store.workflow_templates.detail('editor', original['id'], '1', EDITOR, management=True)
    operation(store, original, 'retire', 'retire-v1')
    after = local_store(tmp_path).get_project('owner', project['id'])['cases'][0]['workflow_templates']['project']
    assert after == before
    history = store.workflow_templates.history('owner', original['id'], EDITOR, management=True)
    assert any(usage['case_id'] == project['cases'][0]['id'] and usage['template_version'] == '1'
        for usage in history['usages'])


@pytest.mark.parametrize('mutation', ['missing-start', 'partial-team', 'downstream-node'])
def test_project_publication_cannot_bypass_gates_quality_or_terminal_boundary(tmp_path, mutation):
    store = local_store(tmp_path)
    template = project_template(store)
    graph = deepcopy(template['graph'])
    if mutation == 'missing-start':
        graph['nodes'] = [node for node in graph['nodes'] if node['id'] != 'rd_start']
        graph['edges'] = [edge for edge in graph['edges'] if 'rd_start' not in (edge['source'], edge['target'])]
        graph['edges'].append({'id': 'skip-start', 'source': 'selection_decision', 'target': 'taskbook'})
    elif mutation == 'partial-team':
        next(node for node in graph['nodes'] if node['id'] == 'taskbook')['action_resource'] = {
            'resource_id': 'consistency-team', 'resource_version': 1}
    else:
        graph['nodes'].append({'id': 'scheme', 'title': '后续方案设计', 'role': '研发工程师',
            'deliverables': ['方案'], 'position': {'x': 1500, 'y': 0}})
        graph['edges'].append({'id': 'after-generation', 'source': 'taskbook', 'target': 'scheme'})
    draft = save_project_template(store, template, graph=graph)
    checked = store.workflow_templates.validate('editor', EDITOR, {'category': 'project', 'graph': graph})
    assert checked['valid'] is False
    with pytest.raises(RdError) as error:
        operation(store, draft, 'publish', 'publish-invalid')
    assert error.value.status == 422


def test_bound_project_flow_cannot_be_replaced_or_bypassed_by_research_adoption(tmp_path):
    store = local_store(tmp_path)
    project = activated(store)
    original = deepcopy(project['cases'][0]['workflow_templates']['project'])
    for template in (project_template(store), store.workflow_templates.detail('owner', 'taskbook-modification-v1', '1')):
        with pytest.raises(RdError) as error:
            issue(store, project, 'adopt_workflow_template', {
                'template_id': template['id'], 'template_version': template['version'],
                'template_digest': template['digest']})
        assert error.value.status in {409, 422}
    with pytest.raises(RdError):
        bind(store, project, store.workflow_templates.detail('owner', 'taskbook-modification-v1', '1'))
    assert store.get_project('owner', project['id'])['cases'][0]['workflow_templates']['project'] == original


def test_existing_project_can_bind_its_retired_fixed_flow_without_reselecting_research(tmp_path):
    store = local_store(tmp_path)
    template = project_template(store)
    project = activated(store, template)
    operation(store, template, 'retire', 'retire-before-binding')
    project = bind(store, project, template)
    case = project['cases'][0]
    assert case['taskbook_binding']['workflow']['id'] == template['id']
    assert case['taskbook_binding']['workflow']['version'] == '1'
    assert case['taskbook_binding']['workflow']['digest'] == template['digest']
    assert case['taskbook_binding']['workflow']['graph'] == template['graph']
    assert 'research' not in case['workflow_templates']
    assert case['stage'] == 'planning' and case['workpackages'] == []


def test_selection_review_records_the_project_flow_actually_selected_at_creation(tmp_path):
    store = local_store(tmp_path)
    template = project_template(store)
    project = activated(store, template)
    selection = next(bundle for bundle in project['cases'][0]['review_bundles'] if bundle['kind'] == 'selection')
    assert selection['fixed_objects']['workflow_template'] == template_ref(template)
    assert selection['id'] == project['cases'][0]['business_lifecycle']['current_selection_bundle_id']
    assert local_store(tmp_path).get_project('owner', project['id']) == project


def test_project_full_engine_chain_completes_only_its_terminal_workflow_projection(tmp_path):
    store = local_store(tmp_path)
    project = submitted(store)
    case = project['cases'][0]
    candidate = case['execution_candidates'][-1]
    assert candidate['business_template']['template_id'] == 'taskbook-generation'
    assert {row['business_node_id'] for row in candidate['mapping']} == {'taskbook'}
    assert [row['action_id'] for row in candidate['compiled_plan']] == [
        'resolve_context', 'template_plan', 'content_completion', 'generate', 'verify']
    assert finish(store) == ['resolve_context', 'template_plan', 'content_completion', 'generate', 'verify']
    final = store.get_project('owner', project['id'])
    case = final['cases'][0]
    state = case['project_workflow_status']
    assert state['status'] == 'completed' and state['terminal_node_id'] == 'taskbook'
    assert state['template_id'] == 'taskbook-generation' and state['template_version'] == '1'
    assert state['execution_ref']['run_id'] == case['workpackages'][-1]['run_id']
    assert case['workflow_templates']['project']['node_states']['taskbook'] == 'completed'
    assert set(case['workflow_templates']['project']['node_states']) == set(PROJECT_NODES)
    assert case['stage'] == 'planning' and case['status'] != 'completed'
    assert case['business_lifecycle']['current_taskbook_scope_decision_id'] is None
    assert not any(row.get('kind') == 'taskbook_scope' for row in case['decisions'])
    assert local_store(tmp_path).get_project('owner', project['id']) == final


@pytest.mark.parametrize('quality,document', [(False, True), (True, False)])
def test_completed_steps_without_passing_quality_and_real_document_are_not_flow_completion(tmp_path, quality, document):
    store = local_store(tmp_path)
    project = submitted(store)
    finish(store, quality=quality, document=document)
    case = store.get_project('owner', project['id'])['cases'][0]
    assert case['workpackages'][-1]['status'] == 'completed'
    assert case['project_workflow_status']['status'] != 'completed'
    assert case['workflow_templates']['project']['node_states']['taskbook'] != 'completed'


def test_blocked_and_stale_input_keep_terminal_projection_unfinished(tmp_path):
    store = local_store(tmp_path)
    project = submitted(store)
    finish(store, blocked_action='content_completion')
    blocked = store.get_project('owner', project['id'])
    assert blocked['cases'][0]['project_workflow_status']['status'] == 'blocked'
    assert blocked['cases'][0]['workflow_templates']['project']['node_states']['taskbook'] == 'blocked'

    other = local_store(tmp_path / 'stale')
    project = submitted(other)
    finish(other)
    current = other.get_project('owner', project['id'])
    assert current['cases'][0]['project_workflow_status']['status'] == 'completed'
    changed = issue(other, current, 'save_context', {'context': {**CONTEXT, 'product_series': 'NEW-SERIES'}})
    assert changed['cases'][0]['project_workflow_status']['status'] == 'stale'
    assert changed['cases'][0]['workflow_templates']['project']['node_states']['taskbook'] != 'completed'


@pytest.mark.parametrize('mutation', ['replace-resource', 'omit-fixed-action', 'bypass-dependency', 'skip-route'])
def test_execution_draft_cannot_impersonate_or_omit_a_published_project_action(tmp_path, mutation):
    store = local_store(tmp_path)
    template = project_template(store)
    graph = deepcopy(template['graph'])
    graph['nodes'].append({'id': 'extra-check', 'title': '任务书前置一致性检查', 'role': '质量工程师',
        'deliverables': ['一致性记录'], 'position': {'x': 1100, 'y': 0},
        'action_resource': {'resource_id': 'consistency-team', 'resource_version': 1},
        'workpackage_definition_id': 'taskbook'})
    graph['edges'] = [edge for edge in graph['edges'] if (edge['source'], edge['target']) != ('rd_start', 'taskbook')]
    graph['edges'].extend([{'id': 'to-extra', 'source': 'rd_start', 'target': 'extra-check'},
        {'id': 'from-extra', 'source': 'extra-check', 'target': 'taskbook'}])
    template = operation(store, save_project_template(store, template, graph=graph), 'publish', 'publish-extra')
    project = bind(store, activated(store, template), template)
    project = issue(store, project, 'pull_workpackage', {'definition_id': 'taskbook'})
    wid = project['cases'][0]['workpackages'][-1]['id']
    project = issue(store, project, 'create_flow_draft', {'workpackage_id': wid})
    graph = deepcopy(project['cases'][0]['flow_drafts'][-1]['graph'])
    extra = next(node for node in graph['nodes'] if node['business_node_id'] == 'extra-check')
    if mutation == 'replace-resource':
        # Reusing the published business ID must not claim its consistency check
        # was performed by an unrelated context parser.
        extra['resource_id'] = 'context-team'
    elif mutation == 'omit-fixed-action':
        graph['nodes'].remove(extra)
        graph['edges'] = [edge for edge in graph['edges'] if extra['id'] not in (edge['source'], edge['target'])]
    elif mutation == 'skip-route':
        extra['route'] = 'new'
    else:
        graph['edges'] = []
    project = issue(store, project, 'create_flow_draft', {'workpackage_id': wid, 'graph': graph})
    draft = project['cases'][0]['flow_drafts'][-1]
    before_candidates = deepcopy(project['cases'][0]['execution_candidates'])
    with pytest.raises(RdError) as error:
        issue(store, project, 'prepare_execution_bundle', {'draft_id': draft['id']})
    assert error.value.status == 422
    current = store.get_project('owner', project['id'])['cases'][0]
    assert current['execution_candidates'] == before_candidates
    assert current['workpackages'][-1]['run_id'] is None


def test_generation_terminal_project_cannot_prepare_an_undeclared_downstream_scope_review(tmp_path):
    store = local_store(tmp_path)
    project = submitted(store)
    finish(store)
    project = store.get_project('owner', project['id'])
    assert project['cases'][0]['project_workflow_status']['status'] == 'completed'
    wid = project['cases'][0]['workpackages'][-1]['id']
    with pytest.raises(RdError) as error:
        issue(store, project, 'prepare_taskbook_scope_review', {'workpackage_id': wid})
    assert error.value.status == 422
    assert store.get_project('owner', project['id']) == project
