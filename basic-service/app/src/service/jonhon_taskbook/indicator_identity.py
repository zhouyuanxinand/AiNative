"""Shared, product-neutral identities for governed technical indicators."""
from __future__ import annotations

import re


def indicator_display_value(text: str, name: str, aliases=()) -> str:
    """Remove only a redundant leading row label; keep the technical payload.

    Units and state qualifiers in a label are not silently discarded. Source
    evidence stays unchanged; this projection is shared by rendering and QA.
    """
    def key(label):
        return re.sub(r"\s+", "", str(label or "")).rstrip("※")

    primary = key(name)
    qualified = re.compile(r"初始|初期|终值|末期|试验前|试验后|测试前|测试后|常温|高温|低温|通电前|通电后")
    labels = {
        key(label) for label in [name, *aliases]
        if re.fullmatch(r"[\u4e00-\u9fffA-Za-z]+", key(label))
        and not (set(qualified.findall(key(label))) - set(qualified.findall(primary)))
    }
    prefix = re.compile(
        r"^\s*(?:(?:[（(]\d+[）)]|\d+(?:\.\d+)*[.、）)]?)\s*)?"
        r"(?P<label>[^：:\n]{1,80})[：:]\s*(?P<value>\S.*)$"
    )
    lines = []
    for line in str(text or "").split("\n"):
        match = prefix.match(line)
        lines.append(match.group("value") if match and key(match.group("label")) in labels else line)
    return "\n".join(lines)


def canonical_indicator_name(name: str) -> str:
    """Normalize configured, source and template aliases to one identity."""
    # The controlled templates mark existing rows with a trailing footnote.
    # Ignore only that annotation for identity; callers keep the display name.
    value = re.sub(r"(?:\s*※)+\s*$", "", str(name or ""))
    value = re.sub(r"[\s：:（）()]+", "", value)
    aliases = (
        (("额定电流", "额定载流量"), "额定电流"),
        (("冲击电流", "脉冲电流"), "冲击电流"),
        (("其他接点总载流", "其他接点总电流"), "其他接点总载流"),
        (("介质耐电压", "耐电压"), "介质耐电压"),
        # “插入力/分离力/分离扭矩”可能分别描述单针、接触件或整机，
        # 不能仅凭词面统一并入“插拔力”。是否合并必须由本次来源证据和
        # 受控指标定义决定。
        (("插拔力", "总插拔力", "插合分离力"), "插拔力"),
        # V3 底层表单与受控模板的显示名不同，但它们指向同一模板槽位。
        (("总分离力或分离扭矩", "总分离力"), "总分离力或分离扭矩"),
        (("低温低气压", "低气压"), "低温低气压"),
        # Customer thermal templates contain both ambient and working
        # temperature as independent rows. Profiles may still explicitly use
        # one as a source alias; table identities must preserve both names.
        (("机械寿命", "插拔寿命"), "机械寿命"),
        (("灵巧指按压力", "按钮按压力", "按压力", "承压力"), "按压力"),
    )
    for candidates, canonical in aliases:
        if any(candidate in value for candidate in candidates):
            return canonical
    return value
