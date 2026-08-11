# -*- coding: utf-8 -*-
"""加载入口已经选择的受控产品 Profile。

产品类型和领域只能来自受控目录。生产链不再根据上传正文关键词猜产品，
避免任意新文件被静默套用某个历史样例配置。
"""
from __future__ import annotations
from pathlib import Path

from .indicator_profile_validator import validate_indicator_profile


def load_profile(
    tech_path: str,
    profiles_dir: str | None = None,
    explicit_profile: str | None = None,
    tech_paras=None,
    spec_paras=None,
) -> tuple[dict, str, str]:
    """加载入口已选中的受控 Profile；不自动猜测、不回退默认配置。"""
    import yaml

    profiles_dir = Path(profiles_dir or Path(__file__).parent)

    if explicit_profile and Path(explicit_profile).exists():
        with open(explicit_profile, encoding="utf-8") as f:
            profile = yaml.safe_load(f) or {}
        validate_indicator_profile(profile, source=str(explicit_profile))
        return profile, explicit_profile, "用户指定"
    if explicit_profile:
        raise FileNotFoundError(f"受控 Profile 不存在: {explicit_profile}")
    raise ValueError("未提供受控 Profile；请先选择产品类型和领域")
