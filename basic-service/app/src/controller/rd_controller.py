"""Authenticated HTTP adapter for the R&D domain."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import Field

from src.service.rd_platform.runtime import get_store

from .rd_dependencies import Actor, RdRoute, RequestBody, RequestKey

router = APIRouter(prefix="/api/rd", tags=["研发管理"], route_class=RdRoute)


class ProjectBody(RequestBody):
    name: str = Field(min_length=1, max_length=1000)
    code: str | None = Field(default=None, max_length=1000)
    customer: str = Field(min_length=1, max_length=1000)
    product: str = Field(min_length=1, max_length=1000)


class CommandBody(RequestBody):
    action: str
    expected_version: int = Field(ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class CaptureBody(RequestBody):
    jid: str = Field(min_length=1, max_length=256)
    revision_id: str = Field(min_length=1, max_length=256)
    expected_version: int = Field(ge=1)


@router.get("/workspace")
def workspace(actor: Actor):
    return get_store().workspace(actor["user_id"])


@router.get("/projects")
def list_projects(actor: Actor, q: str = "", page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100)):
    return get_store().list_projects(actor["user_id"], q, page, page_size)


@router.post("/projects")
def create_project(body: ProjectBody, actor: Actor, request_key: RequestKey):
    return get_store().create_project(actor, body.model_dump(exclude_none=True), request_key)


@router.get("/projects/{pid}")
def project_detail(pid: str, actor: Actor):
    return get_store().detail(pid, actor["user_id"])


@router.post("/projects/{pid}/commands")
def project_command(pid: str, body: CommandBody, actor: Actor, request_key: RequestKey):
    return get_store().execute(pid, actor, body.action, body.payload, body.expected_version, request_key)


@router.post("/projects/{pid}/tasks/{tid}/artifacts")
def capture_artifact(pid: str, tid: str, body: CaptureBody, actor: Actor, request_key: RequestKey):
    from src.service.rd_platform.integration import capture_artifact as capture
    return capture(get_store(), pid, tid, actor, body.jid, body.revision_id, body.expected_version, request_key)


@router.get("/projects/{pid}/artifacts/{aid}/download")
def download_artifact(pid: str, aid: str, actor: Actor, approved: bool = False):
    artifact = get_store().artifact(pid, aid, actor["user_id"], approved)
    # Respond with the exact verified bytes: a path opened later by FileResponse
    # could change between the integrity check and actual streaming.
    try:
        content = Path(artifact["file_ref"]).read_bytes()
    except OSError as exc:
        raise HTTPException(404, "固定成果文件不存在") from exc
    if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
        raise HTTPException(409, "成果文件完整性校验失败，禁止下载")
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(artifact["filename"], safe=""), "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


def get_router():
    return router
