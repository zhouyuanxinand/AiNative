"""Authenticated native taskbook workspace and exact-version operations."""
from __future__ import annotations
import copy
from pathlib import Path
from typing import Any, Annotated
from urllib.parse import quote
from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import Field
from .rd_dependencies import RdRoute, RequestBody, Actor, RequestKey
from src.service.rd_platform.runtime import get_store
from src.service.rd_platform.store import RdError,_json
from src.service.rd_platform import taskbook_inputs as inputs,taskbook_runs as runs
from src.service.rd_platform.taskbook_drafts import load_taskbook_draft,save_taskbook_draft

router=APIRouter(prefix='/api/rd/projects',tags=['研制任务书'],route_class=RdRoute)
T='/{pid}/tasks/{tid}/taskbook'

class PackageBody(RequestBody):
    expected_version:int=Field(ge=1)
    source_refs:list[dict[str,Any]]=Field(min_length=1,max_length=50)
    parameters:dict[str,Any]=Field(default_factory=dict)
    model_selection:dict[str,Any]=Field(default_factory=dict)
    confirmed:bool

class DraftBody(RequestBody):
    expected_draft_revision:int=Field(ge=0)
    input_package_id:str|None=Field(default=None,max_length=100)
    form:dict[str,Any]=Field(default_factory=dict)
    pending_operations:list[dict[str,Any]]=Field(default_factory=list,max_length=1000)

class RunBody(RequestBody):
    package_id:str=Field(min_length=1,max_length=100)
    expected_version:int=Field(ge=1)
    parent_run_id:str|None=Field(default=None,max_length=100)

class VersionBody(RequestBody):
    expected_version:int=Field(ge=1)

class SelectBody(VersionBody):
    run_id:str=Field(min_length=1,max_length=100)
    revision_id:str=Field(min_length=1,max_length=100)

class CheckBody(SelectBody):
    decisions:list[dict[str,Any]]=Field(default_factory=list,max_length=15)

class SubmitBody(SelectBody):
    coverage_id:str=Field(min_length=1,max_length=100)
    wbs_revision:int=Field(ge=1)

class PrecheckBody(RequestBody):
    package_id:str=Field(min_length=1,max_length=100)

class ClarificationBody(VersionBody):
    answers:dict[str,str]

@router.get(T)
def workspace(pid:str,tid:str,actor:Actor):
    from src.service.rd_platform.taskbook_workflow import build_taskbook_workspace
    store=get_store()
    with store._connection() as conn:
        doc,_,unit=inputs.task_context(store,conn,pid,tid,actor)
        result=build_taskbook_workspace(doc,tid,actor['user_id'])
    result['runs']=runs.list_taskbook_runs(store,pid,tid,actor)
    result['draft']=load_taskbook_draft(store,pid,tid,actor,unit.get('input_package_id'))
    result['section_mapping']=__import__('src.service.rd_platform.taskbook_coverage',fromlist=['load_mapping']).load_mapping()
    return inputs.public_value(result)

@router.post('/{pid}/sources')
async def upload_source(pid:str,actor:Actor,request_key:RequestKey,file:UploadFile=File(...),role:str=Form(...),expected_version:int=Form(...),provenance:str=Form('manual')):
    from src.controller import taskbook_controller as jobs
    data=await file.read(jobs._STATE.max_upload_bytes+1)
    return inputs.add_project_source(get_store(),pid,actor,role,file.filename or '',data,expected_version,request_key,provenance)

@router.get('/{pid}/sources/{source_id}/versions/{version}/download')
def download_source(pid:str,source_id:str,version:int,actor:Actor):
    store=get_store()
    with store._connection() as conn:
        doc=store._load(conn,pid,actor['user_id'])
        source=next((s for s in doc.get('project_sources',[]) if s['source_id']==source_id and s['version']==version),None)
    if not source:raise RdError(404,'资料版本不存在')
    try:data=Path(source['file_ref']).read_bytes()
    except OSError as exc:raise RdError(404,'固定资料文件缺失') from exc
    if inputs.digest(data)!=source['sha256']:raise RdError(409,'资料校验失败')
    return Response(data,media_type='application/octet-stream',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(source['name'],safe=''),'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

@router.put(T+'/draft')
def draft_save(pid:str,tid:str,body:DraftBody,actor:Actor):
    return save_taskbook_draft(get_store(),pid,tid,actor,body.model_dump())

@router.get(T+'/draft')
def draft_get(pid:str,tid:str,actor:Actor,input_package_id:str|None=Query(default=None,max_length=100)):
    return load_taskbook_draft(get_store(),pid,tid,actor,input_package_id)

@router.post(T+'/input-packages')
def create_package(pid:str,tid:str,body:PackageBody,actor:Actor,request_key:RequestKey):
    return inputs.create_input_package(get_store(),pid,tid,actor,body.model_dump(exclude={'expected_version'}),body.expected_version,request_key)

@router.post(T+'/runs')
def run_start(pid:str,tid:str,body:RunBody,actor:Actor,request_key:RequestKey,background_tasks:BackgroundTasks):
    if body.parent_run_id:raise RdError(422,'指标澄清请使用父运行的澄清接口')
    return runs.start_taskbook_run(get_store(),pid,tid,actor,body.package_id,body.expected_version,request_key,background_tasks=background_tasks)

@router.post(T+'/runs/{run_id}/clarifications')
def run_clarify(pid:str,tid:str,run_id:str,body:ClarificationBody,actor:Actor,request_key:RequestKey,background_tasks:BackgroundTasks):
    store=get_store();parent=runs.get_taskbook_run(store,pid,tid,actor,run_id,write=True)
    return runs.start_taskbook_run(store,pid,tid,actor,parent['package_id'],body.expected_version,request_key,parent_run_id=run_id,answers=body.answers,background_tasks=background_tasks)

@router.post(T+'/runs/{run_id}/cancel')
def run_cancel(pid:str,tid:str,run_id:str,body:VersionBody,actor:Actor,request_key:RequestKey):
    return runs.cancel_taskbook_run(get_store(),pid,tid,actor,run_id,body.expected_version,request_key)

def _revision(store,pid,tid,actor,run_id,revision_id):
    from src.controller import review_controller as review
    from src.service.rd_platform.taskbook_models import usable_run
    run=runs.get_taskbook_run(store,pid,tid,actor,run_id,write=True)
    if not usable_run(run) or run.get('cancel_requested'):raise RdError(409,'运行没有可采用的有效完成稿')
    store.authorize_generation(run['jid'],actor['user_id'],write=True)
    with store._connection() as conn:
        doc,_,unit=inputs.task_context(store,conn,pid,tid,actor,write=True)
        if unit.get('input_package_id')!=run['package_id']:raise RdError(409,'此运行采用的输入包已经变化')
        package=copy.deepcopy(inputs.package_from_doc(doc,tid,run['package_id']))
    inputs.verify_package(package)
    try:
        review.ensure_review(run['jid']);revision=review.get_store().revision(run['jid'],revision_id)
        if inputs.digest(review.get_store().revision_path(run['jid'],revision_id).read_bytes())!=revision['sha256']:raise RdError(409,'修订文件校验失败')
    except (FileNotFoundError,ValueError) as exc:raise RdError(409,'无法读取所选固定修订') from exc
    return run,package,revision

@router.post(T+'/revisions/select')
def select_revision(pid:str,tid:str,body:SelectBody,actor:Actor,request_key:RequestKey):
    from src.service.rd_platform.taskbook_workflow import select_taskbook_revision
    store=get_store();_,_,revision=_revision(store,pid,tid,actor,body.run_id,body.revision_id)
    return select_taskbook_revision(store,pid,tid,actor,body.run_id,body.revision_id,body.expected_version,request_key,revision={'id':body.revision_id,'sha256':revision['sha256']})

@router.post(T+'/checks')
def check_revision(pid:str,tid:str,body:CheckBody,actor:Actor,request_key:RequestKey):
    from src.controller import review_controller as review
    from src.service.rd_platform.taskbook_coverage import check_taskbook_coverage,load_mapping
    from jonhon_taskbook.review_document import document_projection
    store=get_store();fp=inputs.digest(_json(body.model_dump(exclude={'expected_version'})).encode())
    with store._connection() as conn:
        inputs.task_context(store,conn,pid,tid,actor,write=True)
        replay=store._replay(conn,tid+':checks',actor['user_id'],request_key,fp)
        if replay:return replay
    run,package,revision=_revision(store,pid,tid,actor,body.run_id,body.revision_id)
    qa=review.get_store().check_revision(run['jid'],body.revision_id,independent_review=True)
    projection=document_projection(review.get_store().revision_path(run['jid'],body.revision_id),revision_id=body.revision_id)
    decisions=[]
    for decision in body.decisions:
        if set(decision)-{'section_key','status','output_anchor','evidence_ref','requirement_ref','reason'}:raise RdError(422,'覆盖处置字段无效，确认身份由服务端记录')
        decisions.append({**decision,'checked_by':actor['user_id']})
    coverage=check_taskbook_coverage(package,revision,projection,load_mapping(),decisions)
    coverage.update(task_id=tid,run_id=body.run_id)
    inputs.verify_package(package)
    with store._transaction() as conn:
        doc,_,unit=inputs.task_context(store,conn,pid,tid,actor,write=True)
        replay=store._replay(conn,tid+':checks',actor['user_id'],request_key,fp)
        if replay:return replay
        store._version(doc,body.expected_version)
        if unit['input_package_id']!=package['id']:raise RdError(409,'核验过程中输入包已变化')
        doc.setdefault('taskbook_coverages',[]).append(coverage)
        store._save(conn,doc,'check_taskbook_revision',actor['user_id'],{'task_id':tid,'coverage_id':coverage['id'],'revision_id':body.revision_id})
        result={'coverage':coverage,'qa':qa,'project_version':doc['project']['version']}
        store._remember(conn,tid+':checks',actor['user_id'],request_key,fp,result)
    return inputs.public_value(result)

@router.post(T+'/submit-review')
def submit_review(pid:str,tid:str,body:SubmitBody,actor:Actor,request_key:RequestKey):
    from src.service.rd_platform.taskbook_release import submit_taskbook_review
    from src.service.rd_platform.integration import prepare_artifact_payload
    store=get_store()
    # Retry must remain readable after the first request has moved the task to
    # in_review. Revalidate current membership, role and assignee before replay.
    fp=_json({'action':'submit_taskbook_review','task_id':tid,**body.model_dump()})
    with store._connection() as conn:
        doc,task,_=inputs.task_context(store,conn,pid,tid,actor)
        member=store._member(doc,actor['user_id'])
        if task['assignee_id']!=actor['user_id'] or member['role'] not in {'owner','engineer'}:
            raise RdError(403,'仅当前任务执行人可以送审任务书')
        replay=store._replay(conn,pid,actor['user_id'],request_key,fp)
        if replay:return replay
    run,_,_=_revision(store,pid,tid,actor,body.run_id,body.revision_id)
    artifact=prepare_artifact_payload(store,run['jid'],body.revision_id)
    return submit_taskbook_review(store,pid,tid,actor,{**body.model_dump(exclude={'expected_version'}),'artifact_payload':artifact},body.expected_version,request_key)

@router.post(T+'/precheck')
def precheck(pid:str,tid:str,body:PrecheckBody,actor:Actor):
    from src.controller import taskbook_controller as jobs
    store=get_store()
    with store._connection() as conn:
        doc,_,unit=inputs.task_context(store,conn,pid,tid,actor,write=True)
        package=copy.deepcopy(inputs.package_from_doc(doc,tid,body.package_id))
        if unit.get('input_package_id')!=package['id']:raise RdError(409,'请采用当前固定输入包预检')
    inputs.verify_package(package)
    files={}
    for item in package['source_refs']:
        if item['role'] not in {'tech','spec'}:continue
        text=jobs._extract_docx_text_from_bytes(Path(item['file_ref']).read_bytes())
        check=jobs._classify_doc_role(item['name'],text,item['role'])
        if Path(item['name']).suffix.lower()!='.docx':check.update(ok=True,requires_review=True,message='生成时转换并保留识别证据，转换内容须人工核对')
        files[item['role']]={'name':item['name'],**check}
    template=package['template_ref']
    files['tpl']={'name':template['name'],'managed':True,**jobs._classify_doc_role(template['name'],jobs._extract_docx_text_from_bytes(Path(template['file_ref']).read_bytes()),'tpl')}
    model=package['model_selection'];p=package['normalized_parameters']
    model_error=jobs._llm_submission_error(str(p['use_llm']).lower(),model.get('provider',''),model.get('name',''),model.get('id',''))
    return {'package_id':package['id'],'files':files,'consistency':jobs._check_name_consistency(files['tech']['name'],files['spec']['name'],template['name']),
            'model_available':not bool(model_error),'blockers':['所选模型不可运行，请检查固定模型配置'] if model_error else [],'business_state_advanced':False}

def get_router():return router
