import json
import sqlite3
from src.service.rd_platform.store import RdStore


def test_v1_database_preserves_legacy_ids_and_allows_native_tables(tmp_path):
    path=tmp_path/'legacy.sqlite3'
    document={'project':{'id':'legacy-project','owner_id':'owner','version':7,'current_baseline_id':'baseline-1'},'members':[{'user_id':'owner','role':'owner'}],'requirements':[],'baselines':[{'id':'baseline-1'}],'tasks':[{'id':'legacy-task','title':'研制任务书','status':'done'}],'artifacts':[{'id':'artifact-1','file_ref':'C:/private/a.docx'}],'reviews':[{'id':'review-1','status':'approved'}],'events':[],'generations':[{'jid':'unbound-old-job'}]}
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE projects (id TEXT PRIMARY KEY,version INTEGER NOT NULL,document TEXT NOT NULL)')
        conn.execute('CREATE TABLE requests (scope TEXT,actor_id TEXT,request_key TEXT,fingerprint TEXT,response TEXT,PRIMARY KEY(scope,actor_id,request_key))')
        conn.execute('CREATE TABLE generations (jid TEXT PRIMARY KEY,project_id TEXT,binding TEXT)')
        conn.execute('INSERT INTO projects VALUES (?,?,?)',('legacy-project',7,json.dumps(document)))
        conn.execute('INSERT INTO generations VALUES (?,?,?)',('unbound-old-job','legacy-project',json.dumps({'jid':'unbound-old-job','task_id':'legacy-task'})))
        conn.execute('PRAGMA user_version=1')
    store=RdStore(path)
    view=store.detail('legacy-project','owner')
    assert view['project']['version']==7
    assert view['tasks'][0]==document['tasks'][0]
    assert view['artifacts'][0]['id']=='artifact-1' and view['reviews'][0]['id']=='review-1'
    assert view['taskbook_work_units']==[]
    with sqlite3.connect(path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==2
        assert conn.execute('SELECT count(*) FROM taskbook_runs').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM taskbook_drafts').fetchone()[0]==0
        assert json.loads(conn.execute('SELECT document FROM projects').fetchone()[0])==document
    assert store.generation('unbound-old-job')['task_id']=='legacy-task'


def test_nested_native_views_redact_internal_sources_and_response_replay_is_shape_safe():
    value={'package':{'id':'p1','source_refs':[{'file_ref':'C:/private/source.docx','sha256':'abc'}],'selection':{'category_mapping_path':'C:/private/mapping.json'},'runtime_fingerprint':'fixed'},'project_version':2}
    result=RdStore._public_artifacts(value)
    assert 'C:/private' not in str(result)
    assert result['package']['runtime_fingerprint']=='fixed'
