"""Optional local document editor routes for taskbook review."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jonhon_taskbook.review_editor import EditorConfig, EditorError, ReviewEditor
from src.controller import taskbook_controller
from src.controller.review_controller import _error, ensure_review, get_store

router = APIRouter()


def _editor() -> ReviewEditor:
    try:
        return ReviewEditor(get_store(), taskbook_controller._STATE.output_dir / "reviews", EditorConfig.from_env())
    except EditorError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/api/review/editor/status")
def editor_status():
    try:
        config = EditorConfig.from_env()
    except EditorError as exc:
        return {"configured": False, "message": str(exc)}
    return {"configured": True, "script_url": config.script_url, "message": "已配置本地文档编辑服务"}


class EditorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: str = Field(min_length=1, max_length=100)
    mode: str = "edit"


@router.post("/api/review/{jid}/editor")
def open_editor(jid: str, body: EditorRequest):
    try:
        ensure_review(jid)
        return _editor().open(jid, body.revision_id, body.mode)
    except EditorError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.get("/api/review/{jid}/editor/{sid}")
def editor_session(jid: str, sid: str):
    try:
        return _editor().state(jid, sid)
    except EditorError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/api/review/{jid}/editor/{sid}/file")
def editor_file(jid: str, sid: str, token: str):
    try:
        path = _editor().file(jid, sid, token)
        return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Cache-Control": "no-store"})
    except EditorError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/api/review/{jid}/editor/{sid}/callback")
async def editor_callback(jid: str, sid: str, request: Request):
    # ONLYOFFICE signs the callback body; unsigned body fields never reach the
    # download or persistence service. Tokens/URLs are deliberately not logged.
    from starlette.concurrency import run_in_threadpool

    try:
        raw = await request.body()
        if len(raw) > 1024 * 1024:
            raise EditorError("编辑回调超过大小限制。", 413)
        import json
        body = json.loads(raw)
        bearer = request.headers.get("authorization", "")
        token = body.get("token") or (bearer[7:] if bearer.lower().startswith("bearer ") else "")
        return await run_in_threadpool(_editor().callback, jid, sid, token)
    except EditorError as exc:
        return JSONResponse({"error": 1, "message": str(exc)}, status_code=exc.status_code)
    except (ValueError, TypeError, AttributeError):
        return JSONResponse({"error": 1, "message": "无效的编辑回调。"}, status_code=400)


@router.post("/api/review/{jid}/editor/{sid}/save")
def save_editor(jid: str, sid: str):
    try:
        return _editor().save(jid, sid)
    except EditorError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
