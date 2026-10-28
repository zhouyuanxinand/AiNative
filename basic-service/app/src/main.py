"""Public platform entrypoint: ``python -m src.main`` from basic-service/app.

Application composition lives in src.application. create_app remains available
here for the existing uvicorn/test entrypoint contract.
"""
from __future__ import annotations

import os
import sys

from fastapi import FastAPI

from src.application.factory import create_app
from src.application.lifecycle import lifespan
from src.utils.config_loader import get_config


def _build_app() -> FastAPI:
    # Bind the lifespan to the lazily-built app. ``create_app`` is also used by
    # tests without the lifespan, so keep lifespan wiring here at module level.
    app = create_app()
    app.router.lifespan_context = lifespan
    return app


app = _build_app()


if __name__ == "__main__":
    import uvicorn

    _settings = get_config()
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if callable(_reconfigure):
            try:
                _reconfigure(errors="replace")
            except (OSError, ValueError):
                pass
    uvicorn.run(
        "src.main:app",
        host=os.getenv("JTB_HOST", _settings.api_host),
        port=int(os.getenv("JTB_PORT", _settings.api_port)),
    )
