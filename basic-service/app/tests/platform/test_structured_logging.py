from __future__ import annotations

import json
import logging
import sys

from src.common.logger import CorrelationIdFilter, JsonFormatter
from src.common.request_context import correlation_id_var, job_id_var, job_stage_var


def test_formatter_emits_diagnostic_context_and_redacts_disk_payload():
    correlation_token = correlation_id_var.set("request-123")
    job_token = job_id_var.set("job-456")
    stage_token = job_stage_var.set("semantic_plan")
    try:
        try:
            raise RuntimeError(
                "provider failed api_key=sk_synthetic_test_credential_0000000000000000000"
            )
        except RuntimeError:
            record = logging.LogRecord(
                name="src.test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=20,
                msg="调用失败 Authorization: Bearer bearer-secret-value",
                args=(),
                exc_info=sys.exc_info(),
            )
        record.detail = "password=plain-secret-value"
        record.api_key = "structured-secret-value"
        record.prompt = "document source text must never be persisted"
        record.source_text = "classified requirement body must never be persisted"
        CorrelationIdFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        job_stage_var.reset(stage_token)
        job_id_var.reset(job_token)
        correlation_id_var.reset(correlation_token)

    assert payload["correlation_id"] == "request-123"
    assert payload["job_id"] == "job-456"
    assert payload["stage"] == "semantic_plan"
    assert payload["level"] == "ERROR"
    assert "Authorization: ***" in payload["message"]
    assert "password=***" in payload["detail"]
    assert "api_key=***" in payload["exception"]
    serialized = json.dumps(payload, ensure_ascii=False)
    for secret in (
        "bearer-secret-value",
        "plain-secret-value",
        "structured-secret-value",
        "QN50XdR19GeQuH5pOAvxJkqh5SegO1OD6MepVg9qczTij",
        "document source text must never be persisted",
        "classified requirement body must never be persisted",
    ):
        assert secret not in serialized
    assert "api_key" not in payload
    assert "prompt" not in payload
    assert "source_text" not in payload


def test_formatter_omits_empty_background_context():
    record = logging.LogRecord(
        name="src.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=70,
        msg="request_completed",
        args=(),
        exc_info=None,
    )
    CorrelationIdFilter().filter(record)

    payload = json.loads(JsonFormatter().format(record))

    assert payload["correlation_id"] == "-"
    assert "job_id" not in payload
    assert "stage" not in payload
