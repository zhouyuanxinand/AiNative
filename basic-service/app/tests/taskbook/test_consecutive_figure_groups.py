"""Figures keep their images and captions together across routing and coverage."""

from __future__ import annotations

import struct
import zlib
from io import BytesIO

from docx import Document
from jonhon_taskbook.coverage_ledger import (
    mark_covered_from_output,
    parse_docx_to_ledger,
)
from jonhon_taskbook.qa_gate import QAGate
from jonhon_taskbook.semantic_orchestrator import (
    apply_semantic_plan,
    extract_source_blocks,
    extract_template_slots,
)


def _png(rgb: tuple[int, int, int]) -> BytesIO:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00" + bytes(rgb))
    return BytesIO(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                   + chunk(b"IDAT", pixels) + chunk(b"IEND", b""))


def _source_with_consecutive_images(path):
    document = Document()
    document.add_heading("外形及安装图", level=1)
    document.add_picture(_png((255, 0, 0)))
    document.add_paragraph("图1 导热硅脂示意图")
    document.add_picture(_png((0, 255, 0)))
    document.add_picture(_png((0, 0, 255)))
    document.add_paragraph("图2 标记内容示意")
    document.save(path)


def _routed_output(path, *, include_middle_image: bool):
    document = Document()
    document.add_heading("安装形式和方法", level=1)
    document.add_picture(_png((255, 0, 0)))
    document.add_paragraph("图7 导热硅脂示意图")
    document.add_heading("外形尺寸", level=1)
    if include_middle_image:
        document.add_picture(_png((0, 255, 0)))
    document.add_picture(_png((0, 0, 255)))
    document.add_paragraph("图8 标记内容示意")
    document.save(path)


def test_consecutive_images_share_the_following_caption_without_reusing_the_previous_one(tmp_path):
    source = tmp_path / "source.docx"
    _source_with_consecutive_images(source)

    blocks = extract_source_blocks(str(source), "tech")
    images = [block for block in blocks if block["has_drawing"]]
    first_caption = next(block for block in blocks if block["text"] == "图1 导热硅脂示意图")
    second_caption = next(block for block in blocks if block["text"] == "图2 标记内容示意")

    assert images[0]["media_group_members"] == [images[0]["id"], first_caption["id"]]
    expected_second_group = [images[1]["id"], images[2]["id"], second_caption["id"]]
    assert images[1]["media_group_members"] == expected_second_group
    assert images[2]["media_group_members"] == expected_second_group
    assert second_caption["media_group_members"] == expected_second_group
    assert first_caption["media_group_members"] == images[0]["media_group_members"]


def test_coverage_recognizes_each_image_in_a_routed_figure_and_blocks_a_missing_one(tmp_path):
    source = tmp_path / "source.docx"
    output = tmp_path / "output.docx"
    _source_with_consecutive_images(source)
    ledger = parse_docx_to_ledger(str(source))
    images = [block for block in ledger.blocks if block.block_type == "image"]

    assert [block.image_caption for block in images] == [
        "图1 导热硅脂示意图", "图2 标记内容示意", "图2 标记内容示意",
    ]
    assert [block.image_caption_order for block in images] == ["after", "after", "after"]

    _routed_output(output, include_middle_image=True)
    mark_covered_from_output(ledger, str(output))
    assert all(block.covered for block in images)

    _routed_output(output, include_middle_image=False)
    ledger = parse_docx_to_ledger(str(source))
    mark_covered_from_output(ledger, str(output))
    images = [block for block in ledger.blocks if block.block_type == "image"]
    assert [block.covered for block in images] == [True, False, True]


def test_semantic_routing_keeps_each_figure_and_caption_in_its_section(tmp_path):
    source = tmp_path / "source.docx"
    output = tmp_path / "output.docx"
    _source_with_consecutive_images(source)
    blocks = extract_source_blocks(str(source), "tech")
    images = [block for block in blocks if block["has_drawing"]]

    document = Document()
    document.add_heading("安装形式和方法", level=1)
    document.add_heading("外形尺寸", level=1)
    document.save(output)
    slots = {slot["title"]: slot for slot in extract_template_slots(str(output))}
    evidence = apply_semantic_plan(str(output), {
        "slots": list(slots.values()),
        "source_blocks": blocks,
        "decisions": [
            {"target_slot": slots["安装形式和方法"]["id"], "source_ids": [images[0]["id"]],
             "operation": "copy_exact", "edit_action": "append", "confidence": 0.99},
            {"target_slot": slots["外形尺寸"]["id"], "source_ids": [images[1]["id"]],
             "operation": "copy_exact", "edit_action": "append", "confidence": 0.99},
        ],
    })

    document = Document(output)
    texts = [paragraph.text for paragraph in document.paragraphs]
    assert evidence["passed"]
    assert texts.count("图1 导热硅脂示意图") == 1
    assert texts.count("图2 标记内容示意") == 1
    assert texts.index("安装形式和方法") < texts.index("图1 导热硅脂示意图") < texts.index("外形尺寸")
    assert texts.index("外形尺寸") < texts.index("图2 标记内容示意")
    ledger = parse_docx_to_ledger(str(source))
    mark_covered_from_output(ledger, str(output))
    assert all(block.covered for block in ledger.blocks if block.block_type == "image")
    qa = QAGate({"block_if": {"required_figure_captions": [
        "图1 导热硅脂示意图", "图2 标记内容示意",
    ]}}, {}).check(document.element)
    assert not any("图题孤立" in reason for reason in qa["block_reasons"])


def test_saved_plan_with_old_overlapping_media_groups_cannot_duplicate_a_caption(tmp_path):
    source = tmp_path / "source.docx"
    output = tmp_path / "output.docx"
    _source_with_consecutive_images(source)
    blocks = extract_source_blocks(str(source), "tech")
    images = [block for block in blocks if block["has_drawing"]]
    first_caption = next(block for block in blocks if block["text"] == "图1 导热硅脂示意图")
    stale_group = [first_caption["id"], images[1]["id"]]
    first_caption["media_group_members"] = stale_group
    images[1]["media_group_members"] = stale_group

    document = Document()
    document.add_heading("安装形式和方法", level=1)
    document.add_heading("外形尺寸", level=1)
    document.save(output)
    slots = {slot["title"]: slot for slot in extract_template_slots(str(output))}
    apply_semantic_plan(str(output), {
        "slots": list(slots.values()), "source_blocks": blocks,
        "decisions": [
            {"target_slot": slots["安装形式和方法"]["id"], "source_ids": [images[0]["id"]],
             "operation": "copy_exact", "edit_action": "append", "confidence": 0.99},
            {"target_slot": slots["外形尺寸"]["id"], "source_ids": [images[1]["id"]],
             "operation": "copy_exact", "edit_action": "append", "confidence": 0.99},
        ],
    })

    texts = [paragraph.text for paragraph in Document(output).paragraphs]
    assert texts.count("图1 导热硅脂示意图") == 1
    assert texts.count("图2 标记内容示意") == 1
    ledger = parse_docx_to_ledger(str(source))
    mark_covered_from_output(ledger, str(output))
    assert all(block.covered for block in ledger.blocks if block.block_type == "image")


def test_caption_with_no_image_still_fails_qa():
    document = Document()
    document.add_heading("安装形式和方法", level=1)
    document.add_paragraph("图1 导热硅脂示意图")

    qa = QAGate({"block_if": {
        "required_figure_captions": ["图1 导热硅脂示意图"],
    }}, {}).check(document.element)

    assert any("图题孤立" in reason for reason in qa["block_reasons"])
