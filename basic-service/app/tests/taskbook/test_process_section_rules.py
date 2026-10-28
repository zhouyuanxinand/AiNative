"""Process-dependent template sections, including the appendix boundary."""

import json

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from jonhon_taskbook.fill import _apply_process_specific_sections, fill
from jonhon_taskbook.postprocess import postprocess
from jonhon_taskbook.qa_gate import QAGate
from jonhon_taskbook.template_registry import resolve_template_selection


PROCESSES = ("全新", "改型I", "改型II", "改型III")
FAMILIES = (
    "low_frequency_rectangular", "rf_contact", "filter_connector",
    "cable_assembly", "liquid_cooling_pipeline", "liquid_cooling_chassis",
)


def section_presence(document):
    texts = ["".join(paragraph.text.split()) for paragraph in document.paragraphs]
    return {
        "qfd": any("QFD质量功能分解" in text for text in texts),
        "scene": any(text.startswith("产品运行场景识别") for text in texts),
        "appendix_a": any(text.startswith("附录A") for text in texts),
    }


@pytest.mark.parametrize("product_type", FAMILIES)
@pytest.mark.parametrize("process", PROCESSES)
def test_real_template_sections_survive_full_fill_and_postprocess(tmp_path, product_type, process):
    selected = resolve_template_selection(product_type, "military")
    template = Document(selected.template_path)
    original = section_presence(template)
    assert original["scene"] and original["appendix_a"]
    tech, spec, output = (tmp_path / name for name in ("tech.docx", "spec.docx", "out.docx"))
    Document().save(tech)
    Document().save(spec)
    fill(
        str(tech), str(spec), selected.template_path, str(output), selected.profile_path,
        category_mapping_path=selected.category_mapping_path,
        requirement_classification={"source_blocks": [], "classifications": []},
        development_process=process, controlled_product_domain="military",
        controlled_product_label=selected.product_type_label,
        product_series="无历史记录合成系列", preserve_unfilled_template=True, finalize=False,
    )
    filled = Document(output)
    assert filled.element.body.find(qn("w:sectPr")) is not None
    assert filled.sections[-1].page_width == template.sections[-1].page_width
    postprocess(output, preserve_template_guidance=True, selected_product_domain="military")
    rendered = Document(output)
    assert section_presence(rendered) == {
        "qfd": original["qfd"] and process == "全新",
        "scene": process in {"全新", "改型I"},
        "appendix_a": process in {"全新", "改型I"},
    }
    assert any("任务书编制依据" in paragraph.text for paragraph in rendered.paragraphs)
    assert any("工艺要求" in paragraph.text for paragraph in rendered.paragraphs)
    assert rendered.element.body.find(qn("w:sectPr")) is not None
    audit = json.loads(output.with_suffix(".process_rule_audit.json").read_text(encoding="utf-8"))
    assert ("附录A" in audit["deleted_semantic_headings"]) == (process in {"改型II", "改型III"})
    quality = QAGate(
        {"block_if": {"appendix_a_empty_table_exists": True}},
        {"preserve_template_guidance": True, "template_path": selected.template_path},
    ).check(rendered.element)
    assert not any("附录A" in reason for reason in quality["block_reasons"])


@pytest.mark.parametrize("process", ("改型II", "改型III类"))
def test_linked_appendix_removed_without_primary_heading_and_next_appendix_preserved(tmp_path, process):
    document = Document()
    document.styles.add_style("附录标识", WD_STYLE_TYPE.PARAGRAPH)
    document.add_heading("其他要求", 1)
    document.add_paragraph("正文仅引用附录A，不是附录标题。")
    document.add_paragraph("附 录 A\n产品运行场景识别", "附录标识")
    document.add_paragraph("场景附录的正文")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "场景表格内容"
    document.add_paragraph("附录 B\n其他附录", "附录标识")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "必须保留的附录B表格"
    audit = _apply_process_specific_sections(
        document, {}, process, "滤波连接器", "合成系列", str(tmp_path / "out.docx"),
    )
    text = "\n".join(document.element.body.xpath(".//w:t/text()"))
    assert "正文仅引用附录A，不是附录标题。" in text
    assert "场景附录的正文" not in text
    assert "场景表格内容" not in text
    assert "必须保留的附录B表格" in text
    assert document.element.body.find(qn("w:sectPr")) is not None
    scene = next(item for item in audit["section_retention_rules"] if item["id"] == "running_scene")
    assert scene["removed_nodes"] == 0 and scene["linked_removed_nodes"] == 3


def test_qfd_subtree_deletion_uses_heading_identity_not_position_or_body_reference(tmp_path):
    document = Document()
    document.add_heading("工艺要求", 1)
    document.add_paragraph("此处的材料要求保留；相关流程曾参考产品需求分解。")
    for index in (23, 51):
        document.add_heading(f"{index}.7 产品需求分解（QFD质量功能分解）", 2)
        document.add_heading("质量屋分解", 3)
        document.add_paragraph("QFD 专属正文")
        document.add_table(rows=1, cols=1).cell(0, 0).text = "QFD 专属表格"
        document.add_heading(f"{index}.8 相邻章节", 2)
        document.add_paragraph(f"相邻正文{index}")
    audit = _apply_process_specific_sections(
        document, {}, "改型I类", "滤波连接器", "合成系列", str(tmp_path / "out.docx"),
    )
    text = "\n".join(document.element.body.xpath(".//w:t/text()"))
    assert "QFD 专属" not in text and "质量屋分解" not in text
    assert "此处的材料要求保留；相关流程曾参考产品需求分解。" in text
    assert "相邻正文23" in text and "相邻正文51" in text
    assert audit["section_retention_rules"][0]["removed_nodes"] == 8
