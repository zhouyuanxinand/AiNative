"""Read-only endpoint for the latest bounded application logs."""
from __future__ import annotations

import asyncio
import sqlite3
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src.common.request_log_store import MAX_REQUEST_LOG_PAGE, get_request_log_store
from src.common.runtime_logs import DEFAULT_LOG_LIMIT, MAX_LOG_LIMIT, read_latest_logs

router = APIRouter(prefix="/api/logs", tags=["runtime-logs"])
_NO_CACHE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _response(data, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers=_NO_CACHE)


def _allowed(request: Request) -> bool:
    return (
        request.headers.get("X-Log-Viewer") == "1"
        and request.headers.get("Sec-Fetch-Site") != "cross-site"
    )


@router.get("/latest")
async def latest_logs(
    request: Request,
    limit: int = Query(DEFAULT_LOG_LIMIT, ge=1, le=MAX_LOG_LIMIT),
):
    if not _allowed(request):
        return _response({"error": "请从平台的日志查看入口访问。"}, 403)
    try:
        payload = await asyncio.to_thread(
            read_latest_logs,
            request.app.state.config.logs_dir,
            limit,
        )
    except OSError:
        return _response({"error": "运行日志暂时无法读取，请稍后重试。"}, 503)
    return _response(payload)


@router.get('/requests')
async def request_logs(
    request: Request,
    status: Literal['running', 'success', 'failed'] | None = None,
    q: str | None = Query(None, max_length=300),
):
    if not _allowed(request):
        return _response({'error': '请从平台的日志查看入口访问。'}, 403)

    def read():
        return get_request_log_store(request.app.state.config.logs_dir).list_requests(status=status, q=q)

    try:
        payload = await asyncio.to_thread(read)
    except (OSError, sqlite3.Error):
        return _response({'error': '请求日志暂时无法读取，请稍后重试。'}, 503)
    return _response(payload)


@router.get('/requests/{request_id}')
async def request_log_detail(
    request: Request,
    request_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(MAX_REQUEST_LOG_PAGE, ge=1, le=MAX_REQUEST_LOG_PAGE),
):
    if not _allowed(request):
        return _response({'error': '请从平台的日志查看入口访问。'}, 403)

    def read():
        return get_request_log_store(request.app.state.config.logs_dir).detail(request_id, after=after, limit=limit)

    try:
        payload = await asyncio.to_thread(read)
    except (OSError, sqlite3.Error):
        return _response({'error': '请求日志暂时无法读取，请稍后重试。'}, 503)
    if payload is None:
        return _response({'error': '该请求日志不存在或已超过保留数量被自动清理。'}, 404)
    return _response(payload)
