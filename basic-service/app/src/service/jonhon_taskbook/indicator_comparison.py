"""Compare complete guaranteed bounds without inventing a combined requirement.

Workbook 7-22, development logic C51 and Sheet1 C4 require guaranteed min/max
values to decide strictness. A typical value is reference information only.
This module intentionally does not infer an indicator's direction from its name
or decide which product variant or test condition applies.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, localcontext


@dataclass(frozen=True)
class IndicatorComparison:
    """The selected source text and whether a human must resolve comparison."""

    adopted: str
    audit_note: str
    manual_review_required: bool
    status: str


@dataclass(frozen=True)
class _Bound:
    value: Decimal
    inclusive: bool


@dataclass(frozen=True)
class _Requirement:
    dimension: str
    lower: _Bound | None
    upper: _Bound | None
    context: str
    scalar: bool = False


# Prefixes remain case sensitive: mOhm and MOhm cannot share a normalized key.
# Use only explicit, dimensionally defined conversions; unknown units require
# review instead of treating their numbers as unitless values.
_UNITS: dict[str, tuple[str, str, str]] = {"": ("unitless", "1", "0")}
for _symbol, _dimension in (
    ("Ω", "resistance"), ("V", "voltage"), ("A", "current"),
    ("Hz", "frequency"), ("Pa", "pressure"), ("N", "force"),
    ("F", "capacitance"), ("H", "inductance"),
):
    for _prefix, _factor in (("", "1"), ("p", "0.000000000001"), ("n", "0.000000001"),
                             ("m", "0.001"), ("μ", "0.000001"),
                             ("u", "0.000001"), ("k", "1000"),
                             ("M", "1000000"), ("G", "1000000000")):
        _UNITS[_prefix + _symbol] = (_dimension, _factor, "0")

for _dimension, _unit_factors in {
    "length": {"m": "1", "cm": "0.01", "mm": "0.001", "μm": "0.000001", "um": "0.000001"},
    "mass": {"kg": "1"},
    "time": {"s": "1", "秒": "1", "ms": "0.001", "μs": "0.000001", "us": "0.000001",
             "min": "60", "分钟": "60", "h": "3600", "小时": "3600"},
    "cycles": {"次": "1"},
    "percentage": {"%": "1"},
    "angle": {"°": "1"},
    "volume": {"L": "1", "mL": "0.001", "m3": "1000"},
    "flow": {"L/min": "1", "mL/min": "0.001", "m3/min": "1000"},
    "torque": {"N·m": "1", "N*m": "1", "N·mm": "0.001"},
}.items():
    for _unit, _factor in _unit_factors.items():
        _UNITS[_unit] = (_dimension, _factor, "0")
_UNITS.update({
    "°C": ("temperature", "1", "0"),
    "K": ("temperature", "1", "-273.15"),
    "bar": ("pressure", "100000", "0"),
    "mbar": ("pressure", "100", "0"),
    # In these documents g/mg can denote mass or acceleration. Comparing the
    # same symbol is safe; converting it to kg without indicator context is not.
    "g": ("ambiguous_g", "1", "0"),
    "mg": ("ambiguous_mg", "1", "0"),
})

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_UNIT = "(?:" + "|".join(re.escape(unit) for unit in sorted(_UNITS, key=len, reverse=True) if unit) + ")"
_TYP_MARKER = r"(?<![A-Za-z])(?:(?i:typ(?:ical)?)|典型(?:值)?|参考值)"
_TYPICAL = re.compile(
    rf"{_TYP_MARKER}\s*(?:值)?\s*[:=]?\s*(?:[<>]=?|[≤≥])?\s*{_NUMBER}\s*(?:{_UNIT})?"
)
_TYP_MARKER_RE = re.compile(_TYP_MARKER)
_LABEL = r"(?:(?i:minimum|maximum|min|max)|最小(?:值)?|最大(?:值)?)"
_LOWER_INCLUSIVE = {"≥", ">=", "不小于", "不少于", "不低于", "大于等于", "至少"}
_UPPER_INCLUSIVE = {"≤", "<=", "不大于", "不超过", "不高于", "小于等于", "至多"}
_LOWER_EXCLUSIVE = {">", "大于"}
_UPPER_EXCLUSIVE = {"<", "小于"}
_OPERATORS = sorted(_LOWER_INCLUSIVE | _UPPER_INCLUSIVE | _LOWER_EXCLUSIVE | _UPPER_EXCLUSIVE, key=len, reverse=True)
_TOKEN = re.compile(
    rf"(?<![A-Za-z0-9_.])(?P<label>{_LABEL})?\s*[:=]?\s*"
    rf"(?P<op>{'|'.join(re.escape(op) for op in _OPERATORS)})?\s*"
    rf"(?P<number>{_NUMBER})\s*(?P<unit>{_UNIT})?"
)
_ACCEPTANCE_RANGE = re.compile(
    rf"^\s*(?:验收区间|验收范围|允许测量值范围|测量值范围)\s*:?\s*"
    rf"(?P<lower>{_NUMBER})\s*(?P<lower_unit>{_UNIT})?\s*[~至到]\s*"
    rf"(?P<upper>{_NUMBER})\s*(?P<upper_unit>{_UNIT})?\s*$"
)


def _normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("−", "-")


def _context(text: str) -> str:
    text = re.sub(r"(?:并且|且|(?i:\band\b))", "", text)
    return re.sub(r"[\s,;、。:()\[\]{}]+", "", text)


def _without_typical(text: str) -> tuple[str, bool]:
    normalized = _normalized(text)
    return _TYPICAL.sub("", normalized), bool(_TYP_MARKER_RE.search(normalized))


def _parse(text: str) -> tuple[_Requirement | None, str]:
    text, has_typical = _without_typical(text)
    if _TYP_MARKER_RE.search(text):
        return None, "typ 参考信息无法完整分离"
    if not _context(text):
        return None, "只有 typ 参考值，缺少 min/max 保证值" if has_typical else "没有可比较指标"
    if re.search(r"或|(?i:\bor\b)", text):
        return None, "含多个可选条件，不能合并为单一验收区间"
    explicit_range = _ACCEPTANCE_RANGE.fullmatch(text)
    if explicit_range:
        lower_unit = explicit_range.group("lower_unit") or explicit_range.group("upper_unit") or ""
        upper_unit = explicit_range.group("upper_unit") or lower_unit
        text = (
            f"≥{explicit_range.group('lower')}{lower_unit}且"
            f"≤{explicit_range.group('upper')}{upper_unit}"
        )
    tokens = list(_TOKEN.finditer(text))
    if not tokens or len(tokens) > 2:
        return None, "缺少明确边界，或包含多组定量要求"
    # All numeric text must belong to a recognized bound. A later duration,
    # temperature, amplitude, or nominal value must not disappear behind the
    # first threshold match.
    fragments = []
    cursor = 0
    for token in tokens:
        fragments.append(text[cursor:token.start()])
        cursor = token.end()
    fragments.append(text[cursor:])
    if any(re.search(r"\d|[<>≤≥=~～±]", fragment) for fragment in fragments):
        return None, "存在未解析的定量条件或区间"
    if len(tokens) == 2 and _context(fragments[1]):
        return None, "多个指标或测试条件不能按首个阈值裁决"

    lower = upper = None
    dimension = None
    scalar = False
    for index, token in enumerate(tokens):
        label = (token.group("label") or "").lower()
        op = token.group("op") or ""
        unit = token.group("unit") or ""
        # Prevent partial-unit parsing, such as treating 5mohm as 5m or 5AWG as
        # 5A. A unitless bound also cannot silently consume an unknown unit.
        suffix = fragments[index + 1]
        if suffix and suffix[0].isalpha() and (not unit or suffix[0].isascii()):
            return None, "单位未被明确识别"
        if re.match(r"\s*[/·*^]", suffix):
            return None, "复合单位未被明确识别"
        current_dimension, scale, offset = _UNITS[unit]
        if dimension is not None and current_dimension != dimension:
            return None, "同一表达式包含不同量纲"
        dimension = current_dimension
        number = token.group("number")
        with localcontext() as context:
            context.prec = max(50, len(number) + 20)
            value = Decimal(number) * Decimal(scale) + Decimal(offset)
        is_min = label in {"min", "minimum", "最小", "最小值"}
        is_max = label in {"max", "maximum", "最大", "最大值"}
        is_lower = op in _LOWER_INCLUSIVE | _LOWER_EXCLUSIVE
        is_upper = op in _UPPER_INCLUSIVE | _UPPER_EXCLUSIVE
        if (is_min and is_upper) or (is_max and is_lower):
            return None, "min/max 标签与比较方向矛盾"
        if is_lower or (is_min and not op):
            if lower is not None:
                return None, "包含多个下限，需按条件分别确认"
            lower = _Bound(value, op not in _LOWER_EXCLUSIVE)
        elif is_upper or (is_max and not op):
            if upper is not None:
                return None, "包含多个上限，需按条件分别确认"
            upper = _Bound(value, op not in _UPPER_EXCLUSIVE)
        elif len(tokens) == 1:
            scalar = True
            lower = upper = _Bound(value, True)
        else:
            return None, "缺少 min/max 或显式上下限，不能推断范围的择严方向"
    if lower and upper and (
        lower.value > upper.value
        or (lower.value == upper.value and not (lower.inclusive and upper.inclusive))
    ):
        return None, "上下限互相矛盾，验收区间为空"
    return _Requirement(dimension or "unitless", lower, upper, _context("".join(fragments)), scalar), ""


def _subset(left: _Requirement, right: _Requirement) -> bool:
    """Whether every value accepted by left is also accepted by right."""
    if right.lower is not None:
        if left.lower is None or left.lower.value < right.lower.value:
            return False
        if left.lower.value == right.lower.value and left.lower.inclusive and not right.lower.inclusive:
            return False
    if right.upper is not None:
        if left.upper is None or left.upper.value > right.upper.value:
            return False
        if left.upper.value == right.upper.value and left.upper.inclusive and not right.upper.inclusive:
            return False
    return True


def compare_indicator_values(user_value: str, standard_value: str) -> IndicatorComparison:
    """Select a source only when the complete guarantee is at least as strict.

    Adopted text is always one original input (trimmed), never a fabricated
    intersection of requirements. ``manual_review`` retains the user text and
    sets an explicit review flag. Naked ranges and differing nominal values
    need product semantics and are therefore not automatically ranked.
    """
    user = (user_value or "").strip()
    standard = (standard_value or "").strip()
    user_requirement, user_error = _parse(user)
    standard_requirement, standard_error = _parse(standard)
    has_typical = _without_typical(user)[1] or _without_typical(standard)[1]
    typical_note = "[参考信息] typ 仅作参考，本次仅按 min/max 保证边界比较。" if has_typical else ""

    def reviewed(reason: str) -> IndicatorComparison:
        return IndicatorComparison(
            user,
            f"[人工复核] {reason}：用户要求={user}；标准要求={standard}",
            True,
            "manual_review",
        )

    # Typical-only text is not a guaranteed specification, even when repeated
    # verbatim in both sources or present only in the standard.
    for source, requirement, error in ((user, user_requirement, user_error), (standard, standard_requirement, standard_error)):
        if source and _without_typical(source)[1] and requirement is None:
            return reviewed(error)
        if source and _without_typical(source)[1] and requirement is not None and requirement.scalar:
            return reviewed("只有 typ 参考值或未指定保证边界的标称值")
        if source and "矛盾" in error:
            return reviewed(error)
    if not user and not standard:
        return IndicatorComparison("", "", False, "empty")
    if not user:
        return IndicatorComparison(standard, typical_note, False, "standard_only")
    if not standard:
        return IndicatorComparison(user, typical_note, False, "user_only")
    if re.sub(r"\s+", "", _normalized(user)) == re.sub(r"\s+", "", _normalized(standard)):
        return IndicatorComparison(user, typical_note, False, "equal")
    if user_requirement is None or standard_requirement is None:
        return reviewed(user_error or standard_error)
    if user_requirement.dimension != standard_requirement.dimension:
        return reviewed("量纲不同或单位不一致，无法自动择严")
    if user_requirement.context != standard_requirement.context:
        return reviewed("测试条件或其他要求不一致，无法自动择严")

    user_subset = _subset(user_requirement, standard_requirement)
    standard_subset = _subset(standard_requirement, user_requirement)
    if user_subset and standard_subset:
        return IndicatorComparison(user, typical_note, False, "equal")
    if user_requirement.scalar or standard_requirement.scalar:
        return reviewed("标称值未指定验收上下限，不能推断择严方向")
    if user_subset:
        return IndicatorComparison(user, "[严格值裁决] 用户完整验收区间更严格。" + typical_note, False, "stricter_user")
    if standard_subset:
        return IndicatorComparison(standard, "[严格值裁决] 规范完整验收区间更严格。" + typical_note, False, "stricter_standard")
    return reviewed("双方上下限互有严宽或区间不包含，不能只按首个阈值择严")
