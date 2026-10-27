"""Administrator allowlist and opaque sessions for the separate admin service."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OWNER_USERNAME = "wangxue"
DEFAULT_SESSION_TTL_SECONDS = 8 * 60 * 60
_USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_.@-]{1,128}", flags=re.ASCII)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}", flags=re.ASCII)


class AdminAlreadyExistsError(ValueError):
    """The normalized OA account is already in the allowlist."""


class OwnerRemovalError(ValueError):
    """The bootstrap administrator cannot be removed."""


def normalize_admin_username(username: str) -> str:
    """Use the OA account identifier, never a display name or a Unicode lookalike."""
    if not isinstance(username, str):
        raise ValueError("管理员账号必须为字符串")  # noqa: TRY004 - one validation error contract
    value = username.strip()
    if _USERNAME_PATTERN.fullmatch(value) is None:
        raise ValueError("管理员账号限 1 至 128 个字母、数字、点、下划线、@ 或连字符")
    return value.casefold()


def _timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _context(app_id: str | int, base_url: str, origin: str) -> tuple[str, str, str]:
    if (
        isinstance(app_id, bool)
        or not isinstance(app_id, (str, int))
        or not isinstance(base_url, str)
        or not isinstance(origin, str)
    ):
        raise ValueError("管理员会话上下文无效")  # noqa: TRY004 - one validation error contract
    values = (str(app_id).strip(), str(base_url).strip(), str(origin).strip())
    if any(not value or len(value) > 2048 for value in values):
        raise ValueError("管理员会话必须绑定有效的应用编号、问学地址和访问地址")
    return values


def _token_hash(token: str) -> str | None:
    if not isinstance(token, str) or _TOKEN_PATTERN.fullmatch(token) is None:
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class AdminAccessStore:
    """SQLite transactions serialize membership changes and session issuance."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS admin_accounts (
                    username TEXT PRIMARY KEY,
                    is_owner INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    CHECK ((username = 'wangxue' AND is_owner = 1)
                        OR (username <> 'wangxue' AND is_owner = 0))
                );
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL REFERENCES admin_accounts(username)
                        ON DELETE CASCADE,
                    userid TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    app_id TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS admin_sessions_username
                    ON admin_sessions(username);
                CREATE INDEX IF NOT EXISTS admin_sessions_expiry
                    ON admin_sessions(expires_at);
                CREATE TABLE IF NOT EXISTS admin_login_states (
                    state_hash TEXT PRIMARY KEY,
                    app_id TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS admin_login_states_expiry
                    ON admin_login_states(expires_at);
            """)
            connection.execute(
                """INSERT OR IGNORE INTO admin_accounts
                    (username, is_owner, created_at, created_by) VALUES (?, 1, ?, ?)""",
                (OWNER_USERNAME, _timestamp(time.time()), "system"),
            )

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _account(row: sqlite3.Row) -> dict[str, Any]:
        return {**dict(row), "is_owner": bool(row["is_owner"])}

    def list_admins(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT username, is_owner, created_at, created_by
                   FROM admin_accounts ORDER BY is_owner DESC, username"""
            ).fetchall()
        return [self._account(row) for row in rows]

    def is_admin(self, username: str) -> bool:
        try:
            normalized = normalize_admin_username(username)
        except ValueError:
            return False
        with self._connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM admin_accounts WHERE username=?", (normalized,)
                ).fetchone()
                is not None
            )

    @staticmethod
    def _require_owner(actor: str) -> str:
        if normalize_admin_username(actor) != OWNER_USERNAME:
            raise PermissionError("只有 wangxue 可以管理管理员名单")
        return OWNER_USERNAME

    def add_admin(self, username: str, *, actor: str) -> dict[str, Any]:
        actor = self._require_owner(actor)
        normalized = normalize_admin_username(username)
        with self._connect(write=True) as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO admin_accounts
                    (username, is_owner, created_at, created_by) VALUES (?, 0, ?, ?)""",
                (normalized, _timestamp(time.time()), actor),
            )
            if cursor.rowcount == 0:
                raise AdminAlreadyExistsError("该账号已在管理员名单中")
            row = connection.execute(
                """SELECT username, is_owner, created_at, created_by
                   FROM admin_accounts WHERE username=?""",
                (normalized,),
            ).fetchone()
            return self._account(row)

    def remove_admin(self, username: str, *, actor: str) -> bool:
        self._require_owner(actor)
        normalized = normalize_admin_username(username)
        if normalized == OWNER_USERNAME:
            raise OwnerRemovalError("初始管理员 wangxue 不可删除")
        with self._connect(write=True) as connection:
            return (
                connection.execute(
                    "DELETE FROM admin_accounts WHERE username=?", (normalized,)
                ).rowcount
                == 1
            )

    def begin_login(
        self,
        *,
        app_id: str | int,
        base_url: str,
        origin: str,
        ttl_seconds: int = 300,
    ) -> str:
        context = _context(app_id, base_url, origin)
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or ttl_seconds <= 0
        ):
            raise ValueError("管理员登录状态有效期必须为正整数秒")
        now = time.time()
        state = secrets.token_urlsafe(32)
        with self._connect(write=True) as connection:
            connection.execute(
                "DELETE FROM admin_login_states WHERE expires_at<=?", (now,)
            )
            connection.execute(
                """INSERT INTO admin_login_states
                    (state_hash, app_id, base_url, origin, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                (_token_hash(state), *context, now, now + ttl_seconds),
            )
        return state

    def consume_login(
        self, state: str, *, app_id: str | int, base_url: str, origin: str
    ) -> bool:
        digest = _token_hash(state)
        if digest is None:
            return False
        context = _context(app_id, base_url, origin)
        with self._connect(write=True) as connection:
            return (
                connection.execute(
                    """DELETE FROM admin_login_states
                       WHERE state_hash=? AND app_id=? AND base_url=?
                         AND origin=? AND expires_at>?""",
                    (digest, *context, time.time()),
                ).rowcount
                == 1
            )

    def create_session(
        self,
        *,
        username: str,
        userid: str,
        display_name: str,
        app_id: str | int,
        base_url: str,
        origin: str,
        ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ) -> str:
        normalized = normalize_admin_username(username)
        context = _context(app_id, base_url, origin)
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or ttl_seconds <= 0
        ):
            raise ValueError("管理员会话有效期必须为正整数秒")
        now = time.time()
        token = secrets.token_urlsafe(32)
        with self._connect(write=True) as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM admin_accounts WHERE username=?", (normalized,)
                ).fetchone()
                is None
            ):
                raise PermissionError("该 OA 账号不在管理员名单中")
            connection.execute("DELETE FROM admin_sessions WHERE expires_at<=?", (now,))
            connection.execute(
                """INSERT INTO admin_sessions
                    (token_hash, username, userid, display_name, app_id, base_url,
                     origin, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    _token_hash(token),
                    normalized,
                    str(userid),
                    str(display_name),
                    *context,
                    now,
                    now + ttl_seconds,
                ),
            )
        return token

    def lookup_session(
        self, token: str, *, app_id: str | int, base_url: str, origin: str
    ) -> dict[str, Any] | None:
        digest = _token_hash(token)
        if digest is None:
            return None
        context = _context(app_id, base_url, origin)
        with self._connect() as connection:
            row = connection.execute(
                """SELECT s.username, s.userid, s.display_name, s.created_at,
                          s.expires_at, a.is_owner
                   FROM admin_sessions AS s
                   JOIN admin_accounts AS a ON a.username=s.username
                   WHERE s.token_hash=? AND s.app_id=? AND s.base_url=?
                     AND s.origin=? AND s.expires_at>?""",
                (digest, *context, time.time()),
            ).fetchone()
        if row is None:
            return None
        return {
            "username": row["username"],
            "userid": row["userid"],
            "display_name": row["display_name"],
            "is_owner": bool(row["is_owner"]),
            "created_at": _timestamp(row["created_at"]),
            "expires_at": _timestamp(row["expires_at"]),
        }

    def revoke_session(self, token: str) -> bool:
        digest = _token_hash(token)
        if digest is None:
            return False
        with self._connect(write=True) as connection:
            return (
                connection.execute(
                    "DELETE FROM admin_sessions WHERE token_hash=?", (digest,)
                ).rowcount
                == 1
            )


def get_admin_access_store(runtime_dir: Path | str) -> AdminAccessStore:
    configured = os.getenv("JTB_ADMIN_ACCESS_DB", "").strip()
    return AdminAccessStore(
        Path(configured) if configured else Path(runtime_dir) / "admin_access.sqlite3"
    )
