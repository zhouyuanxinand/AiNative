"""Shared HTTP request logging and upload-size enforcement."""
from __future__ import annotations

import logging
import time
import uuid

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response

from src.common.logger import get_logger
from src.common.request_context import correlation_id_var
from src.utils.config_loader import AppConfig

# Keep the established logger name used by deployments and request log queries.
logger = get_logger("src.main")
_QUIET_ACCESS_LOG_PATHS = {"/api/logs/latest"}


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Inject / propagate ``X-Correlation-ID`` and bind it to logging context."""

    async def dispatch(
        self, request: StarletteRequest, call_next
    ) -> Response:
        correlation_id = request.headers.get("x-correlation-id") or uuid.uuid4().hex
        token = correlation_id_var.set(correlation_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception(
                "request_failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "correlation_id": correlation_id,
                    "duration_ms": round(
                        (time.perf_counter() - start) * 1000, 2
                    ),
                    "error_type": type(exc).__name__,
                },
            )
            raise
        finally:
            correlation_id_var.reset(token)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Correlation-ID"] = correlation_id
        if (
            request.url.path not in _QUIET_ACCESS_LOG_PATHS
            or response.status_code >= 400
        ):
            level = (
                logging.ERROR
                if response.status_code >= 500
                else logging.WARNING
                if response.status_code >= 400
                else logging.INFO
            )
            logger.log(
                level,
                "request_completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": elapsed_ms,
                    "correlation_id": correlation_id,
                },
            )
        return response


class UploadContentLengthLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized multipart uploads before the body is fully buffered."""

    _UPLOAD_PATHS = {"/api/submit", "/api/precheck", "/api/templates/onboard", "/api/templates/versions"}

    async def dispatch(self, request: StarletteRequest, call_next) -> Response:
        if request.url.path in self._UPLOAD_PATHS or (
            request.method == "POST" and request.url.path.startswith("/api/rd/projects/")
            and request.url.path.endswith("/sources")
        ):
            config: AppConfig = request.app.state.config
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > config.max_upload_bytes:
                return JSONResponse(
                    {"error": f"上传体积超过 {config.max_upload_bytes // (1024 * 1024)} MB 限制"},
                    status_code=413,
                )
        return await call_next(request)
