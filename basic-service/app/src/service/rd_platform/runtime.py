"""Configured R&D store instances, independent of the HTTP controllers."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from src.application.paths import RUNTIME_DIR

from .store import RdStore


@lru_cache(maxsize=4)
def _store_for_paths(db_path: str, artifact_root: str):
    return RdStore(Path(db_path), Path(artifact_root))


def get_store() -> RdStore:
    from src.service.rd_platform.demo import demo_mode_enabled
    runtime = RUNTIME_DIR
    demo = demo_mode_enabled()
    db = os.environ.get("JTB_RD_DB") or str(runtime / ("rd_platform.demo.sqlite3" if demo else "rd_platform.sqlite3"))
    artifacts = os.environ.get("JTB_RD_ARTIFACTS") or str(Path(db).parent / ("rd_artifacts_demo" if demo else "rd_artifacts"))
    return _store_for_paths(db, artifacts)
