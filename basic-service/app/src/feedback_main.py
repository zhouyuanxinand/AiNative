"""Independent feedback management listener; run with ``python -m src.feedback_main``."""
from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

# main establishes the shared business-package import paths but does not start jobs.
from src.main import CorrelationIdMiddleware, _resolve_web_index

# isort: split
from src.common.logger import configure_logging, get_logger, shutdown_logging
from src.controller import feedback_controller
from src.controller.auth_settings_controller import router as auth_settings_router
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
                return JSONResponse({"error": "反馈管理操作仅支持同源请求"}, status_code=403)
        return await call_next(request)


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Build the isolated management app without starting generation workers."""
    application = FastAPI(title="用户反馈管理", version="1.0.0")
    application.state.config = config or get_config()
    application.state.auth_settings_admin = True
    application.add_middleware(SameOriginMutationMiddleware)
    application.add_middleware(CorrelationIdMiddleware)
    application.include_router(feedback_controller.admin_router)
    application.include_router(auth_settings_router)

    @application.get("/api/health")
    def health():
        try:
            feedback_controller.get_feedback_store().search(page_size=1)
        except (sqlite3.Error, OSError):
            logger.exception("feedback_store_unavailable")
            return JSONResponse({"ok": False, "service": "feedback-admin"}, status_code=503)
        return {"ok": True, "service": "feedback-admin"}

    @application.get("/", include_in_schema=False)
    async def management_entry():
        return RedirectResponse("/feedback")

    web_index = _resolve_web_index()
    if web_index is not None:
        @application.get("/feedback", response_class=HTMLResponse, include_in_schema=False)
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
