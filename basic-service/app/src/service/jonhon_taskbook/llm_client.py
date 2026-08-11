# -*- coding: utf-8 -*-
"""受控 LLM 调用层。

支持神州问学、DashScope、Azure OpenAI 和 OpenAI JSON 协议兼容接口。大模型仅由上层用于
语义分类、路由和模板标题树操作，不在此模块生成业务正文。

网页提交的凭据只保存在当前 Python 进程内存中；本模块不会把凭据写入
源码、YAML、日志或输出文档。
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
import json
import os
import re
import threading
import time
from typing import Any, Iterator
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

import httpx


# Patch ThreadPoolExecutor so that contextvars (specifically the model
# selection set by ``model_scope``) are propagated into worker threads.
# Business code spawns ThreadPoolExecutors (e.g. semantic_orchestrator);
# without this patch the child threads lose the selected provider and fall
# back to the default configuration, causing them to hit the wrong endpoint.
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

_original_submit = ThreadPoolExecutor.submit


def _submit_with_context(self, fn, /, *args, **kwargs):
    ctx = copy_context()
    return _original_submit(self, ctx.run, fn, *args, **kwargs)


ThreadPoolExecutor.submit = _submit_with_context


_SHARED_ENV_FILE_KEY = "JTB_SHARED_ENV_FILE"

_LOCAL_ENV_KEYS = {
    _SHARED_ENV_FILE_KEY,
    "JTB_LLM_PROVIDER",
    "JTB_LLM_API_URL",
    "JTB_LLM_API_KEY",
    "JTB_LLM_APP_ID",
    "JTB_LLM_TENANT_ID",
    "JTB_LLM_APP_ID_HEADER",
    "JTB_LLM_API_KEY_HEADER",
    "JTB_LLM_TENANT_ID_HEADER",
    "JTB_LLM_MODELS_API_URL",
    "JTB_LLM_MODEL",
    "JTB_LLM_MODEL_ID",
    "JTB_LLM_TIMEOUT_SECONDS",
    "JTB_LLM_MAX_TOKENS",
    "JTB_EMBEDDING_API_URL",
    "JTB_EMBEDDING_MODELS_API_URL",
    "JTB_EMBEDDING_MODEL",
    "JTB_EMBEDDING_MODEL_ID",
    "JTB_RERANK_API_URL",
    "JTB_RERANK_MODEL",
    "JTB_RERANK_MODEL_ID",
    "JTB_RETRIEVAL_TIMEOUT_SECONDS",
    "JTB_SEMANTIC_RETRIEVAL",
    "JTB_SEMANTIC_RERANK",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_API_KEY",
    "AZURE_API_BASE",
    "AZURE_DEPLOYMENT",
    "AZURE_API_VERSION",
    # 与自动化输入审查服务保持一致的模型配置变量。
    "MODEL_PROVIDER",
    "MODEL_BASE_URL",
    "MODEL_APP_ID",
    "MODEL_API_KEY",
    "MODEL_TENANT_ID",
    "MODEL_APP_ID_HEADER",
    "MODEL_API_KEY_HEADER",
    "MODEL_TENANT_ID_HEADER",
    "MODEL_GENERATE_PATH",
    "MODEL_NAME",
    "MODEL_ID",
    "MODEL_MAX_TOKENS",
    "MODEL_TEMPERATURE",
    "AI_API_URL",
    "AI_API_KEY",
    "AI_MODEL",
    "AI_MAX_TOKENS",
    "AI_TEMPERATURE",
    "AI_TIMEOUT",
}

# The customer deployment uses this MaaS-compatible endpoint by default.
# These values are routing defaults, not credentials.  The API key remains
# an environment/deployment secret so the same packaged code can be shipped
# to multiple customers without embedding a secret in source.
_DEFAULT_MAAS_ENDPOINT = (
    "https://sv.dcsmartvision.com/open/opi-maas/v1/chat/completions"
)
_DEFAULT_MAAS_APP_ID = "1000000122"
_DEFAULT_MAAS_MODEL = "dashscope/qwen3.5-plus"
_DEFAULT_MAAS_MODEL_ID = "5506"
_DEFAULT_DASHSCOPE_ENDPOINT = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
)
_DEFAULT_DASHSCOPE_MODEL = "qwen-plus"
_DEFAULT_MODELS_PATH = "opi-maas/v1/chat/models"


def _read_env_file(env_path: Path) -> dict[str, str]:
    try:
        raw = env_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}

    values: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        if key.startswith("export "):
            key = key[7:].strip()
        if key not in _LOCAL_ENV_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _apply_env_values(values: dict[str, str]) -> None:
    """Apply an allow-listed dotenv mapping without replacing process values."""
    for key, value in values.items():
        if key not in os.environ:
            os.environ[key] = value


def _load_local_env_once() -> None:
    """Load private local/shared dotenv files without exposing credentials.

    Loading precedence is process environment > project ``.env`` > shared
    dotenv. ``JTB_SHARED_ENV_FILE`` allows this service to consume the same
    deployment credentials as the automation input audit service while keeping
    the secret values in their original ignored file.
    """
    env_path = Path(__file__).resolve().parents[1] / ".env"
    local_values = _read_env_file(env_path)
    _apply_env_values(local_values)

    shared_value = os.getenv(_SHARED_ENV_FILE_KEY, "").strip()
    if not shared_value:
        return
    shared_path = Path(os.path.expandvars(shared_value)).expanduser()
    if not shared_path.is_absolute():
        shared_path = env_path.parent / shared_path
    try:
        if shared_path.resolve() == env_path.resolve():
            return
    except OSError:
        return
    _apply_env_values(_read_env_file(shared_path))


_load_local_env_once()

_DEFAULT_DEPLOYMENT = os.getenv(
    "AZURE_OPENAI_DEPLOYMENT",
    os.getenv("AZURE_DEPLOYMENT", "gpt-4o"),
)
_DEFAULT_API_VERSION = os.getenv(
    "AZURE_OPENAI_API_VERSION",
    os.getenv("AZURE_API_VERSION", "2024-12-01-preview"),
)
_SUPPORTED_PROVIDERS = {
    "azure",
    "openai_compatible",
    "smartvision",
    "dashscope",
}
_LOCK = threading.RLock()
_runtime_config: "LLMConfig | None" = None
_azure_client = None
_azure_client_signature: tuple[str, str, str] | None = None

# 可重试的 HTTP 状态码与参考服务（auto_input_audit_service）保持一致：
# 仅服务端瞬时故障与限流重试，鉴权/参数等 4xx 错误立即失败，避免无意义等待。
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class _LLMHTTPError(RuntimeError):
    """携带 HTTP 状态码的调用异常，供重试层区分可重试与不可重试错误。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class LLMConfig:
    """单个 LLM 连接配置。api_key 只允许驻留在内存。"""

    provider: str
    api_key: str
    endpoint: str
    model: str
    app_id: str = ""
    model_id: str = ""
    tenant_id: str = ""
    app_id_header: str = "App-Id"
    api_key_header: str = "Api-Key"
    tenant_id_header: str = "Tenant-Id"
    api_version: str = _DEFAULT_API_VERSION
    timeout_seconds: float = 90.0
    max_tokens: int = 8192
    source: str = "runtime"


@dataclass(frozen=True)
class ModelSelection:
    """一次请求/后台任务所使用的模型，不包含任何凭据。"""

    provider: str
    model: str
    model_id: str = ""


_model_selection: ContextVar[ModelSelection | None] = ContextVar(
    "jtb_llm_model_selection",
    default=None,
)


def _clean_endpoint(value: str, provider: str) -> str:
    endpoint = (value or "").strip()
    if not endpoint:
        raise ValueError("LLM 接口地址不能为空")
    parts = urlsplit(endpoint)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("LLM 接口地址必须是有效的 http/https URL")
    if parts.username or parts.password:
        raise ValueError("LLM 接口地址不能包含用户名或密码")
    if parts.query or parts.fragment:
        raise ValueError("LLM 接口地址不能包含查询参数或片段")
    path = parts.path.rstrip("/")
    if provider in {"openai_compatible", "smartvision", "dashscope"} and not path.endswith("/chat/completions"):
        raise ValueError("兼容接口地址必须指向 /chat/completions")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def make_config(
    *,
    provider: str,
    api_key: str,
    endpoint: str,
    model: str,
    app_id: str = "",
    model_id: str = "",
    tenant_id: str = "",
    app_id_header: str = "App-Id",
    api_key_header: str = "Api-Key",
    tenant_id_header: str = "Tenant-Id",
    api_version: str = _DEFAULT_API_VERSION,
    timeout_seconds: float = 90.0,
    max_tokens: int = 8192,
    source: str = "runtime",
) -> LLMConfig:
    provider = (provider or "").strip().lower()
    if provider not in _SUPPORTED_PROVIDERS:
        raise ValueError(f"不支持的 LLM provider: {provider or '(空)'}")
    if not (api_key or "").strip():
        raise ValueError("LLM API Key 不能为空")
    if not (model or "").strip():
        raise ValueError("LLM 模型/部署名不能为空")
    timeout = float(timeout_seconds)
    tokens = int(max_tokens)
    if not 5 <= timeout <= 600:
        raise ValueError("LLM 超时时间必须在 5 到 600 秒之间")
    if not 32 <= tokens <= 65536:
        raise ValueError("max_tokens 必须是 32 到 65536 之间的整数")
    return LLMConfig(
        provider=provider,
        api_key=(api_key or "").strip(),
        endpoint=_clean_endpoint(endpoint, provider),
        model=(model or "").strip(),
        app_id=(app_id or "").strip(),
        model_id=(model_id or "").strip(),
        tenant_id=(tenant_id or "").strip(),
        app_id_header=(app_id_header or "App-Id").strip(),
        api_key_header=(api_key_header or "Api-Key").strip(),
        tenant_id_header=(tenant_id_header or "Tenant-Id").strip(),
        api_version=(api_version or _DEFAULT_API_VERSION).strip(),
        timeout_seconds=timeout,
        max_tokens=tokens,
        source=source,
    )


def _completion_url(base_url: str, generate_path: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/{(generate_path or '').strip().lstrip('/')}"


def _smartvision_config_from_environment() -> LLMConfig | None:
    """读取参考服务使用的 MODEL_* 神州问学配置。"""
    api_key = os.getenv("MODEL_API_KEY", "").strip()
    base_url = os.getenv("MODEL_BASE_URL", "").strip()
    app_id = os.getenv("MODEL_APP_ID", "").strip()
    if not (api_key and base_url and app_id):
        return None
    return make_config(
        provider="smartvision",
        api_key=api_key,
        endpoint=_completion_url(
            base_url,
            os.getenv("MODEL_GENERATE_PATH", "opi-maas/v1/chat/completions"),
        ),
        app_id=app_id,
        tenant_id=os.getenv("MODEL_TENANT_ID", ""),
        app_id_header=os.getenv("MODEL_APP_ID_HEADER", "App-Id"),
        api_key_header=os.getenv("MODEL_API_KEY_HEADER", "Api-Key"),
        tenant_id_header=os.getenv("MODEL_TENANT_ID_HEADER", "Tenant-Id"),
        model=os.getenv("MODEL_NAME", _DEFAULT_MAAS_MODEL),
        model_id=os.getenv("MODEL_ID", ""),
        timeout_seconds=float(os.getenv("AI_TIMEOUT", "90")),
        max_tokens=int(os.getenv("MODEL_MAX_TOKENS", "8192")),
        source="environment",
    )


def _jtb_config_from_environment() -> LLMConfig | None:
    api_key = os.getenv("JTB_LLM_API_KEY", "").strip()
    if not api_key:
        return None
    requested_provider = os.getenv("JTB_LLM_PROVIDER", "").strip().lower()
    app_id = os.getenv("JTB_LLM_APP_ID", _DEFAULT_MAAS_APP_ID).strip()
    provider = requested_provider or ("smartvision" if app_id else "openai_compatible")
    if provider not in {"smartvision", "dashscope", "openai_compatible"}:
        return None
    default_endpoint = _DEFAULT_DASHSCOPE_ENDPOINT if provider == "dashscope" else _DEFAULT_MAAS_ENDPOINT
    default_model = _DEFAULT_DASHSCOPE_MODEL if provider == "dashscope" else _DEFAULT_MAAS_MODEL
    default_model_id = "" if provider == "dashscope" else _DEFAULT_MAAS_MODEL_ID
    return make_config(
        provider=provider,
        api_key=api_key,
        endpoint=os.getenv("JTB_LLM_API_URL", default_endpoint),
        app_id=app_id if provider in {"smartvision", "openai_compatible"} else "",
        tenant_id=os.getenv("JTB_LLM_TENANT_ID", ""),
        app_id_header=os.getenv("JTB_LLM_APP_ID_HEADER", "App-Id"),
        api_key_header=os.getenv("JTB_LLM_API_KEY_HEADER", "Api-Key"),
        tenant_id_header=os.getenv("JTB_LLM_TENANT_ID_HEADER", "Tenant-Id"),
        model=os.getenv("JTB_LLM_MODEL", default_model),
        model_id=os.getenv("JTB_LLM_MODEL_ID", default_model_id),
        timeout_seconds=float(os.getenv("JTB_LLM_TIMEOUT_SECONDS", "90")),
        max_tokens=int(os.getenv("JTB_LLM_MAX_TOKENS", "8192")),
        source="environment",
    )


def _azure_config_from_environment() -> LLMConfig | None:
    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_API_BASE")
    if not (api_key and endpoint):
        return None
    return make_config(
        provider="azure",
        api_key=api_key,
        endpoint=endpoint,
        model=os.getenv(
            "AZURE_OPENAI_DEPLOYMENT",
            os.getenv("AZURE_DEPLOYMENT", _DEFAULT_DEPLOYMENT),
        ),
        api_version=os.getenv(
            "AZURE_OPENAI_API_VERSION",
            os.getenv("AZURE_API_VERSION", _DEFAULT_API_VERSION),
        ),
        timeout_seconds=float(os.getenv("JTB_LLM_TIMEOUT_SECONDS", "90")),
        max_tokens=int(os.getenv("JTB_LLM_MAX_TOKENS", "8192")),
        source="environment",
    )


def _dashscope_config_from_environment() -> LLMConfig | None:
    api_key = os.getenv("AI_API_KEY", "").strip()
    if not api_key:
        return None
    return make_config(
        provider="dashscope",
        api_key=api_key,
        endpoint=os.getenv("AI_API_URL", _DEFAULT_DASHSCOPE_ENDPOINT),
        model=os.getenv("AI_MODEL", _DEFAULT_DASHSCOPE_MODEL),
        timeout_seconds=float(os.getenv("AI_TIMEOUT", "90")),
        max_tokens=int(os.getenv("AI_MAX_TOKENS", "30000")),
        source="environment",
    )


def _openai_config_from_environment() -> LLMConfig | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    endpoint = os.getenv("OPENAI_BASE_URL", "").strip()
    if not (api_key and endpoint):
        return None
    if not endpoint.rstrip("/").endswith("/chat/completions"):
        endpoint = endpoint.rstrip("/") + "/chat/completions"
    return make_config(
        provider="openai_compatible",
        api_key=api_key,
        endpoint=endpoint,
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        timeout_seconds=float(os.getenv("JTB_LLM_TIMEOUT_SECONDS", "90")),
        max_tokens=int(os.getenv("JTB_LLM_MAX_TOKENS", "8192")),
        source="environment",
    )


def _environment_configs() -> list[LLMConfig]:
    configs: list[LLMConfig] = []
    for loader in (
        _smartvision_config_from_environment,
        _jtb_config_from_environment,
        _azure_config_from_environment,
        _dashscope_config_from_environment,
        _openai_config_from_environment,
    ):
        config = loader()
        if config is not None:
            configs.append(config)
    return configs


def _config_from_environment() -> LLMConfig | None:
    configs = _environment_configs()
    return configs[0] if configs else None


def _base_config() -> LLMConfig | None:
    with _LOCK:
        config = _runtime_config
    if config is None:
        config = _config_from_environment()
    return config


def _provider_kind(config: LLMConfig) -> str:
    if config.provider == "openai_compatible" and config.app_id:
        return "smartvision"
    return config.provider


def _resolve_model_config(selection: ModelSelection | None) -> LLMConfig:
    base = _base_config()
    if selection is None:
        if base is None:
            raise RuntimeError(
                "LLM 未配置：请设置 MODEL_* / AI_* / JTB_LLM_* / Azure 环境变量。"
                "为避免按章节号、章节顺序或旧配置猜测位置，受控语义流程已停止。"
            )
        return base

    provider = (selection.provider or "").strip().lower()
    model = (selection.model or "").strip()
    model_id = (selection.model_id or "").strip()
    if provider not in _SUPPORTED_PROVIDERS:
        raise RuntimeError(f"不支持的模型供应方：{provider or '(空)'}")
    if not model or len(model) > 200 or any(ch in model for ch in "\r\n\t"):
        raise RuntimeError("请选择有效的模型")
    if len(model_id) > 128 or any(ch in model_id for ch in "\r\n\t"):
        raise RuntimeError("模型 ID 无效")

    candidates: list[LLMConfig] = []
    if base is not None:
        candidates.append(base)
    candidates.extend(_environment_configs())
    selected_config = next(
        (item for item in candidates if _provider_kind(item) == provider),
        None,
    )
    if selected_config is None:
        provider_label = {
            "smartvision": "神州问学",
            "dashscope": "阿里云 DashScope",
            "azure": "Azure OpenAI",
            "openai_compatible": "OpenAI 兼容接口",
        }.get(provider, provider)
        raise RuntimeError(
            f"{provider_label} 尚未配置调用凭据，请检查对应环境变量"
        )
    return replace(selected_config, model=model, model_id=model_id)


def _active_config() -> LLMConfig:
    return _resolve_model_config(_model_selection.get())


@contextmanager
def model_scope(
    provider: str = "",
    model: str = "",
    model_id: str = "",
    *,
    resolve: bool = True,
) -> Iterator[LLMConfig | None]:
    """将模型选择限定在当前请求/任务上下文，避免并发任务互相覆盖。"""
    selection = None
    if provider or model or model_id:
        selection = ModelSelection(provider=provider, model=model, model_id=model_id)
    token = _model_selection.set(selection)
    try:
        yield _active_config() if resolve else None
    finally:
        _model_selection.reset(token)


def _safe_status(config: LLMConfig | None) -> dict[str, Any]:
    if config is None:
        return {
            "configured": False,
            "provider": "",
            "endpoint": "",
            "model": "",
            "source": "",
            "app_id_configured": False,
            "tenant_id_configured": False,
            "model_id_configured": False,
        }
    return {
        "configured": True,
        "provider": _provider_kind(config),
        "endpoint": config.endpoint,
        "model": config.model,
        "source": config.source,
        "app_id_configured": bool(config.app_id),
        "tenant_id_configured": bool(config.tenant_id),
        "model_id_configured": bool(config.model_id),
    }


def get_status() -> dict[str, Any]:
    """返回可展示状态；永远不返回 API Key 或完整认证头。"""
    with _LOCK:
        config = _runtime_config
    if config is None:
        try:
            config = _config_from_environment()
        except (TypeError, ValueError):
            config = None
    return _safe_status(config)


def get_model_status(
    provider: str = "",
    model: str = "",
    model_id: str = "",
) -> dict[str, Any]:
    """检查某个下拉选择是否有可用凭据，不发起模型请求。"""
    try:
        selection = None
        if provider or model or model_id:
            selection = ModelSelection(provider=provider, model=model, model_id=model_id)
        return _safe_status(_resolve_model_config(selection))
    except (RuntimeError, TypeError, ValueError):
        return {
            **_safe_status(None),
            "provider": (provider or "").strip().lower(),
            "model": (model or "").strip(),
        }


def _catalog_url(config: LLMConfig) -> str:
    explicit = os.getenv("JTB_LLM_MODELS_API_URL", "").strip()
    if explicit:
        parts = urlsplit(explicit)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("模型目录地址必须是有效的 http/https URL")
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    parts = urlsplit(config.endpoint)
    path = parts.path.rstrip("/")
    suffix = "/chat/completions"
    if path.endswith(suffix):
        path = path[: -len(suffix)] + "/chat/models"
    else:
        path = path.rstrip("/") + "/" + _DEFAULT_MODELS_PATH
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _parse_catalog_response(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        if payload.get("success") is False:
            return []
        items = payload.get("data")
        if isinstance(items, dict):
            items = items.get("list")
    else:
        return []
    if not isinstance(items, list):
        return []

    models: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("model") or raw.get("name") or raw.get("id") or "").strip()
        if not name:
            continue
        vendor = str(raw.get("vendor") or raw.get("provider_name") or "").strip()
        if not vendor and "/" in name:
            prefix = name.split("/", 1)[0].lower()
            vendor = {
                "openai": "OpenAI",
                "azure": "微软 Azure",
                "dashscope": "阿里云 DashScope",
            }.get(prefix, prefix)
        models.append(
            {
                "model": name,
                "vendor": vendor or "神州问学",
                "id": str(raw.get("id") or "").strip(),
                "provider": "smartvision",
                "configured": True,
            }
        )
    return models


def list_available_models() -> list[dict[str, Any]]:
    """按参考服务协议返回模型目录，并保留配置模型作为可靠兜底。"""
    configured: list[LLMConfig] = []
    base = _base_config()
    if base is not None:
        configured.append(base)
    configured.extend(_environment_configs())

    models: list[dict[str, Any]] = []
    smartvision = next(
        (item for item in configured if _provider_kind(item) == "smartvision"),
        None,
    )
    if smartvision is not None:
        try:
            response = httpx.get(
                _catalog_url(smartvision),
                headers={key: value for key, value in _compatible_headers(smartvision).items() if key != "Content-Type"},
                timeout=httpx.Timeout(3.0, connect=1.5),
                follow_redirects=False,
            )
            response.raise_for_status()
            models.extend(_parse_catalog_response(response.json()))
        except (httpx.HTTPError, ValueError, json.JSONDecodeError):
            # 目录服务不可达时仍返回配置中的默认模型，与参考服务保持降级行为。
            pass

    vendor_labels = {
        "smartvision": "神州问学",
        "dashscope": "阿里云 DashScope",
        "azure": "微软 Azure",
        "openai_compatible": "OpenAI 兼容接口",
    }
    for config in configured:
        provider = _provider_kind(config)
        models.append(
            {
                "model": config.model,
                "vendor": vendor_labels.get(provider, provider),
                "id": config.model_id,
                "provider": provider,
                "configured": True,
            }
        )

    configured_providers = {_provider_kind(item) for item in configured}
    if "smartvision" not in configured_providers:
        models.append(
            {
                "model": os.getenv("MODEL_NAME", _DEFAULT_MAAS_MODEL),
                "vendor": "神州问学",
                "id": os.getenv("MODEL_ID", _DEFAULT_MAAS_MODEL_ID),
                "provider": "smartvision",
                "configured": False,
            }
        )
    if "dashscope" not in configured_providers:
        models.append(
            {
                "model": os.getenv("AI_MODEL", _DEFAULT_DASHSCOPE_MODEL),
                "vendor": "阿里云 DashScope",
                "id": "",
                "provider": "dashscope",
                "configured": False,
            }
        )

    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in models:
        key = (str(item["provider"]), str(item["model"]), str(item["id"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    provider_order = {"smartvision": 0, "dashscope": 1, "azure": 2, "openai_compatible": 3}
    unique.sort(
        key=lambda item: (
            not bool(item.get("configured")),
            provider_order.get(str(item.get("provider")), 9),
            str(item.get("model")),
        )
    )
    return unique


def clear_runtime_config() -> dict[str, Any]:
    """清除网页注入的内存配置；环境变量配置不受影响。"""
    global _runtime_config, _azure_client, _azure_client_signature
    with _LOCK:
        _runtime_config = None
        _azure_client = None
        _azure_client_signature = None
    return get_status()


def configure_runtime(config: LLMConfig, *, verify: bool = True) -> dict[str, Any]:
    """验证后原子替换内存配置。验证失败时保留原有可用配置。"""
    global _runtime_config, _azure_client, _azure_client_signature
    if verify:
        probe_config(config)
    with _LOCK:
        _runtime_config = replace(config, source="runtime")
        _azure_client = None
        _azure_client_signature = None
    return get_status()


def _redact(value: object, config: LLMConfig) -> str:
    text = str(value)
    if config.api_key:
        text = text.replace(config.api_key, "[REDACTED]")
    if config.app_id:
        text = text.replace(config.app_id, "[REDACTED]")
    text = re.sub(r"\bsk_[A-Za-z0-9_-]{8,}\b", "[REDACTED]", text)
    return text[:800]


def _compatible_headers(config: LLMConfig) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connection": "keep-alive",
        "User-Agent": "JONHON-Taskbook/1.0",
    }
    if config.app_id:
        headers[config.app_id_header] = config.app_id
        headers[config.api_key_header] = config.api_key
        if config.tenant_id and config.tenant_id_header:
            headers[config.tenant_id_header] = config.tenant_id
    else:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def _message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("LLM 响应缺少 choices[0]")
    message = choices[0].get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text") or item.get("content") or "")
            for item in content
            if isinstance(item, dict)
        )
    return "" if content is None else str(content)


def _request_compatible(
    config: LLMConfig,
    system: str,
    user: str,
    *,
    temperature: float,
    max_tokens: int,
) -> str:
    body: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": max(0.0, min(float(temperature), 1.0)),
        "max_tokens": min(int(max_tokens), config.max_tokens),
    }
    if config.model_id:
        body["extra_parameters"] = {"model_id": config.model_id}
    try:
        response = httpx.post(
            config.endpoint,
            headers=_compatible_headers(config),
            json=body,
            timeout=config.timeout_seconds,
            follow_redirects=False,
        )
        if response.is_redirect:
            # 重定向是 endpoint 配置错误，立即失败，不重试。
            raise RuntimeError("LLM 接口返回重定向；请填写最终 /chat/completions 地址")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise _LLMHTTPError("LLM 响应不是 JSON 对象", status_code=200)
        return _message_content(payload)
    except httpx.HTTPStatusError as exc:
        detail = _redact(exc.response.text, config)
        raise _LLMHTTPError(
            f"LLM 接口返回 HTTP {exc.response.status_code}: {detail}",
            exc.response.status_code,
        ) from None
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        # 超时与连接异常属于可重试的瞬时网络故障，不附带状态码。
        raise _LLMHTTPError(f"LLM 接口网络异常: {_redact(exc, config)}") from None
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        # 协议错误、JSON 解析失败等属于不可重试的非瞬时异常。
        raise RuntimeError(f"LLM 接口调用失败: {_redact(exc, config)}") from None


def _get_azure_client(config: LLMConfig):
    global _azure_client, _azure_client_signature
    signature = (config.endpoint, config.api_version, config.model)
    with _LOCK:
        if _azure_client is None or _azure_client_signature != signature:
            from openai import AzureOpenAI

            _azure_client = AzureOpenAI(
                api_key=config.api_key,
                api_version=config.api_version,
                azure_endpoint=config.endpoint.rstrip("/"),
                timeout=config.timeout_seconds,
            )
            _azure_client_signature = signature
        return _azure_client


def _request_once(
    config: LLMConfig,
    system: str,
    user: str,
    *,
    deployment: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> str:
    if config.provider in {"openai_compatible", "smartvision", "dashscope"}:
        return _request_compatible(
            config,
            system,
            user,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    client = _get_azure_client(config)
    kwargs: dict[str, Any] = {
        "model": config.model or deployment,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": min(int(max_tokens), config.max_tokens),
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def _is_retryable(exc: Exception) -> bool:
    """判断异常是否值得重试，与参考服务的策略保持一致。

    可重试：HTTP 429/500/502/503/504、网络/超时异常（_LLMHTTPError 无状态码）、
    Azure SDK 的限流/服务端异常。不可重试：400/401/403/404 等客户端错误、
    重定向/协议/JSON 解析等 RuntimeError，以及 Azure 鉴权错误——这些重试无意义，
    应立即暴露给上层。
    """
    if isinstance(exc, _LLMHTTPError):
        status = exc.status_code
        # 无状态码 → 网络/超时异常（可重试）；有状态码 → 仅服务端瞬时故障可重试。
        return status is None or status in _RETRYABLE_STATUS_CODES
    # RuntimeError（重定向、协议错误、JSON 解析失败等）属于不可重试的确定性失败。
    if isinstance(exc, RuntimeError):
        return False
    # Azure SDK 异常：鉴权/参数类错误不重试，仅限流/服务端错误可重试。
    exc_name = type(exc).__name__
    if exc_name in {
        "AuthenticationError",
        "PermissionDeniedError",
        "BadRequestError",
        "NotFoundError",
        "UnprocessableEntityError",
    }:
        return False
    # RateLimitError/APIStatusError/APIError 等剩余 SDK 异常保守按可重试处理。
    return True


def _request_with_retry(
    config: LLMConfig,
    system: str,
    user: str,
    *,
    deployment: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    retries: int,
) -> str:
    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            return _request_once(
                config,
                system,
                user,
                deployment=deployment,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )
        except Exception as exc:  # SDK 与兼容 HTTP 客户端异常统一在边界判定
            last_error = exc
            # 不可重试的错误（鉴权失败、参数错误等）立即抛出，不做无意义等待。
            if not _is_retryable(exc):
                raise RuntimeError(_redact(exc, config)) from None
            if attempt + 1 < max(1, retries):
                # 退避 2**attempt（1/2/4...），与参考服务一致；可由环境变量封顶。
                max_delay = float(
                    os.getenv("JTB_LLM_RETRY_MAX_DELAY_SECONDS", "20")
                )
                time.sleep(min(max(0.0, max_delay), float(2**attempt)))
    if last_error is not None:
        raise RuntimeError(_redact(last_error, config)) from None
    raise RuntimeError("LLM 调用失败")


def probe_config(config: LLMConfig) -> None:
    """发送最小请求验证连接；不修改当前激活配置。"""
    raw = _request_with_retry(
        config,
        "你是连接检测器。只返回 OK。",
        "返回 OK",
        deployment=config.model,
        temperature=0.0,
        max_tokens=32,
        json_mode=False,
        retries=_configured_retries(default=3),
    )
    if not raw.strip():
        raise RuntimeError("LLM 连接成功但响应内容为空")


def chat(
    system: str,
    user: str,
    deployment: str = _DEFAULT_DEPLOYMENT,
    temperature: float = 0.5,
    max_tokens: int = 8192,
    retries: int = 3,
) -> str:
    """单次受控对话，返回文本。

    默认值与参考服务（auto_input_audit_service）对齐：temperature=0.5、
    max_tokens=8192，直接透传不做 clamp（clamp 仍由 _request_compatible 保留
    作为安全边界）。
    """
    config = _active_config()
    return _request_with_retry(
        config,
        system,
        user,
        deployment=deployment,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=False,
        retries=retries,
    )


def _parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        fenced = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.I | re.S)
        try:
            return json.loads(fenced)
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            for match in re.finditer(r"[\[{]", raw):
                try:
                    value, _ = decoder.raw_decode(raw[match.start():])
                    return value
                except json.JSONDecodeError:
                    continue
    raise RuntimeError("LLM 未返回可解析的 JSON")


def chat_json(
    system: str,
    user: str,
    deployment: str = _DEFAULT_DEPLOYMENT,
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> Any:
    """要求模型返回 JSON 并严格解析；不接受无法解析的自然语言兜底。"""
    config = _active_config()
    raw = _request_with_retry(
        config,
        system,
        user,
        deployment=deployment,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=True,
        retries=_configured_retries(default=7),
    )
    return _parse_json(raw)


def _configured_retries(*, default: int) -> int:
    """Read a bounded transport retry count without changing semantic behavior."""
    try:
        value = int(os.getenv("JTB_LLM_RETRIES", str(default)))
    except ValueError:
        value = default
    return max(1, min(value, 12))
