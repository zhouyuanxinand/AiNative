# -*- coding: utf-8 -*-
"""研制任务书受控生成服务 — FastAPI 应用工厂与启动入口。

启动方式（cwd 必须是 ``basic-service/app``）::

    python -m src.main
    # 或
    uvicorn src.main:app --host 127.0.0.1 --port 18130

业务逻辑全部位于 ``jonhon_taskbook`` 包与 ``pipeline`` 模块；本文件只负责 HTTP
外壳、中间件链、配置装配与静态资源服务。
"""
from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# ── sys.path 桥接 ────────────────────────────────────────────────
# 业务包以 ``from jonhon_taskbook...`` 绝对导入，且 pipeline.py 与 config/prompts
# 同级位于 ``src/service/``。把该目录加入 sys.path 后，包内 import 与
# ``from src.pipeline_cli import run_pipeline`` 同时可用。
SRC_DIR = Path(__file__).resolve().parent
SERVICE_DIR = SRC_DIR / "service"
APP_DIR = SRC_DIR.parent
for _candidate in (str(SERVICE_DIR), str(SRC_DIR)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.requests import Request as StarletteRequest  # noqa: E402
from starlette.responses import Response  # noqa: E402

from src.common.logger import configure_logging, get_logger, shutdown_logging  # noqa: E402
from src.common.platform_auth import AuthSettings, PlatformAuthMiddleware  # noqa: E402
from src.common.request_context import correlation_id_var  # noqa: E402
from src.controller.taskbook_controller import register as register_controller  # noqa: E402
from src.controller.taskbook_controller import router as taskbook_router  # noqa: E402
from src.controller.failure_database_controller import router as failure_database_router  # noqa: E402
from src.controller.feedback_controller import public_router as feedback_router  # noqa: E402
from src.controller.auth_controller import router as auth_router  # noqa: E402
from src.controller.auth_settings_controller import router as auth_settings_router  # noqa: E402
from src.controller.service_credentials_controller import router as service_credentials_router  # noqa: E402
from src.controller.runtime_logs_controller import router as runtime_logs_router  # noqa: E402
from src.controller.review_controller import router as review_router  # noqa: E402
from src.controller.review_editor_controller import router as review_editor_router  # noqa: E402
from src.utils.config_loader import AppConfig, get_config  # noqa: E402

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
        if request.url.path in self._UPLOAD_PATHS:
            config: AppConfig = request.app.state.config
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > config.max_upload_bytes:
                return JSONResponse(
                    {"error": f"上传体积超过 {config.max_upload_bytes // (1024 * 1024)} MB 限制"},
                    status_code=413,
                )
        return await call_next(request)


def _resolve_web_index() -> Path | None:
    """Locate the single-file SPA, preferring the repo web/ directory.

    In containers the SPA is copied next to the app root (``app/web/index.html``);
    in development it lives at the repository ``web/`` directory two levels up.
    """
    candidates = [
        APP_DIR / "web" / "dist" / "index.html",
        APP_DIR.parent.parent / "web" / "dist" / "index.html",
        APP_DIR / "web" / "index.html",
        APP_DIR.parent.parent / "web" / "index.html",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Application factory used by uvicorn and tests."""
    settings = config or get_config()
    application = FastAPI(
        title="研制任务书受控生成服务",
        description="研制任务书受控生成、LLM 语义路由、模板管理与交付门禁。",
        version="1.0.0",
    )
    application.state.config = settings
    auth_settings = AuthSettings.from_env()
    application.state.auth_settings = auth_settings

    allow_credentials = settings.cors_origins != ["*"]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )
    application.add_middleware(UploadContentLengthLimitMiddleware)
    application.add_middleware(CorrelationIdMiddleware)
    application.add_middleware(PlatformAuthMiddleware, settings=auth_settings)

    application.include_router(taskbook_router)
    application.include_router(auth_router)
    application.include_router(auth_settings_router)
    application.include_router(failure_database_router)
    application.include_router(feedback_router)
    application.include_router(service_credentials_router)
    application.include_router(runtime_logs_router)
    application.include_router(review_editor_router)
    application.include_router(review_router)

    web_index = _resolve_web_index()

    if web_index is not None:
        web_dir = web_index.parent

        @application.get("/", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/log", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/logs", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/review/{jid}", response_class=HTMLResponse, include_in_schema=False)
        async def serve_spa_root() -> HTMLResponse:
            return HTMLResponse(
                web_index.read_text(encoding="utf-8"),
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )

        assets_dir = web_dir / "assets"
        if assets_dir.is_dir():
            from fastapi.staticfiles import StaticFiles

            application.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="web-assets",
            )

    return application


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    settings = get_config()
    configure_logging(
        level=settings.log_level,
        log_dir=settings.logs_dir,
    )
    register_controller(_app, settings)
    logger.info(
        "service_starting",
        extra={
            "profile": settings.profile,
            "host": settings.api_host,
            "port": settings.api_port,
        },
    )
    try:
        yield
    finally:
        logger.info("service_stopping")
        shutdown_logging()


def _build_app() -> FastAPI:
    # Bind the lifespan to the lazily-built app. ``create_app`` is also used by
    # tests without the lifespan, so keep lifespan wiring here at module level.
    app = create_app()
    app.router.lifespan_context = _lifespan
    return app


app = _build_app()


if __name__ == "__main__":
    import uvicorn

    _settings = get_config()
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if callable(_reconfigure):
            try:
                _reconfigure(errors="replace")
            except (OSError, ValueError):
                pass
    uvicorn.run(
        "src.main:app",
        host=os.getenv("JTB_HOST", _settings.api_host),
        port=int(os.getenv("JTB_PORT", _settings.api_port)),
    )
