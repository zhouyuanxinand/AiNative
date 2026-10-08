from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from jonhon_taskbook.fill import (
    _apply_process_specific_sections,
    _prepare_manual_potential_failure_analysis_table,
    _technical_support_module_groups,
)
from jonhon_taskbook.coverage_ledger import (
    mark_covered_from_output,
    parse_docx_to_ledger,
)
from jonhon_taskbook.postprocess import postprocess


class P1RuleAlignmentTests(unittest.TestCase):
    def test_condition_support_groups_by_source_heading_not_sentence(self) -> None:
        groups = _technical_support_module_groups(
            [
                {
                    "kind": "paragraph",
                    "source_chapter_id": "acceptance",
                    "source_heading": "6.1 验收要求",
                    "text": "验收在一般大气环境下进行。",
                },
                {
                    "kind": "table",
                    "source_chapter_id": "acceptance",
                    "source_heading": "6.1 验收要求",
                },
                {
                    "kind": "paragraph",
                    "source_chapter_id": "delivery",
                    "source_heading": "6.2 交付要求",
                    "text": "随产品提供使用说明书。",
                },
            ]
        )

        self.assertEqual(["验收要求", "交付要求"], [g["title"] for g in groups])
        self.assertEqual(2, len(groups[0]["items"]))
        self.assertEqual(1, len(groups[1]["items"]))

    def test_potential_failure_analysis_table_is_left_blank_for_manual_input(self) -> None:
        document = Document()
        table = document.add_table(rows=1, cols=5)
        for cell, text in zip(
            table.rows[0].cells,
            ["序号", "可能发生的失效模式", "失效模式机理", "失效模式后果", "可考虑的解决办法"],
        ):
            cell.text = text
        for values in (
            ("1", "历史失效模式", "AI机理", "AI影响", "AI措施"),
            ("2", "另一种模式", "其他机理", "其他影响", "其他措施"),
        ):
            row = table.add_row()
            for cell, text in zip(row.cells, values):
                cell.text = text

        cleared = _prepare_manual_potential_failure_analysis_table(document)

        self.assertEqual(10, cleared)
        self.assertEqual(3, len(table.rows))
        for row in table.rows[1:]:
            self.assertTrue(all(cell.text == "" for cell in row.cells))

    def test_process_sections_follow_explicit_business_retention_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            for process in ("全新", "改型I", "改型II", "改型III"):
                with self.subTest(process=process):
                    document = Document()
                    document.add_heading("产品运行场景识别", level=2)
                    document.add_paragraph("模板说明与示例内容")
                    document.add_heading(
                        "产品需求分解（QFD质量功能分解）（利用EdrawMax编制）",
                        level=2,
                    )
                    document.add_paragraph("模板质量屋示例")
                    document.add_heading("工艺要求", level=1)
                    document.add_paragraph("材料要求按原工艺章节保留。")
                    document.add_heading("附录A", level=1)
                    document.add_paragraph("模板附录说明")
                    _apply_process_specific_sections(
                        document, {"source_blocks": [], "classifications": []},
                        process, "低频连接器-矩形低频", "无历史记录合成系列",
                        str(Path(temp_dir) / f"{process}.docx"),
                    )
                    paragraphs = [paragraph.text for paragraph in document.paragraphs]
                    keep_scene = process in {"全新", "改型I"}
                    self.assertEqual(keep_scene, "产品运行场景识别" in paragraphs)
                    self.assertEqual(keep_scene, "模板说明与示例内容" in paragraphs)
                    self.assertEqual(process == "全新", "模板质量屋示例" in paragraphs)
                    self.assertEqual(keep_scene, "附录A" in paragraphs)
                    self.assertEqual(keep_scene, "模板附录说明" in paragraphs)
                    self.assertIn("工艺要求", paragraphs)
                    self.assertIn("材料要求按原工艺章节保留。", paragraphs)

    def test_postprocess_does_not_delete_retained_qfd_manual_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "taskbook.docx"
            document = Document()
            document.add_heading("产品运行场景识别", level=2)
            document.add_paragraph("需设计员编辑。")
            document.add_heading("产品需求分解（QFD质量功能分解）", level=2)
            document.add_paragraph("需设计员编辑。")
            document.add_heading("其他", level=2)
            document.save(path)

            postprocess(path)
            rendered = Document(path)

        paragraphs = [paragraph.text for paragraph in rendered.paragraphs]
        self.assertIn("产品运行场景识别【人工填写】", paragraphs)
        self.assertIn("产品需求分解（QFD质量功能分解）【人工填写】", paragraphs)
        self.assertEqual(2, paragraphs.count("需设计员编辑。"))

    def test_manual_annotation_section_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "taskbook.docx"
            document = Document()
            document.add_heading("初步的失效模式分析", level=1)
            document.add_heading("相似失效问题规避【人工标注】", level=2)
            similar_body = document.add_paragraph()
            similar_body.add_run("保留的非斜体正文")
            similar_body.add_run("【人工标注】")
            italic = similar_body.add_run("斜体模板说明")
            italic.italic = True
            similar_table = document.add_table(rows=2, cols=1)
            similar_table.cell(1, 0).paragraphs[0].add_run("表格斜体说明").italic = True

            document.add_heading("潜在失效模式初步分析", level=2)
            document.add_paragraph("请设计人员填写下表。")
            potential_table = document.add_table(rows=3, cols=5)
            for cell, text in zip(
                potential_table.rows[0].cells,
                ["序号", "可能发生的失效模式", "失效模式机理", "失效模式后果/影响", "可考虑的解决办法"],
            ):
                cell.text = text
            for row, values in zip(
                potential_table.rows[1:],
                (("1", "模板填写说明", "模板机理说明", "模板影响说明", "模板措施说明"), ("2", "模板原有内容", "", "", "")),
            ):
                for cell, text in zip(row.cells, values):
                    cell.text = text

            document.add_heading(
                "研制经费预算：【请人工标注】(适用于非中央研究院产品)",
                level=1,
            )
            document.add_paragraph().add_run("非中央研究院说明").italic = True
            document.add_heading(
                "研制经费预算及经济性分析：【人工标注】(适用于中央研究院产品)",
                level=1,
            )
            document.add_paragraph().add_run("中央研究院说明").italic = True
            document.save(path)

            stats = postprocess(path)
            postprocess(path)
            rendered = Document(path)

        similar_heading = next(p for p in rendered.paragraphs if "相似失效问题规避" in p.text)
        similar_body_rendered = next(p for p in rendered.paragraphs if "保留的非斜体正文" in p.text)
        potential_heading = next(p for p in rendered.paragraphs if "潜在失效模式初步分析" in p.text)
        scope_headings = [
            p
            for p in rendered.paragraphs
            if "适用于非中央研究院产品" in p.text or "适用于中央研究院产品" in p.text
        ]
        self.assertNotIn("人工标注", similar_heading.text)
        self.assertTrue(any(run.italic and run.text == "斜体模板说明" for run in similar_body_rendered.runs))
        self.assertEqual(1, potential_heading.text.count("【人工填写】"))
        self.assertTrue(
            next(run for run in potential_heading.runs if run.text == "【人工填写】").bold
        )
        self.assertTrue(all(heading.text.count("【人工填写】") == 1 for heading in scope_headings))
        self.assertIn("表格斜体说明", rendered.tables[0].cell(1, 0).text)
        self.assertEqual("模板填写说明", rendered.tables[1].cell(1, 1).text)
        self.assertEqual("模板原有内容", rendered.tables[1].cell(2, 1).text)
        self.assertEqual(0, stats.get("similar_failure_italic_runs_removed", 0))
        self.assertEqual(0, stats.get("potential_failure_analysis_cells_cleared", 0))

    def test_postprocess_normalizes_only_chapter_prose_to_song_five_point(self) -> None:
        def set_run_font(run, name: str, size: float) -> None:
            run.font.name = name
            run.font.size = Pt(size)
            fonts = run._r.get_or_add_rPr().get_or_add_rFonts()
            fonts.set(qn("w:eastAsia"), name)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "taskbook.docx"
            document = Document()

            cover_run = document.add_paragraph().add_run("封面标题")
            set_run_font(cover_run, "黑体", 26)

            heading = document.add_heading("第一章 总体要求", level=1)
            set_run_font(heading.runs[0], "黑体", 16)

            body_run = document.add_paragraph().add_run("这是从来源文件搬运的正文。")
            set_run_font(body_run, "仿宋_GB2312", 12)

            caption_run = document.add_paragraph().add_run("图1 示例图")
            set_run_font(caption_run, "黑体", 12)

            table = document.add_table(rows=1, cols=1)
            table_run = table.cell(0, 0).paragraphs[0].add_run("表格专用文字")
            set_run_font(table_run, "仿宋_GB2312", 9)
            document.save(path)

            postprocess(path)
            rendered = Document(path)

        rendered_cover = next(p for p in rendered.paragraphs if p.text == "封面标题")
        rendered_heading = next(p for p in rendered.paragraphs if p.text.startswith("第一章"))
        rendered_body = next(p for p in rendered.paragraphs if "来源文件搬运" in p.text)
        rendered_caption = next(p for p in rendered.paragraphs if p.text == "图1 示例图")
        rendered_table_run = rendered.tables[0].cell(0, 0).paragraphs[0].runs[-1]

        self.assertAlmostEqual(26.0, rendered_cover.runs[0].font.size.pt)
        self.assertEqual("黑体", rendered_cover.runs[0]._r.rPr.rFonts.get(qn("w:eastAsia")))
        self.assertAlmostEqual(16.0, rendered_heading.runs[0].font.size.pt)
        self.assertEqual("黑体", rendered_heading.runs[0]._r.rPr.rFonts.get(qn("w:eastAsia")))
        self.assertAlmostEqual(10.5, rendered_body.runs[0].font.size.pt)
        self.assertEqual("宋体", rendered_body.runs[0].font.name)
        self.assertEqual("宋体", rendered_body.runs[0]._r.rPr.rFonts.get(qn("w:eastAsia")))
        self.assertAlmostEqual(12.0, rendered_caption.runs[0].font.size.pt)
        self.assertEqual("黑体", rendered_caption.runs[0]._r.rPr.rFonts.get(qn("w:eastAsia")))
        self.assertAlmostEqual(10.5, rendered_table_run.font.size.pt)
        self.assertEqual("仿宋", rendered_table_run._r.rPr.rFonts.get(qn("w:eastAsia")))

    def test_italic_annotation_is_once_per_nearest_chapter_heading(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "taskbook.docx"
            document = Document()
            document.add_heading("总体要求", level=1)
            first = document.add_paragraph()
            first.add_run("【人工标注】")
            first.add_run("斜体第一段").italic = True
            document.add_paragraph().add_run("【请人工标注】斜体第二段").italic = True
            document.add_heading("详细要求", level=2)
            third = document.add_paragraph()
            third.add_run("【人工标注】")
            third.add_run("斜体第三段").italic = True
            document.add_paragraph().add_run("斜体第四段").italic = True
            table_paragraph = document.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0]
            table_paragraph.add_run("【人工标注】")
            table_paragraph.add_run("表格斜体内容").italic = True
            document.add_heading("模板已有标记【人工标注】", level=2)
            document.add_paragraph().add_run("斜体第五段").italic = True
            document.add_paragraph().add_run("斜体第六段").italic = True
            document.add_heading("普通章节", level=1)
            document.add_paragraph("普通正文")
            document.save(path)

            stats = postprocess(path)
            postprocess(path)  # 再次处理也不得重复标注或把标记变黑。
            rendered = Document(path)

        overall = next(p for p in rendered.paragraphs if p.text.startswith("总体要求"))
        detail = next(p for p in rendered.paragraphs if p.text.startswith("详细要求"))
        existing = next(p for p in rendered.paragraphs if p.text.startswith("模板已有标记"))
        normal = next(p for p in rendered.paragraphs if p.text == "普通章节")
        body_paragraphs = [p for p in rendered.paragraphs if p.text.startswith("斜体第")]

        # 多个未填写子项属于同一“总体要求”标题子树，只在父标题提示一次。
        self.assertEqual(1, overall.text.count("【人工填写】"))
        self.assertEqual(0, detail.text.count("【人工填写】"))
        self.assertEqual(0, existing.text.count("【人工填写】"))
        self.assertNotIn("人工标注", existing.text)
        self.assertNotIn("人工标注", normal.text)
        self.assertTrue(all("人工标注" not in paragraph.text for paragraph in body_paragraphs))
        self.assertTrue(all(paragraph.runs[0].italic for paragraph in body_paragraphs))
        rendered_table_paragraph = rendered.tables[0].cell(0, 0).paragraphs[0]
        self.assertNotIn("人工标注", rendered_table_paragraph.text)
        self.assertEqual(1, rendered_table_paragraph.text.count("【人工填写】"))
        self.assertTrue(any(run.text == "表格斜体内容" and run.italic for run in rendered_table_paragraph.runs))
        self.assertEqual(1, stats["italic_annotation_chapters"])
        self.assertEqual(1, stats["italic_annotations_added"])
        self.assertEqual(3, stats["italic_annotations_relocated"])
        self.assertEqual(2, stats["italic_annotations_collapsed"])

        marker_run = next(run for run in overall.runs if run.text == "【人工填写】")
        self.assertTrue(marker_run.bold)
        self.assertEqual("FF0000", str(marker_run.font.color.rgb))
        table_marker_run = next(
            run for run in rendered_table_paragraph.runs if run.text == "【人工填写】"
        )
        self.assertTrue(table_marker_run.bold)
        self.assertEqual("FF0000", str(table_marker_run.font.color.rgb))

    def test_short_prose_cannot_consume_acceptance_table_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.docx"
            output_path = Path(temp_dir) / "output.docx"

            source = Document()
            source.add_heading("5.7 其余技术要求", level=2)
            source.add_paragraph("无。")
            source.add_heading("6.1 验收要求", level=2)
            source_table = source.add_table(rows=1, cols=3)
            for cell, text in zip(source_table.rows[0].cells, ["项目", "技术要求", "抽样方案"]):
                cell.text = text
            for values in (
                ("外观和机械检查", "连接器标记正确、清晰，外观无磕碰伤。", "100%"),
                ("绝缘电阻（常温）", "应符合绝缘电阻要求", "100%"),
            ):
                row = source_table.add_row()
                for cell, text in zip(row.cells, values):
                    cell.text = text
            source.save(source_path)

            output = Document()
            output_table = output.add_table(rows=1, cols=3)
            for cell, text in zip(output_table.rows[0].cells, ["项目", "技术要求", "抽样方案"]):
                cell.text = text
            for values in (
                ("外观和机械检查", "连接器标记正确、清晰，外观无磕碰伤。", "100%"),
                ("绝缘电阻（常温）", "应符合绝缘电阻要求", "100%"),
            ):
                row = output_table.add_row()
                for cell, text in zip(row.cells, values):
                    cell.text = text
            output.add_paragraph("无。")
            output.save(output_path)

            ledger = parse_docx_to_ledger(str(source_path))
            mark_covered_from_output(ledger, str(output_path))

        short_prose = next(block for block in ledger.blocks if block.raw_text == "无。")
        acceptance_table = next(block for block in ledger.blocks if block.block_type == "table")
        self.assertTrue(short_prose.covered)
        self.assertTrue(acceptance_table.covered)


if __name__ == "__main__":
    unittest.main()
