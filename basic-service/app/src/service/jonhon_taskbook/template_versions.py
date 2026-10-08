"""Replace an existing catalog binding without changing its business rules."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml
from docx import Document

from .asset_lifecycle import _atomic_text
from .input_normalizer import normalize_input
from .template_registry import _resolve_controlled
from .template_scanner import scan_template_tree


class TemplateConflictError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _verify_docx(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 5000 or sum(m.file_size for m in members) > 200 * 1024 * 1024:
                raise ValueError("模板解压后过大，请精简图片或附件后重试。")
            if {"[Content_Types].xml", "word/document.xml"} - set(archive.namelist()):
                raise ValueError("文件不是有效的 Word 文档。")
            if any(".." in m.filename.replace("\\", "/").split("/") or
                   m.filename.startswith(("/", "\\")) for m in members):
                raise ValueError("Word 文档包含不安全的压缩包路径。")
            if any("vbaproject" in m.filename.lower() for m in members):
                raise ValueError("模板不能包含宏，请另存为无宏 DOCX 后上传。")
        Document(path)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("Word 模板无法读取，请检查文件是否损坏或加密。") from exc


def validate_replacement(template: Path, mapping_path: Path, previous: Path) -> dict:
    """Check the existing product's semantic destinations and supported tables."""
    _verify_docx(template)
    mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    slots = scan_template_tree(str(template))
    by_id = {slot["id"]: slot for slot in slots}
    problems, matches = [], []
    routing_rules = {**mapping.get("semantic_roles", {}), **mapping.get("categories", {})}
    for key, rule in routing_rules.items():
        if rule.get("container_only"):
            continue
        names = rule.get("target_heading_keywords") or []
        if isinstance(names, str):
            names = [names]
        candidates = [
            s for s in slots
            if any(name in s["title"] for name in names)
            and (not rule.get("target_heading_level") or s["level"] == rule["target_heading_level"])
            and (not rule.get("target_parent_heading") or
                 by_id.get(s.get("parent_id"), {}).get("title") == rule["target_parent_heading"])
        ]
        if len(candidates) != 1:
            problems.append(f"“{rule.get('label', key)}”需要唯一目标章节，当前找到 {len(candidates)} 个（{'、'.join(names)}）。")
        else:
            matches.append({"category": key, "title": candidates[0]["title"]})
    doc = Document(template)
    indicator_tables = [
        t for t in doc.tables if t.rows
        and "用户要求" in "".join(c.text for c in t.rows[0].cells)
    ]
    requirements_mode = mapping.get("technical_requirements_mode", "table")
    if requirements_mode not in ("table", "sections"):
        problems.append(f"无法识别技术要求填写模式：{requirements_mode}。")
    if requirements_mode == "sections":
        # Section templates use the same semantic destination checks above;
        # they must not acquire an unrelated connector indicator table.
        performance = routing_rules.get("performance_indicator", {})
        if performance.get("container_only"):
            targets = performance.get("block_target_categories")
            if not isinstance(targets, list) or not targets or any(not isinstance(target, str) for target in targets):
                problems.append("章节式技术要求容器需明确声明技术叶子类别 block_target_categories。")
            else:
                matched = {match["category"] for match in matches}
                for target in targets:
                    if target not in matched or routing_rules.get(target, {}).get("container_only"):
                        label = routing_rules.get(target, {}).get("label", target)
                        problems.append(f"章节式技术要求叶子类别“{label}”需配置并保留唯一的可写目标章节。")
        elif not any(match["category"] == "performance_indicator" for match in matches):
            problems.append("章节式技术要求需配置并保留唯一的技术指标目标章节。")
    elif len(indicator_tables) != 1:
        problems.append(f"需要一张技术指标表，当前识别到 {len(indicator_tables)} 张。")
    elif len(indicator_tables[0].rows[0].cells) not in (4, 5):
        problems.append("技术指标表须为四列或五列，包含项目、用户要求指标、拟采用指标及依据。")
    else:
        table = indicator_tables[0]
        headers = [re.sub(r"\s+", "", c.text) for c in table.rows[0].cells]
        if not (
            any(label in headers[0] for label in ("项目", "指标", "名称"))
            and "用户要求" in headers[1] and "拟采用" in headers[-2]
            and "依据" in headers[-1]
            and (len(headers) == 4 or any(label in headers[2] for label in ("标准", "规范")))
        ):
            problems.append("指标表列顺序须为：项目、用户要求、〔标准要求〕、拟采用指标、依据。")
        if not any(len(row._tr.tc_lst) == len(headers) for row in table.rows[1:]):
            problems.append("指标表需保留至少一行未合并的指标填写行。")
    before = scan_template_tree(str(previous))
    old_titles, new_titles = {s["title"] for s in before}, {s["title"] for s in slots}
    return {
        "passed": not problems, "problems": problems, "matches": matches,
        "technical_requirements_mode": requirements_mode,
        "heading_count": len(slots), "table_count": len(doc.tables),
        "headings_added": sorted(new_titles - old_titles),
        "headings_removed": sorted(old_titles - new_titles),
    }


class TemplateVersions:
    """Immutable files, per-product activation, and durable version history.

    The catalog is the sole active pointer. Publishing copies a verified file
    first, then atomically updates just one domain. Readers keep the old file
    for in-flight jobs. The lock is shared with the rule editor in the API.
    """

    def __init__(self, catalog_path, template_root, mapping_root, history_root, *, lock=None):
        self.catalog_path = Path(catalog_path).resolve()
        self.template_root = Path(template_root).resolve()
        self.mapping_root = Path(mapping_root).resolve()
        self.history_root = Path(history_root).resolve()
        self.lock = lock or threading.RLock()

    def _binding(self, product: str, domain: str):
        catalog = yaml.safe_load(self.catalog_path.read_text(encoding="utf-8"))
        product_cfg = catalog.get("product_types", {}).get(product)
        if not isinstance(product_cfg, dict) or not product_cfg.get("enabled", True):
            raise ValueError("请选择目录中已启用的产品类型。")
        config = product_cfg.get("domains", {}).get(domain)
        if not isinstance(config, dict):
            raise ValueError("该产品没有所选质量管理体系的模板。")
        path = _resolve_controlled(self.template_root, config.get("template", ""), "当前模板")
        digest = _digest(path)
        token = hashlib.sha256(json.dumps([config, digest], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return catalog, product_cfg, config, path, digest, token

    def current(self, product: str, domain: str) -> dict:
        _, product_cfg, config, path, digest, token = self._binding(product, domain)
        return self._current(product, domain, product_cfg, config, path, digest, token)

    @staticmethod
    def _current(product, domain, product_cfg, config, path, digest, token) -> dict:
        return {
            "product_type_id": product, "product_domain_id": domain,
            "product_type": product_cfg.get("label", product),
            "product_domain": config.get("label", domain),
            "template": path.name,
            "filename": config.get("template_source_name", path.name),
            "version": config.get("template_version", "初始版本"),
            "version_id": config.get("template_revision", ""),
            "updated_at": config.get("template_updated_at", ""),
            "sha256": digest, "revision": token,
        }

    def catalog_items(self) -> list[dict]:
        catalog = yaml.safe_load(self.catalog_path.read_text(encoding="utf-8"))
        hashes, result = {}, []
        for product, product_cfg in catalog.get("product_types", {}).items():
            if not product_cfg.get("enabled", True):
                continue
            for domain, config in product_cfg.get("domains", {}).items():
                path = _resolve_controlled(self.template_root, config.get("template", ""), "当前模板")
                if path not in hashes:
                    hashes[path] = _digest(path)
                digest = hashes[path]
                token = hashlib.sha256(json.dumps([config, digest], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                result.append(self._current(product, domain, product_cfg, config, path, digest, token))
        return result

    def _directory(self, version_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", version_id):
            raise ValueError("模板版本编号无效。")
        directory = (self.history_root / version_id).resolve()
        if not directory.is_relative_to(self.history_root):
            raise ValueError("模板版本路径无效。")
        return directory

    def _read(self, version_id: str) -> dict:
        path = self._directory(version_id) / "version.json"
        if not path.is_file():
            raise FileNotFoundError("模板版本不存在。")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, record: dict) -> None:
        _atomic_text(self._directory(record["id"]) / "version.json",
                     json.dumps(record, ensure_ascii=False, indent=2))

    def _describe(self, record: dict, current: dict) -> dict:
        active = record["id"] == current["version_id"]
        status = ("active" if active else "historical" if record.get("activated_at")
                  else "ready" if record["validation"]["passed"] else "invalid")
        return {key: record.get(key) for key in (
            "id", "product", "domain", "filename", "version", "note", "actor",
            "created_at", "activated_at", "sha256", "validation", "warnings", "base_revision",
        )} | {"status": status}

    def history(self, product: str, domain: str) -> dict:
        current = self.current(product, domain)
        records = []
        for path in self.history_root.glob("*/version.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if (record["product"], record["domain"]) == (product, domain):
                records.append(self._describe(record, current))
        records.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return {"current": current, "versions": records}

    def stage(self, product: str, domain: str, filename: str, payload: bytes, *,
              version: str = "", note: str = "", actor: str = "web-user") -> dict:
        current = self.current(product, domain)
        _, _, config, previous, _, _ = self._binding(product, domain)
        version_id = uuid.uuid4().hex
        directory = self._directory(version_id)
        suffix = Path(filename).suffix.lower()
        if suffix not in (".doc", ".docx") or not payload:
            raise ValueError("请选择非空的 DOC 或 DOCX 模板。")
        is_docx = payload.startswith(b"PK")
        if not is_docx and (suffix != ".doc" or not payload.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))):
            raise ValueError("文件内容与 Word 格式不符。")
        directory.mkdir(parents=True)
        source = directory / ("source.docx" if is_docx else "source.doc")
        source.write_bytes(payload)
        if is_docx:
            _verify_docx(source)
        normalized = normalize_input(source, directory / "conversion")
        target = directory / "template.docx"
        shutil.copy2(normalized.path, target)
        mapping = _resolve_controlled(self.mapping_root, config.get("category_mapping", ""), "产品分类规则")
        validation = validate_replacement(target, mapping, previous)
        record = {
            "id": version_id, "product": product, "domain": domain,
            "filename": Path(filename.replace("\\", "/")).name,
            "version": version.strip() or datetime.now().strftime("%Y%m%d-%H%M%S"),
            "note": note.strip(), "actor": actor.strip() or "web-user", "created_at": _now(),
            "sha256": _digest(target), "source_sha256": hashlib.sha256(payload).hexdigest(),
            "base_revision": current["revision"], "validation": validation,
            "warnings": list(normalized.warnings),
        }
        self._write(record)
        return {"current": current, "version": self._describe(record, current)}

    def file(self, version_id: str) -> tuple[Path, str]:
        record = self._read(version_id)
        path = self._directory(version_id) / "template.docx"
        if not path.is_file() or _digest(path) != record["sha256"]:
            raise ValueError("模板版本文件已变化或丢失，请重新上传。")
        return path, Path(record["filename"]).stem + ".docx"

    def current_file(self, product: str, domain: str) -> tuple[Path, str]:
        current = self.current(product, domain)
        path = self._binding(product, domain)[3]
        return path, Path(current["filename"]).stem + ".docx"

    def activate(self, version_id: str, *, expected_revision: str,
                 actor: str = "web-user", note: str = "") -> dict:
        with self.lock:
            record = self._read(version_id)
            product, domain = record["product"], record["domain"]
            current = self.current(product, domain)
            if current["version_id"] == version_id:
                return self.history(product, domain)
            if not expected_revision or current["revision"] != expected_revision:
                raise TemplateConflictError("当前模板已被更新，请刷新目录后重试。")
            if not record.get("activated_at") and record["base_revision"] != expected_revision:
                raise TemplateConflictError("上传后当前模板已变化，请重新上传并校验。")
            path, _ = self.file(version_id)
            catalog, _, config, previous, _, _ = self._binding(product, domain)
            mapping = _resolve_controlled(self.mapping_root, config.get("category_mapping", ""), "产品分类规则")
            validation = validate_replacement(path, mapping, previous)
            if not validation["passed"]:
                raise ValueError("模板校验未通过：" + "；".join(validation["problems"]))
            # Save the original binding once before the first activation.
            if not current["version_id"]:
                backup_id = uuid.uuid4().hex
                backup_dir = self._directory(backup_id)
                backup_dir.mkdir(parents=True)
                shutil.copy2(previous, backup_dir / "template.docx")
                self._write({
                    "id": backup_id, "product": product, "domain": domain,
                    "filename": current["filename"], "version": current["version"],
                    "note": "首次更换前的模板", "actor": actor, "created_at": _now(),
                    "activated_at": config.get("template_updated_at") or _now(),
                    "sha256": current["sha256"], "base_revision": current["revision"],
                    "validation": validate_replacement(previous, mapping, previous), "warnings": [],
                })
            destination = self.template_root / "versions" / (version_id + ".docx")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if _digest(destination) != record["sha256"]:
                    raise ValueError("已归档模板文件发生变化，禁止启用。")
            else:
                shutil.copy2(path, destination)
            now = _now()
            config.update({
                "template": destination.relative_to(self.template_root).as_posix(),
                "template_revision": version_id, "template_version": record["version"],
                "template_source_name": record["filename"], "template_updated_at": now,
            })
            _atomic_text(self.catalog_path, yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False))
            record["activated_at"] = now
            record["validation"] = validation
            record.setdefault("events", []).append({
                "at": now, "actor": actor.strip() or "web-user",
                "note": note.strip() or record.get("note", ""),
                "previous_version_id": current["version_id"], "previous_sha256": current["sha256"],
            })
            self._write(record)
            return self.history(product, domain)
