"""Persistent generation intents and recovery around the original engine entry."""
import asyncio
import json
import pytest
from fastapi import BackgroundTasks
from src.service.rd_platform.store import RdError
from tests.support.taskbook_inputs import native, package
from tests.support.rd_project import ENGINEER

@pytest.fixture
def worker(monkeypatch,tmp_path):
    from src.controller import taskbook_controller as jobs
    state=jobs._RuntimeState();state.upload_dir=tmp_path/'uploads';state.output_dir=tmp_path/'outputs'
    state.upload_dir.mkdir();state.output_dir.mkdir()
    monkeypatch.setattr(jobs,'_STATE',state)
    monkeypatch.setattr(jobs,'_llm_submission_error',lambda *a:None)
    calls=[]
    def run(jid,*args,**kw):
        calls.append((jid,args,kw))
        jobs._STATE.jobs[jid]['status']='done'
    monkeypatch.setattr(jobs,'_run_job',run)
    return calls

def test_intent_is_durable_before_dispatch_and_idempotent(native,worker):
    from src.service.rd_platform.taskbook_runs import start_taskbook_run,list_taskbook_runs
    store,pid,tid=native;fixed=package(native); bg=BackgroundTasks()
    version=store.detail(pid,'engineer')['project']['version']
    first=start_taskbook_run(store,pid,tid,ENGINEER,fixed['id'],version,'run',background_tasks=bg)
    assert not worker
    assert store.generation(first['run']['jid'])['inputs']['package_id']==fixed['id']
    assert list_taskbook_runs(store,pid,tid,ENGINEER)[0]['status']=='intent'
    assert start_taskbook_run(store,pid,tid,ENGINEER,fixed['id'],version,'run',background_tasks=bg)==first
    asyncio.run(bg())
    assert len(worker)==1
    assert list_taskbook_runs(store,pid,tid,ENGINEER)[0]['status']=='done'
    assert worker[0][1][0].endswith('.docx') and worker[0][1][1].endswith('.docx')
    assert worker[0][2]['cover_phase']=='F'
    assert store.detail(pid,'engineer')['taskbook_work_units'][0]['selected_revision_id'] is None

def test_restart_marks_lost_dispatch_interrupted_and_does_not_rerun(native,worker):
    from src.service.rd_platform.taskbook_runs import start_taskbook_run,reconcile_taskbook_runs,list_taskbook_runs
    store,pid,tid=native;fixed=package(native);bg=BackgroundTasks()
    result=start_taskbook_run(store,pid,tid,ENGINEER,fixed['id'],store.detail(pid,'engineer')['project']['version'],'run',background_tasks=bg)
    with store._transaction() as c:
        row=c.execute('SELECT document FROM taskbook_runs WHERE run_id=?',(result['run']['run_id'],)).fetchone();run=json.loads(row[0]);run['status']='dispatching'
        c.execute('UPDATE taskbook_runs SET document=? WHERE run_id=?',(json.dumps(run),run['run_id']))
    reconcile_taskbook_runs(store,dispatch_intents=False)
    assert list_taskbook_runs(store,pid,tid,ENGINEER)[0]['status']=='interrupted'
    assert not worker

def test_cancel_before_dispatch_cannot_become_current_success(native,worker):
    from src.service.rd_platform.taskbook_runs import start_taskbook_run,cancel_taskbook_run,list_taskbook_runs
    store,pid,tid=native;fixed=package(native);bg=BackgroundTasks()
    result=start_taskbook_run(store,pid,tid,ENGINEER,fixed['id'],store.detail(pid,'engineer')['project']['version'],'run',background_tasks=bg)
    cancel_taskbook_run(store,pid,tid,ENGINEER,result['run']['run_id'],store.detail(pid,'engineer')['project']['version'],'cancel')
    asyncio.run(bg())
    assert list_taskbook_runs(store,pid,tid,ENGINEER)[0]['status']=='cancelled'
    assert not worker

def test_drift_and_unavailable_model_refuse_before_intent(native,worker,monkeypatch):
    from src.controller import taskbook_controller as jobs
    from src.service.rd_platform import taskbook_inputs as inputs
    from src.service.rd_platform.taskbook_runs import start_taskbook_run,list_taskbook_runs
    store,pid,tid=native;fixed=package(native);version=store.detail(pid,'engineer')['project']['version']
    monkeypatch.setattr(jobs,'_llm_submission_error',lambda *a:'模型不可用')
    with pytest.raises(RdError,match='模型'):
        start_taskbook_run(store,pid,tid,ENGINEER,fixed['id'],version,'run',background_tasks=BackgroundTasks())
    monkeypatch.setattr(jobs,'_llm_submission_error',lambda *a:None)
    monkeypatch.setattr(inputs,'runtime_fingerprint',lambda:'changed')
    with pytest.raises(RdError,match='环境'):
        start_taskbook_run(store,pid,tid,ENGINEER,fixed['id'],version,'run',background_tasks=BackgroundTasks())
    assert list_taskbook_runs(store,pid,tid,ENGINEER)==[]

def test_restart_rejects_tampered_terminal_artifact(native,worker):
    from pathlib import Path
    from src.controller import taskbook_controller as jobs
    from src.service.rd_platform.taskbook_runs import start_taskbook_run,reconcile_taskbook_runs,list_taskbook_runs
    store,pid,tid=native;fixed=package(native)
    result=start_taskbook_run(store,pid,tid,ENGINEER,fixed['id'],store.detail(pid,'engineer')['project']['version'],'recover',background_tasks=BackgroundTasks())
    run_id=result['run']['run_id'];jid=result['run']['jid']
    with store._transaction() as c:
        run=json.loads(c.execute('SELECT document FROM taskbook_runs WHERE run_id=?',(run_id,)).fetchone()[0]);run['status']='running'
        c.execute('UPDATE taskbook_runs SET document=? WHERE run_id=?',(json.dumps(run),run_id))
    out=jobs._STATE.output_dir/'recovered.docx';out.write_bytes(b'tampered')
    jobs._STATE.jobs[jid]={'status':'done','restored_from_manifest':True,'result':{'out':str(out)},'artifact_sha256':'wrong'}
    reconcile_taskbook_runs(store,dispatch_intents=False)
    assert list_taskbook_runs(store,pid,tid,ENGINEER)[0]['status']=='interrupted'

def test_late_result_cannot_replace_explicitly_selected_revision(native,worker):
    from src.service.rd_platform.taskbook_runs import start_taskbook_run
    from src.service.rd_platform.store import _json
    store,pid,tid=native;fixed=package(native);bg=BackgroundTasks()
    start_taskbook_run(store,pid,tid,ENGINEER,fixed['id'],store.detail(pid,'engineer')['project']['version'],'late',background_tasks=bg)
    with store._transaction() as c:
        d=store._load(c,pid,'engineer');d['taskbook_work_units'][0]['selected_revision_id']='manual-newer-revision'
        c.execute('UPDATE projects SET document=? WHERE id=?',(_json(d),pid))
    asyncio.run(bg())
    assert store.detail(pid,'engineer')['taskbook_work_units'][0]['selected_revision_id']=='manual-newer-revision'

def test_native_and_legacy_adapter_pass_same_engine_inputs(native,worker):
    from pathlib import Path
    from jonhon_taskbook.template_registry import resolve_template_selection
    from src.service.rd_platform.integration import enqueue_bound_job,submission_fingerprint
    from src.service.rd_platform.taskbook_runs import start_taskbook_run
    store,pid,tid=native;fixed=package(native)
    with store._connection() as conn:
        internal=next(p for p in store._load(conn,pid,'engineer')['taskbook_input_packages'] if p['id']==fixed['id'])
    payloads={source['role']:Path(source['file_ref']).read_bytes() for source in internal['source_refs'] if source['role'] in {'tech','spec'}}
    p=fixed['normalized_parameters'];m=fixed['model_selection']
    opts={k:p[k] for k in ('development_process','product_series','organization_scope','cover_phase')}
    opts.update(model_provider=m['provider'],model_name=m['name'],model_id=m['id'])
    baseline=store.detail(pid,'engineer')['project']['current_baseline_id']
    context={'store':store,'actor':ENGINEER,'pid':pid,'tid':tid,'baseline_id':baseline,'key':'legacy'}
    bg=BackgroundTasks()
    enqueue_bound_job(context,submission_fingerprint(payloads,{'rd_baseline_id':baseline}),payloads,{'tech':'tech.docx','spec':'spec.docx'},bg,resolve_template_selection('filter_connector','military'),opts,False,None,False)
    asyncio.run(bg())
    legacy=worker[-1]
    bg=BackgroundTasks();start_taskbook_run(store,pid,tid,ENGINEER,fixed['id'],store.detail(pid,'engineer')['project']['version'],'native',background_tasks=bg);asyncio.run(bg())
    new=worker[-1]
    assert legacy[2]=={k:v for k,v in new[2].items() if k!='indicator_clarifications'}
    for index in (0,1):assert Path(legacy[1][index]).read_bytes()==Path(new[1][index]).read_bytes()
    for field in ('template_path','profile_path','category_mapping_path'):
        assert Path(getattr(legacy[1][2],field)).read_bytes()==Path(getattr(new[1][2],field)).read_bytes()
