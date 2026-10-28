from tests.support.paths import APP_ROOT
import base64
import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from jonhon_taskbook.development_process_policy import normalize_development_process
from jonhon_taskbook.domain_sections import apply_domain_sections
from jonhon_taskbook.failure_mode_matcher import match_failure_modes_with_audit
from jonhon_taskbook.fill import fill
from jonhon_taskbook.postprocess import postprocess
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks
from jonhon_taskbook.template_registry import resolve_template_selection
from jonhon_taskbook.template_scanner import heading_level, semantic_title
from openpyxl import Workbook


def failure_database(path: Path, models, description="密封失效"):
    book = Workbook()
    sheet = book.active
    sheet.append(["数据所属产品的产品名称", "所属型号", "故障描述", "故障原因", "设计改进措施"])
    for model in models:
        sheet.append(["低频连接器-圆形低频-O形圈", model, description, "尺寸偏差", "控制尺寸"])
    book.save(path)
    book.close()


def test_c53_series_letters_are_exact_not_symmetric_prefix(tmp_path):
    path = tmp_path / "failures.xlsx"
    failure_database(path, ["ICG-08BKTK0-70", "ICGB-01", "IC", "OTHER-01"])
    records, audit = match_failure_modes_with_audit("低频连接器-圆形低频", "ICG", path)
    assert [row["product_series"] for row in records] == ["ICG-08BKTK0-70"]
    assert records[0]["product_name"] == "低频连接器-圆形低频"
    assert records[0]["failure_location"] == "O形圈"
    assert records[0]["failure_mode"] == "密封失效"
    assert records[0]["failure_analysis"] == "尺寸偏差"
    assert records[0]["reliability_design_method"] == "控制尺寸"
    assert audit["rejected_counts"]["series_mismatch"] == 3


def test_c53_blank_failure_description_never_uses_unprovided_columns(tmp_path):
    path = tmp_path / "failures.xlsx"
    failure_database(path, ["ICG-08"], description=None)
    records, audit = match_failure_modes_with_audit("低频连接器-圆形低频", "ICG", path)
    assert len(records) == 1
    assert records[0]["failure_mode"] == ""
    assert audit["accepted_count"] == 1


@pytest.mark.parametrize("value", ["改型I类", "改型II类", "改型III类"])
def test_c53_workbook_process_labels_are_accepted(value):
    assert normalize_development_process(value) == value.removesuffix("类")


def test_c54_potential_analysis_preserves_template_cell_content(tmp_path):
    path = tmp_path / "manual.docx"
    document = Document()
    document.add_heading("潜在失效模式初步分析", 2)
    table = document.add_table(rows=2, cols=5)
    for cell, text in zip(table.rows[0].cells, ["序号", "可能发生的失效模式", "失效模式机理", "失效模式后果", "可考虑的解决办法"]):
        cell.text = text
    table.cell(1, 0).text = "1"
    table.cell(1, 1).text = "由设计员识别失效模式"
    document.save(path)
    postprocess(path, preserve_template_guidance=True)
    rendered = Document(path)
    assert rendered.tables[0].cell(1, 0).text == "1"
    assert rendered.tables[0].cell(1, 1).text == "由设计员识别失效模式"


def test_b57_manual_headings_have_canonical_red_marker_even_without_italics(tmp_path):
    path = tmp_path / "manual.docx"
    document = Document()
    for heading in ("进度要求", "研制经费预算（适用于非中央研究院产品）", "潜在失效模式初步分析"):
        document.add_heading(heading, 1)
        document.add_paragraph("由设计填写。")
    old = document.add_heading("详细要求", 1)
    old.add_run("【人工")
    old.add_run("标注】")
    document.add_paragraph("模板原有内容")
    document.save(path)
    postprocess(path, preserve_template_guidance=True)
    postprocess(path, preserve_template_guidance=True)
    rendered = Document(path)
    headings = [p for p in rendered.paragraphs if p.style.name.startswith("Heading")]
    assert len(headings) == 4
    for heading in headings:
        assert heading.text.count("【人工填写】") == 1
        marker = next(run for run in heading.runs if run.text == "【人工填写】")
        assert marker.bold
        assert str(marker.font.color.rgb) == "FF0000"
        assert "人工标注" not in heading.text


@pytest.mark.parametrize("preserve", [False, True])
def test_b56_preservation_keeps_template_placeholder_in_manual_schedule(tmp_path, preserve):
    path = tmp_path / "schedule.docx"
    document = Document()
    document.add_heading("进度要求", 1)
    document.add_paragraph("20xx年x月完成样品研制")
    document.add_paragraph("……")
    document.add_heading("后续章节", 1)
    document.add_paragraph("模板保留正文")
    document.save(path)
    postprocess(path, preserve_template_guidance=preserve)
    rendered = Document(path)
    texts = [paragraph.text for paragraph in rendered.paragraphs]
    assert "20xx年x月完成样品研制" in texts
    assert "……" in texts
    assert "模板保留正文" in texts


@pytest.mark.parametrize("domain", ["军品", "适航", "民机", "AS9100"])
def test_c55_domain_removal_removes_full_subtree_not_references(domain):
    document = Document()
    labels = {"军品": None, "适航": "适航要求", "民机": "民机专项要求", "AS9100": "原材料/元器件过时淘汰风险（AS9100）"}
    document.add_heading("引用标准（含 AS9100）", 1)
    document.add_paragraph("AS9100D 航空航天质量标准条款")
    document.add_heading("通用要求", 1)
    document.add_paragraph("本项引用适航标准、民机规范和 AS9100，不是领域专用分支。")
    for index, label in enumerate(filter(None, labels.values()), 1):
        document.add_heading(f"{index + 20} {label}", 1)
        document.add_paragraph(f"专用正文：{label}")
        document.add_heading("下级内容", 2)
        document.add_table(rows=1, cols=1).cell(0, 0).text = f"专用表格：{label}"
    document.add_heading("进度要求", 1)
    document.add_paragraph("由设计填写")
    audit = apply_domain_sections(document, domain)
    texts = [paragraph.text for paragraph in document.paragraphs]
    all_text = "\n".join(texts + [cell.text for table in document.tables for row in table.rows for cell in row.cells])
    assert "引用标准（含 AS9100）" in texts
    assert "AS9100D 航空航天质量标准条款" in texts
    assert "进度要求" in texts
    assert "通用要求" in texts
    for selected, label in labels.items():
        if not label:
            continue
        assert (f"专用正文：{label}" in all_text) == (selected == domain)
        assert (f"专用表格：{label}" in all_text) == (selected == domain)
    assert len(audit["deleted_sections"]) == (3 if domain == "军品" else 2)


@pytest.mark.parametrize("domain", ["military", "airworthiness", "civil_aviation", "as9100"])
def test_c55_real_connector_template_selects_exact_domain(domain):
    template = APP_ROOT / "src/service/jonhon_taskbook/resources/templates/connector_taskbook.docx"
    document = Document(template)
    apply_domain_sections(document, domain)
    headings = [paragraph.text for paragraph in document.paragraphs if paragraph.style.name.startswith("Heading")]
    assert any("适航要求" in heading for heading in headings) == (domain == "airworthiness")
    assert any("过时淘汰风险" in heading for heading in headings) == (domain == "as9100")
    assert any("进度要求" in heading for heading in headings)


@pytest.mark.parametrize("preserve", [False, True])
def test_c55_cleanup_does_not_undo_selected_airworthiness_domain(tmp_path, preserve):
    path = tmp_path / "domain.docx"
    document = Document()
    document.add_heading("适航要求（非适航产品请删除）", 1)
    document.add_heading("适用的适航条款", 2)
    document.add_paragraph("型号审定条款由用户提供。")
    document.add_heading("AS9100 专项要求", 1)
    document.add_paragraph("应删除的正文")
    apply_domain_sections(document, "适航")
    document.save(path)
    postprocess(path, preserve_template_guidance=preserve, selected_product_domain="airworthiness")
    texts = [paragraph.text for paragraph in Document(path).paragraphs]
    assert "适航要求（非适航产品请删除）" in texts
    assert "适用的适航条款" in texts
    assert "型号审定条款由用户提供。" in texts
    assert "应删除的正文" not in texts


def test_b57_cover_table_manual_marker_retains_valid_xml_and_red_color(tmp_path):
    path = tmp_path / "cover.docx"
    document = Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "设计人员"
    table.cell(0, 1).text = "【人工填写】"
    document.save(path)
    postprocess(path, preserve_template_guidance=True)
    postprocess(path, preserve_template_guidance=True)
    rendered = Document(path)
    marker = next(run for run in rendered.tables[0].cell(0, 1).paragraphs[0].runs if run.text == "【人工填写】")
    assert str(marker.font.color.rgb) == "FF0000"
    assert marker.bold
    assert rendered.tables[0].cell(0, 1).text == "【人工填写】"


def section_text(document, title):
    paragraphs = [paragraph for paragraph in document.paragraphs if heading_level(paragraph)]
    start = next((paragraph for paragraph in paragraphs if semantic_title(paragraph.text).replace("【人工填写】", "").rstrip("：:") == title), None)
    if start is None:
        return None
    depth = heading_level(start)
    node = start._p.getnext()
    parts = []
    while node is not None:
        if node.tag == qn("w:p"):
            level = heading_level(Paragraph(node, document))
            if level and level <= depth:
                break
        parts.extend(node.xpath(".//w:t/text()"))
        node = node.getnext()
    return "\n".join(parts).replace("【人工填写】", "")


@pytest.fixture
def fill_workbook_case(tmp_path):
    selected = resolve_template_selection("low_frequency_rectangular", "military")

    def run(process="全新", inputs=(), source_factory=None):
        source = Document()
        roles = {}
        for heading, role, evidence in inputs:
            source.add_heading(heading, 1)
            roles[heading] = role
            source.add_paragraph().add_run(evidence).bold = True
        if source_factory:
            source, roles = source_factory()
        tech = tmp_path / "source.docx"
        spec = tmp_path / "spec.docx"
        output = tmp_path / "result.docx"
        source.save(tech)
        Document().save(spec)
        blocks = extract_source_blocks(str(tech), "tech")
        classification = {
            "source_blocks": blocks,
            "classifications": [{"source_id": block["id"], "category": roles[block["heading_text"]]} for block in blocks],
        }
        # 不依赖 review_copy 开关：默认正式路径也要遵循业务模板保留规则。
        fill(str(tech), str(spec), selected.template_path, str(output), selected.profile_path,
             category_mapping_path=selected.category_mapping_path,
             requirement_classification=classification, development_process=process,
             controlled_product_domain="military", controlled_product_label=selected.product_type_label,
             product_series="无历史记录的合成验证", finalize=False)
        return Document(selected.template_path), Document(output)

    return run


def test_e30_e38_no_input_preserves_real_template_in_default_fill(fill_workbook_case):
    original, result = fill_workbook_case()
    for title in ("来源和功能", "使用环境和部位", "产品组成", "安装方式", "外形尺寸", "安装尺寸", "互换性要求", "条件保障要求"):
        assert section_text(result, title) == section_text(original, title), title


def test_c26_d46_schedule_input_cannot_replace_template(fill_workbook_case):
    original, result = fill_workbook_case(inputs=[("进度要求", "schedule", "2099年1月1日完成试验，这是输入中出现的时间。")])
    apply_domain_sections(original, "military")
    assert section_text(result, "任务进度要求") == section_text(original, "任务进度要求")
    assert "2099年1月1日" not in "\n".join(paragraph.text for paragraph in result.paragraphs)


def test_e30_source_and_function_copies_whole_paragraphs_and_format(fill_workbook_case):
    texts = ("为某设备新增配套接口，用户要求开展定制研制。", "产品负责电能传输，并提供辅助状态信号。")
    _, result = fill_workbook_case(inputs=[("来源和功能", "source_and_function", text) for text in texts])
    rendered_section = section_text(result, "来源和功能")
    for text in texts:
        assert text in rendered_section
        paragraph = next(paragraph for paragraph in result.paragraphs if paragraph.text == text)
        assert any(run.text == text and run.bold for run in paragraph.runs)


@pytest.mark.parametrize("process", ["全新", "改型I", "改型II", "改型III"])
def test_e39_quality_sections_follow_process_when_input_absent(fill_workbook_case, process):
    original, result = fill_workbook_case(process=process)
    for title in ("可靠性要求", "维修性要求", "测试性要求", "保障性要求", "安全性定性要求", "环境适应性要求"):
        if process == "全新":
            assert section_text(result, title) == section_text(original, title), title
        else:
            assert section_text(result, title) is None, title
    potential = "潜在失效模式初步分析"
    if process in {"全新", "改型I"}:
        assert section_text(result, potential) == section_text(original, potential)
    else:
        assert section_text(result, potential) is None


def test_e39_existing_quality_input_copied_for_modified_product(fill_workbook_case):
    evidence = "产品应具备故障隔离能力，维修时间不超过30分钟。"
    _, result = fill_workbook_case(process="改型II", inputs=[("维修性要求", "maintainability", evidence)])
    assert evidence in section_text(result, "维修性要求")
    assert section_text(result, "可靠性要求") is None


@pytest.mark.parametrize("source_heading,target_heading,evidence", [
    ("MTBF", "可靠性要求", "MTBF不低于10000 h，试验时应记录每次故障现象及间隔。"),
    ("盐雾", "环境适应性要求", "盐雾试验持续48 h，试验后接触部位不得出现影响连接功能的腐蚀。"),
    ("工作温度", "环境适应性要求", "工作温度为-40℃～85℃；高温运行后应检查密封垫和外壳完整性。"),
])
def test_e39_performance_evidence_is_copied_whole_into_quality_section(fill_workbook_case, source_heading, target_heading, evidence):
    _, result = fill_workbook_case(process="改型II", inputs=[(source_heading, "performance_indicator", evidence)])
    text = section_text(result, target_heading)
    assert text is not None
    assert text.count(evidence) == 1
    paragraph = next(paragraph for paragraph in result.paragraphs if paragraph.text == evidence)
    assert any(run.text == evidence and run.bold for run in paragraph.runs)


@pytest.mark.parametrize("source_heading,evidence", [
    ("工业干扰环境", "工业干扰环境：在10 V/m场强下试验；考核标准：功能不得中断；环境适配约束条件：屏蔽壳体闭合后考核。"),
    ("长期环境稳定性", "长期环境稳定性：-20℃～60℃运行1000 h；耐受阈值：漂移不超过1%；考核标准：按用户环境试验规程验收。"),
    ("力学过载", "力学过载：150 m/s²，三个正交轴分别施加；考核标准：结构无变形且功能正常。"),
])
def test_e39_special_environmental_input_keeps_modified_product_chapter(fill_workbook_case, source_heading, evidence):
    _, result = fill_workbook_case(process="改型II", inputs=[(source_heading, "performance_indicator", evidence)])
    assert evidence in section_text(result, "环境适应性要求")


def test_e39_empty_or_unknown_source_does_not_retain_quality_section(tmp_path):
    from jonhon_taskbook.fill import _apply_process_specific_sections

    document = Document()
    document.add_heading("通用质量特性要求", 1)
    document.add_heading("可靠性要求", 2)
    document.add_paragraph("原模板可靠性说明")
    document.add_heading("环境适应性要求", 2)
    document.add_paragraph("原模板环境说明")
    classification = {
        "source_blocks": [{"id": "empty", "heading_text": "MTBF", "text": ""}],
        "classifications": [{"source_id": "empty", "category": "performance_indicator"}, {"source_id": "missing", "category": "environmental_adaptability"}],
    }
    _apply_process_specific_sections(document, classification, "改型II", "低频连接器-矩形低频", "合成系列", str(tmp_path / "quality.docx"))
    assert section_text(document, "可靠性要求") is None
    assert section_text(document, "环境适应性要求") is None


def test_e39_environment_is_prose_while_other_quality_keeps_source_table(fill_workbook_case):
    image_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5Wk3kAAAAASUVORK5CYII=")

    def source_factory():
        source = Document()
        source.add_heading("性能要求", 1)
        table = source.add_table(rows=3, cols=2)
        for row, values in zip(table.rows, [("指标", "要求"), ("MTBF", "至少10000 h"), ("盐雾", "持续48 h后外壳无明显腐蚀")]):
            for cell, text in zip(row.cells, values):
                cell.text = text
        table.cell(2, 1).paragraphs[0].add_run().add_picture(BytesIO(image_bytes))
        return source, {"性能要求": "performance_indicator"}

    _, result = fill_workbook_case(process="改型II", source_factory=source_factory)
    expected_hash = hashlib.sha256(image_bytes).hexdigest()
    for title in ("可靠性要求", "环境适应性要求"):
        text = section_text(result, title)
        assert text is not None and "持续48 h后外壳无明显腐蚀" in text
        assert ("至少10000 h" in text) == (title == "可靠性要求")
        heading = next(p for p in result.paragraphs if semantic_title(p.text) == title)
        depth = heading_level(heading)
        element = heading._p.getnext()
        tables = []
        while element is not None:
            if element.tag == qn("w:p"):
                level = heading_level(Paragraph(element, result))
                if level and level <= depth:
                    break
            if element.tag == qn("w:tbl"):
                tables.append(element)
            element = element.getnext()
        if title == "环境适应性要求":
            assert not tables
            continue
        assert len(tables) == 1
        image_ids = tables[0].xpath(".//a:blip/@r:embed")
        assert len(image_ids) == 1
        assert hashlib.sha256(result.part.related_parts[image_ids[0]].blob).hexdigest() == expected_hash
