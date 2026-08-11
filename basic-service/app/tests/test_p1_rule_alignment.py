from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docx import Document

from jonhon_taskbook.development_process_policy import (
    new_process_manual_section_rules,
)
from jonhon_taskbook.fill import (
    _fill_potential_failure_analysis_table,
    _replace_section_body_with_manual_note,
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

    def test_matched_failure_modes_seed_potential_analysis_column(self) -> None:
        document = Document()
        table = document.add_table(rows=1, cols=5)
        for cell, text in zip(
            table.rows[0].cells,
            ["序号", "可能发生的失效模式", "失效模式机理", "失效模式后果", "可考虑的解决办法"],
        ):
            cell.text = text
        table.add_row()

        written = _fill_potential_failure_analysis_table(
            document,
            [
                {"failure_mode": "弹针缩针"},
                {"failure_mode": "导销无法装入导销孔"},
            ],
        )

        self.assertEqual(2, written)
        self.assertEqual(3, len(table.rows))
        self.assertEqual("弹针缩针", table.rows[1].cells[1].text)
        self.assertEqual("导销无法装入导销孔", table.rows[2].cells[1].text)
        self.assertEqual("", table.rows[1].cells[2].text)

    def test_full_new_manual_sections_keep_clean_heading_and_note(self) -> None:
        document = Document()
        document.add_heading("产品运行场景识别", level=2)
        document.add_paragraph("模板说明与示例内容")
        document.add_heading(
            "产品需求分解（QFD质量功能分解）（利用EdrawMax编制）",
            level=2,
        )
        document.add_paragraph("模板质量屋示例")
        document.add_heading("其他", level=2)

        rules = {rule["id"]: rule for rule in new_process_manual_section_rules()}
        for rule in rules.values():
            _replace_section_body_with_manual_note(
                document,
                rule["semantic_titles"],
                rule["output_title"],
                rule["note"],
            )

        paragraphs = [paragraph.text for paragraph in document.paragraphs]
        self.assertIn("产品运行场景识别", paragraphs)
        self.assertIn("产品需求分解（QFD质量功能分解）", paragraphs)
        self.assertEqual(2, paragraphs.count("需设计员编辑。"))
        self.assertNotIn("模板说明与示例内容", paragraphs)
        self.assertNotIn("模板质量屋示例", paragraphs)

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
        self.assertIn("产品运行场景识别", paragraphs)
        self.assertIn("产品需求分解（QFD质量功能分解）", paragraphs)
        self.assertEqual(2, paragraphs.count("需设计员编辑。"))

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
