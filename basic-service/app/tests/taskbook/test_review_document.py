from __future__ import annotations

import base64
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
from jonhon_taskbook.review_document import apply_edits, document_projection

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=")


def save_doc(tmp_path, document):
    path = tmp_path / "original.docx"
    document.save(path)
    return path


def all_paragraphs(blocks):
    for block in blocks:
        if block["kind"] == "paragraph":
            yield block
        else:
            for row in block["rows"]:
                for cell in row["cells"]:
                    yield from all_paragraphs(cell["blocks"])


def find_paragraph(path, text):
    return next(block for block in all_paragraphs(document_projection(path)["blocks"]) if block["text"] == text)


def test_projection_has_version_bound_ids_outline_and_merged_cells(tmp_path):
    document = Document()
    document.add_heading("技术要求", level=1)
    document.add_paragraph("基本要求")
    document.add_heading("电气指标", level=2)
    table = document.add_table(rows=3, cols=3)
    table.cell(0, 0).merge(table.cell(1, 0)).text = "合并指标"
    table.cell(0, 1).merge(table.cell(0, 2)).text = "横向合并"
    path = save_doc(tmp_path, document)
    first = document_projection(path, asset_id="baseline", revision_id="r0")
    second = document_projection(path)
    assert first["blocks"] == second["blocks"]
    assert first["asset_id"] == "baseline"
    assert first["view_mode"] == "content"
    assert [entry["level"] for entry in first["outline"]] == [1, 2]
    assert first["outline"][1]["parent_id"] == first["outline"][0]["id"]
    assert first["blocks"][1]["section_id"] == first["outline"][0]["id"]
    rows = first["blocks"][-1]["rows"]
    assert rows[0]["cells"][0]["rowspan"] == 2
    assert rows[0]["cells"][1]["colspan"] == 2
    assert len(rows[1]["cells"]) == 2


def test_replaces_text_preserving_run_formats_numbering_media_headers_and_other_parts(tmp_path):
    document = Document()
    document.sections[0].header.paragraphs[0].text = "受控页眉"
    document.sections[0].footer.paragraphs[0].text = "受控页脚"
    paragraph = document.add_paragraph(style="List Number")
    paragraph.add_run("绝缘电阻 ").bold = True
    paragraph.add_run("1000").italic = True
    paragraph.add_run(" MΩ；额定电压 200 V")
    image_path = tmp_path / "image.png"
    image_path.write_bytes(PNG)
    picture = document.add_paragraph("安装示意图")
    picture.add_run().add_picture(str(image_path), width=Inches(0.1))
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "指标"
    table.cell(1, 0).text = "振动"
    table.cell(1, 1).text = "10 Hz"
    source = save_doc(tmp_path, document)
    dest = tmp_path / "revision.docx"
    identity = find_paragraph(source, paragraph.text)["id"]
    result = apply_edits(source, dest, [{"op": "replace_text", "element_id": identity, "text": "绝缘电阻 2000 MΩ；额定电压 250 V"}])
    loaded = Document(dest)
    assert loaded.paragraphs[0].text == "绝缘电阻 2000 MΩ；额定电压 250 V"
    assert loaded.paragraphs[0].runs[0].bold is True
    assert loaded.paragraphs[0].runs[1].italic is True
    assert loaded.paragraphs[0].style.name == "List Number"
    assert len(loaded.inline_shapes) == 1
    with ZipFile(source) as before, ZipFile(dest) as after:
        assert before.namelist() == after.namelist()
        for name in before.namelist():
            if name != "word/document.xml":
                assert before.read(name) == after.read(name), name
    assert result["changes"][0]["before"] == paragraph.text
    assert result["changed_element_ids"] == [identity]
    assert Document(source).paragraphs[0].text == paragraph.text


@pytest.mark.parametrize("before,after", [
    (["abc", "def"], "aXef"),
    (["abc", "def"], "abcdef!"),
    (["abc", "def"], "!abcdef"),
    (["abc", "def"], ""),
    (["abc", "def"], "aXcdeY"),
    (["a", "a", "b", "a", "a"], "aaXaa"),
    (["", "abc", ""], "ab!c"),
    ([""], "新增内容\t制表\n第二行"),
    (["abc", "def"], "a\tbc\ndef"),
])
def test_text_patch_preserves_actual_word_text(tmp_path, before, after):
    document = Document()
    paragraph = document.add_paragraph()
    for text in before:
        paragraph.add_run(text)
    source = save_doc(tmp_path, document)
    dest = tmp_path / "revision.docx"
    apply_edits(source, dest, [{"op": "replace_text", "element_id": find_paragraph(source, paragraph.text)["id"], "text": after}])
    assert Document(dest).paragraphs[0].text == after


def test_table_paragraph_edit_insert_and_delete_preserves_cell_structure(tmp_path):
    document = Document()
    document.add_heading("技术指标", 1)
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "原要求"
    table.cell(0, 0).add_paragraph("删除要求")
    source = save_doc(tmp_path, document)
    dest = tmp_path / "revision.docx"
    operations = [
        {"op": "replace_text", "element_id": find_paragraph(source, "原要求")["id"], "text": "修订要求"},
        {"op": "insert_paragraph", "element_id": find_paragraph(source, "原要求")["id"], "text": "补充要求", "position": "after"},
        {"op": "delete_paragraph", "element_id": find_paragraph(source, "删除要求")["id"]},
    ]
    apply_edits(source, dest, operations)
    assert [p.text for p in Document(dest).tables[0].cell(0, 0).paragraphs] == ["修订要求", "补充要求"]


def test_insert_after_heading_is_plain_text_not_an_extra_heading(tmp_path):
    document = Document()
    document.add_heading("章节", 1)
    source = save_doc(tmp_path, document)
    dest = tmp_path / "revision.docx"
    apply_edits(source, dest, [{"op": "insert_paragraph", "element_id": find_paragraph(source, "章节")["id"], "text": "新增正文"}])
    assert Document(dest).paragraphs[1].style.name == "Normal"
    assert len(document_projection(dest)["outline"]) == 1


def test_images_are_projected_and_cannot_be_deleted_but_text_can_change(tmp_path):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(PNG)
    document = Document()
    paragraph = document.add_paragraph("图题")
    paragraph.add_run().add_picture(str(image_path), width=Inches(0.1))
    source = save_doc(tmp_path, document)
    projected = find_paragraph(source, "图题")
    assert projected["images"][0]["src"].startswith("data:image/png;base64,")
    assert projected["editable"] is True
    assert projected["can_delete"] is False
    dest = tmp_path / "revision.docx"
    with pytest.raises(ValueError, match="图片"):
        apply_edits(source, dest, [{"op": "delete_paragraph", "element_id": projected["id"]}])
    assert not dest.exists()
    apply_edits(source, dest, [{"op": "replace_text", "element_id": projected["id"], "text": "修改图题"}])
    assert len(Document(dest).inline_shapes) == 1


@pytest.mark.parametrize("tag", ["fldChar", "hyperlink", "sdt", "ins"])
def test_special_structure_is_read_only(tmp_path, tag):
    document = Document()
    paragraph = document.add_paragraph("保留特殊结构")
    paragraph._p.append(OxmlElement("w:" + tag))
    source = save_doc(tmp_path, document)
    projected = find_paragraph(source, "保留特殊结构")
    assert projected["editable"] is False
    assert projected["edit_reason"]
    with pytest.raises(ValueError, match="版式编辑器"):
        apply_edits(source, tmp_path / "revision.docx", [{"op": "replace_text", "element_id": projected["id"], "text": "不能修改"}])


def test_deleting_all_cell_paragraphs_in_one_batch_is_rejected(tmp_path):
    document = Document()
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    cell.text = "A"
    cell.add_paragraph("B")
    source = save_doc(tmp_path, document)
    operations = [{"op": "delete_paragraph", "element_id": find_paragraph(source, text)["id"]} for text in ("A", "B")]
    with pytest.raises(ValueError, match="至少需要保留"):
        apply_edits(source, tmp_path / "revision.docx", operations)


def test_invalid_batch_never_changes_source_or_destination(tmp_path):
    document = Document()
    document.add_paragraph("原文")
    source = save_doc(tmp_path, document)
    original_bytes = source.read_bytes()
    dest = tmp_path / "revision.docx"
    dest.write_bytes(b"unchanged")
    identity = find_paragraph(source, "原文")["id"]
    for operations in (
        [{"op": "replace_text", "element_id": "unknown", "text": "x"}],
        [{"op": "replace_text", "element_id": identity, "text": "x"}] * 2,
        [{"op": "delete_paragraph", "element_id": identity}, {"op": "replace_text", "element_id": identity, "text": "x"}],
        [{"op": "replace_text", "element_id": identity, "text": "bad\x00text"}],
    ):
        with pytest.raises(ValueError):
            apply_edits(source, dest, operations)
        assert source.read_bytes() == original_bytes
        assert dest.read_bytes() == b"unchanged"
    with pytest.raises(ValueError, match="不能覆盖"):
        apply_edits(source, source, [{"op": "replace_text", "element_id": identity, "text": "x"}])


def test_previous_revision_ids_are_rejected_after_save(tmp_path):
    document = Document()
    document.add_paragraph("旧版")
    source = save_doc(tmp_path, document)
    revision = tmp_path / "revision.docx"
    identity = find_paragraph(source, "旧版")["id"]
    apply_edits(source, revision, [{"op": "replace_text", "element_id": identity, "text": "新版"}])
    with pytest.raises(ValueError, match="版本已变化"):
        apply_edits(revision, tmp_path / "next.docx", [{"op": "replace_text", "element_id": identity, "text": "丢失更新"}])


def test_oversize_images_only_warn(tmp_path, monkeypatch):
    import jonhon_taskbook.review_document as module
    image_path = tmp_path / "image.png"
    image_path.write_bytes(PNG)
    document = Document()
    document.add_paragraph().add_run().add_picture(str(image_path), width=Inches(0.1))
    source = save_doc(tmp_path, document)
    monkeypatch.setattr(module, "MAX_IMAGE_BYTES", 1)
    projected = document_projection(source)
    assert projected["warnings"]
    assert projected["blocks"][0]["images"][0]["available"] is False


def test_repeated_images_also_respect_total_response_budget(tmp_path, monkeypatch):
    import jonhon_taskbook.review_document as module
    image_path = tmp_path / "image.png"
    image_path.write_bytes(PNG)
    document = Document()
    for _ in range(2):
        document.add_paragraph().add_run().add_picture(str(image_path), width=Inches(0.1))
    source = save_doc(tmp_path, document)
    monkeypatch.setattr(module, "MAX_TOTAL_IMAGE_BYTES", len(PNG))
    projected = document_projection(source)
    assert projected["blocks"][0]["images"][0]["available"] is True
    assert projected["blocks"][1]["images"][0]["available"] is False


def test_unchanged_text_preserves_exact_archive_hash(tmp_path):
    document = Document()
    document.add_paragraph("未修改")
    source = save_doc(tmp_path, document)
    dest = tmp_path / "revision.docx"
    result = apply_edits(source, dest, [{"op": "replace_text", "element_id": find_paragraph(source, "未修改")["id"], "text": "未修改"}])
    assert result["changes"] == []
    assert source.read_bytes() == dest.read_bytes()


def test_special_metadata_at_body_level_is_not_an_unsupported_content_warning(tmp_path):
    document = Document()
    document.add_paragraph("内容")
    bookmark = OxmlElement("w:bookmarkEnd")
    bookmark.set(qn("w:id"), "0")
    document._element.body.insert(1, bookmark)
    source = save_doc(tmp_path, document)
    assert document_projection(source)["warnings"] == []


def test_numbering_properties_and_page_breaks_survive_unrelated_text_edit(tmp_path):
    document = Document()
    paragraph = document.add_paragraph("正文")
    properties = paragraph._p.get_or_add_pPr()
    num_pr = OxmlElement("w:numPr")
    num_id = OxmlElement("w:numId")
    num_id.set(qn("w:val"), "4")
    num_pr.append(num_id)
    properties.append(num_pr)
    run = paragraph.add_run()
    page_break = OxmlElement("w:br")
    page_break.set(qn("w:type"), "page")
    run._r.append(page_break)
    source = save_doc(tmp_path, document)
    dest = tmp_path / "revision.docx"
    apply_edits(source, dest, [{"op": "replace_text", "element_id": find_paragraph(source, "正文\n")["id"], "text": "修改正文\n"}])
    paragraph = Document(dest).paragraphs[0]
    assert paragraph._p.find(".//" + qn("w:numId")).get(qn("w:val")) == "4"
    assert paragraph._p.find(".//" + qn("w:br")).get(qn("w:type")) == "page"
