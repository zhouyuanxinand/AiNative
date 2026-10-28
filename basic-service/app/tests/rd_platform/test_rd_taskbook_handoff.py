from tests.support.taskbook_handoff import approved, published
import copy
from tests.support.rd_project import ENGINEER, REVIEWER, command, raises
from tests.support.rd_project import store as store
from tests.support.taskbook_release import planned, submit


def test_unapproved_cannot_publish_and_repeated_publish_is_one_plan(store):
    d=planned(store)
    raises(404,lambda:command(store,d,'publish_plan',{'task_id':d['tasks'][0]['id'],'release_id':'not-approved'}))
    d=submit(store,d)
    d=command(store,d,'decide_review',{'review_id':d['reviews'][-1]['id'],'decision':'approved'},REVIEWER)
    d=command(store,d,'publish_plan',{'task_id':d['tasks'][0]['id'],'release_id':d['taskbook_releases'][0]['id']})
    original=copy.deepcopy(d['plan_releases'])
    d=command(store,d,'publish_plan',{'task_id':d['tasks'][0]['id'],'release_id':d['taskbook_releases'][0]['id']})
    assert len(d['tasks'])==2 and d['plan_releases']==original


def test_receipt_required_before_actual_start_and_traceable_source(store):
    d=published(store); child=d['tasks'][1]; handoff=d['handoffs'][0]
    assert child['source_release_id']==d['taskbook_releases'][0]['id']
    assert child['requirement_ids']==d['taskbook_releases'][0]['requirement_ids']
    raises(409,lambda:command(store,d,'start_task',{'task_id':child['id']},ENGINEER))
    raises(403,lambda:command(store,d,'accept_handoff',{'handoff_id':handoff['id']},REVIEWER))
    d=command(store,d,'accept_handoff',{'handoff_id':handoff['id']},ENGINEER)
    assert not d['tasks'][1].get('actual_start')
    d=command(store,d,'start_task',{'task_id':child['id']},ENGINEER)
    assert d['tasks'][1]['actual_start']>=d['handoffs'][0]['accepted_at']
    assert d['project_plan']['items'][0]['actual_start']==d['tasks'][1]['actual_start']


def test_unrelated_requirement_change_keeps_native_approved_valid(store):
    d=approved(store); rid=d['taskbook_releases'][0]['id']
    d=command(store,d,'save_requirement',{'title':'unrelated','content':'finish','source':'extra','acceptance':'inspect','clarification':'resolved'})
    d=command(store,d,'confirm_baseline')
    assert d['tasks'][0]['status']=='done'
    assert d['change_impacts']==[]
    d=command(store,d,'publish_plan',{'task_id':d['tasks'][0]['id'],'release_id':rid})
    assert len(d['plan_releases'])==1


def test_linked_change_preserves_approval_and_pauses_inflight_use(store):
    d=published(store); handoff=d['handoffs'][0]
    d=command(store,d,'accept_handoff',{'handoff_id':handoff['id']},ENGINEER)
    d=command(store,d,'start_task',{'task_id':d['tasks'][1]['id']},ENGINEER)
    started=d['tasks'][1]['actual_start']; release=copy.deepcopy(d['taskbook_releases'][0]); requirement=d['requirements'][0]
    d=command(store,d,'save_requirement',{**{k:requirement[k] for k in ('id','title','source','acceptance','clarification')},'content':'changed thermal'})
    d=command(store,d,'confirm_baseline')
    assert d['taskbook_releases'][0]==release
    assert d['tasks'][1]['actual_start']==started
    assert d['change_impacts'][0]['status']=='pending'
    assert d['tasks'][1]['status']=='needs_revalidation'
    raises(409,lambda:store.authorize_generation('j1','engineer',write=True))
    d=command(store,d,'resolve_change_impact',{'impact_id':d['change_impacts'][0]['id'],'decision':'unaffected','reason':'Confirmed thermal requirement does not affect this usage'})
    assert d['tasks'][1]['status']=='in_progress'
    assert d['tasks'][1]['actual_start']==started


def test_targeted_source_change_and_unknown_mapping_are_conservative(store):
    from src.service.rd_platform.taskbook_changes import assess_taskbook_impact
    d=approved(store)
    assert assess_taskbook_impact(d,[{'kind':'source','source_id':'unrelated','version':2}])==[]
    d['taskbook_input_packages'][0]['source_refs']=[{'source_id':'technical','version':1}]
    impacts=assess_taskbook_impact(d,[{'kind':'source','source_id':'technical','version':2}])
    assert len(impacts)==1 and impacts[0]['status']=='pending'


def test_new_requirement_unknown_for_all_scope_adoption_requires_review(store):
    d=approved(store)
    with store._transaction() as conn:
        doc=store._load(conn,d['project']['id'],'owner')
        doc['development_adoptions'][0]['requirement_scope']='all'
        store._save(conn,doc,'fixture','owner',{})
    d=store.detail(d['project']['id'],'owner')
    d=command(store,d,'save_requirement',{'title':'new','content':'new approval scope unknown','source':'new agreement','acceptance':'test','clarification':'resolved'})
    d=command(store,d,'confirm_baseline')
    assert d['change_impacts'][0]['status']=='pending'


def test_revised_plan_preserves_inflight_task_and_requires_fresh_receipt(store):
    from tests.support.taskbook_release import item
    d=published(store);tid=d['tasks'][0]['id'];child_id=d['tasks'][1]['id'];old_release=copy.deepcopy(d['taskbook_releases'][0])
    d=command(store,d,'accept_handoff',{'handoff_id':d['handoffs'][0]['id']},ENGINEER)
    d=command(store,d,'start_task',{'task_id':child_id},ENGINEER);started=d['tasks'][1]['actual_start']
    d=command(store,d,'reopen_taskbook',{'task_id':tid,'reason':'new verification delivery scope'})
    d=command(store,d,'advance_taskbook_stage',{'task_id':tid,'target_stage':'ND14'},ENGINEER)
    d=command(store,d,'save_wbs',{'task_id':tid,'expected_wbs_revision':1,'source_revision_id':'r1','items':[item(d,deliverable='revised report',planned_start='2027-01-01')]},ENGINEER)
    d=submit(store,d,key='submit-new-edition')
    d=command(store,d,'decide_review',{'review_id':d['reviews'][-1]['id'],'decision':'approved'},REVIEWER)
    d=command(store,d,'publish_plan',{'task_id':tid,'release_id':d['taskbook_releases'][-1]['id']})
    assert len(d['tasks'])==2 and len(d['plan_releases'])==2
    assert d['taskbook_releases'][0]==old_release
    assert d['tasks'][1]['actual_start']==started
    assert d['tasks'][1]['status']=='needs_revalidation'
    d=command(store,d,'accept_handoff',{'handoff_id':d['handoffs'][-1]['id']},ENGINEER)
    assert d['tasks'][1]['status']=='in_progress'
    assert d['tasks'][1]['actual_start']==started
    assert d['tasks'][1]['planned_start'] is None


def test_published_usage_remains_impact_dependency_after_draft_changes(store):
    from src.service.rd_platform.taskbook_changes import assess_taskbook_impact
    d=published(store)
    d['taskbook_releases'][0]['source_refs']=[{'source_id':'old-technical','version':1}]
    d['taskbook_input_packages'][0]['source_refs']=[{'source_id':'new-draft-technical','version':1}]
    impacts=assess_taskbook_impact(d,[{'kind':'source','source_id':'old-technical','version':2}])
    assert len(impacts)==1
    assert impacts[0]['downstream_task_ids']==[d['tasks'][1]['id']]


def test_revalidate_can_explicitly_adopt_new_approved_scope(store):
    d=approved(store);requirement=d['requirements'][0]
    d=command(store,d,'save_requirement',{'id':requirement['id'],'title':'R1','content':'expanded thermal scope','source':'approval2','acceptance':'test','clarification':'resolved'})
    d=command(store,d,'confirm_baseline')
    d=command(store,d,'adopt_development',{'route':'modified','approval_ref':'OA-2','scope':'expanded','process_template_ref':{'id':'BP05','version':'2'},'provenance':'manual'})
    new_adoption=d['development_adoptions'][-1]['id']
    d=command(store,d,'resolve_change_impact',{'impact_id':d['change_impacts'][0]['id'],'decision':'revalidate','reason':'approved expanded scope','adoption_id':new_adoption})
    assert d['taskbook_work_units'][0]['adoption_id']==new_adoption
    assert d['tasks'][0]['status']=='in_progress'
    assert d['taskbook_work_units'][0]['input_package_id'] is None


def plan_item_in_review(store):
    import hashlib
    d=published(store);pid=d['project']['id'];tid=d['tasks'][1]['id']
    d=command(store,d,'accept_handoff',{'handoff_id':d['handoffs'][0]['id']},ENGINEER)
    d=command(store,d,'start_task',{'task_id':tid},ENGINEER)
    store.bind_generation(pid,tid,ENGINEER,'child-job',{})
    d=store.detail(pid,'engineer');path=store.artifact_root/'child.docx';path.write_bytes(b'child report');sha=hashlib.sha256(path.read_bytes()).hexdigest()
    evidence={'revision_id':'child-r1','sha256':sha,'checks':{'status':'passed','revision_id':'child-r1','sha256':sha,'scope':'revision_deterministic'}}
    payload={'jid':'child-job','source_revision_id':'child-r1','filename':'child.docx','sha256':sha,'file_ref':str(path),'quality_status':'passed','quality_evidence':evidence}
    d=store.register_artifact(pid,tid,ENGINEER,payload,d['project']['version'],'child-capture')
    return command(store,d,'submit_review',{'task_id':tid,'artifact_id':d['artifacts'][-1]['id']},ENGINEER)


def test_pending_handoff_reassignment_revokes_old_recipient(store):
    d=published(store);tid=d['tasks'][1]['id'];old_handoff=d['handoffs'][0]['id']
    d=command(store,d,'add_member',{'user_id':'new','display_name':'new','role':'engineer'})
    d=command(store,d,'reassign_task',{'task_id':tid,'assignee_id':'new','reviewer_id':'reviewer'})
    raises(403,lambda:command(store,d,'accept_handoff',{'handoff_id':old_handoff},ENGINEER))
    current=d['tasks'][1]['required_handoff_id']
    assert current!=old_handoff
    assert d['handoffs'][-1]['assignee_id']=='new'
    d=command(store,d,'accept_handoff',{'handoff_id':current},{'user_id':'new','display_name':'new'})
    assert d['tasks'][1]['assignee_id']=='new'
    d=command(store,d,'start_task',{'task_id':tid},{'user_id':'new','display_name':'new'})
    assert d['tasks'][1]['status']=='in_progress'


def test_reassign_in_review_requires_new_receipt_and_withdraws_old_review(store):
    d=plan_item_in_review(store);tid=d['tasks'][1]['id'];rid=d['reviews'][-1]['id'];old_handoff=d['handoffs'][0]['id']
    d=command(store,d,'add_member',{'user_id':'new','display_name':'new','role':'engineer'})
    d=command(store,d,'reassign_task',{'task_id':tid,'assignee_id':'new','reviewer_id':'reviewer'})
    assert d['reviews'][-1]['status']=='withdrawn'
    raises(409,lambda:command(store,d,'decide_review',{'review_id':rid,'decision':'approved'},REVIEWER))
    raises(403,lambda:command(store,d,'accept_handoff',{'handoff_id':old_handoff},ENGINEER))
    raises(409,lambda:store.bind_generation(d['project']['id'],tid,{'user_id':'new','display_name':'new'},'new-before-receipt',{}))
    d=command(store,d,'accept_handoff',{'handoff_id':d['tasks'][1]['required_handoff_id']},{'user_id':'new','display_name':'new'})
    assert d['tasks'][1]['assignee_id']=='new'
    assert d['handoffs'][0]['accepted_by']=='engineer'
    assert d['handoffs'][-1]['accepted_by']=='new'


def test_unrelated_baseline_does_not_block_plan_item_review_approval(store):
    d=plan_item_in_review(store);rid=d['reviews'][-1]['id']
    d=command(store,d,'save_requirement',{'title':'other','content':'unrelated','source':'extra','acceptance':'test','clarification':'resolved'})
    d=command(store,d,'confirm_baseline')
    assert d['tasks'][1]['status']=='in_review' and d['change_impacts']==[]
    assert store.authorize_generation('child-job','engineer',write=True)['task_id']==d['tasks'][1]['id']
    d=command(store,d,'decide_review',{'review_id':rid,'decision':'approved'},REVIEWER)
    assert d['tasks'][1]['status']=='done'
