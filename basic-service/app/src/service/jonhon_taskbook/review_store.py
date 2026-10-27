"""Persistent, immutable document revisions and the inputs actually used by a task."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import threading
import time
import uuid
import zipfile

from lxml import etree

_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,100}$")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
logger = logging.getLogger(__name__)
SIDECARS = (
    "requirement_classification.json", "effective_requirement_classification.json", "semantic_plan.json", "semantic_evidence.json",
    "semantic_review.json", "coverage_ledger.json", "coverage_report.md", "qa_gate_report.md",
    "configured_qa_gate.json", "delivery_gate.json", "indicator_audit.json",
    "input_normalization.json", "process_rule_audit.json", "domain_rule_audit.json",
    "preservation.json", "regression.json", "business_value_audit.json",
)


class ReviewConflictError(ValueError):
    """The caller is editing an older revision."""

    status_code = 409


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identifier(value: str) -> str:
    if not _ID.fullmatch(value or ""):
        raise ValueError("无效的审阅标识")
    return value


def contained(path: Path, root: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("文件不在本任务允许的目录内")
    return path


def validate_docx(path: Path) -> None:
    if path.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("任务书不能超过 100 MB")
    try:
        with zipfile.ZipFile(path) as package:
            names = package.namelist()
            if len(names) != len(set(names)) or len(names) > 10000:
                raise ValueError("DOCX 包结构无效")
            if sum(item.file_size for item in package.infolist()) > 400 * 1024 * 1024:
                raise ValueError("DOCX 解压大小超过限制")
            if any(item.flag_bits & 1 for item in package.infolist()):
                raise ValueError("不支持加密的 DOCX 文件")
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise ValueError("请提供有效的 DOCX 任务书")
            if any(name.startswith(("/", "\\")) or ".." in Path(name.replace("\\", "/")).parts for name in names):
                raise ValueError("DOCX 包含不安全路径")
            if any("vbaproject" in name.lower() for name in names):
                raise ValueError("不支持包含宏的任务书")
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            root = etree.fromstring(package.read("word/document.xml"), parser)
            if root.tag != "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document":
                raise ValueError("DOCX 正文格式无效")
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise ValueError("请提供有效的 DOCX 任务书") from exc


class ReviewStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, jid: str) -> Path:
        return contained(self.root / _identifier(jid), self.root)

    @contextmanager
    def _lock(self, jid: str):
        lock_dir = self.root / ".locks"
        lock_dir.mkdir(exist_ok=True)
        path = lock_dir / (_identifier(jid) + ".lock")
        with _LOCKS_GUARD:
            lock = _LOCKS.setdefault(str(path), threading.RLock())
        with lock, path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                deadline = time.monotonic() + 30
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise ReviewConflictError("审阅正在保存，请稍后重试")
                        time.sleep(0.05)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _write(self, jid: str, bundle: dict) -> None:
        target = self.directory(jid) / "review.json"
        temporary = target.with_name("review-" + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(bundle, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def get_review(self, jid: str) -> dict:
        return json.loads((self.directory(jid) / "review.json").read_text(encoding="utf-8"))

    def ensure_review(self, jid: str, job: dict | None = None, source_roots: dict | None = None) -> dict:
        with self._lock(jid):
            if (self.directory(jid) / "review.json").is_file():
                return self.get_review(jid)
            if not job or job.get("status") not in {"done", "blocked"}:
                raise FileNotFoundError("该任务尚无可审阅的生成文件")
            roots = source_roots or {}
            output_root = Path(roots["output_dir"]).resolve()
            upload_root = (Path(roots["upload_dir"]) / jid).resolve()
            result = job.get("result") or {}
            original = contained(Path(result.get("out") or ""), output_root)
            if not original.is_file():
                raise FileNotFoundError("原始生成文件已不存在，不能建立审阅")
            validate_docx(original)
            expected_artifact = (result.get("meta") or {}).get("artifact_sha256") or job.get("artifact_sha256")
            if expected_artifact and digest(original) != expected_artifact:
                raise ValueError("原始生成文件与任务记录的哈希不符，不能作为审阅基线")
            directory = self.directory(jid)
            directory.mkdir(exist_ok=True)
            (directory / "assets").mkdir(exist_ok=True)
            (directory / "revisions").mkdir(exist_ok=True)
            baseline = directory / "revisions" / "baseline.docx"
            shutil.copy2(original, baseline)
            replay = job.get("replay") or {}
            options = replay.get("options") or {}
            meta = result.get("meta") or {}
            bundle = {
                "schema_version": 1, "jid": jid, "title": original.name,
                "created_at": now(), "selection": {**(replay.get("selection") or {}), **options},
                "baseline_revision_id": "baseline", "current_revision_id": "baseline",
                "generation_status": job.get("status"), "assets": [], "warnings": [],
                "revisions": [{"id": "baseline", "parent_id": None, "created_at": now(),
                    "actor": "生成服务", "reason": "原始生成件", "sha256": digest(baseline),
                    "filename": "baseline.docx", "annotations": [], "checks": None}],
                "generation_summary": {"delivery_status": result.get("delivery_status"),
                    "qa_ok": meta.get("qa_ok"), "warnings": result.get("warnings", []),
                    "rule_revisions": meta.get("rule_revisions", {})},
            }
            def archive(aid: str, role: str, label: str, source: Path | None, *, expected="", name=""):
                item = {"id": aid, "role": role, "label": label,
                        "name": name or (source.name if source else label),
                        "format": source.suffix.lstrip(".").lower() if source else "",
                        "available": False, "sha256": "", "url": f"/api/review/{jid}/assets/{aid}"}
                if source and source.is_file():
                    actual = digest(source)
                    if expected and expected != actual:
                        item["missing_reason"] = "任务副本哈希不符，未作为审阅依据"
                    else:
                        destination = directory / "assets" / (aid + source.suffix.lower())
                        shutil.copy2(source, destination)
                        item.update(available=True, sha256=actual, filename=destination.name)
                if not item["available"]:
                    item.setdefault("missing_reason", "历史任务未保留该文件或副本已清理")
                    bundle["warnings"].append(f"{label}：{item['missing_reason']}")
                bundle["assets"].append(item)

            files = replay.get("files") or {}
            for key, role, label in (
                ("tech", "tech", "需求文件"), ("spec", "spec", "产品规范"),
                ("template", "template_original", "原始受控模板"),
                ("mapping", "mapping", "原始章节映射"), ("profile", "profile", "产品规则"),
                ("effective_template", "template", "本次实际模板"),
                ("effective_mapping", "mapping", "本次章节映射"),
            ):
                file_meta = files.get(key) or {}
                source = None
                if file_meta.get("name"):
                    try:
                        source = contained(upload_root / file_meta["name"], upload_root)
                    except ValueError:
                        pass
                # Old tasks used the original snapshot unless an edit plan was applied.
                if key == "effective_template" and not file_meta:
                    if options.get("template_edit_plan") or meta.get("template_edited"):
                        source = upload_root / "template_edited.docx"
                    else:
                        file_meta = files.get("template") or {}
                        if file_meta.get("name"):
                            source = contained(upload_root / file_meta["name"], upload_root)
                if key == "effective_mapping" and not file_meta:
                    continue
                source = contained(source, upload_root) if source else None
                archive(key, role, label, source, expected=file_meta.get("sha256", ""),
                        name=(meta.get("inputs") or {}).get(key, ""))
            for key, file_meta in files.items():
                if not key.startswith("rule_"):
                    continue
                try:
                    _identifier(key)
                    source = contained(upload_root / file_meta["name"], upload_root)
                except (ValueError, KeyError):
                    continue
                archive(key, "rule", file_meta.get("original_name", key), source,
                        expected=file_meta.get("sha256", ""))
            if not any(item["role"] == "rule" and item["available"] for item in bundle["assets"]):
                bundle["warnings"].append("历史任务没有公共规则快照；不会使用当前规则冒充生成时规则。")
            for suffix in SIDECARS:
                path = original.with_suffix("." + suffix)
                if path.is_file():
                    expected = (job.get("sidecar_sha256") or {}).get("." + suffix, "")
                    archive("evidence_" + suffix.split(".")[0], "evidence", suffix, path, expected=expected)
            self._write(jid, bundle)
            logger.info("Review archived jid=%s assets=%s warnings=%s baseline_sha256=%s", jid,
                        sum(item["available"] for item in bundle["assets"]), len(bundle["warnings"]), digest(baseline))
            return bundle

    def revision(self, jid: str, revision_id: str) -> dict:
        _identifier(revision_id)
        for item in self.get_review(jid)["revisions"]:
            if item["id"] == revision_id:
                return item
        raise FileNotFoundError("修订版不存在")

    def revision_path(self, jid: str, revision_id: str) -> Path:
        item = self.revision(jid, revision_id)
        path = contained(self.directory(jid) / "revisions" / item["filename"], self.directory(jid))
        if not path.is_file() or digest(path) != item["sha256"]:
            raise ValueError("修订文件缺失或校验不一致")
        return path

    def asset_path(self, jid: str, asset_id: str) -> Path:
        _identifier(asset_id)
        for item in self.get_review(jid)["assets"]:
            if item["id"] == asset_id and item.get("available"):
                path = contained(self.directory(jid) / "assets" / item["filename"], self.directory(jid))
                if not path.is_file() or digest(path) != item["sha256"]:
                    raise ValueError("审阅依据文件缺失或校验不一致")
                return path
        raise FileNotFoundError("该审阅依据未归档或不存在")

    def save_revision(self, jid: str, expected_revision_id: str, docx_path: str | Path,
                      actor: str = "web-user", reason: str = "正文修改", changes: list | None = None) -> dict:
        source = Path(docx_path)
        validate_docx(source)
        with self._lock(jid):
            bundle = self.get_review(jid)
            if bundle["current_revision_id"] != expected_revision_id:
                logger.warning("Review revision conflict jid=%s expected=%s current=%s", jid, expected_revision_id, bundle["current_revision_id"])
                raise ReviewConflictError("已有更新的修订版，请刷新后再保存；本次修改未覆盖他人内容")
            revision_id = "r-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
            target = self.directory(jid) / "revisions" / (revision_id + ".docx")
            shutil.copy2(source, target)
            item = {"id": revision_id, "parent_id": expected_revision_id, "created_at": now(),
                    "actor": str(actor)[:100], "reason": str(reason)[:500], "sha256": digest(target),
                    "filename": target.name, "annotations": [], "checks": None, "changes": changes or []}
            bundle["revisions"].append(item)
            bundle["current_revision_id"] = revision_id
            self._write(jid, bundle)
            logger.info("Review revision saved jid=%s revision=%s parent=%s sha256=%s actor=%r", jid,
                        revision_id, expected_revision_id, item["sha256"], item["actor"])
            return bundle

    def restore_revision(self, jid: str, revision_id: str, expected_revision_id: str, actor="web-user") -> dict:
        return self.save_revision(jid, expected_revision_id, self.revision_path(jid, revision_id),
                                  actor, f"恢复版本 {revision_id}")

    def check_revision(self, jid: str, revision_id: str) -> dict:
        from jonhon_taskbook.review_checks import check_review_revision
        path = self.revision_path(jid, revision_id)
        checks = check_review_revision(self, jid, revision_id, path)
        with self._lock(jid):
            bundle = self.get_review(jid)
            for item in bundle["revisions"]:
                if item["id"] == revision_id:
                    item["checks"] = checks
            self._write(jid, bundle)
        logger.info("Review revision checked jid=%s revision=%s status=%s issues=%s", jid,
                    revision_id, checks["status"], len(checks["issues"]))
        return checks

    def annotate(self, jid: str, revision_id: str, element_id: str, status: str, note="", actor="web-user") -> dict:
        if status not in {"checked", "pending"}:
            raise ValueError("核对状态必须为 checked 或 pending")
        from jonhon_taskbook.review_document import document_projection
        document = document_projection(self.revision_path(jid, revision_id))
        from jonhon_taskbook.review_checks import flatten_blocks
        if element_id not in {item["id"] for item in flatten_blocks(document["blocks"])}:
            raise ValueError("段落定位已变化，请刷新当前修订版")
        with self._lock(jid):
            bundle = self.get_review(jid)
            revision = next(item for item in bundle["revisions"] if item["id"] == revision_id)
            annotations = [item for item in revision.get("annotations", []) if item["element_id"] != element_id]
            annotations.append({"element_id": element_id, "status": status, "note": str(note)[:2000],
                                "actor": str(actor)[:100], "updated_at": now()})
            revision["annotations"] = annotations
            self._write(jid, bundle)
        return {"annotations": annotations}
