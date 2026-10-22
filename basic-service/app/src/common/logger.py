from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from src.common.request_context import (
    correlation_id_var,
    job_id_var,
    job_stage_var,
    request_archive_id_var,
)
from src.common.runtime_logs import redact_log_text, sanitize_log_value

LOGGER_NAME = "src"
_STANDARD_RECORD_KEYS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
# Keys that must never reach a log record. Credentials and prompts/outputs are
# considered sensitive even when attached as extra fields.
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "password",
    "credential",
    "secret",
    "prompt",
    "source_document",
    "source_text",
    "source_content",
    "document_text",
    "request_body",
    "response_body",
    "raw_response",
    "model_output",
)
_SENSITIVE_KEY_NAMES = {"token", "access_token", "id_token", "refresh_token"}


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in _SENSITIVE_KEY_NAMES or any(
        part in normalized for part in _SENSITIVE_KEY_PARTS
    )


class JsonFormatter(logging.Formatter):
    """Structured JSON log line carrying the request correlation id."""

    def format(self, record: logging.LogRecord) -> str:
        correlation_id = redact_log_text(
            str(getattr(record, "correlation_id", correlation_id_var.get()) or "-")
        )
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_log_text(record.getMessage()),
            "correlation_id": correlation_id,
        }
        job_id = getattr(record, "job_id", job_id_var.get())
        stage = getattr(record, "stage", job_stage_var.get())
        if job_id and job_id != "-":
            payload["job_id"] = redact_log_text(str(job_id))
        if stage and stage != "-":
            payload["stage"] = redact_log_text(str(stage))
        for key, value in record.__dict__.items():
            if (
                key in _STANDARD_RECORD_KEYS
                or key in {"correlation_id", "job_id", "stage"}
                or key.startswith("_")
                or _is_sensitive_key(key)
            ):
                continue
            try:
                safe_value = sanitize_log_value(value, key=key)
                json.dumps(safe_value)
                payload[key] = safe_value
            except TypeError:
                payload[key] = redact_log_text(str(value))
        if record.exc_info:
            payload["exception"] = redact_log_text(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, ensure_ascii=False)


class CorrelationIdFilter(logging.Filter):
    """Bind the active correlation id onto every record before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "correlation_id", None):
            record.correlation_id = correlation_id_var.get()
        if not getattr(record, "job_id", None):
            record.job_id = job_id_var.get()
        if not getattr(record, "stage", None):
            record.stage = job_stage_var.get()
        return True


class UvicornSafePathFilter(logging.Filter):
    """Keep HTTP diagnostics while excluding login credentials in query strings."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, path, version, status = record.args
            record.args = (client, method, str(path).split("?", 1)[0], version, status)
        return True


class RequestArchiveHandler(logging.Handler):
    """Persist all structured logs within the active generation request."""

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.setFormatter(JsonFormatter())
        self.addFilter(CorrelationIdFilter())

    def emit(self, record):
        request_id = request_archive_id_var.get()
        if not request_id:
            return
        try:
            self.store.append(request_id, json.loads(self.format(record)))
        except (OSError, sqlite3.Error):
            # Never log recursively or print the unredacted LogRecord on failure.
            sys.stderr.write("request archive storage unavailable\n")


def configure_logging(
    *,
    level: str = "INFO",
    log_dir: Path | str | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 7,
    archive_store=None,
) -> None:
    """Install the JSON formatter, correlation filter and rotating file handler."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, UvicornSafePathFilter) for item in access_logger.filters):
        access_logger.addFilter(UvicornSafePathFilter())
    # Reset any pre-existing handlers so reconfiguration (e.g. in tests) is clean.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JsonFormatter())
    stream_handler.addFilter(CorrelationIdFilter())
    root.addHandler(stream_handler)
    if archive_store is not None:
        root.addHandler(RequestArchiveHandler(archive_store))

    # The platform emits its own bounded HTTP/LLM diagnostics.  Raw transport
    # DEBUG logs otherwise crowd all useful task events out of the latest-log
    # window and may include request implementation details.
    for dependency_logger in (
        "httpcore",
        "httpx",
        "openai",
        "multipart",
        "asyncio",
    ):
        logging.getLogger(dependency_logger).setLevel(logging.WARNING)

    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path / "app.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(CorrelationIdFilter())
        root.addHandler(file_handler)

        error_handler = RotatingFileHandler(
            log_path / "app.error.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(JsonFormatter())
        error_handler.addFilter(CorrelationIdFilter())
        root.addHandler(error_handler)

    logging.getLogger(LOGGER_NAME).propagate = True


def shutdown_logging() -> None:
    for handler in logging.getLogger().handlers:
        try:
            handler.close()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass
        finally:
            logging.getLogger().removeHandler(handler)


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    return logging.getLogger(name)
