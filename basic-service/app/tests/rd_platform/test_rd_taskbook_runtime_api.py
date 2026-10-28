"""HTTP authorization, server-owned references and private state semantics."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.support.taskbook_inputs import native,package,docx
from tests.support.rd_project import ENGINEER

@pytest.fixture
def api(native,monkeypatch):
    from src.controller import rd_taskbook_controller as controller
    from src.service.rd_platform import integration
    store,pid,tid=native
    monkeypatch.setattr(controller,'get_store',lambda:store)
    monkeypatch.setattr(integration,'get_rd_store',lambda:store)
    app=FastAPI()
    @app.middleware('http')
    async def identity(request,call_next):
        uid=request.headers.get('Test-User','engineer')
        request.state.current_user={'userid':uid,'verified':True}
        return await call_next(request)
    app.include_router(controller.router)
    return TestClient(app),f'/api/rd/projects/{pid}/tasks/{tid}/taskbook'

def test_workspace_private_draft_and_no_paths(api,native):
    client,url=api;store,pid,tid=native
    fixed=package(native)
    body={'input_package_id':fixed['id'],'expected_draft_revision':0,'form':{'product_series':'private'},'pending_operations':[]}
    response=client.put(url+'/draft',json=body)
    assert response.status_code==200,response.text
    result=client.get(url)
    assert result.status_code==200,result.text
    assert result.json()['draft']['form']['product_series']=='private'
    assert str(store.artifact_root) not in result.text
    assert client.get(url,headers={'Test-User':'reviewer'}).json()['draft'] is None
    assert client.put(url+'/draft',json=body,headers={'Test-User':'reviewer'}).status_code==403
    assert client.get(url,headers={'Test-User':'outsider'}).status_code==404

def test_source_reference_download_enforces_membership_and_integrity(api,native):
    client,url=api;store,pid,tid=native
    response=client.post(f'/api/rd/projects/{pid}/sources',data={'role':'tech','expected_version':store.detail(pid,'engineer')['project']['version']},files={'file':('技术文件.docx',docx())},headers={'Idempotency-Key':'source'})
    assert response.status_code==200,response.text
    source=response.json()['source'];download=f"/api/rd/projects/{pid}/sources/{source['source_id']}/versions/1/download"
    assert client.get(download).status_code==200
    assert client.get(download,headers={'Test-User':'outsider'}).status_code==404
    with store._connection() as c:
        internal=store._load(c,pid,'engineer')['project_sources'][0]
    from pathlib import Path
    Path(internal['file_ref']).write_bytes(b'bad')
    assert client.get(download).status_code==409

def test_unsupported_and_cross_project_source_paths_rejected(api,native):
    client,url=api;store,pid,tid=native
    body={'expected_version':store.detail(pid,'engineer')['project']['version'],'source_refs':[{'file_ref':'C:/secret','source_id':'other','version':1}],'parameters':{'cover_phase':'F'},'confirmed':True}
    result=client.post(url+'/input-packages',json=body,headers={'Idempotency-Key':'bad-ref'})
    assert result.status_code==422,result.text

def test_submitted_review_retry_replays_after_task_enters_review(api,native):
    from src.service.rd_platform.store import _json
    client,url=api;store,pid,tid=native
    body={'run_id':'original-run','revision_id':'baseline','coverage_id':'coverage','wbs_revision':1,'expected_version':store.detail(pid,'engineer')['project']['version']}
    fp=_json({'action':'submit_taskbook_review','task_id':tid,**body})
    original={'project':{'id':pid,'version':body['expected_version']+1},'reviews':[{'id':'review-once'}]}
    with store._transaction() as c:
        d=store._load(c,pid,'engineer');d['tasks'][0]['status']='in_review'
        c.execute('UPDATE projects SET document=? WHERE id=?',(_json(d),pid))
        store._remember(c,pid,'engineer','submission',fp,original)
    response=client.post(url+'/submit-review',json=body,headers={'Idempotency-Key':'submission'})
    assert response.status_code==200,response.text
    assert response.json()==original
    assert client.post(url+'/submit-review',json=body,headers={'Idempotency-Key':'submission','Test-User':'reviewer'}).status_code==403

def test_native_legacy_job_resources_redact_local_paths(api,native,monkeypatch):
    from src.controller import taskbook_controller as jobs
    from src.service.rd_platform.integration import RdJobAccessMiddleware
    client,url=api;store,pid,tid=native
    client.app.include_router(jobs.router)
    client.app.add_middleware(RdJobAccessMiddleware,store_getter=lambda:store)
    client.app.user_middleware.reverse()  # Identity must wrap the job access guard.
    state=jobs._RuntimeState();state.output_dir=store.artifact_root/'outputs';state.output_dir.mkdir();state.upload_dir=store.artifact_root/'uploads';state.upload_dir.mkdir()
    monkeypatch.setattr(jobs,'_STATE',state)
    jid='123456abcd';store.bind_generation(pid,tid,ENGINEER,jid,{'package_id':'fixed-native'})
    job=jobs._job_record();job.update(status='done',log=['保存到 '+str(store.artifact_root/'private.docx')],result={'out':str(store.artifact_root/'private.docx'),'meta':{'selection':{'template_path':str(store.artifact_root/'template.docx')},'api_key':'secret-not-for-api'}})
    state.jobs[jid]=job
    for path in (f'/api/status/{jid}',f'/api/stream/{jid}'):
        response=client.get(path)
        assert response.status_code==200,response.text
        assert str(store.artifact_root) not in response.text
        assert 'template_path' not in response.text
        assert 'secret-not-for-api' not in response.text

def test_native_editor_preserves_explicit_signed_client_capability(api,native,monkeypatch):
    from src.controller import taskbook_controller as jobs,review_controller,review_editor_controller
    from src.service.rd_platform.integration import RdJobAccessMiddleware
    from jonhon_taskbook.review_editor import verify_token
    client,url=api;store,pid,tid=native
    for router in (jobs.router,review_controller.router,review_editor_controller.router):client.app.include_router(router)
    client.app.add_middleware(RdJobAccessMiddleware,store_getter=lambda:store);client.app.user_middleware.reverse()
    state=jobs._RuntimeState();state.output_dir=store.artifact_root/'outputs';state.output_dir.mkdir();state.upload_dir=store.artifact_root/'uploads';state.upload_dir.mkdir()
    monkeypatch.setattr(jobs,'_STATE',state)
    for key,value in {'JTB_REVIEW_EDITOR_URL':'http://editor.test','JTB_REVIEW_PUBLIC_URL':'http://testserver','JTB_REVIEW_EDITOR_SECRET':'test-only-not-production-secret-123456789'}.items():monkeypatch.setenv(key,value)
    jid='123456abcd';store.bind_generation(pid,tid,ENGINEER,jid,{'package_id':'fixed-native'})
    out=state.output_dir/'editor.docx';out.write_bytes(docx())
    job=jobs._job_record();job.update(status='done',result={'out':str(out),'meta':{}});state.jobs[jid]=job
    response=client.post(f'/api/review/{jid}/editor',json={'revision_id':'baseline','mode':'edit'})
    assert response.status_code==200,response.text
    config=response.json()['config']
    assert config.get('token') and verify_token(config['token'],'test-only-not-production-secret-123456789')
    assert '[REDACTED]' not in config['document']['url']

def test_downstream_generation_and_capture_keep_valid_adopted_baseline_after_unrelated_change(tmp_path,monkeypatch):
    from pathlib import Path
    from src.service.rd_platform import integration
    from src.service.rd_platform.store import RdStore
    from tests.support.rd_project import command
    from tests.support.taskbook_handoff import published
    from jonhon_taskbook.review_store import ReviewStore
    from src.controller import review_controller
    store=RdStore(tmp_path/'downstream.sqlite3',tmp_path/'artifacts');d=published(store)
    pid=d['project']['id'];child=d['tasks'][1];tid=child['id'];baseline=child['baseline_id']
    d=command(store,d,'accept_handoff',{'handoff_id':d['handoffs'][0]['id']},ENGINEER)
    d=command(store,d,'start_task',{'task_id':tid},ENGINEER)
    d=command(store,d,'save_requirement',{'title':'unrelated extra','content':'decorative finish','source':'new','acceptance':'inspect','clarification':'resolved'})
    d=command(store,d,'confirm_baseline')
    assert d['project']['current_baseline_id']!=baseline and not d['change_impacts']
    assert integration.validate_submission(store,ENGINEER,pid,tid,baseline,True)['id']==tid
    jid='1234567890';store.bind_generation(pid,tid,ENGINEER,jid,{'rd_baseline_id':baseline})
    source=tmp_path/'child.docx';source.write_bytes(docx())
    reviews=ReviewStore(tmp_path/'reviews');bundle=reviews.ensure_review(jid,{'status':'done','result':{'out':str(source)}},{'output_dir':tmp_path,'upload_dir':tmp_path/'uploads'})
    revision=bundle['revisions'][0]
    revision['checks']={'status':'passed','revision_id':'baseline','sha256':revision['sha256'],'scope':'revision_deterministic'};reviews._write(jid,bundle)
    monkeypatch.setattr(review_controller,'ensure_review',lambda jid:reviews.get_review(jid));monkeypatch.setattr(review_controller,'get_store',lambda:reviews)
    result=integration.capture_artifact(store,pid,tid,ENGINEER,jid,'baseline',store.detail(pid,'engineer')['project']['version'],'child-artifact')
    assert result['artifacts'][-1]['task_id']==tid and result['artifacts'][-1]['baseline_id']==baseline

def test_blocked_generation_can_be_revised_checked_and_selected_but_failed_qa_cannot_submit(api,native,monkeypatch):
    from src.controller import taskbook_controller as jobs,review_controller
    from src.service.rd_platform import integration
    from src.service.rd_platform.store import _json
    from src.service.rd_platform.taskbook_inputs import digest
    client,url=api;store,pid,tid=native
    state=jobs._RuntimeState();state.output_dir=store.artifact_root/'outputs';state.output_dir.mkdir();state.upload_dir=store.artifact_root/'uploads';state.upload_dir.mkdir()
    monkeypatch.setattr(jobs,'_STATE',state)
    fixed=package(native);jid='123456abcd';run_id='blocked-native-run'
    store.bind_generation(pid,tid,ENGINEER,jid,{'package_id':fixed['id']})
    run={'run_id':run_id,'jid':jid,'project_id':pid,'task_id':tid,'package_id':fixed['id'],'status':'blocked','actor_id':'engineer','runtime_fingerprint':fixed['runtime_fingerprint']}
    with store._transaction() as c:c.execute('INSERT INTO taskbook_runs VALUES(?,?,?,?)',(run_id,pid,tid,_json(run)))
    out=state.output_dir/'blocked.docx';out.write_bytes(docx())
    job=jobs._job_record();job.update(status='blocked',result={'out':str(out),'meta':{'qa_ok':False}});state.jobs[jid]=job
    response=client.post(url+'/revisions/select',json={'run_id':run_id,'revision_id':'baseline','expected_version':store.detail(pid,'engineer')['project']['version']},headers={'Idempotency-Key':'select-blocked'})
    assert response.status_code==200,response.text
    checked=client.post(url+'/checks',json={'run_id':run_id,'revision_id':'baseline','expected_version':store.detail(pid,'engineer')['project']['version'],'decisions':[]},headers={'Idempotency-Key':'check-blocked'})
    assert checked.status_code==200,checked.text
    assert checked.json()['qa']['status']!='passed'
    with pytest.raises(Exception,match='QA|检查'):
        integration.prepare_artifact_payload(store,jid,'baseline')
    with store._connection() as c:
        import json
        assert json.loads(c.execute('SELECT document FROM taskbook_runs WHERE run_id=?',(run_id,)).fetchone()[0])['status']=='blocked'
