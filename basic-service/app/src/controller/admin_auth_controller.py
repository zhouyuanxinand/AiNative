"""Admin OA callback, opaque session and owner-managed allowlist endpoints."""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import sqlite3
from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from starlette.responses import HTMLResponse, RedirectResponse

from src.common.admin_access_store import AdminAlreadyExistsError, OwnerRemovalError
from src.common.admin_auth import (
    ADMIN_COOKIE,
    STATE_COOKIE,
    admin_identity,
    admin_response,
    clear_admin_cookie,
)
from src.common.platform_auth import (
    AUTH_RESPONSE_HEADERS,
    PlatformUnavailableError,
    external_origin,
    platform_login_url,
)

router = APIRouter(tags=["admin-auth"])
logger = logging.getLogger(__name__)
_ERRORS = {
    "origin": ("当前地址未获准用于管理员回跳，请检查服务部署配置。", 400),
    "state": ("登录请求已过期或不匹配，请重新发起管理员登录。", 400),
    "callback": ("问学回跳信息不完整或应用编号不匹配，请重新登录。", 400),
    "unavailable": ("暂时无法向问学校验身份，请稍后重试。", 503),
    "identity": ("问学登录未通过，或校验结果没有可识别的 OA 登录账号。请确认账号后重试。", 403),
    "forbidden": ("当前 OA 账号不在管理员名单中。请联系 wangxue 添加登录账号。", 403),
    "storage": ("管理员会话暂时无法保存，请稍后重试。", 503),
}


def _login_error(message: str, status=403):
    # Credentials never appear in this page. A new login starts a fresh state.
    response = HTMLResponse(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>管理员登录 · AI Native研发管理平台</title>'
        '<style>body{margin:0;background:#f5f5f7;color:#1d1d1f;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}'
        'main{max-width:560px;margin:12vh auto;padding:32px;background:white;border:1px solid #dedee3;border-radius:14px}'
        'h1{font-size:22px}a{color:#0066cc}p{overflow-wrap:anywhere}@media(max-width:640px){main{margin:8vh 16px;padding:24px}}</style>'
        '<main><h1>无法进入管理员页面</h1><p>' + escape(message) + '</p>'
        '<p>如需切换账号，请先在 OA／问学退出当前账户，再重新登录。</p>'
        '<a href="/admin/auth/login">重新通过 OA／问学登录</a></main></html>',
        status_code=status, headers={**AUTH_RESPONSE_HEADERS, "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"},
    )
    return response


def _mutation_allowed(request: Request) -> bool:
    # Fetch's custom header blocks cross-origin form POSTs even without Origin.
    return request.headers.get("X-Admin-Action") == "1" and request.headers.get("Sec-Fetch-Site") != "cross-site"


@router.get("/admin/auth/error", include_in_schema=False)
async def login_error(request: Request):
    message, status = _ERRORS.get(request.query_params.get("reason"), _ERRORS["identity"])
    return _login_error(message, status)


@router.get("/admin/auth/login", include_in_schema=False)
async def login(request: Request):
    settings = request.app.state.admin_auth_settings
    try:
        origin = external_origin(request, settings)
    except ValueError:
        return _login_error("当前地址未获准用于管理员回跳，请检查服务部署配置。", 400)
    try:
        state = await asyncio.to_thread(
            request.app.state.admin_access_store.begin_login,
            app_id=settings.app_id, base_url=settings.platform_base_url, origin=origin,
        )
    except (OSError, sqlite3.Error):
        return _login_error("登录请求暂时无法建立，请稍后重试。", 503)
    callback = origin + "/admin/auth/callback?" + urlencode({"state": state})
    response = RedirectResponse(platform_login_url(settings, callback), status_code=302, headers=AUTH_RESPONSE_HEADERS)
    response.set_cookie(STATE_COOKIE, state, max_age=300, httponly=True, secure=origin.startswith("https://"), samesite="lax", path="/admin/auth")
    clear_admin_cookie(response, origin.startswith("https://"))
    return response


@router.get("/admin/auth/callback", include_in_schema=False)
async def callback(request: Request):
    settings = request.app.state.admin_auth_settings
    try:
        origin = external_origin(request, settings)
    except ValueError:
        return RedirectResponse("/admin/auth/error?reason=origin", status_code=303, headers=AUTH_RESPONSE_HEADERS)
    secure = origin.startswith("https://")

    def finish(response):
        response.delete_cookie(STATE_COOKIE, path="/admin/auth", httponly=True, secure=secure, samesite="lax")
        return response

    def fail(reason):
        # Remove upstream token/userid from the address bar even on rejection.
        response = RedirectResponse("/admin/auth/error?" + urlencode({"reason": reason}), status_code=303, headers=AUTH_RESPONSE_HEADERS)
        clear_admin_cookie(response, secure)
        return finish(response)

    state = request.query_params.get("state", "")
    expected_state = request.cookies.get(STATE_COOKIE, "")
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{43}", state)
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", expected_state)
        or not secrets.compare_digest(state, expected_state)
    ):
        return fail("state")
    try:
        accepted = await asyncio.to_thread(
            request.app.state.admin_access_store.consume_login, state,
            app_id=settings.app_id, base_url=settings.platform_base_url, origin=origin,
        )
    except (OSError, sqlite3.Error):
        return fail("storage")
    if not accepted:
        return fail("state")
    userid, token = request.query_params.get("userid", ""), request.query_params.get("token", "")
    appid = request.query_params.get("appid")
    if not userid or len(userid) > 256 or not token or len(token) > 16384 or (appid is not None and appid != str(settings.app_id)):
        return fail("callback")
    try:
        payload = await request.app.state.admin_token_verifier(userid, token, settings.app_id)
    except PlatformUnavailableError:
        logger.warning("admin_oa_validation_unavailable")
        return fail("unavailable")
    try:
        identity = admin_identity(userid, payload)
    except (ValueError, TypeError):
        logger.warning("admin_oa_identity_rejected")
        return fail("identity")
    try:
        session = await asyncio.to_thread(
            request.app.state.admin_access_store.create_session,
            username=identity["username"], userid=identity["userid"], display_name=identity["display_name"],
            app_id=settings.app_id, base_url=settings.platform_base_url, origin=origin, ttl_seconds=settings.cookie_max_age,
        )
    except PermissionError:
        logger.info("admin_access_denied", extra={"username": identity["username"], "account_source": identity["account_source"]})
        return fail("forbidden")
    except (OSError, sqlite3.Error):
        logger.error("admin_session_creation_failed")
        return fail("storage")
    logger.info("admin_login_succeeded", extra={"username": identity["username"], "account_source": identity["account_source"]})
    response = RedirectResponse("/admin", status_code=303, headers=AUTH_RESPONSE_HEADERS)
    response.set_cookie(ADMIN_COOKIE, session, max_age=settings.cookie_max_age, httponly=True, secure=secure, samesite="lax", path="/")
    return finish(response)


@router.get("/api/admin/session")
async def session_info(request: Request):
    user = request.state.admin_user
    return admin_response({"authenticated": True, "user": {key: user[key] for key in ("username", "userid", "display_name")}, "can_manage_admins": user["is_owner"]})


@router.post("/api/admin/logout")
async def logout(request: Request):
    if not _mutation_allowed(request):
        return admin_response({"error": "请从管理员页面退出登录。"}, 403)
    settings = request.app.state.admin_auth_settings
    try:
        origin = external_origin(request, settings)
        await asyncio.to_thread(request.app.state.admin_access_store.revoke_session, request.cookies.get(ADMIN_COOKIE, ""))
    except ValueError:
        return admin_response({"error": "管理员访问地址无效。"}, 400)
    except (OSError, sqlite3.Error):
        return admin_response({"error": "退出未完成，请重试。"}, 503)
    response = admin_response({"success": True})
    clear_admin_cookie(response, origin.startswith("https://"))
    response.delete_cookie(STATE_COOKIE, path="/admin/auth", httponly=True, secure=origin.startswith("https://"), samesite="lax")
    return response


@router.get("/api/admin/members")
async def members(request: Request):
    try:
        items = await asyncio.to_thread(request.app.state.admin_access_store.list_admins)
    except (OSError, sqlite3.Error):
        return admin_response({"error": "管理员名单暂时无法读取，请重试。"}, 503)
    return admin_response({"items": items, "can_manage_admins": request.state.admin_user["is_owner"]})


def _owner_check(request: Request):
    if not request.state.admin_user["is_owner"]:
        return admin_response({"error": "只有 wangxue 可以维护管理员名单。", "code": "OWNER_REQUIRED"}, 403)
    if not _mutation_allowed(request):
        return admin_response({"error": "请从管理员名单页面操作。"}, 403)
    return None


@router.post("/api/admin/members")
async def add_member(request: Request):
    rejected = _owner_check(request)
    if rejected is not None:
        return rejected
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) != {"username"}:
            raise ValueError("请仅填写要授权的 OA 登录账号。")
        member = await asyncio.to_thread(request.app.state.admin_access_store.add_admin, payload["username"], actor=request.state.admin_user["username"])
    except AdminAlreadyExistsError:
        return admin_response({"error": "该账号已在管理员名单中。"}, 409)
    except (ValueError, TypeError):
        return admin_response({"error": "请填写 1 至 128 位 OA 登录账号，仅支持字母、数字、点、下划线、@ 和连字符。"}, 400)
    except (OSError, sqlite3.Error):
        return admin_response({"error": "管理员未添加，请稍后重试。"}, 503)
    logger.info("admin_member_added", extra={"username": member["username"], "actor": request.state.admin_user["username"]})
    return admin_response({"member": member}, 201)


@router.delete("/api/admin/members/{username}")
async def delete_member(username: str, request: Request):
    rejected = _owner_check(request)
    if rejected is not None:
        return rejected
    try:
        removed = await asyncio.to_thread(request.app.state.admin_access_store.remove_admin, username, actor=request.state.admin_user["username"])
    except OwnerRemovalError:
        return admin_response({"error": "初始管理员 wangxue 不能移除。"}, 409)
    except ValueError:
        return admin_response({"error": "管理员账号格式不正确。"}, 400)
    except (OSError, sqlite3.Error):
        return admin_response({"error": "管理员未移除，请稍后重试。"}, 503)
    if not removed:
        return admin_response({"error": "该账号已不在管理员名单中，请刷新列表。"}, 404)
    logger.info("admin_member_removed", extra={"username": username, "actor": request.state.admin_user["username"]})
    return admin_response({"success": True})
