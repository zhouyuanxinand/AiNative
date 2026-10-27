"""Smartvision reference-compatible login for the taskbook application.

Read configuration when constructing the application, then install
``PlatformAuthMiddleware`` with that ``AuthSettings`` instance. The OA custom
application ID is independent from the model service's application ID.

An empty ``JTB_AUTH_PUBLIC_URL`` derives the callback from the current request,
including its published port. Automatic callback hosts are restricted to the
configured platform host, loopback, and explicit ``JTB_AUTH_CALLBACK_HOSTS``.
Direct ``userid`` and ``token`` callbacks are checked with the platform. Existing
application cookies follow the reference session flow only when the callback
does not select a different userid; a missing display name is backfilled without
blocking access. No shared session store is required.
"""
from __future__ import annotations

import logging
import math
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlsplit, urlunsplit

import httpx
from dotenv import dotenv_values
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from jonhon_taskbook.usage_context import model_user_scope

AUTH_RESPONSE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
COOKIE_APPID = "jtb_sv_appid"
COOKIE_TOKEN = "jtb_sv_token"
COOKIE_USERID = "jtb_sv_userid"
COOKIE_USERNAME = "jtb_sv_username"
_COOKIE_NAMES = (COOKIE_APPID, COOKIE_TOKEN, COOKIE_USERID, COOKIE_USERNAME)
_LEGACY_COOKIE_NAMES = ("sv_appid", "sv_token", "sv_userid", "sv_username", "sv_login_state")
_NAME_KEYS = (
    "sn", "name", "realName", "real_name", "trueName", "nickName", "nick_name",
    "displayName", "display_name", "user_name", "username", "userName", "nickname",
)
AUTH_PRESETS = MappingProxyType({
    "intranet": MappingProxyType({"app_id": 127, "platform_base_url": "http://172.23.255.36", "public_url": None}),
    "external": MappingProxyType({"app_id": 9086, "platform_base_url": "https://sv.dcsmartvision.com", "public_url": None}),
})
_SIGNED_EDITOR_SERVER_PATH = re.compile(
    r"/api/review/[A-Za-z0-9_-]{1,128}/editor/[a-f0-9]{32}/(file|callback)"
)
_AUTH_ENV_GROUPS = (
    ("JTB_AUTH_ENABLED", "AUTH_ENABLED"),
    ("JTB_AUTH_APP_ID", "APP_ID"),
    ("JTB_AUTH_PLATFORM_BASE_URL", "PLATFORM_BASE_URL"),
    ("JTB_AUTH_PUBLIC_URL",),
    ("JTB_AUTH_CALLBACK_HOSTS",),
    ("JTB_AUTH_TIMEOUT_SECONDS",),
    ("JTB_AUTH_CACHE_SECONDS",),
    ("JTB_AUTH_COOKIE_MAX_AGE",),
)
CurrentUser = Mapping[str, Any]
TokenVerifier = Callable[[str, str, int], Awaitable[dict[str, Any] | None]]
logger = logging.getLogger(__name__)


def _auth_environment() -> dict[str, str]:
    """Read only auth settings: process > project dotenv > packaged dotenv.

    Resolve aliases within each source, so an explicit process switch can
    override a baked switch regardless of which supported spelling it uses.
    Do not export file values into the process or change model configuration.
    """
    keys = {key for group in _AUTH_ENV_GROUPS for key in group}
    sources = [{key: value for key, value in os.environ.items() if key in keys}]
    module = Path(__file__).resolve()
    for path in (module.parents[4] / ".env", module.parents[1] / "service/.env"):
        if path.is_file():
            parsed = dotenv_values(path, encoding="utf-8-sig", interpolate=False)
            sources.append({key: value for key, value in parsed.items() if key in keys and value is not None})
    result = {}
    for names in _AUTH_ENV_GROUPS:
        for source in sources:
            chosen = next((source[name] for name in names if name in source), None)
            if chosen is not None:
                result[names[0]] = chosen
                break
    return result


def _http_url(value: str, name: str, *, origin_only: bool = False) -> str:
    try:
        parsed = urlsplit(value.strip())
        _ = parsed.port
    except ValueError:
        raise ValueError(f"{name} must be an HTTP(S) URL") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "\\" in parsed.netloc or "%" in parsed.netloc
        or any(character.isspace() for character in value)
        or (origin_only and parsed.path not in {"", "/"})
    ):
        raise ValueError(f"{name} must be an HTTP(S) origin" if origin_only else f"{name} must be an HTTP(S) URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _app_id(value: object) -> int | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    if not re.fullmatch(r"[0-9]+", text) or int(text) <= 0:
        raise ValueError("JTB_AUTH_APP_ID / APP_ID must be a positive numeric OA application ID")
    return int(text)


def _callback_host(value: str) -> str:
    """Validate one literal host, without accepting URLs, ports or wildcards."""
    value = value.strip().lower()
    authority = f"[{value}]" if ":" in value and not value.startswith("[") else value
    parsed = urlsplit(_http_url(f"http://{authority}", "JTB_AUTH_CALLBACK_HOSTS", origin_only=True))
    if parsed.port is not None or "*" in value:
        raise ValueError("JTB_AUTH_CALLBACK_HOSTS must contain hostnames without ports or wildcards")
    return parsed.hostname.rstrip(".")


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool = False
    app_id: int | None = AUTH_PRESETS["intranet"]["app_id"]
    platform_base_url: str = AUTH_PRESETS["intranet"]["platform_base_url"]
    public_url: str | None = None
    callback_hosts: tuple[str, ...] = ()
    timeout_seconds: float = 10
    cache_seconds: float = 60
    cookie_max_age: int = 28800

    def __post_init__(self) -> None:
        object.__setattr__(self, "app_id", _app_id(self.app_id))
        if self.enabled and self.app_id is None:
            raise ValueError("JTB_AUTH_APP_ID / APP_ID is required when authentication is enabled")
        object.__setattr__(self, "platform_base_url", _http_url(self.platform_base_url, "JTB_AUTH_PLATFORM_BASE_URL"))
        if self.public_url:
            object.__setattr__(self, "public_url", _http_url(self.public_url, "JTB_AUTH_PUBLIC_URL", origin_only=True))
        object.__setattr__(self, "callback_hosts", tuple(_callback_host(host) for host in self.callback_hosts))
        for field, name, allow_zero in (
            ("timeout_seconds", "JTB_AUTH_TIMEOUT_SECONDS", False),
            ("cache_seconds", "JTB_AUTH_CACHE_SECONDS", True),
            ("cookie_max_age", "JTB_AUTH_COOKIE_MAX_AGE", False),
        ):
            value = getattr(self, field)
            if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
                raise ValueError(f"{name} must be {'nonnegative' if allow_zero else 'positive'}")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AuthSettings:
        env = _auth_environment() if environ is None else environ
        if environ is None:
            from src.common.auth_settings_store import get_auth_settings_store

            saved = get_auth_settings_store().read()
            if saved is not None:
                desired = saved["settings"]
                env = {
                    **env,
                    "JTB_AUTH_ENABLED": "true" if desired["enabled"] else "false",
                    "JTB_AUTH_APP_ID": str(desired["app_id"]) if desired["app_id"] is not None else "",
                    "JTB_AUTH_PLATFORM_BASE_URL": desired["platform_base_url"],
                    "JTB_AUTH_PUBLIC_URL": desired["public_url"] or "",
                }
        enabled = env.get("JTB_AUTH_ENABLED", env.get("AUTH_ENABLED", "false")).strip().lower()
        if enabled not in {"true", "false"}:
            raise ValueError("JTB_AUTH_ENABLED / AUTH_ENABLED must be true or false")
        numeric = {}
        for field, name, default, converter in (
            ("timeout_seconds", "JTB_AUTH_TIMEOUT_SECONDS", "10", float),
            ("cache_seconds", "JTB_AUTH_CACHE_SECONDS", "60", float),
            ("cookie_max_age", "JTB_AUTH_COOKIE_MAX_AGE", "28800", int),
        ):
            try:
                numeric[field] = converter(env.get(name, default))
            except (ValueError, TypeError):
                raise ValueError(f"{name} must be numeric") from None
        return cls(
            enabled=enabled == "true",
            app_id=env.get("JTB_AUTH_APP_ID", env.get("APP_ID", str(AUTH_PRESETS["intranet"]["app_id"]))),
            platform_base_url=env.get("JTB_AUTH_PLATFORM_BASE_URL", env.get("PLATFORM_BASE_URL", AUTH_PRESETS["intranet"]["platform_base_url"])),
            public_url=env.get("JTB_AUTH_PUBLIC_URL") or None,
            callback_hosts=tuple(host.strip() for host in env.get("JTB_AUTH_CALLBACK_HOSTS", "").split(",") if host.strip()),
            **numeric,
        )


def get_deployment_auth_settings() -> AuthSettings:
    """Read deployment defaults, without consulting the editable saved profile."""
    return AuthSettings.from_env(_auth_environment())


class PlatformUnavailableError(Exception):
    """The token validation service did not produce a usable response."""


class PlatformTokenVerifier:
    """Validate credentials with the configured OA application, without logging secrets."""

    def __init__(self, settings: AuthSettings):
        self.settings = settings

    async def __call__(self, userid: str, token: str, appid: int) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.settings.timeout_seconds, trust_env=False) as client:
                response = await client.post(
                    f"{self.settings.platform_base_url}/tenant-api/api/auth/check-app-token",
                    json={"userid": userid, "token": token, "appid": appid},
                )
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise PlatformUnavailableError from None
        if not isinstance(payload, dict):
            raise PlatformUnavailableError
        if payload.get("code") != 0:
            return None
        return payload


def get_current_user(request: Request) -> CurrentUser | None:
    """Read the immutable identity established by the application login flow."""
    return getattr(request.state, "current_user", None)


def get_auth_settings(request: Request) -> AuthSettings:
    settings = getattr(request.state, "auth_settings", None)
    if settings is None:
        settings = getattr(request.app.state, "auth_settings", None)
    return settings if settings is not None else AuthSettings()


def external_origin(request: Request, settings: AuthSettings) -> str:
    """Keep the published port from Host; do not trust raw forwarding headers.

    The bundled nginx preserves Host (including port), and overwrites protocol
    headers for uvicorn's trusted loopback proxy. Custom proxy deployments may
    configure a fixed origin or allow their public hostname without a port.
    """
    if settings.public_url:
        return settings.public_url
    origin = _http_url(f"{request.url.scheme}://{request.url.netloc}", "request origin", origin_only=True)
    host = urlsplit(origin).hostname.rstrip(".").lower()
    if settings.enabled and host not in {
        "localhost", "127.0.0.1", "::1",
        urlsplit(settings.platform_base_url).hostname.rstrip(".").lower(),
        *settings.callback_hosts,
    }:
        raise ValueError("Automatic callback host is not allowed")
    return origin


def clean_request_url(request: Request, settings: AuthSettings) -> str:
    pairs = [
        (key, str(settings.app_id) if key == "appid" else value)
        for key, value in request.query_params.multi_items()
        if key not in {"userid", "token", "_jtb_auth_state"}
    ]
    query = urlencode(pairs)
    return f"{external_origin(request, settings)}{request.url.path}" + (f"?{query}" if query else "")


def platform_login_url(settings: AuthSettings, redirect_uri: str) -> str:
    query = urlencode({"app_id": settings.app_id, "redirect_uri": redirect_uri, "login_mode": "auto"})
    return f"{settings.platform_base_url}/oauth2/login?{query}"


def clear_auth_cookies(response: Response, *, secure: bool) -> None:
    for name in (*_COOKIE_NAMES, *_LEGACY_COOKIE_NAMES):
        response.delete_cookie(name, path="/", httponly=True, secure=secure, samesite="lax")


def begin_platform_login(request: Request, settings: AuthSettings, *, redirect_uri: str | None = None) -> Response:
    """Use the platform reference auto-login request with the clean return URL."""
    return_url = redirect_uri or clean_request_url(request, settings)
    response = RedirectResponse(platform_login_url(settings, return_url), status_code=307, headers=AUTH_RESPONSE_HEADERS)
    secure = external_origin(request, settings).startswith("https://")
    clear_auth_cookies(response, secure=secure)
    return response


def _verified_identity(userid: str, payload: dict[str, Any]) -> CurrentUser:
    name = ""
    for scope in (payload.get("data"), payload):
        if isinstance(scope, dict):
            for key in _NAME_KEYS:
                candidate = str(scope.get(key) or "").strip()
                if candidate:
                    name = candidate
                    break
        if name:
            break
    name = name or userid
    return MappingProxyType({
        "userid": userid, "name": name, "display_name": name, "source": "smartvision", "verified": True,
    })


class PlatformAuthMiddleware(BaseHTTPMiddleware):
    """Match the platform callback and existing application-cookie session flow.

    ``verifier`` may be an async callable with ``(userid, token, appid)`` that
    returns a validated platform payload or ``None``, and raises
    ``PlatformUnavailableError`` when validation cannot be completed.
    """

    def __init__(self, app, *, settings: AuthSettings | None = None, verifier: TokenVerifier | None = None):
        super().__init__(app)
        self.settings = settings if settings is not None else AuthSettings.from_env()
        self.verifier = verifier if verifier is not None else PlatformTokenVerifier(self.settings)
        self._backfill_cooldown_until = 0.0

    async def _verify(self, userid: str, token: str) -> CurrentUser | None:
        payload = await self.verifier(userid, token, self.settings.app_id)
        if payload is None:
            return None
        return _verified_identity(userid, payload)

    def _reject(self, request: Request) -> Response:
        if request.url.path.startswith("/api/"):
            response = JSONResponse(
                {"success": False, "error": "未登录或登录已失效", "auth_required": True, "login_url": "/auth/login"},
                status_code=401, headers=AUTH_RESPONSE_HEADERS,
            )
        else:
            return begin_platform_login(request, self.settings)
        clear_auth_cookies(
            response, secure=external_origin(request, self.settings).startswith("https://"),
        )
        return response

    async def dispatch(self, request: Request, call_next) -> Response:
        # Public/local requests have no OA identity. Never inherit attribution
        # from an enclosing task; authenticated work binds its own userid below.
        with model_user_scope():
            return await self._dispatch_authenticated(request, call_next)

    async def _dispatch_authenticated(self, request: Request, call_next) -> Response:
        request.state.auth_settings = self.settings
        request.state.current_user = None
        path = request.url.path
        if not self.settings.enabled:
            return await call_next(request)
        if path in {"/api/health", "/favicon.ico", "/assets", "/static", "/logged-out", "/api/system/logout"} or path.startswith(("/assets/", "/static/")):
            return await call_next(request)
        document_server = _SIGNED_EDITOR_SERVER_PATH.fullmatch(path)
        if document_server and (request.method, document_server.group(1)) in {("GET", "file"), ("POST", "callback")}:
            # ONLYOFFICE has no browser cookies. The controller still verifies
            # its signed file capability or signed callback before doing work.
            return await call_next(request)
        try:
            external_origin(request, self.settings)
        except ValueError:
            return JSONResponse(
                {"error": "当前访问地址不能用于自动回跳，请使用配置的主站地址，或由运维设置回跳地址。"},
                status_code=400, headers=AUTH_RESPONSE_HEADERS,
            )
        if path == "/auth/login":
            return await call_next(request)

        cookie_userid = request.cookies.get(COOKIE_USERID, "")
        cookie_token = request.cookies.get(COOKIE_TOKEN, "")
        query_userid = request.query_params.get("userid")
        matching_user = query_userid is None or cookie_userid == query_userid
        application_session = cookie_userid and cookie_token and request.cookies.get(COOKIE_APPID) == str(self.settings.app_id)
        if application_session and not matching_user:
            # A new OA account must be validated instead of being hidden by the
            # old session. Log the decision, never either credential's value.
            logger.info("platform_auth_user_mismatch", extra={
                "callback_user_present": bool(query_userid),
                "callback_token_present": bool(request.query_params.get("token")),
            })
        if application_session and matching_user:
            username = unquote(request.cookies.get(COOKIE_USERNAME, "") or "")
            request.state.current_user = _verified_identity(cookie_userid, {"data": {"sn": username}})
            if any(key in request.query_params for key in ("userid", "token")):
                response = RedirectResponse(clean_request_url(request, self.settings), status_code=307, headers=AUTH_RESPONSE_HEADERS)
            else:
                with model_user_scope(cookie_userid):
                    response = await call_next(request)
            if COOKIE_USERNAME not in request.cookies and time.time() >= self._backfill_cooldown_until:
                try:
                    user = await self._verify(cookie_userid, cookie_token)
                except PlatformUnavailableError:
                    user = None
                if user is not None:
                    response.set_cookie(
                        COOKIE_USERNAME, quote(user["name"]), httponly=True,
                        secure=external_origin(request, self.settings).startswith("https://"),
                        samesite="lax", path="/",
                    )
                else:
                    self._backfill_cooldown_until = time.time() + 60
            response.headers.update(AUTH_RESPONSE_HEADERS)
            return response

        if path == "/api/current-user" and not any(name in request.cookies for name in (*_COOKIE_NAMES, *_LEGACY_COOKIE_NAMES)):
            response = await call_next(request)
            response.headers.update(AUTH_RESPONSE_HEADERS)
            return response
        if path.startswith("/api/"):
            return self._reject(request)

        userid = query_userid
        token = request.query_params.get("token")
        callback_appid = request.query_params.get("appid")
        if userid and token and (not callback_appid or callback_appid == str(self.settings.app_id)):
            try:
                user = await self._verify(userid, token)
            except PlatformUnavailableError:
                user = None
            if user is not None:
                request.state.current_user = user
                response = RedirectResponse(clean_request_url(request, self.settings), status_code=307, headers=AUTH_RESPONSE_HEADERS)
                secure = external_origin(request, self.settings).startswith("https://")
                for name in _LEGACY_COOKIE_NAMES:
                    response.delete_cookie(name, httponly=True, secure=secure, samesite="lax", path="/")
                for name, value in (
                    (COOKIE_APPID, str(self.settings.app_id)), (COOKIE_TOKEN, token),
                    (COOKIE_USERID, userid), (COOKIE_USERNAME, quote(user["name"])),
                ):
                    response.set_cookie(
                        name, value, httponly=True,
                        secure=secure, samesite="lax", path="/",
                    )
                return response
        return begin_platform_login(request, self.settings)
