"""Archive one generation submission, including its background execution."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import traceback
import uuid
from datetime import datetime, timezone

from src.common.request_context import request_archive_id_var, request_archive_state_var
from src.common.runtime_logs import redact_log_text

logger = logging.getLogger(__name__)
_PATHS = {"/api/submit", "/api/submit_local"}
_CLARIFY = re.compile(r"^/api/indicator_review/[0-9a-f]{10}/clarify$")


def failure_summary(value: object) -> str:
    text = redact_log_text(str(value or ""))
    for marker in ("model output", "model response", "response body", "模型输出", "模型响应", "原始响应", "响应正文"):
        index = text.lower().find(marker.lower())
        if index >= 0:
            text = text[:index + len(marker)] + " [detail omitted]"
    return text[:1000]


def _write(store, action: str, *args, **kwargs):
    try:
        return getattr(store, action)(*args, **kwargs)
    except (OSError, sqlite3.Error):
        # Log storage failure must not change the generation's business outcome.
        logger.error("request_archive_write_failed", extra={"operation": action})
        return None


def update_archive_metadata(metadata: dict) -> None:
    state = request_archive_state_var.get()
    if state is not None:
        _write(state["store"], "update_metadata", state["request_id"], metadata)


def bind_archive_job(jid: str, job: dict) -> None:
    state = request_archive_state_var.get()
    if state is not None:
        state["job"] = job
        job["request_archive_id"] = state["request_id"]
        update_archive_metadata({"job_id": jid})


def archive_progress(message: str, stage: str) -> None:
    state = request_archive_state_var.get()
    if state is not None:
        _event(state["store"], state["request_id"], "taskbook_progress", failure_summary(message), stage=stage)


def _event(store, request_id: str, event: str, message: str, **fields) -> None:
    _write(store, "append", request_id, {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "logger": "src.request_archive", "level": "INFO", "event": event, "message": message, **fields,
    })


class RequestArchiveMiddleware:
    """Pure ASGI keeps the archive open until response background tasks finish."""

    def __init__(self, app, store):
        self.app = app
        self.store = store

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or scope.get("method") != "POST" or (path not in _PATHS and not _CLARIFY.fullmatch(path)):
            return await self.app(scope, receive, send)

        request_id = uuid.uuid4().hex
        user = scope.get("state", {}).get("current_user") or {}
        verified = user.get("verified") is True
        _write(self.store, "begin", request_id, {
            "username": (user.get("display_name") or user.get("name") or user.get("userid")) if verified else "本地用户（未登录）",
            "userid": user.get("userid", "") if verified else "",
            "request_kind": "clarification" if _CLARIFY.fullmatch(path) else "generation",
        })
        state = {"request_id": request_id, "store": self.store, "job": None}
        id_token = request_archive_id_var.set(request_id)
        state_token = request_archive_state_var.set(state)
        _event(self.store, request_id, "generation_request_started", "收到生成请求", method="POST", path=path)
        status_code = 500
        error_body = bytearray()
        failure = ""

        async def capture(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message = {**message, "headers": [*message.get("headers", []), (b"x-request-log-id", request_id.encode("ascii"))]}
            elif message["type"] == "http.response.body" and status_code >= 400 and len(error_body) < 65536:
                error_body.extend(message.get("body", b"")[:65536 - len(error_body)])
            await send(message)

        try:
            await self.app(scope, receive, capture)
        except BaseException as exc:
            failure = failure_summary(exc) or type(exc).__name__
            _event(self.store, request_id, "generation_request_exception", failure, level="ERROR",
                   error_type=type(exc).__name__, exception="".join(traceback.format_tb(exc.__traceback__)) + type(exc).__name__ + ": " + failure)
            raise
        finally:
            try:
                job = state["job"] or {}
                result = job.get("result") or {}
                meta = result.get("meta") or {}
                summary = failure or failure_summary(job.get("error"))
                if not summary and status_code >= 400:
                    try:
                        body = json.loads(error_body)
                        reason = body.get("error") or body.get("detail")
                    except (ValueError, AttributeError):
                        reason = ""
                    summary = failure_summary(reason) if isinstance(reason, str) and reason else f"生成请求被拒绝（HTTP {status_code}）"
                terminal = job.get("status")
                success = not failure and status_code < 400 and terminal == "done"
                if not success and not summary:
                    summary = {"cancelled": "用户已终止本次任务", "blocked": "质量门禁未通过"}.get(terminal, "请求未完成生成任务")
                metadata = {}
                if result.get("out"):
                    metadata["files"] = {"output": result["out"]}
                if meta.get("llm_model"):
                    metadata["model"] = meta["llm_model"]
                _event(self.store, request_id, "generation_request_finished", "生成成功" if success else summary,
                       level="INFO" if success else "ERROR", status="success" if success else "failed",
                       status_code=status_code, job_status=terminal or "rejected", error_summary=summary)
                _write(self.store, "finish", request_id, "success" if success else "failed", error_summary=summary, metadata=metadata)
            finally:
                request_archive_state_var.reset(state_token)
                request_archive_id_var.reset(id_token)
