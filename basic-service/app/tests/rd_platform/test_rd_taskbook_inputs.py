"""Native fixed input isolation, content versions and durable draft behavior."""
from tests.support.taskbook_inputs import native as native
from tests.support.taskbook_inputs import docx, package
import pytest
from src.service.rd_platform.store import RdError, RdStore
from tests.support.rd_project import ENGINEER, REVIEWER


def test_same_name_different_bytes_are_immutable_source_versions(native):
    from src.service.rd_platform.taskbook_inputs import add_project_source
    store,pid,tid=native
    one=add_project_source(store,pid,ENGINEER,'tech','资料.docx',docx('一'),store.detail(pid,'engineer')['project']['version'],'a')['source']
    two=add_project_source(store,pid,ENGINEER,'tech','资料.docx',docx('二'),store.detail(pid,'engineer')['project']['version'],'b')['source']
    assert one['source_id']==two['source_id'] and (one['version'],two['version'])==(1,2)
    assert one['sha256'] != two['sha256']
    assert 'file_ref' not in one

def test_confirmed_package_requires_tech_spec_and_freezes_template(native):
    from pathlib import Path
    from src.service.rd_platform.taskbook_inputs import create_input_package, package_from_doc, verify_package
    store,pid,tid=native
    with pytest.raises(RdError,match='资料'):
        create_input_package(store,pid,tid,ENGINEER,{'source_refs':[],'parameters':{},'confirmed':True},store.detail(pid,'engineer')['project']['version'],'missing')
    fixed=package(native)
    assert fixed['fingerprint'] and fixed['runtime_fingerprint']
    with store._connection() as c:
        doc=store._load(c,pid,'engineer'); internal=package_from_doc(doc,tid,fixed['id'])
    assert Path(internal['selection']['template_path']).is_relative_to(store.artifact_root)
    verify_package(internal)
    Path(internal['selection']['template_path']).write_bytes(b'changed')
    with pytest.raises(RdError,match='校验'):
        verify_package(internal)

def test_private_drafts_are_role_scoped_and_use_independent_cas(native):
    from src.service.rd_platform.taskbook_drafts import save_taskbook_draft, load_taskbook_draft
    store,pid,tid=native
    body={'input_package_id':None,'expected_draft_revision':0,'form':{'product_series':'A'},'pending_operations':[]}
    saved=save_taskbook_draft(store,pid,tid,ENGINEER,body)
    assert saved['draft_revision']==1
    assert load_taskbook_draft(store,pid,tid,REVIEWER,None) is None
    assert load_taskbook_draft(RdStore(store.db_path,store.artifact_root),pid,tid,ENGINEER,None)['form']==body['form']
    with pytest.raises(RdError,match='草稿'):
        save_taskbook_draft(store,pid,tid,ENGINEER,body)

def test_source_replacement_creates_impact_without_rewriting_confirmed_package(native):
    from src.service.rd_platform.taskbook_inputs import add_project_source
    store,pid,tid=native;fixed=package(native)
    before=store.detail(pid,'engineer')['taskbook_input_packages'][0]['fingerprint']
    result=add_project_source(store,pid,ENGINEER,'tech','tech.docx',docx('新技术要求'),store.detail(pid,'engineer')['project']['version'],'replacement')
    d=store.detail(pid,'engineer')
    assert result['source']['version']==2
    assert d['taskbook_input_packages'][0]['fingerprint']==before
    assert len(d['change_impacts'])==1 and d['change_impacts'][0]['status']=='pending'
    assert d['tasks'][0]['status']=='needs_revalidation'

def test_model_request_configuration_change_requires_new_confirmation(native,monkeypatch):
    from src.service.rd_platform import taskbook_inputs as inputs
    store,pid,tid=native;fixed=package(native)
    with store._connection() as conn:
        internal=inputs.package_from_doc(store._load(conn,pid,'engineer'),tid,fixed['id'])
    monkeypatch.setattr(inputs,'model_runtime_fingerprint',lambda model:'changed-request-configuration')
    with pytest.raises(RdError,match='模型.*配置'):
        inputs.verify_package(internal)

def test_confirmed_package_parameter_mutation_is_detected(native):
    from src.service.rd_platform import taskbook_inputs as inputs
    store,pid,tid=native;fixed=package(native)
    with store._connection() as conn:
        internal=inputs.package_from_doc(store._load(conn,pid,'engineer'),tid,fixed['id'])
    internal['normalized_parameters']['product_series']='silently-changed'
    with pytest.raises(RdError,match='输入包.*校验'):
        inputs.verify_package(internal)
