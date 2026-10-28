"""Startup and shutdown owned exclusively by the generation listener."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.common.logger import configure_logging, get_logger, shutdown_logging
from src.controller.taskbook_controller import register as register_controller
from src.utils.config_loader import get_config

logger = get_logger("src.main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_config()
    archive_store = _app.state.request_log_store
    # Only the single generation service owns recovery. Starting/restarting the
    # independent admin listener must never close active generation archives.
    archive_store.recover_interrupted()
    configure_logging(
        level=settings.log_level,
        log_dir=settings.logs_dir,
        archive_store=archive_store,
    )
    register_controller(_app, settings)
    from src.service.rd_platform.demo_taskbook import ensure_native_demo_workspace
    from src.service.rd_platform.runtime import get_store as get_rd_store
    from src.service.rd_platform.taskbook_runs import reconcile_taskbook_runs
    reconcile_taskbook_runs(get_rd_store())
    ensure_native_demo_workspace(get_rd_store())
    logger.info(
        "service_starting",
        extra={
            "profile": settings.profile,
            "host": settings.api_host,
            "port": settings.api_port,
        },
    )
    try:
        yield
    finally:
        logger.info("service_stopping")
        shutdown_logging()
