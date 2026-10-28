"""Shared HTTP dependencies and validation for R&D and assistant endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict

from src.common.platform_auth import get_current_user
from src.service.rd_platform.store import RdError


class RdRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def handle(request):
            try:
                return await handler(request)
            except RdError as exc:
                raise HTTPException(exc.status, exc.detail) from exc
            except RequestValidationError as exc:
                fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
                raise HTTPException(422, "请求字段格式不正确：" + fields) from exc
        return handle


def require_actor(request: Request) -> dict[str, str]:
    user = get_current_user(request)
    if not user or user.get("verified") is not True or not str(user.get("userid") or "").strip():
        raise HTTPException(401, "研发管理需要经过统一身份验证的登录用户")
    uid = str(user["userid"])
    return {"user_id": uid, "display_name": str(user.get("display_name") or user.get("name") or uid)}


Actor = Annotated[dict[str, str], Depends(require_actor)]
RequestKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=256)]


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
