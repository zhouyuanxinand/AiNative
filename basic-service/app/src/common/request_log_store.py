"""Durable diagnostics for complete generation requests, shared by both services."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.runtime_logs import redact_log_text, sanitize_log_value

REQUEST_LOG_RETENTION = 50
MAX_REQUEST_LOG_PAGE = 500
_STATUSES = {"running", "success", "failed"}
_METADATA_FIELDS = {
    "job_id",
    "username",
    "userid",
    "request_kind",
    "product_type",
    "product_series",
    "model",
    "product_domain",
    "development_process",
    "process_classification",
    "product_scope",
    "cover_stage",
    "model_provider",
    "parent_jid",
    "delivery_status",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(value: Any, key: str = "") -> Any:
    # The common sanitizer protects credentials and document bodies. Prompts and
    # whole source documents are also excluded, including inside nested extras.
    if any(part in key.lower() for part in ("prompt", "source_document")):
        return "***"
    if isinstance(value, dict):
        value = {str(k): _safe(v, str(k)) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        value = [_safe(item) for item in value]
    return sanitize_log_value(value, key=key)


def _encode(value: Any) -> str:
    return json.dumps(
        _safe(value),
        ensure_ascii=False,
        default=lambda item: redact_log_text(str(item)),
    )


def _metadata(value: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: _safe(str(item or ""), key)
        for key, item in value.items()
        if key in _METADATA_FIELDS
    }
    if isinstance(value.get("files"), dict):
        result["files"] = {
            key: redact_log_text(str(item or "").replace("\\", "/").rsplit("/", 1)[-1])
            for key, item in value["files"].items()
            if key in {"tech", "spec", "output"}
        }
    return result


class RequestLogStore:
    """Each operation owns its connection; writers serialize in SQLite transactions."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS request_logs (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('running', 'success', 'failed')),
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_ms REAL,
                    error_summary TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS request_logs_status_started
                    ON request_logs(status, started_at DESC, sequence DESC);
                CREATE TABLE IF NOT EXISTS request_log_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL REFERENCES request_logs(request_id) ON DELETE CASCADE,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS request_log_entries_request_cursor
                    ON request_log_entries(request_id, id);
            """)

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

    def begin(self, request_id: str, metadata: dict[str, Any]) -> bool:
        if not request_id or len(request_id) > 200:
            raise ValueError("Invalid request id")
        with self._connect(write=True) as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO request_logs(request_id, status, started_at, metadata_json) VALUES (?, ?, ?, ?)",
                (request_id, "running", _now(), _encode(_metadata(metadata))),
            )
            return cursor.rowcount == 1

    def update_metadata(self, request_id: str, metadata: dict[str, Any]) -> bool:
        with self._connect(write=True) as connection:
            return self._update_metadata(connection, request_id, metadata)

    @staticmethod
    def _update_metadata(
        connection: sqlite3.Connection, request_id: str, metadata: dict[str, Any]
    ) -> bool:
        row = connection.execute(
            "SELECT metadata_json FROM request_logs WHERE request_id=?", (request_id,)
        ).fetchone()
        if row is None:
            return False
        current = json.loads(row["metadata_json"])
        update = _metadata(metadata)
        if "files" in update:
            update["files"] = {**current.get("files", {}), **update["files"]}
        connection.execute(
            "UPDATE request_logs SET metadata_json=? WHERE request_id=?",
            (_encode({**current, **update}), request_id),
        )
        return True

    def append(self, request_id: str, entry: dict[str, Any]) -> bool:
        payload = {
            "timestamp": _now(),
            "level": "INFO",
            "logger": "runtime",
            "message": "",
            **entry,
        }
        payload.pop("id", None)
        with self._connect(write=True) as connection:
            cursor = connection.execute(
                "INSERT INTO request_log_entries(request_id, payload_json) SELECT request_id, ? FROM request_logs WHERE request_id=?",
                (_encode(payload), request_id),
            )
            return cursor.rowcount == 1

    def finish(
        self,
        request_id: str,
        status: str = "success",
        error_summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        if status not in {"success", "failed"}:
            raise ValueError("Completed request status must be success or failed")
        with self._connect(write=True) as connection:
            row = connection.execute(
                "SELECT started_at, status FROM request_logs WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row is None or row["status"] != "running":
                return False
            finished_at = _now()
            duration_ms = max(
                0,
                (
                    datetime.fromisoformat(finished_at)
                    - datetime.fromisoformat(row["started_at"])
                ).total_seconds()
                * 1000,
            )
            if metadata:
                self._update_metadata(connection, request_id, metadata)
            connection.execute(
                "UPDATE request_logs SET status=?, finished_at=?, duration_ms=?, error_summary=? WHERE request_id=?",
                (
                    status,
                    finished_at,
                    round(duration_ms, 2),
                    redact_log_text(error_summary),
                    request_id,
                ),
            )
            self._prune(connection)
            return True

    @staticmethod
    def _prune(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM request_logs WHERE request_id IN (
                SELECT request_id FROM request_logs WHERE status <> 'running'
                ORDER BY started_at DESC, sequence DESC LIMIT -1 OFFSET ?
            )
        """,
            (REQUEST_LOG_RETENTION,),
        )

    def recover_interrupted(self) -> int:
        """Called only by the main service before accepting new generation jobs."""
        with self._connect(write=True) as connection:
            rows = connection.execute(
                "SELECT request_id, started_at FROM request_logs WHERE status='running'"
            ).fetchall()
            finished_at = _now()
            message = "平台重启，上次执行中的请求已中断，请重新生成。"
            for row in rows:
                duration_ms = max(
                    0,
                    (
                        datetime.fromisoformat(finished_at)
                        - datetime.fromisoformat(row["started_at"])
                    ).total_seconds()
                    * 1000,
                )
                connection.execute(
                    "UPDATE request_logs SET status=?, finished_at=?, duration_ms=?, error_summary=? WHERE request_id=?",
                    (
                        "failed",
                        finished_at,
                        round(duration_ms, 2),
                        message,
                        row["request_id"],
                    ),
                )
                connection.execute(
                    "INSERT INTO request_log_entries(request_id, payload_json) VALUES (?, ?)",
                    (
                        row["request_id"],
                        _encode(
                            {
                                "timestamp": finished_at,
                                "level": "ERROR",
                                "logger": "request_logs",
                                "message": message,
                                "event": "request_interrupted",
                                "error_type": "Interrupted",
                            }
                        ),
                    ),
                )
            self._prune(connection)
            return len(rows)

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict[str, Any]:
        metadata = json.loads(row["metadata_json"])
        result = {key: metadata.get(key, "") for key in _METADATA_FIELDS}
        result.update(
            {
                "request_id": row["request_id"],
                "status": row["status"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "duration_ms": row["duration_ms"],
                "error_summary": row["error_summary"],
                "event_count": row["event_count"],
                "files": {
                    "tech": "",
                    "spec": "",
                    "output": "",
                    **metadata.get("files", {}),
                },
            }
        )
        return result

    def list_requests(
        self, status: str | None = None, q: str | None = None
    ) -> dict[str, Any]:
        if status and status not in _STATUSES:
            raise ValueError("Invalid request status")
        with self._connect() as connection:
            # A read transaction keeps counts and list consistent while another
            # process finishes/prunes a request.
            connection.execute("BEGIN")
            counts = connection.execute(
                "SELECT status, count(*) AS count FROM request_logs GROUP BY status"
            ).fetchall()
            rows = connection.execute("""
                SELECT r.*, (SELECT count(*) FROM request_log_entries e WHERE e.request_id=r.request_id) AS event_count
                FROM request_logs r ORDER BY started_at DESC, sequence DESC
            """).fetchall()
        stats = {key: 0 for key in ("running", "success", "failed")}
        stats.update({row["status"]: row["count"] for row in counts})
        stats["total"] = sum(stats.values())
        items = [self._summary(row) for row in rows]
        if status:
            items = [item for item in items if item["status"] == status]
        if q and q.strip():
            needle = q.strip().casefold()
            items = [
                item
                for item in items
                if needle in json.dumps(item, ensure_ascii=False).casefold()
            ]
        return {"items": items, "retention": REQUEST_LOG_RETENTION, "stats": stats}

    def detail(
        self, request_id: str, after: int = 0, limit: int = MAX_REQUEST_LOG_PAGE
    ) -> dict[str, Any] | None:
        if after < 0 or not 1 <= limit <= MAX_REQUEST_LOG_PAGE:
            raise ValueError("Invalid log page cursor or limit")
        with self._connect() as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                """
                SELECT r.*, (SELECT count(*) FROM request_log_entries e WHERE e.request_id=r.request_id) AS event_count
                FROM request_logs r WHERE request_id=?
            """,
                (request_id,),
            ).fetchone()
            if row is None:
                return None
            entries = connection.execute(
                "SELECT id, payload_json FROM request_log_entries WHERE request_id=? AND id>? ORDER BY id LIMIT ?",
                (request_id, after, limit + 1),
            ).fetchall()
        page = [
            {**json.loads(entry["payload_json"]), "id": entry["id"]}
            for entry in entries[:limit]
        ]
        return {
            "request": self._summary(row),
            "entries": page,
            "next_cursor": page[-1]["id"] if page else after,
            "has_more": len(entries) > limit,
        }


def get_request_log_store(logs_dir: Path | str) -> RequestLogStore:
    override = os.environ.get("JTB_REQUEST_LOG_DB", "").strip()
    return RequestLogStore(
        Path(override)
        if override
        else Path(logs_dir).parent / "runtime" / "request_logs.sqlite3"
    )
