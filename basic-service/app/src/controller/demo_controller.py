"""Identity switching exists only when explicit demo mode is enabled."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse

from src.common.platform_auth import AUTH_RESPONSE_HEADERS, get_current_user
from .rd_dependencies import RdRoute
from src.service.rd_platform.demo import DEMO_COOKIE, DEMO_LOGGED_OUT_COOKIE, DEMO_USERS, demo_mode_enabled

router = APIRouter(prefix="/api/demo", tags=["演示模式"], route_class=RdRoute)


class IdentityBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    user_id: str


@router.get("/status")
def demo_status(request: Request):
    enabled = demo_mode_enabled()
    user = get_current_user(request) if enabled else None
    return JSONResponse({"enabled": enabled, "users": list(DEMO_USERS) if enabled else [], "current_user_id": user["userid"] if user else None}, headers=AUTH_RESPONSE_HEADERS)


@router.post("/identity")
def demo_identity(body: IdentityBody, request: Request):
    if not demo_mode_enabled():
        raise HTTPException(404, "演示模式未启用")
    if body.user_id not in {user["userid"] for user in DEMO_USERS}:
        raise HTTPException(422, "请选择允许的演示身份")
    response = JSONResponse({"enabled": True, "current_user_id": body.user_id}, headers=AUTH_RESPONSE_HEADERS)
    response.set_cookie(DEMO_COOKIE, body.user_id, httponly=True, samesite="lax", secure=request.url.scheme == "https", path="/")
    response.delete_cookie(DEMO_LOGGED_OUT_COOKIE, httponly=True, samesite="lax", secure=request.url.scheme == "https", path="/")
    return response
