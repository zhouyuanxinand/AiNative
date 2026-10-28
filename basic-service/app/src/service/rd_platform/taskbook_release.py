"""Atomic native review submission and immutable design input releases."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from .store import RdError, RdStore, _id, _now, _actor, _json, _text
from .taskbook_models import work_unit, native_validity, usable_run
from .taskbook_planning import current_wbs, validate_wbs


def validate_coverage(doc,w,coverage_id=None):
    matches=[c for c in doc['taskbook_coverages'] if c['task_id']==w['task_id'] and c['revision_id']==w.get('selected_revision_id') and c['package_id']==w.get('input_package_id') and c['document_sha256']==w.get('selected_document_sha256') and (not coverage_id or c['id']==coverage_id)]
    coverage=matches[-1] if matches else None
    if not coverage or coverage.get('run_id') != w.get('selected_run_id') or coverage.get('blocking_count') != 0:
        raise RdError(409,'当前修订须完成无阻断的十五类内容核验')
    findings=coverage.get('findings',[])
    if len({f.get('section_key') for f in findings}) != 15 or any(f.get('status') not in {'evidenced','not_applicable'} or not f.get('checked_by') or not f.get('evidence_ref') for f in findings):
        raise RdError(409,'内容核验必须有十五类已确认依据或批准的不适用')
    return coverage


def validate_review_snapshot(doc,review):
    task=RdStore._find(doc,'tasks',review['task_id']);native_validity(doc,task)
    snapshot=review.get('taskbook_snapshot')
    if not snapshot:raise RdError(409,'任务书须通过固定包审签入口送审')
    artifact=RdStore._find(doc,'artifacts',review['artifact_id'])
    w=work_unit(doc,task['id'])
    if (snapshot['document_sha256'] != artifact['sha256'] or snapshot['revision_id'] != artifact['source_revision_id']
            or snapshot['package_id'] != w['input_package_id'] or snapshot['revision_id'] != w['selected_revision_id']
            or snapshot['wbs']['id'] != w['wbs_draft_id']):raise RdError(409,'送审固定包与当前采用版本不一致')
    validate_wbs(doc,snapshot['wbs']['items'])
    return snapshot


def submit_taskbook_review(store,pid,tid,actor,payload,expected_version,key):
    """artifact_payload is computed by the trusted exact-revision adapter."""
    actor=_actor(actor);uid=actor['user_id']
    intent={k:payload.get(k) for k in ('run_id','revision_id','coverage_id','wbs_revision')}
    fp=_json({'action':'submit_taskbook_review','task_id':tid,**intent,'expected_version':expected_version})
    with store._transaction() as conn:
        doc=store._load(conn,pid,uid);store._permission(doc,uid,'register_artifact')
        replay=store._replay(conn,pid,uid,key,fp)
        if replay is not None:return replay
        store._version(doc,expected_version);task=store._find(doc,'tasks',tid);store._assignee(doc,task,uid)
        w=work_unit(doc,tid)
        if w['current_stage']!='ND15' or task['status'] not in {'in_progress','changes_requested'}:raise RdError(409,'须完成ND14并在ND15送审')
        if intent['run_id']!=w['selected_run_id'] or intent['revision_id']!=w['selected_revision_id']:raise RdError(409,'送审必须使用当前采用的运行和修订')
        latest_review=next((r for r in reversed(doc['reviews']) if r['task_id']==tid),None)
        if latest_review and latest_review['status']=='rejected' and latest_review.get('taskbook_snapshot',{}).get('revision_id')==intent['revision_id']:
            raise RdError(409,'退回后须形成新修订并重新核验，不得重复提交原退回稿')
        row=conn.execute('SELECT document FROM taskbook_runs WHERE run_id=? AND project_id=? AND task_id=?',(intent['run_id'],pid,tid)).fetchone()
        run=json.loads(row[0]) if row else None
        if not run or run['package_id']!=w['input_package_id'] or not usable_run(run):raise RdError(409,'运行未完成、已取消或输入已变化')
        coverage=validate_coverage(doc,w,intent['coverage_id']);draft=current_wbs(doc,w);validate_wbs(doc,draft['items'])
        if type(intent['wbs_revision']) is not int or intent['wbs_revision']!=draft['revision'] or draft['source_revision_id']!=intent['revision_id'] or draft['status']!='verified':raise RdError(409,'WBS版本须核对当前采用修订')
        package=store._find(doc,'taskbook_input_packages',w['input_package_id'])
        source=payload.get('artifact_payload')
        if not isinstance(source,dict):raise RdError(422,'缺少服务端固定成果快照')
        values={k:_text(source.get(k),k,maximum=4000) for k in ('jid','source_revision_id','filename','sha256','file_ref','quality_status')}
        if values['jid']!=run['jid'] or values['source_revision_id']!=intent['revision_id'] or values['sha256']!=w['selected_document_sha256']:raise RdError(409,'固定成果必须对应采用修订的精确哈希')
        binding=next((b for b in doc['generations'] if b['jid']==run['jid']),None)
        if not binding or binding['actor_id']!=uid or binding['task_id']!=tid:raise RdError(409,'成果必须属于本任务当前执行人')
        if Path(values['filename']).name!=values['filename'] or any(c in values['filename'] for c in ('/','\\')):raise RdError(422,'成果文件名不正确')
        values['quality_evidence']=copy.deepcopy(source.get('quality_evidence',{}));store._verify_file(values);store._verify_quality(values)
        artifact={'id':_id(),'task_id':tid,'baseline_id':task['baseline_id'],**values,'author_id':uid,'status':'draft','created_at':_now()}
        doc['artifacts'].append(artifact)
        snapshot={'run_id':run['run_id'],'revision_id':intent['revision_id'],'document_sha256':values['sha256'],'package_id':package['id'],'package':copy.deepcopy(package),'coverage_id':coverage['id'],'coverage':copy.deepcopy(coverage),'wbs_revision':draft['revision'],'wbs':copy.deepcopy(draft),'quality_evidence':copy.deepcopy(values['quality_evidence'])}
        store._submit(doc,task,uid,artifact['id'],native_snapshot=snapshot)
        store._save(conn,doc,'submit_taskbook_review',uid,{'task_id':tid,'artifact_id':artifact['id'],'review_id':doc['reviews'][-1]['id'],'request_key':key})
        result=store._view(doc,uid);store._remember(conn,pid,uid,key,fp,result);return result


def freeze_taskbook_release(doc,review):
    existing=next((r for r in doc['taskbook_releases'] if review['id'] in r['review_ids']),None)
    if existing:return existing
    snapshot=validate_review_snapshot(doc,review)
    task=RdStore._find(doc,'tasks',review['task_id']);w=work_unit(doc,task['id'])
    previous=[r for r in doc['taskbook_releases'] if r['task_id']==task['id']]
    release={'id':_id(),'task_id':task['id'],'version':len(previous)+1,'artifact_id':review['artifact_id'],'revision_id':snapshot['revision_id'],'sha256':snapshot['document_sha256'],'package_id':snapshot['package_id'],'coverage_id':snapshot['coverage_id'],'wbs_revision':snapshot['wbs_revision'],'wbs':copy.deepcopy(snapshot['wbs']),'review_ids':[review['id']],'source_refs':copy.deepcopy(snapshot['package'].get('source_refs',[])),'requirement_ids':list(dict.fromkeys(r for item in snapshot['wbs']['items'] for r in item['requirement_ids'])),'created_at':_now(),'approved_by':review['decided_by'],'supersedes_release_id':previous[-1]['id'] if previous else None}
    if previous:
        old={i['id']:i for i in previous[-1]['wbs']['items']};new={i['id']:i for i in snapshot['wbs']['items']}
        release['differences']={'document_changed':previous[-1]['sha256']!=release['sha256'],'package_changed':previous[-1]['package_id']!=release['package_id'],'added_items':sorted(new.keys()-old.keys()),'removed_items':sorted(old.keys()-new.keys()),'changed_items':sorted(i for i in old.keys() & new.keys() if old[i]!=new[i])}
    doc['taskbook_releases'].append(release);w['release_id']=release['id']
    for stage in w['stages']:
        if stage['node_code']=='ND15':stage.update(status='completed',completed_at=_now())
    return release
