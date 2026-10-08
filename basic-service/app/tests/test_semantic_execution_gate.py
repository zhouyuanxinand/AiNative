"""The semantic gate verifies already assembled media before rejecting a route."""
from __future__ import annotations

import copy
import hashlib
from io import BytesIO

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from jonhon_taskbook.semantic_orchestrator import (
    apply_semantic_plan,
    extract_source_blocks,
    extract_template_slots,
)
from PIL import Image


def _picture():
    stream = BytesIO()
    Image.new("RGB", (8, 8), (20, 40, 80)).save(stream, format="PNG")
    stream.seek(0)
    return stream


def _figure_plan(tmp_path):
    source = Document()
    source.add_heading("接口尺寸", level=1)
    source.add_picture(_picture())
    source.add_paragraph("图1 外螺纹插座接口规格")
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    blocks = extract_source_blocks(str(source_path), "tech")
    output = Document()
    output.add_heading("接口尺寸", level=1)
    output_path = tmp_path / "output.docx"
    output.save(output_path)
    slots = extract_template_slots(str(output_path))
    image = next(block for block in blocks if block["has_drawing"])
    decision = {
        "target_slot": slots[0]["id"], "source_ids": [image["id"]],
        "operation": "copy_exact", "edit_action": "append", "confidence": 0.99,
    }
    return output_path, {
        "slots": slots, "source_blocks": blocks, "decisions": [decision],
    }


def test_already_copied_figure_passes_low_confidence_route_without_duplication(tmp_path):
    output_path, plan = _figure_plan(tmp_path)
    first = apply_semantic_plan(str(output_path), plan)
    assert first["counts"]["inserted"] == 2
    assert len(Document(output_path).inline_shapes) == 1
    original_output = output_path.read_bytes()
    plan["decisions"][0]["confidence"] = 0.30

    evidence = apply_semantic_plan(str(output_path), plan)

    assert evidence["passed"], evidence["blocking_skipped"]
    assert evidence["counts"]["inserted"] == 0
    assert evidence["counts"]["verified_present"] == 2
    assert output_path.read_bytes() == original_output


def test_caption_alone_cannot_prove_its_missing_figure_is_already_present(tmp_path):
    output_path, plan = _figure_plan(tmp_path)
    caption = next(block for block in plan["source_blocks"] if not block["has_drawing"])
    output = Document(output_path)
    output.add_paragraph(caption["text"])
    output.save(output_path)
    plan["decisions"][0].update(source_ids=[caption["id"]], confidence=0.30)

    evidence = apply_semantic_plan(str(output_path), plan)

    assert not evidence["passed"]
    assert evidence["blocking_skipped"][0]["reason"] == "invalid_operation_or_low_confidence"
    assert not Document(output_path).inline_shapes


@pytest.mark.parametrize("mutation", ["missing_caption", "wrong_slot", "different_image", "invalid_operation"])
def test_low_confidence_figure_requires_the_whole_group_in_the_correct_slot(tmp_path, mutation):
    output_path, plan = _figure_plan(tmp_path)
    output = Document(output_path)
    if mutation == "wrong_slot":
        output.add_heading("其他要求", level=1)
    if mutation == "different_image":
        stream = BytesIO()
        Image.new("RGB", (8, 8), (255, 0, 0)).save(stream, format="PNG")
        stream.seek(0)
        output.add_picture(stream)
    else:
        output.add_picture(_picture())
    if mutation != "missing_caption":
        output.add_paragraph("图1 外螺纹插座接口规格")
    output.save(output_path)
    original_output = output_path.read_bytes()
    decision = plan["decisions"][0]
    decision["confidence"] = 0.30
    if mutation == "invalid_operation":
        decision["operation"] = "rewrite"

    evidence = apply_semantic_plan(str(output_path), plan)

    assert not evidence["passed"]
    assert evidence["counts"]["blocking_skipped"] == 1
    assert evidence["counts"]["inserted"] == 0
    assert output_path.read_bytes() == original_output


@pytest.mark.parametrize("operation", ["copy_exact", "rewrite"])
def test_unexecuted_route_reports_the_evidence_needed_to_diagnose_the_gate(tmp_path, operation):
    output_path, plan = _figure_plan(tmp_path)
    decision = plan["decisions"][0]
    decision.update(operation=operation, confidence=0.30)

    evidence = apply_semantic_plan(str(output_path), plan)

    assert not evidence["passed"]
    blocked = evidence["blocking_skipped"][0]
    assert blocked["source_ids"] == decision["source_ids"]
    assert blocked["operation"] == operation
    assert blocked["confidence"] == 0.30
    assert blocked["required_confidence"] == 0.60


@pytest.mark.parametrize("confidence", [0.30, 0.99])
@pytest.mark.parametrize("hidden_part", ["image_run", "image_paragraph", "caption_run"])
def test_hidden_figure_content_is_not_counted_as_visible_evidence(tmp_path, confidence, hidden_part):
    output_path, plan = _figure_plan(tmp_path)
    output = Document(output_path)
    output.add_picture(_picture())
    caption = output.add_paragraph("图1 外螺纹插座接口规格")
    picture = output.paragraphs[1]
    if hidden_part == "image_paragraph":
        properties = OxmlElement("w:rPr")
        picture._p.get_or_add_pPr().append(properties)
    else:
        run = caption.runs[0] if hidden_part == "caption_run" else picture.runs[0]
        properties = run._r.get_or_add_rPr()
    properties.append(OxmlElement("w:vanish"))
    output.save(output_path)
    original_output = output_path.read_bytes()
    decision = plan["decisions"][0]
    decision["confidence"] = confidence

    evidence = apply_semantic_plan(str(output_path), plan)

    if confidence < 0.60:
        assert not evidence["passed"]
        assert evidence["counts"]["blocking_skipped"] == 1
        assert output_path.read_bytes() == original_output
    else:
        assert evidence["passed"]
        assert evidence["counts"]["inserted"] == 1
        assert evidence["counts"]["verified_present"] == 1
        # One visible copy is added while the original hidden node stays intact.
        output = Document(output_path)
        if hidden_part == "caption_run":
            assert sum(p.text == caption.text for p in output.paragraphs) == 2
            assert output.paragraphs[-1].runs[0].font.hidden is not True
        else:
            assert len(output.inline_shapes) == 2
            assert output.paragraphs[-1]._p.find('.//' + qn('w:vanish')) is None


def test_explicitly_unhidden_image_remains_valid_existing_evidence(tmp_path):
    output_path, plan = _figure_plan(tmp_path)
    output = Document(output_path)
    output.add_picture(_picture())
    output.paragraphs[-1].runs[0].font.hidden = False
    output.add_paragraph("图1 外螺纹插座接口规格")
    output.save(output_path)
    plan["decisions"][0]["confidence"] = 0.30

    evidence = apply_semantic_plan(str(output_path), plan)

    assert evidence["passed"]
    assert evidence["counts"]["inserted"] == 0
    assert evidence["counts"]["verified_present"] == 2


@pytest.mark.parametrize("mutation", ["complete", "changed_threshold", "missing_row", "wrong_slot"])
def test_low_confidence_table_requires_complete_existing_values_in_target(tmp_path, mutation):
    """A copied environmental table is evidence; a changed value is not."""
    source = Document()
    source.add_heading("环境性能要求", level=1)
    table = source.add_table(rows=3, cols=2)
    for row, values in zip(table.rows, [
        ("项目", "指标"), ("工作温度", "-55℃～125℃"), ("中性盐雾", "共192h"),
    ]):
        for cell, value in zip(row.cells, values):
            cell.text = value
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    blocks = extract_source_blocks(str(source_path), "tech")
    block = next(block for block in blocks if block["type"] == "table")
    output = Document()
    output.add_heading("环境适应性要求", level=1)
    if mutation == "wrong_slot":
        output.add_heading("其他要求", level=1)
    copied_table = copy.deepcopy(table._tbl)
    if mutation == "changed_threshold":
        text_node = next(node for node in copied_table.iter(qn("w:t")) if node.text == "共192h")
        text_node.text = "共96h"
    elif mutation == "missing_row":
        row = copied_table.findall(qn("w:tr"))[-1]
        copied_table.remove(row)
    output.element.body.insert(-1, copied_table)
    output_path = tmp_path / "output.docx"
    output.save(output_path)
    slots = extract_template_slots(str(output_path))
    original_output = output_path.read_bytes()

    evidence = apply_semantic_plan(str(output_path), {
        "slots": slots, "source_blocks": blocks,
        "decisions": [{"target_slot": slots[0]["id"], "source_ids": [block["id"]],
                       "operation": "copy_exact", "edit_action": "append", "confidence": 0.30}],
    })

    assert evidence["passed"] is (mutation == "complete")
    assert evidence["counts"]["inserted"] == 0
    assert evidence["counts"]["verified_present"] == (1 if mutation == "complete" else 0)
    assert output_path.read_bytes() == original_output


@pytest.mark.parametrize("mutation", ["complete", "missing_condition", "changed_method", "wrong_slot"])
def test_low_confidence_fragment_requires_its_entire_installation_clause(tmp_path, mutation):
    """A mixed usage paragraph can be routed as exact independent fragments."""
    fragment = "插头通过导套与印制板固定后，接触件表贴焊接；"
    paragraph_text = "产品用于机箱内部，" + fragment + "插座针脚穿孔焊接。"
    source = Document()
    source.add_heading("安装使用环境", level=1)
    source.add_paragraph(paragraph_text)
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    parent = next(block for block in extract_source_blocks(str(source_path), "tech")
                  if block["text"] == paragraph_text)
    start = paragraph_text.index(fragment)
    block = {**parent, "id": parent["id"] + "-fragment", "text": fragment,
             "content_hash": hashlib.sha256(fragment.encode("utf-8")).hexdigest(),
             "is_fragment": True, "parent_source_id": parent["id"], "fragment_index": 0,
             "source_span_start": start, "source_span_end": start + len(fragment),
             "element_content_hash": parent["content_hash"]}
    rendered = fragment.rstrip("；") + "。"
    if mutation == "missing_condition":
        rendered = "插头接触件表贴焊接。"
    elif mutation == "changed_method":
        rendered = rendered.replace("表贴焊接", "穿孔焊接")
    output = Document()
    output.add_heading("安装方式", level=1)
    if mutation == "wrong_slot":
        output.add_heading("端接方式", level=1)
    output.add_paragraph(rendered)
    output_path = tmp_path / "output.docx"
    output.save(output_path)
    slots = extract_template_slots(str(output_path))
    original_output = output_path.read_bytes()

    evidence = apply_semantic_plan(str(output_path), {
        "slots": slots, "source_blocks": [block],
        "decisions": [{"target_slot": slots[0]["id"], "source_ids": [block["id"]],
                       "operation": "copy_exact", "edit_action": "append", "confidence": 0.30}],
    })

    assert evidence["passed"] is (mutation == "complete")
    assert evidence["counts"]["inserted"] == 0
    assert evidence["counts"]["verified_present"] == (1 if mutation == "complete" else 0)
    assert output_path.read_bytes() == original_output
