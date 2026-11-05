"""Project and scenario HTTP boundary; business decisions live in RdStore."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from src.common.platform_auth import external_origin, get_auth_settings, get_current_user
from src.service.rd_platform.store import RdError, Store

logger = logging.getLogger(__name__)
_COOKIE = "jtb_rd_local_client"
_LOCAL_ID = re.compile(r"^[a-f0-9]{32}$")
_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _actor(request: Request) -> str:
    if getattr(request.state, "rd_actor", None):
        return request.state.rd_actor
    settings = get_auth_settings(request)
    user = get_current_user(request)
    if settings.enabled:
        if not user:
            raise HTTPException(401, "请先通过OA／问学登录")
        actor = str(user["userid"])
    else:
        token = request.cookies.get(_COOKIE, "")
        if not _LOCAL_ID.fullmatch(token):
            token = uuid.uuid4().hex
            request.state.rd_new_cookie = token
        actor = "local:" + token
    request.state.rd_actor = actor
    return actor


def _same_origin(request: Request):
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise HTTPException(403, "请从研发平台页面操作")
    origin = request.headers.get("Origin")
    if origin:
        try:
            allowed = external_origin(request, get_auth_settings(request))
        except ValueError:
            raise HTTPException(403, "访问来源未获准") from None
        if urlsplit(origin).netloc != urlsplit(allowed).netloc or urlsplit(origin).scheme != urlsplit(allowed).scheme:
            raise HTTPException(403, "访问来源未获准")


class RdRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request: Request):
            try:
                _actor(request)
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    _same_origin(request)
                response = await original(request)
            except RdError as exc:
                response = JSONResponse({"error": str(exc.detail)}, status_code=exc.status, headers=_HEADERS)
            except (OSError, sqlite3.Error):
                logger.exception("rd_storage_unavailable")
                response = JSONResponse({"error": "研发数据暂时无法读写，请稍后重试"}, status_code=503)
            response.headers.update(_HEADERS)
            token = getattr(request.state, "rd_new_cookie", None)
            if token:
                response.set_cookie(_COOKIE, token, httponly=True, samesite="lax",
                                    secure=request.url.scheme == "https", max_age=365 * 86400)
            return response
        return handle


router = APIRouter(prefix="/api/rd", tags=["research-development"], route_class=RdRoute)


class CreateProject(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=200)
    context: dict[str, str] = Field(default_factory=dict)
    brief: str = Field(default="", max_length=4000)
    customer_name: str = Field(default="", max_length=200)
    product_name: str = Field(default="", max_length=200)


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=1)
    command: str = Field(min_length=1, max_length=80)
    data: dict = Field(default_factory=dict)


class AssistantQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=2000)
    topic: str = Field(default="", max_length=100)


class SourceAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=1)


class SourceClassificationFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)


class SourceClassificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: str = Field(max_length=200)
    name: str = Field(max_length=200)
    id: str = Field(max_length=200)


class SourceClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    files: list[SourceClassificationFile] = Field(min_length=1, max_length=50)
    model_selection: SourceClassificationModel | None = None
    use_model: bool = False


def _store(request: Request) -> Store:
    return request.app.state.rd_store


def _key(request: Request) -> str:
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 128:
        raise HTTPException(400, "请提供不超过128字符的Idempotency-Key")
    return key


def _workspace_permissions(request: Request) -> dict:
    """Capability roles use verified actor IDs, independently of RD admin roles."""
    actor = _actor(request)
    settings = get_auth_settings(request)
    local_bootstrap = bool(not settings.enabled and os.getenv("JTB_RD_LOCAL_WORKSPACE_ADMIN") == "1"
                           and request.client and request.client.host in {"127.0.0.1", "::1"})
    def has_role(name):
        return actor in {entry.strip() for entry in os.getenv(name, "").split(",") if entry.strip()}
    publisher = local_bootstrap or has_role("JTB_RD_WORKSPACE_PUBLISHERS")
    return {"application_id": _store(request).workspace.application_id,
            "can_edit_resources": publisher, "can_publish_resources": publisher,
            "can_manage_application_grants": local_bootstrap or has_role("JTB_RD_WORKSPACE_GRANT_MANAGERS"),
            "local_bootstrap": local_bootstrap}


async def _workspace_payload(request: Request) -> dict:
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "资源参数必须为JSON对象") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "资源参数必须为对象")
    if {"application_id", "app_id", "can_manage", "permissions", "roles"} & payload.keys():
        raise HTTPException(422, "应用身份及权限由服务端确定，不能由请求指定")
    return payload


def _governance_permissions(request: Request) -> dict:
    actor = _actor(request)
    local = bool(not get_auth_settings(request).enabled
                 and os.getenv('JTB_RD_LOCAL_WORKSPACE_ADMIN') == '1'
                 and request.client and request.client.host in {'127.0.0.1', '::1'})
    def role(name):
        return local or actor in {v.strip() for v in os.getenv(name, '').split(',') if v.strip()}
    workflows = role('JTB_RD_WORKFLOW_PUBLISHERS')
    templates = role('JTB_RD_TEMPLATE_PUBLISHERS')
    return {'can_edit_workflows': workflows, 'can_publish_workflows': workflows,
            'can_prepare_templates': templates, 'can_publish_templates': templates,
            'can_review_templates': role('JTB_RD_TEMPLATE_REVIEWERS'), 'local_bootstrap': local}


def _require_governance(request: Request, permission: str) -> str:
    _same_origin(request)
    if not _governance_permissions(request).get(permission):
        raise HTTPException(403, '当前主体没有此治理操作权限')
    return _actor(request)


@router.get('/governance/session')
async def governance_session(request: Request):
    return _governance_permissions(request)


@router.get('/workflow-templates')
async def workflow_templates(request: Request, category: str | None = None,
                             q: str = Query(default='', max_length=200),
                             page: int = Query(default=1, ge=1),
                             page_size: int = Query(default=5, ge=1, le=50), management: bool = False):
    return await asyncio.to_thread(_store(request).workflow_templates.list, _actor(request),
        _governance_permissions(request), category=category, q=q, page=page, page_size=page_size, management=management)


@router.post('/workflow-templates/validate')
async def validate_workflow_template(request: Request):
    _same_origin(request)
    permissions = _governance_permissions(request)
    if not any(permissions.get(name) for name in ('can_edit_workflows', 'can_publish_workflows')):
        raise HTTPException(403, '当前主体没有流程模板校验权限')
    payload = await _workspace_payload(request)
    if {'actor', 'publisher', 'reviewer', 'status'} & payload.keys():
        raise HTTPException(422, '主体和发布状态由服务端确定')
    return await asyncio.to_thread(_store(request).workflow_templates.validate, _actor(request), permissions, payload)


@router.get('/workflow-templates/{rid}/history')
async def workflow_template_history(request: Request, rid: str,
                                    page: int = Query(default=1, ge=1),
                                    page_size: int = Query(default=5, ge=1, le=50), management: bool = False):
    return await asyncio.to_thread(_store(request).workflow_templates.history, _actor(request), rid,
        _governance_permissions(request), management=management, page=page, page_size=page_size)


@router.get('/workflow-templates/{rid}/{version}')
async def workflow_template(request: Request, rid: str, version: str, management: bool = False):
    fixed_version = None if version == 'latest' else str(_resource_version(version))
    return await asyncio.to_thread(_store(request).workflow_templates.detail, _actor(request), rid,
        fixed_version, _governance_permissions(request), management=management)


@router.post('/workflow-templates')
async def save_workflow_template(request: Request):
    _same_origin(request)
    permissions = _governance_permissions(request)
    if not any(permissions.get(name) for name in ('can_edit_workflows', 'can_publish_workflows')):
        raise HTTPException(403, '当前主体没有此治理操作权限')
    payload = await _workspace_payload(request)
    if {'actor', 'publisher', 'reviewer', 'status'} & payload.keys():
        raise HTTPException(422, '主体和发布状态由服务端治理操作确定')
    return await asyncio.to_thread(_store(request).workflow_templates.save, _actor(request),
        permissions, payload, _key(request))


def _resource_version(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]{0,8}", value):
        raise HTTPException(422, "资源固定版本必须为正整数")
    return int(value)


@router.get("/catalog")
async def catalog(request: Request):
    return await asyncio.to_thread(_store(request).workspace.filtered_catalog)


@router.get("/catalog/resources")
async def catalog_resources(request: Request, q: str = Query(default="", max_length=200),
                            kind: str | None = None, page: int = Query(default=1, ge=1),
                            page_size: int = Query(default=5, ge=1, le=50)):
    return await asyncio.to_thread(_store(request).workspace.catalog_list,
                                   q=q, kind=kind, page=page, page_size=page_size)


@router.get("/catalog/resources/{rid}/{version}")
async def catalog_resource(request: Request, rid: str, version: str):
    return await asyncio.to_thread(_store(request).workspace.catalog_detail, rid, _resource_version(version))


def _report_catalog():
    # Document assets retain their existing catalog owner and access policy.
    from src.controller import taskbook_controller
    registry = taskbook_controller._STATE.template_versions
    if registry is None:
        raise RdError(503, "受控文档目录暂未就绪。")
    return registry.catalog_items()


@router.get("/catalog/items")
async def catalog_items(request: Request, category: str, q: str = Query(default="", max_length=200),
                        page: int = Query(default=1, ge=1), page_size: int = Query(default=5, ge=1, le=50)):
    if category != "reports":
        return await asyncio.to_thread(_store(request).workspace.catalog_items, category,
                                       q=q, page=page, page_size=page_size)
    entries = await asyncio.to_thread(_report_catalog)
    query = q.strip().casefold()
    items = sorted((item for item in entries if not query or query in " ".join(
        str(item.get(key, "")) for key in ("product_type", "product_domain", "filename")).casefold()),
        key=lambda item: (str(item.get("product_type_id", "")), str(item.get("product_domain_id", ""))))
    return {"items": items[(page - 1) * page_size:page * page_size], "page": page, "page_size": page_size,
            "total": len(items), "total_pages": (len(items) + page_size - 1) // page_size}


@router.get("/session")
async def session(request: Request):
    return {"actor_id": _actor(request), "local_mode": not get_auth_settings(request).enabled}


@router.get("/projects")
async def projects(request: Request):
    return {"projects": await asyncio.to_thread(_store(request).list_projects, _actor(request))}


@router.post("/projects")
async def create_project(payload: CreateProject, request: Request):
    return await asyncio.to_thread(_store(request).create_project, _actor(request),
        payload.title, payload.context, request.headers.get("Idempotency-Key") or None,
        brief=payload.brief, customer_name=payload.customer_name, product_name=payload.product_name)


@router.get("/projects/{pid}")
async def project(pid: str, request: Request):
    return await asyncio.to_thread(_store(request).get_project, _actor(request), pid)


@router.delete("/projects/{pid}")
async def delete_project(pid: str, request: Request, expected_version: int = Query(..., ge=1)):
    return await asyncio.to_thread(_store(request).delete_project, _actor(request), pid, expected_version, _key(request))


@router.post("/projects/{pid}/commands")
async def command(pid: str, payload: Command, request: Request):
    key = _key(request)
    from src.service.rd_platform.review_records import ReviewRecords
    if get_auth_settings(request).enabled and payload.command in ReviewRecords.DECISION_COMMANDS:
        raise RdError(403, "OA部署尚未配置企业工程决定政策，不能用本地演练记录代替正式审签。")
    return await asyncio.to_thread(_store(request).command, _actor(request), pid,
        payload.expected_version, key, payload.command, payload.data)


@router.post("/projects/{pid}/cases/{cid}/sources")
async def upload_source(pid: str, cid: str, request: Request, expected_version: int = Form(...),
                        role: str = Form(...), file: UploadFile = File(...)):
    key = _key(request)
    maximum = request.app.state.config.max_upload_bytes
    content = await file.read(maximum + 1)
    await file.close()
    if len(content) > maximum:
        raise HTTPException(413, "文件超过平台上传限制")
    return await asyncio.to_thread(_store(request).add_source, _actor(request), pid, cid,
        expected_version, key, role, file.filename or "source", content)


@router.post("/projects/{pid}/cases/{cid}/sources/batch")
async def upload_source_batch(pid: str, cid: str, request: Request, expected_version: int = Form(..., ge=1),
                              manifest: str = Form(..., max_length=64000), files: list[UploadFile] = File(...)):
    key = _key(request)
    maximum = request.app.state.config.max_upload_bytes
    uploaded, total = [], 0
    try:
        try:
            items = json.loads(manifest)
        except json.JSONDecodeError:
            raise HTTPException(422, "manifest须为有效JSON数组") from None
        if not 1 <= len(files) <= 50:
            raise HTTPException(422, "每批须包含1至50份资料")
        for file in files:
            content = await file.read(maximum + 1)
            total += len(content)
            if len(content) > maximum:
                raise HTTPException(413, "文件超过平台上传限制")
            if total > maximum:
                raise HTTPException(413, "整批资料超过平台上传限制，请拆分批次后上传")
            uploaded.append((file.filename or "source", content))
    finally:
        for file in files:
            await file.close()
    return await asyncio.to_thread(_store(request).add_sources, _actor(request), pid, cid,
                                   expected_version, key, items, uploaded)


@router.post("/projects/{pid}/cases/{cid}/sources/classify")
async def classify_source_names(pid: str, cid: str, payload: SourceClassificationRequest, request: Request):
    return await asyncio.to_thread(_store(request).classify_source_names, _actor(request), pid, cid,
        [file.model_dump() for file in payload.files],
        model_selection=payload.model_selection.model_dump() if payload.model_selection is not None else None,
        use_model=payload.use_model)


@router.post("/projects/{pid}/cases/{cid}/analysis")
async def analyze_sources(pid: str, cid: str, payload: SourceAnalysisRequest, request: Request):
    return await asyncio.to_thread(_store(request).analyze_sources, _actor(request), pid, cid,
                                   payload.expected_version, _key(request))


@router.get("/projects/{pid}/cases/{cid}/sources/{sid}")
async def source_file(pid: str, cid: str, sid: str, request: Request):
    store = _store(request)
    actor = _actor(request)
    path = await asyncio.to_thread(store.source_path, actor, pid, cid, sid)
    project = await asyncio.to_thread(store.get_project, actor, pid)
    case = next(c for c in project["cases"] if c["id"] == cid)
    source = next(s for s in case["sources"] + case.get("deleted_sources", []) if s["id"] == sid)
    return FileResponse(path, filename=source["name"], headers=_HEADERS)


@router.get("/projects/{pid}/cases/{cid}/workpackages/{wid}/artifacts/{aid}")
async def artifact_file(pid: str, cid: str, wid: str, aid: str, request: Request):
    path = await asyncio.to_thread(_store(request).artifact_path, _actor(request), pid, cid, wid, aid)
    project = await asyncio.to_thread(_store(request).get_project, _actor(request), pid)
    case = next(c for c in project["cases"] if c["id"] == cid)
    workpackage = next(w for w in case["workpackages"] if w["id"] == wid)
    artifact = next(a for a in workpackage["artifacts"] if a["id"] == aid)
    return FileResponse(path, filename=artifact["name"], headers=_HEADERS)


@router.get("/workspace/session")
async def workspace_session(request: Request):
    return _workspace_permissions(request)


@router.get("/workspace/resources")
async def resources(request: Request, q: str = Query(default="", max_length=200), kind: str | None = None,
                    page: int = Query(default=1, ge=1), page_size: int = Query(default=5, ge=1, le=50)):
    return await asyncio.to_thread(_store(request).workspace.management_list, _actor(request),
                                  _workspace_permissions(request), q=q, kind=kind, page=page, page_size=page_size)


@router.get("/workspace/resources/{rid}/{version}")
async def workspace_resource(request: Request, rid: str, version: str):
    return await asyncio.to_thread(_store(request).workspace.management_detail, _actor(request),
                                  _workspace_permissions(request), rid, None if version == "latest" else _resource_version(version))


@router.post("/workspace/resources")
async def save_resource(request: Request):
    permissions = _workspace_permissions(request)
    if not permissions["can_edit_resources"] and not permissions["can_publish_resources"]:
        raise HTTPException(403, "当前主体没有Workspace资源编辑或发布权限")
    return await asyncio.to_thread(_store(request).workspace.save_resource, _actor(request), permissions,
                                  await _workspace_payload(request), _key(request))


@router.post("/workspace/grants")
async def workspace_grant(request: Request):
    permissions = _workspace_permissions(request)
    if not permissions["can_manage_application_grants"]:
        raise HTTPException(403, "当前主体没有Workspace应用授权权限")
    return await asyncio.to_thread(_store(request).workspace.set_grant, _actor(request), permissions,
                                  await _workspace_payload(request), _key(request))


def _assistant(request: Request):
    assistant = getattr(request.app.state, "rd_assistant", None)
    if assistant is None:
        from src.service.rd_platform.assistant import CaseAssistant
        assistant = CaseAssistant(_store(request))
        request.app.state.rd_assistant = assistant
    return assistant


@router.get("/projects/{pid}/cases/{cid}/assistant")
async def assistant_history(pid: str, cid: str, request: Request, before: int | None = Query(default=None, ge=1)):
    return await asyncio.to_thread(_assistant(request).get, _actor(request), pid, cid, before=before)


@router.post("/projects/{pid}/cases/{cid}/assistant")
async def assistant_ask(pid: str, cid: str, payload: AssistantQuestion, request: Request):
    return await asyncio.to_thread(_assistant(request).ask, _actor(request), pid, cid,
                                  payload.message, _key(request), payload.topic)


@router.get("/contracts")
async def contracts():
    return {"execution_mode": "contract_example", "connected": False, "version": "1.0",
            "description": "接口契约示例；外部服务尚未接入，示例数据不能作为真实工作包证据",
            "boundaries": [
                {"id": "workpackage_source", "operations": ["list", "read_revision", "instantiate"]},
                {"id": "workspace", "operations": ["catalog", "execute", "events", "result", "cancel"]},
                {"id": "ontology_agent", "operations": ["start", "obligations", "events", "result", "cancel"]},
                {"id": "kbox", "operations": ["search", "read_evidence", "validity"]},
            ],
            "request_example": {"contract_version": "1.0", "execution_mode": "contract_example",
                "provider_id": "example", "input_hash": "<sha256>", "source_refs": [],
                "idempotency_key": "<stable-key>", "obligations": [],
                "business_selection": {"project_id": "<project-id>", "case_id": "<case-id>",
                    "binding_id": "<adoption-id>", "business_fingerprint": "<sha256>",
                    "requirement_revision": "<fixed-revision>",
                    "research_workflow": {"id": "<workflow-id>", "version": "<published-version>"},
                    "document_template": {"template_sha256": "<sha256>", "profile_sha256": "<sha256>",
                        "mapping_sha256": "<sha256>"}}},
            "current_inputs": {"mode": "manual_upload", "external_lookup_enabled": False,
                "ontology_owns": ["applicable_obligations", "evidence_resolution", "kbox_queries"],
                "workspace_owns": ["published_capabilities", "execution", "events", "results"],
                "rd_platform_owns": ["project", "confirmed_requirements", "comparisons", "adoption", "business_decisions"]},
            "response_example": {"execution_mode": "contract_example", "provider_id": "example",
                "status": "blocked", "blocked_reasons": ["尚未连接真实服务"], "evidence": []}}


def configure_rd(application, config):
    root = Path(os.environ.get("JTB_RD_DATA_DIR") or config.logs_dir.parent / "data" / "rd_platform")
    local_review = os.environ.get("JTB_RD_LOCAL_REVIEW") == "1" and getattr(getattr(application.state, "auth_settings", None), "enabled", True) is False
    application.state.rd_store = Store(root / "rd.sqlite3", root / "assets", local_review_enabled=local_review,
                                      application_id=os.environ.get("JTB_RD_WORKSPACE_APP_ID", "rd-platform-local"))


def start_rd_worker(application):
    from src.service.rd_platform.executors import execute
    from src.service.rd_platform.runtime import Worker
    worker = Worker(application.state.rd_store, execute)
    application.state.rd_worker = worker
    worker.start()
    return worker


from src.controller.platform_chat_controller import router as platform_chat_router

router.include_router(platform_chat_router)
