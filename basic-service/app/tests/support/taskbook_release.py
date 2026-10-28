"""Fixed taskbook revisions, WBS plans and review submission scenarios."""
import hashlib
import json
from tests.support.rd_project import ENGINEER, command
from tests.support.taskbook_workflow import native


def drafted(store):
    d=native(store); tid=d['tasks'][0]['id']; pid=d['project']['id']
    d=command(store,d,'start_task',{'task_id':tid},ENGINEER)
    with store._transaction() as conn:
        doc=store._load(conn,pid,'engineer'); w=doc['taskbook_work_units'][0]
        w.update(input_package_id='p1',selected_run_id='run1',selected_revision_id='r1',selected_document_sha256=hashlib.sha256(b'doc').hexdigest())
        doc['taskbook_input_packages'].append({'id':'p1','task_id':tid,'baseline_id':doc['project']['current_baseline_id'],'confirmation':{'confirmed':True},'source_refs':[]})
        coverage={'id':'c1','task_id':tid,'run_id':'run1','revision_id':'r1','document_sha256':w['selected_document_sha256'],'package_id':'p1','blocking_count':0,'findings':[{'section_key':str(n),'status':'evidenced','checked_by':'engineer','evidence_ref':'source'} for n in range(15)]}
        doc['taskbook_coverages'].append(coverage)
        binding={'jid':'j1','project_id':pid,'task_id':tid,'baseline_id':doc['project']['current_baseline_id'],'actor_id':'engineer'}
        doc['generations'].append(binding)
        conn.execute('INSERT INTO generations VALUES (?,?,?)',('j1',pid,json.dumps(binding)))
        conn.execute('INSERT INTO taskbook_runs VALUES (?,?,?,?)',('run1',pid,tid,json.dumps({'run_id':'run1','jid':'j1','project_id':pid,'task_id':tid,'package_id':'p1','status':'completed'})))
        store._save(conn,doc,'fixture','engineer',{})
    d=store.detail(pid,'engineer')
    return command(store,d,'advance_taskbook_stage',{'task_id':tid,'target_stage':'ND14'},ENGINEER)


def item(d, **changes):
    return {'id':'w1','title':'Verify thermal','kind':'verification','assignee_id':'engineer','reviewer_id':'reviewer','requirement_ids':[d['requirements'][0]['id']],'output_anchor':'section:thermal','deliverable':'report','acceptance':'passes thermal test','acceptance_owner_id':'reviewer','verification_method':'test','predecessor_ids':[],**changes}


def planned(store):
    d=drafted(store); tid=d['tasks'][0]['id']
    return command(store,d,'save_wbs',{'task_id':tid,'expected_wbs_revision':0,'source_revision_id':'r1','items':[item(d)]},ENGINEER)


def submit(store,d,key='submit1'):
    from src.service.rd_platform.taskbook_release import submit_taskbook_review
    if d['taskbook_work_units'][0]['current_stage']=='ND14':
        d=command(store,d,'advance_taskbook_stage',{'task_id':d['tasks'][0]['id'],'target_stage':'ND15'},ENGINEER)
    path=store.artifact_root/'doc.docx'; path.write_bytes(b'doc'); sha=hashlib.sha256(b'doc').hexdigest()
    artifact={'jid':'j1','source_revision_id':'r1','sha256':sha,'file_ref':str(path),'filename':'doc.docx','quality_status':'passed','quality_evidence':{'revision_id':'r1','sha256':sha,'checks':{'status':'passed','revision_id':'r1','sha256':sha,'scope':'revision_deterministic'}}}
    payload={'run_id':'run1','revision_id':'r1','coverage_id':'c1','wbs_revision':d['taskbook_wbs_drafts'][-1]['revision'],'artifact_payload':artifact}
    return submit_taskbook_review(store,d['project']['id'],d['tasks'][0]['id'],ENGINEER,payload,d['project']['version'],key)
