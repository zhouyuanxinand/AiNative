"""Exercise HTTP-200 responses through the production JSON client boundary."""

from dataclasses import replace
from unittest.mock import patch

import httpx
import pytest
from jonhon_taskbook import llm_client as llm

CONFIG = llm.LLMConfig(
    provider="smartvision",
    api_key="test-secret-key",
    endpoint="https://example.test/chat/completions",
    model="azure/gpt-5",
    app_id="test-app",
    tenant_id="test-tenant",
    model_id="4771",
    max_tokens=8192,
)


def completion(content, finish="stop", tokens=100, reasoning=0):
    return httpx.Response(
        200,
        request=httpx.Request("POST", CONFIG.endpoint),
        json={
            "choices": [{"finish_reason": finish, "message": {"content": content}}],
            "usage": {
                "completion_tokens": tokens,
                "completion_tokens_details": {"reasoning_tokens": reasoning},
            },
        },
    )


def test_reasoning_exhaustion_recovers_within_configured_budget(caplog):
    # Shape observed in the failing live response: all 4096 tokens spent on reasoning.
    responses = [completion("", "length", 4096, 4096), completion('{"headings": []}')]
    with (
        patch.object(llm, "_active_config", return_value=CONFIG),
        patch.object(llm.httpx, "post", side_effect=responses) as post,
    ):
        assert llm.chat_json("Return JSON", "private document text", max_tokens=4096) == {"headings": []}
    assert [call.kwargs["json"]["max_tokens"] for call in post.call_args_list] == [
        4096,
        8192,
    ]
    assert "4096" in caplog.text
    assert CONFIG.api_key not in caplog.text
    assert "private document text" not in caplog.text


@pytest.mark.parametrize("reasoning_tokens", [8192, 16384])
def test_default_gateway_budget_recovers_after_reasoning_exhaustion(reasoning_tokens):
    config = llm.make_config(
        provider=CONFIG.provider,
        api_key=CONFIG.api_key,
        endpoint=CONFIG.endpoint,
        model=CONFIG.model,
        app_id=CONFIG.app_id,
    )

    def response_for_budget(*args, **kwargs):
        budget = kwargs["json"]["max_tokens"]
        if budget <= reasoning_tokens:
            return completion("", "length", budget, budget)
        return completion('{"headings": []}', tokens=reasoning_tokens + 100, reasoning=reasoning_tokens)

    with (
        patch.object(llm, "_active_config", return_value=config),
        patch.object(llm.httpx, "post", side_effect=response_for_budget) as post,
    ):
        assert llm.chat_json("Return JSON", "private document text") == {"headings": []}
    expected_budgets = [16384] if reasoning_tokens == 8192 else [16384, 32768]
    assert [call.kwargs["json"]["max_tokens"] for call in post.call_args_list] == expected_budgets
    assert all(budget <= config.max_tokens for budget in expected_budgets)


def test_repeated_truncation_stops_at_cap_with_actionable_error():
    with (
        patch.object(llm, "_active_config", return_value=CONFIG),
        patch.object(
            llm.httpx,
            "post",
            side_effect=[
                completion("", "length", 4096, 4096),
                completion("", "length", 8192, 8192),
            ],
        ) as post,
        pytest.raises(RuntimeError, match="输出.*上限.*8192"),
    ):
        llm.chat_json("Return JSON", "{}", max_tokens=4096)
    assert post.call_count == 2


def test_truncated_json_never_accepts_nested_fragment():
    with (
        patch.object(
            llm, "_active_config", return_value=replace(CONFIG, max_tokens=4096)
        ),
        patch.object(
            llm.httpx,
            "post",
            return_value=completion(
                '{"classifications":[{"source_id":"a"},',
                "length",
                4096,
            ),
        ) as post,pytest.raises(RuntimeError, match="输出.*上限")
    ):
        llm.chat_json("Return JSON", "{}")
    assert post.call_count == 1


@pytest.mark.parametrize("finish", ["stop", None])
def test_incomplete_json_without_length_reason_is_still_rejected(finish):
    with (
        patch.object(llm, "_active_config", return_value=CONFIG),
        patch.object(
            llm.httpx,
            "post",
            return_value=completion(
                '{"classifications":[{"source_id":"a"},',
                finish,
            ),
        ) as post,
        pytest.raises(RuntimeError, match="未返回可解析的 JSON"),
    ):
        llm.chat_json("Return JSON", "{}")
    assert post.call_count == 1


@pytest.mark.parametrize(
    "content",
    [
        '{"ok": true}',
        '```json\n{"ok": true}\n```',
        'JSON result: {"ok": true} End.',
    ],
)
def test_complete_json_and_wrapped_json_remain_supported(content):
    with (
        patch.object(llm, "_active_config", return_value=CONFIG),
        patch.object(llm.httpx, "post", return_value=completion(content)),
    ):
        assert llm.chat_json("Return JSON", "{}") == {"ok": True}


def test_json_mode_is_sent_to_compatible_gateway():
    with (
        patch.object(llm, "_active_config", return_value=CONFIG),
        patch.object(llm.httpx, "post", return_value=completion('{"ok":true}')) as post,
    ):
        assert llm.chat_json("Return JSON", "{}") == {"ok": True}
    body = post.call_args.kwargs["json"]
    assert body["response_format"] == {"type": "json_object"}
    assert body["extra_parameters"]["model_id"] == "4771"


def test_text_requests_do_not_force_json_mode():
    with (
        patch.object(llm, "_active_config", return_value=CONFIG),
        patch.object(llm.httpx, "post", return_value=completion("OK")) as post,
    ):
        assert llm.chat("Reply OK", "OK") == "OK"
    assert "response_format" not in post.call_args.kwargs["json"]


def test_empty_stopped_response_is_distinct_from_invalid_json():
    with (
        patch.object(llm, "_active_config", return_value=CONFIG),
        patch.object(llm.httpx, "post", return_value=completion("")) as post,
        pytest.raises(RuntimeError, match="响应内容为空"),
    ):
        llm.chat_json("Return JSON", "{}")
    assert post.call_count == 1


def test_authentication_error_is_not_retried_for_more_tokens():
    error = httpx.Response(
        401,
        request=httpx.Request("POST", CONFIG.endpoint),
        json={"error": "unauthorized"},
    )
    with (
        patch.object(llm, "_active_config", return_value=CONFIG),
        patch.object(llm.httpx, "post", return_value=error) as post,
        pytest.raises(RuntimeError, match="HTTP 401"),
    ):
        llm.chat_json("Return JSON", "{}")
    assert post.call_count == 1
