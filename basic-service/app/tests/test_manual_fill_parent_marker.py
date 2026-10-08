from pathlib import Path

from docx import Document

from jonhon_taskbook.postprocess import postprocess


MANUAL_FILL_MARKER = "【人工填写】"


def test_multiple_unfilled_children_share_one_marker_on_parent_heading(
    tmp_path: Path,
) -> None:
    """The production postprocessor must collapse one pending subtree to its parent."""
    path = tmp_path / "customer-requirements.docx"
    document = Document()
    parent = document.add_heading("顾客的特殊要求", level=1)
    document.add_paragraph().add_run(
        "（此条要求对顾客的特殊要求进行识别，没有可写无）"
    ).italic = True
    first_child = document.add_heading("超出现有技术的要求", level=2)
    document.add_paragraph("由设计人员填写。")
    second_child = document.add_heading("超出同类产品状态的要求", level=2)
    document.add_paragraph("由设计人员填写。")
    document.save(path)

    # This is the same finalization step used by pipeline_cli and fill(finalize=True).
    postprocess(path, preserve_template_guidance=True)
    postprocess(path, preserve_template_guidance=True)
    rendered = Document(path)

    heading_texts = [
        paragraph.text
        for paragraph in rendered.paragraphs
        if paragraph.style.name.startswith("Heading")
    ]
    assert sum(text.count(MANUAL_FILL_MARKER) for text in heading_texts) == 1
    assert heading_texts == [
        f"{parent.text}{MANUAL_FILL_MARKER}",
        first_child.text,
        second_child.text,
    ]
    assert all(
        MANUAL_FILL_MARKER not in paragraph.text
        for paragraph in rendered.paragraphs
        if not paragraph.style.name.startswith("Heading")
    )

    rendered_parent = rendered.paragraphs[0]
    marker_run = next(
        run for run in rendered_parent.runs if run.text == MANUAL_FILL_MARKER
    )
    assert marker_run.bold is True
    assert str(marker_run.font.color.rgb) == "FF0000"


def test_explicit_table_marker_stays_in_cell_without_marking_heading(
    tmp_path: Path,
) -> None:
    path = tmp_path / "indicator.docx"
    document = Document()
    document.add_heading("技术指标", level=1)
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    cell.text = "【人工标注】"
    document.save(path)

    postprocess(path, preserve_template_guidance=True)
    postprocess(path, preserve_template_guidance=True)
    rendered = Document(path)

    assert MANUAL_FILL_MARKER not in rendered.paragraphs[0].text
    rendered_cell = rendered.tables[0].cell(0, 0)
    assert rendered_cell.text == MANUAL_FILL_MARKER
    marker_run = next(
        run
        for paragraph in rendered_cell.paragraphs
        for run in paragraph.runs
        if run.text == MANUAL_FILL_MARKER
    )
    assert marker_run.bold is True
    assert str(marker_run.font.color.rgb) == "FF0000"
