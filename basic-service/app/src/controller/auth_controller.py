"""OA identity, login and application-session logout endpoints."""
from fastapi import APIRouter, Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from src.common.logged_out_page import LOGGED_OUT_HTML
from src.common.platform_auth import (
    AUTH_RESPONSE_HEADERS,
    begin_platform_login,
    clear_auth_cookies,
    external_origin,
    get_auth_settings,
    get_current_user,
)

router = APIRouter(tags=["authentication"])


@router.get("/api/current-user")
async def current_user(request: Request):
    settings = get_auth_settings(request)
    demo = getattr(request.state, "demo_mode", False)
    user = get_current_user(request) if settings.enabled or demo else None
    payload = {"auth_enabled": settings.enabled, "authenticated": user is not None, "user": dict(user) if user else None}
    if demo:
        payload["demo_mode"] = True
    if settings.enabled and user is None:
        payload["login_url"] = "/auth/login"
    return JSONResponse(payload, headers=AUTH_RESPONSE_HEADERS)


@router.get("/api/auth/me")
async def reference_current_user(request: Request):
    """Expose the reference application's identity contract to integrations."""
    settings = get_auth_settings(request)
    user = get_current_user(request) if settings.enabled or getattr(request.state, "demo_mode", False) else None
    if user is None:
        return JSONResponse({
            "success": False, "code": "AUTH_REQUIRED", "detail": "请先通过问学登录",
        }, status_code=401, headers=AUTH_RESPONSE_HEADERS)
    # Reference application roles belong to its own authorization store.
    # An OA identity alone grants no taskbook management or developer role.
    return JSONResponse({
        "success": True, "userid": user["userid"],
        "username": user["display_name"], "is_admin": False, "is_dev": False,
    }, headers=AUTH_RESPONSE_HEADERS)


@router.post("/api/system/logout")
async def logout(request: Request):
    """Clear this application's browser session without signing out of OA."""
    settings = get_auth_settings(request)
    response = JSONResponse({"success": True}, headers=AUTH_RESPONSE_HEADERS)
    secure = (settings.public_url or str(request.base_url)).startswith("https://")
    clear_auth_cookies(response, secure=secure)
    if getattr(request.state, "demo_mode", False):
        from src.service.rd_platform.demo import DEMO_COOKIE, DEMO_LOGGED_OUT_COOKIE
        response.delete_cookie(DEMO_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
        response.set_cookie(DEMO_LOGGED_OUT_COOKIE, "1", path="/", secure=secure, httponly=True, samesite="lax")
    return response


@router.get("/logged-out", include_in_schema=False)
async def logged_out(request: Request):
    html = LOGGED_OUT_HTML
    if getattr(request.state, "demo_mode", False):
        html = html.replace("研制任务书平台", "研发管理平台").replace("研制任务书登录会话", "研发管理平台会话").replace('href="/"', 'href="/auth/login"')
    return HTMLResponse(html, headers=AUTH_RESPONSE_HEADERS)


@router.get("/auth/login", include_in_schema=False)
async def login(request: Request):
    settings = get_auth_settings(request)
    origin = external_origin(request, settings)
    if settings.enabled:
        return begin_platform_login(request, settings, redirect_uri=f"{origin}/")
    response = RedirectResponse("/", status_code=302, headers=AUTH_RESPONSE_HEADERS)
    clear_auth_cookies(response, secure=origin.startswith("https://"))
    if getattr(request.state, "demo_mode", False):
        from src.service.rd_platform.demo import DEMO_LOGGED_OUT_COOKIE
        response.delete_cookie(DEMO_LOGGED_OUT_COOKIE, path="/", secure=origin.startswith("https://"), httponly=True, samesite="lax")
    return response
