"""Stable filesystem roots shared by HTTP composition and platform services.

The deployed app/resources and src/service paths are part of the controlled
engine's resource contract. Keep directory discovery here when moving adapters.
"""
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent
APP_DIR = SRC_DIR.parent
SERVICE_DIR = SRC_DIR / "service"
REPOSITORY_DIR = APP_DIR.parent.parent
RUNTIME_DIR = APP_DIR / "runtime"
