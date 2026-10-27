from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


TERMINAL_REVIEW_STATES = {"approved", "rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class ControlledAssetLifecycle:
    """Explicit review/publish/rollback lifecycle for uploaded template bundles.

    Candidate creation is intentionally separate (``template_onboarding``).  This
    class never accepts an arbitrary file path from a request: every operation is
    scoped to a candidate id below ``candidate_root``.
    """

    def __init__(
        self,
        *,
        candidate_root: str | Path,
        catalog_path: str | Path,
        template_root: str | Path,
        mapping_root: str | Path,
        profile_root: str | Path,
        audit_root: str | Path,
    ) -> None:
        self.candidate_root = Path(candidate_root).resolve()
        self.catalog_path = Path(catalog_path).resolve()
        self.template_root = Path(template_root).resolve()
        self.mapping_root = Path(mapping_root).resolve()
        self.profile_root = Path(profile_root).resolve()
        self.audit_root = Path(audit_root).resolve()

    def _candidate(self, candidate_id: str) -> Path:
        if not candidate_id or not candidate_id.isalnum():
            raise ValueError("候选版本编号非法")
        candidate = (self.candidate_root / candidate_id).resolve()
        try:
            candidate.relative_to(self.candidate_root)
        except ValueError as exc:
            raise ValueError("候选版本路径越界") from exc
        if not candidate.is_dir():
            raise FileNotFoundError(f"候选版本不存在: {candidate_id}")
        return candidate

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"JSON 必须是对象: {path.name}")
        return data

    def _state_path(self, candidate: Path) -> Path:
        return candidate / "lifecycle.json"

    def _state(self, candidate: Path) -> dict[str, Any]:
        path = self._state_path(candidate)
        if path.exists():
            return self._read_json(path)
        report = self._read_json(candidate / "onboarding_report.json")
        state = {
            "schema_version": "1.0",
            "candidate_id": candidate.name,
            "status": "validated" if report.get("machine_validation_passed") else "candidate",
            "machine_validation_passed": bool(report.get("machine_validation_passed")),
            "events": [{"at": _now(), "event": "candidate_registered"}],
        }
        self._write_state(candidate, state)
        return state

    def _write_state(self, candidate: Path, state: dict[str, Any]) -> None:
        _atomic_text(
            self._state_path(candidate),
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        )

    def list_candidates(self) -> list[dict[str, Any]]:
        if not self.candidate_root.exists():
            return []
        result = []
        for candidate in sorted(self.candidate_root.iterdir(), reverse=True):
            if candidate.is_dir() and (candidate / "onboarding_report.json").exists():
                result.append(self.describe(candidate.name))
        return result

    def describe(self, candidate_id: str) -> dict[str, Any]:
        candidate = self._candidate(candidate_id)
        report = self._read_json(candidate / "onboarding_report.json")
        state = self._state(candidate)
        return {
            "candidate_id": candidate_id,
            "status": state["status"],
            "machine_validation_passed": state["machine_validation_passed"],
            "product_type": report.get("product_type"),
            "product_label": report.get("product_label"),
            "domain": report.get("domain"),
            "domain_label": report.get("domain_label"),
            "version": report.get("version"),
            "template_sha256": report.get("template_sha256"),
            "events": state.get("events", []),
        }

    def review(
        self,
        candidate_id: str,
        *,
        approved: bool,
        reviewer: str,
        reason: str,
        regression_passed: bool,
        visual_review_passed: bool,
    ) -> dict[str, Any]:
        candidate = self._candidate(candidate_id)
        state = self._state(candidate)
        reviewer = reviewer.strip()
        reason = reason.strip()
        if not reviewer or not reason:
            raise ValueError("审核人和审核意见不能为空")
        if approved and not state["machine_validation_passed"]:
            raise ValueError("机器校验未通过，禁止批准")
        if approved and not regression_passed:
            raise ValueError("真实样例回归未通过，禁止批准")
        if approved and not visual_review_passed:
            raise ValueError("全页视觉复核未通过，禁止批准")
        state["status"] = "approved" if approved else "rejected"
        state["review"] = {
            "reviewer": reviewer,
            "reason": reason,
            "regression_passed": bool(regression_passed),
            "visual_review_passed": bool(visual_review_passed),
        }
        state["events"].append(
            {"at": _now(), "event": state["status"], "actor": reviewer, "reason": reason}
        )
        self._write_state(candidate, state)
        return self.describe(candidate_id)

    def publish(self, candidate_id: str, *, publisher: str) -> dict[str, Any]:
        candidate = self._candidate(candidate_id)
        state = self._state(candidate)
        publisher = publisher.strip()
        if not publisher:
            raise ValueError("发布人不能为空")
        if state["status"] != "approved":
            raise ValueError("只有已批准候选版本可以发布")
        report = self._read_json(candidate / "onboarding_report.json")
        files = report.get("files") or {}
        required = {"template", "mapping", "profile", "catalog_patch"}
        if set(files) != required:
            raise ValueError("候选包文件清单不完整")
        destinations = {
            "template": self.template_root / str(files["template"]),
            "mapping": self.mapping_root / str(files["mapping"]),
            "profile": self.profile_root / str(files["profile"]),
        }
        for kind, destination in destinations.items():
            source = candidate / str(files[kind])
            if not source.is_file():
                raise FileNotFoundError(f"候选包缺少 {kind}: {source.name}")
            if destination.exists() and _sha256(destination) != _sha256(source):
                raise FileExistsError(f"已存在不同内容的同名受控资产: {destination.name}")

        catalog_before = self.catalog_path.read_text(encoding="utf-8")
        catalog = yaml.safe_load(catalog_before) or {}
        patch = yaml.safe_load((candidate / str(files["catalog_patch"])).read_text(encoding="utf-8")) or {}
        patch_types = patch.get("product_types") or {}
        if len(patch_types) != 1:
            raise ValueError("目录补丁必须且只能包含一个产品类型")
        product_type, product_cfg = next(iter(patch_types.items()))
        product_cfg = dict(product_cfg)
        product_cfg["enabled"] = True
        product_cfg.pop("unavailable_reason", None)
        catalog.setdefault("product_types", {})[product_type] = product_cfg

        revision_dir = self.audit_root / candidate_id
        revision_dir.mkdir(parents=True, exist_ok=False)
        (revision_dir / "catalog_before.yaml").write_text(catalog_before, encoding="utf-8")
        for destination in destinations.values():
            destination.parent.mkdir(parents=True, exist_ok=True)
        for kind, destination in destinations.items():
            if not destination.exists():
                shutil.copy2(candidate / str(files[kind]), destination)
        _atomic_text(
            self.catalog_path,
            yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False),
        )
        state["status"] = "published"
        state["published_files"] = {key: str(value) for key, value in destinations.items()}
        state["events"].append({"at": _now(), "event": "published", "actor": publisher})
        self._write_state(candidate, state)
        (revision_dir / "publish_manifest.json").write_text(
            json.dumps(self.describe(candidate_id), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.describe(candidate_id)

    def rollback(self, candidate_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        candidate = self._candidate(candidate_id)
        state = self._state(candidate)
        actor, reason = actor.strip(), reason.strip()
        if state["status"] != "published":
            raise ValueError("只有已发布版本可以回滚")
        if not actor or not reason:
            raise ValueError("回滚人和回滚原因不能为空")
        snapshot = self.audit_root / candidate_id / "catalog_before.yaml"
        if not snapshot.exists():
            raise FileNotFoundError("找不到发布前目录快照，禁止不安全回滚")
        _atomic_text(self.catalog_path, snapshot.read_text(encoding="utf-8"))
        state["status"] = "rolled_back"
        state["events"].append(
            {"at": _now(), "event": "rolled_back", "actor": actor, "reason": reason}
        )
        self._write_state(candidate, state)
        return self.describe(candidate_id)
