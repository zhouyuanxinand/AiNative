"""SPA route registration and assets shared by the two HTTP listeners."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from .paths import APP_DIR


def resolve_web_index() -> Path | None:
    """Locate the built SPA in the deployed app or repository web directory.

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


def mount_platform_web(application: FastAPI) -> None:
    @application.get("/log", include_in_schema=False)
    @application.get("/logs", include_in_schema=False)
    async def private_logs_only():
        return JSONResponse({"error": "运行日志已移至独立管理员端口，请通过管理员页面登录后查看。"}, status_code=403, headers={"Cache-Control": "no-store"})

    web_index = resolve_web_index()

    if web_index is not None:
        web_dir = web_index.parent

        @application.get("/", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/help/video", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/help/manual", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/review/{jid}", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/rd", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/rd/{project_id}", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/rd/{project_id}/tasks/{task_id}", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/taskbook", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/requirements", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/tasks", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/artifacts", response_class=HTMLResponse, include_in_schema=False)
        @application.get("/approvals", response_class=HTMLResponse, include_in_schema=False)
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
