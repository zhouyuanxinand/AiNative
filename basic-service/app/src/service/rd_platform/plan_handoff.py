"""Explicit plan publication and independently accepted downstream inputs."""
import copy
from .store import RdStore, RdError, _id, _now
from .taskbook_models import native_validity, normalize


def apply_handoff_command(doc,actor,action,p):
    store=RdStore.__new__(RdStore);uid=actor['user_id']
    if action=='publish_plan':
        release=store._find(doc,'taskbook_releases',p.get('release_id'))
        task=store._find(doc,'tasks',p.get('task_id'));native_validity(doc,task)
        if release['task_id']!=task['id']:raise RdError(409,'发布包不属于当前任务')
        if task['status']!='done':raise RdError(409,'任务书正在修订或复核，暂不能发布计划')
        if not any(r['id'] in release['review_ids'] and r['status']=='approved' for r in doc['reviews']):raise RdError(409,'发布计划必须引用已批准任务书')
        if any(r['release_id']==release['id'] for r in doc['plan_releases']):return
        from .taskbook_models import work_unit
        if work_unit(doc,task['id'])['release_id']!=release['id']:raise RdError(409,'只能发布当前最新批准包')
        prior=[r for r in doc['plan_releases'] if r['task_id']==task['id']]
        if prior:
            old_release=store._find(doc,'taskbook_releases',prior[-1]['release_id'])
            if release['version']<=old_release['version']:raise RdError(409,'不能将计划回退至旧发布包')
        plan={'id':_id(),'task_id':task['id'],'release_id':release['id'],'plan_version':len(prior)+1,'item_task_map':{},'published_by':uid,'published_at':_now(),'source_refs':copy.deepcopy(release['source_refs'])}
        existing_map={item:tid for previous in prior for item,tid in previous['item_task_map'].items()}
        for item in release['wbs']['items']:
            store._assignments(doc,item['assignee_id'],item['reviewer_id'])
            child=next((t for t in doc['tasks'] if t['id']==existing_map.get(item['id'])),None)
            if child is None:
                child={'id':_id(),'kind':'plan_item','item_kind':item['kind'],'title':item['title'],'description':item['deliverable'],'assignee_id':item['assignee_id'],'reviewer_id':item['reviewer_id'],'due_date':item.get('planned_end'),'baseline_id':task['baseline_id'],'status':'todo','created_at':_now(),'source_task_id':task['id'],'source_item_id':item['id'],'source_release_id':release['id'],'source_revision_id':release['revision_id'],'source_sha256':release['sha256'],'requirement_ids':copy.deepcopy(item['requirement_ids']),'acceptance':item['acceptance'],'verification_method':item['verification_method'],'acceptance_owner_id':item['acceptance_owner_id'],'planned_start':item.get('planned_start'),'planned_end':item.get('planned_end')}
                doc['tasks'].append(child)
            else:
                if child['status']!='needs_revalidation':child['previous_status']=child['status']
                child['status']='needs_revalidation'
            plan['item_task_map'][item['id']]=child['id']
            for old in doc['handoffs']:
                if old['task_id']==child['id'] and old['status']=='pending':old['status']='superseded'
            handoff={'id':_id(),'source_task_id':task['id'],'task_id':child['id'],'release_id':release['id'],'plan_release_id':plan['id'],'plan_version':plan['plan_version'],'item_id':item['id'],'item':copy.deepcopy(item),'input_kind':'verification_input' if item['kind']=='verification' else 'design_input' if item['kind']=='design' else 'work_input','source_revision_id':release['revision_id'],'source_sha256':release['sha256'],'source_refs':copy.deepcopy(release['source_refs']),'requirement_ids':copy.deepcopy(item['requirement_ids']),'assignee_id':item['assignee_id'],'status':'pending','created_at':_now(),'accepted_by':None,'accepted_at':None}
            handoff['reviewer_id']=item['reviewer_id']
            handoff['assignment_basis']={key:child[key] for key in ('assignee_id','reviewer_id')}
            doc['handoffs'].append(handoff);child['required_handoff_id']=handoff['id']
        for item,tid in plan['item_task_map'].items():
            child=store._find(doc,'tasks',tid)
            if not child.get('actual_start'):child['predecessor_task_ids']=[plan['item_task_map'][i] for i in next(x for x in release['wbs']['items'] if x['id']==item)['predecessor_ids']]
        doc['plan_releases'].append(plan)
    else:
        handoff=store._find(doc,'handoffs',p.get('handoff_id'))
        task=store._find(doc,'tasks',handoff['task_id'])
        member=store._member(doc,uid)
        if uid!=handoff['assignee_id'] or not member or member['role'] not in {'owner','engineer'}:raise RdError(403,'只有当前指定接收人可以接受交接')
        if handoff['status']=='accepted':
            if task.get('required_handoff_id')!=handoff['id'] or task['assignee_id']!=uid:
                raise RdError(403,'任务分派已经变化，此回执不再是当前接收凭据')
            return
        basis=handoff.get('assignment_basis',{'assignee_id':handoff['assignee_id'],'reviewer_id':handoff['item']['reviewer_id']})
        if any(task[key]!=basis[key] for key in ('assignee_id','reviewer_id')):
            raise RdError(403,'任务分派已经变化，此交接不再具备接收权限')
        if handoff['status']!='pending' or task.get('required_handoff_id')!=handoff['id']:raise RdError(409,'交接已被新版本替代')
        native_validity(doc,task)
        source=store._find(doc,'tasks',handoff['source_task_id']);native_validity(doc,source)
        item=handoff['item'];reviewer=handoff.get('reviewer_id',item['reviewer_id']);store._assignments(doc,handoff['assignee_id'],reviewer)
        handoff.update(status='accepted',accepted_by=uid,accepted_at=_now())
        task.update(assignee_id=handoff['assignee_id'],reviewer_id=reviewer,source_release_id=handoff['release_id'],source_revision_id=handoff['source_revision_id'],source_sha256=handoff['source_sha256'],requirement_ids=copy.deepcopy(handoff['requirement_ids']),accepted_handoff_id=handoff['id'])
        task.update(title=item['title'],description=item['deliverable'],acceptance=item['acceptance'],verification_method=item['verification_method'],acceptance_owner_id=item['acceptance_owner_id'],item_kind=item['kind'])
        if task['status']=='needs_revalidation':task['status']=task.pop('previous_status','todo')
        # A new acceptance changes the applicable input; it does not rewrite
        # actual dates or the existing published schedule of an in-flight task.
        if not task.get('actual_start'):
            task.update(title=item['title'],description=item['deliverable'],planned_start=item.get('planned_start'),planned_end=item.get('planned_end'),due_date=item.get('planned_end'))


def require_handoff(doc,task):
    handoff=next((h for h in doc['handoffs'] if h['id']==task.get('required_handoff_id')),None)
    if not handoff or handoff['status']!='accepted' or task.get('accepted_handoff_id')!=handoff['id'] or handoff.get('accepted_by')!=task['assignee_id']:raise RdError(409,'须由当前执行人接受当前版本交接后才可办理')
    for dep in task.get('predecessor_task_ids',[]):
        predecessor=RdStore._find(doc,'tasks',dep)
        if predecessor['status']!='done':raise RdError(409,'前置任务尚未完成')


def reassign_handoff(doc,task,assignee_id,reviewer_id):
    """A changed assignment requires a fresh receipt; keep prior facts intact."""
    original=next((h for h in doc['handoffs'] if h['id']==task.get('required_handoff_id')),None)
    if original is None:return
    if original['status']=='pending':original['status']='superseded'
    replacement=copy.deepcopy(original)
    replacement.update(id=_id(),assignee_id=assignee_id,reviewer_id=reviewer_id,status='pending',created_at=_now(),accepted_by=None,accepted_at=None,reassigned_from_handoff_id=original['id'],assignment_basis={'assignee_id':assignee_id,'reviewer_id':reviewer_id})
    doc['handoffs'].append(replacement)
    task['required_handoff_id']=replacement['id']
    task.pop('accepted_handoff_id',None)


def build_project_plan(doc):
    normalize(doc)
    return {'versions':copy.deepcopy(doc['plan_releases']),'items':[{k:copy.deepcopy(t.get(k)) for k in ('id','title','status','assignee_id','reviewer_id','source_task_id','source_item_id','source_release_id','source_revision_id','requirement_ids','planned_start','planned_end','actual_start','actual_end','predecessor_task_ids','required_handoff_id','accepted_handoff_id')} for t in doc['tasks'] if t.get('kind')=='plan_item'],'work_units':copy.deepcopy(doc['taskbook_work_units'])}
