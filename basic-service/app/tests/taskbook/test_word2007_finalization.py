"""Final DOCX writers retain evidence while encoding legacy Word bit flags."""

from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
from lxml import etree
from PIL import Image

from jonhon_taskbook.auto_repair import run_auto_repair
from jonhon_taskbook.placeholder_cleanup import final_placeholder_sweep_docx
from jonhon_taskbook.postprocess import postprocess


def _set_look(properties, value, **flags):
    look = properties.find(qn("w:tblLook"))
    if look is None:
        look = OxmlElement("w:tblLook")
        properties.append(look)
    look.attrib.clear()
    look.set(qn("w:val"), value)
    for name, enabled in flags.items():
        look.set(qn("w:" + name), enabled)


def _fixture(tmp_path):
    document = Document()
    document.add_heading("技术资料", 1)
    document.add_paragraph("工作压力0.3MPa，温度5℃～42℃。")
    table = document.add_table(rows=2, cols=2)
    for cell, text in zip(table._cells, ("原始项目", "原始数值", "管长", "200mm")):
        cell.text = text
    _set_look(table._tbl.tblPr, "04A0", firstRow="false", lastRow="1")

    style = document.styles.add_style("Copied evidence table", WD_STYLE_TYPE.TABLE)
    properties = OxmlElement("w:tblPr")
    style.element.append(properties)
    _set_look(properties, "04A0", firstRow="0", noVBand="off")
    table.style = style

    header = document.sections[0].header
    header.paragraphs[0].text = "原始资料页眉"
    header_table = header.add_table(rows=1, cols=2, width=Inches(5))
    header_table.cell(0, 0).text = "原始记录"
    header_table.cell(0, 1).text = "原始状态"
    _set_look(header_table._tbl.tblPr, "04A0", firstColumn="false",
              lastColumn="on", noHBand="true")

    settings = document.settings.element
    filter_node = settings.find(qn("w:stylePaneFormatFilter"))
    if filter_node is None:
        filter_node = OxmlElement("w:stylePaneFormatFilter")
        settings.append(filter_node)
    filter_node.attrib.clear()
    filter_node.set(qn("w:val"), "000C")
    filter_node.set(qn("w:allStyles"), "1")
    filter_node.set(qn("w:stylesInUse"), "false")

    image = BytesIO()
    Image.new("RGB", (12, 8), "#2060a0").save(image, format="PNG")
    document.add_picture(BytesIO(image.getvalue()), width=Inches(.3))
    header.paragraphs[0].add_run().add_picture(BytesIO(image.getvalue()), width=Inches(.3))
    document.add_paragraph("待填写时长：[XXh]")
    path = tmp_path / "final-word2007.docx"
    document.save(path)
    return path


def _parts(path):
    with ZipFile(path) as package:
        return {name: package.read(name) for name in package.namelist()}


def _evidence(parts):
    media = {name: sha256(data).hexdigest() for name, data in parts.items()
             if name.startswith("word/media/")}
    relationships = {
        name: sorted(tuple(sorted(node.attrib.items())) for node in etree.fromstring(data))
        for name, data in parts.items() if name.endswith(".rels")
    }
    geometry = {}
    texts = {}
    for name in ("word/document.xml", "word/header1.xml"):
        root = etree.fromstring(parts[name])
        texts[name] = [node.text or "" for node in root.iter(qn("w:t"))]
        geometry[name] = [
            [(etree.QName(node).localname, tuple(sorted(node.attrib.items())))
             for node in table.iter()
             if node.tag in {qn("w:gridCol"), qn("w:tcW"), qn("w:gridSpan"), qn("w:vMerge")}]
            for table in root.iter(qn("w:tbl"))
        ]
    return media, relationships, geometry, texts


def _assert_legacy_flags(parts):
    # Independent bit-mask examples: firstRow=0020, lastRow=0040,
    # firstColumn=0080, lastColumn=0100, noHBand=0200, noVBand=0400.
    for name, expected in (("word/document.xml", 0x04C0),
                           ("word/header1.xml", 0x0720)):
        root = etree.fromstring(parts[name])
        look = root.find(".//" + qn("w:tblLook"))
        assert set(look.attrib) == {qn("w:val")}, (name, dict(look.attrib))
        assert int(look.get(qn("w:val")), 16) == expected
    styles = etree.fromstring(parts["word/styles.xml"])
    style = next(node for node in styles.iter(qn("w:style"))
                 if node.find(qn("w:name")) is not None
                 and node.find(qn("w:name")).get(qn("w:val")) == "Copied evidence table")
    look = style.find(".//" + qn("w:tblLook"))
    assert set(look.attrib) == {qn("w:val")}
    assert int(look.get(qn("w:val")), 16) == 0x0080
    settings = etree.fromstring(parts["word/settings.xml"])
    filter_node = settings.find(qn("w:stylePaneFormatFilter"))
    assert set(filter_node.attrib) == {qn("w:val")}
    # Preserve existing 0004, enable allStyles=0001, disable stylesInUse=0008.
    assert int(filter_node.get(qn("w:val")), 16) == 0x0005


def test_postprocess_then_placeholder_sweep_preserves_word2007_flags_and_evidence(tmp_path):
    path = _fixture(tmp_path)
    before = _evidence(_parts(path))

    postprocess(path)
    assert final_placeholder_sweep_docx(path) == 1

    after_parts = _parts(path)
    after = _evidence(after_parts)
    assert after[:3] == before[:3]
    expected_texts = {name: [text.replace("[XXh]", "/") for text in texts]
                      for name, texts in before[3].items()}
    assert after[3] == expected_texts
    _assert_legacy_flags(after_parts)


def test_auto_repair_candidate_final_writer_preserves_word2007_flags_and_evidence(tmp_path):
    path = _fixture(tmp_path)
    before = _evidence(_parts(path))

    def evaluate(candidate):
        # A real package read keeps this at the repair publication boundary.
        # Compatibility-only repair must never clear a separate human review.
        assert _evidence(_parts(candidate)) == before
        return {"qa_ok": True, "delivery_gate_ok": False,
                "blocking_keys": ["SOURCE_REVIEW_REQUIRED"],
                "covered_source_ids": ["original-evidence"],
                "semantic_integrity": {"violations": []}}

    report = run_auto_repair(path, None, None, evaluate=evaluate, cb=lambda _: None)

    _assert_legacy_flags(_parts(path))
    assert report["accepted_rounds"] == 1
    assert report["snapshot"]["blocking_keys"] == ["SOURCE_REVIEW_REQUIRED"]
    assert not report["snapshot"]["delivery_gate_ok"]
    assert _evidence(_parts(path)) == before
