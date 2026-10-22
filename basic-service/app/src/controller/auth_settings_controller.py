"""Edit desired login settings without changing the running authentication policy."""
from __future__ import annotations

import asyncio
import sqlite3
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.common.auth_settings_store import (
    AUTH_SETTINGS_FIELDS,
    AuthSettingsConflictError,
    get_auth_settings_store,
    validate_auth_profile,
    validate_expected_version,
)
from src.common.platform_auth import (
    AUTH_PRESETS,
    AuthSettings,
    get_deployment_auth_settings,
)

router = APIRouter(prefix="/api/settings/auth", tags=["auth-settings"])


def _response(data, status=200):
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store"})


def _active(request: Request) -> dict | None:
    if getattr(request.app.state, "auth_settings_admin", False) is True:
        return None
    settings = getattr(request.app.state, "auth_settings", None)
    if not isinstance(settings, AuthSettings):
        return None
    return {field: getattr(settings, field) for field in AUTH_SETTINGS_FIELDS}


def _can_edit(request: Request, active: dict | None) -> bool:
    if getattr(request.app.state, "auth_settings_requires_admin", False):
        user = getattr(request.state, "admin_user", None)
        return bool(user and user.get("is_owner"))
    return getattr(request.app.state, "auth_settings_admin", False) is True or (active is not None and not active["enabled"])


def _view(request: Request, saved: dict | None) -> dict:
    active = _active(request)
    if saved is None:
        defaults = get_deployment_auth_settings()
        desired = {field: getattr(defaults, field) for field in AUTH_SETTINGS_FIELDS}
    else:
        desired = saved["settings"]
    return {
        "settings": desired,
        "active": active,
        "version": saved["version"] if saved else 0,
        "can_edit": _can_edit(request, active),
        "requires_restart": saved is not None and desired != active,
        "presets": {name: dict(profile) for name, profile in AUTH_PRESETS.items()},
    }


def _same_origin(request: Request) -> bool:
    try:
        origin = urlsplit(request.headers.get("Origin", ""))
        target = urlsplit(str(request.url))
        return (
            origin.scheme in {"http", "https"}
            and origin.hostname is not None
            and origin.username is None
            and origin.password is None
            and not origin.path and not origin.query and not origin.fragment
            and origin.scheme == target.scheme
            and origin.hostname == target.hostname
            and (origin.port or (443 if origin.scheme == "https" else 80))
            == (target.port or (443 if target.scheme == "https" else 80))
        )
    except ValueError:
        return False


@router.get("")
async def get_auth_settings(request: Request):
    try:
        saved = await asyncio.to_thread(get_auth_settings_store().read)
        return _response(_view(request, saved))
    except (OSError, sqlite3.Error, ValueError):
        return _response({"error": "统一登录设置读取失败，请检查服务端数据目录后重试。"}, 503)


@router.put("")
async def put_auth_settings(request: Request):
    if (
        not _can_edit(request, _active(request))
        or request.headers.get("X-Credential-Settings") != "1"
        or request.headers.get("Sec-Fetch-Site") == "cross-site"
        or not _same_origin(request)
    ):
        return _response({"error": "请由 wangxue 登录管理员页面，从统一登录设置入口操作。"}, 403)
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) != {*AUTH_SETTINGS_FIELDS, "expected_version"}:
            raise ValueError("请完整提交统一登录设置，且不要包含其他字段。")
        version = validate_expected_version(payload["expected_version"])
        profile = validate_auth_profile({field: payload[field] for field in AUTH_SETTINGS_FIELDS})
        if getattr(request.app.state, "auth_settings_requires_admin", False) and profile["app_id"] is None:
            return _response({"error": "管理员登录仍需有效的问学应用编号，不能清空。"}, 400)
    except (ValueError, TypeError, RecursionError):
        return _response({"error": "统一登录配置格式不正确，请检查开关、应用编号和 HTTP(S) 回跳地址。"}, 400)
    try:
        saved = await asyncio.to_thread(get_auth_settings_store().save, profile, expected_version=version)
        return _response(_view(request, saved))
    except AuthSettingsConflictError:
        return _response({"error": "统一登录设置已被其他页面修改，请刷新后重试。"}, 409)
    except (OSError, sqlite3.Error, ValueError):
        return _response({"error": "统一登录设置未保存，请检查服务端数据目录后重试。"}, 503)
