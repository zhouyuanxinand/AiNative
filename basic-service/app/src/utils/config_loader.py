from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.application.paths import APP_DIR, SERVICE_DIR


def _active_profile() -> str:
    """Resolve the runtime profile, honouring APP_ENV then SPRING_PROFILES_ACTIVE."""
    raw = (os.getenv("APP_ENV") or os.getenv("SPRING_PROFILES_ACTIVE") or "").strip()
    if not raw:
        return "development"
    normalized = raw.lower()
    return {"dev": "development", "test": "testing"}.get(normalized, normalized)


def _runtime_profile_settings() -> dict[str, Any]:
    """Load and apply the jonhon_taskbook runtime profile (non-secret defaults).

    The business package owns its own profile loader (dev/test/prod YAML under
    app/resources/). It uses ``SPRING_PROFILES_ACTIVE`` as its selector, so we
    mirror the selected profile into that variable before delegating. Credentials
    remain environment variables and always take precedence.
    """
    profile = _active_profile()
    profile_token = {"development": "dev", "testing": "test", "prod": "prod"}.get(
        profile, "dev"
    )
    # The package loader reads SPRING_PROFILES_ACTIVE; keep it in sync with APP_ENV.
    os.environ.setdefault("SPRING_PROFILES_ACTIVE", profile_token)
    from jonhon_taskbook.runtime_profile import apply_runtime_profile

    return apply_runtime_profile(profile_token)


def _parse_cors_origins(raw: Any) -> list[str]:
    if not raw:
        return ["*"]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    text = str(raw).strip()
    if text.startswith("["):
        import json

        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
    return [origin.strip() for origin in text.split(",") if origin.strip()]


@dataclass(frozen=True)
class AppConfig:
    """Frozen application configuration assembled from YAML profiles and env."""

    profile: str
    app_name: str
    api_host: str
    api_port: int
    cors_origins: list[str]
    upload_dir: Path
    output_dir: Path
    config_dir: Path
    prompts_dir: Path
    resources_dir: Path
    package_root: Path
    package_resources_dir: Path
    logs_dir: Path
    template_candidate_dir: Path
    template_release_dir: Path
    max_upload_bytes: int
    max_concurrent_jobs: int
    job_ttl_seconds: int
    max_job_records: int
    allow_local_paths: bool
    allow_remote_llm_config: bool
    log_level: str
    runtime_settings: dict[str, Any] = field(default_factory=dict)


def load_config() -> AppConfig:
    """Build the immutable AppConfig from the runtime profile + environment."""
    settings = _runtime_profile_settings()
    profile = _active_profile()
    app_name = str(
        settings.get("application", {}).get("name", "agent-develop-task-doc-service")
    )

    api_host = os.getenv("JTB_HOST") or str(
        settings.get("server", {}).get("host", "0.0.0.0")
    )
    api_port = int(os.getenv("JTB_PORT") or settings.get("server", {}).get("port", 18130))

    cors_raw = os.getenv("CORS_ORIGINS") or settings.get("cors", {}).get("origins", ["*"])
    cors_origins = _parse_cors_origins(cors_raw)

    package_root = SERVICE_DIR / "jonhon_taskbook"
    config_dir = SERVICE_DIR / "config"
    prompts_dir = SERVICE_DIR / "prompts"
    resources_dir = APP_DIR / "resources"
    package_resources_dir = package_root / "resources"
    logs_dir = APP_DIR / "logs"

    storage = settings.get("storage", {}) or {}
    upload_dir = Path(
        os.getenv("JTB_UPLOAD_DIR") or storage.get("upload_dir") or str(APP_DIR / "uploads")
    )
    output_dir = Path(
        os.getenv("JTB_OUTPUT_DIR") or storage.get("output_dir") or str(APP_DIR / "正式输出")
    )

    runtime_root = APP_DIR / "runtime"
    template_candidate_dir = Path(
        os.getenv("JTB_TEMPLATE_CANDIDATE_DIR") or str(runtime_root / "template_candidates")
    )
    template_release_dir = Path(
        os.getenv("JTB_TEMPLATE_RELEASE_AUDIT_DIR") or str(runtime_root / "template_releases")
    )

    jobs = settings.get("jobs", {}) or {}
    uploads_cfg = settings.get("uploads", {}) or {}

    return AppConfig(
        profile=profile,
        app_name=app_name,
        api_host=api_host,
        api_port=api_port,
        cors_origins=cors_origins,
        upload_dir=upload_dir,
        output_dir=output_dir,
        config_dir=config_dir,
        prompts_dir=prompts_dir,
        resources_dir=resources_dir,
        package_root=package_root,
        package_resources_dir=package_resources_dir,
        logs_dir=logs_dir,
        template_candidate_dir=template_candidate_dir,
        template_release_dir=template_release_dir,
        max_upload_bytes=int(os.getenv("JTB_MAX_UPLOAD_MB") or uploads_cfg.get("max_mb", 100))
        * 1024
        * 1024,
        max_concurrent_jobs=max(1, int(os.getenv("JTB_MAX_CONCURRENT_JOBS") or jobs.get("max_concurrent", 2))),
        job_ttl_seconds=int(os.getenv("JTB_JOB_TTL_HOURS") or jobs.get("ttl_hours", 24)) * 60 * 60,
        max_job_records=int(os.getenv("JTB_MAX_JOB_RECORDS") or jobs.get("max_records", 100)),
        allow_local_paths=os.getenv("JTB_ALLOW_LOCAL_PATHS", "0") == "1",
        allow_remote_llm_config=os.getenv("JTB_ALLOW_REMOTE_LLM_CONFIG", "0")
        in {"1", "true", "yes", "on"},
        log_level=str(os.getenv("LOG_LEVEL") or settings.get("logging", {}).get("level", "INFO")),
        runtime_settings=settings,
    )


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config()
