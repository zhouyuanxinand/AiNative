"""Server-verified Smartvision identity for the taskbook application.

Read configuration when constructing the application, then install
``PlatformAuthMiddleware`` with that ``AuthSettings`` instance. The OA custom
application ID is independent from the model service's application ID.

Enabling authentication requires an explicit ``JTB_AUTH_PUBLIC_URL`` origin.
OA must preserve the query already present in ``redirect_uri`` when adding
``userid`` and ``token``: ``_jtb_auth_state`` binds that callback to a login
initiated in this browser. This requirement needs verification during OA
integration. No shared application session store is required.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from dotenv import dotenv_values
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

AUTH_RESPONSE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_COOKIE_NAMES = ("sv_appid", "sv_token", "sv_userid", "sv_username")
_LOGIN_STATE_COOKIE = "sv_login_state"
_LOGIN_STATE_QUERY = "_jtb_auth_state"
_LOGIN_STATE_MAX_AGE = 600
_NAME_KEYS = ("name", "username", "userName", "nickname", "realName", "real_name", "display_name")
_IDENTITY_QUERY_KEYS = frozenset(key.lower() for key in (
    "userid", "token", "appid", "app_id", *_NAME_KEYS, "displayName", "user_name", *_COOKIE_NAMES,
    _LOGIN_STATE_QUERY,
))
_CACHE_LIMIT = 512
_SIGNED_EDITOR_SERVER_PATH = re.compile(
    r"/api/review/[A-Za-z0-9_-]{1,128}/editor/[a-f0-9]{32}/(file|callback)"
)
_AUTH_ENV_GROUPS = (
    ("JTB_AUTH_ENABLED", "AUTH_ENABLED"),
    ("JTB_AUTH_APP_ID", "APP_ID"),
    ("JTB_AUTH_PLATFORM_BASE_URL", "PLATFORM_BASE_URL"),
    ("JTB_AUTH_PUBLIC_URL",),
    ("JTB_AUTH_TIMEOUT_SECONDS",),
    ("JTB_AUTH_CACHE_SECONDS",),
    ("JTB_AUTH_COOKIE_MAX_AGE",),
)
CurrentUser = Mapping[str, Any]
TokenVerifier = Callable[[str, str, int], Awaitable[dict[str, Any] | None]]


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
    parsed = urlsplit(value.strip())
    try:
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


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool = False
    app_id: int | None = None
    platform_base_url: str = "https://sv.dcsmartvision.com"
    public_url: str | None = None
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
        elif self.enabled:
            raise ValueError("JTB_AUTH_PUBLIC_URL is required when authentication is enabled")
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
            app_id=env.get("JTB_AUTH_APP_ID", env.get("APP_ID")),
            platform_base_url=env.get("JTB_AUTH_PLATFORM_BASE_URL", env.get("PLATFORM_BASE_URL", "https://sv.dcsmartvision.com")),
            public_url=env.get("JTB_AUTH_PUBLIC_URL") or None,
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
            async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
                response = await client.post(
                    f"{self.settings.platform_base_url}/tenant-api/api/auth/check-app-token",
                    json={"userid": userid, "token": token, "appid": appid},
                )
            if response.status_code >= 500:
                raise PlatformUnavailableError
            if not 200 <= response.status_code < 300:
                return None
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise PlatformUnavailableError from None
        if not isinstance(payload, dict):
            raise PlatformUnavailableError
        if type(payload.get("code")) is not int or payload["code"] != 0:
            return None
        return payload


def get_current_user(request: Request) -> CurrentUser | None:
    """Read the server-verified, immutable request identity; never inspect client claims."""
    return getattr(request.state, "current_user", None)


def get_auth_settings(request: Request) -> AuthSettings:
    settings = getattr(request.state, "auth_settings", None)
    if settings is None:
        settings = getattr(request.app.state, "auth_settings", None)
    return settings if settings is not None else AuthSettings()


def external_origin(request: Request, settings: AuthSettings) -> str:
    """Enabled auth always uses the configured origin; local mode may use request origin."""
    return settings.public_url or f"{request.url.scheme}://{request.url.netloc}"


def clean_request_url(request: Request, settings: AuthSettings) -> str:
    pairs = [(key, value) for key, value in request.query_params.multi_items() if key.lower() not in _IDENTITY_QUERY_KEYS]
    query = urlencode(pairs)
    return f"{external_origin(request, settings)}{request.url.path}" + (f"?{query}" if query else "")


def platform_login_url(settings: AuthSettings, redirect_uri: str) -> str:
    query = urlencode({"app_id": settings.app_id, "redirect_uri": redirect_uri})
    return f"{settings.platform_base_url}/oauth2/login?{query}"


def clear_auth_cookies(response: Response, *, secure: bool, include_login_state: bool = True) -> None:
    names = (*_COOKIE_NAMES, _LOGIN_STATE_COOKIE) if include_login_state else _COOKIE_NAMES
    for name in names:
        response.delete_cookie(name, path="/", httponly=True, secure=secure, samesite="lax")


def begin_platform_login(request: Request, settings: AuthSettings, *, redirect_uri: str | None = None) -> Response:
    """Issue a browser-bound login nonce and send only a clean return URL to OA."""
    state = secrets.token_urlsafe(32)
    clean_url = urlsplit(redirect_uri or clean_request_url(request, settings))
    query = [*parse_qsl(clean_url.query, keep_blank_values=True), (_LOGIN_STATE_QUERY, state)]
    return_url = urlunsplit((clean_url.scheme, clean_url.netloc, clean_url.path, urlencode(query), ""))
    response = RedirectResponse(platform_login_url(settings, return_url), status_code=302, headers=AUTH_RESPONSE_HEADERS)
    secure = external_origin(request, settings).startswith("https://")
    clear_auth_cookies(response, secure=secure, include_login_state=False)
    response.set_cookie(
        _LOGIN_STATE_COOKIE, state, max_age=_LOGIN_STATE_MAX_AGE, httponly=True,
        secure=secure, samesite="lax", path="/",
    )
    return response


def _verified_identity(userid: str, payload: dict[str, Any]) -> CurrentUser:
    name = ""
    for scope in (payload.get("data"), payload):
        if isinstance(scope, dict):
            for key in _NAME_KEYS:
                candidate = scope.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    name = candidate.strip()
                    break
        if name:
            break
    name = name or userid
    return MappingProxyType({
        "userid": userid, "name": name, "display_name": name, "source": "smartvision", "verified": True,
    })


class PlatformAuthMiddleware(BaseHTTPMiddleware):
    """Gate business requests using OA checks and a bounded, short-lived verification cache.

    ``verifier`` may be an async callable with ``(userid, token, appid)`` that
    returns a validated platform payload or ``None``, and raises
    ``PlatformUnavailableError`` when validation cannot be completed.
    """

    def __init__(self, app, *, settings: AuthSettings | None = None, verifier: TokenVerifier | None = None):
        super().__init__(app)
        self.settings = settings if settings is not None else AuthSettings.from_env()
        self.verifier = verifier if verifier is not None else PlatformTokenVerifier(self.settings)
        self._cache: OrderedDict[str, tuple[float, CurrentUser]] = OrderedDict()

    async def _verify(self, userid: str, token: str) -> CurrentUser | None:
        key = hashlib.sha256(json.dumps(
            [userid, token, self.settings.app_id], ensure_ascii=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            if cached[0] > time.monotonic():
                self._cache.move_to_end(key)
                return cached[1]
            del self._cache[key]
        payload = await self.verifier(userid, token, self.settings.app_id)
        if payload is None:
            return None
        user = _verified_identity(userid, payload)
        if self.settings.cache_seconds > 0:
            self._cache[key] = (time.monotonic() + self.settings.cache_seconds, user)
            self._cache.move_to_end(key)
            while len(self._cache) > _CACHE_LIMIT:
                self._cache.popitem(last=False)
        return user

    def _matches_app(self, appid: str | None) -> bool:
        if appid is None:
            return True
        try:
            return _app_id(appid) == self.settings.app_id
        except ValueError:
            return False

    def _reject(self, request: Request, *, force_json: bool = False) -> Response:
        if force_json or request.url.path.startswith("/api/"):
            response = JSONResponse(
                {"error": "请先登录神州问学。", "auth_required": True, "login_url": "/auth/login"},
                status_code=401, headers=AUTH_RESPONSE_HEADERS,
            )
        else:
            return begin_platform_login(request, self.settings)
        clear_auth_cookies(
            response, secure=external_origin(request, self.settings).startswith("https://"),
            include_login_state=False,
        )
        return response

    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.auth_settings = self.settings
        request.state.current_user = None
        path = request.url.path
        if not self.settings.enabled:
            return await call_next(request)
        if path == "/api/health" or path in {"/favicon.ico", "/assets", "/static"} or path.startswith(("/assets/", "/static/")):
            return await call_next(request)
        document_server = _SIGNED_EDITOR_SERVER_PATH.fullmatch(path)
        if document_server and (request.method, document_server.group(1)) in {("GET", "file"), ("POST", "callback")}:
            # ONLYOFFICE has no browser cookies. The controller still verifies
            # its signed file capability or signed callback before doing work.
            return await call_next(request)
        if path == "/auth/login":
            return await call_next(request)

        callback_userid = request.query_params.get("userid")
        callback_token = request.query_params.get("token")
        is_callback = bool(callback_userid and callback_token)
        userid = callback_userid if is_callback else request.cookies.get("sv_userid")
        token = callback_token if is_callback else request.cookies.get("sv_token")
        appid = request.query_params.get("appid") if is_callback else request.cookies.get("sv_appid")
        if not self._matches_app(appid):
            return self._reject(request, force_json=True)

        if is_callback:
            cookie_state = request.cookies.get(_LOGIN_STATE_COOKIE)
            query_state = request.query_params.get(_LOGIN_STATE_QUERY)
            if not (
                cookie_state and query_state
                and secrets.compare_digest(cookie_state.encode("utf-8"), query_state.encode("utf-8"))
            ):
                return begin_platform_login(request, self.settings)

        if userid and token:
            try:
                user = await self._verify(userid, token)
            except PlatformUnavailableError:
                return JSONResponse(
                    {"error": "登录验证服务暂时不可用，请稍后重试。"}, status_code=503, headers=AUTH_RESPONSE_HEADERS,
                )
            if user is None:
                return self._reject(request)
            request.state.current_user = user
            if is_callback:
                response = RedirectResponse(clean_request_url(request, self.settings), status_code=302, headers=AUTH_RESPONSE_HEADERS)
                secure = external_origin(request, self.settings).startswith("https://")
                for name, value in (("sv_appid", str(self.settings.app_id)), ("sv_token", token), ("sv_userid", userid)):
                    response.set_cookie(
                        name, value, max_age=self.settings.cookie_max_age, httponly=True,
                        secure=secure, samesite="lax", path="/",
                    )
                response.delete_cookie("sv_username", httponly=True, secure=secure, samesite="lax", path="/")
                response.delete_cookie(_LOGIN_STATE_COOKIE, httponly=True, secure=secure, samesite="lax", path="/")
                return response
        elif any(name in request.cookies for name in _COOKIE_NAMES) or path != "/api/current-user":
            return self._reject(request)

        response = await call_next(request)
        response.headers.update(AUTH_RESPONSE_HEADERS)
        return response
