"""Native demo imports documents honestly and never invokes the model worker."""
from pathlib import Path

import pytest


@pytest.fixture
def native_demo(tmp_path, monkeypatch):
    from src.controller import taskbook_controller as jobs
    from src.service.rd_platform.store import RdStore
    monkeypatch.setenv('JTB_DEMO_MODE', 'true')
    state = jobs._RuntimeState()
    state.upload_dir = tmp_path / 'uploads'
    state.output_dir = tmp_path / 'outputs'
    state.upload_dir.mkdir()
    state.output_dir.mkdir()
    monkeypatch.setattr(jobs, '_STATE', state)
    monkeypatch.setattr(jobs, '_run_job', lambda *a, **k: pytest.fail('Seed must not invoke model generation'))
    store = RdStore(tmp_path / 'rd.sqlite3', tmp_path / 'artifacts')
    from src.service.rd_platform.demo import ensure_demo_workspace
    ensure_demo_workspace(store)
    return store


def test_native_demo_contains_operable_workflow_and_preserves_user_edits(native_demo):
    from src.service.rd_platform.demo_taskbook import ensure_native_demo_workspace
    ensure_native_demo_workspace(native_demo)
    details = native_demo.workspace('demo-owner')['projects']
    units = [w for d in details for w in d['taskbook_work_units']]
    assert len(units) >= 6
    assert {w['current_stage'] for w in units} >= {'ND13', 'ND15'}
    assert any(d['taskbook_releases'] for d in details)
    assert any(d['plan_releases'] and d['handoffs'] for d in details)
    assert any(r['status'] == 'pending' and r.get('taskbook_snapshot') for d in details for r in d['reviews'])
    assert any(r['status'] == 'rejected' and r.get('taskbook_snapshot') for d in details for r in d['reviews'])
    before = sum(len(d['events']) for d in details)
    from src.service.rd_platform.store import RdStore
    reopened = RdStore(native_demo.db_path, native_demo.artifact_root)
    ensure_native_demo_workspace(reopened)
    assert sum(len(d['events']) for d in reopened.workspace('demo-owner')['projects']) == before


def test_native_sample_is_not_reported_as_live_generation(native_demo):
    import json
    from src.service.rd_platform.demo_taskbook import ensure_native_demo_workspace
    ensure_native_demo_workspace(native_demo)
    with native_demo._connection() as conn:
        runs = [json.loads(row[0]) for row in conn.execute('SELECT document FROM taskbook_runs')]
    assert runs
    assert all(r['status'] == 'demo_sample' and r['provenance'] == 'mock' for r in runs)
    from src.controller import taskbook_controller as jobs
    assert not jobs._STATE.jobs
    for d in native_demo.workspace('demo-owner')['projects']:
        for release in d['taskbook_releases']:
            artifact = native_demo.artifact(d['project']['id'], release['artifact_id'], 'demo-owner')
            assert artifact['quality_evidence']['source'] == 'mock'
            assert Path(artifact['file_ref']).is_file()


def test_native_seed_disabled_does_not_write_data(native_demo, monkeypatch):
    from src.service.rd_platform.demo_taskbook import ensure_native_demo_workspace
    monkeypatch.setenv('JTB_DEMO_MODE', 'false')
    ensure_native_demo_workspace(native_demo)
    assert not any(d['taskbook_work_units'] for d in native_demo.workspace('demo-owner')['projects'])


def test_change_demo_uses_targeted_source_change_and_keeps_approved_handoff_history(native_demo):
    from src.service.rd_platform.demo_taskbook import ensure_native_demo_workspace
    ensure_native_demo_workspace(native_demo)
    details=native_demo.workspace('demo-owner')['projects']
    units=[w for d in details for w in d['taskbook_work_units']]
    assert len(units)==7
    impacts=[(d,i) for d in details for i in d['change_impacts'] if i['status']=='pending']
    assert len(impacts)==1
    detail,impact=impacts[0]
    task=next(t for t in detail['tasks'] if t['id']==impact['task_id'])
    assert task['title']=='研制任务书 · 变更待复核'
    assert task['status']=='needs_revalidation' and task['previous_status']=='done'
    assert {r['kind'] for r in impact['changed_refs']}=={'source'}
    releases=[r for r in detail['taskbook_releases'] if r['task_id']==task['id']]
    assert len(releases)==1
    assert any(r['status']=='approved' and r['id'] in releases[0]['review_ids'] for r in detail['reviews'])
    handoffs=[h for h in detail['handoffs'] if h['source_task_id']==task['id']]
    assert len(handoffs)==2 and any(h['status']=='accepted' and h['accepted_at'] for h in handoffs)
    children=[t for t in detail['tasks'] if t.get('source_task_id')==task['id']]
    assert all(t['status']=='needs_revalidation' for t in children)
    assert any(t.get('actual_start') for t in children)
    package=next(p for p in detail['taskbook_input_packages'] if p['id']==impact['package_id'])
    changed=impact['changed_refs'][0]
    adopted=next(s for s in package['source_refs'] if s['source_id']==changed['source_id'])
    versions=[s for s in detail['project_sources'] if s['source_id']==changed['source_id']]
    assert adopted['version']==1 and {s['version'] for s in versions}=={1,2}
    assert len({s['sha256'] for s in versions})==2
    assert all(t['status']!='needs_revalidation' for d in details for t in d['tasks'] if t.get('kind')=='taskbook' and t['id']!=task['id'])


def test_v1_upgrade_adds_only_change_sample_and_restart_preserves_edits(native_demo,monkeypatch):
    import copy
    from src.service.rd_platform import demo_taskbook as demo
    from src.service.rd_platform.store import RdStore
    with monkeypatch.context() as old_version:
        old_version.setattr(demo,'SEED_GROUPS',((demo.MARKER,demo.CASES),))
        demo.ensure_native_demo_workspace(native_demo)
    before=native_demo.workspace('demo-owner')['projects']
    assert sum(len(d['taskbook_work_units']) for d in before)==6
    first=next(d for d in before if d['project']['code']=='RD-DEMO-001')
    editable=next(t for t in first['tasks'] if t.get('kind')=='taskbook')
    native_demo.execute(first['project']['id'],{'user_id':'demo-owner','display_name':'owner'},'reassign_task',{'task_id':editable['id'],'assignee_id':'demo-engineer','reviewer_id':'demo-owner'},first['project']['version'],'user-reassign-before-upgrade')
    before=copy.deepcopy(native_demo.workspace('demo-owner')['projects'])
    reopened=RdStore(native_demo.db_path,native_demo.artifact_root)
    demo.ensure_native_demo_workspace(reopened)
    after=reopened.workspace('demo-owner')['projects']
    assert sum(len(d['taskbook_work_units']) for d in after)==7
    for original in before:
        updated=next(d for d in after if d['project']['id']==original['project']['id'])
        for collection in ('tasks','taskbook_work_units','development_adoptions','taskbook_input_packages','taskbook_coverages','taskbook_wbs_drafts','taskbook_releases','plan_releases','handoffs','reviews','artifacts'):
            for row in original[collection]:
                assert next(r for r in updated[collection] if r['id']==row['id'])==row
        for source in original['project_sources']:
            assert next(s for s in updated['project_sources'] if (s['source_id'],s['version'])==(source['source_id'],source['version']))==source
    demo.ensure_native_demo_workspace(RdStore(native_demo.db_path,native_demo.artifact_root))
    assert reopened.workspace('demo-owner')['projects']==after
    # Recover a stop between the per-case marker and the final group marker.
    # The completed case must remain untouched while only the marker is added.
    with reopened._transaction() as conn:
        conn.execute('DELETE FROM demo_bootstrap WHERE name=?',(demo.CHANGE_MARKER,))
    demo.ensure_native_demo_workspace(RdStore(native_demo.db_path,native_demo.artifact_root))
    assert reopened.workspace('demo-owner')['projects']==after
