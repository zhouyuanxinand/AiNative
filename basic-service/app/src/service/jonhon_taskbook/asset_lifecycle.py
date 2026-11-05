from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .template_derivation import candidate_file, core_asset_digest, digest, full_manifest

_CATALOG_LOCK = threading.RLock()


@contextmanager
def _catalog_lock(path):
    """Serialize compare-and-swap across workers, including Windows processes."""
    with _CATALOG_LOCK:
        lock_path = path.with_suffix(path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as stream:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)


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
            "asset_manifest": full_manifest(candidate),
            "asset_digest": core_asset_digest(candidate),
            "target_digest": self.target_digest(report.get("product_type"), report.get("domain")),
            "derivation": report.get("derivation"),
            "review": state.get("review"),
        }

    def target_digest(self, product_type, domain):
        catalog = yaml.safe_load(self.catalog_path.read_text(encoding="utf-8")) or {}
        return digest(self._target(catalog, product_type, domain))

    @staticmethod
    def _target(catalog, product_type, domain):
        return deepcopy((catalog.get("product_types", {}).get(product_type) or {}).get("domains", {}).get(domain))

    def _validate_evidence(self, candidate, evidence_manifest):
        if not isinstance(evidence_manifest, dict) or set(evidence_manifest) != {"regression", "visual"}:
            raise ValueError("批准需要固定的回归报告和全页视觉复核证据，布尔值不能作为证据")
        asset_digest = core_asset_digest(candidate)
        for kind, reference in evidence_manifest.items():
            path = candidate_file(candidate, reference.get("file"))
            if reference.get("sha256") != _sha256(path):
                raise ValueError("审核证据摘要变化")
            evidence = self._read_json(path)
            if evidence.get("fixture") or evidence.get("asset_digest") != asset_digest:
                raise ValueError("测试夹具或旧资产证据不能批准生产资产")
            if kind == "regression":
                report = self._read_json(candidate / "onboarding_report.json")
                if evidence.get("target") != {"product_type": report["product_type"], "domain": report["domain"]}:
                    raise ValueError("回归证据不属于候选目标产品及领域")
                runs = evidence.get("runs", [])
                if not runs:
                    raise ValueError("回归证据缺少真实样例运行")
                for run in runs:
                    if run.get("engine") != "src.pipeline_cli.run_pipeline" or not run.get("case") or not run.get("checks") or not all(c.get("passed") is True for c in run["checks"]):
                        raise ValueError("真实原引擎回归未通过")
                    self._validate_artifact_refs(candidate, run.get("outputs", []))
            else:
                if evidence.get("conclusion") != "passed" or not evidence.get("reviewer"):
                    raise ValueError("全页视觉复核未通过")
                if evidence.get("regression_sha256") != _sha256(candidate_file(candidate, evidence_manifest["regression"]["file"])):
                    raise ValueError("视觉复核未绑定本次固定回归证据")
                self._validate_artifact_refs(candidate, evidence.get("pages", []))

    @staticmethod
    def _validate_artifact_refs(candidate, references):
        if not references:
            raise ValueError("证据缺少实际产物")
        for reference in references:
            path = candidate_file(candidate, reference.get("file"))
            if _sha256(path) != reference.get("sha256"):
                raise ValueError("回归或视觉产物摘要变化")

    def review(
        self,
        candidate_id: str,
        *,
        approved: bool,
        reviewer: str,
        reason: str,
        regression_passed: bool,
        visual_review_passed: bool,
        evidence_manifest: dict | None = None,
        expected_manifest_digest: str | None = None,
    ) -> dict[str, Any]:
        candidate = self._candidate(candidate_id)
        state = self._state(candidate)
        reviewer = reviewer.strip()
        reason = reason.strip()
        if not reviewer or not reason:
            raise ValueError("审核人和审核意见不能为空")
        if state["status"] in {"published", "rolled_back"}:
            raise ValueError("发布历史不能重新审核覆写")
        if approved:
            manifest = full_manifest(candidate)
            if not expected_manifest_digest or manifest["digest"] != expected_manifest_digest:
                raise ValueError("候选完整资产摘要已变化或未固定")
            report = self._read_json(candidate / "onboarding_report.json")
            if report.get("derivation", {}).get("fixture"):
                raise ValueError("测试派生夹具禁止生产发布")
            self._validate_evidence(candidate, evidence_manifest)
            if full_manifest(candidate)["digest"] != manifest["digest"]:
                raise ValueError("审核期间候选资产变化")
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
            "manifest_digest": full_manifest(candidate)["digest"],
            "evidence_manifest": evidence_manifest,
        }
        state["events"].append(
            {"at": _now(), "event": state["status"], "actor": reviewer, "reason": reason}
        )
        self._write_state(candidate, state)
        return self.describe(candidate_id)

    def publish(self, candidate_id: str, *, publisher: str, expected_target_digest: str | None = None) -> dict[str, Any]:
        with _catalog_lock(self.catalog_path):
            return self._publish(candidate_id, publisher=publisher, expected_target_digest=expected_target_digest)

    def _publish(self, candidate_id: str, *, publisher: str, expected_target_digest=None) -> dict[str, Any]:
        candidate = self._candidate(candidate_id)
        state = self._state(candidate)
        publisher = publisher.strip()
        if not publisher:
            raise ValueError("发布人不能为空")
        if state["status"] != "approved":
            raise ValueError("只有已批准候选版本可以发布")
        if full_manifest(candidate)["digest"] != state.get("review", {}).get("manifest_digest"):
            raise ValueError("审核后的完整资产已变化，必须重新审核")
        self._validate_evidence(candidate, state["review"].get("evidence_manifest"))
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
            source = candidate_file(candidate, str(files[kind]))
            if destination.parent.resolve() not in {self.template_root, self.mapping_root, self.profile_root}:
                raise ValueError("发布目标路径越界")
            if not source.is_file():
                raise FileNotFoundError(f"候选包缺少 {kind}: {source.name}")
            if destination.exists() and _sha256(destination) != _sha256(source):
                raise FileExistsError(f"已存在不同内容的同名受控资产: {destination.name}")

        catalog_before = self.catalog_path.read_text(encoding="utf-8")
        catalog = yaml.safe_load(catalog_before) or {}
        patch = yaml.safe_load(candidate_file(candidate, str(files["catalog_patch"])).read_text(encoding="utf-8")) or {}
        patch_types = patch.get("product_types") or {}
        if len(patch_types) != 1:
            raise ValueError("目录补丁必须且只能包含一个产品类型")
        product_type, product_cfg = next(iter(patch_types.items()))
        product_cfg = dict(product_cfg)
        domains = product_cfg.get("domains") or {}
        if len(domains) != 1 or product_type != report.get("product_type") or report.get("domain") not in domains:
            raise ValueError("目录补丁必须绑定候选目标产品及唯一领域")
        domain, binding = next(iter(domains.items()))
        if not isinstance(binding, dict) or any(binding.get(key) != files[kind] for key, kind in
                (("template", "template"), ("profile", "profile"), ("category_mapping", "mapping"))):
            raise ValueError("目录目标绑定与已回归审核的候选资产不一致")
        before = self._target(catalog, product_type, domain)
        if not expected_target_digest or digest(before) != expected_target_digest:
            raise ValueError("目标产品/领域目录版本冲突")
        products = catalog.setdefault("product_types", {})
        existed = product_type in products
        current = products.setdefault(product_type, {k: v for k, v in product_cfg.items() if k != "domains"})
        metadata_before = {k: current.get(k) for k in ("enabled", "unavailable_reason")}
        current["enabled"] = True
        current.pop("unavailable_reason", None)
        current.setdefault("domains", {})[domain] = binding

        revision_dir = self.audit_root / candidate_id
        revision_dir.mkdir(parents=True, exist_ok=True)
        import uuid
        attempt_dir = revision_dir / uuid.uuid4().hex
        attempt_dir.mkdir()
        (attempt_dir / "catalog_before.yaml").write_text(catalog_before, encoding="utf-8")
        target_before = json.dumps({"product_type": product_type, "domain": domain,
                     "binding": before, "published_binding": binding, "product_existed": existed,
                     "metadata_before": metadata_before}, ensure_ascii=False)
        _atomic_text(attempt_dir / "target_before.json", target_before)
        for destination in destinations.values():
            destination.parent.mkdir(parents=True, exist_ok=True)
        for kind, destination in destinations.items():
            if not destination.exists():
                shutil.copy2(candidate_file(candidate, str(files[kind])), destination)
        if full_manifest(candidate)["digest"] != state["review"]["manifest_digest"]:
            raise ValueError("发布期间候选资产变化，未更新目录")
        _atomic_text(revision_dir / "target_before.json", target_before)
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
        with _catalog_lock(self.catalog_path):
            return self._rollback(candidate_id, actor=actor, reason=reason)

    def _rollback(self, candidate_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        candidate = self._candidate(candidate_id)
        state = self._state(candidate)
        actor, reason = actor.strip(), reason.strip()
        if state["status"] != "published":
            raise ValueError("只有已发布版本可以回滚")
        if not actor or not reason:
            raise ValueError("回滚人和回滚原因不能为空")
        snapshot = self.audit_root / candidate_id / "target_before.json"
        if not snapshot.exists():
            raise FileNotFoundError("找不到发布前目录快照，禁止不安全回滚")
        before = self._read_json(snapshot)
        catalog = yaml.safe_load(self.catalog_path.read_text(encoding="utf-8")) or {}
        product_type, domain = before["product_type"], before["domain"]
        if digest(self._target(catalog, product_type, domain)) != digest(before["published_binding"]):
            raise ValueError("目标已有后续发布，禁止覆盖回退")
        product = catalog["product_types"][product_type]
        if before["binding"] is None:
            product["domains"].pop(domain, None)
        else:
            product["domains"][domain] = before["binding"]
        if not product["domains"] and not before["product_existed"]:
            catalog["product_types"].pop(product_type)
        _atomic_text(self.catalog_path, yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False))
        state["status"] = "rolled_back"
        state["events"].append(
            {"at": _now(), "event": "rolled_back", "actor": actor, "reason": reason}
        )
        self._write_state(candidate, state)
        return self.describe(candidate_id)
