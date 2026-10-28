"""Dependency-specific impact records, never edits to approved history."""
import copy
from .store import RdStore, RdError, _id, _now, _text
from .taskbook_models import normalize, work_unit


def assess_taskbook_impact(doc,changed_refs):
    normalize(doc);created=[]
    for w in doc['taskbook_work_units']:
        adoption=RdStore._find(doc,'development_adoptions',w['adoption_id'])
        package=next((p for p in doc['taskbook_input_packages'] if p['id']==w.get('input_package_id')),None)
        active_release_ids={h['release_id'] for h in doc['handoffs'] if h['source_task_id']==w['task_id'] and h['status'] in {'accepted','pending'}}
        releases=[r for r in doc['taskbook_releases'] if r['id'] in active_release_ids]
        packages=[p for p in doc['taskbook_input_packages'] if p['id'] in {r['package_id'] for r in releases} or package and p['id']==package['id']]
        requirements=adoption.get('requirement_ids')
        if requirements is not None:requirements=set(requirements) | {rid for release in releases for rid in release.get('requirement_ids',[])}
        relevant=[]
        for ref in changed_refs:
            kind=ref.get('kind')
            if kind=='requirement':
                if requirements is None or ref.get('requirement_id') in requirements or (adoption.get('requirement_scope','all')=='all' and ref.get('old_revision') is None):relevant.append(ref)
            elif kind=='source' and (package or releases):
                sources=[s for p in packages for s in p.get('source_refs',[])] + [s for r in releases for s in r.get('source_refs',[])]
                if any('source_refs' not in p for p in packages):relevant.append(ref)
                elif any(s.get('source_id',s.get('id'))==ref.get('source_id') and s.get('version')!=ref.get('version') for s in sources):relevant.append(ref)
            elif kind in {'template','profile','mapping'} and packages:
                for candidate in packages:
                    adopted=candidate.get(kind+'_ref')
                    if adopted and (not ref.get('id') or adopted.get('id')==ref.get('id')) and adopted.get('version')!=ref.get('version'):
                        relevant.append(ref);break
            elif kind=='unknown':relevant.append(ref)
        if not relevant:continue
        duplicate=next((i for i in doc['change_impacts'] if i['task_id']==w['task_id'] and i['changed_refs']==relevant),None)
        if duplicate:continue
        downstream=[t['id'] for t in doc['tasks'] if t.get('source_task_id')==w['task_id']]
        impact={'id':_id(),'task_id':w['task_id'],'package_id':w.get('input_package_id'),'release_id':w.get('release_id'),'changed_refs':copy.deepcopy(relevant),'downstream_task_ids':downstream,'status':'pending','created_at':_now(),'resolution':None}
        doc['change_impacts'].append(impact);created.append(impact)
        for tid in [w['task_id'],*downstream]:
            task=RdStore._find(doc,'tasks',tid)
            if task['status']!='needs_revalidation':task['previous_status']=task['status']
            RdStore._cancel_reviews(doc,task,'input_changed','关联输入变化，须先完成影响复核')
            task['status']='needs_revalidation'
    return created


def resolve_change_impact(doc,actor,p):
    impact=RdStore._find(doc,'change_impacts',p.get('impact_id'))
    if impact['status']!='pending':raise RdError(409,'该影响记录已完成复核')
    decision=p.get('decision')
    if decision not in {'unaffected','revalidate'}:raise RdError(422,'复核决定不正确')
    reason=_text(p.get('reason'),'影响复核依据')
    new_adoption=None
    if p.get('adoption_id'):
        new_adoption=RdStore._find(doc,'development_adoptions',p['adoption_id'])
        if decision!='revalidate' or new_adoption['route']=='direct' or new_adoption['requirements_baseline_id']!=doc['project']['current_baseline_id']:
            raise RdError(409,'重新采用须引用当前基线的新研或改型批准依据')
    impact.update(status='resolved',resolution={'decision':decision,'reason':reason,'resolved_by':actor['user_id'],'resolved_at':_now()})
    tids=[impact['task_id'],*impact['downstream_task_ids']]
    for tid in tids:
        if any(i['status']=='pending' and (i['task_id']==tid or tid in i.get('downstream_task_ids',[])) for i in doc['change_impacts']):continue
        task=RdStore._find(doc,'tasks',tid)
        if decision=='unaffected':
            previous=task.pop('previous_status','in_progress')
            task['status']='in_progress' if previous=='in_review' else previous
        elif tid==impact['task_id']:
            w=work_unit(doc,tid)
            if new_adoption:w['adoption_id']=new_adoption['id']
            if w.get('input_package_id'):
                package=RdStore._find(doc,'taskbook_input_packages',w['input_package_id']);package['status']='needs_revalidation'
            w.update(input_package_id=None,selected_run_id=None,selected_revision_id=None,current_stage='ND13')
            task.update(status='in_progress',baseline_id=doc['project']['current_baseline_id'])
            task.pop('previous_status',None)
            for stage in w['stages']:stage.update(status='in_progress' if stage['node_code']=='ND13' else 'pending',completed_at=None)
            for draft in doc['taskbook_wbs_drafts']:
                if draft['task_id']==tid:draft['status']='needs_revalidation'
