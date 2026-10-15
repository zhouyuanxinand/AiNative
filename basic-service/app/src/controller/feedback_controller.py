"""Public feedback receipts and a router reserved for the separate admin app."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from copy import deepcopy
from itertools import islice
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from jonhon_taskbook.feedback_store import (
    FeedbackConflictError,
    get_feedback_store,
    validate_create,
)

from src.common.platform_auth import get_auth_settings, get_current_user
from src.common.runtime_logs import redact_log_text
from src.controller import taskbook_controller

public_router = APIRouter(prefix="/api/feedback")
admin_router = APIRouter(prefix="/api/feedback-admin")
_BODY_LIMIT = 64 * 1024
_MANIFEST_LIMIT = 10000
_MANIFEST_BYTES = 8 * 1024 * 1024
logger = logging.getLogger(__name__)


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _filename(value):
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1][:500]


def _safe_text(value, limit=500):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    value = redact_log_text(str(value))
    value = re.sub(r"https?://[^\s]+|[A-Za-z]:[\\/][^\s]+|/(?:home|root|tmp|app|usr|var|opt)/[^\s]+", "[已隐藏]", value)
    return value[:limit]


def _resolve_job(jid, *, output_dir=None):
    job = taskbook_controller._get_job(jid)
    if job:
        return deepcopy(job)
    if not taskbook_controller._VALID_JOB_ID.fullmatch(jid or ""):
        raise FileNotFoundError("生成任务不存在。")
    output_dir = Path(output_dir or taskbook_controller._STATE.output_dir).resolve()
    # Older task manifests use output names rather than job IDs. Scan only the
    # configured output directory, with bounded entries and per-file size.
    direct = output_dir / (jid + ".job.json")
    candidates = [direct, *islice(output_dir.glob("*.job.json"), _MANIFEST_LIMIT)]
    for manifest in candidates:
        try:
            if not manifest.resolve().is_relative_to(output_dir) or manifest.stat().st_size > _MANIFEST_BYTES:
                continue
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("jid") != jid:
                continue
            if payload.get("status") not in {"done", "blocked", "error", "cancelled"}:
                continue
            return payload
        except (OSError, ValueError, UnicodeError):
            continue
    raise FileNotFoundError("生成任务不存在。")


def _snapshot(jid, job):
    result = _mapping(job.get("result"))
    meta = _mapping(result.get("meta"))
    replay = _mapping(job.get("replay"))
    selection = _mapping(replay.get("selection"))
    options = _mapping(replay.get("options"))
    context = _mapping(job.get("diagnostic_context"))
    files = _mapping(replay.get("files"))
    original = {**_mapping(job.get("original_filenames")), **_mapping(meta.get("original_filenames"))}
    inputs = _mapping(meta.get("inputs"))

    def source_name(role):
        item = _mapping(files.get(role))
        return _filename(original.get(role) or item.get("original_name") or inputs.get(role) or item.get("name"))

    parameters = {
        "product_type": meta.get("selected_product_type") or selection.get("product_type") or context.get("product_type"),
        "product_type_label": meta.get("selected_product_type_label") or selection.get("product_type_label"),
        "product_domain": meta.get("product_domain") or meta.get("selected_product_domain") or selection.get("product_domain") or context.get("product_domain"),
        "product_domain_label": meta.get("product_domain_label") or selection.get("product_domain_label"),
        "development_process": options.get("development_process") or meta.get("development_process") or context.get("process_classification"),
        "cover_phase": options.get("cover_phase") or meta.get("cover_phase"),
        "product_series": options.get("product_series") or meta.get("product_series"),
        "organization_scope": options.get("organization_scope") or meta.get("organization_scope"),
        "model_provider": meta.get("llm_model_provider") or options.get("model_provider"),
        "model_name": meta.get("llm_model") or options.get("model_name") or context.get("model"),
        "model_id": meta.get("llm_model_id") or options.get("model_id"),
        "template_name": _filename(meta.get("template_name") or selection.get("template_path") or inputs.get("tpl") or _mapping(files.get("effective_template")).get("original_name") or _mapping(files.get("template")).get("original_name")),
    }
    status = _safe_text(job.get("status"))
    error = job.get("error") or result.get("error") or (job.get("result") if isinstance(job.get("result"), str) else "")
    return {"jid": jid, "job_status": status, "parameters": {key: _safe_text(value) for key, value in parameters.items()},
        "files": {"tech": source_name("tech"), "spec": source_name("spec"), "output": _filename(result.get("out")), "report": _filename(result.get("report"))},
        "delivery_status": _safe_text(result.get("delivery_status") or {"done": "approved", "blocked": "blocked", "error": "failed"}.get(status, status)),
        "qa_ok": meta.get("qa_ok") if isinstance(meta.get("qa_ok"), bool) else None, "error": _safe_text(error, 4000)}


async def _body(request):
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _BODY_LIMIT:
            raise ValueError("反馈内容过长，请精简后重试。")
        chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("请求内容不是有效的 JSON。") from exc
    if not isinstance(payload, dict):
        raise ValueError("请提交完整的反馈记录。")  # noqa: TRY004 - malformed request content is a validation failure.
    return payload


async def _call(operation):
    try:
        return JSONResponse(await asyncio.to_thread(operation))
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except FeedbackConflictError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except (sqlite3.Error, OSError):
        logger.exception("Feedback database request failed")
        return JSONResponse({"error": "反馈存储暂不可用，请稍后重试。"}, status_code=503)


def _create(payload, *, admin=False, output_dir=None, identity=None):
    values = validate_create(payload, admin=admin)
    jid = values["jid"]
    snapshot = _snapshot(jid, _resolve_job(jid, output_dir=output_dir))
    return {"record": get_feedback_store().create(payload, snapshot=snapshot, admin=admin, identity=identity)}


async def _submit(request, *, admin=False):
    identity = None
    if not admin and get_auth_settings(request).enabled:
        user = get_current_user(request)
        if not user or user.get("verified") is not True:
            return JSONResponse({"error": "请先登录神州问学。", "auth_required": True, "login_url": "/auth/login"}, status_code=401)
        username = user.get("display_name") or user.get("name") or user.get("userid")
        identity = {"userid": user.get("userid", ""), "name": user.get("name") or username,
                    "source": user.get("source") or "smartvision", "verified": True}
    try:
        payload = await _body(request)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if identity is not None:
        payload["username"] = username
    config = getattr(request.app.state, "config", None)
    output_dir = getattr(config, "output_dir", None)
    return await _call(lambda: _create(payload, admin=admin, output_dir=output_dir, identity=identity))


@public_router.post("")
async def submit(request: Request):
    return await _submit(request)


@admin_router.post("")
async def admin_create(request: Request):
    return await _submit(request, admin=True)


def _positive(value):
    if not str(value).isascii() or not str(value).isdigit() or len(str(value)) > 18 or int(value) < 1:
        raise ValueError("记录标识或版本必须是正整数。")
    return int(value)


@admin_router.get("")
async def search(request: Request):
    def operation():
        params = request.query_params
        return get_feedback_store().search(q=params.get("q", ""), rating=params.get("rating", ""), status=params.get("status", ""),
            date_from=params.get("date_from", ""), date_to=params.get("date_to", ""),
            page=_positive(params.get("page", "1")), page_size=_positive(params.get("page_size", "20")))
    return await _call(operation)


@admin_router.get("/{record_id}")
async def detail(record_id: str):
    return await _call(lambda: {"record": get_feedback_store().get(_positive(record_id))})


@admin_router.put("/{record_id}")
async def update(record_id: str, request: Request):
    try:
        payload = await _body(request)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return await _call(lambda: {"record": get_feedback_store().update(_positive(record_id), payload)})


@admin_router.delete("/{record_id}")
async def delete(record_id: str, request: Request):
    return await _call(lambda: get_feedback_store().delete(_positive(record_id), _positive(request.query_params.get("expected_version", ""))))
