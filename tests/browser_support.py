"""Shared paths and browser settings for standalone UI/integration checks."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "basic-service" / "app"
BASE = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:18130").rstrip("/")


def browser_options() -> dict:
    """Use an explicit executable, installed Windows Edge, or Playwright Chromium."""
    options = {"headless": True}
    configured = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if configured:
        options["executable_path"] = configured
    elif os.name == "nt":
        for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
            directory = os.environ.get(variable)
            if directory:
                edge = Path(directory) / "Microsoft/Edge/Application/msedge.exe"
                if edge.is_file():
                    options["executable_path"] = str(edge)
                    break
    return options
