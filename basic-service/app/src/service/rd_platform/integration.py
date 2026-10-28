"""Trusted bridge between R&D tasks and the existing document job service."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

_JOB_PATH = re.compile(r"^/api/(?:status|stream|cancel|download|report|input_evidence|indicator_review|review)/([^/]+)(?:/|$)")
_OFFICE_PATH = re.compile(r"^/api/review/([^/]+)/editor/([a-f0-9]{32})/(file|callback)$")


def get_rd_store():
    from .runtime import get_store
    return get_store()


def _error(status: int, detail: str):
    from src.service.rd_platform.store import RdError
    return RdError(status, detail)


def verified_actor(request: Request) -> dict:
    from src.common.platform_auth import get_current_user
    user = get_current_user(request)
    if not user or user.get("verified") is not True or not user.get("userid"):
        raise HTTPException(401, "研发项目操作需要已验证的企业身份")
    return {"user_id": user["userid"], "display_name": user.get("display_name") or user.get("name") or user["userid"]}


def review_actor(request: Request, jid: str, fallback: str = "web-user") -> str:
    """Legacy actor fields remain compatible, but never attribute bound work."""
    if get_rd_store().generation(jid):
        return verified_actor(request)["user_id"]
    return fallback


class RdJobAccessMiddleware(BaseHTTPMiddleware):
    """Register inside identity middleware; guard every legacy job subresource."""
    def __init__(self, app, store_getter=None):
        super().__init__(app)
        self.store_getter = store_getter or get_rd_store

    async def dispatch(self, request, call_next):
        match = _JOB_PATH.match(request.url.path)
        if not match:
            return await call_next(request)
        jid = match.group(1)
        store = self.store_getter()
        binding=store.generation(jid)
        if not binding:
            return await call_next(request)
        try:
            office = _OFFICE_PATH.fullmatch(request.url.path)
            if office and (request.method, office.group(3)) in {("GET", "file"), ("POST", "callback")}:
                # These requests carry signed capabilities rather than cookies.
                # Identity comes from the session created by the verified opener.
                from src.controller.review_editor_controller import _editor
                session = _editor()._session(jid, office.group(2))
                actor_id = session.get("rd_actor_id")
                if not actor_id:
                    raise HTTPException(401, "项目编辑会话缺少已验证身份，请重新打开")
                store.authorize_generation(jid, actor_id, write=office.group(3) == "callback")
                request.state.rd_actor_id = actor_id
            else:
                actor = verified_actor(request)
                store.authorize_generation(jid, actor["user_id"], write=request.method not in {"GET", "HEAD", "OPTIONS"})
                request.state.rd_actor_id = actor["user_id"]
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        except Exception as exc:
            if hasattr(exc, "status"):
                return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=exc.status)
            if hasattr(exc, "status_code"):
                return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)
            raise
        response=await call_next(request)
        # The Office opener deliberately returns scoped signed capabilities to
        # its verified client. Preserve that exact signed configuration.
        if binding.get('inputs',{}).get('package_id') and request.url.path!=f'/api/review/{jid}/editor' and 'application/json' in response.headers.get('content-type',''):
            body=b''.join([chunk async for chunk in response.body_iterator])
            try:payload=json.loads(body)
            except (ValueError,UnicodeError):return Response(body,status_code=response.status_code,headers=dict(response.headers))
            headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-length','content-type'}}
            return JSONResponse(native_public_payload(payload),status_code=response.status_code,headers=headers)
        return response


def native_public_payload(value):
    from .taskbook_inputs import public_value
    from src.common.runtime_logs import redact_log_text
    def scrub(item):
        if isinstance(item,dict):return {k:scrub(v) for k,v in public_value(item).items()}
        if isinstance(item,list):return [scrub(v) for v in item]
        if not isinstance(item,str):return item
        text=redact_log_text(item)
        # Server diagnostics can contain paths inside free-form log strings.
        text=re.sub(r'[A-Za-z]:[\\/][^\r\n]*','[受控文件]',text)
        if text.startswith('/') and not text.startswith('/api/') and not text.startswith('//'):
            return '[受控文件]'
        return text
    return scrub(value)


def native_job_payload(jid,value):
    binding=get_rd_store().generation(jid)
    return native_public_payload(value) if binding and binding.get('inputs',{}).get('package_id') else value


def history_visible(request: Request, jid: str) -> bool:
    store = get_rd_store()
    if not store.generation(jid):
        return True
    try:
        store.authorize_generation(jid, verified_actor(request)["user_id"])
        return True
    except Exception as exc:
        if isinstance(exc, HTTPException) or hasattr(exc, "status"):
            return False
        raise


def validate_submission(store, actor, pid, tid, baseline_id, confirmed):
    if not pid or not tid:
        raise _error(422, "项目与任务必须同时指定")
    detail = store.detail(pid, actor["user_id"])
    task = next((item for item in detail["tasks"] if item["id"] == tid), None)
    if not task:
        raise _error(404, "研发任务不存在")
    if task["assignee_id"] != actor["user_id"]:
        raise _error(403, "仅当前任务执行人可以生成任务书")
    if task.get('kind')=='taskbook':
        raise _error(409,'原生任务书须通过固定输入包运行入口办理')
    if task.get('kind')=='plan_item':
        store._assignee(detail,task,actor['user_id'])
        valid_baseline=bool(baseline_id and task['baseline_id']==baseline_id)
    else:
        valid_baseline=bool(baseline_id and baseline_id==detail['project']['current_baseline_id'] and task['baseline_id']==baseline_id)
    if not valid_baseline:
        raise _error(409, "需求基线已变化，请重新核对并采用当前基线")
    if task["status"] != "in_progress":
        raise _error(409, "请先开始任务，再生成任务书")
    if not confirmed:
        raise _error(422, "请确认上传资料与当前需求基线一致")
    return task


def submission_error(exc):
    if isinstance(exc, HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if hasattr(exc, "status"):
        return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=exc.status)
    raise exc


def prepare_submission(request, pid, tid, baseline_id, confirmed):
    if not pid and not tid:
        if any(request.query_params.get(key) for key in ("rd_project", "rd_task")):
            raise _error(422, "项目上下文必须随上传表单提交")
        return None
    actor = verified_actor(request)
    store = get_rd_store()
    validate_submission(store, actor, pid, tid, baseline_id, confirmed.lower() == "true")
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 256:
        raise _error(422, "项目生成需要有效的 Idempotency-Key")
    return {"store": store, "actor": actor, "pid": pid, "tid": tid, "baseline_id": baseline_id, "key": key}


def submission_fingerprint(payloads, parameters):
    inputs = {"files": {key: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                         for key, data in sorted(payloads.items())}, "parameters": parameters,
              "rd_baseline_id": parameters["rd_baseline_id"], "inputs_confirmed": True}
    inputs["fingerprint"] = hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return inputs


def enqueue_bound_job(context, inputs, payloads, filenames, background_tasks, selection, options, use_llm, edit_plan, fail_on_regression,
                      *, parent_jid=None, indicator_clarifications=None):
    from filelock import FileLock
    from src.controller import taskbook_controller as jobs
    store, actor = context["store"], context["actor"]
    intent_parts = [context["pid"], context["tid"], actor["user_id"], context["key"]]
    if parent_jid:
        intent_parts.extend(["indicator_clarification", parent_jid])
    intent = json.dumps(intent_parts, ensure_ascii=False)
    jid = hashlib.sha256(intent.encode()).hexdigest()[:10]
    locks = Path(store.artifact_root) / ".submission-locks"
    locks.mkdir(parents=True, exist_ok=True)
    with FileLock(str(locks / (jid + ".lock")), timeout=30):
        binding = store.generation(jid)
        if binding:
            store.authorize_generation(jid, actor["user_id"], write=True)
            if (binding["project_id"] != context["pid"] or binding["task_id"] != context["tid"]
                    or binding.get("inputs", {}).get("fingerprint") != inputs["fingerprint"]):
                raise _error(409, "同一生成请求键对应的资料已变化，请发起新的生成")
            job = jobs._get_job(jid)
            if not job or job.get("restored_from_manifest") and job.get("status") not in {"done", "blocked", "error", "cancelled"}:
                raise _error(409, "该生成已中断，请使用新的请求键明确重试")
            return JSONResponse({"jid": jid, **({"parent_jid": parent_jid} if parent_jid else {})})
        validate_submission(store, actor, context["pid"], context["tid"], context["baseline_id"], True)
        # Persist the binding before creating any externally reachable job.
        store.bind_generation(context["pid"], context["tid"], actor, jid, inputs)
        jobdir = jobs._STATE.upload_dir / jid
        jobdir.mkdir(parents=False, exist_ok=False)
        names = {"tech": "tech" + Path(filenames["tech"] or "").suffix.lower(),
                 "spec": "spec" + Path(filenames["spec"] or "").suffix.lower(),
                 "baseline_docx": "baseline_docx.docx", "baseline_json": "baseline.json"}
        paths = {key: str(jobdir / names[key]) for key in payloads}
        for key, data in payloads.items():
            Path(paths[key]).write_bytes(data)
        jobs._register_job(jid, selection=selection, **options)
        jobs._STATE.jobs[jid]["result"]["meta"].update({
            "original_filenames": {key: Path(value or (key + ".docx")).name for key, value in filenames.items()},
            "rd_project": context["pid"], "rd_task": context["tid"], "rd_baseline_id": context["baseline_id"],
        })
        if parent_jid:
            jobs._STATE.jobs[jid]["result"]["meta"].update({"parent_jid": parent_jid,
                "indicator_clarifications": indicator_clarifications or {}})
        background_tasks.add_task(jobs._run_job, jid, paths["tech"], paths["spec"], selection,
                                  jobs._make_output_path(), use_llm, template_edit_plan=edit_plan,
                                  template_edit_confirmed=bool(edit_plan), baseline_docx=paths.get("baseline_docx"),
                                  baseline_json=paths.get("baseline_json"), fail_on_regression=fail_on_regression,
                                  **({"indicator_clarifications": indicator_clarifications} if parent_jid else {}), **options)
        return JSONResponse({"jid": jid, **({"parent_jid": parent_jid} if parent_jid else {})})


def capture_artifact(store, pid, tid, actor, jid, revision_id, expected_version, key):
    binding = store.generation(jid)
    if not binding or binding["project_id"] != pid or binding["task_id"] != tid:
        raise _error(409, "生成作业未绑定到本项目任务，不能认领历史作业")
    store.authorize_generation(jid, actor["user_id"], write=True)
    detail = store.detail(pid, actor["user_id"])
    task = next((item for item in detail["tasks"] if item["id"] == tid), None)
    if task and task.get('kind')=='taskbook':
        raise _error(409,'原生任务书须通过固定包送审入口登记成果')
    if task and task.get('kind')=='plan_item':
        store._assignee(detail,task,actor['user_id'])
        valid_baseline=task['baseline_id']==binding['baseline_id']
    else:
        valid_baseline=bool(task and task['baseline_id']==binding['baseline_id'] and detail['project']['current_baseline_id']==binding['baseline_id'])
    if not valid_baseline:
        raise _error(409, "生成作业采用的需求基线已过期，请重新生成")
    return store.register_artifact(pid, tid, actor, prepare_artifact_payload(store, jid, revision_id), expected_version, key)


def prepare_artifact_payload(store, jid, revision_id):
    """Copy exact QA-checked revision bytes; caller enforces project ownership."""
    from src.controller import review_controller
    try:
        bundle = review_controller.ensure_review(jid)
        reviews = review_controller.get_store()
        # ReviewStore revisions are immutable. Read metadata and exact bytes from
        # the same revision; never use the mutable current_revision pointer.
        revision = reviews.revision(jid, revision_id)
        source = reviews.revision_path(jid, revision_id)
        checks = revision.get("checks") or {}
        if not (checks.get("status") == "passed" and checks.get("revision_id") == revision_id
                and checks.get("sha256") == revision["sha256"]
                and checks.get("scope") == "revision_deterministic"):
            raise _error(409, "所选修订尚无完整通过的对应版本 QA 检查，请先检查该修订")
        assets = [{key: item.get(key) for key in ("id", "role", "name", "sha256")}
                  for item in bundle.get("assets", []) if item.get("available")]
        rules = [item for item in assets if item["role"] in {"rule", "profile", "template", "mapping"}]
        quality_evidence = {
            "revision_id": revision_id, "sha256": revision["sha256"], "checks": checks,
            "generation_summary": bundle.get("generation_summary", {}), "generation_status": bundle.get("generation_status"),
            "selection": bundle.get("selection", {}), "archived_assets": assets,
            "rules_fingerprint": hashlib.sha256(json.dumps(rules, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        }
        root = Path(store.artifact_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=root, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            shutil.copyfile(source, temporary)
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            if digest != revision["sha256"]:
                raise _error(409, "修订文件校验不一致，未登记成果")
            target = root / (digest + ".docx")
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise _error(409, "已有成果文件哈希不一致")
            if not target.exists():
                os.replace(temporary, target)
            return {
                "jid": jid, "source_revision_id": revision_id, "filename": source.name,
                "sha256": digest, "file_ref": str(target), "quality_status": "passed",
                "quality_evidence": quality_evidence,
            }
        finally:
            temporary.unlink(missing_ok=True)
    except (FileNotFoundError, ValueError) as exc:
        if hasattr(exc, "status"):
            raise
        raise _error(409, "无法读取经过校验的修订文件：" + str(exc)) from exc
