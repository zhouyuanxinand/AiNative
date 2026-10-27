"""Extract explicit source standard references without changing their identifiers."""
from __future__ import annotations

import re


_CODE = re.compile(
    r"(?<![A-Z0-9/])(?:"
    r"(?:GJB(?:\s*/\s*Z)?|GB(?:\s*/\s*[TZ])?|ISO(?:\s*/\s*IEC)?|IEC|"
    r"KJB|CCAR|SAE(?:\s+AS)?|AS)\s*\d[A-Z0-9./:\-]*"
    r"|MIL[-\s][A-Z]+[-\s]\d[A-Z0-9./:\-]*"
    r"|TE-\d[A-Z0-9./:\-]*|Q/\s*[A-Z0-9][A-Z0-9./:\-]*"
    r")",
    re.I,
)
_LIST_PREFIX = re.compile(r"^[\s·•●○\-—–（(]*\d*(?:\.\d+)*[）).、\s]*")
_CHINESE_NUMBER = r"[零〇一二三四五六七八九十百千万两]+"
_HEADING_PREFIX = re.compile(
    rf"^\s*(?:第{_CHINESE_NUMBER}[章节篇]\s*|{_CHINESE_NUMBER}[、．.]\s*)"
)
_REFERENCE_HEADINGS = frozenset({
    "适用标准", "引用标准", "执行标准", "依据标准", "标准依据",
    "引用文件", "规范性引用", "规范性引用文件", "规范性引用标准",
    "参考标准", "参考文献", "标准清单", "适用的法律法规",
    "适用的法律法规要求", "适用法律法规", "适用法律法规要求",
})
_REFERENCE_ROW_LABEL = re.compile(r"[\u4e00-\u9fffA-Za-z /\-]{0,24}(?:标准|规范|引用文件)")
_SHORT_CONTEXT_LABEL = re.compile(r"[\u4e00-\u9fffA-Za-z /\-]{1,24}")
_INSTRUCTION_PREFIX = re.compile(
    r"(?:^|[：:，,；;\s])(?:按(?:照)?|依照|根据|依据|应(?:当)?|须|需|采用|参照|满足|符合)"
    r"|进行|开展|执行.*(?:检测|试验)|试验方法|检测方法"
)


def _display_label(text: str) -> str:
    value = _HEADING_PREFIX.sub("", (text or "").strip())
    return _LIST_PREFIX.sub("", value).strip(" \t\r\n：:")


def is_reference_heading(text: str) -> bool:
    """Recognize a complete reference-section title, not a technical sentence.

    The caller supplies structural heading boundaries; this function identifies
    only the title's meaning, independently of its source display numbering.
    """
    return _display_label(text) in _REFERENCE_HEADINGS


def standard_code(text: str) -> str:
    match = _CODE.match(text.strip())
    return re.sub(r"\s+", "", match.group()).upper() if match else ""


def extract_standard_references(text: str, *, reference_context: bool = False) -> list[str]:
    """Split a reference list, retaining each original code, title and conditions.

    An embedded reference must have an explicit reference-list label or belong
    to a structurally identified reference section. This
    prevents ordinary test instructions from being promoted to normative titles.
    Standalone standard rows continue to be accepted, including table cells.
    """
    value = (text or "").strip()
    matches = list(_CODE.finditer(value))
    if not matches:
        return []
    prefix = value[:matches[0].start()]
    label = _display_label(prefix)
    if label:
        explicit_heading = label in _REFERENCE_HEADINGS
        # Named reference rows commonly use a qualifier before 标准, such as
        # 通用基础标准 and 可靠性试验标准. A colon makes the label unambiguous.
        explicit_row = bool(
            prefix.rstrip().endswith(("：", ":"))
            and _REFERENCE_ROW_LABEL.fullmatch(label)
        )
        contextual_row = bool(reference_context and _SHORT_CONTEXT_LABEL.fullmatch(label))
        if _INSTRUCTION_PREFIX.search(label) and not explicit_heading:
            return []
        if not (explicit_heading or explicit_row or contextual_row):
            return []
    result = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        reference = value[match.start():end].strip(" \t\r\n、，,；;。")
        if reference:
            result.append(reference)
    return result
