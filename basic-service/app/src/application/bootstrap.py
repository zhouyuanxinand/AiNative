"""Import setup for the existing standalone controlled generation package."""
from __future__ import annotations

import sys

from .paths import SERVICE_DIR, SRC_DIR


def configure_import_paths() -> None:
    """Expose legacy engine modules without constructing either HTTP app."""
    for candidate in (str(SERVICE_DIR), str(SRC_DIR)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
