"""Runtime profile loader for dev/test/prod deployments.

The profile files contain non-secret operational defaults only. Credentials
remain process environment variables and always take precedence over profile
defaults.
"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from typing import Any, Mapping

import yaml


# 包位于 app/src/service/jonhon_taskbook/，parents[3] 即运行时根 app/
# （parents[0]=jonhon_taskbook, [1]=service, [2]=src, [3]=app）。
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RESOURCE_ROOT = PROJECT_ROOT / "resources"
ALLOWED_PROFILES = {"dev", "test", "prod"}

_ENV_BINDINGS: dict[tuple[str, ...], str] = {
    ("server", "host"): "JTB_HOST",
    ("server", "port"): "JTB_PORT",
    ("uploads", "max_mb"): "JTB_MAX_UPLOAD_MB",
    ("jobs", "max_concurrent"): "JTB_MAX_CONCURRENT_JOBS",
    ("jobs", "ttl_hours"): "JTB_JOB_TTL_HOURS",
    ("jobs", "max_records"): "JTB_MAX_JOB_RECORDS",
    ("security", "allow_local_paths"): "JTB_ALLOW_LOCAL_PATHS",
    ("security", "allow_remote_llm_config"): "JTB_ALLOW_REMOTE_LLM_CONFIG",
    ("semantic", "retrieval"): "JTB_SEMANTIC_RETRIEVAL",
    ("semantic", "rerank"): "JTB_SEMANTIC_RERANK",
    ("semantic", "timeout_seconds"): "JTB_RETRIEVAL_TIMEOUT_SECONDS",
    ("storage", "upload_dir"): "JTB_UPLOAD_DIR",
    ("storage", "output_dir"): "JTB_OUTPUT_DIR",
}


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"运行配置不存在: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"运行配置根节点必须是映射: {path}")
    return value


def load_runtime_profile(
    profile: str | None = None,
    *,
    resource_root: str | Path = DEFAULT_RESOURCE_ROOT,
) -> dict[str, Any]:
    """Load and merge application.yml with one isolated environment profile."""
    selected = (profile or os.getenv("SPRING_PROFILES_ACTIVE", "dev")).strip().lower()
    if selected not in ALLOWED_PROFILES:
        raise ValueError(
            f"SPRING_PROFILES_ACTIVE 必须是 {', '.join(sorted(ALLOWED_PROFILES))}"
        )
    root = Path(resource_root)
    base = _read_yaml(root / "application.yml")
    override = _read_yaml(root / f"application-{selected}.yml")
    merged = _deep_merge(base, override)
    merged["active_profile"] = selected
    merged["resource_root"] = str(root.resolve())
    return merged


def _nested_value(data: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _env_text(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def apply_runtime_profile(
    profile: str | None = None,
    *,
    resource_root: str | Path = DEFAULT_RESOURCE_ROOT,
) -> dict[str, Any]:
    """Apply non-secret profile values as defaults without overriding the environment."""
    settings = load_runtime_profile(profile, resource_root=resource_root)
    for path, env_name in _ENV_BINDINGS.items():
        value = _nested_value(settings, path)
        if value is not None:
            os.environ.setdefault(env_name, _env_text(value))
    return settings


def public_runtime_status(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Return only safe operational metadata suitable for the health endpoint."""
    return {
        "profile": str(settings.get("active_profile", "")),
        "server_port": int(os.getenv("JTB_PORT", "7860")),
        "max_concurrent_jobs": int(os.getenv("JTB_MAX_CONCURRENT_JOBS", "1")),
        "semantic_retrieval": os.getenv("JTB_SEMANTIC_RETRIEVAL", "0") == "1",
        "semantic_rerank": os.getenv("JTB_SEMANTIC_RERANK", "0") == "1",
    }
