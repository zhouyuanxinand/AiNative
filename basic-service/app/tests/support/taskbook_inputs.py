"""Isolated input-package fixture and in-memory source-document builders.

The native fixture returns (store, project_id, task_id); it is distinct from
taskbook_workflow.native(store), which returns an adopted work-unit document.
"""
import io
import pytest
from docx import Document
from src.service.rd_platform.store import RdStore, _json
from tests.support.rd_project import ENGINEER, prepared


@pytest.fixture
def native(tmp_path):
    store = RdStore(tmp_path / 'native.sqlite3', tmp_path / 'artifacts')
    d = prepared(store)
    pid, tid = d['project']['id'], d['tasks'][0]['id']
    with store._transaction() as conn:
        doc = store._load(conn, pid, 'engineer')
        for name in ('project_sources','taskbook_input_packages','taskbook_work_units','development_adoptions','taskbook_coverages'):
            doc.setdefault(name, [])
        doc['development_adoptions'].append({'id':'adopt','route':'new','approval_ref':'mock-approved','scope':'连接器研制','process_template_ref':{'id':'BP05','version':'1'},'requirements_baseline_id':doc['project']['current_baseline_id']})
        doc['taskbook_work_units'].append({'id':'wu','task_id':tid,'adoption_id':'adopt','current_stage':'ND13','input_package_id':None,'selected_run_id':None,'selected_revision_id':None,'stages':[]})
        conn.execute('UPDATE projects SET document=? WHERE id=?', (_json(doc),pid))
    return store,pid,tid


def docx(text='连接器技术要求及产品规范'):
    doc=Document(); doc.add_paragraph(text); b=io.BytesIO(); doc.save(b); return b.getvalue()


def package(native, **overrides):
    from src.service.rd_platform.taskbook_inputs import add_project_source, create_input_package
    store,pid,tid=native
    refs=[]
    for role in ('tech','spec'):
        version=store.detail(pid,'engineer')['project']['version']
        s=add_project_source(store,pid,ENGINEER,role,role+'.docx',docx(),version,role)
        refs.append({'source_id':s['source']['source_id'],'version':s['source']['version']})
    payload={'source_refs':refs,'parameters':{'product_type':'filter_connector','product_domain':'military','development_process':'全新','organization_scope':'non_central_research','cover_phase':'F','use_llm':False},'model_selection':{},'confirmed':True,**overrides}
    version=store.detail(pid,'engineer')['project']['version']
    return create_input_package(store,pid,tid,ENGINEER,payload,version,'package')['package']
