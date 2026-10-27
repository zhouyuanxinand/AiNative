from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_FILE_NAME = "app.log"
DEFAULT_LOG_LIMIT = 200
MAX_LOG_LIMIT = 500

# Bound both disk I/O and response size.  The application log is line-oriented
# JSON, so reading backwards avoids loading a multi-megabyte rotating file just
# to show its most recent entries.
_READ_CHUNK_BYTES = 64 * 1024
_MAX_SCAN_BYTES = 2 * 1024 * 1024
_MAX_LINE_CHARS = 12_000
_MAX_SCAN_LINES = 5_000
_TRANSPORT_LOGGER_PREFIXES = (
    "httpcore",
    "httpx",
    "openai",
    "multipart",
    "asyncio",
)

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "credential",
    "secret",
    "access_token",
    "refresh_token",
    "id_token",
    "source_text",
    "source_content",
    "document_text",
    "request_body",
    "response_body",
    "raw_response",
    "model_output",
)
_SENSITIVE_KEY_NAMES = {"token", "api-key", "x-api-key", "proxy-authorization"}
_REDACTED = "***"

# These patterns also protect secrets embedded in a message string rather than
# attached as structured logging fields.
_BEARER_PATTERN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")
_KEY_VALUE_PATTERN = re.compile(
    r"(?ix)"
    r"([\"']?\b(?:(?:[a-z0-9]+[_-])*(?:api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|id[_-]?token|token|password|secret)|"
    r"authorization|proxy-authorization)\b[\"']?"
    r"\s*[:=]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|Bearer\s+[A-Za-z0-9._~+/=-]+|[^\s,;}&]+)"
)
_QUERY_SECRET_PATTERN = re.compile(
    r"(?i)([?&](?:api[_-]?key|token|access[_-]?token|secret)=)[^&#\s]+"
)
_SMARTVISION_KEY_PATTERN = re.compile(r"(?i)\bsk[_-][A-Za-z0-9_-]{8,}\b")


def _is_sensitive_key(key: str) -> bool:
    normalized = str(key).strip().lower()
    return normalized in _SENSITIVE_KEY_NAMES or any(
        part in normalized for part in _SENSITIVE_KEY_PARTS
    )


def redact_log_text(value: str) -> str:
    """Remove common credential forms from free-form log text."""

    text = _KEY_VALUE_PATTERN.sub(lambda match: match.group(1) + _REDACTED, str(value))
    text = _BEARER_PATTERN.sub(r"\1" + _REDACTED, text)
    text = _QUERY_SECRET_PATTERN.sub(lambda match: match.group(1) + _REDACTED, text)
    return _SMARTVISION_KEY_PATTERN.sub("sk_" + _REDACTED, text)


def sanitize_log_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Return a JSON-safe, redacted value suitable for persisted diagnostics."""

    if key and _is_sensitive_key(key):
        return _REDACTED
    if depth >= 12:
        return "[日志嵌套层级已截断]"
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_log_value(
                item, key=str(item_key), depth=depth + 1
            )
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_log_value(item, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return [sanitize_log_value(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        return redact_log_text(value)
    return value


def _tail_lines(path: Path, limit: int) -> tuple[list[str], bool]:
    """Return at most ``limit`` complete tail lines with bounded disk reads."""

    with path.open("rb") as stream:
        stream.seek(0, 2)
        file_size = stream.tell()
        position = file_size
        data = b""
        while position > 0 and data.count(b"\n") <= limit and len(data) < _MAX_SCAN_BYTES:
            read_size = min(_READ_CHUNK_BYTES, position, _MAX_SCAN_BYTES - len(data))
            if read_size <= 0:
                break
            position -= read_size
            stream.seek(position)
            data = stream.read(read_size) + data

    truncated = position > 0
    lines = data.splitlines()
    # When scanning stopped before the beginning of the file, the first bytes
    # may start in the middle of a UTF-8 line.  Never expose that fragment.
    if truncated and lines:
        lines = lines[1:]
    decoded = [line.decode("utf-8", errors="replace") for line in lines[-limit:]]
    return decoded, truncated or len(lines) > limit


def _entry_from_line(line: str) -> dict[str, Any]:
    clipped = line
    was_clipped = len(clipped) > _MAX_LINE_CHARS
    if was_clipped:
        clipped = clipped[:_MAX_LINE_CHARS] + "…[日志行已截断]"
    try:
        parsed = json.loads(clipped)
    except (json.JSONDecodeError, UnicodeError):
        entry: dict[str, Any] = {
            "timestamp": "",
            "level": "INFO",
            "logger": "runtime",
            "message": redact_log_text(clipped),
        }
    else:
        if isinstance(parsed, dict):
            entry = sanitize_log_value(parsed)
            # Older log files used ``exc_info`` while the browser contract uses
            # ``exception``.  Normalize on read so historical failures remain
            # diagnosable after the logging format is upgraded.
            if "exception" not in entry and entry.get("exc_info"):
                entry["exception"] = entry.pop("exc_info")
            entry.setdefault("timestamp", "")
            entry.setdefault("level", "INFO")
            entry.setdefault("logger", "runtime")
            entry.setdefault("message", "")
        else:
            entry = {
                "timestamp": "",
                "level": "INFO",
                "logger": "runtime",
                "message": redact_log_text(clipped),
            }
    if was_clipped:
        entry["line_truncated"] = True
    return entry


def _is_low_value_transport(entry: dict[str, Any]) -> bool:
    """Hide routine transport chatter while retaining transport warnings/errors."""

    logger_name = str(entry.get("logger") or "").lower()
    level = str(entry.get("level") or "INFO").upper()
    return level in {"DEBUG", "INFO"} and logger_name.startswith(
        _TRANSPORT_LOGGER_PREFIXES
    )


def read_latest_logs(logs_dir: Path | str, limit: int = DEFAULT_LOG_LIMIT) -> dict[str, Any]:
    """Read the current application log only; callers cannot select a path."""

    bounded_limit = max(1, min(int(limit), MAX_LOG_LIMIT))
    log_path = Path(logs_dir) / LOG_FILE_NAME
    if not log_path.is_file():
        return {
            "entries": [],
            "returned": 0,
            "limit": bounded_limit,
            "source": LOG_FILE_NAME,
            "updated_at": None,
            "truncated": False,
            "filtered_transport": 0,
        }

    # Scan farther back than the response limit because historical DEBUG-level
    # HTTP transport chatter may occupy the raw tail.  The response still
    # contains only the latest bounded set of actionable records.
    scan_limit = min(_MAX_SCAN_LINES, max(bounded_limit, bounded_limit * 10))
    lines, truncated = _tail_lines(log_path, scan_limit)
    parsed = [_entry_from_line(line) for line in lines if line.strip()]
    actionable = [entry for entry in parsed if not _is_low_value_transport(entry)]
    entries = actionable[-bounded_limit:]
    modified = datetime.fromtimestamp(log_path.stat().st_mtime, timezone.utc).isoformat()
    return {
        "entries": entries,
        "returned": len(entries),
        "limit": bounded_limit,
        "source": LOG_FILE_NAME,
        "updated_at": modified,
        "truncated": truncated or len(actionable) > bounded_limit,
        "filtered_transport": len(parsed) - len(actionable),
    }
