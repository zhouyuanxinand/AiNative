"""HTTP adapter for task-specific document comparison and immutable revisions."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from jonhon_taskbook.review_store import ReviewConflictError, ReviewStore
from src.controller import taskbook_controller

router = APIRouter(prefix="/api/review", tags=["review"])


def get_store() -> ReviewStore:
    return ReviewStore(taskbook_controller._STATE.output_dir / "reviews")


def ensure_review(jid: str) -> dict:
    state = taskbook_controller._STATE
    job = taskbook_controller._get_job(jid)
    # History metadata may have aged out of the in-memory queue, while the
    # persistent generation artifact remains available.
    if job is None and taskbook_controller._VALID_JOB_ID.fullmatch(jid or ""):
        for path in state.output_dir.glob("*.job.json"):
            try:
                candidate = json.loads(path.read_text(encoding="utf-8"))
                if candidate.get("jid") == jid:
                    job = candidate
                    break
            except (OSError, ValueError):
                continue
    return get_store().ensure_review(jid, job, {
        "upload_dir": state.upload_dir, "output_dir": state.output_dir,
        "rules_dir": state.config_dir,
    })


def _error(exc: Exception):
    if isinstance(exc, ReviewConflictError):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(400, str(exc)) from exc
    raise exc


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision_id: str = Field(min_length=1, max_length=100)
    operations: list[dict] = Field(min_length=1, max_length=1000)
    actor: str = Field(default="web-user", max_length=100)


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision_id: str = Field(min_length=1, max_length=100)
    actor: str = Field(default="web-user", max_length=100)


class AnnotationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    element_id: str = Field(min_length=1, max_length=200)
    status: str
    note: str = Field(default="", max_length=2000)
    actor: str = Field(default="web-user", max_length=100)


@router.get("/{jid}")
def review_bundle(jid: str):
    try:
        return ensure_review(jid)
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.get("/{jid}/assets/{asset_id}")
def review_asset(jid: str, asset_id: str):
    try:
        bundle = ensure_review(jid)
        path = get_store().asset_path(jid, asset_id)
        asset = next(item for item in bundle["assets"] if item["id"] == asset_id)
        inline = path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
        return FileResponse(path, filename=asset["name"], content_disposition_type="inline" if inline else "attachment")
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.get("/{jid}/document")
def review_document(jid: str, asset_id: str | None = None, revision_id: str | None = None):
    from jonhon_taskbook.review_document import document_projection
    try:
        bundle = ensure_review(jid)
        if asset_id and revision_id:
            raise ValueError("只能指定一个文档来源")
        store = get_store()
        revision_id = revision_id or (None if asset_id else bundle["current_revision_id"])
        path = store.asset_path(jid, asset_id) if asset_id else store.revision_path(jid, revision_id)
        converted = False
        warnings = []
        if path.suffix.lower() == ".doc":
            from jonhon_taskbook.input_normalizer import normalize_input
            normalized = normalize_input(path, store.directory(jid) / "previews", ocr_enabled=False)
            path = normalized.path
            warnings = list(normalized.warnings)
            converted = True
        if path.suffix.lower() != ".docx":
            return {"document_id": asset_id, "format": path.suffix.lstrip("."),
                    "view_mode": "original", "blocks": [], "outline": [], "sections": [],
                    "url": f"/api/review/{jid}/assets/{asset_id}",
                    "warnings": ["请查看原文件；该格式不提供可编辑 DOCX 段落定位。"]}
        document = document_projection(path, asset_id=asset_id, revision_id=revision_id)
        document.setdefault("warnings", []).extend(warnings)
        document["converted"] = converted
        return document
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.get("/{jid}/links")
def links(jid: str, revision_id: str | None = None):
    from jonhon_taskbook.review_checks import review_links
    try:
        bundle = ensure_review(jid)
        return review_links(get_store(), jid, revision_id or bundle["current_revision_id"])
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.get("/{jid}/revisions/{revision_id}/download")
def revision_download(jid: str, revision_id: str):
    try:
        bundle = ensure_review(jid)
        path = get_store().revision_path(jid, revision_id)
        name = Path(bundle["title"]).stem + "_" + revision_id + ".docx"
        return FileResponse(path, filename=name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.post("/{jid}/revisions")
def save_edits(jid: str, request: EditRequest, http_request: Request):
    from jonhon_taskbook.review_document import apply_edits
    try:
        bundle = ensure_review(jid)
        store = get_store()
        if bundle["current_revision_id"] != request.expected_revision_id:
            raise ReviewConflictError("已有更新的修订版，请刷新后再保存")
        with tempfile.TemporaryDirectory(prefix="review-edit-") as directory:
            target = Path(directory) / "edited.docx"
            edited = apply_edits(store.revision_path(jid, request.expected_revision_id), target, request.operations)
            from src.service.rd_platform.integration import review_actor
            return store.save_revision(jid, request.expected_revision_id, target, review_actor(http_request, jid, request.actor),
                                       "正文修改", changes=edited.get("changes", []))
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.post("/{jid}/revisions/upload")
async def upload_revision(jid: str, request: Request, expected_revision_id: str = Form(...),
                          file: UploadFile = File(...), actor: str = Form("web-user"),
                          reason: str = Form("上传修订件")):
    try:
        ensure_review(jid)
        if not (file.filename or "").lower().endswith(".docx"):
            raise ValueError("只接受 DOCX 修订件")
        data = await file.read(100 * 1024 * 1024 + 1)
        if len(data) > 100 * 1024 * 1024:
            raise ValueError("任务书不能超过 100 MB")
        with tempfile.TemporaryDirectory(prefix="review-upload-") as directory:
            path = Path(directory) / "revision.docx"
            path.write_bytes(data)
            from src.service.rd_platform.integration import review_actor
            return get_store().save_revision(jid, expected_revision_id, path, review_actor(request, jid, actor), reason)
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.post("/{jid}/revisions/{revision_id}/check")
def check_revision(jid: str, revision_id: str):
    try:
        ensure_review(jid)
        from src.service.rd_platform.integration import get_rd_store
        if get_rd_store().generation(jid):
            # Technical QA can pass an edited file; independent engineering
            # approval remains a separate mandatory R&D workflow decision.
            return get_store().check_revision(jid, revision_id, independent_review=True)
        return get_store().check_revision(jid, revision_id)
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.post("/{jid}/revisions/{revision_id}/restore")
def restore_revision(jid: str, revision_id: str, request: RestoreRequest, http_request: Request):
    try:
        ensure_review(jid)
        from src.service.rd_platform.integration import review_actor
        return get_store().restore_revision(jid, revision_id, request.expected_revision_id, review_actor(http_request, jid, request.actor))
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.post("/{jid}/revisions/{revision_id}/annotations")
def annotations(jid: str, revision_id: str, request: AnnotationRequest, http_request: Request):
    try:
        ensure_review(jid)
        from src.service.rd_platform.integration import review_actor
        return get_store().annotate(jid, revision_id, request.element_id, request.status, request.note, review_actor(http_request, jid, request.actor))
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)
