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
from typing import Any, Dict, List, Sequence
from lxml import etree
import yaml
from .figure_pairing import pair_figure_captions
from .source_scope import (
    has_substantive_heading_content,
    is_source_heading,
    source_exclusion_reasons,
    source_heading_label,
    normalize_source_display_text,
    review_reference_source_details,
)
from .standard_references import extract_standard_references, is_reference_heading
from .indicator_identity import canonical_indicator_name
from .environmental_prose import is_environmental_slot, project_environmental_evidence

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
    return is_source_heading(element, text)


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
_IMG_CAPTION = re.compile(r"图\s*\d+|Fig\.", re.I)

# ── 数据结构 ──────────────────────────────────────────────────────────────────


def _coverage_text(text: str) -> str:
    """Normalize non-technical document numbering for evidence matching.

    Semantic routing can change the final order of figures, so postprocessing
    is allowed to renumber ``图N`` captions and their explicit references.
    The figure ordinal is not a technical fact; every other number, unit and
    threshold remains part of the exact coverage evidence.
    """
    compact = normalize_source_display_text(text)
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
    source_body_index: int = -1
    output_fragment_evidence: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CoverageLedger:
    source_file: str
    blocks: List[InputBlock] = field(default_factory=list)
    # LLM/Word structure detection may recognize an unnumbered Normal-style
    # paragraph as a chapter heading.  Such structural text is audited here,
    # but it is not a writable requirement and therefore does not belong in
    # the exact-copy coverage denominator.
    excluded_structural_headings: List[Dict[str, str]] = field(default_factory=list)
    # Business rules can require keeping the target template instead of copying
    # a source block. Preserve the complete source evidence without claiming
    # that it was written or counting it in the exact-copy denominator.
    excluded_rule_sources: list[dict[str, Any]] = field(default_factory=list)
    # Historical measurement artifacts are retained for review, not claimed as
    # copied requirements. Keep their exact source coordinates and media hash.
    review_only_sources: list[dict[str, Any]] = field(default_factory=list)
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
                "excluded_rule_sources": self.excluded_rule_sources,
                "review_only_sources": self.review_only_sources,
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
            excluded_rule_sources=list(data.get("excluded_rule_sources", [])),
            review_only_sources=list(data.get("review_only_sources", [])),
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

        if self.excluded_rule_sources:
            lines += [
                "## 业务规则保留模板（原输入留档，不计入覆盖分母）",
                "",
                *[
                    f"- [{item['block_id']}] body={item['source_body_index']} "
                    f"{item['rule_ref']} | {item['source_section']} | {item['summary']}"
                    for item in self.excluded_rule_sources
                ],
                "",
            ]

        if self.review_only_sources:
            lines += [
                "## 历史测试资料（仅供审阅，不计入正文覆盖率）",
                "",
                *[
                    f"- [{item['block_id']}] {item['source_file']} | "
                    f"正文位置 {item['source_body_index'] + 1} | {item['source_section']} | "
                    f"{item['summary']} | 来源ID：{','.join(item['semantic_source_ids'])}"
                    for item in self.review_only_sources
                ],
                "",
            ]

        if self.passed():
            lines += ["## ✅ 质量门禁：通过（应转入的输入内容全部转入）", ""]
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

        figure_pairs = pair_figure_captions(
            body_texts,
            {index for index, rids in enumerate(body_rids) if rids},
            _caption_text,
        )

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
                caption, caption_index, caption_order = figure_pairs.get(
                    body_index, ("", -1, "")
                )
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

    facts = _document_facts(docx_path)
    body = facts.body
    exclusions = source_exclusion_reasons(list(body))
    images_by_body_index: Dict[int, List[_ImageEvidence]] = {}
    for image in facts.images:
        images_by_body_index.setdefault(image.body_index, []).append(image)

    for body_index, child in enumerate(body):
        if body_index in exclusions:
            continue
        tag = child.tag

        if tag == _wtag("p"):
            text = _para_text(child)
            is_heading = _is_heading(child, text)

            substantive = has_substantive_heading_content(text)
            if is_heading and (not substantive or source_heading_label(text) != text):
                current_section = source_heading_label(text)
            # A numbered clause may contain the complete requirement.  Only
            # pure structural headings may be absent from the coverage ledger.
            if is_heading and not substantive and not _has_drawing(child):
                continue

            body_images = images_by_body_index.get(body_index, [])
            if body_images:
                for image in body_images:
                    img_idx += 1
                    caption = image.caption or (text[:60] if text else f"图片{img_idx}")
                    ledger.blocks.append(InputBlock(
                        block_id=f"TR-IMG-{img_idx:03d}",
                        source_body_index=body_index,
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
                    source_body_index=body_index,
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
                    source_body_index=body_index,
                    block_type="indicator",
                    source_section=current_section,
                    summary=text[:120],
                    raw_text=text,
                    is_indicator=True,
                ))
                continue

            para_idx += 1
            ledger.blocks.append(InputBlock(
                block_id=f"TR-PARA-{para_idx:03d}",
                source_body_index=body_index,
                block_type="paragraph",
                source_section=current_section,
                summary=text[:120],
                raw_text=text,
            ))

        elif tag == _wtag("tbl"):
            raw = _table_to_json(child)
            # Images embedded in table cells are first-class source evidence.
            for image in images_by_body_index.get(body_index, []):
                img_idx += 1
                caption = image.caption or f"图片{img_idx}"
                ledger.blocks.append(InputBlock(
                    block_id=f"TR-IMG-{img_idx:03d}",
                    source_body_index=body_index,
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
            has_ind = bool(_IND_KEYWORDS.search(raw))
            ledger.blocks.append(InputBlock(
                block_id=f"TR-TABLE-{table_idx:03d}",
                source_body_index=body_index,
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
    block.output_fragment_evidence = []


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
        elif (references := extract_standard_references(
            block.raw_text or "", reference_context=is_reference_heading(block.source_section),
        )):
            # A labelled source list is deliberately rendered as individual
            # normative references.  The label is presentation; every complete
            # identifier, title and condition must still have output evidence.
            reference_nodes = []
            for reference in references:
                normalized_reference = _coverage_text(reference)
                reference_node = next((
                    candidate for candidate in facts.nodes
                    if candidate.kind == "paragraph"
                    and normalized_reference in candidate.normalized_text
                ), None)
                if reference_node is None:
                    reference_nodes = []
                    break
                reference_nodes.append(reference_node)
            covered = len(reference_nodes) == len(references)
            if covered:
                matched_indices = list(dict.fromkeys(node.body_index for node in reference_nodes))
                used_body_evidence.update(matched_indices)
                matched_slot = reference_nodes[0].slot
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
            # Structured indicator rows are verified separately, with source
            # coordinates, identity and complete user-cell evidence. Matching
            # numeric tokens elsewhere cannot prove conditions were preserved.
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

    # Parent chapters with no direct content do not appear in source_chapters.
    # Use the parser's position audit for those headings, requiring the same
    # source document and no classified body content at that position.
    audit = classification.get("source_structure_audit") or {}
    audited_positions: set[int] = set()
    if isinstance(audit, dict) and audit.get("source_path") and Path(audit["source_path"]).resolve() == Path(ledger.source_file).resolve():
        body_positions = {
            item.get("body_index") for item in classification.get("source_blocks", []) or []
            if isinstance(item, dict)
        }
        audited_positions = {
            item["body_index"] for item in audit.get("headings", []) or []
            if isinstance(item, dict) and type(item.get("body_index")) is int
            and item.get("action") == "structure_only"
            and item["body_index"] not in body_positions
        }

    if not heading_candidates and not audited_positions:
        return []

    excluded: List[Dict[str, str]] = []
    kept: List[InputBlock] = []
    for block in ledger.blocks:
        key = _coverage_text(block.raw_text)
        candidates = heading_candidates.get(key, [])
        audited_heading = (block.source_body_index in audited_positions
                           and not has_substantive_heading_content(block.raw_text))
        if block.block_type != "paragraph" or not (candidates or audited_heading):
            kept.append(block)
            continue
        chapter = candidates.pop(0) if candidates else {}
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


def exclude_review_reference_sources(
    ledger: CoverageLedger,
    classification: dict | None,
) -> list[dict[str, Any]]:
    """Keep raw historical test artifacts as review references, not requirements.

    Only historical tables/images and unvalued result labels in an explicitly
    identified test-results section qualify. Technical clauses and requirement
    tables elsewhere remain subject to exact-copy/indicator verification.
    File and position must match; neither similar text nor an LLM category
    alone can waive coverage.
    """
    if not isinstance(classification, dict):
        return []
    review_details = review_reference_source_details(classification)
    review_ids = set(review_details)
    source_path = Path(ledger.source_file).resolve()
    sources_by_position: dict[int, list[dict]] = {}
    for source in classification.get("source_blocks", []) or []:
        if not isinstance(source, dict) or source.get("source") != "tech":
            continue
        position = source.get("body_index")
        path = source.get("source_path")
        if type(position) is not int or position < 0 or not path or Path(path).resolve() != source_path:
            continue
        sources_by_position.setdefault(position, []).append(source)

    references, kept = [], []
    for block in ledger.blocks:
        sources = sources_by_position.get(block.source_body_index, [])
        all_review_ids = bool(sources) and all(
            str(source.get("id")) in review_ids for source in sources
        )
        qualifies = all_review_ids and block.block_type in {"table", "image", "paragraph"}
        if not qualifies:
            kept.append(block)
            continue
        references.append({
            **asdict(block),
            "action": "review_reference_only",
            "covered": False,
            "rule_ref": "historical_test_artifacts_review_only",
            "source_file": str(source_path),
            "semantic_source_ids": [str(source["id"]) for source in sources],
            "scope_decisions": [review_details[str(source["id"])] for source in sources],
            "source_section": " / ".join(dict.fromkeys([
                *(str(h) for h in sources[0].get("parent_headings", [])),
                str(sources[0].get("section") or block.source_section),
            ])),
            "reason": (
                "历史测试资料引导段仅供审阅；质量报告保留来源引用，不作为任务书正文缺失"
                if block.block_type == "paragraph" else
                "历史测试图片及原始数据表仅供审阅；质量报告保留来源引用，不作为任务书正文缺失"
            ),
        })
    ledger.blocks = kept
    ledger.review_only_sources.extend(references)
    return references


def exclude_preserved_template_sources(
    ledger: CoverageLedger,
    classification: dict | None,
    category_mapping_path: str | Path | None,
) -> list[dict[str, Any]]:
    """Audit source blocks intentionally not copied under a template-only rule.

    Source document identity and body position are mandatory; equal text in a
    different paragraph cannot inherit the exclusion. Mixed-role source blocks
    remain in coverage unless their exact fragments can be individually proved.
    """
    if not classification or not category_mapping_path:
        return []
    mapping = yaml.safe_load(Path(category_mapping_path).read_text(encoding="utf-8")) or {}
    roles = {
        str(role): rule
        for group in (mapping.get("categories") or {}, mapping.get("semantic_roles") or {})
        for role, rule in group.items()
        if isinstance(rule, dict) and rule.get("write_mode") == "preserve_template"
    }
    if not roles:
        return []
    assignments: dict[str, set[str]] = {}
    for assignment in classification.get("classifications", []):
        if isinstance(assignment, dict) and assignment.get("source_id"):
            assignments.setdefault(str(assignment["source_id"]), set()).add(str(assignment.get("category") or ""))
    source_path = Path(ledger.source_file).resolve()
    source_by_position: dict[int, list[dict]] = {}
    for source in classification.get("source_blocks", []):
        if not isinstance(source, dict):
            continue
        position = source.get("body_index")
        if type(position) is not int or position < 0:
            continue
        path = str(source.get("source_path") or "")
        if not path or Path(path).resolve() != source_path:
            continue
        source_by_position.setdefault(position, []).append(source)

    kept: list[InputBlock] = []
    excluded: list[dict[str, Any]] = []
    for block in ledger.blocks:
        sources = source_by_position.get(block.source_body_index, [])
        categories = [assignments.get(str(source.get("id")), set()) for source in sources]
        # Never exempt a paragraph merely because one of its fragments is a
        # progress clause: all of its independently routed text must qualify.
        if not sources or any(not assigned or not assigned.issubset(roles) for assigned in categories):
            kept.append(block)
            continue
        if any(source.get("parent_source_id") for source in sources):
            fragments = sorted(sources, key=lambda source: int(source.get("source_span_start", -1)))
            reconstructed = ""
            valid = block.block_type in {"paragraph", "indicator"}
            for fragment in fragments:
                text = str(fragment.get("text") or "")
                start, end = fragment.get("source_span_start"), fragment.get("source_span_end")
                if start != len(reconstructed) or end != len(reconstructed) + len(text):
                    valid = False
                    break
                reconstructed += text
            if not valid or _coverage_text(reconstructed) != _coverage_text(block.raw_text):
                kept.append(block)
                continue
        selected_roles = sorted({role for assigned in categories for role in assigned})
        refs = [str(roles[role].get("rule_ref") or ("开发逻辑!C26/D46" if role == "schedule" else "受控模板保留策略")) for role in selected_roles]
        record = {
            **asdict(block),
            "action": "excluded_by_business_rule",
            "covered": False,
            "rule_ref": "、".join(dict.fromkeys(refs)),
            "categories": selected_roles,
            "semantic_source_ids": [str(source.get("id")) for source in sources],
            "source_file": str(source_path),
            "reason": "按业务规则保留目标模板，由设计填写；输入原文留档，不宣称已转入",
        }
        excluded.append(record)
    ledger.blocks = kept
    ledger.excluded_rule_sources.extend(excluded)
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
                and block.block_type in {"paragraph", "indicator"}
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


def _table_requirement_cells(rows: list[list[str]]) -> set[tuple[int, int]]:
    """Only plain column headings and their serial numbers are presentation."""
    headings = {"序号", "项目", "指标", "名称", "项目名称", "指标名称", "技术指标",
                "技术要求", "性能要求", "指标要求", "参数名称", "参数值", "要求"}
    label_headings = {"序号", "项目", "名称", "项目名称", "指标名称", "参数名称"}
    serial_columns: set[int] = set()
    required: set[tuple[int, int]] = set()
    for row_index, row in enumerate(rows):
        values = [_coverage_text(str(cell)) for cell in row]
        # The indicator extractor already recognizes this exact descriptive
        # header pair. It carries column roles, not an additional requirement.
        # Other headings (acceptance criteria, constraints, etc.) remain cells
        # that need their own evidence even when adjacent to this pair.
        descriptive_pair = "技术特性类型" in values and "特性描述" in values
        presentation_headings = headings | ({"技术特性类型", "特性描述"} if descriptive_pair else set())
        if descriptive_pair or any(cell in label_headings for cell in values):
            serial_columns.update(i for i, cell in enumerate(values) if cell == "序号")
            # Thresholds, assessment criteria and adaptation constraints carry
            # meaning. Their headings need visible evidence alongside values.
            required.update((row_index, column) for column, cell in enumerate(values)
                            if cell and cell not in presentation_headings)
            continue
        required.update((row_index, column) for column, cell in enumerate(values)
                        if cell and not (column in serial_columns and re.fullmatch(r"\d+[)）.]?", cell)))
    return required


def _environmental_table_evidence(
    block: InputBlock, rows: list[list[str]], output: _DocumentFacts, claimed: set[int],
) -> tuple[list[dict], set[tuple[int, int]], list[_BodyNodeEvidence], bool]:
    """Reproject source cells, crediting only cells preserved in their entirety."""
    projections = project_environmental_evidence({
        "id": block.block_id, "source": "tech", "type": "table", "table_rows": rows,
        "body_index": block.source_body_index, "heading_text": block.source_section,
    })
    evidence, nodes = [], []
    covered_cells: set[tuple[int, int]] = set()
    local_indices: set[int] = set()
    for projection in projections:
        normalized = _coverage_text(projection["text"])
        node = next((candidate for candidate in output.nodes
                     if candidate.kind == "paragraph" and candidate.normalized_text == normalized
                     and is_environmental_slot({"title": candidate.slot})
                     and candidate.body_index not in claimed | local_indices), None)
        if node is None:
            continue
        coordinate = projection["source_coordinates"]
        row_index, label_column = coordinate["table_row"], coordinate["label_column"]
        fragments_by_column: dict[int, list[str]] = {label_column: [projection["source_fragments"][0]]}
        for column, fragment in zip(coordinate["value_columns"], projection["source_fragments"][1:]):
            fragments_by_column.setdefault(column, []).append(fragment)
        cells = {(row_index, column) for column, fragments in fragments_by_column.items()
                 if _coverage_text("".join(fragments)) == _coverage_text(rows[row_index][column])}
        for header in projection.get("source_headers", []):
            header_row, header_column = header["table_row"], header["column"]
            if _coverage_text(rows[header_row][header_column]) == _coverage_text(header["text"]):
                cells.add((header_row, header_column))
        covered_cells.update(cells)
        local_indices.add(node.body_index)
        nodes.append(node)
        record = {
            "projection_policy": projection["policy"], "source_coordinates": coordinate,
            "source_fragments": projection["source_fragments"], "source_cells": sorted(cells),
            "output_body_index": node.body_index, "output_text": node.text,
        }
        if projection.get("source_headers"):
            record["source_headers"] = projection["source_headers"]
        evidence.append(record)
    return evidence, covered_cells, nodes, bool(projections)


def _table_fact_cells(rows: list[list[str]], fact: dict) -> set[tuple[int, int]]:
    coordinate = fact.get("source_coordinates") or {}
    row_index, label_column = coordinate.get("table_row"), coordinate.get("label_column")
    value_columns = coordinate.get("value_columns")
    if (type(row_index) is not int or not 0 <= row_index < len(rows)
            or type(label_column) is not int or not 0 <= label_column < len(rows[row_index])
            or not isinstance(value_columns, list) or not value_columns
            or any(type(column) is not int or not 0 <= column < len(rows[row_index])
                   or column == label_column for column in value_columns)
            or len(set(value_columns)) != len(value_columns)):
        return set()
    source_label = str(fact.get("source_label", ""))
    source_identity = canonical_indicator_name(rows[row_index][label_column])
    fact_identity = canonical_indicator_name(str(fact.get("indicator_name", "")))
    if source_identity != fact_identity:
        # Controlled profiles can rename an exact source label, e.g. 组件流阻
        # -> 流阻. Verify its preserved source_label rather than interpreting
        # the profile's display name as the original table cell. Uncontrolled
        # facts still require the same indicator identity.
        if (fact.get("governed_name") is not True or not source_label
                or _coverage_text(source_label) != _coverage_text(rows[row_index][label_column])):
            return set()
    value = "；".join(rows[row_index][column] for column in value_columns if rows[row_index][column].strip())
    if _coverage_text(value) != _coverage_text(str(fact.get("source_value", ""))):
        return set()
    return {(row_index, column) for column in [label_column, *value_columns]}


_VALUE_EDGE = re.compile(r"[0-9A-Za-zµμΩΩ℃°%‰⁰¹²³⁴⁵⁶⁷⁸⁹次秒分时天年月米克升度伏安欧赫帕牛瓦焦亨法]")
_VALUE_JOIN = re.compile(r"[0-9A-Za-zµμΩΩ℃°%‰⁰¹²³⁴⁵⁶⁷⁸⁹次秒分时天年月米克升度伏安欧赫帕牛瓦焦亨法.+\-−±≤≥<>＝=/*·^]")


def _find_complete_fact(text: str, value: str, start: int = 0) -> int:
    """Find literal evidence without accepting part of another value/unit.

    Keep all original characters. For example 500次 cannot prove 1500次,
    -500次 or 500次/s, while a separate occurrence after a clause separator
    remains eligible for the existing unique-consumption check.
    """
    if not value:
        return -1
    position = text.find(value, start)
    while position >= 0:
        end = position + len(value)
        extends_left = (position > 0 and _VALUE_JOIN.fullmatch(value[0])
                        and _VALUE_JOIN.fullmatch(text[position - 1]))
        extends_right = (end < len(text) and _VALUE_EDGE.fullmatch(value[-1])
                         and _VALUE_JOIN.fullmatch(text[end]))
        if not extends_left and not extends_right:
            return position
        position = text.find(value, position + 1)
    return -1


def mark_structured_indicator_coverage(
    ledger: CoverageLedger,
    out_path: str,
) -> CoverageLedger:
    """Prove original indicator coverage independently of adoption approval.

    The workbook requires the user input column before comparing/adopting a
    specification value. Pending design confirmation therefore cannot erase
    source coverage. Every credited fact still needs a unique consumption,
    matching source coordinates/text and its identified visible user row.
    A table projected partly into environmental prose is complete only when
    those exact paragraphs and the user rows jointly preserve every source
    requirement cell, including non-environmental rows and residual conditions.
    """
    audit_path = Path(out_path).with_suffix(".indicator_audit.json")
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        audit = {}
    if not isinstance(audit, dict):
        audit = {}
    source_facts = [item for item in audit.get("input_indicator_facts", []) or []
                    if isinstance(item, dict)]
    decisions = [item for item in audit.get("comparison_decisions", []) or []
                 if isinstance(item, dict)]

    classification_blocks: dict[str, dict] = {}
    for suffix in (".requirement_classification.json", ".effective_requirement_classification.json"):
        try:
            payload = json.loads(Path(out_path).with_suffix(suffix).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        for item in payload.get("source_blocks", []) or []:
            if isinstance(item, dict) and item.get("id"):
                classification_blocks[str(item["id"])] = item

    output_facts = _output_facts(out_path)
    output_rows: dict[str, list[tuple[_BodyNodeEvidence, int, str]]] = {}
    for node in output_facts.nodes:
        if node.kind != "table":
            continue
        rows = json.loads(node.table_json)
        user_column = None
        for row_index, row in enumerate(rows):
            columns = [i for i, cell in enumerate(row) if "用户要求" in _coverage_text(str(cell))]
            if columns and (user_column is None or _coverage_text(str(row[0])) in {"项目", "指标", "指标项", "指标名称"}):
                user_column = columns[0]
                continue
            if user_column is None or len(row) <= user_column or not row:
                continue
            identity = canonical_indicator_name(str(row[0]))
            if identity:
                output_rows.setdefault(identity, []).append((node, row_index, str(row[user_column])))

    facts_by_id: dict[str, list[dict]] = {}
    consumers: dict[str, list[dict]] = {}
    for fact in source_facts:
        facts_by_id.setdefault(str(fact.get("fact_id", "")), []).append(fact)
    for decision in decisions:
        for fact_id in decision.get("user_fact_ids", []) or []:
            consumers.setdefault(str(fact_id), []).append(decision)

    audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest() if audit_path.is_file() else ""
    claimed_facts: set[str] = set()
    claimed_spans: dict[tuple[int, int], list[tuple[int, int]]] = {}
    claimed_prose = {index for block in ledger.blocks if block.covered and block.block_type != "table"
                     for index in block.output_body_indices}
    for block in ledger.blocks:
        if block.covered or block.block_type == "image" or block.source_body_index < 0:
            continue
        original = _coverage_text(block.raw_text)
        table_rows = json.loads(block.raw_text) if block.block_type == "table" else None
        candidates = [fact for fact in source_facts if
                      (fact.get("source_coordinates") or {}).get("body_index") == block.source_body_index]
        evidence: list[dict] = []
        local_spans: dict[tuple[int, int], list[tuple[int, int]]] = {}
        source_spans: list[tuple[int, int]] = []
        nodes: list[_BodyNodeEvidence] = []
        covered_cells: set[tuple[int, int]] = set()
        if table_rows is not None:
            evidence, covered_cells, nodes, has_projection = _environmental_table_evidence(
                block, table_rows, output_facts, claimed_prose,
            )
            if not has_projection:
                continue
            original = _coverage_text("".join(cell for row in table_rows for cell in row))
            candidates = [fact for fact in candidates
                          if not (cells := _table_fact_cells(table_rows, fact)) or not cells.issubset(covered_cells)]
        verified_facts = 0
        for fact in candidates:
            fact_id = str(fact.get("fact_id", ""))
            value = _coverage_text(str(fact.get("source_value", "")))
            identity = canonical_indicator_name(str(fact.get("indicator_name", "")))
            if (not fact_id or not value or not identity or fact_id in claimed_facts
                    or len(facts_by_id.get(fact_id, [])) != 1 or len(consumers.get(fact_id, [])) != 1):
                break
            coordinate = fact.get("source_coordinates") or {}
            if table_rows is not None:
                fact_cells = _table_fact_cells(table_rows, fact)
                if not fact_cells:
                    break
            else:
                start, end = coordinate.get("start"), coordinate.get("end")
                if start is None and end is None and value == original:
                    start, end = 0, len(block.raw_text)
                if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(block.raw_text)
                        or _coverage_text(block.raw_text[start:end]) != value):
                    break
            decision = consumers[fact_id][0]
            if canonical_indicator_name(str(decision.get("indicator_name", ""))) != identity:
                break
            source_ids = [str(item) for item in fact.get("source_ids", []) or []]
            if source_ids:
                if not set(source_ids).issubset(set(map(str, decision.get("user_source_ids", []) or []))):
                    break
                anchors = [classification_blocks.get(source_id, {}) for source_id in source_ids]
                if any(anchor.get("body_index") != block.source_body_index
                       or not _coverage_text(str(anchor.get("text", "")))
                       or _coverage_text(str(anchor.get("text", ""))) not in original for anchor in anchors):
                    break
            user_requirement = _coverage_text(str(decision.get("user_requirement", "")))
            matching_rows = output_rows.get(identity, [])
            if len(matching_rows) != 1 or _find_complete_fact(user_requirement, value) < 0:
                break
            node, row_index, user_cell = matching_rows[0]
            display_value = value
            display_requirement = user_requirement
            if decision.get("display_labels"):
                from jonhon_taskbook.indicator_identity import indicator_display_value
                labels = decision["display_labels"]
                name = str(decision.get("indicator_name", ""))
                display_value = _coverage_text(indicator_display_value(str(fact["source_value"]), name, labels))
                display_requirement = _coverage_text(indicator_display_value(str(decision["user_requirement"]), name, labels))
            actual_user = _coverage_text(user_cell)
            if actual_user != display_requirement or not display_value:
                break
            row_key = (node.body_index, row_index)
            occupied = claimed_spans.get(row_key, []) + local_spans.get(row_key, [])
            output_start = _find_complete_fact(actual_user, display_value)
            while output_start >= 0 and any(output_start < b and output_start + len(display_value) > a for a, b in occupied):
                output_start = _find_complete_fact(actual_user, display_value, output_start + 1)
            if output_start < 0:
                break
            local_spans.setdefault(row_key, []).append((output_start, output_start + len(display_value)))
            if table_rows is not None:
                covered_cells.update(fact_cells)
            else:
                source_spans.append((start, end))
            nodes.append(node)
            verified_facts += 1
            evidence.append({
                "fact_id": fact_id, "indicator_identity": identity,
                "source_coordinates": coordinate, "source_ids": source_ids,
                "source_text": value, "display_text": display_value, "output_body_index": node.body_index,
                "output_row_index": row_index, "output_user_cell": user_cell,
            })
        if verified_facts != len(candidates) or (not candidates and table_rows is None):
            continue
        if table_rows is not None:
            complete = _table_requirement_cells(table_rows).issubset(covered_cells)
        else:
            cursor = 0
            complete = False
            for start, end in sorted(source_spans):
                # Separators may move between rows; no substantive source words,
                # conditions or numbers may disappear between extracted facts.
                if start < cursor or re.search(r"[^\s；;。]", block.raw_text[cursor:start]):
                    break
                cursor = end
            else:
                complete = not re.search(r"[^\s；;。]", block.raw_text[cursor:])
        if not complete:
            continue
        claimed_facts.update(item["fact_id"] for item in evidence if item.get("fact_id"))
        claimed_prose.update(node.body_index for node in nodes if node.kind == "paragraph")
        for key, spans in local_spans.items():
            claimed_spans.setdefault(key, []).extend(spans)
        block.covered = True
        block.action = "structured_table_cell_evidence" if table_rows is not None else "structured_indicator_exact_fact"
        block.assigned_section = " / ".join(dict.fromkeys(node.slot for node in nodes if node.slot)) or "技术指标（结构化表格）"
        block.confidence = 1.0
        block.output_slot = block.assigned_section
        block.output_body_indices = list(dict.fromkeys(node.body_index for node in nodes))
        if table_rows is not None:
            block.output_fragment_evidence = evidence
        block.output_evidence_hash = hashlib.sha256(json.dumps({
            "source_id": block.block_id, "source_body_index": block.source_body_index,
            "source_text": original, "facts": evidence,
            "indicator_audit_sha256": audit_hash,
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
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


