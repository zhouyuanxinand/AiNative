"""Versioned WBS candidates; saving never creates execution tasks."""
import copy
from datetime import date
from .store import RdError, RdStore, _id, _now, _text
from .taskbook_models import work_unit


def current_wbs(doc,w):
    row=next((d for d in reversed(doc['taskbook_wbs_drafts']) if d['id']==w.get('wbs_draft_id')),None)
    if not row: raise RdError(409,'请先保存WBS与验证策划草案')
    return row


def validate_wbs(doc,items):
    if not isinstance(items,list) or not items or len(items)>500:
        raise RdError(422,'WBS须包含1至500个条目')
    ids=[]
    for item in items:
        if not isinstance(item,dict): raise RdError(422,'WBS条目须为对象')
        for field in ('id','title','deliverable','acceptance','acceptance_owner_id','verification_method','output_anchor'):
            _text(item.get(field),field)
        if item.get('kind') not in ('work','design','verification'): raise RdError(422,'WBS类型不正确')
        RdStore.__new__(RdStore)._assignments(doc,item.get('assignee_id'),item.get('reviewer_id'))
        if not RdStore._member(doc,item['acceptance_owner_id']): raise RdError(422,'接受责任人必须为项目成员')
        refs=item.get('requirement_ids')
        if not isinstance(refs,list) or not refs or any(not isinstance(r,str) or r not in {r['id'] for r in doc['requirements']} for r in refs):
            raise RdError(422,'每个WBS须追溯本项目确认要求')
        deps=item.get('predecessor_ids')
        if not isinstance(deps,list) or any(not isinstance(r,str) for r in deps): raise RdError(422,'WBS前置须为条目ID数组')
        for key in ('planned_start','planned_end'):
            if item.get(key):
                try: date.fromisoformat(item[key])
                except (TypeError,ValueError): raise RdError(422,'计划日期须为YYYY-MM-DD') from None
        if item.get('planned_start') and item.get('planned_end') and item['planned_start']>item['planned_end']: raise RdError(422,'结束日期不得早于开始日期')
        ids.append(item['id'])
    if len(ids)!=len(set(ids)): raise RdError(422,'WBS条目ID不能重复')
    graph={i['id']:i['predecessor_ids'] for i in items}; visiting=set(); done=set()
    def visit(i):
        if i in visiting: raise RdError(422,'WBS前置依赖不能成环')
        if i in done:return
        if i not in graph:raise RdError(422,'WBS前置条目不存在')
        visiting.add(i)
        for dep in graph[i]:visit(dep)
        visiting.remove(i);done.add(i)
    for i in ids:visit(i)


def save_wbs(doc,actor,p):
    store=RdStore.__new__(RdStore);task=store._find(doc,'tasks',p.get('task_id'));store._assignee(doc,task,actor['user_id'])
    w=work_unit(doc,task['id'])
    if task['status'] not in {'in_progress','changes_requested'} or w['current_stage'] not in {'ND14','ND15'}:
        raise RdError(409,'当前节点或审签状态不能修改WBS')
    latest=next((d for d in reversed(doc['taskbook_wbs_drafts']) if d['task_id']==task['id']),None)
    revision=latest['revision'] if latest else 0
    if type(p.get('expected_wbs_revision')) is not int:raise RdError(422,'expected_wbs_revision须为整数')
    if p['expected_wbs_revision'] != revision:raise RdError(409,'WBS已被其他操作更新，请比较后保存')
    if not w.get('selected_revision_id') or p.get('source_revision_id') != w['selected_revision_id']:raise RdError(409,'WBS必须核对当前采用修订')
    validate_wbs(doc,p.get('items'))
    package=store._find(doc,'taskbook_input_packages',w['input_package_id'])
    adoption=store._find(doc,'development_adoptions',w['adoption_id'])
    allowed=set(package.get('requirement_ids',adoption.get('requirement_ids',[])))
    if any(ref not in allowed for item in p['items'] for ref in item['requirement_ids']):raise RdError(422,'WBS只能引用固定输入包采用范围内的要求')
    draft={'id':_id(),'task_id':task['id'],'revision':revision+1,'source_revision_id':p['source_revision_id'],'items':copy.deepcopy(p['items']),'status':'verified','created_by':actor['user_id'],'created_at':_now()}
    doc['taskbook_wbs_drafts'].append(draft);w['wbs_draft_id']=draft['id']
