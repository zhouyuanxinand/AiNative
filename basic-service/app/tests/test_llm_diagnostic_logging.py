from __future__ import annotations

import json
import logging
from unittest.mock import patch

import httpx
import pytest
from jonhon_taskbook import llm_client as llm

CONFIG = llm.LLMConfig(
    provider="smartvision",
    api_key="diagnostic-secret-key",
    endpoint="https://diagnostic.example/chat/completions",
    model="qwen3.8",
    app_id="diagnostic-app-id",
    tenant_id="diagnostic-tenant-id",
    max_tokens=4096,
)


def _completion(content: str = "OK") -> httpx.Response:
    return httpx.Response(
        200,
        request=httpx.Request("POST", CONFIG.endpoint),
        json={
            "choices": [
                {"finish_reason": "stop", "message": {"content": content}}
            ],
            "usage": {
                "completion_tokens": 23,
                "completion_tokens_details": {"reasoning_tokens": 7},
            },
        },
    )


def _events(caplog) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == llm.__name__
        and record.getMessage().startswith("llm_call_")
    ]


def _assert_common_fields(record: logging.LogRecord) -> None:
    for field in (
        "provider",
        "model",
        "operation",
        "attempt",
        "max_attempts",
        "duration_ms",
        "status_code",
        "error_type",
        "finish_reason",
        "completion_tokens",
        "reasoning_tokens",
        "content_chars",
    ):
        assert hasattr(record, field)


def _serialized(records: list[logging.LogRecord]) -> str:
    return json.dumps(
        [record.__dict__ for record in records],
        ensure_ascii=False,
        default=str,
    )


def test_retryable_500_then_200_logs_retry_and_completion_without_content(caplog):
    private_output = "private-model-output"
    failure = httpx.Response(
        500,
        request=httpx.Request("POST", CONFIG.endpoint),
        text=(
            f"api_key={CONFIG.api_key} app={CONFIG.app_id} "
            f"tenant={CONFIG.tenant_id} private-response-body"
        ),
    )
    caplog.set_level(logging.INFO, logger=llm.__name__)

    with (
        patch.object(llm, "_active_config", return_value=CONFIG),
        patch.object(llm.httpx, "post", side_effect=[failure, _completion(private_output)]) as post,
        patch.object(llm.time, "sleep") as sleep,
    ):
        assert llm.chat("private-system-prompt", "private-user-prompt", retries=2) == private_output

    assert post.call_count == 2
    sleep.assert_called_once_with(1.0)
    records = _events(caplog)
    assert [record.getMessage() for record in records] == [
        "llm_call_retrying",
        "llm_call_completed",
    ]
    for record in records:
        _assert_common_fields(record)
        assert record.provider == "smartvision"
        assert record.model == "qwen3.8"
        assert record.operation == "chat"
        assert record.max_attempts == 2
        assert record.duration_ms >= 0

    retrying, completed = records
    assert retrying.attempt == 1
    assert retrying.status_code == 500
    assert retrying.error_type == "service_unavailable"
    assert completed.attempt == 2
    assert completed.status_code == 200
    assert completed.error_type == ""
    assert completed.finish_reason == "stop"
    assert completed.completion_tokens == 23
    assert completed.reasoning_tokens == 7
    assert completed.content_chars == len(private_output)

    logged = _serialized(records)
    for sensitive in (
        CONFIG.api_key,
        CONFIG.app_id,
        CONFIG.tenant_id,
        "private-response-body",
        private_output,
        "private-system-prompt",
        "private-user-prompt",
        CONFIG.endpoint,
    ):
        assert sensitive not in logged


def test_timeout_logs_safe_final_failure(caplog):
    request = httpx.Request("POST", CONFIG.endpoint)
    caplog.set_level(logging.INFO, logger=llm.__name__)
    timeout = httpx.ReadTimeout(
        f"{CONFIG.api_key} private-timeout-detail",
        request=request,
    )

    with (
        patch.object(llm, "_active_config", return_value=CONFIG),
        patch.object(llm.httpx, "post", side_effect=timeout) as post,
        pytest.raises(RuntimeError, match="网络异常"),
    ):
        llm.chat("private-system-prompt", "private-user-prompt", retries=1)

    assert post.call_count == 1
    records = _events(caplog)
    assert len(records) == 1
    failed = records[0]
    _assert_common_fields(failed)
    assert failed.getMessage() == "llm_call_failed"
    assert failed.attempt == failed.max_attempts == 1
    assert failed.status_code is None
    assert failed.error_type == "timeout"
    assert "private-timeout-detail" not in _serialized(records)
    assert CONFIG.api_key not in _serialized(records)


def test_authentication_failure_is_logged_once_and_not_retried(caplog):
    error = httpx.Response(
        401,
        request=httpx.Request("POST", CONFIG.endpoint),
        text=f"{CONFIG.api_key} {CONFIG.app_id} {CONFIG.tenant_id} private-body",
    )
    caplog.set_level(logging.INFO, logger=llm.__name__)

    with (
        patch.object(llm, "_active_config", return_value=CONFIG),
        patch.object(llm.httpx, "post", return_value=error) as post,
        pytest.raises(RuntimeError, match="HTTP 401"),
    ):
        llm.chat("private-system-prompt", "private-user-prompt", retries=3)

    assert post.call_count == 1
    records = _events(caplog)
    assert len(records) == 1
    failed = records[0]
    _assert_common_fields(failed)
    assert failed.getMessage() == "llm_call_failed"
    assert failed.attempt == 1 and failed.max_attempts == 3
    assert failed.status_code == 401
    assert failed.error_type == "authentication_failed"
    logged = _serialized(records)
    for sensitive in (
        CONFIG.api_key,
        CONFIG.app_id,
        CONFIG.tenant_id,
        "private-body",
        "private-system-prompt",
        "private-user-prompt",
    ):
        assert sensitive not in logged
