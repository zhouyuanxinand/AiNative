"""Bound an interactive caller without changing the taskbook client's defaults."""
from dataclasses import replace
from unittest.mock import MagicMock

import httpx
import pytest

from jonhon_taskbook import llm_client as llm


CONFIG = llm.LLMConfig(provider='smartvision', api_key='fixture',
    endpoint='https://fixture.invalid/chat/completions', model='azure/gpt-5.4',
    timeout_seconds=90, max_tokens=32768)


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(llm.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(llm.time, 'perf_counter', lambda: now[0])
    monkeypatch.setattr(llm.time, 'sleep', lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(llm, '_active_config', lambda: CONFIG)
    monkeypatch.delenv('JTB_LLM_RETRIES', raising=False)
    monkeypatch.delenv('JTB_LLM_RETRY_MAX_DELAY_SECONDS', raising=False)
    return now


def response(content='{"ok":true}', finish='stop'):
    return httpx.Response(200, request=httpx.Request('POST', CONFIG.endpoint), json={
        'choices': [{'finish_reason': finish, 'message': {'content': content}}]})


def test_attempts_share_deadline_and_use_only_remaining_time(monkeypatch, clock):
    timeouts = []
    def timeout(*args, **kwargs):
        timeouts.append(kwargs['timeout'])
        clock[0] += kwargs['timeout']
        raise httpx.ReadTimeout('fixture')
    monkeypatch.setattr(llm.httpx, 'post', timeout)
    with pytest.raises(TimeoutError):
        llm.chat_json('system', '{}', deadline=1240, timeout_seconds=120, retries=2)
    assert timeouts == [120, 119]
    assert clock[0] == 1240
    assert CONFIG.timeout_seconds == 90


def test_expired_deadline_never_calls_model(monkeypatch, clock):
    monkeypatch.setattr(llm.httpx, 'post', lambda *a, **k: pytest.fail('expired model call'))
    with pytest.raises(TimeoutError):
        llm.chat_json('system', '{}', deadline=999)


def test_response_arriving_after_deadline_is_rejected(monkeypatch, clock):
    def late(*args, **kwargs):
        clock[0] = 1241
        return response()
    monkeypatch.setattr(llm.httpx, 'post', late)
    with pytest.raises(TimeoutError):
        llm.chat_json('system', '{}', deadline=1240, timeout_seconds=120, retries=2)


def test_truncated_output_recovery_keeps_original_deadline(monkeypatch, clock):
    calls = []
    def respond(*args, **kwargs):
        calls.append((kwargs['timeout'], kwargs['json']['max_tokens']))
        if len(calls) == 1:
            clock[0] += 100
            return response('', 'length')
        clock[0] += 10
        return response()
    monkeypatch.setattr(llm.httpx, 'post', respond)
    assert llm.chat_json('system', '{}', max_tokens=4096, deadline=1120,
                         timeout_seconds=120, retries=2) == {'ok': True}
    assert calls == [(120, 4096), (20, 32768)]


def test_separate_calls_share_a_callers_deadline(monkeypatch, clock):
    timeouts = []
    def respond(*args, **kwargs):
        timeouts.append(kwargs['timeout'])
        clock[0] += 100 if len(timeouts) == 1 else 20
        return response()
    monkeypatch.setattr(llm.httpx, 'post', respond)
    for _ in range(2):
        assert llm.chat_json('system', '{}', deadline=1130, timeout_seconds=120, retries=2) == {'ok': True}
    assert timeouts == [120, 30]
    clock[0] = 1130
    with pytest.raises(TimeoutError):
        llm.chat_json('system', '{}', deadline=1130, timeout_seconds=120, retries=2)
    assert len(timeouts) == 2


def test_backoff_cannot_exceed_remaining_deadline(monkeypatch, clock):
    calls = []
    def timeout(*args, **kwargs):
        calls.append(kwargs['timeout'])
        clock[0] += 0.4
        raise httpx.ReadTimeout('fixture')
    monkeypatch.setattr(llm.httpx, 'post', timeout)
    with pytest.raises(TimeoutError):
        llm.chat_json('system', '{}', deadline=1000.5, timeout_seconds=120, retries=2)
    assert calls == [0.5]
    assert clock[0] == 1000.5


def test_explicit_retry_count_overrides_environment(monkeypatch, clock):
    monkeypatch.setenv('JTB_LLM_RETRIES', '7')
    calls = []
    def timeout(*args, **kwargs):
        calls.append(kwargs['timeout'])
        clock[0] += kwargs['timeout']
        raise httpx.ReadTimeout('fixture')
    monkeypatch.setattr(llm.httpx, 'post', timeout)
    with pytest.raises(RuntimeError):
        llm.chat_json('system', '{}', deadline=1240, timeout_seconds=120, retries=1)
    assert calls == [120]


def test_unbounded_default_keeps_existing_retry_policy(monkeypatch, clock):
    calls = []
    def timeout(*args, **kwargs):
        calls.append(kwargs['timeout'])
        clock[0] += kwargs['timeout']
        raise httpx.ReadTimeout('fixture')
    monkeypatch.setattr(llm.httpx, 'post', timeout)
    with pytest.raises(RuntimeError):
        llm.chat_json('system', '{}')
    assert calls == [90] * 7
    assert clock[0] == 1681


def test_budgeted_azure_call_disables_sdk_retries_and_sets_attempt_timeout(monkeypatch, clock):
    config = replace(CONFIG, provider='azure')
    monkeypatch.setattr(llm, '_active_config', lambda: config)
    client = MagicMock()
    payload = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]}
    client.with_options.return_value.chat.completions.create.return_value.model_dump.return_value = payload
    client.chat.completions.create.return_value.model_dump.return_value = payload
    monkeypatch.setattr(llm, '_get_azure_client', lambda cfg: client)
    assert llm.chat_json('system', '{}', deadline=1010, timeout_seconds=120, retries=2) == {'ok': True}
    client.with_options.assert_called_once_with(timeout=10, max_retries=0)
    client.chat.completions.create.assert_not_called()
    client.reset_mock()
    assert llm.chat_json('system', '{}') == {'ok': True}
    client.with_options.assert_not_called()
    client.chat.completions.create.assert_called_once()
