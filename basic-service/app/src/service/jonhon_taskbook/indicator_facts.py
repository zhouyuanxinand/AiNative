"""Extract source-owned indicator atoms independently of narrative routing.

A chapter may explain reliability and also contain a salt-spray limit.  Its
narrative destination must not erase that explicit measurement.  Conversely,
a standard reference or a measurement mentioned only as a test condition is
not a new indicator. Identities come from explicit labels or governed names.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .indicator_identity import canonical_indicator_name
from .source_scope import is_unvalued_historical_result_caption, review_reference_source_ids


_NUMBERING = re.compile(r"^\s*(?:(?:[（(]\d+[）)]|\d+(?:\.\d+)*[.、)）]?)\s*)")
_MEASUREMENT = re.compile(r"\d\s*(?:[~～至到±≤≥<>%℃°]|(?:[pnuμµmkMG]?[AVWΩFH]|[kMG]?Hz|[munμµ]?s|[munμµ]?m|dB|Pa|MPa|kPa|N|g|h|次|周期|循环))|IP\s*\d{2}", re.I)
_CONTAINER = re.compile(r"^(?:核心)?(?:技术|电气|电|机械|环境|光学|光|热|流体)?(?:性能|技术)?(?:指标|要求|性能|参数)(?:指标|要求|参数)?$")
_NON_TECHNICAL_CONTEXT = re.compile(r"引用标准|规范性引用|编制依据|参考文献|双方签字|签章|质量保证与售后|质保期|检验与验收|验收标准")
_QUALIFIER_LABEL = re.compile(r"^(?:(?:试验|测试|检验|验收|合格|判定|工作|适用|参考)?(?:条件|判据|标准|环境|状态|方法|结果)|(?:试验|测试|检验)(?:设备|仪器|装置|样品|试样|介质|程序|步骤|持续时间|时长|时间|频次|频率|次数|幅值|顺序)|备注|注|说明|要求|依据)$")
_TABLE_CONTEXT_HEADER = re.compile(r"条件|环境|状态|型号|规格|适用|单位|温度|湿度|频率|电压|电流|部位|接触件|试验前|试验后|测试前|测试后|允许偏差|公差|判据|试验方法|测试方法|检验方法")
_NARRATIVE_PERFORMANCE_ROLES = {"usage_environment", "environmental_adaptability", "reliability"}
_NARRATIVE_FIELD = re.compile(r"^(?:安装(?:方式|形式|方法|尺寸|部位)|使用(?:部位|场景)|产品(?:型号|名称|组成|用途)|结构(?:形式|组成)|材质|材料|接线方式|端接形式)$")


def _label(text: str) -> str:
    return _NUMBERING.sub("", str(text or "")).strip(" ：:；;。※*")


def _key(text: str) -> str:
    value = re.sub(r"\s+", "", _label(text))
    return re.sub(r"[（(][A-Za-z][A-Za-z0-9 /-]*[）)]$", "", value)


def _is_container(label: str) -> bool:
    value = re.sub(r"[（(][^()（）]*[）)]", "", _key(label))
    value = re.sub(r"^(?:(?:通用|核心|主要|基本|一般|射频|高频|低频))+", "", value)
    return bool(_CONTAINER.fullmatch(value) or re.fullmatch(r"(?:工作)?环境(?:工作)?条件", value))


def _category(heading: str) -> str:
    # A small heading such as “锁紧力矩” inherits its performance domain from
    # the nearest parent. A broad ancestor must not override a specific child.
    for title in reversed(heading.split(" / ")):
        for terms, category in (
            (("可靠性",), "可靠性"),
            (("电气", "电性能", "高频", "电磁兼容", "EMC"), "电性能"),
            (("机械",), "机械性能"),
            (("环境",), "环境性能"),
            (("光学", "光性能"), "光性能"),
        ):
            if any(term in title for term in terms):
                return category
    return "其他"


def _rows(block: dict) -> list[list[str]]:
    embedded = block.get("table_rows")
    if isinstance(embedded, (list, tuple)):
        return [[str(cell or "").strip() for cell in row] for row in embedded]
    path = block.get("source_path")
    if not path or not isinstance(block.get("body_index"), int):
        return []
    # Read only the same original body node referenced by the classifier.
    from docx import Document
    from docx.oxml.ns import qn
    from pathlib import Path
    if not Path(path).is_file():
        return []
    document = Document(path)
    nodes = list(document.element.body)
    index = block["body_index"]
    if not 0 <= index < len(nodes) or nodes[index].tag != qn("w:tbl"):
        return []
    return [["\n".join("".join(t.text or "" for t in p.iter(qn("w:t")))
                       for p in cell.iter(qn("w:p"))).strip()
             for cell in row.findall(qn("w:tc"))]
            for row in nodes[index].findall(qn("w:tr"))]


def extract_indicator_facts(
    classification: dict | None,
    indicator_map: dict[str, list[dict]] | None = None,
    *,
    excluded_names: list[str] | tuple[str, ...] = (),
    source_document=None,
) -> list[dict[str, Any]]:
    """Return independently identified facts with exact source coordinates.

    Known indicator labels are eligible across technical narrative categories.
    New labels require performance evidence, including explicitly labelled
    environmental requirements. Qualitative requirements remain source facts;
    numerical comparability is decided separately when selecting adopted values.
    """
    if not isinstance(classification, dict):
        return []
    review_ids = review_reference_source_ids(classification)
    vocabulary: dict[str, tuple[str, str]] = {}
    for category, entries in (indicator_map or {}).items():
        for entry in entries:
            name = str(entry.get("name", ""))
            for alias in [name, *(entry.get("tech_kws") or [])]:
                if _key(alias):
                    vocabulary[_key(alias)] = (name, category)
    excluded = {canonical_indicator_name(name) for name in excluded_names}
    assignments = {str(row.get("source_id")): str(row.get("category", ""))
                   for row in classification.get("classifications", []) if isinstance(row, dict)}

    grouped: dict[str, list[dict]] = {}
    for block in classification.get("source_blocks", []):
        if not isinstance(block, dict) or not block.get("id") or block.get("source", "tech") != "tech":
            continue
        grouped.setdefault(str(block.get("parent_source_id") or block["id"]), []).append(block)
    if source_document is not None:
        # The original document is the completeness boundary. Reconcile with
        # classification only for provenance; a missed source block must not
        # disappear from the independent indicator ledger.
        from docx.oxml.ns import qn
        from docx.text.paragraph import Paragraph
        from .template_scanner import heading_level
        from .source_scope import source_exclusion_reasons, is_source_heading, has_substantive_heading_content
        by_index: dict[int, list[dict]] = {}
        for blocks in grouped.values():
            for block in blocks:
                if isinstance(block.get("body_index"), int):
                    by_index.setdefault(block["body_index"], []).append(block)
        complete: dict[str, list[dict]] = {}
        synthetic_by_text = {str(block.get("text", "")).strip(): blocks
                             for blocks in grouped.values() for block in blocks
                             if not isinstance(block.get("body_index"), int)}
        reconciled_synthetic: set[str] = set()
        headings: dict[int, str] = {}
        elements = list(source_document.element.body)
        exclusions = source_exclusion_reasons(elements)
        for index, node in enumerate(elements):
            if index in exclusions:
                continue
            if node.tag not in {qn("w:p"), qn("w:tbl")}:
                continue
            text = "".join(t.text or "" for t in node.iter(qn("w:t"))).strip()
            if not text:
                continue
            if node.tag == qn("w:p"):
                level = heading_level(Paragraph(node, source_document))
                # A styled paragraph with a measured value is still a fact,
                # not a heading merely because a model or author styled it.
                if is_source_heading(node, text) and not has_substantive_heading_content(text):
                    level = level or 1
                    headings = {depth: title for depth, title in headings.items() if depth < level}
                    headings[level] = _label(text)
                    continue
            existing = by_index.get(index, []) or synthetic_by_text.get(text, [])
            reconciled_synthetic.update(str(item.get("parent_source_id") or item["id"]) for item in existing)
            if existing:
                copy = dict(existing[0])
                copy["id"] = str(copy.get("parent_source_id") or copy["id"])
                copy["original_source_ids"] = [str(item["id"]) for item in existing]
                roles = [assignments.get(str(item["id"]), "") for item in existing]
                assignments[copy["id"]] = "performance_indicator" if "performance_indicator" in roles else next(iter(roles), "")
                copy.pop("parent_source_id", None)
                copy["body_index"] = index
                copy["text"] = text
            else:
                source_id = "tech-original-" + hashlib.sha256(f"{index}:{text}".encode()).hexdigest()[:16]
                heading = next(reversed(headings.values()), "")
                copy = {"id": source_id, "body_index": index, "type": "table" if node.tag == qn("w:tbl") else "paragraph",
                        "text": text, "heading_text": heading, "parent_headings": list(headings.values())[:-1]}
                if re.search(r"(?:技术|电气|机械|环境|光学).*?(?:指标|性能)", " / ".join(headings.values())):
                    assignments[source_id] = "performance_indicator"
            if node.tag == qn("w:tbl"):
                copy["table_rows"] = [["\n".join("".join(t.text or "" for t in p.iter(qn("w:t"))) for p in cell.iter(qn("w:p"))).strip()
                                       for cell in row.findall(qn("w:tc"))] for row in node.findall(qn("w:tr"))]
            complete[copy["id"]] = [copy]
        # Synthetic/offline callers sometimes supply explicit source blocks
        # without body coordinates; those remain valid input evidence.
        for key, blocks in grouped.items():
            if key not in reconciled_synthetic and not any(isinstance(block.get("body_index"), int) for block in blocks):
                complete[key] = blocks
        grouped = complete
    facts: list[dict[str, Any]] = []

    def add(label: str, value: str, heading: str, blocks: list[dict], *, coordinate: dict, performance: bool, table: bool = False):
        key = _key(label)
        governed = vocabulary.get(key)
        if not key or _is_container(key) or (not governed and _QUALIFIER_LABEL.fullmatch(key)) or not value.strip() or value.strip() in {"无", "无要求", "不适用", "/", "\\"}:
            return
        if not governed and not performance:
            return
        context = " / ".join([*map(str, blocks[0].get("parent_headings") or []), heading])
        name, category = governed or (_label(label), _category(context))
        if canonical_indicator_name(name) in excluded:
            return
        source_ids = list(dict.fromkeys(source_id for block in blocks for source_id in block.get("original_source_ids", [str(block["id"])])))
        coordinate = {"body_index": blocks[0].get("body_index"), **coordinate}
        identity = {"source": str(blocks[0].get("parent_source_id") or blocks[0]["id"]), **coordinate}
        fact_id = "indicator-" + hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        facts.append({"fact_id": fact_id, "indicator_name": name, "source_label": _label(label),
                      "category": category, "source_value": value.strip(), "source_heading": heading,
                      "source_ids": source_ids, "source_coordinates": coordinate, "is_table": table,
                      "governed_name": bool(governed)})

    for blocks in grouped.values():
        block = blocks[0]
        source_ids = {str(sid) for item in blocks for sid in item.get("original_source_ids", [item["id"]])}
        if source_ids and source_ids.issubset(review_ids):
            continue
        heading = str(block.get("heading_text") or block.get("section") or "")
        context = " / ".join([*map(str, block.get("parent_headings") or []), heading])
        roles = {assignments.get(str(item["id"]), "") for item in blocks}
        if roles == {"standards_reference"} or _NON_TECHNICAL_CONTEXT.search(context):
            continue
        if block.get("type") != "table" and is_unvalued_historical_result_caption(
            str(block.get("text") or ""), context,
        ):
            continue
        performance = "performance_indicator" in roles
        quantitative_narrative = (
            bool(roles & _NARRATIVE_PERFORMANCE_ROLES) and _category(context) != "其他"
        )

        def eligible_label(label: str, value: str) -> bool:
            key = _key(label)
            return key in vocabulary or (
                not _QUALIFIER_LABEL.fullmatch(key) and not _NARRATIVE_FIELD.fullmatch(key)
                and (performance or (quantitative_narrative and bool(_MEASUREMENT.search(value))))
            )
        if block.get("type") == "table":
            matrix = _rows(block)
            label_columns, value_columns, ignored_columns, header_rows = set(), set(), set(), set()
            context_columns: dict[int, str] = {}
            candidate_headers = [
                [re.sub(r"[\s：:]", "", cell) for cell in row]
                for row in matrix[:4]
            ]
            descriptive_pairs = [
                "技术特性类型" in tokens and "特性描述" in tokens
                for tokens in candidate_headers
            ]
            # These descriptive columns are design indicators only when their
            # source table was routed as performance evidence. An identically
            # headed inspection/result table has no such authority.
            if any(descriptive_pairs) and not performance:
                continue
            for row_index, row in enumerate(matrix[:4]):
                tokens = candidate_headers[row_index]
                # Some governed specifications use this descriptive pair in
                # place of 项目/指标. Treat it as row-level design input only
                # when the same table was classified as a performance source.
                # A historical test table with an identical header must not
                # gain indicator facts merely because it shares these labels.
                descriptive_pair = descriptive_pairs[row_index]
                for col, cell in enumerate(row):
                    token = tokens[col]
                    if descriptive_pair and token == "技术特性类型":
                        label_columns.add(col); header_rows.add(row_index)
                    if descriptive_pair and token == "特性描述":
                        value_columns.add(col); header_rows.add(row_index)
                    if token in {"项目", "项目名称", "指标名称", "指标项目", "参数名称", "性能项目", "试验项目", "检验项目", "名称"}:
                        label_columns.add(col); header_rows.add(row_index)
                    if token in {"指标", "指标值", "技术指标", "性能指标", "用户要求指标", "技术要求", "性能要求", "要求", "参数", "参数值", "数值", "规格"}:
                        value_columns.add(col); header_rows.add(row_index)
                    if _TABLE_CONTEXT_HEADER.search(token) and not _MEASUREMENT.search(token):
                        # Context is part of the requirement, not a separate
                        # indicator. Only header rows establish its columns.
                        if any(re.sub(r"[\s：:]", "", title) in {"项目", "项目名称", "指标名称", "指标项目", "参数名称", "性能项目", "试验项目", "检验项目", "名称"} for title in row):
                            context_columns[col] = cell.strip()
                    if any(word in token for word in ("序号", "编号", "抽样", "备注", "依据", "适用", "试验方法", "检验方法", "测试方法")):
                        ignored_columns.add(col)
            for index, row in enumerate(matrix):
                if index in header_rows:
                    continue
                for col in sorted(label_columns):
                    if col >= len(row):
                        continue
                    selected_values = value_columns - label_columns
                    if not selected_values:
                        selected_values = {i for i in range(col + 1, len(row)) if i not in ignored_columns | label_columns}
                    selected = sorted((selected_values | context_columns.keys()) - label_columns)
                    value = "；".join(
                        f"{context_columns[i]}：{row[i]}" if i in context_columns else row[i]
                        for i in selected if i < len(row) and row[i].strip()
                    )
                    add(row[col], value, heading, blocks, coordinate={"table_row": index, "label_column": col, "value_columns": selected}, performance=eligible_label(row[col], value), table=True)
            continue
        ordered = sorted(blocks, key=lambda item: int(item.get("source_span_start", 0)))
        text = "".join(str(item.get("text", "")) for item in ordered)
        if not text.strip():
            continue
        # Distinct list paragraphs are independent atoms. Conditions and
        # alternate ranges within one labelled clause stay together.
        # A semicolon starts another atom only when immediately followed by
        # an explicit label. Ordinary conditions remain with their metric.
        boundaries = [0]
        for separator in re.finditer(r"\n|[；;]", text):
            if separator.group() == "\n":
                boundaries.append(separator.end())
                continue
            next_clause = re.split(r"[；;\n]", text[separator.end():], maxsplit=1)[0]
            next_label = re.match(r"^([^：:\n]{1,48})[：:](.*)", _label(next_clause))
            if not next_label:
                continue
            label_key = _key(next_label.group(1))
            if (not _QUALIFIER_LABEL.fullmatch(label_key) and next_label.group(2).strip()
                    and eligible_label(label_key, next_label.group(2))):
                boundaries.append(separator.end())
        boundaries.append(len(text))
        segments = [(start, end, text[start:end].rstrip("\n"))
                    for start, end in zip(boundaries, boundaries[1:])]
        for start, end, raw_value in segments:
            value = raw_value.strip()
            clean = _label(value)
            match = re.match(r"^([^：:\n]{1,48})[：:]", clean)
            if match:
                label = match.group(1)
                if eligible_label(label, value):
                    add(label, value, heading, ordered, coordinate={"start": start, "end": end}, performance=True)
                    continue
            heading_key = _key(heading)
            if heading_key in vocabulary:
                add(heading, value, heading, ordered, coordinate={"start": start, "end": end}, performance=performance)
                continue
            if performance:
                # A full sentence can state a governed indicator without a
                # colon. Require exactly one identity, not a mentioned test
                # condition or another metric's acceptance criterion.
                hits = {(name, category) for alias, (name, category) in vocabulary.items()
                        if clean.startswith(alias) or clean.startswith("产品" + alias)}
                if len(hits) == 1:
                    name, _ = next(iter(hits))
                    add(name, value, heading, ordered, coordinate={"start": start, "end": end}, performance=True)
                elif (heading_key and len(heading_key) <= 48
                      and not _is_container(heading_key)
                      and not _QUALIFIER_LABEL.fullmatch(heading_key)
                      and not _NARRATIVE_FIELD.fullmatch(heading_key)):
                    add(heading, value, heading, ordered, coordinate={"start": start, "end": end}, performance=True)
    return facts


def indicator_fact_evidence(facts: list[dict], name: str) -> tuple[str, str, list[str], list[str], bool]:
    matched = [fact for fact in facts if canonical_indicator_name(fact["indicator_name"]) == canonical_indicator_name(name)]
    return ("\n".join(dict.fromkeys(fact["source_value"] for fact in matched)),
            next((fact["source_heading"] for fact in matched if fact["source_heading"]), ""),
            list(dict.fromkeys(source_id for fact in matched for source_id in fact["source_ids"])),
            [fact["fact_id"] for fact in matched], bool(matched) and all(fact["is_table"] for fact in matched))


def audit_indicator_fact_coverage(facts: list[dict], decisions: list[dict]) -> dict[str, Any]:
    """Audit independent source atoms against rows, including cross-name reuse."""
    expected = {fact["fact_id"]: fact for fact in facts}
    owners: dict[str, list[str]] = {}
    for row in decisions:
        for fact_id in row.get("user_fact_ids", []):
            owners.setdefault(str(fact_id), []).append(str(row.get("indicator_name", "")))
    missing = [fact for fact_id, fact in expected.items() if fact_id not in owners]
    duplicate = [{"fact_id": fact_id, "indicator_names": names} for fact_id, names in owners.items() if len(names) > 1]
    unknown = [fact_id for fact_id in owners if fact_id not in expected]
    wrong_identity = [{"fact_id": fact_id, "expected": expected[fact_id]["indicator_name"], "actual": names}
                      for fact_id, names in owners.items() if fact_id in expected
                      and any(canonical_indicator_name(name) != canonical_indicator_name(expected[fact_id]["indicator_name"]) for name in names)]
    return {"source_fact_count": len(expected), "consumed_fact_count": len(set(expected) & set(owners)),
            "missing_facts": missing, "duplicate_consumption": duplicate, "unknown_fact_ids": unknown,
            "wrong_indicator_identity": wrong_identity,
            "passed": not (missing or duplicate or unknown or wrong_identity)}
