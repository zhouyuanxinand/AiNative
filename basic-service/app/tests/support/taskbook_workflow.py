"""Adopted development and taskbook work-unit scenarios."""
from tests.support.rd_project import ENGINEER, REVIEWER, command, project


def admitted(store, route='new'):
    d = project(store)
    for actor, role in ((ENGINEER, 'engineer'), (REVIEWER, 'reviewer')):
        d = command(store, d, 'add_member', {**actor, 'role': role})
    d = command(store, d, 'save_requirement', {'title':'R1','content':'thermal','source':'agreement','acceptance':'test','clarification':'resolved'})
    d = command(store, d, 'confirm_baseline')
    return command(store, d, 'adopt_development', {'route':route,'approval_ref':'OA-demo-1','scope':'connector','process_template_ref':{'id':'BP05','version':'1'},'provenance':'mock','requirement_ids':[r['id'] for r in d['requirements']]})


def native(store):
    d = admitted(store)
    return command(store, d, 'create_taskbook', {'adoption_id':d['development_adoptions'][0]['id'],'title':'Taskbook','description':'scope','assignee_id':'engineer','reviewer_id':'reviewer'})
