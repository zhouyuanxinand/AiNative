from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Any

import yaml

from .indicator_profile_validator import validate_indicator_profile


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = PROJECT_ROOT / "config" / "template_catalog.yaml"
TEMPLATE_ROOT = Path(__file__).resolve().parent / "resources" / "templates"
PROFILE_ROOT = Path(__file__).resolve().parent
MAPPING_ROOT = PROJECT_ROOT / "config"


def _truthy_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _catalog_path_from_env(catalog_path: str | Path | None = None) -> Path:
    if catalog_path is not None:
        return Path(catalog_path)
    override = os.getenv("JTB_TEMPLATE_CATALOG_PATH", "").strip()
    return Path(override) if override else CATALOG_PATH


def _allow_disabled_product_types() -> bool:
    return _truthy_env("JTB_CATALOG_ALLOW_DISABLED", default=False)


@dataclass(frozen=True)
class TemplateSelection:
    product_type: str
    product_type_label: str
    product_domain: str
    product_domain_label: str
    template_path: str
    profile_path: str | None
    category_mapping_path: str
    preserve_unfilled_template: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_catalog(catalog_path: str | Path = CATALOG_PATH) -> dict[str, Any]:
    path = _catalog_path_from_env(catalog_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"模板目录配置不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("product_types"), dict):
        raise ValueError("模板目录配置缺少 product_types")
    return data


def _resolve_controlled(root: Path, relative: str, kind: str) -> Path:
    if not relative:
        raise ValueError(f"{kind}路径为空")
    root = root.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{kind}路径越出受控目录: {relative}") from exc
    if not resolved.exists():
        raise FileNotFoundError(f"{kind}不存在: {resolved}")
    return resolved


def list_product_catalog(catalog_path: str | Path = CATALOG_PATH) -> list[dict[str, Any]]:
    catalog = _load_catalog(catalog_path)
    allow_disabled = _allow_disabled_product_types()
    result: list[dict[str, Any]] = []
    for type_key, type_cfg in catalog["product_types"].items():
        domains = []
        for domain_key, domain_cfg in (type_cfg.get("domains") or {}).items():
            domains.append({"value": domain_key, "label": domain_cfg.get("label", domain_key)})
        configured_enabled = bool(type_cfg.get("enabled", True))
        effective_enabled = configured_enabled or allow_disabled
        result.append(
            {
                "value": type_key,
                "label": type_cfg.get("label", type_key),
                "enabled": effective_enabled,
                "configured_enabled": configured_enabled,
                "template_label": str(type_cfg.get("template_label", "")),
                "unavailable_reason": str(type_cfg.get("unavailable_reason", "")),
                "domains": domains,
            }
        )
    return result


def resolve_template_selection(
    product_type: str,
    product_domain: str,
    catalog_path: str | Path = CATALOG_PATH,
) -> TemplateSelection:
    catalog = _load_catalog(catalog_path)
    alias_key = f"{product_type}/{product_domain}"
    alias_value = (catalog.get("aliases") or {}).get(alias_key)
    if alias_value:
        product_type, product_domain = str(alias_value).split("/", 1)
    type_cfg = catalog["product_types"].get(product_type)
    if not isinstance(type_cfg, dict):
        raise ValueError(f"不支持的产品类型: {product_type}")
    if not bool(type_cfg.get("enabled", True)) and not _allow_disabled_product_types():
        reason = str(type_cfg.get("unavailable_reason", "模板尚未配置"))
        raise ValueError(f"产品类型 {type_cfg.get('label', product_type)} 暂不可用: {reason}")
    domain_cfg = (type_cfg.get("domains") or {}).get(product_domain)
    if not isinstance(domain_cfg, dict):
        raise ValueError(f"产品类型 {product_type} 不支持领域 {product_domain}")

    template_path = _resolve_controlled(
        TEMPLATE_ROOT, str(domain_cfg.get("template", "")), "内置模板"
    )
    mapping_path = _resolve_controlled(
        MAPPING_ROOT, str(domain_cfg.get("category_mapping", "")), "语义分类映射"
    )
    profile_value = str(domain_cfg.get("profile", "")).strip()
    if not profile_value:
        raise ValueError(
            f"产品类型 {type_cfg.get('label', product_type)} / "
            f"{domain_cfg.get('label', product_domain)} 未配置受控产品 Profile"
        )
    resolved_profile = _resolve_controlled(PROFILE_ROOT, profile_value, "产品配置")
    profile_data = yaml.safe_load(resolved_profile.read_text(encoding="utf-8")) or {}
    if not isinstance(profile_data, dict):
        raise ValueError(f"产品配置必须是 YAML 对象: {resolved_profile}")
    validate_indicator_profile(profile_data, source=str(resolved_profile))
    profile_path = str(resolved_profile)

    return TemplateSelection(
        product_type=product_type,
        product_type_label=str(type_cfg.get("label", product_type)),
        product_domain=product_domain,
        product_domain_label=str(domain_cfg.get("label", product_domain)),
        template_path=str(template_path),
        profile_path=profile_path,
        category_mapping_path=str(mapping_path),
        preserve_unfilled_template=bool(domain_cfg.get("preserve_unfilled_template", True)),
    )
