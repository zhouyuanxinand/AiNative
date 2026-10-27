"""Shared source-content boundaries for routing, facts and coverage accounting."""
from __future__ import annotations

import re
from typing import Any, Sequence

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_NUMBER = re.compile(r"^\s*\d+(?:\.\d+)*(?:\s+|[、)]|[.．](?!\d))")
_STANDARD = re.compile(r"(?:GB(?:/T)?|GJB(?:/Z)?|IEC|ISO|MIL-[A-Z]+|HB|QJ)\s*\d", re.I)
_VALUE = re.compile(r"[≥≤<>＝=]|\d\s*(?:℃|°C|Ω|%|GHz|MHz|kHz|Hz|mm|cm|MPa|kPa|dB|mΩ|kΩ|N·m|V|A|h|次|天|小时|个月)", re.I)
_REQUIREMENT = re.compile(r"必须|不得|应当|应(?:满足|符合|具备|采用|提供|保证|不|能|有)|需(?:满足|保证|提供|采用)|要求(?:为|不|达到)")
_SIGNATURE_HEADING = re.compile(r"^(?:双方签字|双方签署|签字盖章|签署页|签署栏|签署|使用单位签[署字]|研制(?:或试制)?单位签[署字])(?:[（(].*[）)])?[：:]?$")
_SIGNATURE_FIELD = re.compile(r"^(?:(?:需方|供方|甲方|乙方)(?:[（(](?:盖章|签字)[）)])?|(?:法定|授权)?代表人?(?:签字)?|签署人|签字人|审核|批准|会签)[：:]\s*.*$")
_DATE = re.compile(r"^(?:(?:签署)?日期[：:]\s*)?[\d_＿\-—\s./年月日]+$")
_AI_NOTICE = re.compile(r"^[|｜]?[（(]?(?:注[：:]?)?(?:部分|本|本文|该|以上)?内容(?:可能)?(?:由|为)?\s*AI\s*生成[。.]?[）)]?$", re.I)
_TECHNICAL = re.compile(r"产品|电气|机械|性能|材料|尺寸|试验|测试|检验|验收|交付|维护|质保|可靠")
_HISTORICAL_RESULTS_CONTEXT = re.compile(
    r"(?:测试|试验|检测|测量)(?:设备及)?(?:测试|试验|检测|测量)?(?:数据|结果)"
    r"|(?:历史|原始)(?:测试|试验|检测|测量)?(?:数据|结果)"
)
_UNVALUED_RESULT_CAPTION = re.compile(
    r"^.{0,120}(?:(?:测试|试验|检测|测量))?(?:数据|结果)[：:]$"
)


def _text(element: Any) -> str:
    return "".join(node.text or "" for node in element.findall(f".//{W}t")).strip()


def _unnumbered(text: str) -> str:
    return _NUMBER.sub("", (text or "").strip()).strip()


def has_substantive_heading_content(text: str) -> bool:
    """A heading hint must not erase a requirement written in the same paragraph."""
    value = _unnumbered(text)
    if re.search(r"[：:]\s*\S", value):
        return True
    return bool(
        re.search(r"[，,；;。！？!?]", value)
        or _STANDARD.search(value)
        or _VALUE.search(value)
        or _REQUIREMENT.search(value)
        or (_DATE.fullmatch(value) and "年" in value and "日" in value)
        or value in {"无", "无要求", "暂无", "不适用", "不涉及"}
    )


def is_source_heading(element: Any, text: str | None = None) -> bool:
    """Recognize structure only; callers must separately retain inline content."""
    if element.tag != f"{W}p":
        return False
    text = _text(element) if text is None else text
    if not _unnumbered(text):
        return False
    ppr = element.find(f"{W}pPr")
    style = ppr.find(f"{W}pStyle") if ppr is not None else None
    outline = ppr.find(f"{W}outlineLvl") if ppr is not None else None
    style_name = style.get(f"{W}val", "") if style is not None else ""
    return bool(re.match(r"^[1-9]$|^[Hh]eading|^标题", style_name) or outline is not None or _NUMBER.match(text))


def source_heading_label(text: str) -> str:
    """Separate a numbered field's label from its value without rewriting evidence."""
    value = (text or "").strip()
    match = re.search(r"[：:]", value)
    if _NUMBER.match(value) and match and value[match.end():].strip():
        return value[:match.start()].strip()
    return value


def normalize_source_display_text(
    text: str, *, heading_number: str = "", heading_text: str = ""
) -> str:
    """Normalize presentation while preserving every technical value and clause.

    Decimal prefixes are ambiguous with measurements. Remove them only when
    supplied heading metadata proves the prefix, or when a Chinese field label
    and colon make it an explicit numbered field. Never strip a bare numeric
    value, a unit, an internal decimal point, or internal sentence punctuation.
    """
    value = str(text or "").strip()
    explicit_list = re.match(r"^(?:[（(]\d+[）)]|\d+[、）)])\s*", value)
    numbered = _NUMBER.match(value)
    if explicit_list:
        value = value[explicit_list.end():]
    elif numbered:
        remainder = value[numbered.end():].strip()
        prefix = numbered.group().strip().rstrip(".．、)")
        label = str(heading_text or "").strip()
        known_heading = (
            bool(heading_number and label)
            and prefix == str(heading_number).strip()
            and remainder.startswith(label)
        )
        labelled_field = bool(re.match(r"[\u4e00-\u9fff][^：:，,。；;!?！？\d]{1,30}[：:]", remainder))
        if known_heading or labelled_field:
            value = remainder
    return re.sub(r"[；;。]+$", "", re.sub(r"\s+", "", value))


def is_signature_heading(text: str) -> bool:
    return bool(_SIGNATURE_HEADING.fullmatch(re.sub(r"\s+", "", _unnumbered(text))))


def is_unvalued_historical_result_caption(text: str, context: str) -> bool:
    """Recognize a result label with no value in a historical-results section.

    Such labels introduce the raw table or image that follows; they are still
    source evidence for review, but have no design or acceptance value to use
    as an indicator. A stated threshold after the colon is never suppressed.
    """
    compact_context = re.sub(r"\s+", "", str(context or ""))
    compact_text = re.sub(r"\s+", "", str(text or ""))
    return bool(
        _HISTORICAL_RESULTS_CONTEXT.search(compact_context)
        and _UNVALUED_RESULT_CAPTION.fullmatch(compact_text)
    )


def review_reference_source_ids(classification: dict | None) -> set[str]:
    """Identify historical result artifacts and empty captions for review only.

    Require explicit results context and source coordinates as well as a
    performance category for data artifacts. An empty result caption may also
    carry the testability category. Mixed categories/fragments and paragraphs
    containing a real value remain ordinary source evidence.
    """
    if not isinstance(classification, dict):
        return set()
    categories: dict[str, set[str]] = {}
    for item in classification.get("classifications", []) or []:
        if isinstance(item, dict) and item.get("source_id"):
            categories.setdefault(str(item["source_id"]), set()).add(str(item.get("category") or ""))
    result: set[str] = set()
    for source in classification.get("source_blocks", []) or []:
        if not isinstance(source, dict) or source.get("source") != "tech":
            continue
        source_id = str(source.get("id") or "")
        position = source.get("body_index")
        if (not source_id or not source.get("source_path") or type(position) is not int
                or position < 0 or source.get("parent_source_id")):
            continue
        assigned = categories.get(source_id)
        text = str(source.get("text") or "").strip()
        artifact = source.get("type") == "table" or (
            source.get("has_drawing") and (not text or re.fullmatch(r"\[图片对象 body=\d+\]", text))
        )
        headings = [*(source.get("parent_headings") or []), source.get("heading_text", ""), source.get("section", "")]
        context = " / ".join(str(heading) for heading in headings)
        if (artifact and assigned == {"performance_indicator"}
                and _HISTORICAL_RESULTS_CONTEXT.search(re.sub(r"\s+", "", context))):
            result.add(source_id)
        elif (source.get("type") == "paragraph" and not source.get("has_drawing")
              and assigned in ({"performance_indicator"}, {"testability"})
              and is_unvalued_historical_result_caption(text, context)):
            result.add(source_id)
    return result


def nontechnical_text_reason(text: str, *, kind: str = "paragraph") -> str | None:
    """Exclude administrative evidence only, never a substantive technical clause."""
    value = _unnumbered(text)
    compact = re.sub(r"\s+", "", value)
    if _AI_NOTICE.fullmatch(compact):
        return "ai_generation_notice"
    if is_signature_heading(value):
        return "signature_heading"
    if value.startswith("签署日期") and _DATE.fullmatch(value):
        return "signature_date"
    if _SIGNATURE_FIELD.fullmatch(value) and not (_REQUIREMENT.search(value) or _TECHNICAL.search(value)):
        return "signature_field"
    if re.search(r"本(?:协议|合同)一式|甲乙双方各保存|签字盖章后生效", value) and not _TECHNICAL.search(value):
        return "contract_execution_clause"
    if (
        re.search(r"(?:本(?:协议|合同)[^。；;]{0,12}未尽事宜|补充协议[^。；;]{0,30}(?:同等法律效力|同等效力))", value)
        and not (_TECHNICAL.search(value) or _STANDARD.search(value) or _VALUE.search(value))
    ):
        return "contract_administration_clause"
    if kind == "table":
        if re.search(r"使用单位签[署字]|研制(?:或试制)?单位签[署字]|签字/盖章", compact) and not _TECHNICAL.search(compact.replace("研制", "")):
            return "signature_table"
        if "版本" in compact and "章条编号" in compact:
            return "change_record"
        if "产品名称" in compact and any(word in compact for word in ("使用单位", "研制单位", "密级", "研制阶段")):
            return "cover_metadata"
    if compact == "部件规格承认书" or re.fullmatch(r"研\s*制\s*任\s*务\s*书|变更记录|中航光电(?:科技股份有限公司)?|JONHON|目\s*录|第\s*\d+\s*页", value, re.I):
        return "document_furniture"
    if re.match(r"^(?:编\s*号|版本|密\s*级|研制阶段|使用单位|研制单位|名\s*称)[：:]", value) and not _REQUIREMENT.search(value):
        return "cover_metadata"
    return None


def source_exclusion_reasons(elements: Sequence[Any]) -> dict[int, str]:
    """Determine the same administrative scope for extraction and coverage."""
    excluded: dict[int, str] = {}
    signature_tail = False
    for index, element in enumerate(elements):
        kind = "table" if element.tag == f"{W}tbl" else "paragraph"
        text = _text(element)
        substantive = has_substantive_heading_content(text)
        if is_source_heading(element, text) and not substantive:
            signature_tail = is_signature_heading(text)
        reason = nontechnical_text_reason(text, kind=kind)
        # A bare result label only introduces the immediately following raw
        # table/image. Do not require multiple copies of this label as if it
        # were a requirement; substantive results after the colon stay intact.
        if kind == "paragraph" and re.fullmatch(r"(?:测试|试验|检测|测量)结果[：:]", text):
            for following in elements[index + 1:]:
                following_text = _text(following)
                has_media = bool(following.xpath('.//*[local-name()="blip" or local-name()="imagedata"]'))
                if not following_text and not has_media and following.tag == f"{W}p":
                    continue
                if (following.tag == f"{W}tbl" and following_text) or has_media:
                    reason = "test_result_artifact_label"
                break
        if signature_tail and _DATE.fullmatch(_unnumbered(text)) and text:
            reason = "signature_date"
        if reason:
            excluded[index] = reason
            if reason.startswith("signature"):
                signature_tail = True
            continue
        has_image = bool(element.xpath('.//*[local-name()="blip" or local-name()="imagedata"]'))
        if signature_tail and not text and has_image:
            excluded[index] = "signature_image"
            continue
        if text:
            signature_tail = False
    return excluded
