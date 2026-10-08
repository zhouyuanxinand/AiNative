"""HTTP CRUD for historical product failures and improvement experience."""
import asyncio
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from jonhon_taskbook.failure_database import FailureConflictError, get_failure_database

router = APIRouter(prefix="/api/failures")


async def _call(method, *args, **kwargs):
    try:
        result = await asyncio.to_thread(lambda: getattr(get_failure_database(), method)(*args, **kwargs))
        return JSONResponse(result)
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except FailureConflictError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def _body(request):
    body = await request.body()
    if len(body) > 256 * 1024:
        raise ValueError("记录内容过长，请精简后重试。")
    try:
        result = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("请求内容不是有效的 JSON。") from exc
    if not isinstance(result, dict):
        raise ValueError("请提交完整的故障记录。")
    return result


@router.get("")
async def search(q: str = Query("", max_length=500), product_type: str = Query("", max_length=120),
                 series: str = Query("", max_length=200), page: int = Query(1, ge=1),
                 page_size: int = Query(20, ge=1, le=100)):
    return await _call("search", q=q, product_type=product_type, series=series, page=page, page_size=page_size)


@router.get("/options")
async def options():
    return await _call("options")


@router.get("/{record_id}")
async def detail(record_id: int):
    return await _call("get", record_id)


@router.post("")
async def create(request: Request):
    try:
        payload = await _body(request)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return await _call("create", payload)


@router.put("/{record_id}")
async def update(record_id: int, request: Request):
    try:
        payload = await _body(request)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return await _call("update", record_id, payload)


@router.delete("/{record_id}")
async def delete(record_id: int, expected_version: int = Query(..., ge=1)):
    return await _call("delete", record_id, expected_version)
