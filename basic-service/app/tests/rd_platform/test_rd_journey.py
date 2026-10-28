"""Real aggregate commands preserve decisions, authority and baseline evidence."""
import json
import sqlite3

import pytest

from tests.support.rd_project import OWNER, ENGINEER, REVIEWER, command, project, raises, store


def baseline(store):
    d = project(store)
    for actor, role in ((ENGINEER, 'engineer'), (REVIEWER, 'reviewer')):
        d = command(store, d, 'add_member', {**actor, 'role': role})
    d = command(store, d, 'save_requirement', {'title': '接口', 'content': '按协议核对', 'source': '协议1', 'acceptance': '试验', 'clarification': 'resolved'})
    return command(store, d, 'confirm_baseline')


def selection(route='direct', **changes):
    return {'route': route, 'selected_product': '连接器A', 'rationale': '按接口核对', 'evidence_ref': '选型记录1', 'suitability': 'confirmed', 'supply_status': 'confirmed', **changes}


def delivery(d, **changes):
    return {'selection_id': d['journey']['selection']['id'], 'outcome': 'accepted', 'recipient': '客户工程部', 'reference': '签收单1', 'note': '', **changes}


def adoption(route='new'):
    return {'route': route, 'approval_ref': '批准1', 'scope': '接口研发', 'process_template_ref': {'id': 'BP05', 'version': '1'}, 'provenance': 'manual'}


def test_direct_selection_delivery_persist_with_real_owner_and_history(store):
    d = baseline(store)
    d = command(store, d, 'record_selection', selection())
    decision = d['journey']['selection']
    assert decision['created_by'] == 'owner'
    assert decision['baseline_id'] == d['project']['current_baseline_id']
    assert d['journey']['stage'] == 'delivery_ready'
    d = command(store, d, 'record_delivery', delivery(d, outcome='blocked', reference='', note='等待客户收货'))
    assert d['journey']['stage'] == 'delivery_blocked'
    assert d['journey']['blockers']
    d = command(store, d, 'record_delivery', delivery(d))
    from src.service.rd_platform.store import RdStore
    saved = RdStore(store.db_path, store.artifact_root).detail(d['project']['id'], 'owner')
    assert saved['journey']['stage'] == 'delivered'
    assert saved['journey']['delivery']['created_by'] == 'owner'
    assert len(saved['delivery_records']) == 2
    assert saved['journey']['selection'] == decision


def test_selection_requires_owner_confirmed_baseline_and_valid_fields(store):
    d = project(store)
    raises(409, lambda: command(store, d, 'record_selection', selection()))
    d = baseline(store)
    raises(403, lambda: command(store, d, 'record_selection', selection(), ENGINEER))
    for invalid in ({'route': 'modified'}, {'suitability': 'yes'}, {'supply_status': 'unknown'}, {'rationale': ''}):
        raises(422, lambda: command(store, d, 'record_selection', selection(**invalid)))
    d = command(store, d, 'record_selection', selection(evidence_ref='', suitability='pending'))
    assert d['journey']['stage'] == 'selection_pending'
    assert d['journey']['selection']['evidence_ref'] == ''
    raises(409, lambda: command(store, d, 'record_delivery', delivery(d)))


def test_delivery_rejects_unconfirmed_or_noncurrent_or_development_selection(store):
    d = baseline(store)
    d = command(store, d, 'record_selection', selection(supply_status='pending'))
    raises(409, lambda: command(store, d, 'record_delivery', delivery(d)))
    d = command(store, d, 'record_delivery', delivery(d, outcome='blocked', reference='', note='供货待确认'))
    assert d['journey']['delivery']['outcome'] == 'blocked'
    old = d['journey']['selection']['id']
    d = command(store, d, 'record_selection', selection())
    raises(409, lambda: command(store, d, 'record_delivery', delivery(d, selection_id=old)))
    raises(403, lambda: command(store, d, 'record_delivery', delivery(d), ENGINEER))
    raises(422, lambda: command(store, d, 'record_delivery', delivery(d, reference='')))
    raises(422, lambda: command(store, d, 'record_delivery', delivery(d, recipient='')))
    d = command(store, d, 'record_selection', selection('new'))
    assert d['journey']['delivery'] is None
    raises(409, lambda: command(store, d, 'record_delivery', delivery(d)))


def test_changed_draft_and_baseline_keep_decision_but_require_revalidation(store):
    d = command(store, baseline(store), 'record_selection', selection())
    d = command(store, d, 'record_delivery', delivery(d))
    decision, receipt = d['journey']['selection'], d['journey']['delivery']
    requirement = d['requirements'][0]
    payload = {k: v for k, v in requirement.items() if k not in {'revision', 'history'}}
    d = command(store, d, 'save_requirement', {**payload, 'content': '接口调整'})
    assert d['journey']['stage'] == 'needs_revalidation'
    raises(409, lambda: command(store, d, 'record_selection', selection()))
    raises(409, lambda: command(store, d, 'record_delivery', delivery(d)))
    d = command(store, d, 'confirm_baseline')
    assert d['journey']['stage'] == 'needs_revalidation'
    assert d['journey']['selection'] == decision
    assert d['journey']['delivery'] == receipt
    d = command(store, d, 'record_selection', selection('modification'))
    assert d['journey']['delivery'] is None
    assert len(d['selection_decisions']) == 2
    assert len(d['delivery_records']) == 1


def test_selection_and_delivery_replay_and_cas(store):
    d = baseline(store)
    selected = command(store, d, 'record_selection', selection(), key='selection-key')
    assert command(store, d, 'record_selection', selection(), key='selection-key') == selected
    raises(409, lambda: command(store, d, 'record_selection', selection(), key='stale-key'))
    raises(409, lambda: command(store, d, 'record_selection', selection('new'), key='selection-key'))
    delivered = command(store, selected, 'record_delivery', delivery(selected), key='delivery-key')
    assert command(store, selected, 'record_delivery', delivery(selected), key='delivery-key') == delivered
    assert len(delivered['selection_decisions']) == len(delivered['delivery_records']) == 1


@pytest.mark.parametrize(('route', 'native_route'), [('modification', 'modified'), ('new', 'new')])
def test_development_selection_requires_matching_native_admission(store, route, native_route):
    d = command(store, baseline(store), 'record_selection', selection(route))
    assert d['journey']['stage'] == 'development_pending'
    d = command(store, d, 'adopt_development', adoption(native_route))
    d = command(store, d, 'create_taskbook', {'adoption_id': d['development_adoptions'][-1]['id'], 'title': '任务书', 'assignee_id': 'engineer', 'reviewer_id': 'reviewer'})
    assert d['tasks'][-1]['kind'] == 'taskbook'
    assert d['journey']['stage'] == 'development'
    d = command(store, d, 'record_selection', selection('direct'))
    raises(409, lambda: command(store, d, 'create_taskbook', {'adoption_id': d['development_adoptions'][-1]['id'], 'title': '绕过路线', 'assignee_id': 'engineer', 'reviewer_id': 'reviewer'}))
    raises(409, lambda: command(store, d, 'adopt_development', adoption(native_route)))


def test_legacy_admission_is_readable_without_fabricated_selection(store):
    d = command(store, baseline(store), 'adopt_development', adoption('modified'))
    assert d['journey']['route'] == 'modification'
    assert d['journey']['selection'] is None
    assert d['journey']['delivery'] is None
    assert d['journey']['blockers']


def test_only_project_role_is_exposed_and_legacy_view_metadata_is_preserved(store):
    d = project(store)
    member = {'user_id': 'lead', 'display_name': '领导', 'role': 'viewer', 'workbench_role': 'leadership'}
    raises(422, lambda: command(store, d, 'add_member', member))
    with store._transaction() as conn:
        raw = store._load(conn, d['project']['id'], 'owner')
        raw['members'].append(member)
        store._save(conn, raw, 'legacy_fixture', 'owner', {})
    d = store.detail(d['project']['id'], 'lead')
    assert d['project']['role'] == 'viewer'
    assert 'workbench_role' not in d['project']
    assert all('workbench_role' not in m for m in d['members'])
    assert 'workbench_role' not in store.list_projects('lead')['items'][0]
    raises(403, lambda: command(store, d, 'confirm_baseline', actor={'user_id': 'lead', 'display_name': '领导'}))
    d = command(store, d, 'add_member', {k: v for k, v in member.items() if k != 'workbench_role'})
    with store._connection() as conn:
        assert store._load(conn, d['project']['id'], 'owner')['members'][-1]['workbench_role'] == 'leadership'


RETIRED_MEMBERS = (
    {'user_id': 'demo-technical', 'display_name': '刘工 · 演示技术负责人', 'role': 'engineer', 'workbench_role': 'technical_lead'},
    {'user_id': 'demo-leader', 'display_name': '张总 · 演示领导', 'role': 'viewer', 'workbench_role': 'leadership'},
    {'user_id': 'demo-knowledge', 'display_name': '孙工 · 演示知识治理', 'role': 'viewer', 'workbench_role': 'knowledge'},
    {'user_id': 'demo-operations', 'display_name': '周工 · 演示IT运营', 'role': 'viewer', 'workbench_role': 'operations'},
)


def legacy_demo(store, migrated=True):
    owner = {'user_id': 'demo-owner', 'display_name': '原负责人'}
    d = store.create_project(owner, {'code': 'RD-DEMO-001', 'name': '用户修改过的项目', 'customer': '客户', 'product': '产品'}, 'old-demo')
    with store._transaction() as conn:
        conn.execute('CREATE TABLE demo_bootstrap (name TEXT PRIMARY KEY, completed_at TEXT NOT NULL)')
        conn.execute("INSERT INTO demo_bootstrap VALUES ('workspace-v1', '2026-01-01')")
        raw = store._load(conn, d['project']['id'], 'demo-owner')
        raw['members'].extend(dict(m) for m in RETIRED_MEMBERS)
        store._save(conn, raw, 'migrate_demo_workbench_members' if migrated else 'manual_fixture', 'demo-owner', {'added_user_ids': [m['user_id'] for m in RETIRED_MEMBERS], 'source': 'mock'})
    return owner, store.detail(d['project']['id'], 'demo-owner')


def test_existing_demo_removes_only_proven_unused_members_and_runs_once(store, monkeypatch):
    from src.service.rd_platform.demo import DEMO_USERS, ensure_demo_workspace
    monkeypatch.setenv('JTB_DEMO_MODE', 'true')
    owner, d = legacy_demo(store)
    before_events = d['events']
    ensure_demo_workspace(store)
    migrated = store.detail(d['project']['id'], 'demo-owner')
    assert len(DEMO_USERS) == 4
    assert migrated['project']['name'] == '用户修改过的项目'
    assert [m['user_id'] for m in migrated['members']] == ['demo-owner']
    assert migrated['events'][:-1] == before_events
    assert migrated['project']['version'] == d['project']['version'] + 1
    ensure_demo_workspace(store)
    assert store.detail(d['project']['id'], 'demo-owner') == migrated


@pytest.mark.parametrize('use', ['manual', 'renamed', 'edited_back', 'task', 'history', 'source', 'handoff', 'draft', 'generation', 'run'])
def test_demo_cleanup_preserves_manual_edits_and_business_use(store, monkeypatch, use):
    from src.service.rd_platform.demo import ensure_demo_workspace
    monkeypatch.setenv('JTB_DEMO_MODE', 'true')
    owner, d = legacy_demo(store, migrated=use != 'manual')
    uid = 'demo-technical'
    if use == 'edited_back':
        d = store.execute(d['project']['id'], owner, 'add_member', {k: v for k, v in RETIRED_MEMBERS[0].items() if k != 'workbench_role'}, d['project']['version'], 'manual-edit')
    with store._transaction() as conn:
        raw = store._load(conn, d['project']['id'], 'demo-owner')
        if use == 'renamed':
            raw['members'][1]['display_name'] = '用户改名'
        elif use == 'task':
            raw['tasks'].append({'id': 't', 'assignee_id': uid, 'reviewer_id': 'r', 'status': 'todo'})
        elif use == 'history':
            store._event(raw, 'reassign_task', 'demo-owner', {'assignee_id': uid})
        elif use == 'source':
            raw['project_sources'].append({'created_by': uid})
        elif use == 'handoff':
            raw['handoffs'].append({'item': {'acceptance_owner_id': uid}})
        elif use == 'draft':
            conn.execute('INSERT INTO taskbook_drafts VALUES (?,?,?)', (json.dumps([d['project']['id'], 't', uid, 'engineer', None]), 1, '{}'))
        elif use == 'generation':
            conn.execute('INSERT INTO generations VALUES (?,?,?)', ('j', d['project']['id'], json.dumps({'actor_id': uid})))
        elif use == 'run':
            conn.execute('INSERT INTO taskbook_runs VALUES (?,?,?,?)', ('run', d['project']['id'], 't', json.dumps({'actor_id': uid})))
        conn.execute('UPDATE projects SET document=? WHERE id=?', (json.dumps(raw), d['project']['id']))
    ensure_demo_workspace(store)
    with store._connection() as conn:
        saved = store._load(conn, d['project']['id'], 'demo-owner')
    assert any(m['user_id'] == uid for m in saved['members'])
    for name in ('tasks', 'project_sources', 'handoffs'):
        assert saved[name] == raw[name]
    if use == 'manual':
        assert saved['members'] == raw['members']
    else:
        assert [m['user_id'] for m in saved['members']] == ['demo-owner', uid]


def test_demo_uses_four_original_identities_and_retired_cookie_is_readonly(store, monkeypatch):
    from src.service.rd_platform.demo import DEMO_USERS, demo_user, ensure_demo_workspace
    monkeypatch.setenv('JTB_DEMO_MODE', 'true')
    ensure_demo_workspace(store)
    assert [u['role'] for u in DEMO_USERS] == ['owner', 'engineer', 'reviewer', 'viewer']
    for member in RETIRED_MEMBERS:
        assert demo_user(member['user_id'])['userid'] == 'demo-viewer'
        from fastapi import HTTPException
        from starlette.requests import Request
        from src.controller.demo_controller import IdentityBody, demo_identity
        with pytest.raises(HTTPException) as caught:
            demo_identity(IdentityBody(user_id=member['user_id']), Request({'type': 'http'}))
        assert caught.value.status_code == 422
    for d in store.workspace('demo-owner')['projects']:
        assert len(d['members']) == 4
    before = store.workspace('demo-owner')
    ensure_demo_workspace(store)
    assert store.workspace('demo-owner') == before


@pytest.mark.parametrize('invalid', [{'route': ['direct']}, {'suitability': ['confirmed']}, {'supply_status': {}}])
def test_selection_rejects_nonstring_enums_without_server_error(store, invalid):
    d = baseline(store)
    raises(422, lambda: command(store, d, 'record_selection', selection(**invalid)))


def test_pending_publication_is_current_valid_approved_release(store):
    from tests.support.taskbook_handoff import approved
    d = approved(store)
    release = d['taskbook_releases'][0]
    assert d['project_plan']['pending_releases'] == [{'task_id': d['tasks'][0]['id'], 'release_id': release['id'], 'source_revision_id': release['revision_id']}]
    d = command(store, d, 'publish_plan', {'task_id': d['tasks'][0]['id'], 'release_id': release['id']})
    assert d['project_plan']['pending_releases'] == []


def test_pending_publication_hides_approved_release_with_linked_change(store):
    from tests.support.taskbook_handoff import approved
    d = approved(store)
    requirement = d['requirements'][0]
    d = command(store, d, 'save_requirement', {k: ('new thermal input' if k == 'content' else requirement[k]) for k in ('id', 'title', 'content', 'source', 'acceptance', 'clarification')})
    d = command(store, d, 'confirm_baseline')
    assert d['project_plan']['pending_releases'] == []


def test_new_native_task_rejects_selection_route_mismatch(store):
    d = command(store, baseline(store), 'record_selection', selection('new'))
    raises(409, lambda: command(store, d, 'adopt_development', adoption('modified')))


def test_project_reads_do_not_add_an_operations_runtime_projection(store):
    d = baseline(store)
    other = store.create_project({'user_id': 'other', 'display_name': '其他人'}, {'name': '不可见项目', 'customer': 'C', 'product': 'P'}, 'other-project')
    for run_id, pid in (('visible-run', d['project']['id']), ('hidden-run', other['project']['id'])):
        run = {'run_id': run_id, 'jid': run_id + '-job', 'task_id': 'task-1', 'status': 'interrupted', 'error': '服务重启，请明确重试', 'file_ref': 'internal/path', 'runtime_fingerprint': 'internal'}
        with sqlite3.connect(store.db_path) as conn:
            conn.execute('INSERT INTO taskbook_runs VALUES (?,?,?,?)', (run_id, pid, 'task-1', json.dumps(run)))
    detail = store.detail(d['project']['id'], 'owner')
    workspace = store.workspace('owner')
    assert 'taskbook_runs' not in detail
    assert 'taskbook_runs' not in workspace['projects'][0]
    assert 'internal/path' not in json.dumps(workspace)
    assert 'internal' not in json.dumps(detail)
    assert len(store.workspace('owner')['projects']) == 1
    with sqlite3.connect(store.db_path) as conn:
        run = json.loads(conn.execute('SELECT document FROM taskbook_runs WHERE run_id=?', ('visible-run',)).fetchone()[0])
        run.update(status='done')
        run.pop('error')
        conn.execute('UPDATE taskbook_runs SET document=? WHERE run_id=?', (json.dumps(run), 'visible-run'))
    with sqlite3.connect(store.db_path) as conn:
        actual = json.loads(conn.execute('SELECT document FROM taskbook_runs WHERE run_id=?', ('visible-run',)).fetchone()[0])
    assert actual['status'] == 'done' and 'error' not in actual
    assert actual['file_ref'] == 'internal/path'


def test_reconfirmed_route_keeps_unaffected_native_release_across_baselines(store):
    from tests.support.taskbook_handoff import approved
    d = approved(store)
    release = d['taskbook_releases'][0]
    d = command(store, d, 'save_requirement', {'title': 'unrelated', 'content': 'finish', 'source': 'extra', 'acceptance': 'inspect', 'clarification': 'resolved'})
    d = command(store, d, 'confirm_baseline')
    d = command(store, d, 'record_selection', selection('new'))
    assert d['change_impacts'] == []
    assert d['journey']['stage'] == 'publication'
    assert d['project_plan']['pending_releases'][0]['release_id'] == release['id']
    d = command(store, d, 'publish_plan', {'task_id': d['tasks'][0]['id'], 'release_id': release['id']})
    assert d['journey']['stage'] == 'execution'
    assert d['taskbook_releases'][0] == release


def test_reconfirmed_route_does_not_hide_linked_native_change(store):
    from tests.support.taskbook_handoff import approved
    d = approved(store)
    requirement = d['requirements'][0]
    d = command(store, d, 'save_requirement', {k: ('changed thermal' if k == 'content' else requirement[k]) for k in ('id', 'title', 'content', 'source', 'acceptance', 'clarification')})
    d = command(store, d, 'confirm_baseline')
    d = command(store, d, 'record_selection', selection('new'))
    assert d['journey']['stage'] == 'needs_revalidation'
    assert d['project_plan']['pending_releases'] == []


def test_reconfirmed_different_route_does_not_adopt_existing_native_unit(store):
    from tests.support.taskbook_handoff import approved
    d = approved(store)
    d = command(store, d, 'record_selection', selection('modification'))
    assert d['journey']['stage'] == 'development_pending'
