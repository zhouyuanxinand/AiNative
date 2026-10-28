"""Compose the public platform app without starting generation workers."""
from __future__ import annotations

from .bootstrap import configure_import_paths

configure_import_paths()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.common.platform_auth import AuthSettings, PlatformAuthMiddleware
from src.common.request_archive import RequestArchiveMiddleware
from src.common.request_log_store import get_request_log_store
from src.controller.assistant_controller import router as assistant_router
from src.controller.auth_controller import router as auth_router
from src.controller.auth_settings_controller import router as auth_settings_router
from src.controller.demo_controller import router as demo_router
from src.controller.failure_database_controller import router as failure_database_router
from src.controller.feedback_controller import public_router as feedback_router
from src.controller.help_resources_controller import (
    read_router as help_resources_router,
)
from src.controller.rd_controller import router as rd_router
from src.controller.rd_taskbook_controller import router as rd_taskbook_router
from src.controller.review_controller import router as review_router
from src.controller.review_editor_controller import router as review_editor_router
from src.controller.service_credentials_controller import (
    router as service_credentials_router,
)
from src.controller.taskbook_controller import router as taskbook_router
from src.service.rd_platform.integration import RdJobAccessMiddleware
from src.utils.config_loader import AppConfig, get_config

from .middleware import CorrelationIdMiddleware, UploadContentLengthLimitMiddleware
from .web import mount_platform_web


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Application factory used by uvicorn and tests."""
    settings = config or get_config()
    from src.service.rd_platform.demo import ensure_demo_workspace
    ensure_demo_workspace()
    application = FastAPI(
        title="研发管理平台",
        description="研发项目、需求基线、任务协同、成果审签与研制任务书受控生成。",
        version="1.0.0",
    )
    application.state.config = settings
    application.state.request_log_store = get_request_log_store(settings.logs_dir)
    auth_settings = AuthSettings.from_env()
    application.state.auth_settings = auth_settings
    application.state.auth_settings_requires_admin = True

    allow_credentials = settings.cors_origins != ["*"]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )
    application.add_middleware(UploadContentLengthLimitMiddleware)
    application.add_middleware(CorrelationIdMiddleware)
    application.add_middleware(RequestArchiveMiddleware, store=application.state.request_log_store)
    application.add_middleware(RdJobAccessMiddleware)
    application.add_middleware(PlatformAuthMiddleware, settings=auth_settings)

    application.include_router(taskbook_router)
    application.include_router(auth_router)
    application.include_router(auth_settings_router)
    application.include_router(failure_database_router)
    application.include_router(feedback_router)
    application.include_router(help_resources_router)
    application.include_router(service_credentials_router)
    application.include_router(review_editor_router)
    application.include_router(review_router)
    application.include_router(rd_router)
    application.include_router(rd_taskbook_router)
    application.include_router(demo_router)
    application.include_router(assistant_router)

    mount_platform_web(application)
    return application
