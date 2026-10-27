"""Edit the supported business fields of the registered taskbook rule files.

The editor exposes field patches, never arbitrary YAML or filesystem paths.
The generation modules remain the owners of executable behavior; this module
owns validation, optimistic concurrency and the on-disk revision journal.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .indicator_profile_validator import validate_indicator_profile


class RuleValidationError(ValueError):
    """A requested business rule change is not supported or is invalid."""


class RuleConflictError(RuntimeError):
    """The caller edited a version which is no longer current."""


class RuleNotFoundError(LookupError):
    """The requested rule or historical revision is not registered."""


_LOCK = threading.RLock()
_CATEGORY_FILES = {
    "connector_requirement_categories": "低频连接器语义分类",
    "rf_connector_requirement_categories": "射频连接器语义分类",
    "filter_connector_requirement_categories": "滤波连接器语义分类",
    "cable_assembly_requirement_categories": "线缆组件语义分类",
    "liquid_cooling_pipeline_requirement_categories": "液冷管路语义分类",
    "liquid_cooling_chassis_requirement_categories": "液冷机箱与冷板语义分类",
    "optical_connector_requirement_categories": "光连接器语义分类",
    "optical_cable_assembly_requirement_categories": "光缆组件语义分类",
    "liquid_cooling_connector_requirement_categories": "液冷连接器语义分类",
    "printed_board_assembly_requirement_categories": "印制板组件语义分类",
    "chassis_requirement_categories": "机箱、安装板与光布线箱语义分类",
    "system_integration_requirement_categories": "安装架、设备柜与显控台语义分类",
}
_POLICY_FILES = {
    "development_process_policy": ("研制流程与六性证据", "业务策略", "设置 QFD、运行场景与关联附录的保留流程，以及流程别名和六性章节证据词。"),
    "standard_applicability": ("标准与领域适用范围", "业务策略", "设置标准族、模板标记和领域章节的适用范围。"),
    "failure_mode_policy": ("历史故障空结果说明", "业务策略", "设置未匹配到本产品与系列历史故障时的说明文字。"),
    "qa_gate": ("文档质量检查", "质量检查", "设置生成文档的质量阈值、模板残留词及有效检查项。"),
    "template_variant_policy": ("研制经费模板分支", "模板分支", "设置不同产品归属范围对应的标题识别词。"),
    "single_budget_template_variant_policy": ("单预算模板分支", "模板分支", "设置仅提供非中央研究院预算分支的模板标题识别词。"),
    "connector_indicator_catalog": ("通用指标词表", "指标词表", "设置有来源证据时才启用的指标别名与关联词，不提供指标数值。"),
    "taskbook_requirement_taxonomy": ("新模板候选分类词表", "模板接入", "仅用于新模板候选包接入；已启用产品生成时使用各产品语义分类规则。"),
}
_LABELS = {
    "label": "显示名称", "definition": "分类定义", "source_heading_keywords": "来源标题关键词",
    "source_parent_heading_keywords": "来源父标题关键词", "source_content_patterns": "来源内容匹配表达式",
    "atomic_source_heading_keywords": "完整来源标题关键词", "target_heading_keywords": "目标标题关键词",
    "target_heading_level": "目标标题层级", "target_parent_heading": "目标父标题", "content_priority": "内容匹配优先级",
    "excluded_indicator_names": "排除的指标名称", "source_categories": "适用的来源分类",
    "target_categories": "允许的目标分类", "min_text_length": "最短片段字数",
    "max_fragments_per_block": "每个来源块的最大片段数", "match_any": "任一命中词", "extract_patterns": "证据提取表达式",
    "tech_kws": "需求指标识别词", "std_kws": "规范指标识别词", "related_kws": "相关指标识别词",
    "spec_exact_names": "规范精确匹配名称", "value_patterns": "来源数值提取表达式", "reference_families": "引用的指标词表家族",
    "required_headings": "必须包含的标题", "forbidden_phrases": "禁止出现的文字",
    "min_indicator_rows": "最少指标行数", "min_interface_fills": "最少接口填充数",
    "indicator_excluded_names": "不进入指标表的名称", "semantic_title": "章节语义标题",
    "evidence_roles": "有效证据分类", "indicator_signals": "有效指标证据词", "allowed_domains": "适用领域",
    "semantic_titles": "章节标题识别词", "keep_processes": "保留该章节的研制流程",
    "linked_semantic_titles": "同步删除的关联章节",
    "heading_markers": "标题识别词", "heading_exact_names": "标题精确名称",
    "reference_heading_markers": "引用标准章节识别词", "exact_aliases": "精确别名", "related_terms": "关联词",
    "red_text_count_gt": "允许的新增红字数", "highlight_count_gt": "允许的新增高亮数",
    "change_record_data_rows_gt": "允许的变更记录数据行数", "template_phrases_exist": "禁止残留的模板词",
    "as9100_table_exists": "检查不适用的 AS9100 表格", "civil_aircraft_table_exists": "检查不适用的民机表格",
    "appendix_a_empty_table_exists": "检查附录 A 空表", "indicator_table_missing": "检查技术指标表缺失",
    "indicator_table_no_basis_col": "检查指标依据列缺失", "duplicate_body_image_relationship": "检查重复图片引用",
    "figure_caption_sequence_wrong": "检查图题编号顺序", "standard_version_conflict": "提示标准版本冲突",
    "standard_sort_wrong": "提示标准排序问题", "cover_phase_empty": "提示封面阶段缺失",
    "failure_mode_table_empty": "提示故障模式表为空",
    "indicator_table_wrong_columns": "检查指标表字段与行结构", "indicator_instruction_exists": "检查新增指标模板提示语",
    "indicator_change_record_contamination": "检查指标混入变更记录", "landscape_section_exists": "检查未允许的横向页面",
    "figure_caption_orphan_auto": "检查图题附近缺失图片", "is_as9100": "使用 AS9100 质量检查范围",
    "is_civil_aircraft": "使用民机质量检查范围", "allow_landscape": "允许横向页面", "standards_heading_keywords": "标准章节标题关键词",
    "required_phrases_all": "必须包含的文字", "required_figure_captions": "必须包含的图题", "required_table_keywords": "必须包含的表格词",
}
_CATEGORY_KEYS = (
    "label", "definition", "source_heading_keywords", "source_parent_heading_keywords", "source_content_patterns",
    "atomic_source_heading_keywords", "target_heading_keywords", "target_heading_level", "target_parent_heading",
    "content_priority", "excluded_indicator_names",
)
_DOMAINS = ["military", "airworthiness", "civil_aviation", "as9100"]
_OPTION_LABELS = {
    "military": "军品", "airworthiness": "适航", "civil_aviation": "民机", "as9100": "AS9100",
    "common": "通用", "high_frequency": "高频", "optical": "光学",
}
_REGEX_KEYS = {"source_content_patterns", "extract_patterns", "value_patterns"}


def _read_yaml(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        content = path.read_bytes()
        data = yaml.safe_load(content.decode("utf-8-sig"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RuleValidationError(f"规则文件无法读取：{path.name}") from exc
    if not isinstance(data, dict):
        raise RuleValidationError(f"规则文件必须是对象：{path.name}")
    return content, data


def _revision(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _lookup(data: Any, path: list[str | int]) -> Any:
    for key in path:
        data = data[key]
    return data


class RuleEditor:
    def __init__(self, config_dir: str | Path, package_root: str | Path, history_root: str | Path):
        self.config_dir = Path(config_dir).resolve()
        self.package_root = Path(package_root).resolve()
        self.history_root = Path(history_root).resolve()

    def _registry(self) -> dict[str, dict[str, Any]]:
        rules: dict[str, dict[str, Any]] = {}

        def register(rule_id: str, path: Path, title: str, group: str, description: str, root: Path):
            resolved = path.resolve()
            if resolved.parent != root or not resolved.is_file():
                return
            rules[rule_id] = {"id": rule_id, "title": title, "group": group, "description": description, "path": resolved}

        for rule_id, title in _CATEGORY_FILES.items():
            register(rule_id, self.config_dir / f"{rule_id}.yaml", title, "语义分类", "设置来源语义分类与目标标题匹配，不依赖章节编号。", self.config_dir)
        for rule_id, (title, group, description) in _POLICY_FILES.items():
            register(rule_id, self.config_dir / f"{rule_id}.yaml", title, group, description, self.config_dir)
        catalog_path = self.config_dir / "template_catalog.yaml"
        if catalog_path.is_file():
            _, catalog = _read_yaml(catalog_path)
            for product in (catalog.get("product_types") or {}).values():
                if not isinstance(product, dict) or not product.get("enabled"):
                    continue
                for domain in (product.get("domains") or {}).values():
                    profile = domain.get("profile", "") if isinstance(domain, dict) else ""
                    if not isinstance(profile, str) or not re.fullmatch(r"[a-zA-Z0-9_]+_profile\.yaml", profile):
                        continue
                    register(Path(profile).stem, self.package_root / profile,
                             f"{product.get('label', Path(profile).stem)}指标规则", "产品指标",
                             "设置产品指标识别词、交付门槛与专属质量要求。", self.package_root)
        return rules

    def _entry(self, rule_id: str) -> dict[str, Any]:
        entry = self._registry().get(rule_id) if isinstance(rule_id, str) else None
        if entry is None:
            raise RuleNotFoundError("未找到该规则，或该文件不在可编辑范围内")
        return entry

    def _role_labels(self) -> dict[str, str]:
        roles: dict[str, str] = {}
        for rule_id in _CATEGORY_FILES:
            path = self.config_dir / f"{rule_id}.yaml"
            if path.is_file():
                _, data = _read_yaml(path)
                for group in ("categories", "semantic_roles"):
                    for key, item in (data.get(group) or {}).items():
                        roles.setdefault(key, str(item.get("label") or key))
        return roles

    def _fields(self, rule_id: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []

        def add(path: list[str | int], section: str, *, label: str = "", options: list[str] | None = None, option_labels: dict[str, str] | None = None):
            try:
                value = _lookup(data, path)
            except (KeyError, IndexError, TypeError):
                return
            kind = ("boolean" if isinstance(value, bool) else "number" if isinstance(value, (int, float))
                    else "string" if isinstance(value, str) else "string_list" if isinstance(value, list) and all(isinstance(v, str) for v in value) else "")
            if not kind:
                return
            field = {"path": path, "label": label or _LABELS.get(str(path[-1]), str(path[-1])), "section": section, "type": "enum" if options and kind == "string" else kind}
            if options is not None:
                field["options"] = options
                labels = {**_OPTION_LABELS, **(option_labels or {})}
                field["option_labels"] = {option: labels.get(option, option) for option in options}
            if path[-1] in _REGEX_KEYS:
                field["description"] = "每行一个正则表达式，保存前会检查语法；只用于匹配上传的来源文本。"
            if path[-1] == "related_kws":
                field["description"] = "关联词用于识别近义指标，不等同于可互换的精确别名。"
            if path[-1] == "keep_processes":
                field["description"] = "勾选的流程保留模板章节；未勾选的流程删除该章节及关联章节。"
            if path[-1] == "linked_semantic_titles":
                field["description"] = "删除主章节时同步删除这些章节及其正文、表格；保留主章节时一并保留。"
            fields.append(field)

        if rule_id in _CATEGORY_FILES or rule_id == "taskbook_requirement_taxonomy":
            for group in ("semantic_roles", "categories"):
                for role, item in (data.get(group) or {}).items():
                    for key in _CATEGORY_KEYS:
                        add([group, role, key], str(item.get("label") or role))
            if rule_id in _CATEGORY_FILES:
                roles = sorted(data.get("categories") or {})
                role_labels = {key: str(item.get("label") or key) for key, item in (data.get("categories") or {}).items()}
                for key in ("min_text_length", "max_fragments_per_block", "source_categories", "target_categories"):
                    add(["exact_fragment_routing", key], "原文片段细分", options=roles if key.endswith("categories") else None, option_labels=role_labels)
                for i, item in enumerate(data.get("evidence_projections") or []):
                    section = f"跨分类证据 · {item.get('source_category', '')} → {item.get('target_category', '')}"
                    for key in ("match_any", "extract_patterns"):
                        add(["evidence_projections", i, key], section)
        elif rule_id.endswith("_profile"):
            for group, items in (data.get("indicator_map") or {}).items():
                for i, item in enumerate(items):
                    for key in ("tech_kws", "std_kws", "related_kws", "spec_exact_names", "value_patterns"):
                        add(["indicator_map", group, i, key], f"{group} · {item.get('name', '')}")
            for key in ("min_indicator_rows", "min_interface_fills", "required_headings"):
                add(["delivery_gate", key], "交付门槛")
            for key in ("required_headings", "forbidden_phrases", "required_phrases_all", "required_figure_captions", "required_table_keywords", "standards_heading_keywords", "is_as9100", "is_civil_aircraft", "allow_landscape"):
                add(["qa_profile", key], "产品质量要求")
            add(["indicator_excluded_names"], "指标排除规则")
            catalog_path = self.config_dir / "connector_indicator_catalog.yaml"
            families = []
            if catalog_path.is_file():
                _, catalog = _read_yaml(catalog_path)
                families = [name for name in ("common", "high_frequency", "optical") if isinstance(catalog.get(name), dict)]
            add(["indicator_sources", "reference_families"], "引用的通用指标词表", options=families)
            for i, _ in enumerate(data.get("std_sort_order") or []):
                add(["std_sort_order", i], "标准排序", label=f"第 {i + 1} 优先级标准前缀")
        elif rule_id == "development_process_policy":
            for i, item in enumerate(data.get("section_retention_rules") or []):
                for key in ("semantic_titles", "keep_processes", "linked_semantic_titles"):
                    add(
                        ["section_retention_rules", i, key],
                        f"章节保留 · {item.get('label') or item.get('id')}",
                        options=list(data.get("canonical_processes") or []) if key == "keep_processes" else None,
                    )
            for alias in (data.get("aliases") or {}):
                add(["aliases", alias], "研制流程别名", label=f"{alias} 归一化为", options=list(data.get("canonical_processes") or []))
            role_labels = self._role_labels()
            roles = sorted(role_labels)
            add(["quality_section_parent_titles"], "六性章节范围", label="六性共同父章节标题")
            add(["failure_mode_section_titles"], "失效分析章节", label="失效模式章节标题及别名")
            for i, item in enumerate(data.get("quality_section_evidence") or []):
                for key in ("semantic_title", "semantic_aliases", "evidence_roles", "leaf_evidence_roles", "indicator_signals"):
                    add(["quality_section_evidence", i, key], str(item.get("semantic_title") or item.get("id")),
                        label={"semantic_aliases": "章节标题别名", "leaf_evidence_roles": "子分类保留证据"}.get(key, ""),
                        options=roles if key in {"evidence_roles", "leaf_evidence_roles"} else None,
                        option_labels=role_labels)
        elif rule_id == "standard_applicability":
            for key in ("prefix_allowed_domains", "marker_allowed_domains", "marker_excluded_domains"):
                for marker in (data.get(key) or {}):
                    add([key, marker], "标准与标记领域", label=f"{marker} {'排除' if key == 'marker_excluded_domains' else '适用'}领域", options=_DOMAINS)
            for alias in (data.get("domain_aliases") or {}):
                add(["domain_aliases", alias], "领域别名", label=f"{alias} 对应领域", options=_DOMAINS)
            add(["reference_heading_markers"], "引用标准章节")
            for i, item in enumerate(data.get("domain_section_rules") or []):
                for key in ("heading_markers", "allowed_domains"):
                    add(["domain_section_rules", i, key], f"领域章节 · {item.get('id', '')}", options=_DOMAINS if key == "allowed_domains" else None)
            for marker in (data.get("condition_marker_evidence") or {}):
                add(["condition_marker_evidence", marker], "条件性标准证据", label=marker)
        elif rule_id == "failure_mode_policy":
            add(["no_applicable_record", "text"], "未匹配到历史记录", label="无历史故障时的说明文字")
        elif rule_id == "qa_gate":
            for key in ("red_text_count_gt", "highlight_count_gt", "change_record_data_rows_gt", "template_phrases_exist", "as9100_table_exists", "civil_aircraft_table_exists", "appendix_a_empty_table_exists", "indicator_table_missing", "indicator_table_no_basis_col", "figure_caption_sequence_wrong", "duplicate_body_image_relationship", "indicator_table_wrong_columns", "indicator_instruction_exists", "indicator_change_record_contamination", "landscape_section_exists", "figure_caption_orphan_auto"):
                add(["block_if", key], "阻断交付检查")
            for key in ("standard_version_conflict", "standard_sort_wrong", "cover_phase_empty", "failure_mode_table_empty"):
                add(["warn_if", key], "人工复核提示")
        elif rule_id in {"template_variant_policy", "single_budget_template_variant_policy"}:
            for i, group in enumerate(data.get("mutually_exclusive_groups") or []):
                for variant in (group.get("variants") or {}):
                    for key in ("heading_markers", "heading_exact_names"):
                        add(["mutually_exclusive_groups", i, "variants", variant, key], f"模板分支 · {variant}")
        elif rule_id == "connector_indicator_catalog":
            for family in ("common", "high_frequency", "optical"):
                for group, items in (data.get(family) or {}).items():
                    for i, item in enumerate(items):
                        if not str(item.get("target_role", "")).startswith("performance_indicator."):
                            continue
                        add([family, group, i, "exact_aliases"], f"{family} · {item.get('name', '')}")
        return fields

    @staticmethod
    def _validate_value(field: dict[str, Any], value: Any) -> Any:
        label, kind, path = field["label"], field["type"], field["path"]
        key = path[-1]
        if kind in {"string", "enum"}:
            if not isinstance(value, str) or not value.strip() or len(value) > 4000:
                raise RuleValidationError(f"{label}：请输入 1 到 4000 字的非空文本")
            value = value.strip()
        elif kind == "boolean":
            if type(value) is not bool:
                raise RuleValidationError(f"{label}：必须为布尔值")
        elif kind == "number":
            lower, upper = {"target_heading_level": (1, 9), "min_text_length": (8, 10000), "max_fragments_per_block": (2, 100)}.get(key, (0, 10000))
            if type(value) is not int or not lower <= value <= upper:
                raise RuleValidationError(f"{label}：必须为 {lower} 到 {upper} 的整数")
        elif kind == "string_list":
            if not isinstance(value, list) or len(value) > 300 or any(not isinstance(item, str) or not item.strip() or len(item) > 2000 for item in value):
                raise RuleValidationError(f"{label}：必须是至多 300 项的非空文本列表，每项至多 2000 字")
            value = [item.strip() for item in value]
            if len(value) != len(set(value)):
                raise RuleValidationError(f"{label}：列表中存在重复值")
            if key in {"source_categories", "target_categories", "target_heading_keywords", "heading_markers", "heading_exact_names", "tech_kws", "std_kws", "allowed_domains"} and not value:
                raise RuleValidationError(f"{label}：至少保留一项")
            if key == "target_categories" and len(value) < 2:
                raise RuleValidationError(f"{label}：至少保留两项，原文片段细分需要两个或以上目标分类")
        if "options" in field:
            selections = value if isinstance(value, list) else [value]
            if any(item not in field["options"] for item in selections):
                raise RuleValidationError(f"{label}：包含未登记的引用，可选值为 {'、'.join(field['options'])}")
        if key in _REGEX_KEYS:
            for pattern in value:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise RuleValidationError(f"{label}：正则表达式语法错误：{exc}") from exc
        return value

    def _candidate(self, rule_id: str, changes: Any, expected_revision: str | None) -> tuple[dict[str, Any], bytes, dict[str, Any], list[dict[str, Any]]]:
        entry = self._entry(rule_id)
        content, data = _read_yaml(entry["path"])
        if expected_revision is not None and expected_revision != _revision(content):
            raise RuleConflictError("规则已被其他操作更新，请刷新当前规则后重新修改")
        if not isinstance(changes, list) or not changes or len(changes) > 2000:
            raise RuleValidationError("请提交 1 到 2000 项字段修改")
        fields = {tuple(field["path"]): field for field in self._fields(rule_id, data)}
        candidate = copy.deepcopy(data)
        differences: list[dict[str, Any]] = []
        seen: set[tuple[str | int, ...]] = set()
        for change in changes:
            if not isinstance(change, dict) or set(change) != {"path", "value"}:
                raise RuleValidationError("每项修改必须且只能包含 path 和 value")
            path = change["path"]
            if not isinstance(path, list) or not path or any(type(part) not in (str, int) for part in path):
                raise RuleValidationError("字段路径必须是文字或整数的列表")
            address = tuple(path)
            field = fields.get(address)
            if field is None:
                raise RuleValidationError(f"字段 {' / '.join(map(str, path))} 不允许编辑")
            if address in seen:
                raise RuleValidationError(f"{field['label']}：同一字段不能重复提交")
            seen.add(address)
            value = self._validate_value(field, change["value"])
            before = _lookup(data, path)
            _lookup(candidate, path[:-1])[path[-1]] = value
            if before != value:
                differences.append({"path": path, "label": field["label"], "before": before, "after": value, "value": value})
        if rule_id.endswith("_profile"):
            try:
                validate_indicator_profile(candidate, source=entry["title"])
            except ValueError as exc:
                raise RuleValidationError(str(exc)) from exc
        if rule_id == "connector_indicator_catalog":
            indicator_map = {}
            for family in ("common", "high_frequency", "optical"):
                for group, items in (candidate.get(family) or {}).items():
                    indicator_map[f"{family}/{group}"] = [
                        {"name": item["name"], "tech_kws": item.get("exact_aliases", []), "related_kws": item.get("related_terms", [])}
                        for item in items
                        if str(item.get("target_role", "")).startswith("performance_indicator.")
                    ]
            try:
                validate_indicator_profile({"indicator_map": indicator_map}, source=entry["title"])
            except ValueError as exc:
                raise RuleValidationError(str(exc)) from exc
        if rule_id == "development_process_policy":
            from .development_process_policy import validate_section_retention_rules

            try:
                validate_section_retention_rules(candidate)
            except ValueError as exc:
                raise RuleValidationError(str(exc)) from exc
            for item in candidate.get("quality_section_evidence") or []:
                if not item.get("evidence_roles") and not item.get("leaf_evidence_roles") and not item.get("indicator_signals"):
                    raise RuleValidationError(f"{item.get('semantic_title', '六性章节')}：证据分类和证据词不能同时为空")
        if rule_id in {"template_variant_policy", "single_budget_template_variant_policy"}:
            for group in candidate.get("mutually_exclusive_groups") or []:
                signatures = set()
                for item in (group.get("variants") or {}).values():
                    key = "heading_exact_names" if item.get("heading_exact_names") else "heading_markers"
                    signature = (key, tuple(sorted(re.sub(r"\s+", "", text).rstrip("：:") for text in item.get(key, []))))
                    if signature in signatures:
                        raise RuleValidationError("模板分支：不同分支不能使用相同的标题识别条件")
                    signatures.add(signature)
        if not differences:
            raise RuleValidationError("没有实际变更，请先修改规则字段")
        return entry, content, candidate, differences

    def list_rules(self) -> dict[str, Any]:
        with _LOCK:
            items = []
            for entry in self._registry().values():
                content, data = _read_yaml(entry["path"])
                item = {key: value for key, value in entry.items() if key != "path"}
                item.update(revision=_revision(content), updated_at=datetime.fromtimestamp(entry["path"].stat().st_mtime, timezone.utc).isoformat(), field_count=len(self._fields(entry["id"], data)))
                items.append(item)
            return {"items": items}

    def get_rule(self, rule_id: str) -> dict[str, Any]:
        with _LOCK:
            entry = self._entry(rule_id)
            content, data = _read_yaml(entry["path"])
            detail = {key: value for key, value in entry.items() if key != "path"}
            detail.update(revision=_revision(content), updated_at=datetime.fromtimestamp(entry["path"].stat().st_mtime, timezone.utc).isoformat(), data=data, fields=self._fields(rule_id, data), history=self.list_history(rule_id))
            return detail

    def validate_changes(self, rule_id: str, changes: Any, expected_revision: str | None = None) -> dict[str, Any]:
        with _LOCK:
            _, content, _, differences = self._candidate(rule_id, changes, expected_revision)
            return {"valid": True, "revision": _revision(content), "changes": differences}

    def _history_dir(self, rule_id: str) -> Path:
        self._entry(rule_id)
        path = (self.history_root / rule_id).resolve()
        if path.parent != self.history_root:
            raise RuleNotFoundError("规则历史目录不可用")
        return path

    def list_history(self, rule_id: str) -> list[dict[str, Any]]:
        with _LOCK:
            entry = self._entry(rule_id)
            current = _revision(entry["path"].read_bytes())
            history_path = self._history_dir(rule_id) / "history.json"
            records = json.loads(history_path.read_text(encoding="utf-8")) if history_path.is_file() else []
            result = []
            current_found = False
            for record in reversed(records):
                item = dict(record)
                item["is_current"] = not current_found and item["revision"] == current
                current_found |= item["is_current"]
                result.append(item)
            return result

    def _save(self, entry: dict[str, Any], before: bytes, after: bytes, note: str, actor: str, *, restored_from: str = "") -> dict[str, Any]:
        if not isinstance(note, str) or len(note) > 1000 or not isinstance(actor, str) or not actor.strip() or len(actor) > 100:
            raise RuleValidationError("变更说明至多 1000 字，操作者必须为 1 到 100 字的文本")
        history_dir = self._history_dir(entry["id"])
        history_path = history_dir / "history.json"
        records = json.loads(history_path.read_text(encoding="utf-8")) if history_path.is_file() else []
        before_revision, after_revision = _revision(before), _revision(after)
        now = datetime.now(timezone.utc).isoformat()
        if not any(record["revision"] == before_revision for record in records):
            records.append({"revision": before_revision, "created_at": now, "note": "修改前版本", "actor": actor, "event_id": uuid.uuid4().hex})
        record = {"revision": after_revision, "created_at": now, "note": note.strip(), "actor": actor.strip(), "event_id": uuid.uuid4().hex}
        if restored_from:
            record["restored_from"] = restored_from
        records.append(record)
        _atomic_write(history_dir / f"{before_revision}.yaml", before)
        _atomic_write(history_dir / f"{after_revision}.yaml", after)
        _atomic_write(entry["path"], after)
        try:
            _atomic_write(history_path, json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8"))
        except OSError:
            _atomic_write(entry["path"], before)
            raise
        return self.get_rule(entry["id"])

    def save_rule(self, rule_id: str, changes: Any, expected_revision: str, note: str = "", actor: str = "web-user") -> dict[str, Any]:
        if not isinstance(expected_revision, str) or not expected_revision:
            raise RuleValidationError("保存规则必须提供当前版本号")
        with _LOCK:
            entry, before, candidate, _ = self._candidate(rule_id, changes, expected_revision)
            after = yaml.safe_dump(candidate, allow_unicode=True, sort_keys=False, width=1000).encode("utf-8")
            return self._save(entry, before, after, note, actor)

    def restore_rule(self, rule_id: str, revision: str, expected_revision: str, note: str = "", actor: str = "web-user") -> dict[str, Any]:
        if not isinstance(expected_revision, str) or not expected_revision:
            raise RuleValidationError("恢复规则必须提供当前版本号")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{64}", revision):
            raise RuleNotFoundError("未找到该历史版本")
        with _LOCK:
            entry = self._entry(rule_id)
            before, current = _read_yaml(entry["path"])
            if expected_revision != _revision(before):
                raise RuleConflictError("规则已被其他操作更新，请刷新当前规则后再恢复")
            if revision == expected_revision:
                raise RuleValidationError("该版本已是当前版本")
            if not any(item["revision"] == revision for item in self.list_history(rule_id)):
                raise RuleNotFoundError("未找到该历史版本")
            after, target = _read_yaml(self._history_dir(rule_id) / f"{revision}.yaml")
            if _revision(after) != revision:
                raise RuleValidationError("历史版本内容校验失败，不能恢复")
            changes = []
            for field in self._fields(rule_id, current):
                path = field["path"]
                try:
                    old, new = _lookup(current, path), _lookup(target, path)
                except (KeyError, IndexError, TypeError) as exc:
                    raise RuleValidationError("历史版本结构已不兼容，不能恢复") from exc
                if old != new:
                    changes.append({"path": path, "value": new})
            if not changes:
                raise RuleValidationError("历史版本没有可恢复的业务字段变更")
            _, _, candidate, _ = self._candidate(rule_id, changes, expected_revision)
            if candidate != target:
                raise RuleValidationError("历史版本包含当前不允许编辑的结构变化，不能恢复")
            return self._save(entry, before, after, note or "恢复历史版本", actor, restored_from=revision)
