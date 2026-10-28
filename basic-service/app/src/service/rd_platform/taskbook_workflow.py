"""BP05 transitions run inside the existing project transaction."""
from __future__ import annotations
import copy
import json
from datetime import date
from .taskbook_models import normalize, work_unit, native_validity, usable_run
from .store import RdError, RdStore, _id, _now, _text, _actor, _json


def apply_taskbook_command(doc, actor, action, payload):
    normalize(doc)
    uid, p = actor['user_id'], payload
    store = RdStore.__new__(RdStore)
    if action == 'adopt_development':
        if p.get('route') not in ('new','modified','direct') or p.get('provenance') not in ('manual','mock'):
            raise RdError(422,'路线或证据来源不正确')
        baseline = doc['project']['current_baseline_id']
        if not baseline:
            raise RdError(409,'请先确认需求基线')
        from .journey import require_development_route
        require_development_route(doc, p['route'])
        template = p.get('process_template_ref')
        if not isinstance(template,dict) or set(template) != {'id','version'}:
            raise RdError(422,'须采用固定流程模板及版本')
        template = {k:_text(template.get(k),'流程模板版本') for k in ('id','version')}
        confirmed=store._find(doc,'baselines',baseline)
        confirmed_ids={r['id'] for r in confirmed['requirements']}
        refs = p.get('requirement_ids',[r['id'] for r in confirmed['requirements']])
        if not isinstance(refs,list) or not refs or any(not isinstance(r,str) or r not in confirmed_ids for r in refs):
            raise RdError(422,'采用需求必须属于当前已确认需求基线')
        doc['development_adoptions'].append({'id':_id(),'route':p['route'],'approval_ref':_text(p.get('approval_ref'),'批准依据'),'scope':_text(p.get('scope'),'批准范围'),'requirements_baseline_id':baseline,'process_template_ref':template,'provenance':p['provenance'],'requirement_ids':list(dict.fromkeys(refs)),'created_by':uid,'created_at':_now()})
        doc['development_adoptions'][-1]['requirement_scope']='selected' if 'requirement_ids' in p else 'all'
    elif action == 'create_taskbook':
        adoption = store._find(doc,'development_adoptions',p.get('adoption_id'))
        if adoption['route'] == 'direct':
            raise RdError(409,'直接选用路线无需创建研制任务书')
        from .journey import require_development_route
        require_development_route(doc, adoption['route'])
        if adoption['requirements_baseline_id'] != doc['project']['current_baseline_id']:
            raise RdError(409,'准入依据须采用当前确认需求')
        store._assignments(doc,p.get('assignee_id'),p.get('reviewer_id'))
        due = p.get('due_date') or None
        if due:
            try: date.fromisoformat(due)
            except (TypeError,ValueError): raise RdError(422,'计划日期须为YYYY-MM-DD') from None
        tid = _id()
        task = {'id':tid,'kind':'taskbook','title':_text(p.get('title'),'任务名称',maximum=1000),'description':_text(p.get('description',''),'任务说明',required=False),'assignee_id':p['assignee_id'],'reviewer_id':p['reviewer_id'],'due_date':due,'baseline_id':adoption['requirements_baseline_id'],'status':'todo','created_at':_now()}
        doc['tasks'].append(task)
        doc['taskbook_work_units'].append({'id':_id(),'task_id':tid,'process_code':'BP05','adoption_id':adoption['id'],'current_stage':'ND13','stages':[{'instance_id':_id(),'node_code':code,'label':label,'status':'ready' if code == 'ND13' else 'pending','assignee_id':p['assignee_id'],'reviewer_id':p['reviewer_id'],'started_at':None,'completed_at':None} for code,label in [('ND13','研制范围与任务书编制'),('ND14','WBS与验证责任拆解'),('ND15','输入评审与要求冻结')]],'input_package_id':None,'selected_run_id':None,'selected_revision_id':None,'wbs_draft_id':None,'release_id':None})
    elif action == 'advance_taskbook_stage':
        task = store._find(doc,'tasks',p.get('task_id')); store._assignee(doc,task,uid)
        w = work_unit(doc,task['id']); target = p.get('target_stage')
        if task['status'] == 'in_review' or task['status'] == 'done':
            raise RdError(409,'当前审签或已批准工作包不能推进')
        if target == 'ND13' and w['current_stage'] in {'ND14','ND15'}:
            pass
        elif w['current_stage'] == 'ND13' and target == 'ND14':
            if not w.get('selected_revision_id') or not w.get('input_package_id'):
                raise RdError(409,'须先采用固定输入和工作稿')
            from .taskbook_release import validate_coverage
            validate_coverage(doc,w)
        elif w['current_stage'] == 'ND14' and target == 'ND15':
            from .taskbook_planning import current_wbs, validate_wbs
            draft = current_wbs(doc,w); validate_wbs(doc,draft['items'])
            if draft['source_revision_id'] != w['selected_revision_id']:
                raise RdError(409,'WBS须核对当前采用稿')
        else:
            raise RdError(409,'节点只能依次办理')
        for stage in w['stages']:
            if target=='ND13' and stage['node_code']!='ND13':
                stage.update(status='pending',completed_at=None)
            elif stage['node_code'] == w['current_stage']:
                stage.update(status='completed',completed_at=_now())
            if stage['node_code'] == target:
                stage.update(status='in_progress',started_at=_now(),completed_at=None)
        w['current_stage'] = target
        task['status'] = 'in_progress'
    elif action == 'save_wbs':
        from .taskbook_planning import save_wbs
        save_wbs(doc,actor,p)
    elif action in {'publish_plan','accept_handoff'}:
        from .plan_handoff import apply_handoff_command
        apply_handoff_command(doc,actor,action,p)
    elif action == 'resolve_change_impact':
        from .taskbook_changes import resolve_change_impact
        resolve_change_impact(doc,actor,p)
    elif action == 'reopen_taskbook':
        task=store._find(doc,'tasks',p.get('task_id'));w=work_unit(doc,task['id'])
        if task['status']!='done':raise RdError(409,'只有已批准任务书可以发起新版编制')
        _text(p.get('reason'),'新版编制依据')
        native_validity(doc,task)
        task['status']='in_progress';w['current_stage']='ND13'
        task.pop('actual_end',None)
        for stage in w['stages']:stage.update(status='in_progress' if stage['node_code']=='ND13' else 'pending',completed_at=None)


def build_taskbook_workspace(doc, task_id, actor_id):
    normalize(doc)
    task = RdStore._find(doc,'tasks',task_id); w = work_unit(doc,task_id)
    public = RdStore._view(doc,actor_id)
    result = {key:public[key] for key in ('project','members','baselines','current_user_id')}
    blockers = []
    try: native_validity(doc,task)
    except RdError as exc: blockers.append(exc.detail)
    if not w.get('input_package_id'): blockers.append('尚未确认固定输入包')
    if not w.get('selected_revision_id'): blockers.append('尚未采用工作稿')
    actions = []
    if actor_id == task['assignee_id'] and not any(i['status']=='pending' and i['task_id']==task_id for i in doc['change_impacts']):
        if task['status'] in {'todo','changes_requested'}: actions.append('start_task')
        if task['status'] in {'in_progress','changes_requested'}: actions += ['create_input_package','start_run','select_revision','save_wbs','advance_taskbook_stage','submit_review']
    if actor_id == task['reviewer_id'] and task['status']=='in_review': actions += ['approve','reject']
    if actor_id == doc['project']['owner_id']:
        actions += ['publish_plan','resolve_change_impact']
        if task['status']=='done':actions.append('reopen_taskbook')
    if any(h['assignee_id']==actor_id and h['status']=='pending' for h in doc['handoffs']): actions.append('accept_handoff')
    result.update(task=copy.deepcopy(task),work_unit=copy.deepcopy(w),sources=public['project_sources'],adoptions=public['development_adoptions'],packages=[p for p in public['taskbook_input_packages'] if p['task_id']==task_id],coverages=[c for c in public['taskbook_coverages'] if c['task_id']==task_id],wbs=next((d for d in reversed(public['taskbook_wbs_drafts']) if d['task_id']==task_id),None),releases=[r for r in public['taskbook_releases'] if r['task_id']==task_id],plan_releases=[r for r in public['plan_releases'] if r['task_id']==task_id],handoffs=[h for h in public['handoffs'] if h['source_task_id']==task_id],change_impacts=[i for i in public['change_impacts'] if i['task_id']==task_id],artifacts=[a for a in public['artifacts'] if a['task_id']==task_id],reviews=[r for r in public['reviews'] if r['task_id']==task_id],allowed_actions=actions,blockers=blockers)
    result['plan']=public['project_plan']
    return result


def select_taskbook_revision(store,pid,tid,actor,run_id,revision_id,expected_version,key,*,revision):
    actor = _actor(actor); uid = actor['user_id']
    fp = _json({'action':'select_taskbook_revision','task_id':tid,'run_id':run_id,'revision_id':revision_id,'expected_version':expected_version})
    with store._transaction() as conn:
        doc=store._load(conn,pid,uid)
        replay=store._replay(conn,pid,uid,key,fp)
        if replay is not None: return replay
        store._version(doc,expected_version)
        task=store._find(doc,'tasks',tid); store._permission(doc,uid,'bind_generation'); store._assignee(doc,task,uid)
        if task['status'] not in {'in_progress','changes_requested'}: raise RdError(409,'当前任务不能采用工作稿')
        w=work_unit(doc,tid)
        row=conn.execute('SELECT document FROM taskbook_runs WHERE run_id=? AND project_id=? AND task_id=?',(run_id,pid,tid)).fetchone()
        run=json.loads(row[0]) if row else None
        if not run or run['package_id'] != w['input_package_id'] or not usable_run(run):
            raise RdError(409,'只能采用本任务当前输入的有效完成稿')
        binding=next((b for b in doc['generations'] if b['jid']==run['jid']),None)
        if not binding or binding['actor_id'] != uid or revision.get('id') != revision_id or not revision.get('sha256'):
            raise RdError(409,'工作稿归属或修订不一致')
        w.update(selected_run_id=run_id,selected_revision_id=revision_id,selected_document_sha256=revision['sha256'])
        for draft in doc['taskbook_wbs_drafts']:
            if draft['task_id']==tid and draft['source_revision_id'] != revision_id: draft['status']='needs_revalidation'
        store._save(conn,doc,'select_taskbook_revision',uid,{'task_id':tid,'run_id':run_id,'revision_id':revision_id})
        result={'work_unit':copy.deepcopy(w),'project_version':doc['project']['version']}
        store._remember(conn,pid,uid,key,fp,result)
        return result
