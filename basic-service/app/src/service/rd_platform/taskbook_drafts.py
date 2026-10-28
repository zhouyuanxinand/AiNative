"""User and role scoped form intent; ReviewStore remains the only document body."""
from .store import RdError, _actor, _json, _now
from .taskbook_inputs import task_context, package_from_doc
import json

def _scope(doc,pid,tid,actor,package_id):
    role=next(m['role'] for m in doc['members'] if m['user_id']==actor['user_id'])
    return _json([pid,tid,actor['user_id'],role,package_id])

def load_taskbook_draft(store,pid,tid,actor,package_id):
    actor=_actor(actor)
    with store._connection() as conn:
        doc,_,_=task_context(store,conn,pid,tid,actor)
        if package_id:package_from_doc(doc,tid,package_id)
        row=conn.execute('SELECT document FROM taskbook_drafts WHERE scope=?',(_scope(doc,pid,tid,actor,package_id),)).fetchone()
        return json.loads(row[0]) if row else None

def save_taskbook_draft(store,pid,tid,actor,payload):
    actor=_actor(actor)
    if len(_json(payload))>500000 or not isinstance(payload.get('form'),dict) or not isinstance(payload.get('pending_operations',[]),list) or len(payload.get('pending_operations',[]))>1000:
        raise RdError(422,'草稿格式无效或过大')
    with store._transaction() as conn:
        doc,_,_=task_context(store,conn,pid,tid,actor,write=True)
        package_id=payload.get('input_package_id')
        if package_id:package_from_doc(doc,tid,package_id)
        scope=_scope(doc,pid,tid,actor,package_id)
        row=conn.execute('SELECT revision FROM taskbook_drafts WHERE scope=?',(scope,)).fetchone()
        revision=row[0] if row else 0
        if type(payload.get('expected_draft_revision')) is not int or payload['expected_draft_revision']!=revision:
            raise RdError(409,'草稿已有更新，请保留本地编辑并比较后重试')
        value={'input_package_id':package_id,'draft_revision':revision+1,'form':payload['form'],'pending_operations':payload.get('pending_operations',[]),'updated_at':_now()}
        conn.execute('INSERT INTO taskbook_drafts VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET revision=excluded.revision,document=excluded.document',(scope,revision+1,_json(value)))
        return value
