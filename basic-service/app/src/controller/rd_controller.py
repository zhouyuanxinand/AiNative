"""Project and scenario HTTP boundary; business decisions live in RdStore."""
from __future__ import annotations

import asyncio
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

from src.common.admin_access_store import get_admin_access_store
from src.common.admin_auth import ADMIN_COOKIE, admin_auth_settings
from src.common.platform_auth import external_origin, get_auth_settings, get_current_user
from src.service.rd_platform.catalog import get_catalog
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


def _store(request: Request) -> Store:
    return request.app.state.rd_store


def _key(request: Request) -> str:
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 128:
        raise HTTPException(400, "请提供不超过128字符的Idempotency-Key")
    return key


async def _workspace_manager(request: Request) -> str | None:
    # Local resource editing requires an explicit development switch. OA modes
    # always use the existing opaque admin session, never the displayed name.
    settings = get_auth_settings(request)
    if (not settings.enabled and os.getenv("JTB_RD_LOCAL_WORKSPACE_ADMIN") == "1"
            and request.client and request.client.host in {"127.0.0.1", "::1"}):
        return _actor(request)
    token = request.cookies.get(ADMIN_COOKIE, "")
    if not token:
        return None
    admin_settings = admin_auth_settings(settings)
    try:
        origin = external_origin(request, admin_settings)
        access = get_admin_access_store(request.app.state.config.logs_dir.parent / "runtime")
        user = await asyncio.to_thread(access.lookup_session, token,
            app_id=admin_settings.app_id, base_url=admin_settings.platform_base_url, origin=origin)
    except ValueError:
        return None
    return str(user["userid"]) if user is not None else None


@router.get("/catalog")
async def catalog():
    return get_catalog()


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


@router.post("/projects/{pid}/commands")
async def command(pid: str, payload: Command, request: Request):
    key = _key(request)
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
    source = next(s for s in case["sources"] if s["id"] == sid)
    return FileResponse(path, filename=source["name"], headers=_HEADERS)


@router.get("/projects/{pid}/cases/{cid}/workpackages/{wid}/artifacts/{aid}")
async def artifact_file(pid: str, cid: str, wid: str, aid: str, request: Request):
    path = await asyncio.to_thread(_store(request).artifact_path, _actor(request), pid, cid, wid, aid)
    project = await asyncio.to_thread(_store(request).get_project, _actor(request), pid)
    case = next(c for c in project["cases"] if c["id"] == cid)
    workpackage = next(w for w in case["workpackages"] if w["id"] == wid)
    artifact = next(a for a in workpackage["artifacts"] if a["id"] == aid)
    return FileResponse(path, filename=artifact["name"], headers=_HEADERS)


@router.get("/workspace/resources")
async def resources(request: Request):
    return {"resources": await asyncio.to_thread(_store(request).list_resources),
            "can_manage": bool(await _workspace_manager(request))}


@router.post("/workspace/resources")
async def save_resource(request: Request):
    manager = await _workspace_manager(request)
    if not manager:
        raise HTTPException(403, "请通过管理员OA登录后管理Workspace资源")
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(400, "资源参数必须为对象")
    return await asyncio.to_thread(_store(request).save_resource, manager,
                                  payload, can_manage=True)


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
    application.state.rd_store = Store(root / "rd.sqlite3", root / "assets")


def start_rd_worker(application):
    from src.service.rd_platform.executors import execute
    from src.service.rd_platform.runtime import Worker
    worker = Worker(application.state.rd_store, execute)
    application.state.rd_worker = worker
    worker.start()
    return worker
