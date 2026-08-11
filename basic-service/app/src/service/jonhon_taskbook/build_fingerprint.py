"""Deterministic build/rule fingerprint shared by CLI, Web and reports.

The fingerprint proves which repository code and controlled rule pack produced
an artifact.  It deliberately excludes environment files, credentials, upload
directories, generated outputs and absolute local paths.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "jonhon_taskbook"
RULE_PACK = PROJECT_ROOT / "resources" / "customer_rules" / "2026-07-22"
PIPELINE_VERSION = "2026.07.22-controlled-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_files() -> list[Path]:
    files = [PROJECT_ROOT / "pipeline.py", PROJECT_ROOT / "app.py"]
    files.extend(
        path for path in PACKAGE_ROOT.rglob("*.py")
        if "tests" not in path.parts and "__pycache__" not in path.parts
    )
    files.extend((PROJECT_ROOT / "config").rglob("*.yaml"))
    files.extend((PROJECT_ROOT / "config").rglob("*.yml"))
    files.extend(PACKAGE_ROOT.glob("*.yaml"))
    files.extend(PACKAGE_ROOT.glob("*.yml"))
    return sorted({path.resolve() for path in files if path.is_file()})


def _combined_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(PROJECT_ROOT.resolve()).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256(path)))
    return digest.hexdigest()


def _controlled_artifacts() -> dict[str, str]:
    candidates = {
        "rule_manifest": RULE_PACK / "manifest.json",
        "rule_workbook": RULE_PACK / "研制任务书生成规则7-22.xlsx",
        "indicator_workbook": PACKAGE_ROOT / "resources" / "mappings" / "indicator_taxonomy_20260722.xlsx",
        "failure_database": PACKAGE_ROOT / "resources" / "mappings" / "failure_mode_database_20260722.xlsx",
        "product_catalog": PROJECT_ROOT / "config" / "template_catalog.yaml",
        "category_mapping": PROJECT_ROOT / "config" / "connector_requirement_categories.yaml",
    }
    return {
        name: _sha256(path)
        for name, path in candidates.items()
        if path.is_file()
    }


def build_fingerprint(*, include_process: bool = False) -> dict:
    source_files = _source_files()
    artifacts = _controlled_artifacts()
    identity = {
        "pipeline_version": PIPELINE_VERSION,
        "source_digest": _combined_digest(source_files),
        "controlled_artifacts": artifacts,
        "rule_pack": "2026-07-22",
    }
    identity["build_id"] = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    if include_process:
        identity["process_id"] = os.getpid()
    return identity
