from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from src.common.request_context import correlation_id_var

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
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(
                record, "correlation_id", correlation_id_var.get()
            ),
        }
        for key, value in record.__dict__.items():
            if (
                key in _STANDARD_RECORD_KEYS
                or key.startswith("_")
                or _is_sensitive_key(key)
            ):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except TypeError:
                payload[key] = str(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class CorrelationIdFilter(logging.Filter):
    """Bind the active correlation id onto every record before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "correlation_id", None):
            record.correlation_id = correlation_id_var.get()
        return True


def configure_logging(
    *,
    level: str = "INFO",
    log_dir: Path | str | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 7,
) -> None:
    """Install the JSON formatter, correlation filter and rotating file handler."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    # Reset any pre-existing handlers so reconfiguration (e.g. in tests) is clean.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JsonFormatter())
    stream_handler.addFilter(CorrelationIdFilter())
    root.addHandler(stream_handler)

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
