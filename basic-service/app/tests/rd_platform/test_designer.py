"""Draft persistence, immutable adoption and actual producer bindings."""
import copy
import pytest

from test_store import new_store, issue, taskbook


def draft_project(tmp_path):
    store = new_store(tmp_path)
    project = taskbook(store)
    wid = project['cases'][0]['workpackages'][0]['id']
    package = project['cases'][0]['workpackages'][0]
    graph = {'nodes': [{k: v for k, v in n.items() if k in {'id', 'action_id', 'action_version', 'required'}} for n in package['nodes']],
        'edges': [{'id': 'edge-' + dep + '-' + n['id'], 'source': dep, 'target': n['id']} for n in package['nodes'] for dep in n['depends_on']]}
    project = issue(store, project, 'create_flow_draft', {'workpackage_id': wid, 'graph': graph})
    return store, project, wid


def patch(store, project, operations, **extra):
    draft = project['cases'][0]['flow_drafts'][-1]
    return issue(store, project, 'apply_flow_patch', {'draft_id': draft['id'], 'origin': 'manual',
        'base_digest': draft['digest'], 'expected_draft_revision': draft['revision'], 'operations': operations, **extra})


def test_draft_patch_cas_restart_layout_and_copy_are_not_execution(tmp_path):
    store, project, wid = draft_project(tmp_path)
    before = project['cases'][0]['flow_drafts'][0]
    project = patch(store, project, [{'op': 'move_node', 'node_id': 'resolve_context', 'position': {'x': 12, 'y': 24}},
        {'op': 'copy_node', 'node_id': 'verify'}])
    after = project['cases'][0]['flow_drafts'][0]
    assert before['semantic_digest'] != after['semantic_digest']
    assert len(after['graph']['nodes']) == 6
    copied = after['graph']['nodes'][-1]
    assert copied['id'] != 'verify' and 'result' not in copied and 'status' not in copied
    assert project['cases'][0]['workpackages'][0]['status'] == 'draft'
    assert new_store(tmp_path).get_project('owner', project['id']) == project
    with pytest.raises(Exception) as error:
        issue(store, project, 'apply_flow_patch', {'draft_id': after['id'], 'origin': 'manual',
            'base_digest': before['digest'], 'expected_draft_revision': before['revision'], 'operations': []})
    assert error.value.status == 409


def test_validation_cycle_and_required_gate_and_assistant_conflict(tmp_path):
    store, project, _ = draft_project(tmp_path)
    project = patch(store, project, [{'op': 'confirm_field', 'node_id': 'verify', 'field': 'title'}])
    unchanged = copy.deepcopy(project)
    project = patch(store, project, [{'op': 'set_node', 'node_id': 'verify', 'properties': {'title': 'AI改名'}}], origin='assistant')
    draft = project['cases'][0]['flow_drafts'][0]
    assert draft['conflicts'] and draft['graph'] == unchanged['cases'][0]['flow_drafts'][0]['graph']
    project = patch(store, project, [{'op': 'add_edge', 'edge': {'source': 'verify', 'target': 'resolve_context'}}])
    project = issue(store, project, 'validate_flow_draft', {'draft_id': draft['id']})
    assert not project['cases'][0]['flow_drafts'][0]['validation']['valid']


def test_candidate_adoption_freezes_graph_and_submission_and_simulation_isolated(tmp_path):
    store, project, wid = draft_project(tmp_path)
    draft = project['cases'][0]['flow_drafts'][0]
    project = issue(store, project, 'prepare_execution_bundle', {'draft_id': draft['id']})
    candidate = copy.deepcopy(project['cases'][0]['execution_candidates'][0])
    for scenario in ('normal', 'missing_input', 'rejected', 'cancelled'):
        project = issue(store, project, 'simulate_execution_bundle', {'candidate_id': candidate['id'], 'scenario': scenario})
    assert project['cases'][0]['workpackages'][0]['run_id'] is None
    project = issue(store, project, 'adopt_execution_bundle', {'candidate_id': candidate['id'], 'candidate_digest': candidate['digest']})
    project = issue(store, project, 'submit_workpackage', {'workpackage_id': wid})
    package = project['cases'][0]['workpackages'][0]
    assert package['snapshot']['execution_candidate']['digest'] == candidate['digest']
    assert package['snapshot']['graph_digest'] == candidate['semantic_digest']
    assert [{k: v for k, v in n.items() if k != 'status'} for n in package['nodes']] == [{k: v for k, v in n.items() if k != 'status'} for n in package['snapshot']['plan']]
    assert project['cases'][0]['execution_candidates'][0] == candidate


def test_checkpoint_append_only_dedup_and_cancel_fence(tmp_path):
    store, project, wid = draft_project(tmp_path)
    d = project['cases'][0]['flow_drafts'][0]
    project = issue(store, project, 'prepare_execution_bundle', {'draft_id': d['id']})
    c = project['cases'][0]['execution_candidates'][0]
    project = issue(store, project, 'adopt_execution_bundle', {'candidate_id': c['id'], 'candidate_digest': c['digest']})
    project = issue(store, project, 'submit_workpackage', {'workpackage_id': wid})
    claim = store.claim_node()
    payload = {'completion_checkpoint': {'session_id': 's1', 'rounds': [{'round': 1}], 'stop_reason': None}}
    assert store.progress(claim, payload) and store.progress(claim, payload)
    project = store.get_project('owner', project['id'])
    assert len(project['cases'][0]['workpackages'][0]['nodes'][0]['completion_checkpoints']) == 1
    project = issue(store, project, 'cancel_workpackage', {'workpackage_id': wid})
    node = project['cases'][0]['workpackages'][0]['nodes'][0]
    assert node['completion_session']['stop_reason'] == 'cancelled'
    assert node['completion_session']['rounds'] == [{'round': 1}]
    assert not store.progress(claim, payload)


def prepared(store, project, wid):
    d = project['cases'][0]['flow_drafts'][-1]
    project = issue(store, project, 'prepare_execution_bundle', {'draft_id': d['id']})
    c = project['cases'][0]['execution_candidates'][-1]
    project = issue(store, project, 'adopt_execution_bundle', {'candidate_id': c['id'], 'candidate_digest': c['digest']})
    return issue(store, project, 'submit_workpackage', {'workpackage_id': wid})


def test_default_team_compiles_into_real_worker_dag_and_keeps_ids(tmp_path):
    from service.rd_platform.runtime import Worker
    store = new_store(tmp_path)
    project = taskbook(store)
    wid = project['cases'][0]['workpackages'][0]['id']
    project = issue(store, project, 'create_flow_draft', {'workpackage_id': wid})
    assert len(project['cases'][0]['flow_drafts'][0]['graph']['nodes']) == 1
    project = prepared(store, project, wid)
    calls = []
    def executor(action, snapshot, previous, directory, progress, cancelled):
        calls.append(action)
        if action == 'generate':
            assert previous['template_plan']['marker'] == 'template_plan'
            assert previous['content_completion']['marker'] == 'content_completion'
        return {'status': 'completed', 'result': {'marker': action}}
    worker = Worker(store, executor)
    while worker.tick():
        pass
    assert calls == ['resolve_context', 'template_plan', 'content_completion', 'generate', 'verify']
    p = store.get_project('owner', project['id'])['cases'][0]['workpackages'][0]
    assert p['status'] == 'completed'
    assert all(m['run_id'] == p['run_id'] and '__' in m['step_instance_id'] for m in p['execution_mapping'])


def test_same_action_instances_bind_exact_producer_without_last_value(tmp_path):
    store, project, wid = draft_project(tmp_path)
    project = patch(store, project, [
        {'op': 'add_node', 'node': {'id': 'check1', 'action_id': 'consistency'}},
        {'op': 'add_node', 'node': {'id': 'check2', 'action_id': 'consistency'}},
        {'op': 'add_edge', 'edge': {'source': 'generate', 'target': 'check1'}},
        {'op': 'add_edge', 'edge': {'source': 'check1', 'target': 'check2'}},
        {'op': 'add_edge', 'edge': {'source': 'check2', 'target': 'verify'}},
        {'op': 'set_node', 'node_id': 'verify', 'properties': {'input_bindings': {'consistency': 'check1'}}}])
    project = prepared(store, project, wid)
    while claim := store.claim_node():
        if claim['action_id'] == 'verify':
            assert claim['previous_results']['consistency']['producer'] == 'check1'
            assert claim['previous_results']['__by_node__']['check2']['producer'] == 'check2'
        assert store.complete_node(claim, {'status': 'completed', 'result': {'producer': claim['node_id']}})


def test_dependency_only_member_hidden_but_team_runs_and_revoke_fences(tmp_path):
    from test_workspace import grant
    store = new_store(tmp_path)
    project = taskbook(store)
    wid = project['cases'][0]['workpackages'][0]['id']
    grant(store, 'generate', revision=1, dependency_only=True, key='dependency')
    assert store.workspace.catalog_list(q='generate')['total'] == 0
    with pytest.raises(Exception) as error:
        store.workspace.catalog_detail('generate', 1)
    assert error.value.status == 404
    assert store.workspace.catalog_list(q='taskbook-authoring-team')['total'] == 1
    project = issue(store, project, 'create_flow_draft', {'workpackage_id': wid})
    project = prepared(store, project, wid)
    claim = store.claim_node()
    assert claim
    assert store.progress(claim, {'completion_checkpoint': {'session_id': 'x', 'rounds': [1]}})
    grant(store, 'generate', revision=2, operation='revoke', key='revoke-dependency')
    assert not store.renew_claim(claim)
    node = store.get_project('owner', project['id'])['cases'][0]['workpackages'][0]['nodes'][0]
    assert node['completion_session']['stop_reason'] == 'permission_revoked'
    assert not store.complete_node(claim, {'status': 'completed', 'result': {}})


def test_budget_checkpoint_stop_preserves_rounds_and_rejects_rewrite(tmp_path):
    store, project, wid = draft_project(tmp_path)
    project = prepared(store, project, wid)
    claim = store.claim_node()
    assert store.progress(claim, {'completion_checkpoint': {'session_id': 's', 'rounds': [{'round': 1, 'accepted': ['a']}]}})
    with pytest.raises(Exception) as error:
        store.progress(claim, {'completion_checkpoint': {'session_id': 's', 'rounds': [{'round': 1, 'accepted': ['different']}]}})
    assert error.value.status == 409
    with store._transaction() as db:
        db.execute('UPDATE runs SET created_at=0 WHERE id=?', (claim['run_id'],))
    assert not store.progress(claim, {'completion_checkpoint': {'session_id': 's', 'rounds': []}})
    node = store.get_project('owner', project['id'])['cases'][0]['workpackages'][0]['nodes'][0]
    assert node['completion_session']['stop_reason'] == 'budget_exhausted'
    assert node['completion_session']['rounds'][0]['accepted'] == ['a']


def test_candidate_cannot_ignore_new_draft_or_revoked_team(tmp_path):
    from test_workspace import grant
    store, project, wid = draft_project(tmp_path)
    d = project['cases'][0]['flow_drafts'][0]
    project = issue(store, project, 'prepare_execution_bundle', {'draft_id': d['id']})
    c = copy.deepcopy(project['cases'][0]['execution_candidates'][0])
    project = patch(store, project, [{'op': 'move_node', 'node_id': 'verify', 'position': {'x': 1, 'y': 1}}])
    with pytest.raises(Exception) as error:
        issue(store, project, 'adopt_execution_bundle', {'candidate_id': c['id'], 'candidate_digest': c['digest']})
    assert error.value.status == 409
    assert project['cases'][0]['execution_candidates'][0] == c
    project = issue(store, project, 'restore_flow_revision', {'draft_id': d['id'], 'revision': 1})
    assert len(project['cases'][0]['flow_drafts']) == 2
    assert project['cases'][0]['flow_drafts'][-1]['restored_from']['revision'] == 1


@pytest.mark.parametrize('mutation', ['missing_gate', 'dangling', 'wrong_input', 'ungranted_version'])
def test_structured_validation_blocks_missing_gates_io_and_fixed_resources(tmp_path, mutation):
    store, project, _ = draft_project(tmp_path)
    operations = {
        'missing_gate': [{'op': 'remove_node', 'node_id': 'content_completion'}],
        'dangling': [{'op': 'add_edge', 'edge': {'source': 'absent', 'target': 'verify'}}],
        'wrong_input': [{'op': 'set_node', 'node_id': 'verify', 'properties': {'input_bindings': {'generate': 'template_plan'}}}],
        'ungranted_version': [{'op': 'set_node', 'node_id': 'verify', 'properties': {'resource_version': 2}}],
    }[mutation]
    project = patch(store, project, operations)
    d = project['cases'][0]['flow_drafts'][0]
    project = issue(store, project, 'validate_flow_draft', {'draft_id': d['id']})
    validation = project['cases'][0]['flow_drafts'][0]['validation']
    assert not validation['valid'] and validation['errors'][0]['message']
    with pytest.raises(Exception) as error:
        issue(store, project, 'prepare_execution_bundle', {'draft_id': d['id']})
    assert error.value.status == 422


def test_layout_only_diff_and_inflight_revision_do_not_change_snapshot(tmp_path):
    store, project, wid = draft_project(tmp_path)
    draft = project['cases'][0]['flow_drafts'][0]
    semantic = draft['semantic_digest']
    project = issue(store, project, 'prepare_execution_bundle', {'draft_id': draft['id']})
    project = patch(store, project, [{'op': 'move_node', 'node_id': 'verify', 'position': {'x': 50, 'y': 80}}])
    project = issue(store, project, 'prepare_execution_bundle', {'draft_id': draft['id']})
    candidate = project['cases'][0]['execution_candidates'][-1]
    assert candidate['semantic_digest'] == semantic and candidate['diff']['layout_only']
    project = issue(store, project, 'adopt_execution_bundle', {'candidate_id': candidate['id'], 'candidate_digest': candidate['digest']})
    project = issue(store, project, 'submit_workpackage', {'workpackage_id': wid})
    fixed = copy.deepcopy(project['cases'][0]['workpackages'][0]['snapshot'])
    project = patch(store, project, [{'op': 'set_node', 'node_id': 'verify', 'properties': {'title': '下次校验'}}])
    assert project['cases'][0]['workpackages'][0]['snapshot'] == fixed
    assert fixed['execution_graph'] == candidate['graph']
    project = issue(store, project, 'restore_flow_revision', {'draft_id': draft['id'], 'revision': 1})
    restored = project['cases'][0]['workpackages'][-1]
    assert restored['id'] != wid and restored['revision_of'] == wid and restored['status'] == 'draft'
    assert restored['run_id'] is None and restored['artifacts'] == []
    assert project['cases'][0]['flow_drafts'][-1]['workpackage_id'] == restored['id']
    assert project['cases'][0]['workpackages'][0]['snapshot'] == fixed


def test_new_policy_cannot_submit_without_adoption_or_downgrade(tmp_path):
    store = new_store(tmp_path)
    project = store.create_project('owner', '新政策')
    project = issue(store, project, 'create_case', {'scenario_id': 'taskbook', 'title': '资料核对'})
    project = issue(store, project, 'pull_workpackage', {'definition_id': 'input_check'})
    wid = project['cases'][0]['workpackages'][0]['id']
    assert project['cases'][0]['workpackages'][0]['execution_schema_version'] == 3
    for extra in ({}, {'schema_version': 1}, {'execution_schema_version': 1}):
        with pytest.raises(Exception) as error:
            issue(store, project, 'submit_workpackage', {'workpackage_id': wid, **extra})
        assert error.value.status == 422


def test_duplicate_team_instances_use_their_own_skill_producers(tmp_path):
    store = new_store(tmp_path)
    project = taskbook(store)
    wid = project['cases'][0]['workpackages'][0]['id']
    project = issue(store, project, 'create_flow_draft', {'workpackage_id': wid})
    original = project['cases'][0]['flow_drafts'][0]['graph']['nodes'][0]['id']
    project = patch(store, project, [{'op': 'copy_node', 'node_id': original}])
    copied = project['cases'][0]['flow_drafts'][0]['graph']['nodes'][1]['id']
    project = patch(store, project, [{'op': 'add_edge', 'edge': {'source': original, 'target': copied}}])
    project = prepared(store, project, wid)
    assert len(project['cases'][0]['workpackages'][0]['nodes']) == 10
    while claim := store.claim_node():
        if claim['action_id'] == 'generate':
            assert claim['previous_results']['template_plan']['producer'] == claim['node_id'].replace('__generate', '__template_plan')
            assert claim['previous_results']['content_completion']['producer'] == claim['node_id'].replace('__generate', '__content_completion')
        assert store.complete_node(claim, {'status': 'completed', 'result': {'producer': claim['node_id']}})


def test_reclaimed_completion_restores_checkpoint_and_fences_old_attempt(tmp_path):
    store, project, wid = draft_project(tmp_path)
    project = prepared(store, project, wid)
    for action in ('resolve_context', 'template_plan'):
        claim = store.claim_node()
        assert claim['action_id'] == action
        assert store.complete_node(claim, {'status': 'completed', 'result': {}})
    old = store.claim_node()
    assert old['action_id'] == 'content_completion'
    assert store.progress(old, {'completion_checkpoint': {'session_id': 'resume', 'rounds': [{'round': 1}],
        'rejected_fingerprints': ['rejected-evidence']}})
    with store._transaction() as db:
        db.execute('UPDATE claims SET lease_until=0 WHERE run_id=? AND node_id=?', (old['run_id'], old['node_id']))
    newer = store.claim_node()
    assert newer['attempt'] == 2 and newer['token'] != old['token']
    assert newer['snapshot']['completion_resume']['rejected_fingerprints'] == ['rejected-evidence']
    assert newer['snapshot']['completion_resume']['rounds'] == [{'round': 1}]
    assert not store.progress(old, {'completion_checkpoint': {'session_id': 'resume', 'rounds': []}})
    assert not store.complete_node(old, {'status': 'completed', 'result': {}})


@pytest.mark.parametrize('mode', ['remote_real', 'contract_example'])
def test_unbound_remote_or_example_team_cannot_gain_local_executor_by_drawing(tmp_path, mode):
    from test_workspace import PUBLISHER
    store = new_store(tmp_path)
    config = copy.deepcopy(store.workspace.catalog_detail('consistency-team', 1)['configuration'])
    config['execution_mode'] = mode
    with pytest.raises(Exception) as error:
        store.workspace.save_resource('publisher', PUBLISHER, {'id': 'unbound-team', 'kind': 'team',
            'name': '未连接团队', 'expected_version': 0, 'configuration': config}, 'unbound-' + mode)
    assert error.value.status == 422


def test_schema3_quality_claim_passes_fixed_receipts_into_real_verification(tmp_path):
    import json
    from pathlib import Path
    from test_executors import verification_fixture
    from service.rd_platform import executors
    from src.service.rd_platform.engine_bridge import artifact
    store = new_store(tmp_path)
    project = taskbook(store)
    upstream_id = project['cases'][0]['workpackages'][0]['id']
    project = issue(store, project, 'submit_workpackage', {'workpackage_id': upstream_id})
    fixture_dir = store.asset_root / 'historical-qa-fixture'
    fixture_dir.mkdir()
    _, results = verification_fixture(fixture_dir)
    first = store.claim_node()
    fixed = first['snapshot']
    generated = results['generate']
    saved = json.loads(Path(generated['receipt']['path']).read_text(encoding='utf-8'))
    saved.update(project_id=project['id'], case_id=project['cases'][0]['id'], workpackage_id=upstream_id,
        source_hashes={s['id']: s['sha256'] for s in fixed['sources']})
    Path(generated['receipt']['path']).write_text(json.dumps(saved), encoding='utf-8')
    generated['receipt'] = artifact(generated['receipt']['path'], 'engine_receipt')
    generated['workpackage_id'] = upstream_id
    claim = first
    while claim:
        assert store.complete_node(claim, {'status': 'completed', 'result': results.get(claim['action_id'], {})})
        claim = store.claim_node()
    # Explicit historical snapshot from before taskbook business bindings existed.
    # The successor is schema3 and must consume those immutable, hashed receipts.
    with store._transaction() as db:
        raw = store._load(db, project['id'])
        old = raw['cases'][0]['workpackages'][0]
        old['snapshot']['taskbook_binding'] = None
        db.execute('UPDATE projects SET payload=? WHERE id=?', (json.dumps(raw), project['id']))
        db.execute('UPDATE runs SET snapshot=? WHERE id=?', (json.dumps(old['snapshot']), old['run_id']))
    project = store.get_project('owner', project['id'])
    project = issue(store, project, 'pull_workpackage', {'definition_id': 'quality_check', 'request_ref': upstream_id})
    wid = project['cases'][0]['workpackages'][-1]['id']
    project = issue(store, project, 'create_flow_draft', {'workpackage_id': wid})
    project = prepared(store, project, wid)
    claim = store.claim_node()
    assert claim['previous_results']['generate']['workpackage_id'] == upstream_id
    assert claim['previous_results']['template_plan']['assets']
    assert claim['previous_results']['content_completion']['ready'] is True
    assert all(value.startswith('upstream:') for value in project['cases'][0]['workpackages'][-1]['nodes'][0]['input_bindings'].values())
    outcome = executors.execute('verify', claim['snapshot'], claim['previous_results'], claim['work_dir'], lambda _: True, lambda: False)
    assert outcome['status'] == 'completed' and outcome['result']['delivery_approved'] is True
    assert store.complete_node(claim, outcome)


@pytest.mark.parametrize('field,value', [('route', 'direct'), ('action_version', '2'), ('inputs', ['generate']), ('outputs', ['verify'])])
def test_team_internal_semantics_are_checked_instead_of_silently_ignored(tmp_path, field, value):
    from test_workspace import PUBLISHER
    store = new_store(tmp_path)
    config = copy.deepcopy(store.workspace.catalog_detail('consistency-team', 1)['configuration'])
    config['execution_graph']['nodes'][0][field] = value
    with pytest.raises(Exception) as error:
        store.workspace.save_resource('publisher', PUBLISHER, {'id': 'invalid-team', 'kind': 'team', 'name': '无效内部图',
            'expected_version': 0, 'configuration': config}, 'invalid-internal')
    assert error.value.status == 422
