"""Isolated, non-persisting model checks for the credentials settings dialog."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from time import perf_counter

import httpx

from . import llm_client
from .service_credentials import validate_credentials

CATALOG_TIMEOUT_SECONDS = 10.0
COMPLETION_TIMEOUT_SECONDS = 45.0
COMPLETION_MAX_TOKENS = 1024


class ProbeFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code


def _model_identifier(value: object, *, optional: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise ValueError("模型标识格式不正确。")
    value = value.strip()
    if not value and not optional:
        raise ValueError("请选择需要测试的模型。")
    return value


def validate_probe_payload(payload: object, *, catalog: bool) -> dict:
    required = {"credentials"} if catalog else {"credentials", "model"}
    allowed = required if catalog else required | {"model_id"}
    if not isinstance(payload, dict) or not required <= payload.keys() or payload.keys() - allowed:
        raise ValueError("测试参数格式不正确。")
    credentials = validate_credentials(payload["credentials"])
    llm_client.validate_service_credentials(credentials)
    result = {"credentials": credentials}
    if not catalog:
        result.update(model=_model_identifier(payload["model"]),
                      model_id=_model_identifier(payload.get("model_id", ""), optional=True))
    return result


def _config(credentials: dict, model: str = "connectivity-check", model_id: str = ""):
    values = credentials["model"]
    if values is None:
        try:
            values = validate_credentials(llm_client.get_service_credential_defaults())["model"]
        except (ValueError, TypeError):
            raise ProbeFailure("not_configured", "部署默认模型凭证不完整，请填写凭证后测试。") from None
    try:
        return replace(llm_client._service_override_config(values), model=model, model_id=model_id,
                       timeout_seconds=COMPLETION_TIMEOUT_SECONDS, max_tokens=COMPLETION_MAX_TOKENS)
    except (ValueError, TypeError):
        raise ProbeFailure("not_configured", "模型凭证配置无效，请检查设置后重试。") from None


def _check_http(response: httpx.Response) -> None:
    code = response.status_code
    if 200 <= code < 300:
        return
    if code in {401, 403}:
        raise ProbeFailure("authentication_failed", "鉴权失败，请检查 App ID、API Key、租户 ID 及访问权限。",
                           status_code=code)
    if 300 <= code < 400:
        raise ProbeFailure("redirect", "服务地址返回重定向，请填写最终服务地址后重试。",
                           status_code=code)
    if code == 404:
        raise ProbeFailure("not_found", "接口或模型不存在，请检查服务地址及模型名称。",
                           status_code=code)
    if code == 429:
        raise ProbeFailure("rate_limited", "服务请求受限，请稍后重试或检查调用额度。",
                           status_code=code)
    if code >= 500:
        raise ProbeFailure("service_unavailable", "模型服务暂不可用，请稍后重试。",
                           status_code=code)
    raise ProbeFailure("request_rejected", "服务拒绝了测试请求，请检查模型名称、接口配置及调用权限。",
                       status_code=code)


async def _request(config, *, catalog: bool) -> httpx.Response:
    timeout = CATALOG_TIMEOUT_SECONDS if catalog else COMPLETION_TIMEOUT_SECONDS
    headers = llm_client._compatible_headers(config)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        if catalog:
            response = await client.get(llm_client._catalog_url(config, use_override=False), headers=headers)
        else:
            body = {
                "model": config.model,
                "messages": [{"role": "user", "content": "这是连通性测试，请仅回复 OK。"}],
                "max_tokens": COMPLETION_MAX_TOKENS,
                "stream": False,
            }
            extra_parameters = llm_client.request_extra_parameters(config)
            if extra_parameters:
                body["extra_parameters"] = extra_parameters
            response = await client.post(config.endpoint, headers=headers, json=body)
        _check_http(response)
        return response


def _catalog(payload: object) -> list[dict]:
    if isinstance(payload, dict) and (payload.get("success") is False or payload.get("error")):
        raise ProbeFailure("request_rejected", "服务未能返回模型目录，请检查凭证及调用权限。")
    items = payload if isinstance(payload, list) else payload.get("data") if isinstance(payload, dict) else None
    if isinstance(items, dict):
        items = items.get("list")
    if not isinstance(items, list):
        raise ProbeFailure("invalid_response", "模型目录返回格式不正确，请检查服务地址和接口兼容性。")
    models = llm_client._parse_catalog_response(payload)
    if not models:
        raise ProbeFailure("empty_models", "服务未返回可用模型，请检查当前凭证的模型授权。")
    return models


def _completion(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ProbeFailure("invalid_response", "模型响应格式不正确，请检查接口兼容性。")
    try:
        content = llm_client._message_content(payload)
        choice = payload["choices"][0]
    except (RuntimeError, KeyError, TypeError):
        raise ProbeFailure("invalid_response", "模型响应格式不正确，请检查接口兼容性。") from None
    finish = choice.get("finish_reason")
    message = choice.get("message")
    if finish == "length":
        raise ProbeFailure("truncated_response", "模型输出达到测试额度，未取得完整响应，请选择其他模型或稍后重试。")
    if finish == "content_filter" or (isinstance(message, dict) and message.get("refusal")):
        raise ProbeFailure("response_rejected", "模型拒绝了测试请求，请检查模型策略或选择其他模型。")
    raw_content = message.get("content") if isinstance(message, dict) else None
    if raw_content is not None and not isinstance(raw_content, (str, list)):
        raise ProbeFailure("invalid_response", "模型响应格式不正确，请检查接口兼容性。")
    if isinstance(raw_content, list) and any(
        not isinstance(item, dict) or not isinstance(item.get("text", item.get("content", "")), str)
        for item in raw_content
    ):
        raise ProbeFailure("invalid_response", "模型响应格式不正确，请检查接口兼容性。")
    if not content.strip():
        raise ProbeFailure("empty_response", "模型未返回有效文本，请检查模型服务或选择其他模型。")
    if finish not in {"stop", "eos", "end_turn"}:
        raise ProbeFailure("incomplete_response", "模型未返回完整结束标记，请检查接口兼容性。")


async def run_probe(payload: dict, *, catalog: bool = False) -> dict:
    """Measure one complete request; never read or mutate active/history credentials."""
    started = perf_counter()
    result = {"models": []} if catalog else {"model": payload["model"]}
    timeout = CATALOG_TIMEOUT_SECONDS if catalog else COMPLETION_TIMEOUT_SECONDS
    provider = ""
    model = payload.get("model", "")
    status_code: int | None = None
    error_type = ""
    completion = llm_client._completion_metadata({})
    try:
        config = _config(payload["credentials"], payload.get("model", "connectivity-check"), payload.get("model_id", ""))
        provider = llm_client._provider_kind(config)
        model = config.model
        response = await asyncio.wait_for(_request(config, catalog=catalog), timeout=timeout)
        status_code = response.status_code
        body = response.json()
        if catalog:
            result["models"] = _catalog(body)
        else:
            completion = llm_client._completion_metadata(
                body,
                status_code=status_code,
            )
            _completion(body)
        result.update(success=True, message="模型目录已获取。" if catalog else "连接成功，模型已返回完整响应。")
    except ProbeFailure as exc:
        status_code = exc.status_code if exc.status_code is not None else status_code
        error_type = exc.code
        result.update(success=False, error_code=exc.code, message=exc.message)
    except (asyncio.TimeoutError, httpx.TimeoutException):
        error_type = "timeout"
        result.update(success=False, error_code="timeout", message=f"请求超时（{timeout:g} 秒），请检查网络或稍后重试。")
    except httpx.NetworkError:
        error_type = "connection_failed"
        result.update(success=False, error_code="connection_failed", message="无法连接模型服务，请检查地址、网络和证书配置。")
    except (httpx.HTTPError, ValueError, TypeError):
        error_type = "invalid_response"
        result.update(success=False, error_code="invalid_response", message="服务响应无效，请检查服务地址和接口兼容性。")
    duration_ms = round((perf_counter() - started) * 1000, 1)
    result.update(response_time_ms=duration_ms,
                  checked_at=datetime.now(timezone.utc).isoformat())
    llm_client._log_llm_event(
        "completed" if result["success"] else "failed",
        provider=provider,
        model=model,
        operation="model_catalog_probe" if catalog else "model_connectivity_probe",
        attempt=1,
        max_attempts=1,
        duration_ms=duration_ms,
        status_code=status_code,
        error_type=error_type,
        finish_reason=completion.get("finish_reason", ""),
        completion_tokens=completion.get("completion_tokens", 0),
        reasoning_tokens=completion.get("reasoning_tokens", 0),
        content_chars=completion.get("content_chars", 0),
    )
    return result
