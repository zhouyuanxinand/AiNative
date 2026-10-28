import hashlib
import json
import base64
from io import BytesIO
import re

from docx import Document
from docx.oxml.ns import qn

from src.service.jonhon_taskbook.postprocess import postprocess

_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5Wk3kAAAAASUVORK5CYII=")


def _source(tmp_path, name, texts, image=_PNG):
    path = tmp_path / name
    doc = Document()
    blocks = []
    for text in texts:
        if re.match(r"^图\d+", text):
            doc.add_picture(BytesIO(image))
        index = len(doc.element.body) - 1
        doc.add_paragraph(text)
        blocks.append({"id": f"{name}-{index}", "source": "tech", "type": "paragraph",
                       "source_path": str(path), "body_index": index, "text": text,
                       "content_hash": hashlib.sha256(re.sub(r"\s+", "", text).encode()).hexdigest()})
    doc.save(path)
    return blocks


def _output(tmp_path, texts, blocks, images=None):
    path = tmp_path / "out.docx"
    doc = Document()
    image_index = 0
    for text in texts:
        if re.match(r"^图\d+", text):
            doc.add_picture(BytesIO(images[image_index] if images else _PNG))
            image_index += 1
        doc.add_paragraph(text)
    doc.save(path)
    classification = {"source_blocks": blocks, "classifications": []}
    path.with_suffix(".effective_requirement_classification.json").write_text(
        json.dumps(classification), encoding="utf-8")
    return path, classification


def _texts(path):
    return [p.text for p in Document(path).paragraphs if p.text]


def test_duplicate_source_figure_copies_update_each_reference_and_are_idempotent(tmp_path):
    texts = ["检测线缠绕轨迹如图18所示，压力0.3MPa。", "图18 检测线缠绕路径"]
    blocks = _source(tmp_path, "source.docx", texts)
    output, _ = _output(tmp_path, texts * 2, blocks)
    postprocess(str(output))
    assert _texts(output) == ["检测线缠绕轨迹如图1所示，压力0.3MPa。", "图1 检测线缠绕路径",
                              "检测线缠绕轨迹如图2所示，压力0.3MPa。", "图2 检测线缠绕路径"]
    postprocess(str(output))
    assert "如图1所示" in _texts(output)[0]
    assert "如图2所示" in _texts(output)[2]


def test_same_old_number_from_two_sources_uses_reference_source_identity(tmp_path):
    first = ["冷板结构见图1，厚度5mm。", "图1 冷板结构"]
    second = ["软管结构见图1，长度200mm。", "图1 软管结构"]
    blocks = _source(tmp_path, "a.docx", first) + _source(tmp_path, "b.docx", second)
    output, _ = _output(tmp_path, second + first, blocks)
    postprocess(str(output))
    assert _texts(output)[0] == second[0]
    assert _texts(output)[2] == "冷板结构见图2，厚度5mm。"


def test_ambiguous_source_reference_is_not_guessed_and_is_reported(tmp_path):
    from src.service.jonhon_taskbook.figure_references import audit_figure_references
    reference = "外形结构如图1所示。"
    blocks = (_source(tmp_path, "a.docx", [reference, "图1 冷板结构"])
              + _source(tmp_path, "b.docx", [reference, "图1 软管结构"]))
    output, classification = _output(tmp_path, [reference, "图1 冷板结构", "图1 软管结构"], blocks)
    postprocess(str(output))
    audit = audit_figure_references(output, classification)
    assert _texts(output)[0] == reference
    assert any(v["code"] == "FIGURE_REFERENCE_AMBIGUOUS" for v in audit["violations"])


def test_deleted_caption_gap_is_repaired_from_source_identity(tmp_path):
    from src.service.jonhon_taskbook.figure_references import synchronize_figure_references
    blocks = _source(tmp_path, "source.docx", ["安装如图18所示。", "图18 安装结构"])
    output, classification = _output(tmp_path, ["安装如图8所示。", "图8 安装结构"], blocks)
    audit = synchronize_figure_references(output, classification)
    assert _texts(output) == ["安装如图1所示。", "图1 安装结构"]
    assert not audit["violations"]
    assert audit["references"][0]["source_body_index"] == 0
    assert audit["references"][0]["source_number"] == 18


def test_reference_update_only_changes_figure_digits_and_keeps_run_formatting(tmp_path):
    from src.service.jonhon_taskbook.figure_references import synchronize_figure_references
    blocks = _source(tmp_path, "source.docx", ["按图18安装，压力0.3MPa。", "图18 安装结构"])
    output, classification = _output(tmp_path, [], blocks)
    doc = Document(output)
    p = doc.add_paragraph()
    p.add_run("按图1").bold = True
    p.add_run("8安装，").italic = True
    p.add_run("压力0.3MPa。").underline = True
    doc.add_picture(BytesIO(_PNG))
    doc.add_paragraph("图18 安装结构")
    doc.save(output)
    synchronize_figure_references(output, classification)
    p = Document(output).paragraphs[0]
    assert p.text == "按图1安装，压力0.3MPa。"
    assert p.runs[0].bold and p.runs[1].italic
    assert p.runs[2].text == "压力0.3MPa。" and p.runs[2].underline


def test_wrong_reference_cannot_pass_merely_because_other_numbers_match(tmp_path):
    from src.service.jonhon_taskbook.figure_references import audit_figure_references
    blocks = _source(tmp_path, "source.docx", ["按图18安装，压力0.3MPa。", "图18 安装结构"])
    output, classification = _output(tmp_path, ["按图99安装，压力0.3MPa。", "图1 安装结构"], blocks)
    audit = audit_figure_references(output, classification)
    assert any(v["code"] == "FIGURE_REFERENCE_MISMATCH" for v in audit["violations"])


def test_same_caption_text_requires_matching_source_image_bytes(tmp_path):
    from PIL import Image
    from src.service.jonhon_taskbook.figure_references import synchronize_figure_references
    stream = BytesIO()
    Image.new("RGB", (2, 2), "red").save(stream, format="PNG")
    red = stream.getvalue()
    first = ["冷板结构见图1。", "图1 结构示意"]
    second = ["软管结构见图1。", "图1 结构示意"]
    blocks = (_source(tmp_path, "a.docx", first)
              + _source(tmp_path, "b.docx", second, image=red))
    output, classification = _output(tmp_path, second + first, blocks, images=[red, _PNG])
    audit = synchronize_figure_references(output, classification)
    assert not audit["violations"]
    assert _texts(output)[0] == "软管结构见图1。"
    assert _texts(output)[2] == "冷板结构见图2。"


def test_reference_at_start_of_paragraph_is_not_a_caption(tmp_path):
    from src.service.jonhon_taskbook.figure_references import synchronize_figure_references
    blocks = _source(tmp_path, "source.docx", ["图18所示结构应能承受0.3MPa。", "图18 结构示意"])
    output, classification = _output(tmp_path, ["图18所示结构应能承受0.3MPa。", "图18 结构示意"], blocks)
    audit = synchronize_figure_references(output, classification)
    assert not audit["violations"]
    assert _texts(output) == ["图1所示结构应能承受0.3MPa。", "图1 结构示意"]


def test_caption_beginning_with_zhongjian_is_not_mistaken_for_reference(tmp_path):
    from src.service.jonhon_taskbook.figure_references import synchronize_figure_references
    blocks = _source(tmp_path, "source.docx", ["图10 中间管尺寸"])
    output, classification = _output(tmp_path, ["图10 中间管尺寸"], blocks)
    audit = synchronize_figure_references(output, classification)
    assert not audit["violations"]
    assert _texts(output) == ["图1 中间管尺寸"]


def test_source_bookmarks_resolve_identical_short_references_and_overlapping_ordinals(tmp_path):
    from src.service.jonhon_taskbook.figure_references import mark_source_element, synchronize_figure_references
    first = ["如图1所示。", "图1 冷板结构"]
    second = ["如图2所示。", "图2 软管结构"]
    a = _source(tmp_path, "a.docx", first)
    b = _source(tmp_path, "b.docx", second)
    output, classification = _output(tmp_path, second + first + first, a + b)
    doc = Document(output)
    for paragraph, source_id in ((doc.paragraphs[0], b[0]["id"]),
                                 (doc.paragraphs[3], a[0]["id"]),
                                 (doc.paragraphs[6], a[0]["id"])):
        mark_source_element(paragraph._p, source_id, doc)
    names = [n.get(qn("w:name")) for n in doc.element.iter(qn("w:bookmarkStart"))]
    assert len(names) == len(set(names)) == 3
    assert all(len(name) <= 40 for name in names)
    doc.save(output)
    first_audit = synchronize_figure_references(output, classification)
    assert not first_audit["violations"]
    assert _texts(output) == ["如图1所示。", "图1 软管结构", "如图2所示。", "图2 冷板结构",
                              "如图3所示。", "图3 冷板结构"]
    second_audit = synchronize_figure_references(output, classification)
    assert not second_audit["violations"]
    assert second_audit["figure_references_renumbered"] == 0
    assert second_audit["figure_captions_renumbered"] == 0


def test_actual_semantic_copy_binds_short_references_before_postprocess(tmp_path):
    from jonhon_taskbook.semantic_orchestrator import apply_semantic_plan, extract_source_blocks, extract_template_slots
    from src.service.jonhon_taskbook.figure_references import synchronize_figure_references
    source = Document()
    source.add_heading("需求正文", level=1)
    source.add_paragraph("如图18所示。")
    source.add_picture(BytesIO(_PNG))
    source.add_paragraph("图18 安装结构")
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    blocks = extract_source_blocks(str(source_path), "tech")
    target = Document()
    target.add_heading("安装形式和方法", level=1)
    output = tmp_path / "out.docx"
    target.save(output)
    slots = extract_template_slots(str(output))
    evidence = apply_semantic_plan(str(output), {
        "slots": slots, "source_blocks": blocks,
        "decisions": [{"target_slot": slots[0]["id"], "source_ids": [b["id"] for b in blocks],
                       "operation": "copy_exact", "edit_action": "append", "confidence": 0.99}],
    })
    assert evidence["passed"]
    audit = synchronize_figure_references(output, {"source_blocks": blocks})
    assert not audit["violations"]
    assert audit["references"][0]["source_binding"] == "bookmark"
    starts = list(Document(output).element.iter(qn("w:bookmarkStart")))
    ends = list(Document(output).element.iter(qn("w:bookmarkEnd")))
    assert {n.get(qn("w:id")) for n in starts} == {n.get(qn("w:id")) for n in ends}
    assert len(starts) == len({n.get(qn("w:id")) for n in starts})


def test_used_bound_source_with_invalid_hash_blocks_reference_audit(tmp_path):
    from src.service.jonhon_taskbook.figure_references import mark_source_element, synchronize_figure_references
    texts = ["按图18安装，压力0.3MPa。", "图18 安装结构"]
    blocks = _source(tmp_path, "source.docx", texts)
    output, classification = _output(tmp_path, texts, blocks)
    doc = Document(output)
    mark_source_element(doc.paragraphs[0]._p, blocks[0]["id"], doc)
    doc.save(output)
    blocks[0]["content_hash"] = "0" * 64
    audit = synchronize_figure_references(output, classification)
    assert any(v["code"] == "FIGURE_REFERENCE_SOURCE_UNVERIFIABLE"
               and v["source_id"] == blocks[0]["id"] for v in audit["violations"])
    assert _texts(output)[0] == texts[0]


def test_unused_unverifiable_reference_source_does_not_block_output(tmp_path):
    from src.service.jonhon_taskbook.figure_references import synchronize_figure_references
    blocks = _source(tmp_path, "source.docx", ["按图18安装。", "图18 安装结构"])
    blocks[0]["content_hash"] = "0" * 64
    output, classification = _output(tmp_path, ["无相关引用。"], blocks)
    audit = synchronize_figure_references(output, classification)
    assert not audit["violations"]
    assert audit["unverifiable_sources"]
