"""Shared, product-neutral identities for governed technical indicators."""
from __future__ import annotations

import re


def canonical_indicator_name(name: str) -> str:
    """Normalize configured, source and template aliases to one identity."""
    value = re.sub(r"[\s：:（）()]+", "", str(name or ""))
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
        (("环境温度", "工作温度"), "工作温度"),
        (("机械寿命", "插拔寿命"), "机械寿命"),
        (("灵巧指按压力", "按钮按压力", "按压力", "承压力"), "按压力"),
    )
    for candidates, canonical in aliases:
        if any(candidate in value for candidate in candidates):
            return canonical
    return value
