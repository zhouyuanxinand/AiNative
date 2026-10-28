from tests.support.taskbook_release import drafted, item, planned, submit
import copy
import json
import pytest
from tests.support.rd_project import ENGINEER, REVIEWER, command, raises
from tests.support.rd_project import store as store


@pytest.mark.parametrize('field',['deliverable','acceptance','acceptance_owner_id','verification_method'])
def test_wbs_rejects_missing_delivery_acceptance_and_responsibility(store,field):
    d=drafted(store)
    raises(422,lambda:command(store,d,'save_wbs',{'task_id':d['tasks'][0]['id'],'expected_wbs_revision':0,'source_revision_id':'r1','items':[item(d,**{field:''})]},ENGINEER))


def test_wbs_cycle_and_stale_revision_rejected(store):
    d=drafted(store); payload={'task_id':d['tasks'][0]['id'],'expected_wbs_revision':0,'source_revision_id':'r1','items':[item(d,predecessor_ids=['w2']),item(d,id='w2',predecessor_ids=['w1'])]}
    raises(422,lambda:command(store,d,'save_wbs',payload,ENGINEER))
    d=command(store,d,'save_wbs',{'task_id':d['tasks'][0]['id'],'expected_wbs_revision':0,'source_revision_id':'r1','items':[item(d)]},ENGINEER)
    raises(409,lambda:command(store,d,'save_wbs',{'task_id':d['tasks'][0]['id'],'expected_wbs_revision':0,'source_revision_id':'r1','items':[item(d)]},ENGINEER))


def test_review_snapshot_frozen_and_one_release_on_approval(store):
    d=planned(store)
    assert d['taskbook_releases']==[]
    d=submit(store,d); snapshot=copy.deepcopy(d['reviews'][-1]['taskbook_snapshot']); rid=d['reviews'][-1]['id']
    raises(403,lambda:command(store,d,'decide_review',{'review_id':rid,'decision':'approved'},ENGINEER))
    raises(409,lambda:command(store,d,'save_wbs',{'task_id':d['tasks'][0]['id'],'expected_wbs_revision':1,'source_revision_id':'r1','items':[item(d,title='changed')]},ENGINEER))
    d=command(store,d,'decide_review',{'review_id':rid,'decision':'approved'},REVIEWER,key='approve')
    assert d['reviews'][-1]['taskbook_snapshot']==snapshot
    assert len(d['taskbook_releases'])==1
    assert d['taskbook_releases'][0]['sha256']==snapshot['document_sha256']
    assert d['tasks'][0]['status']=='done'
    assert d['taskbook_work_units'][0]['stages'][2]['status']=='completed'


def test_native_generic_submit_cannot_bypass_snapshot(store):
    d=planned(store)
    raises(409,lambda:command(store,d,'submit_review',{'task_id':d['tasks'][0]['id'],'artifact_id':'x'},ENGINEER))


def test_concurrent_native_submission_is_one_atomic_snapshot(store):
    from concurrent.futures import ThreadPoolExecutor
    d=planned(store)
    d=command(store,d,'advance_taskbook_stage',{'task_id':d['tasks'][0]['id'],'target_stage':'ND15'},ENGINEER)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:submit(store,d,key='same-submission'),range(2)))
    assert results[0]==results[1]
    assert len(results[0]['artifacts'])==1 and len(results[0]['reviews'])==1


def test_native_withdraw_and_reassign_revoke_old_writer_and_review(store):
    d=submit(store,planned(store));tid=d['tasks'][0]['id'];rid=d['reviews'][-1]['id']
    raises(409,lambda:store.authorize_generation('j1','engineer',write=True))
    d=command(store,d,'withdraw_review',{'review_id':rid,'comment':'reassign author'})
    d=command(store,d,'add_member',{'user_id':'new','display_name':'new','role':'engineer'})
    d=command(store,d,'reassign_task',{'task_id':tid,'assignee_id':'new','reviewer_id':'reviewer'})
    raises(403,lambda:store.authorize_generation('j1','engineer',write=True))
    raises(403,lambda:store.authorize_generation('j1','new',write=True))


def test_rejection_cannot_resubmit_old_revision_and_old_checks(store):
    d=submit(store,planned(store));tid=d['tasks'][0]['id']
    d=command(store,d,'decide_review',{'review_id':d['reviews'][-1]['id'],'decision':'rejected','comment':'correct requirement evidence'},REVIEWER)
    d=command(store,d,'start_task',{'task_id':tid},ENGINEER)
    d=command(store,d,'advance_taskbook_stage',{'task_id':tid,'target_stage':'ND14'},ENGINEER)
    d=command(store,d,'save_wbs',{'task_id':tid,'expected_wbs_revision':1,'source_revision_id':'r1','items':[item(d)]},ENGINEER)
    raises(409,lambda:submit(store,d,key='resubmit-old'))


def test_wbs_requirement_must_belong_to_adopted_input_scope(store):
    d=drafted(store)
    d=command(store,d,'save_requirement',{'title':'other','content':'outside scope','source':'different','acceptance':'test','clarification':'resolved'})
    raises(422,lambda:command(store,d,'save_wbs',{'task_id':d['tasks'][0]['id'],'expected_wbs_revision':0,'source_revision_id':'r1','items':[item(d,requirement_ids=[d['requirements'][-1]['id']])]},ENGINEER))


def test_blocked_technical_run_can_submit_a_fixed_passing_revision(store):
    d=planned(store)
    with store._transaction() as conn:
        run=json.loads(conn.execute('SELECT document FROM taskbook_runs WHERE run_id=?',('run1',)).fetchone()[0])
        run['status']='blocked'
        conn.execute('UPDATE taskbook_runs SET document=? WHERE run_id=?',(json.dumps(run),'run1'))
    d=submit(store,d)
    assert d['reviews'][-1]['status']=='pending'
    assert d['reviews'][-1]['taskbook_snapshot']['quality_evidence']['checks']['status']=='passed'
    with store._connection() as conn:
        assert json.loads(conn.execute('SELECT document FROM taskbook_runs WHERE run_id=?',('run1',)).fetchone()[0])['status']=='blocked'
