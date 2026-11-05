"""Platform credential overrides, using the same SQLite contract as the sister services."""
from __future__ import annotations

import json
import hashlib
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

FIELDS = {
    "model": ("base_url", "app_id", "api_key", "tenant_id"),
}


def validate_credentials(payload: object) -> dict:
    if not isinstance(payload, dict) or set(payload) != set(FIELDS):
        raise ValueError("请提交模型凭证，或恢复部署默认。")
    result = {}
    for provider, fields in FIELDS.items():
        values = payload[provider]
        if values is None:
            result[provider] = None
            continue
        if not isinstance(values, dict) or set(values) != set(fields):
            raise ValueError("凭证字段不完整或包含未知字段。")
        cleaned = {}
        for field in fields:
            value = values[field]
            if not isinstance(value, str) or not value.strip() or len(value) > 4096 or any(c in value for c in "\r\n\x00"):
                raise ValueError("请完整填写有效凭证，或恢复本组默认。")
            value = value if field == "api_key" else value.strip()
            if field.endswith("url"):
                try:
                    parsed = urlsplit(value)
                    valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                             and not parsed.username and not parsed.password
                             and not parsed.query and not parsed.fragment
                             and not any(c.isspace() for c in value))
                    parsed.port
                except ValueError:
                    valid = False
                if not valid:
                    raise ValueError("请输入不含账号、密码或查询参数的 HTTP(S) 服务地址。")
            cleaned[field] = value
        result[provider] = cleaned
    return result


class ServiceCredentialStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> dict | None:
        if not self.path.exists():
            return None
        # LLM calls read this frequently. Schema/bootstrap writes belong to settings operations.
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'service_credentials'"
            ).fetchone() is None:
                return None
            return self._read(connection)

    def read_default_model(self, environment: str) -> dict | None:
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'default_model_selections'"
            ).fetchone() is None:
                return None
            row = connection.execute(
                "SELECT payload FROM default_model_selections WHERE environment = ?", (environment,),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def save_default_model(self, environment: str, selection: dict) -> None:
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS default_model_selections "
                "(environment TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO default_model_selections(environment, payload) VALUES (?, ?) "
                "ON CONFLICT(environment) DO UPDATE SET payload = excluded.payload",
                (environment, json.dumps(selection, ensure_ascii=False)),
            )

    @contextmanager
    def _connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            self.path.chmod(0o600)
            connection.row_factory = sqlite3.Row
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS service_credentials "
                    "(id INTEGER PRIMARY KEY CHECK(id = 1), payload TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS service_credential_history ("
                    "id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, name TEXT NOT NULL, "
                    "payload TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL, last_used_at TEXT)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS service_credential_imports ("
                    "source TEXT NOT NULL, fingerprint TEXT NOT NULL, PRIMARY KEY(source, fingerprint))"
                )
                yield connection

    @staticmethod
    def _read(connection) -> dict | None:
        row = connection.execute("SELECT payload FROM service_credentials WHERE id = 1").fetchone()
        return validate_credentials(json.loads(row[0])) if row else None

    @staticmethod
    def _write(connection, payload):
        connection.execute(
            "INSERT INTO service_credentials(id, payload) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
            (json.dumps(payload, ensure_ascii=False),),
        )

    @staticmethod
    def _snapshot(connection, model, *, name=None, source="manual", used=False):
        # A deployment may intentionally have no complete SmartVision credentials yet.
        try:
            model = validate_credentials({"model": model})["model"]
        except ValueError:
            return
        if model is None:
            return
        fingerprint = _fingerprint(model)
        stamp = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "INSERT INTO service_credential_history "
            "(id, fingerprint, name, payload, source, created_at, last_used_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(fingerprint) DO NOTHING",
            (uuid4().hex, fingerprint, name or f"{urlsplit(model['base_url']).netloc} · {model['app_id']}",
             json.dumps(model, ensure_ascii=False), source, stamp, stamp if used else None),
        )
        if used:
            connection.execute(
                "UPDATE service_credential_history SET last_used_at = ? WHERE fingerprint = ?",
                (stamp, fingerprint),
            )

    def _bootstrap(self, connection, defaults):
        # The import ledger survives history deletions, so deployment presets do not reappear.
        imports = [("deployment", "部署默认凭证", defaults.get("model"))]
        presets = json.loads(os.getenv("JTB_SERVICE_CREDENTIAL_PRESETS") or "[]")
        if not isinstance(presets, list):
            raise ValueError("预置凭证格式不正确。")
        for preset in presets:
            if not isinstance(preset, dict) or set(preset) != {"name", "model"}:
                raise ValueError("预置凭证格式不正确。")
            name = preset["name"]
            if not isinstance(name, str) or not name.strip() or len(name) > 120 or any(c in name for c in "\r\n\x00"):
                raise ValueError("预置凭证名称不正确。")
            model = validate_credentials({"model": preset["model"]})["model"]
            if model is None:
                raise ValueError("预置凭证字段不完整。")
            imports.append(("preset", name.strip(), model))
        for source, name, model in imports:
            try:
                model = validate_credentials({"model": model})["model"]
            except ValueError:
                continue
            if model is None:
                continue
            fingerprint = _fingerprint(model)
            inserted = connection.execute(
                "INSERT OR IGNORE INTO service_credential_imports (source, fingerprint) VALUES (?, ?)",
                (source, fingerprint),
            ).rowcount
            if inserted:
                self._snapshot(connection, model, name=name, source=source)
                if source == "preset":
                    connection.execute(
                        "UPDATE service_credential_history SET name = ?, source = ? WHERE fingerprint = ?",
                        (name, source, fingerprint),
                    )
        saved = self._read(connection)
        current = credentials_view(defaults, saved)["effective"].get("model")
        self._snapshot(connection, current, source="manual" if (saved or {}).get("model") else "deployment",
                       name=None if (saved or {}).get("model") else "部署默认凭证")

    def _view(self, connection, defaults):
        result = credentials_view(defaults, self._read(connection))
        active = _fingerprint(result["effective"].get("model"))
        history = []
        for row in connection.execute(
            "SELECT * FROM service_credential_history ORDER BY COALESCE(last_used_at, created_at) DESC, id"
        ):
            model = json.loads(row["payload"])
            history.append({
                "id": row["id"], "name": row["name"], "base_url": model["base_url"],
                "app_id": model["app_id"], "tenant_id": model["tenant_id"],
                "created_at": row["created_at"], "last_used_at": row["last_used_at"],
                "source": row["source"], "active": row["fingerprint"] == active,
            })
        result["history"] = history
        return result

    def view(self, defaults: dict) -> dict:
        with self._connection() as connection:
            self._bootstrap(connection, defaults)
            return self._view(connection, defaults)

    def save(self, payload: dict, defaults: dict | None = None) -> dict:
        validated = validate_credentials(payload)
        defaults = defaults or {"model": None}
        with self._connection() as connection:
            self._bootstrap(connection, defaults)
            self._write(connection, validated)
            model = credentials_view(defaults, validated)["effective"].get("model")
            self._snapshot(connection, model, used=True,
                           source="manual" if validated.get("model") else "deployment",
                           name=None if validated.get("model") else "部署默认凭证")
            return self._view(connection, defaults)

    def activate(self, history_id: str, defaults: dict, validator=None) -> dict:
        with self._connection() as connection:
            self._bootstrap(connection, defaults)
            row = connection.execute(
                "SELECT payload FROM service_credential_history WHERE id = ?", (history_id,),
            ).fetchone()
            if row is None:
                raise KeyError("历史凭证不存在或已删除。")
            model = validate_credentials({"model": json.loads(row["payload"])})["model"]
            if validator is not None:
                validator({"model": model})
            self._write(connection, {"model": model})
            self._snapshot(connection, model, used=True)
            return self._view(connection, defaults)

    def delete(self, history_id: str, defaults: dict) -> dict:
        with self._connection() as connection:
            self._bootstrap(connection, defaults)
            result = self._view(connection, defaults)
            target = next((item for item in result["history"] if item["id"] == history_id), None)
            if target is None:
                raise KeyError("历史凭证不存在或已删除。")
            if target["active"]:
                raise ActiveCredentialError("当前使用的凭证不能删除，请先切换到其他凭证。")
            connection.execute("DELETE FROM service_credential_history WHERE id = ?", (history_id,))
            return self._view(connection, defaults)


class ActiveCredentialError(ValueError):
    """History deletion must not implicitly change the active service connection."""


def _fingerprint(model) -> str:
    return hashlib.sha256(json.dumps(model, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def get_credential_store() -> ServiceCredentialStore:
    default = Path(__file__).resolve().parents[3] / "runtime" / "service_credentials.sqlite3"
    return ServiceCredentialStore(Path(os.getenv("JTB_SERVICE_CREDENTIALS_DB") or default))


def credentials_view(defaults: dict, saved: dict | None) -> dict:
    return {
        "defaults": defaults,
        "effective": {provider: (saved or {}).get(provider) or values for provider, values in defaults.items()},
        "overridden": [provider for provider, values in (saved or {}).items() if values is not None],
    }
