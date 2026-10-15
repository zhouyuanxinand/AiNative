"""Public identity probe and explicit OA login entry point."""
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse, RedirectResponse

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
    user = get_current_user(request) if settings.enabled else None
    payload = {"auth_enabled": settings.enabled, "authenticated": user is not None, "user": dict(user) if user else None}
    if settings.enabled and user is None:
        payload["login_url"] = "/auth/login"
    return JSONResponse(payload, headers=AUTH_RESPONSE_HEADERS)


@router.get("/auth/login", include_in_schema=False)
async def login(request: Request):
    settings = get_auth_settings(request)
    origin = external_origin(request, settings)
    if settings.enabled:
        return begin_platform_login(request, settings, redirect_uri=f"{origin}/")
    response = RedirectResponse("/", status_code=302, headers=AUTH_RESPONSE_HEADERS)
    clear_auth_cookies(response, secure=origin.startswith("https://"))
    return response
