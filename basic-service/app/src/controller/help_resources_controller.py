"""Read operating instructions on either listener; administer only with OA auth."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import tempfile
from functools import lru_cache
from pathlib import Path
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from lxml import etree
from pydantic import BaseModel, ConfigDict

from jonhon_taskbook.input_normalizer import normalize_input
from jonhon_taskbook.review_document import document_projection
from src.common.help_resource_store import HelpResourceError, HelpResourceStore

logger = logging.getLogger(__name__)
_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


class HelpResourceRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await original(request)
            except HelpResourceError as exc:
                return JSONResponse({"error": str(exc)}, status_code=exc.status_code, headers=_HEADERS)
            except RequestValidationError:
                return JSONResponse({"error": "资料参数不完整或格式不正确，请检查后重试。"}, status_code=400, headers=_HEADERS)
            except (OSError, sqlite3.Error):
                logger.exception("help_resource_storage_unavailable")
                return JSONResponse({"error": "操作资料暂时无法读取或保存，请稍后重试。"}, status_code=503, headers=_HEADERS)

        return handle


read_router = APIRouter(prefix="/api/help-resources", tags=["help-resources"], route_class=HelpResourceRoute)
admin_router = APIRouter(prefix="/api/help-resources-admin", tags=["help-resources-admin"], route_class=HelpResourceRoute)


@lru_cache(maxsize=8)
def _store(root: Path) -> HelpResourceStore:
    return HelpResourceStore(root)


def _get_store(request: Request) -> HelpResourceStore:
    return _store(request.app.state.config.logs_dir.parent / "data" / "help_resources")


def _require_admin(request: Request) -> str:
    user = getattr(request.state, "admin_user", None)
    if not getattr(request.app.state, "admin_auth_settings", None) or not user or not user.get("username"):
        raise HelpResourceError("请通过 OA／问学登录管理员账号。", 401)
    if request.headers.get("X-Admin-Action") != "1" or request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise HelpResourceError("请从管理员页面操作资料。", 403)
    return user["username"]


def _item_or_404(store: HelpResourceStore, resource_id: str) -> dict:
    item = store.get(resource_id)
    if item is None:
        raise HelpResourceError("该资料不存在或已删除。", 404)
    return item


@read_router.get("")
async def list_resources(request: Request, kind: str | None = None):
    items = await asyncio.to_thread(lambda: _get_store(request).list(kind))
    return JSONResponse({"items": items}, headers=_HEADERS)


@read_router.get("/{resource_id}/file")
@read_router.head("/{resource_id}/file")
async def resource_file(resource_id: str, request: Request, download: str = "0"):
    def read():
        store = _get_store(request)
        item = _item_or_404(store, resource_id)
        return item, store.file_path(item)

    item, path = await asyncio.to_thread(read)
    return FileResponse(path, media_type=item["media_type"], filename=item["filename"],
                        content_disposition_type="attachment" if download == "1" else "inline", headers=_HEADERS)


@read_router.get("/{resource_id}/document")
async def resource_document(resource_id: str, request: Request):
    def read():
        store = _get_store(request)
        item = _item_or_404(store, resource_id)
        if item["source_type"] != "file" or item["preview_type"] != "document":
            raise HelpResourceError("该资料不支持 Word 内容预览，请打开原始链接或文件。")
        path = store.file_path(item)
        try:
            if path.suffix.lower() == ".doc":
                # Conversion is entirely local and the original remains downloadable.
                with tempfile.TemporaryDirectory(prefix="preview-", dir=store.root) as temporary:
                    normalized = normalize_input(path, temporary)
                    projection = document_projection(normalized.path, asset_id=resource_id)
                    projection["warnings"] = list(dict.fromkeys([*normalized.warnings, *projection["warnings"]]))
                    return projection
            return document_projection(path, asset_id=resource_id)
        except (etree.XMLSyntaxError, BadZipFile) as exc:
            raise HelpResourceError("Word 文档内容无法解析，请检查文件是否损坏；仍可下载原文件。", 422) from exc
        except ValueError as exc:
            raise HelpResourceError(str(exc), 422) from exc

    return JSONResponse(await asyncio.to_thread(read), headers=_HEADERS)


class LinkPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    title: str
    source_url: str


@admin_router.post("/links", status_code=201)
async def create_link(payload: LinkPayload, request: Request, actor: str = Depends(_require_admin)):
    item = await asyncio.to_thread(lambda: _get_store(request).create_link(payload.kind, payload.title, payload.source_url, actor))
    return JSONResponse({"item": item}, status_code=201, headers=_HEADERS)


@admin_router.post("/upload", status_code=201)
async def upload_resource(request: Request, kind: str = Form(...), title: str = Form(...),
                          file: UploadFile = File(...), actor: str = Depends(_require_admin)):
    try:
        item = await asyncio.to_thread(lambda: _get_store(request).create_file(kind, title, file.filename or "", file.file, actor))
    finally:
        await file.close()
    return JSONResponse({"item": item}, status_code=201, headers=_HEADERS)


@admin_router.delete("/{resource_id}")
async def delete_resource(resource_id: str, request: Request, actor: str = Depends(_require_admin)):
    deleted = await asyncio.to_thread(lambda: _get_store(request).delete(resource_id))
    if not deleted:
        raise HelpResourceError("该资料不存在或已删除。", 404)
    logger.info("help_resource_deleted", extra={"resource_id": resource_id, "actor": actor})
    return JSONResponse({"ok": True}, headers=_HEADERS)
