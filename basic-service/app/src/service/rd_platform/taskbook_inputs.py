"""Immutable project input versions and snapshots for the unchanged engine."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from .store import RdError, _actor, _id, _json, _now, _text

SOURCE_ROLES = {'tech','spec','baseline_docx','baseline_json','reference'}
PARAMETERS = {'product_type','product_domain','development_process','product_series','organization_scope','cover_phase','use_llm','template_edit_plan','template_edit_confirmed','fail_on_regression'}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def public_value(value):
    """Never expose local file locations or credentials in native resources."""
    if isinstance(value,list):
        return [public_value(item) for item in value]
    if not isinstance(value,dict):
        return value
    return {key:public_value(item) for key,item in value.items()
            if key not in {'api_key','base_url','token','password','credential'}
            and not (key.endswith('_path') or key == 'file_ref' and not str(item).startswith('/api/'))}

def task_context(store, conn, pid, tid, actor, *, write=False):
    actor = _actor(actor)
    doc=store._load(conn,pid,actor['user_id'])
    task=store._find(doc,'tasks',tid)
    unit=next((x for x in doc.get('taskbook_work_units',[]) if x['task_id']==tid),None)
    if not unit:
        raise RdError(409,'此任务不是研制任务书工作包')
    if write:
        store._assignee(doc,task,actor['user_id'])
        if task['assignee_id'] != actor['user_id']:
            raise RdError(403,'仅当前任务执行人可以办理任务书')
        member=store._member(doc,actor['user_id'])
        if not member or member['role'] not in {'engineer','owner'}:
            raise RdError(403,'当前项目角色无权编制任务书')
        if task['status'] not in {'in_progress','changes_requested'}:
            raise RdError(409,'任务须处于办理或退回修订状态')
    return doc,task,unit

def package_from_doc(doc,tid,package_id):
    package=next((p for p in doc.get('taskbook_input_packages',[]) if p['id']==package_id and p['task_id']==tid),None)
    if not package:
        raise RdError(404,'本任务的固定输入包不存在')
    return package

def runtime_fingerprint():
    """Hash actual installed engine, global rules and vocabularies, never secrets.

    Global rule loaders have no historical replay parameter. A mismatch blocks
    execution rather than pretending an archived file changes loaded globals.
    """
    from src.controller import taskbook_controller as jobs
    import jonhon_taskbook
    package_root=Path(jonhon_taskbook.__file__).resolve().parent
    paths=set(package_root.rglob('*.py'))
    config_root=Path(jobs._STATE.config_dir)
    if config_root==Path():config_root=package_root.parent/'config'
    for root in (package_root,config_root):
        if root.exists():
            for suffix in ('*.yaml','*.yml','*.json','*.txt','*.xlsx','*.csv'):
                paths.update(root.rglob(suffix))
    # These resources live beside the package, not under it. They include
    # prompt text, product vocabulary packs and the common routing rule pack.
    for root in (package_root.parent/'config',package_root.parent/'prompts',package_root.parent/'products'):
        if root.is_dir():paths.update(p for p in root.rglob('*') if p.is_file())
    from jonhon_taskbook import config as engine_config
    rule_pack=Path(engine_config.RULE_PACK_PATH)
    paths.add(rule_pack)
    if rule_pack.is_file():
        try:
            content=json.loads(rule_pack.read_text(encoding='utf-8'))
            ref=content.get('indicator_catalog') or content.get('indicator_catalog_file')
            if ref:paths.add(rule_pack.parent/ref)
        except (ValueError,UnicodeError):pass
    pipeline=Path(__file__).resolve().parents[2]/'pipeline_cli.py'
    paths.add(pipeline)
    paths.add(Path(jobs.__file__))
    from jonhon_taskbook.failure_database import database_path
    database=database_path()
    if database.is_file():
        paths.add(database)
        wal=Path(str(database)+'-wal')
        if wal.is_file():paths.add(wal)
    relevant=('RULE','QA','PROFILE','TEMPLATE','INPUT','INDICATOR','FAILURE','NORMALIZ','PROCESS','REPAIR','SEMANTIC','CATALOG')
    environment={k:v for k,v in os.environ.items() if k.startswith('JTB_') and any(word in k for word in relevant) and not any(secret in k for secret in ('KEY','SECRET','TOKEN','PASSWORD','AUTH'))}
    environment['ENABLE_LLM_ZONE_FILL_loaded']=bool(engine_config.ENABLE_LLM_ZONE_FILL)
    manifest={str(path.resolve()):digest(path.read_bytes()) for path in sorted(paths) if path.is_file()}
    return digest(_json({'files':manifest,'environment':environment,'python':sys.version}).encode())

def _fixed_copy(root,path,role):
    path=Path(path)
    data=path.read_bytes(); sha=digest(data)
    target=root/(role+'-'+sha+path.suffix.lower())
    if target.exists() and digest(target.read_bytes())!=sha:
        raise RdError(409,'固定输入文件校验失败')
    if not target.exists():
        target.write_bytes(data)
    return {'sha256':sha,'file_ref':str(target),'name':path.name}

def add_project_source(store,pid,actor,role,filename,data,expected_version,key,provenance='manual'):
    from src.controller import taskbook_controller as jobs
    from jonhon_taskbook.input_normalizer import SUPPORTED_INPUT_EXTENSIONS
    actor=_actor(actor); filename=Path(_text(filename,'资料名称',maximum=256)).name
    if role not in SOURCE_ROLES or provenance not in {'manual','mock'}:
        raise RdError(422,'资料用途或来源标识无效')
    if not isinstance(data,bytes) or not data or len(data)>jobs._STATE.max_upload_bytes:
        raise RdError(422,'资料为空或超过上传大小限制')
    suffix=Path(filename).suffix.lower()
    allowed={'.json'} if role=='baseline_json' else {'.docx'} if role=='baseline_docx' else SUPPORTED_INPUT_EXTENSIONS
    if suffix not in allowed:
        raise RdError(422,'资料格式不受支持')
    if suffix=='.docx':
        error=jobs._validate_docx_payload(filename,data)
        if error: raise RdError(422,error)
    if suffix=='.json':
        try: json.loads(data)
        except (ValueError,UnicodeError) as exc: raise RdError(422,'JSON资料格式无效') from exc
    sha=digest(data); fp=digest(_json({'role':role,'filename':filename,'sha256':sha,'provenance':provenance}).encode())
    with store._transaction() as conn:
        doc=store._load(conn,pid,actor['user_id'])
        member=store._member(doc,actor['user_id'])
        if member['role'] not in {'owner','engineer'}: raise RdError(403,'仅项目负责人和工程师可以登记资料')
        replay=store._replay(conn,pid+':sources',actor['user_id'],key,fp)
        if replay:return replay
        store._version(doc,expected_version)
        sources=doc.setdefault('project_sources',[])
        previous=[s for s in sources if s['role']==role and s['name']==filename]
        source={'source_id':previous[0]['source_id'] if previous else _id(),'version':max((s['version'] for s in previous),default=0)+1,
                'role':role,'name':filename,'sha256':sha,'size':len(data),'provenance':provenance,'created_by':actor['user_id'],'created_at':_now()}
        root=store.artifact_root/'sources';root.mkdir(parents=True,exist_ok=True)
        path=root/(sha+suffix)
        if path.exists() and digest(path.read_bytes())!=sha:raise RdError(409,'资料文件校验失败')
        if not path.exists():path.write_bytes(data)
        source['file_ref']=str(path);sources.append(source)
        if previous:
            from .taskbook_changes import assess_taskbook_impact
            assess_taskbook_impact(doc,[{'kind':'source','source_id':source['source_id'],'version':source['version']}])
        store._save(conn,doc,'add_project_source',actor['user_id'],public_value(source))
        result={'source':public_value(source),'project_version':doc['project']['version']}
        store._remember(conn,pid+':sources',actor['user_id'],key,fp,result)
        return result

def create_input_package(store,pid,tid,actor,payload,expected_version,key):
    from src.controller import taskbook_controller as jobs
    actor=_actor(actor); fp=digest(_json(payload).encode())
    if len(_json(payload))>200000:raise RdError(422,'输入参数过大')
    with jobs._STATE.rules_lock, store._transaction() as conn:
        doc,task,unit=task_context(store,conn,pid,tid,actor,write=True)
        replay=store._replay(conn,tid+':packages',actor['user_id'],key,fp)
        if replay:return replay
        store._version(doc,expected_version)
        refs=payload.get('source_refs')
        if not isinstance(refs,list) or not 1<=len(refs)<=50:raise RdError(422,'请采用本项目的技术资料和产品规范资料')
        sources=[]
        for ref in refs:
            if not isinstance(ref,dict) or set(ref)!={'source_id','version'} or not isinstance(ref['source_id'],str) or type(ref['version']) is not int:
                raise RdError(422,'资料引用须指定source_id和整数version')
            source=next((s for s in doc.get('project_sources',[]) if s['source_id']==ref.get('source_id') and s['version']==ref.get('version')),None)
            if not source:raise RdError(422,'引用的项目资料版本不存在')
            sources.append(copy.deepcopy(source))
        roles=[s['role'] for s in sources if s['role']!='reference']
        if 'tech' not in roles or 'spec' not in roles or len(roles)!=len(set(roles)):
            raise RdError(422,'必须采用唯一的技术资料与产品规范资料')
        if 'baseline_json' in roles and 'baseline_docx' not in roles:raise RdError(422,'回归JSON必须同时采用DOCX基线')
        adoption=next((a for a in doc.get('development_adoptions',[]) if a['id']==unit['adoption_id']),None)
        if not adoption or not adoption.get('scope') or not adoption.get('approval_ref') or not adoption.get('process_template_ref'):
            raise RdError(409,'须先登记批准范围及受控流程模板')
        if payload.get('confirmed') is not True:raise RdError(422,'请明确确认固定输入及参数')
        jobs._invalidate_rule_caches()
        raw=payload.get('parameters',{})
        if not isinstance(raw,dict) or set(raw)-PARAMETERS:raise RdError(422,'生成参数含不支持的字段')
        model=payload.get('model_selection') or {}
        if not isinstance(model,dict) or set(model)-{'provider','name','id'}:raise RdError(422,'模型选择不能包含凭据或运行时地址')
        normalized={'product_type':raw.get('product_type','filter_connector'),'product_domain':raw.get('product_domain','military')}
        try:
            process,series,scope,phase=jobs._validate_process_inputs(raw.get('development_process','全新'),raw.get('product_series',''),raw.get('organization_scope','non_central_research'),raw.get('cover_phase',''))
            selection=jobs.resolve_template_selection(normalized['product_type'],normalized['product_domain'])
            edit,error=jobs._read_template_edit_plan(_json(raw.get('template_edit_plan')) if raw.get('template_edit_plan') else '',str(raw.get('template_edit_confirmed',False)).lower())
            if error:raise ValueError(error)
        except (ValueError,FileNotFoundError) as exc:raise RdError(422,'模板或参数不可用，请核对产品类型、阶段与编辑方案') from exc
        for key_name in ('use_llm','fail_on_regression'):
            if key_name in raw and type(raw[key_name]) is not bool:raise RdError(422,'生成开关须为布尔值')
        normalized.update(development_process=process,product_series=series,organization_scope=scope,cover_phase=phase,use_llm=raw.get('use_llm',True),template_edit_plan=edit,fail_on_regression=raw.get('fail_on_regression',False))
        if normalized['use_llm'] and (not model.get('provider') or not model.get('name')):
            raise RdError(422,'使用模型须固定提供方和模型名称')
        model={k:_text(model.get(k,''),'模型选择',required=False,maximum=256) for k in ('provider','name','id')}
        package_id=_id();root=store.artifact_root/'input_packages'/package_id;root.mkdir(parents=True)
        fixed=selection.to_dict()
        assets={}
        for field,role in (('template_path','template'),('profile_path','profile'),('category_mapping_path','mapping')):
            if not fixed.get(field):continue
            assets[role]=_fixed_copy(root,fixed[field],role);fixed[field]=assets[role]['file_ref']
        package={'id':package_id,'version':1+sum(p['task_id']==tid for p in doc.setdefault('taskbook_input_packages',[])), 'task_id':tid,
                 'baseline_id':task['baseline_id'],'source_refs':sources,'selection':fixed,'raw_parameters':copy.deepcopy(raw),'normalized_parameters':normalized,
                 'template_ref':assets['template'],'profile_ref':assets.get('profile'),'mapping_ref':assets['mapping'],'runtime_fingerprint':runtime_fingerprint(),'model_selection':model,'model_runtime_fingerprint':model_runtime_fingerprint(model),
                 'adoption_id':adoption['id'],'scope':adoption['scope'],'process_template_ref':copy.deepcopy(adoption['process_template_ref']),
                 'requirement_ids':adoption.get('requirement_ids',[r['id'] for r in doc.get('requirements',[])]),'confirmation':{'confirmed':True,'actor_id':actor['user_id'],'confirmed_at':_now()}}
        package['fingerprint']=digest(_json(package).encode())
        doc['taskbook_input_packages'].append(package)
        unit.update(input_package_id=package_id,selected_run_id=None,selected_revision_id=None)
        store._save(conn,doc,'confirm_taskbook_inputs',actor['user_id'],{'task_id':tid,'package_id':package_id,'fingerprint':package['fingerprint']})
        result={'package':public_value(package),'project_version':doc['project']['version']}
        store._remember(conn,tid+':packages',actor['user_id'],key,fp,result)
        return result

def model_runtime_fingerprint(model):
    from jonhon_taskbook import llm_client
    try:
        config=llm_client._resolve_model_config(llm_client.ModelSelection(provider=model.get('provider',''),model=model.get('name',''),model_id=model.get('id','')))
        fields=('provider','endpoint','model','model_id','api_version','timeout_seconds','max_tokens')
        return digest(_json({key:getattr(config,key,None) for key in fields}).encode())
    except (RuntimeError,ValueError,TypeError):
        return digest(_json({'unavailable':True,'selection':model}).encode())


def verify_package(package):
    frozen={k:v for k,v in package.items() if k not in {'fingerprint','status'}}
    if package.get('fingerprint')!=digest(_json(frozen).encode()):
        raise RdError(409,'固定输入包参数或引用校验失败，请重新确认')
    if package['runtime_fingerprint']!=runtime_fingerprint():
        raise RdError(409,'受控运行环境已变化，请重新确认输入包')
    if package.get('model_runtime_fingerprint') and package['model_runtime_fingerprint']!=model_runtime_fingerprint(package['model_selection']):
        raise RdError(409,'固定模型的请求配置已变化，请重新确认输入包')
    for item in package['source_refs']+[package[k] for k in ('template_ref','profile_ref','mapping_ref') if package.get(k)]:
        try:actual=digest(Path(item['file_ref']).read_bytes())
        except OSError as exc:raise RdError(409,'固定输入文件缺失，请重新确认资料') from exc
        if actual!=item['sha256']:raise RdError(409,'固定输入文件校验失败，禁止生成或送审')
    return package
