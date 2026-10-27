"""Actual body checks must detect excluded historical evidence reintroduced later."""
from copy import deepcopy
from io import BytesIO

from docx import Document
from PIL import Image

from jonhon_taskbook.semantic_integrity_gate import run_semantic_integrity_gate
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks, extract_template_slots


def _case(tmp_path, *, shared_image=False):
    image = BytesIO()
    Image.new("RGB", (8, 6), "#1555aa").save(image, format="PNG")
    image_bytes = image.getvalue()
    source = Document()
    source.add_heading("产品组成", 1)
    source.add_paragraph("冷板由板体和连接器组成。")
    if shared_image:
        source.add_picture(BytesIO(image_bytes))
    source.add_heading("历史测试结果", 1)
    source.add_paragraph("粗糙度测试数据：")
    table = source.add_table(rows=3, cols=2)
    for row, values in zip(table.rows, [("样品编号", "实测粗糙度/μm"), ("A-1", "0.468"), ("A-2", "0.427")]):
        for cell, value in zip(row.cells, values):
            cell.text = value
    source.add_picture(BytesIO(image_bytes))
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    blocks = extract_source_blocks(str(source_path), "tech")
    classification = {"source_blocks": blocks, "classifications": [
        {"source_id": block["id"], "category": "other"} for block in blocks
    ]}
    output = Document()
    output.add_heading("其他要求", 1)
    output.add_paragraph("冷板由板体和连接器组成。")
    output_path = tmp_path / "output.docx"
    output.save(output_path)
    plan = {"source_blocks": blocks, "slots": extract_template_slots(str(output_path)), "decisions": []}
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text("categories: {}", encoding="utf-8")
    return source, table, source_path, output_path, plan, classification, mapping, image_bytes


def _check(output, plan, classification, mapping):
    return run_semantic_integrity_gate(output, plan, classification, mapping)


def test_historical_table_injected_after_copy_is_blocked(tmp_path):
    _, table, _, output, plan, classification, mapping, _ = _case(tmp_path)
    assert _check(output, plan, classification, mapping)["passed"]
    document = Document(output)
    document.element.body.insert_element_before(deepcopy(table._tbl), "w:sectPr")
    document.save(output)

    report = _check(output, plan, classification, mapping)

    assert not report["passed"]
    violation = next(item for item in report["violations"] if item["code"] == "HISTORICAL_REFERENCE_IN_BODY")
    source = next(block for block in classification["source_blocks"] if block["type"] == "table")
    assert violation["source_id"] == source["id"]
    assert violation["source_body_index"] == source["body_index"]
    assert violation["output_body_index"] == 2


def test_historical_unique_image_is_blocked_but_shared_formal_image_is_only_noted(tmp_path):
    for shared in (False, True):
        directory = tmp_path / str(shared)
        directory.mkdir()
        _, _, _, output, plan, classification, mapping, image_bytes = _case(directory, shared_image=shared)
        document = Document(output)
        document.add_picture(BytesIO(image_bytes))
        document.save(output)
        report = _check(output, plan, classification, mapping)
        if shared:
            assert report["passed"]
            assert report["historical_reference_audit"]["warnings"]
        else:
            assert not report["passed"]
            assert any(item["code"] == "HISTORICAL_REFERENCE_IN_BODY" for item in report["violations"])


def test_short_result_labels_and_partial_or_changed_tables_do_not_trigger_global_match(tmp_path):
    _, table, _, output, plan, classification, mapping, _ = _case(tmp_path)
    document = Document(output)
    document.add_paragraph("粗糙度测试数据：")
    copied = deepcopy(table._tbl)
    document.element.body.insert_element_before(copied, "w:sectPr")
    document.tables[-1].cell(1, 1).text = "0.700"
    document.save(output)
    assert _check(output, plan, classification, mapping)["passed"]


def test_unavailable_or_changed_source_cannot_prove_historical_body_pollution(tmp_path):
    _, table, source, output, plan, classification, mapping, _ = _case(tmp_path)
    document = Document(output)
    document.element.body.insert_element_before(deepcopy(table._tbl), "w:sectPr")
    document.save(output)
    revised_source = Document(source)
    revised_source.tables[0].cell(1, 1).text = "9.99"
    revised_source.save(source)
    assert _check(output, plan, classification, mapping)["passed"]
    source.unlink()
    assert _check(output, plan, classification, mapping)["passed"]
