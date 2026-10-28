"""Strict OA authentication and server-side authorization for the admin listener."""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from dataclasses import replace
from types import MappingProxyType

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.common.admin_access_store import normalize_admin_username
from src.common.platform_auth import (
    AUTH_RESPONSE_HEADERS,
    AuthSettings,
    external_origin,
)

logger = logging.getLogger(__name__)
ADMIN_COOKIE = "jtb_admin_session"
STATE_COOKIE = "jtb_admin_login_state"
_ACCOUNT_KEYS = (
    "loginName", "login_name", "loginUsername", "login_username",
    "username", "userName", "user_name", "account",
)
_DISPLAY_KEYS = ("sn", "realName", "real_name", "name", "displayName", "display_name")
_PUBLIC_PATHS = {
    "/", "/admin", "/feedback", "/log", "/logs", "/favicon.ico", "/api/health",
    "/admin/auth/login", "/admin/auth/callback", "/admin/auth/error", "/api/admin/logout",
}


def admin_auth_settings(settings: AuthSettings | None = None) -> AuthSettings:
    # The public application's optional local mode can never disable admin auth.
    # A fixed main-app origin must not send admin callbacks to the business port.
    return replace(
        settings or AuthSettings.from_env(), enabled=True,
        public_url=os.getenv("JTB_ADMIN_PUBLIC_URL", "").strip() or None,
    )


def admin_identity(userid: str, payload: dict) -> dict:
    """Select the validated login account, never a mutable display name."""
    if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0:
        raise ValueError("问学身份校验未通过")
    scopes = [item for item in (payload.get("data"), payload) if isinstance(item, dict)]
    username, account_source = userid, "verified_userid"
    for scope in scopes:
        chosen = next((key for key in _ACCOUNT_KEYS if scope.get(key) not in (None, "")), None)
        if chosen:
            username, account_source = scope[chosen], chosen
            break
    username = normalize_admin_username(username)
    display_name = next((scope[key].strip()[:256] for scope in scopes for key in _DISPLAY_KEYS
                         if isinstance(scope.get(key), str) and scope[key].strip()), username)
    return {"username": username, "userid": userid, "display_name": display_name, "account_source": account_source}


def admin_response(data, status=200):
    return JSONResponse(data, status_code=status, headers=AUTH_RESPONSE_HEADERS)


def clear_admin_cookie(response, secure: bool):
    response.delete_cookie(ADMIN_COOKIE, path="/", httponly=True, secure=secure, samesite="lax")


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Public HTML is only the login shell; every management API requires a session."""

    async def dispatch(self, request: Request, call_next):
        from src.service.rd_platform.demo import DEMO_COOKIE, demo_mode_enabled, demo_user
        if demo_mode_enabled():
            identity = demo_user(request.cookies.get(DEMO_COOKIE))
            request.state.demo_mode = True
            request.state.auth_settings = AuthSettings(enabled=False)
            request.state.current_user = MappingProxyType(identity)
            request.state.admin_user = MappingProxyType({
                **identity, "username": identity["userid"],
                "is_owner": identity["role"] == "owner",
            })
            response = await call_next(request)
            response.headers.update(AUTH_RESPONSE_HEADERS)
            return response
        request.state.admin_user = None
        settings = request.app.state.admin_auth_settings
        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith("/assets/"):
            return await call_next(request)
        try:
            origin = external_origin(request, settings)
        except ValueError:
            return admin_response({"error": "管理员访问地址未获准用于登录，请检查部署地址配置。"}, 400)
        cookie = request.cookies.get(ADMIN_COOKIE, "")
        try:
            user = await asyncio.to_thread(
                request.app.state.admin_access_store.lookup_session, cookie,
                app_id=settings.app_id, base_url=settings.platform_base_url, origin=origin,
            )
        except (OSError, sqlite3.Error):
            logger.error("admin_session_store_unavailable")
            return admin_response({"error": "管理员认证服务暂不可用，请稍后重试。"}, 503)
        if user is None:
            response = admin_response({
                "error": "请通过 OA／问学登录管理员账号。", "code": "AUTH_REQUIRED",
                "authenticated": False, "login_url": "/admin/auth/login",
            }, 401)
            clear_admin_cookie(response, origin.startswith("https://"))
            return response
        request.state.admin_user = MappingProxyType(user)
        if path.rstrip("/") == "/api/settings/auth" and request.method not in {"GET", "HEAD"} and not user["is_owner"]:
            return admin_response({"error": "只有 wangxue 可以修改统一登录设置。", "code": "OWNER_REQUIRED"}, 403)
        response = await call_next(request)
        response.headers.update(AUTH_RESPONSE_HEADERS)
        return response
