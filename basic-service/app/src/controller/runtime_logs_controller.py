"""Read-only endpoint for the latest bounded application logs."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

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
