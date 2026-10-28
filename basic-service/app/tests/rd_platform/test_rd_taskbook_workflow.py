from tests.support.taskbook_workflow import admitted
from tests.support.rd_project import ENGINEER, command, raises
from tests.support.rd_project import store as store


def test_direct_use_does_not_create_taskbook(store):
    d = admitted(store, 'direct')
    raises(409, lambda: command(store,d,'create_taskbook',{'adoption_id':d['development_adoptions'][0]['id'],'title':'T','assignee_id':'engineer','reviewer_id':'reviewer'}))
    assert store.detail(d['project']['id'],'owner')['tasks'] == []


def test_taskbook_requires_approved_adoption(store):
    d = admitted(store)
    raises(422, lambda: command(store,d,'adopt_development',{'route':'modified','scope':'x','process_template_ref':{'id':'BP05','version':'1'},'provenance':'manual'}))


def test_retry_creates_one_work_unit(store):
    d = admitted(store)
    payload = {'adoption_id':d['development_adoptions'][0]['id'],'title':'T','assignee_id':'engineer','reviewer_id':'reviewer'}
    a = command(store,d,'create_taskbook',payload,key='same')
    assert command(store,d,'create_taskbook',payload,key='same') == a
    w = a['taskbook_work_units'][0]
    assert len({s['instance_id'] for s in w['stages']}) == 3
    assert w['current_stage'] == 'ND13'
    assert a['tasks'][0]['kind'] == 'taskbook'
    raises(409,lambda: command(store,a,'advance_taskbook_stage',{'task_id':a['tasks'][0]['id'],'target_stage':'ND14'},ENGINEER))


def test_generic_task_never_inferred_native_and_migration_preserves_ids(store):
    from tests.support.rd_project import prepared, capture
    d = capture(store, prepared(store))
    from src.service.rd_platform.store import RdStore
    reopened = RdStore(store.db_path,store.artifact_root).detail(d['project']['id'],'owner')
    assert reopened['artifacts'][0]['id'] == d['artifacts'][0]['id']
    assert reopened['taskbook_work_units'] == []


def test_return_to_drafting_never_marks_review_completed(store):
    from tests.support.taskbook_release import planned
    d=planned(store);tid=d['tasks'][0]['id']
    d=command(store,d,'advance_taskbook_stage',{'task_id':tid,'target_stage':'ND15'},ENGINEER)
    d=command(store,d,'advance_taskbook_stage',{'task_id':tid,'target_stage':'ND13'},ENGINEER)
    assert d['taskbook_work_units'][0]['stages'][2]['status']=='pending'
    assert d['taskbook_work_units'][0]['stages'][2]['completed_at'] is None


def test_adoption_rejects_requirement_only_in_unconfirmed_draft(store):
    d=admitted(store)
    d=command(store,d,'save_requirement',{'title':'draft','content':'unresolved','clarification':'open'})
    raises(422,lambda:command(store,d,'adopt_development',{'route':'modified','approval_ref':'OA2','scope':'scope','process_template_ref':{'id':'BP05','version':'1'},'provenance':'manual','requirement_ids':[d['requirements'][-1]['id']]}))


def test_default_adoption_uses_only_confirmed_baseline_requirements(store):
    d=admitted(store);confirmed_ids=[r['id'] for r in d['baselines'][-1]['requirements']]
    d=command(store,d,'save_requirement',{'title':'draft','content':'unresolved','clarification':'open'})
    d=command(store,d,'adopt_development',{'route':'modified','approval_ref':'OA2','scope':'scope','process_template_ref':{'id':'BP05','version':'1'},'provenance':'manual'})
    assert d['development_adoptions'][-1]['requirement_ids']==confirmed_ids
