"""Independent admin listener for feedback and logs; run with ``python -m src.feedback_main``."""
from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

# main establishes the shared business-package import paths but does not start jobs.
from src.main import CorrelationIdMiddleware, _resolve_web_index

# isort: split
from src.common.logger import configure_logging, get_logger, shutdown_logging
from src.common.admin_access_store import AdminAccessStore, get_admin_access_store
from src.common.admin_auth import AdminAuthMiddleware, admin_auth_settings
from src.common.platform_auth import AuthSettings, PlatformTokenVerifier, TokenVerifier
from src.controller import feedback_controller
from src.controller.admin_auth_controller import router as admin_auth_router
from src.controller.auth_settings_controller import router as auth_settings_router
from src.controller.runtime_logs_controller import router as runtime_logs_router
from src.controller.help_resources_controller import admin_router as help_resources_admin_router, read_router as help_resources_router
from src.utils.config_loader import AppConfig, get_config

logger = get_logger("src.feedback_main")


class SameOriginMutationMiddleware(BaseHTTPMiddleware):
    """Keep browser mutations on the management listener's own origin."""

    async def dispatch(self, request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                origin is not None and origin.rstrip("/") != str(request.base_url).rstrip("/")
            ):
                return JSONResponse({"error": "管理员操作仅支持同源请求"}, status_code=403)
        return await call_next(request)


def create_app(
    config: AppConfig | None = None, *, auth_settings: AuthSettings | None = None,
    admin_store: AdminAccessStore | None = None, verifier: TokenVerifier | None = None,
) -> FastAPI:
    """Build the isolated management app without starting generation workers."""
    application = FastAPI(title="AI Native研发管理平台 · 管理", version="1.0.0")
    application.state.config = config or get_config()
    application.state.auth_settings_admin = True
    application.state.auth_settings_requires_admin = True
    main_auth_settings = auth_settings or AuthSettings.from_env()
    application.state.admin_auth_settings = admin_auth_settings(main_auth_settings)
    application.state.admin_access_store = admin_store or get_admin_access_store(application.state.config.logs_dir.parent / "runtime")
    application.state.admin_token_verifier = verifier or PlatformTokenVerifier(application.state.admin_auth_settings)
    application.add_middleware(AdminAuthMiddleware)
    application.add_middleware(SameOriginMutationMiddleware)
    application.add_middleware(CorrelationIdMiddleware)
    application.include_router(admin_auth_router)
    application.include_router(feedback_controller.admin_router)
    application.include_router(help_resources_router)
    # Same-port deployments route this namespace directly to admin auth. Keep
    # the original read URLs for existing standalone management deployments.
    application.include_router(help_resources_router, prefix="/admin")
    application.include_router(help_resources_admin_router)
    application.include_router(auth_settings_router)
    application.include_router(auth_settings_router, prefix="/admin")
    # The shared config points at the main platform's logs directory. The admin
    # process writes its own logs below feedback-admin, but reads generation logs.
    application.include_router(runtime_logs_router)

    @application.get("/admin/home", include_in_schema=False)
    async def main_site_entry(request: Request):
        target = main_auth_settings.public_url or str(request.url.replace(
            port=application.state.config.api_port, path="/", query="",
        ))
        return RedirectResponse(target, status_code=303)

    @application.get("/api/health")
    def health():
        try:
            feedback_controller.get_feedback_store().search(page_size=1)
        except (sqlite3.Error, OSError):
            logger.exception("feedback_store_unavailable")
            return JSONResponse({"ok": False, "service": "feedback-admin"}, status_code=503)
        return {"ok": True, "service": "feedback-admin"}

    @application.get("/", include_in_schema=False)
    @application.get("/feedback", include_in_schema=False)
    async def management_entry(request: Request):
        query = request.url.query
        return RedirectResponse("/admin" + (f"?{query}" if query else ""))

    @application.get("/log", include_in_schema=False)
    @application.get("/logs", include_in_schema=False)
    async def logs_entry(request: Request):
        query = [(key, value) for key, value in request.query_params.multi_items() if key != "view"]
        query.append(("view", "logs"))
        return RedirectResponse("/admin?" + urlencode(query))

    web_index = _resolve_web_index()
    if web_index is not None:
        @application.get("/admin", response_class=HTMLResponse, include_in_schema=False)
        async def management_page():
            return HTMLResponse(
                web_index.read_text(encoding="utf-8"),
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )

        assets_dir = web_index.parent / "assets"
        if assets_dir.is_dir():
            application.mount("/assets", StaticFiles(directory=str(assets_dir)), name="feedback-assets")

    return application


@asynccontextmanager
async def _lifespan(application: FastAPI):
    settings = application.state.config
    configure_logging(level=settings.log_level, log_dir=settings.logs_dir / "feedback-admin")
    logger.info("feedback_admin_starting")
    try:
        yield
    finally:
        logger.info("feedback_admin_stopping")
        shutdown_logging()


app = create_app()
app.router.lifespan_context = _lifespan


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.feedback_main:app",
        host=os.getenv("JTB_FEEDBACK_HOST", "127.0.0.1"),
        port=int(os.getenv("JTB_FEEDBACK_PORT", "18131")),
    )
