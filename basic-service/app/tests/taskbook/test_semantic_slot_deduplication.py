"""Semantic copying recognizes already-filled evidence only within its slot."""
from __future__ import annotations

import pytest
from docx import Document

from jonhon_taskbook.semantic_orchestrator import (
    apply_semantic_plan,
    extract_source_blocks,
    extract_template_slots,
)


def _run_plan(tmp_path, source_text, sections, *, confidence=0.99):
    source = Document()
    source.add_heading("需求正文", level=1)
    source.add_paragraph(source_text)
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    blocks = extract_source_blocks(str(source_path), "tech")
    block = next(block for block in blocks if block["text"] == source_text)
    output = Document()
    for heading, existing in sections:
        output.add_heading(heading, level=1)
        if existing:
            output.add_paragraph(existing)
    out_path = tmp_path / "output.docx"
    output.save(out_path)
    slots = extract_template_slots(str(out_path))
    result = apply_semantic_plan(str(out_path), {
        "slots": slots,
        "source_blocks": blocks,
        "decisions": [
            {"target_slot": slot["id"], "source_ids": [block["id"]],
             "operation": "copy_exact", "edit_action": "append",
             "confidence": confidence}
            for slot in slots
        ],
    })
    return Document(out_path), result


@pytest.mark.parametrize("confidence", [0.99, 0.3])
@pytest.mark.parametrize(("source_text", "existing"), [
    ("2.1 应用领域：用于无线通信设备。", "应用领域：用于无线通信设备。"),
    ("（1）工作温度：-40℃～+85℃；", "工作温度： -40℃～+85℃。"),
])
def test_already_filled_display_variant_is_not_copied_again(tmp_path, source_text, existing, confidence):
    document, evidence = _run_plan(
        tmp_path, source_text, [("使用环境", existing)], confidence=confidence,
    )
    assert [paragraph.text for paragraph in document.paragraphs] == ["使用环境", existing]
    assert evidence["passed"]
    assert evidence["counts"]["inserted"] == 0
    assert evidence["counts"]["verified_present"] == 1


@pytest.mark.parametrize("prefilled", [False, True])
def test_same_evidence_can_be_used_in_two_distinct_slots(tmp_path, prefilled):
    source = "3.3 适配线缆：匹配50Ω同轴电缆。"
    existing = "适配线缆：匹配50Ω同轴电缆。" if prefilled else ""
    document, evidence = _run_plan(tmp_path, source, [
        ("产品组成", existing), ("所接同轴电缆型号", ""),
    ])
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    assert paragraphs == ["产品组成", existing or source, "所接同轴电缆型号", source]
    assert evidence["passed"]
    assert evidence["counts"]["inserted"] == (1 if prefilled else 2)


@pytest.mark.parametrize("existing", [
    "适配线缆：匹配75Ω同轴电缆。",
    "适配线缆：户外匹配50Ω同轴电缆。",
])
def test_different_value_or_condition_in_same_slot_remains_distinct(tmp_path, existing):
    source = "3.3 适配线缆：匹配50Ω同轴电缆。"
    document, evidence = _run_plan(tmp_path, source, [("产品组成", existing)])
    assert [paragraph.text for paragraph in document.paragraphs] == ["产品组成", existing, source]
    assert evidence["passed"]
    assert evidence["counts"]["inserted"] == 1


def test_copied_source_heading_does_not_end_the_target_section(tmp_path):
    from jonhon_taskbook.semantic_integrity_gate import _section_texts

    source = Document()
    source.add_heading("测试资料", level=1)
    source.add_heading("附录六：压缩空气管控标准", level=1)
    source.add_paragraph("固体粒子尺寸和浓度满足标准中的4级。")
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    blocks = extract_source_blocks(str(source_path), "tech")
    output = Document()
    output.add_heading("通用质量特性要求", level=1)
    output.add_heading("测试性要求", level=2)
    output.add_heading("安全性要求", level=2)
    output.add_paragraph("后续章节原文")
    path = tmp_path / "out.docx"
    output.save(path)
    slots = extract_template_slots(str(path))
    target = next(s for s in slots if s["title"] == "测试性要求")
    apply_semantic_plan(str(path), {
        "slots": slots, "source_blocks": blocks,
        "decisions": [{"target_slot": target["id"], "source_ids": [b["id"] for b in blocks],
                       "operation": "copy_exact", "confidence": 0.99}],
    })
    sections, tree = _section_texts(path)
    assert "附录六：压缩空气管控标准" in sections[target["id"]]
    assert "固体粒子尺寸和浓度满足标准中的4级。" in sections[target["id"]]
    assert "后续章节原文" not in sections[target["id"]]
    assert [node["title"] for node in tree] == ["通用质量特性要求", "测试性要求", "安全性要求"]
