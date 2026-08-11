# -*- coding: utf-8 -*-
"""
coverage_ledger.py — 输入覆盖率账本

职责：
  1. 把技术要求 docx 解析成可追踪的「输入块」列表（段落/表格/图片/指标行）
  2. 记录每个输入块的输出去向（目标章节 + 置信度）
  3. 生成覆盖率报告：未转入 = 0 才能通过质量门禁
  4. 输出 coverage_report.md 供雪总审阅
"""
from __future__ import annotations

import json
import hashlib
import posixpath
import re
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Sequence
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{W}}}"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_R = f"{{{R}}}"


def _wtag(name: str) -> str:
    return f"{_W}{name}"


def _para_text(para) -> str:
    return "".join(t.text or "" for t in para.findall(f".//{_W}t")).strip()


def _table_to_json(tbl) -> str:
    rows = []
    for tr in tbl.findall(f".//{_W}tr"):
        row = [
            "".join(t.text or "" for t in tc.findall(f".//{_W}t")).strip()
            for tc in tr.findall(f".//{_W}tc")
        ]
        if any(row):
            rows.append(row)
    return json.dumps(rows, ensure_ascii=False)


def _table_summary(tbl) -> str:
    rows = []
    for tr in tbl.findall(f".//{_W}tr"):
        row = [
            "".join(t.text or "" for t in tc.findall(f".//{_W}t")).strip()
            for tc in tr.findall(f".//{_W}tc")
        ]
        rows.append(" | ".join(c for c in row if c))
    return ("  /  ".join(rows[:3]))[:120]


def _relationship_ids(element) -> list[str]:
    """Return actual image relationship IDs referenced below *element*.

    A ``w:drawing``/``v:shape`` node alone is not evidence of an image.  The
    relationship attribute is the package-level link from visible body XML to
    the binary part and is therefore the minimum acceptable evidence.
    """
    values: list[str] = []
    for node in element.xpath(
        './/*[local-name()="blip" or local-name()="imagedata"]'
    ):
        if node.xpath('ancestor::*[local-name()="del" or local-name()="moveFrom"]'):
            continue
        if node.xpath(
            'ancestor::*[local-name()="r"]/*[local-name()="rPr"]/*[local-name()="vanish"]'
        ):
            continue
        for attr_name, value in node.attrib.items():
            local_name = etree.QName(attr_name).localname
            if local_name in {"embed", "id"} and value:
                values.append(str(value))
    return values


def _has_drawing(elem) -> bool:
    return bool(_relationship_ids(elem))


def _is_heading(element, text: str | None = None) -> bool:
    if element.tag != _wtag("p"):
        return False
    text = _para_text(element) if text is None else text
    ppr = element.find(_wtag("pPr"))
    style = ppr.find(_wtag("pStyle")) if ppr is not None else None
    outline = ppr.find(_wtag("outlineLvl")) if ppr is not None else None
    style_value = style.get(_wtag("val"), "") if style is not None else ""
    return bool(
        re.search(r"heading|标题", style_value, re.I)
        or outline is not None
        or _HEADING.match(text)
    )


def _semantic_heading(text: str) -> str:
    """Remove display numbering while retaining the real template heading."""
    return re.sub(r"^\s*\d+(?:\.\d+)*[\s.、]+", "", text or "").strip()


_IND_KEYWORDS = re.compile(
    r"工作电压|额定电流|冲击电流|绝缘电阻|介质耐电压|接触电阻|"
    r"插拔力|机械寿命|互换性|工作温度|温度冲击|振动|盐雾|"
    r"频率范围|特性阻抗|驻波比|插入损耗|回波损耗|屏蔽效能|"
    r"MTBF|可靠性|维修性|环境适应性"
)
_STANDARD_REFERENCE_LINE = re.compile(
    r"^\s*(?:GB(?:/T)?|GJB(?:/Z)?|HB|QJ|JB(?:/T)?|SJ(?:/T)?|IEC|ISO|"
    r"MIL(?:-[A-Z]+)?|ASTM|Q/)\s*[A-Z0-9]",
    re.I,
)
_STANDARDS_SECTION = re.compile(r"标准|规范|法律法规|引用文件|适用文件")
_HEADING = re.compile(r"^\d+(\.\d+)*\s+\S")
_IMG_CAPTION = re.compile(r"图\s*\d+|Fig\.", re.I)

# 模板结构段：这些段落不代表技术要求内容，解析时跳过
_TEMPLATE_SKIP = re.compile(
    r"^(研\s*制\s*任\s*务\s*书|变更记录|编\s*号[：:]|版本[：:]|"
    r"密\s*级[：:]|研制阶段[：:]|使用单位[：:]|研制单位[：:]|"
    r"名\s*称[：:]|20\d{2}\s*年|\d{4}\s*年\s*\d{1,2}\s*月|"
    r"中航光电|JONHON|目\s*录|第\s*\d+\s*页)"
)


# ── 数据结构 ──────────────────────────────────────────────────────────────────


def _coverage_text(text: str) -> str:
    """Normalize non-technical document numbering for evidence matching.

    Semantic routing can change the final order of figures, so postprocessing
    is allowed to renumber ``图N`` captions and their explicit references.
    The figure ordinal is not a technical fact; every other number, unit and
    threshold remains part of the exact coverage evidence.
    """
    compact = re.sub(r"\s+", "", text or "")
    compact = re.sub(r"图\d+", "图#", compact)
    # 受控装配只允许目标模板统一句末标点。“；”与“。”的
    # 句末形式差异不代表原文证据丢失，但内容中间的数值、单位、
    # 比较符和标点仍然保持严格比对。
    return re.sub(r"[；;。]+$", "", compact)

@dataclass
class InputBlock:
    block_id: str
    block_type: str          # paragraph / table / image / indicator
    source_section: str
    summary: str
    raw_text: str
    artifact_hash: str = ""   # 图片等二进制对象的 SHA-256
    image_caption: str = ""
    is_indicator: bool = False
    assigned_section: str = ""
    confidence: float = 0.0
    action: str = ""         # placed / skipped
    covered: bool = False
    # Deterministic output evidence.  ``block_id`` is the coverage source_id;
    # the fields below prove where that source was found in the final body.
    output_slot: str = ""
    output_body_indices: List[int] = field(default_factory=list)
    output_relationship_id: str = ""
    output_artifact_hash: str = ""
    output_caption: str = ""
    output_caption_body_index: int = -1
    output_caption_order: str = ""
    output_evidence_hash: str = ""
    image_caption_order: str = ""


@dataclass
class CoverageLedger:
    source_file: str
    blocks: List[InputBlock] = field(default_factory=list)
    # LLM/Word structure detection may recognize an unnumbered Normal-style
    # paragraph as a chapter heading.  Such structural text is audited here,
    # but it is not a writable requirement and therefore does not belong in
    # the exact-copy coverage denominator.
    excluded_structural_headings: List[Dict[str, str]] = field(default_factory=list)
    # Package media without a visible document.xml body reference are audit
    # facts only.  They must never satisfy image coverage.
    unreferenced_output_media: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.blocks)

    @property
    def by_type(self) -> Dict[str, int]:
        d: Dict[str, int] = {}
        for b in self.blocks:
            d[b.block_type] = d.get(b.block_type, 0) + 1
        return d

    @property
    def covered_count(self) -> int:
        return sum(1 for b in self.blocks if b.covered)

    @property
    def uncovered(self) -> List[InputBlock]:
        return [b for b in self.blocks if not b.covered]

    @property
    def indicator_blocks(self) -> List[InputBlock]:
        return [b for b in self.blocks if b.block_type == "indicator" or b.is_indicator]

    def passed(self) -> bool:
        return len(self.uncovered) == 0

    def to_json(self) -> str:
        return json.dumps(
            {
                "source_file": self.source_file,
                "blocks": [asdict(b) for b in self.blocks],
                "excluded_structural_headings": self.excluded_structural_headings,
                "unreferenced_output_media": self.unreferenced_output_media,
            },
            ensure_ascii=False, indent=2
        )

    @classmethod
    def from_json(cls, text: str) -> "CoverageLedger":
        data = json.loads(text)
        ledger = cls(
            source_file=data["source_file"],
            excluded_structural_headings=list(
                data.get("excluded_structural_headings", [])
            ),
            unreferenced_output_media=list(data.get("unreferenced_output_media", [])),
        )
        for bd in data["blocks"]:
            ledger.blocks.append(InputBlock(**bd))
        return ledger

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "CoverageLedger":
        return cls.from_json(path.read_text(encoding="utf-8"))

    def coverage_report_md(self) -> str:
        bt = self.by_type
        pct = self.covered_count / max(self.total, 1) * 100
        lines = [
            "# 技术要求输入覆盖率报告",
            "",
            "## 输入统计",
            "| 类型 | 数量 |",
            "|------|------|",
            f"| 段落 | {bt.get('paragraph', 0)} |",
            f"| 表格 | {bt.get('table', 0)} |",
            f"| 图片 | {bt.get('image', 0)} |",
            f"| 指标行 | {bt.get('indicator', 0)} |",
            f"| **合计** | **{self.total}** |",
            "",
            "## 转入统计",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 已转入 | {self.covered_count}/{self.total} |",
            f"| 未转入 | {len(self.uncovered)} |",
            f"| **覆盖率** | **{pct:.1f}%** |",
            "",
        ]

        if self.unreferenced_output_media:
            lines += [
                "## 输出包未引用媒体（不计入覆盖）",
                "",
                *[f"- `{path}`" for path in self.unreferenced_output_media],
                "",
            ]

        if self.excluded_structural_headings:
            lines += [
                "## 来源结构标题（不计入覆盖分母）",
                "",
                *[
                    f"- [{item.get('block_id', '')}] {item.get('text', '')}"
                    for item in self.excluded_structural_headings
                ],
                "",
            ]

        if self.passed():
            lines += ["## ✅ 质量门禁：通过（输入内容全部转入）", ""]
        else:
            lines += [
                f"## ❌ 质量门禁：未通过（{len(self.uncovered)} 块未转入）",
                "",
            ]
            for b in self.uncovered:
                lines.append(
                    f"- [{b.block_id}] {b.block_type} | 来源：{b.source_section} | {b.summary[:60]}"
                )
            lines.append("")

        inds = self.indicator_blocks
        if inds:
            lines += [
                f"## 技术指标追踪（共 {len(inds)} 条）",
                "",
                "| ID | 摘要 | 目标章节 | 输出正文索引 | 状态 |",
                "|----|------|----------|--------------|------|",
            ]
            for b in inds:
                status = "✅" if b.covered else "❌ 未转入"
                lines.append(
                    f"| {b.block_id} | {b.summary[:50]} | {b.assigned_section or '—'} | "
                    f"{','.join(map(str, b.output_body_indices)) or '—'} | {status} |"
                )
            lines.append("")

        return "\n".join(lines)


# ── 解析器 ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _BodyNodeEvidence:
    body_index: int
    kind: str
    text: str
    normalized_text: str
    slot: str
    table_json: str = ""


@dataclass(frozen=True)
class _ImageEvidence:
    body_index: int
    image_index: int
    relationship_id: str
    media_path: str
    artifact_hash: str
    slot: str
    caption: str = ""
    caption_body_index: int = -1
    caption_order: str = ""

    @property
    def evidence_hash(self) -> str:
        payload = json.dumps(
            {
                "body_index": self.body_index,
                "image_index": self.image_index,
                "relationship_id": self.relationship_id,
                "media_path": self.media_path,
                "artifact_hash": self.artifact_hash,
                "slot": self.slot,
                "caption": _coverage_text(self.caption),
                "caption_body_index": self.caption_body_index,
                "caption_order": self.caption_order,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class _DocumentFacts:
    root: object
    body: object
    nodes: List[_BodyNodeEvidence]
    images: List[_ImageEvidence]
    full_text: str
    unreferenced_media: List[str]


def _caption_text(text: str) -> str:
    value = (text or "").strip()
    return value if re.match(r"^(?:图\s*\d+|Fig\.?\s*\d+)(?=\D|$)", value, re.I) else ""


def _media_part_path(target: str) -> str:
    target = (target or "").replace("\\", "/")
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    return posixpath.normpath(posixpath.join("word", target))


def _document_facts(docx_path: str) -> _DocumentFacts:
    """Read only media proven by visible ``document.xml`` body references."""
    with zipfile.ZipFile(docx_path) as package:
        names = set(package.namelist())
        root = etree.fromstring(package.read("word/document.xml"))
        body = root.find(f".//{_W}body")
        if body is None:
            body = root

        media_by_rid: Dict[str, tuple[str, str]] = {}
        rel_path = "word/_rels/document.xml.rels"
        if rel_path in names:
            rel_root = etree.fromstring(package.read(rel_path))
            for rel in rel_root:
                rid = rel.get("Id", "")
                target = rel.get("Target", "")
                rel_type = rel.get("Type", "")
                if (
                    not rid
                    or not target
                    or "image" not in rel_type
                    or rel.get("TargetMode", "").lower() == "external"
                ):
                    continue
                media_path = _media_part_path(target)
                if media_path in names:
                    media_by_rid[rid] = (
                        media_path,
                        hashlib.sha256(package.read(media_path)).hexdigest(),
                    )

        children = list(body)
        body_texts = [
            _para_text(child) if child.tag == _wtag("p") else _table_summary(child)
            if child.tag == _wtag("tbl") else ""
            for child in children
        ]
        body_rids = [_relationship_ids(child) for child in children]

        slots: list[str] = []
        current_slot = "（文档开头）"
        nodes: list[_BodyNodeEvidence] = []
        for body_index, child in enumerate(children):
            text = body_texts[body_index]
            if _is_heading(child, text) and text:
                current_slot = _semantic_heading(text) or text
            slots.append(current_slot)
            if child.tag == _wtag("p"):
                kind = "paragraph"
                table_json = ""
            elif child.tag == _wtag("tbl"):
                kind = "table"
                table_json = _table_to_json(child)
                # For evidence matching use all table cells, not the report
                # summary which is intentionally truncated.
                try:
                    node_text = "".join(
                        str(cell)
                        for row in json.loads(table_json)
                        for cell in row
                    )
                except (TypeError, json.JSONDecodeError):
                    node_text = text
                text = node_text
            else:
                kind = "other"
                table_json = ""
            nodes.append(
                _BodyNodeEvidence(
                    body_index=body_index,
                    kind=kind,
                    text=text,
                    normalized_text=_coverage_text(text),
                    slot=current_slot,
                    table_json=table_json,
                )
            )

        def adjacent_caption(body_index: int) -> tuple[str, int, str]:
            same = _caption_text(body_texts[body_index])
            if same:
                return same, body_index, "same"
            # Empty paragraphs are layout-only.  The first meaningful body
            # node on either side is the only admissible adjacent caption.
            for candidate in range(body_index + 1, len(children)):
                if not body_texts[candidate] and not body_rids[candidate]:
                    continue
                caption = _caption_text(body_texts[candidate])
                if caption:
                    return caption, candidate, "after"
                break
            for candidate in range(body_index - 1, -1, -1):
                if not body_texts[candidate] and not body_rids[candidate]:
                    continue
                caption = _caption_text(body_texts[candidate])
                if caption:
                    return caption, candidate, "before"
                break
            return "", -1, ""

        images: list[_ImageEvidence] = []
        referenced_media_paths: set[str] = set()
        image_index = 0
        for body_index, rids in enumerate(body_rids):
            for rid in rids:
                part = media_by_rid.get(rid)
                if part is None:
                    # A dangling/linked/non-image relationship is not image
                    # evidence and must not enter the coverage hash set.
                    continue
                media_path, artifact_hash = part
                image_index += 1
                caption, caption_index, caption_order = adjacent_caption(body_index)
                referenced_media_paths.add(media_path)
                images.append(
                    _ImageEvidence(
                        body_index=body_index,
                        image_index=image_index,
                        relationship_id=rid,
                        media_path=media_path,
                        artifact_hash=artifact_hash,
                        slot=slots[body_index],
                        caption=caption,
                        caption_body_index=caption_index,
                        caption_order=caption_order,
                    )
                )

        all_media_paths = sorted(
            name for name in names if name.startswith("word/media/") and not name.endswith("/")
        )
        unreferenced = [
            name for name in all_media_paths if name not in referenced_media_paths
        ]

    return _DocumentFacts(
        root=root,
        body=body,
        nodes=nodes,
        images=images,
        full_text=_coverage_text("".join(node.text for node in nodes)),
        unreferenced_media=unreferenced,
    )

def parse_docx_to_ledger(docx_path: str) -> CoverageLedger:
    """把 docx 解析成 CoverageLedger，段落/表格/图片/指标行全部追踪。"""
    ledger = CoverageLedger(source_file=str(docx_path))
    para_idx = table_idx = img_idx = ind_idx = 0
    current_section = "（文档开头）"
    signature_zone = False

    facts = _document_facts(docx_path)
    body = facts.body
    images_by_body_index: Dict[int, List[_ImageEvidence]] = {}
    for image in facts.images:
        images_by_body_index.setdefault(image.body_index, []).append(image)

    for body_index, child in enumerate(body):
        tag = child.tag

        if tag == _wtag("p"):
            text = _para_text(child)
            is_heading = _is_heading(child, text)

            if is_heading and len(text) < 80:
                current_section = text[:60]
                signature_zone = False

            # 跳过封面/变更记录/纯标题行等模板结构段
            if _TEMPLATE_SKIP.search(text) and len(text) < 60:
                continue
            # 跳过纯章节标题（只有编号+标题文字，无实质内容）
            if is_heading and len(text) < 80:
                continue

            body_images = images_by_body_index.get(body_index, [])
            if body_images:
                if signature_zone:
                    continue
                for image in body_images:
                    img_idx += 1
                    caption = image.caption or (text[:60] if text else f"图片{img_idx}")
                    ledger.blocks.append(InputBlock(
                        block_id=f"TR-IMG-{img_idx:03d}",
                        block_type="image",
                        source_section=current_section,
                        summary=caption,
                        raw_text=caption,
                        artifact_hash=image.artifact_hash,
                        image_caption=image.caption,
                        image_caption_order=image.caption_order,
                    ))
                # Image runs may contain alt/caption text, but that text is
                # already bound to the image evidence and must not become a
                # second independent source block.
                continue

            if _has_drawing(child):
                # The XML claims to contain an image, but the relationship is
                # missing/external or its package part does not exist.  Keep a
                # blocking image record with no hash rather than accepting it
                # by filename or by a loose drawing-node check.
                img_idx += 1
                caption = text[:60] if text else f"图片{img_idx}"
                ledger.blocks.append(InputBlock(
                    block_id=f"TR-IMG-{img_idx:03d}",
                    block_type="image",
                    source_section=current_section,
                    summary=caption,
                    raw_text=caption,
                    artifact_hash="",
                    image_caption=_caption_text(caption),
                ))
                continue

            if not text:
                continue

            # 文档首页的名称不是一条技术需求；章节序号变化时也不应把它当作待映射正文。
            if (current_section == "（文档开头）" and len(text) < 60
                    and any(text.endswith(suffix) for suffix in (
                        "技术要求", "技术协议", "产品规格书", "沟通说明书"
                    ))):
                continue

            # 标准清单中的“振动试验、可靠性”等词只是标准名称，不是
            # 用户指标。过去仅凭关键词会把 GJB 标准行误记为 TR-IND，
            # 进而造成虚假的输入覆盖缺口。指标表仍由结构化抽取器负责；
            # 覆盖账本只在正文指标语境中保留 indicator 类型。
            is_standard_reference = bool(
                _STANDARD_REFERENCE_LINE.search(text)
                or _STANDARDS_SECTION.search(_semantic_heading(current_section))
            )
            if _IND_KEYWORDS.search(text) and not is_standard_reference:
                ind_idx += 1
                ledger.blocks.append(InputBlock(
                    block_id=f"TR-IND-{ind_idx:03d}",
                    block_type="indicator",
                    source_section=current_section,
                    summary=text[:120],
                    raw_text=text,
                    is_indicator=True,
                ))
                continue

            # 跳过合同/协议签署条款（不属于技术要求，无需追踪覆盖）
            if any(kw in text for kw in ["一式贰份", "友好协商", "甲乙双方各保存", "技术协调单"]):
                continue

            para_idx += 1
            ledger.blocks.append(InputBlock(
                block_id=f"TR-PARA-{para_idx:03d}",
                block_type="paragraph",
                source_section=current_section,
                summary=text[:120],
                raw_text=text,
            ))

        elif tag == _wtag("tbl"):
            raw = _table_to_json(child)
            if (
                any(marker in raw for marker in ("使用单位签署", "使用单位签字"))
                and any(
                    marker in raw
                    for marker in ("研制单位签署", "研制或试制单位签署", "签字/盖章")
                )
            ):
                # 签字盖章区不是技术正文，不参与语义搬运或覆盖率统计。
                signature_zone = True
                continue
            # Images embedded in table cells are first-class source evidence.
            for image in images_by_body_index.get(body_index, []):
                img_idx += 1
                caption = image.caption or f"图片{img_idx}"
                ledger.blocks.append(InputBlock(
                    block_id=f"TR-IMG-{img_idx:03d}",
                    block_type="image",
                    source_section=current_section,
                    summary=caption,
                    raw_text=caption,
                    artifact_hash=image.artifact_hash,
                    image_caption=image.caption,
                    image_caption_order=image.caption_order,
                ))
            table_idx += 1
            summary = _table_summary(child)
            # 跳过封面表（包含产品名称/使用单位/研制单位字样且行数少）
            if any(kw in raw for kw in ["产品名称", "使用单位", "研制单位", "中航光电科技", "密级", "研制阶段"]) \
                    and raw.count("[[") <= 4:
                continue
            # 跳过变更记录表（第一行含"版本"和"章条编号"）
            if "版本" in raw and "章条编号" in raw:
                continue
            has_ind = bool(_IND_KEYWORDS.search(raw))
            ledger.blocks.append(InputBlock(
                block_id=f"TR-TABLE-{table_idx:03d}",
                block_type="table",
                source_section=current_section,
                summary=summary,
                raw_text=raw,
                is_indicator=has_ind,
            ))

    return ledger


def _output_facts(docx_path: str) -> _DocumentFacts:
    """Return body-indexed output facts and relationship-proven images.

    Merely carrying a binary under ``word/media`` is deliberately not part of
    the image fact set.  The binary must be the target of an image relationship
    that is referenced by a visible node in ``word/document.xml``.
    """
    return _document_facts(docx_path)


def _table_is_present(raw_json: str, output_text: str) -> bool:
    try:
        rows = json.loads(raw_json)
    except (TypeError, json.JSONDecodeError):
        return False
    cells = [_coverage_text(str(cell)) for row in rows for cell in row if str(cell).strip()]
    if not cells:
        return False
    flattened = "".join(cells)
    if flattened and flattened in output_text:
        return True
    # Word 合并单元格可能改变重复表头顺序。保守地要求所有含数字单元格、
    # 且至少 90% 的非空单元格在输出中出现。
    hits = [cell in output_text for cell in cells]
    numeric_cells = [cell for cell in cells if re.search(r"\d", cell)]
    distinctive_cells = [cell for cell in cells if len(cell) >= 4]
    numeric_ok = all(cell in output_text for cell in numeric_cells)
    distinctive_ok = bool(distinctive_cells) and any(
        cell in output_text for cell in distinctive_cells
    )
    return distinctive_ok and numeric_ok and sum(hits) / len(hits) >= 0.90


def _table_matches_node(raw_json: str, node: _BodyNodeEvidence) -> bool:
    return node.kind == "table" and _table_is_present(raw_json, node.normalized_text)


def _text_evidence_hash(
    block_id: str,
    slot: str,
    indices: Sequence[int],
    nodes: Sequence[_BodyNodeEvidence],
) -> str:
    node_by_index = {node.body_index: node for node in nodes}
    payload = {
        "source_id": block_id,
        "slot": slot,
        "body_indices": list(indices),
        "body_hashes": [
            hashlib.sha256(node_by_index[index].normalized_text.encode("utf-8")).hexdigest()
            for index in indices
            if index in node_by_index
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _reset_output_evidence(block: InputBlock) -> None:
    block.covered = False
    block.action = ""
    block.assigned_section = ""
    block.confidence = 0.0
    block.output_slot = ""
    block.output_body_indices = []
    block.output_relationship_id = ""
    block.output_artifact_hash = ""
    block.output_caption = ""
    block.output_caption_body_index = -1
    block.output_caption_order = ""
    block.output_evidence_hash = ""


def mark_covered_from_output(ledger: CoverageLedger, out_path: str) -> CoverageLedger:
    """用输出中的真实原文/表格/媒体证据标记覆盖，绝不默认兜底为已覆盖。"""
    facts = _output_facts(out_path)
    ledger.unreferenced_output_media = list(facts.unreferenced_media)
    used_image_evidence: set[int] = set()
    used_body_evidence: set[int] = set()

    for block in ledger.blocks:
        _reset_output_evidence(block)
        matched_indices: list[int] = []
        matched_slot = ""

        if block.block_type == "image":
            candidates = [
                image
                for image in facts.images
                if image.image_index not in used_image_evidence
                and block.artifact_hash
                and image.artifact_hash == block.artifact_hash
            ]
            if block.image_caption:
                source_caption = _coverage_text(block.image_caption)
                candidates = [
                    image
                    for image in candidates
                    if image.caption
                    and _coverage_text(image.caption) == source_caption
                    and (
                        not block.image_caption_order
                        or image.caption_order == block.image_caption_order
                    )
                ]
            image = candidates[0] if candidates else None
            covered = image is not None
            if image is not None:
                used_image_evidence.add(image.image_index)
                matched_slot = image.slot
                matched_indices = [image.body_index]
                block.output_slot = image.slot
                block.output_body_indices = [image.body_index]
                block.output_relationship_id = image.relationship_id
                block.output_artifact_hash = image.artifact_hash
                block.output_caption = image.caption
                block.output_caption_body_index = image.caption_body_index
                block.output_caption_order = image.caption_order
                block.output_evidence_hash = image.evidence_hash
        elif block.block_type == "table":
            node = next(
                (
                    candidate
                    for candidate in facts.nodes
                    if candidate.body_index not in used_body_evidence
                    and _table_matches_node(block.raw_text, candidate)
                ),
                None,
            )
            covered = node is not None
            if node is not None:
                used_body_evidence.add(node.body_index)
                matched_indices = [node.body_index]
                matched_slot = node.slot
        else:
            raw = _coverage_text(block.raw_text or "")
            node = next(
                (
                    candidate
                    for candidate in facts.nodes
                    if candidate.body_index not in used_body_evidence
                    # Source prose must be proved by prose evidence.  Otherwise
                    # a short source paragraph such as "无。" normalizes to
                    # "无" and can reserve an unrelated table containing
                    # "无磕碰伤", preventing the actual source table from
                    # being checked against its own output table.
                    and candidate.kind == "paragraph"
                    and raw
                    and raw in candidate.normalized_text
                ),
                None,
            )
            covered = node is not None
            if node is not None:
                used_body_evidence.add(node.body_index)
                matched_indices = [node.body_index]
                matched_slot = node.slot
            if not covered and raw:
                # 一个原文段落可按模板的子条目拆成多段（例如“随产品
                # 提供说明书、备件”）。只有当两个以上原文子句全部在输出中
                # 逐句出现、且文档顺序一致时才认定覆盖。
                clauses = [
                    _coverage_text(clause)
                    for clause in re.split(r"[、；;\n]+", block.raw_text or "")
                    if len(_coverage_text(clause)) >= 4
                ]
                clause_nodes: list[_BodyNodeEvidence] = []
                search_after = -1
                for clause in clauses:
                    clause_node = next(
                        (
                            candidate
                            for candidate in facts.nodes
                            if candidate.body_index > search_after
                            and candidate.body_index not in used_body_evidence
                            and candidate.kind == "paragraph"
                            and clause in candidate.normalized_text
                        ),
                        None,
                    )
                    if clause_node is None:
                        clause_nodes = []
                        break
                    clause_nodes.append(clause_node)
                    search_after = clause_node.body_index
                if len(clause_nodes) >= 2:
                    unique_indices = list(dict.fromkeys(node.body_index for node in clause_nodes))
                    used_body_evidence.update(unique_indices)
                    covered = True
                    matched_indices = unique_indices
                    matched_slot = clause_nodes[0].slot
            if not covered and raw:
                # 技术指标段允许拆成多行结构化指标，但每个数值事实必须仍在
                # 输出中出现。这里只接受至少两个且全部命中的“数字+单位/阈值”
                # 证据，不能用章节计划或宽松关键词虚构覆盖。
                metric_tokens = list(dict.fromkeys(re.findall(
                    r"(?:[≤≥<>]|不小于|不大于|不超过)?\s*\d+(?:\.\d+)?(?:\s*[~～]\s*\d+(?:\.\d+)?)?\s*(?:芯|A|mA|V|N|g|kg|Kg|s|Hz|℃|次|mm|°)",
                    block.raw_text or "",
                    re.I,
                )))
                normalized_tokens = [re.sub(r"\s+", "", token) for token in metric_tokens]
                token_indices: list[int] = []
                for token in normalized_tokens:
                    token_node = next(
                        (
                            candidate
                            for candidate in facts.nodes
                            if token in candidate.normalized_text
                        ),
                        None,
                    )
                    if token_node is None:
                        token_indices = []
                        break
                    token_indices.append(token_node.body_index)
                unique_indices = list(dict.fromkeys(token_indices))
                covered = (
                    len(normalized_tokens) >= 2
                    and bool(unique_indices)
                    and not any(index in used_body_evidence for index in unique_indices)
                )
                if covered:
                    used_body_evidence.update(unique_indices)
                    matched_indices = unique_indices
                    matched_slot = next(
                        candidate.slot
                        for candidate in facts.nodes
                        if candidate.body_index == unique_indices[0]
                    )
            if not covered and block.raw_text:
                m = re.match(r"^((?:GJB|GB/T|GB|Q/\w+|KJB|MIL|SAE)\s*[\w./\-]+)", block.raw_text.strip())
                if m:
                    std_id = re.sub(r"\s+", "", m.group(1))
                    node = next(
                        (
                            candidate
                            for candidate in facts.nodes
                            if candidate.body_index not in used_body_evidence
                            and std_id
                            and std_id in candidate.normalized_text
                        ),
                        None,
                    )
                    covered = node is not None
                    if node is not None:
                        used_body_evidence.add(node.body_index)
                        matched_indices = [node.body_index]
                        matched_slot = node.slot
        if covered:
            block.covered = True
            block.action = "placed"
            block.assigned_section = matched_slot or "输出文档（原文证据匹配）"
            block.confidence = 1.0
            if block.block_type != "image":
                block.output_slot = matched_slot
                block.output_body_indices = matched_indices
                block.output_evidence_hash = _text_evidence_hash(
                    block.block_id,
                    matched_slot,
                    matched_indices,
                    facts.nodes,
                )
    return ledger


def exclude_semantic_structure_headings(
    ledger: CoverageLedger,
    classification: dict | None,
) -> List[Dict[str, str]]:
    """Align the coverage denominator with the governed source structure.

    The semantic source parser intentionally removes headings from
    ``source_blocks``.  The deterministic coverage parser cannot recognize
    every unnumbered heading stored with Word's Normal style, so without this
    reconciliation the same paragraph can be treated as structure by the
    planner and as writable body text by QA.  Only exact heading-text matches
    absent from ``source_blocks`` are excluded, and every exclusion remains in
    the ledger as explicit audit evidence.
    """
    if not isinstance(classification, dict):
        return []

    source_texts = {
        _coverage_text(str(item.get("text", "")))
        for item in classification.get("source_blocks", []) or []
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    }
    heading_candidates: Dict[str, List[dict]] = {}
    for chapter in classification.get("source_chapters", []) or []:
        if not isinstance(chapter, dict):
            continue
        text = str(chapter.get("section") or chapter.get("heading_text") or "").strip()
        key = _coverage_text(text)
        if not key or key in source_texts:
            continue
        heading_candidates.setdefault(key, []).append(chapter)

    if not heading_candidates:
        return []

    excluded: List[Dict[str, str]] = []
    kept: List[InputBlock] = []
    for block in ledger.blocks:
        key = _coverage_text(block.raw_text)
        candidates = heading_candidates.get(key, [])
        if block.block_type != "paragraph" or not candidates:
            kept.append(block)
            continue
        chapter = candidates.pop(0)
        excluded.append({
            "block_id": block.block_id,
            "text": block.raw_text,
            "source_section": block.source_section,
            "semantic_chapter_id": str(chapter.get("id", "")),
            "reason": "semantic_source_structure_heading",
        })

    ledger.blocks = kept
    existing_ids = {
        str(item.get("block_id", ""))
        for item in ledger.excluded_structural_headings
        if isinstance(item, dict)
    }
    ledger.excluded_structural_headings.extend(
        item for item in excluded if item["block_id"] not in existing_ids
    )
    return excluded


def mark_exact_fragment_coverage(
    ledger: CoverageLedger,
    out_path: str,
    classification_path: str | Path | None = None,
) -> CoverageLedger:
    """Prove coverage for losslessly partitioned source paragraphs.

    A mixed paragraph may be routed to several semantic slots.  It is covered
    only when (a) its sidecar fragments are contiguous and reconstruct the
    original paragraph exactly and (b) every exact fragment is present in a
    distinct visible output body node.  A route plan by itself is never
    accepted as evidence.
    """
    sidecar = Path(classification_path) if classification_path else Path(out_path).with_suffix(
        ".requirement_classification.json"
    )
    if not sidecar.is_file():
        return ledger
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ledger
    source_blocks = {
        str(block.get("id")): block
        for block in payload.get("source_blocks", [])
        if isinstance(block, dict) and block.get("id")
    }
    facts = _output_facts(out_path)
    claimed_indices: set[int] = set()
    for partition in payload.get("fragment_partitions", []) or []:
        if not isinstance(partition, dict) or not partition.get("reconstructed_exactly"):
            continue
        fragments = [
            source_blocks.get(str(source_id), {})
            for source_id in partition.get("fragment_source_ids", []) or []
        ]
        if len(fragments) < 2 or any(not fragment for fragment in fragments):
            continue
        fragments.sort(key=lambda item: int(item.get("source_span_start", -1)))
        cursor = 0
        valid_partition = True
        reconstructed_parts: list[str] = []
        for fragment in fragments:
            start = int(fragment.get("source_span_start", -1))
            end = int(fragment.get("source_span_end", -1))
            text = str(fragment.get("text", ""))
            if start != cursor or end != start + len(text) or end <= start:
                valid_partition = False
                break
            reconstructed_parts.append(text)
            cursor = end
        if not valid_partition:
            continue
        reconstructed = "".join(reconstructed_parts)
        source_block = next(
            (
                block for block in ledger.blocks
                if not block.covered
                and block.block_type == "paragraph"
                and _coverage_text(block.raw_text) == _coverage_text(reconstructed)
            ),
            None,
        )
        if source_block is None:
            continue
        matched_nodes: list[_BodyNodeEvidence] = []
        local_indices: set[int] = set()
        for fragment in fragments:
            normalized = _coverage_text(str(fragment.get("text", "")))
            node = next(
                (
                    candidate for candidate in facts.nodes
                    if candidate.kind == "paragraph"
                    and candidate.body_index not in claimed_indices
                    and candidate.body_index not in local_indices
                    and normalized
                    and normalized == candidate.normalized_text
                ),
                None,
            )
            if node is None:
                matched_nodes = []
                break
            matched_nodes.append(node)
            local_indices.add(node.body_index)
        if len(matched_nodes) != len(fragments):
            continue
        claimed_indices.update(local_indices)
        source_block.covered = True
        source_block.action = "placed_exact_fragments"
        source_block.assigned_section = " / ".join(
            dict.fromkeys(node.slot for node in matched_nodes if node.slot)
        )
        source_block.confidence = min(
            float(fragment.get("confidence", 1.0) or 1.0)
            for fragment in fragments
        )
        source_block.output_slot = source_block.assigned_section
        source_block.output_body_indices = [node.body_index for node in matched_nodes]
        source_block.output_evidence_hash = _text_evidence_hash(
            source_block.block_id,
            source_block.output_slot,
            source_block.output_body_indices,
            facts.nodes,
        )
    return ledger


def mark_structured_indicator_coverage(
    ledger: CoverageLedger,
    out_path: str,
) -> CoverageLedger:
    """Credit an audited many-to-one indicator-table transformation.

    Several source indicators may be written into one output table node.  The
    ordinary exact-copy matcher reserves a body node for one source block, so
    it cannot express that transformation.  This path still requires a passed
    per-artifact indicator audit plus the semantic label and exact source fact
    in the final output table.
    """
    audit_path = Path(out_path).with_suffix(".indicator_audit.json")
    if not audit_path.is_file():
        return ledger
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return ledger
    if not audit.get("passed"):
        return ledger

    input_names = [
        str(value).strip()
        for value in audit.get("input_indicator_names", [])
        if str(value).strip()
    ]
    output_names = {
        str(value).strip()
        for value in audit.get("output_indicator_names", [])
        if str(value).strip()
    }
    if not input_names or not output_names:
        return ledger
    source_heading_aliases = {
        str(source).strip(): str(target).strip()
        for source, target in (audit.get("source_heading_aliases") or {}).items()
        if str(source).strip() and str(target).strip()
    }
    comparison_decisions = [
        item
        for item in audit.get("comparison_decisions", [])
        if isinstance(item, dict)
    ]

    # The coverage parser and the semantic classifier intentionally use
    # different stable ID namespaces (``TR-*`` versus ``tech-p-*``).  Build a
    # content-addressed crosswalk instead of comparing those IDs directly.
    # This lets an audited indicator atom point back to the exact source
    # paragraph without coupling either parser to the other's numbering.
    classification_blocks: dict[str, str] = {}
    for suffix in (
        ".effective_requirement_classification.json",
        ".requirement_classification.json",
    ):
        classification_path = Path(out_path).with_suffix(suffix)
        if not classification_path.is_file():
            continue
        try:
            classification = json.loads(
                classification_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        for item in classification.get("source_blocks", []) or []:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("id", "")).strip()
            source_text = _coverage_text(str(item.get("text", "")))
            if source_id and source_text:
                classification_blocks[source_id] = source_text

    facts = _output_facts(out_path)
    table_nodes = [node for node in facts.nodes if node.kind == "table"]
    audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()

    for block in ledger.uncovered:
        if block.block_type in {"image", "table"}:
            continue
        semantic_heading = _semantic_heading(block.source_section)
        label = source_heading_aliases.get(semantic_heading, "") or next(
            (
                name
                for name in input_names
                if name in semantic_heading or semantic_heading.endswith(name)
            ),
            "",
        )
        if not label:
            continue
        candidate_labels = {
            label,
            *(
                name
                for name in output_names
                if name == label or name in semantic_heading or label in name
            ),
        }
        source_fact = _coverage_text(block.raw_text)
        # A design-input paragraph frequently contains both a test method and
        # one concise indicator fact.  The indicator table must contain only
        # that fact, not the complete method paragraph.  Credit this controlled
        # atomisation only when the passed audit, the source paragraph and the
        # final table all agree on the exact same verbatim atom.  This is
        # intentionally stricter than a semantic/keyword match and therefore
        # cannot turn a generated or modified value into coverage evidence.
        audited_atom_match = None
        for decision in comparison_decisions:
            decision_label = str(decision.get("indicator_name", "")).strip()
            if decision_label not in candidate_labels:
                continue
            user_atom = _coverage_text(str(decision.get("user_requirement", "")))
            if not user_atom:
                continue
            source_ids = [
                str(value).strip()
                for value in decision.get("user_source_ids", []) or []
                if str(value).strip()
            ]
            exact_source_anchor = any(
                classification_blocks.get(source_id) == source_fact
                for source_id in source_ids
            )
            atom_metric_tokens = list(dict.fromkeys(
                re.sub(r"\s+", "", token)
                for token in re.findall(
                    r"(?:[≤≥<>]|不小于|不大于|不超过)?\s*"
                    r"\d+(?:\.\d+)?(?:\s*[~～]\s*\d+(?:\.\d+)?)?\s*"
                    r"(?:MΩ|mΩ|Ω|芯|A|mA|V|N|g|kg|Kg|s|Hz|℃|次|mm|°)",
                    str(decision.get("user_requirement", "")),
                    re.I,
                )
            ))
            atom_is_source_backed = user_atom in source_fact or (
                exact_source_anchor
                and bool(atom_metric_tokens)
                and all(token in source_fact for token in atom_metric_tokens)
            )
            if not atom_is_source_backed:
                continue
            node = next(
                (
                    candidate
                    for candidate in table_nodes
                    if _coverage_text(decision_label) in candidate.normalized_text
                    and user_atom in candidate.normalized_text
                ),
                None,
            )
            if node is not None:
                audited_atom_match = (decision, user_atom, node)
                break
        if audited_atom_match is not None:
            decision, user_atom, node = audited_atom_match
            block.covered = True
            block.action = "structured_indicator_atom"
            block.assigned_section = node.slot or "技术指标（结构化表格）"
            block.confidence = 1.0
            block.output_slot = node.slot
            block.output_body_indices = [node.body_index]
            block.output_evidence_hash = hashlib.sha256(
                json.dumps(
                    {
                        "source_id": block.block_id,
                        "classification_source_ids": decision.get(
                            "user_source_ids", []
                        ),
                        "source_text": source_fact,
                        "evidence_mode": (
                            "audited_exact_source_atom"
                            if user_atom in source_fact
                            else "audited_classification_source_crosswalk"
                        ),
                        "source_atom": user_atom,
                        "source_metric_tokens": atom_metric_tokens,
                        "indicator_label": decision.get("indicator_name", label),
                        "adopted_requirement": decision.get(
                            "adopted_requirement", ""
                        ),
                        "output_body_index": node.body_index,
                        "indicator_audit_sha256": audit_hash,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            continue
        metric_tokens = list(dict.fromkeys(
            re.sub(r"\s+", "", token)
            for token in re.findall(
                r"(?:[≤≥<>]|不小于|不大于|不超过)?\s*"
                r"\d+(?:\.\d+)?(?:\s*[~～]\s*\d+(?:\.\d+)?)?\s*"
                r"(?:芯|A|mA|V|N|g|kg|Kg|s|Hz|℃|次|mm|°)",
                block.raw_text or "",
                re.I,
            )
        ))
        node = next(
            (
                candidate
                for candidate in table_nodes
                if any(
                    _coverage_text(candidate_label) in candidate.normalized_text
                    for candidate_label in candidate_labels
                )
                and (
                    (source_fact and source_fact in candidate.normalized_text)
                    or (
                        len(metric_tokens) >= 2
                        and all(
                            token in candidate.normalized_text
                            for token in metric_tokens
                        )
                    )
                )
            ),
            None,
        )
        if node is None:
            continue
        block.covered = True
        exact_fact = bool(source_fact and source_fact in node.normalized_text)
        block.action = (
            "structured_indicator"
            if exact_fact
            else "structured_indicator_fragments"
        )
        block.assigned_section = node.slot or "技术指标（结构化表格）"
        block.confidence = 1.0
        block.output_slot = node.slot
        block.output_body_indices = [node.body_index]
        block.output_evidence_hash = hashlib.sha256(
            json.dumps(
                {
                    "source_id": block.block_id,
                    "source_text": source_fact,
                    "evidence_mode": "exact" if exact_fact else "all_metric_tokens",
                    "metric_tokens": metric_tokens,
                    "indicator_label": label,
                    "output_body_index": node.body_index,
                    "indicator_audit_sha256": audit_hash,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
    return ledger


# ── 标记工具（供 extract_sections 调用） ─────────────────────────────────────

def mark_covered(ledger: CoverageLedger, block_id: str,
                 assigned_section: str, confidence: float,
                 action: str = "placed"):
    for b in ledger.blocks:
        if b.block_id == block_id:
            b.assigned_section = assigned_section
            b.confidence = confidence
            b.action = action
            b.covered = True
            return


def mark_all_covered(ledger: CoverageLedger, assigned_section: str,
                     confidence: float = 1.0, action: str = "placed"):
    for b in ledger.blocks:
        if not b.covered:
            b.assigned_section = assigned_section
            b.confidence = confidence
            b.action = action
            b.covered = True


