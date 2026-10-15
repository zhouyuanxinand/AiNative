"""Versioned, restart-only login settings; this database contains no credentials."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

AUTH_SETTINGS_FIELDS = ("enabled", "app_id", "platform_base_url", "public_url")


class AuthSettingsConflictError(ValueError):
    """Another editor saved the profile after it was loaded."""


def validate_auth_profile(payload: Any) -> dict[str, Any]:
    """Validate the four editable fields using the runtime's URL/ID rules."""
    from src.common.platform_auth import AuthSettings

    invalid = "统一登录配置格式不正确，请检查启用开关、应用编号和 HTTP(S) 地址。"
    if (
        not isinstance(payload, dict)
        or set(payload) != set(AUTH_SETTINGS_FIELDS)
        or type(payload["enabled"]) is not bool
        or not isinstance(payload["platform_base_url"], str)
        or (payload["public_url"] is not None and not isinstance(payload["public_url"], str))
        or (payload["app_id"] is not None and type(payload["app_id"]) not in (int, str))
    ):
        raise ValueError(invalid)
    try:
        settings = AuthSettings(**{**payload, "public_url": payload["public_url"] or None})
    except (ValueError, TypeError):
        raise ValueError(invalid) from None
    return {field: getattr(settings, field) for field in AUTH_SETTINGS_FIELDS}


def validate_expected_version(version: Any) -> int:
    if type(version) is not int or version < 0:
        raise ValueError("配置版本无效，请刷新页面后重试。")
    return version


class AuthSettingsStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()

    def read(self) -> dict[str, Any] | None:
        """Read without creating a database or an initial profile on GET."""
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, timeout=10)) as connection:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='auth_settings'").fetchone() is None:
                return None
            row = connection.execute("SELECT profile, version FROM auth_settings WHERE id=1").fetchone()
        if row is None:
            return None
        profile, version = row
        if type(version) is not int or version <= 0:
            raise ValueError("统一登录配置版本损坏。")
        return {"settings": validate_auth_profile(json.loads(profile)), "version": version}

    def save(self, profile: dict[str, Any], *, expected_version: int) -> dict[str, Any]:
        profile = validate_auth_profile(profile)
        expected_version = validate_expected_version(expected_version)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS auth_settings ("
                "id INTEGER PRIMARY KEY CHECK(id=1), profile TEXT NOT NULL, version INTEGER NOT NULL)"
            )
            row = connection.execute("SELECT version FROM auth_settings WHERE id=1").fetchone()
            version = row[0] if row else 0
            if version != expected_version:
                raise AuthSettingsConflictError("统一登录设置已被其他页面修改，请刷新后重试。")
            version += 1
            connection.execute(
                "INSERT INTO auth_settings (id, profile, version) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET profile=excluded.profile, version=excluded.version",
                (json.dumps(profile, ensure_ascii=False, separators=(",", ":")), version),
            )
        return {"settings": profile, "version": version}


def get_auth_settings_store() -> AuthSettingsStore:
    default = Path(__file__).resolve().parents[2] / "runtime/auth_settings.sqlite3"
    return AuthSettingsStore(os.environ.get("JTB_AUTH_SETTINGS_DB") or default)
