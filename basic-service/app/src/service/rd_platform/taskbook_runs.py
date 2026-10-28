"""Durable native intent adapter. The original controller owns generation logic."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import threading
from .store import RdError, _actor, _id, _json, _now
from . import taskbook_inputs as inputs

TERMINAL={'done','blocked','error','cancelled','interrupted','environment_drift','demo_sample'}

def _row(conn,run_id):
    row=conn.execute('SELECT document FROM taskbook_runs WHERE run_id=?',(run_id,)).fetchone()
    if not row:raise RdError(404,'任务书运行不存在')
    return json.loads(row[0])

def _write(conn,run):
    conn.execute('UPDATE taskbook_runs SET document=? WHERE run_id=?',(_json(run),run['run_id']))

def list_taskbook_runs(store,pid,tid,actor):
    with store._connection() as conn:
        inputs.task_context(store,conn,pid,tid,actor)
        return [inputs.public_value(json.loads(row[0])) for row in conn.execute('SELECT document FROM taskbook_runs WHERE project_id=? AND task_id=? ORDER BY rowid DESC',(pid,tid))]

def get_taskbook_run(store,pid,tid,actor,run_id,write=False):
    with store._connection() as conn:
        inputs.task_context(store,conn,pid,tid,actor,write=write)
        run=_row(conn,run_id)
        if run['project_id']!=pid or run['task_id']!=tid:raise RdError(404,'本任务的运行不存在')
        return run

def _ready(package):
    from src.controller import taskbook_controller as jobs
    inputs.verify_package(package)
    model=package['model_selection'];p=package['normalized_parameters']
    error=jobs._llm_submission_error(str(p['use_llm']).lower(),model.get('provider',''),model.get('name',''),model.get('id',''))
    if error:raise RdError(409,'所选模型不可运行，请检查已固定的模型配置；受控流程须启用语义路由模型')

def start_taskbook_run(store,pid,tid,actor,package_id,expected_version,key,*,parent_run_id=None,answers=None,background_tasks=None):
    actor=_actor(actor)
    fp=inputs.digest(_json({'package_id':package_id,'parent_run_id':parent_run_id,'answers':answers}).encode())
    with store._transaction() as conn:
        doc,task,unit=inputs.task_context(store,conn,pid,tid,actor,write=True)
        replay=store._replay(conn,tid+':runs',actor['user_id'],key,fp)
        if replay:return replay
        store._version(doc,expected_version)
        package=inputs.package_from_doc(doc,tid,package_id)
        if unit.get('input_package_id')!=package_id:raise RdError(409,'输入包已更换，请重新核对当前采用版本')
        if any(i.get('task_id')==tid and i.get('status') in {'pending','unresolved','open'} for i in doc.get('change_impacts',[])):
            raise RdError(409,'上游变化影响尚未处置，请先复核输入用途')
        _ready(package)
        parent=None
        if parent_run_id:
            parent=_row(conn,parent_run_id)
            if parent['project_id']!=pid or parent['task_id']!=tid or parent['package_id']!=package_id:raise RdError(409,'澄清运行必须属于当前任务及同一输入包')
            if not isinstance(answers,dict) or not answers or len(_json(answers))>100000 or any(not isinstance(k,str) or not isinstance(v,str) or not v.strip() for k,v in answers.items()):
                raise RdError(422,'请提供有效的指标澄清答案')
            from src.controller import taskbook_controller as jobs
            try:
                review=jobs._indicator_review_payload(parent['jid'])
                parsed=jobs._parse_indicator_clarifications({'clarifications':answers},{str(item['indicator_name']) for item in review['manual_review_required']})
                answers={**review.get('indicator_clarifications',{}),**parsed}
            except (ValueError,FileNotFoundError) as exc:
                raise RdError(422,'澄清答案须对应父运行的待核指标且不能改写指标数值') from exc
        run_id=_id();jid=run_id[:10]
        run={'run_id':run_id,'jid':jid,'project_id':pid,'task_id':tid,'package_id':package_id,'parent_run_id':parent_run_id,
             'attempt':1+sum(1 for _ in conn.execute('SELECT 1 FROM taskbook_runs WHERE project_id=? AND task_id=?',(pid,tid))),
             'status':'intent','request_key':key,'created_at':_now(),'actor_id':actor['user_id'],'runtime_fingerprint':package['runtime_fingerprint'],
             'answers':copy.deepcopy(answers or {})}
        binding={'jid':jid,'project_id':pid,'task_id':tid,'baseline_id':package['baseline_id'],'actor_id':actor['user_id'],'created_at':_now(),
                 'inputs':{'package_id':package_id,'fingerprint':package['fingerprint'],'rd_baseline_id':package['baseline_id'],'run_id':run_id}}
        conn.execute('INSERT INTO taskbook_runs VALUES(?,?,?,?)',(run_id,pid,tid,_json(run)))
        conn.execute('INSERT INTO generations VALUES(?,?,?)',(jid,pid,_json(binding)))
        doc['generations'].append(binding)
        unit['candidate_run_id']=run_id
        store._save(conn,doc,'start_taskbook_run',actor['user_id'],{'task_id':tid,'run_id':run_id,'package_id':package_id})
        result={'run':inputs.public_value(run),'project_version':doc['project']['version']}
        store._remember(conn,tid+':runs',actor['user_id'],key,fp,result)
    if background_tasks is not None:background_tasks.add_task(dispatch_taskbook_run,store,run_id)
    else:threading.Thread(target=dispatch_taskbook_run,args=(store,run_id),daemon=True).start()
    return result

def dispatch_taskbook_run(store,run_id):
    """Claim once before dispatch. A crash after claim requires explicit retry."""
    from src.controller import taskbook_controller as jobs
    from jonhon_taskbook.template_registry import TemplateSelection
    with store._transaction() as conn:
        run=_row(conn,run_id)
        if run['status']!='intent':return
        try:
            doc,_,unit=inputs.task_context(store,conn,run['project_id'],run['task_id'],{'user_id':run['actor_id']},write=True)
        except RdError:
            run.update(status='interrupted',error='派发前任务责任、权限或输入有效性已变化，请核对后明确重试',finished_at=_now())
            _write(conn,run);return
        package=copy.deepcopy(inputs.package_from_doc(doc,run['task_id'],run['package_id']))
        if unit['input_package_id']!=run['package_id']:
            run.update(status='interrupted',error='派发前输入包已更换，请明确重试',finished_at=_now());_write(conn,run);return
        run.update(status='dispatching',dispatched_at=_now());_write(conn,run)
    final_status='error'
    final_error=None
    try:
        with jobs._STATE.rules_lock:
            jobs._invalidate_rule_caches()
            _ready(package)
            root=jobs._STATE.upload_dir/run['jid'];root.mkdir(parents=True,exist_ok=False)
            paths={}
            for source in package['source_refs']:
                if source['role']=='reference':continue
                target=root/(source['role']+Path(source['name']).suffix.lower())
                target.write_bytes(Path(source['file_ref']).read_bytes());paths[source['role']]=str(target)
            selection=TemplateSelection(**package['selection']);p=package['normalized_parameters'];model=package['model_selection']
            options={k:p[k] for k in ('development_process','product_series','organization_scope','cover_phase')}
            options.update(model_provider=model.get('provider',''),model_name=model.get('name',''),model_id=model.get('id',''))
            jobs._register_job(run['jid'],selection=selection,**options)
            jobs._STATE.jobs[run['jid']]['result']['meta'].update(rd_project=run['project_id'],rd_task=run['task_id'],rd_baseline_id=package['baseline_id'],native_run_id=run_id,input_package_id=package['id'],original_filenames={s['role']:s['name'] for s in package['source_refs']})
            with store._transaction() as conn:
                current=_row(conn,run_id)
                if current.get('cancel_requested'):
                    jobs._STATE.jobs[run['jid']]['cancel_requested']=True
                else:current['status']='running'
                _write(conn,current)
            jobs._run_job(run['jid'],paths['tech'],paths['spec'],selection,jobs._make_output_path(),p['use_llm'],
                          template_edit_plan=p.get('template_edit_plan'),template_edit_confirmed=bool(p.get('template_edit_plan')),
                          baseline_docx=paths.get('baseline_docx'),baseline_json=paths.get('baseline_json'),fail_on_regression=p['fail_on_regression'],
                          indicator_clarifications=run.get('answers') or None,**options)
            final_status=(jobs._get_job(run['jid']) or {}).get('status','error')
            try:inputs.verify_package(package)
            except RdError:final_status='environment_drift'
    except RdError as exc:
        final_status='environment_drift' if any(word in exc.detail for word in ('环境','校验','配置已变化','固定输入文件')) else 'error'
        final_error=exc.detail
    except Exception:
        # The old engine logs its detailed diagnostics; persistent native API is
        # deliberately free of local paths, remote addresses and credentials.
        final_status='error'
    finally:
        with store._transaction() as conn:
            current=_row(conn,run_id)
            if current.get('cancel_requested') or current['status']=='cancelled':final_status='cancelled'
            current.update(status=final_status,finished_at=_now(),result_ref={'jid':run['jid']})
            if final_status=='error':current['error']=final_error or '运行未完成，请查看受控运行诊断并明确重试'
            if final_status=='environment_drift':current['error']='运行环境或固定文件发生漂移，该产物不能采用或送审'
            _write(conn,current)

def cancel_taskbook_run(store,pid,tid,actor,run_id,expected_version,key):
    actor=_actor(actor);fp=inputs.digest(run_id.encode())
    with store._transaction() as conn:
        doc,_,_=inputs.task_context(store,conn,pid,tid,actor,write=True)
        replay=store._replay(conn,tid+':cancel',actor['user_id'],key,fp)
        if replay:return replay
        store._version(doc,expected_version);run=_row(conn,run_id)
        if (run['project_id'],run['task_id'])!=(pid,tid):raise RdError(404,'本任务的运行不存在')
        if run['status'] not in TERMINAL:run.update(cancel_requested=True,status='cancelled',finished_at=_now())
        _write(conn,run);store._save(conn,doc,'cancel_taskbook_run',actor['user_id'],{'task_id':tid,'run_id':run_id})
        result={'run':inputs.public_value(run),'project_version':doc['project']['version']}
        store._remember(conn,tid+':cancel',actor['user_id'],key,fp,result)
    from src.controller import taskbook_controller as jobs
    job=jobs._get_job(run['jid'])
    if job and run.get('cancel_requested'):job['cancel_requested']=True
    return result

def reconcile_taskbook_runs(store,*,dispatch_intents=True):
    """Call after original manifests restore, once at process startup."""
    from src.controller import taskbook_controller as jobs
    intents=[];counts={'recovered':0,'interrupted':0,'intents':0}
    with store._transaction() as conn:
        for row in conn.execute('SELECT document FROM taskbook_runs').fetchall():
            run=json.loads(row[0])
            if run['status'] in TERMINAL:continue
            if run['status']=='intent':intents.append(run['run_id']);counts['intents']+=1;continue
            job=jobs._get_job(run['jid'])
            trusted=_trusted_terminal(jobs,run,job)
            if trusted:
                run.update(status=job['status'],finished_at=_now(),result_ref={'jid':run['jid']});counts['recovered']+=1
                # Validate exact output hashes, then reject obsolete runtime.
                try:
                    doc=store._load(conn,run['project_id'],run['actor_id'])
                    inputs.verify_package(inputs.package_from_doc(doc,run['task_id'],run['package_id']))
                except RdError:run['status']='environment_drift'
            else:
                run.update(status='interrupted',finished_at=_now(),error='服务重启后无法证明运行终态，请使用新的请求键明确重试');counts['interrupted']+=1
            _write(conn,run)
    if dispatch_intents:
        for run_id in intents:threading.Thread(target=dispatch_taskbook_run,args=(store,run_id),daemon=True).start()
    return counts


def _trusted_terminal(jobs,run,job):
    if not job or not job.get('restored_from_manifest') or job.get('status') not in {'done','blocked','error','cancelled'}:
        return False
    if job['status'] in {'error','cancelled'}:return True
    path=jobs._job_artifact(run['jid'],'docx')
    if not path or not job.get('artifact_sha256'):return False
    try:
        if inputs.digest(path.read_bytes())!=job['artifact_sha256']:return False
        for suffix,expected in job.get('sidecar_sha256',{}).items():
            if not isinstance(suffix,str) or '/' in suffix or '\\' in suffix or not suffix.startswith('.'):
                return False
            if inputs.digest(path.with_suffix(suffix).read_bytes())!=expected:return False
    except (OSError,ValueError):return False
    return True
