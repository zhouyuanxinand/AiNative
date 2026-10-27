import json
import tempfile
import unittest
from pathlib import Path

import yaml
from docx import Document

from jonhon_taskbook.business_value_gate import audit_indicator_values
from jonhon_taskbook.extractor import parse_doc
from jonhon_taskbook.fill import (
    _classified_indicator_evidence,
    _dynamic_unlisted_indicator_rows,
    _fill_indicator_table,
    build_content,
)
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks


ROOT = Path(__file__).resolve().parents[1] / "src" / "service"


class IndicatorTableRowIsolationTests(unittest.TestCase):
    def _classification(self, path: Path) -> tuple[dict, str]:
        blocks = extract_source_blocks(str(path), "tech")
        table_block = next(block for block in blocks if block.get("type") == "table")
        return (
            {
                "source_blocks": blocks,
                "classifications": [
                    {
                        "source_id": block["id"],
                        "chapter_id": block.get("chapter_id", ""),
                        "category": "performance_indicator",
                    }
                    for block in blocks
                ],
            },
            table_block["id"],
        )

    def test_each_indicator_uses_only_its_own_source_table_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "technical-requirement.docx"
            document = Document()
            document.add_heading("电气性能要求", level=1)
            table = document.add_table(rows=1, cols=3)
            for cell, text in zip(table.rows[0].cells, ["序号", "项目", "指标"]):
                cell.text = text
            source_rows = (
                ("1", "工作电压", "16#与Φ0.5规格接触件间60V DC；Φ0.5规格接触件间15V DC"),
                ("2", "工作电流", "16#接触件：15A；Φ0.5接触件：1A"),
                ("3", "绝缘电阻", "≥1000MΩ"),
                ("4", "接触电阻", "16#：<2.5mΩ；Φ0.5：<15mΩ"),
                ("5", "耐电压", "常温常压：500VAC；低气压（4.4kPa）：150V AC；5s"),
            )
            for source_row in source_rows:
                row = table.add_row()
                for cell, text in zip(row.cells, source_row):
                    cell.text = text

            # This paragraph contains “接触电阻”, but it belongs to a separate
            # mechanical-life requirement and must not be appended when the
            # exact electrical table row is available.
            document.add_heading("机械寿命", level=1)
            document.add_paragraph(
                "连接器应能承受100000次压缩和回弹，试验后接触电阻应满足规定。"
            )
            document.save(path)

            classification, table_source_id = self._classification(path)
            cases = {
                "工作电压": (["工作电压"], source_rows[0][2]),
                "工作电流": (["工作电流"], source_rows[1][2]),
                "绝缘电阻": (["绝缘电阻", "绝缘阻抗"], source_rows[2][2]),
                "接触电阻": (["接触电阻", "接触阻抗", "导通电阻"], source_rows[3][2]),
                "介质耐电压": (["介质耐电压", "耐电压", "耐压"], source_rows[4][2]),
            }
            all_names = set(cases)
            for name, (signals, expected) in cases.items():
                with self.subTest(name=name):
                    value, basis, source_ids = _classified_indicator_evidence(
                        classification,
                        signals,
                    )
                    self.assertEqual(expected, value)
                    self.assertEqual("电气性能要求", basis)
                    self.assertEqual([table_source_id], source_ids)
                    for other_name in all_names - {name}:
                        self.assertNotIn(other_name, value)
                    self.assertNotIn("100000次", value)

    def test_condition_word_in_value_does_not_create_an_indicator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "technical-requirement.docx"
            document = Document()
            document.add_heading("电气性能要求", level=1)
            table = document.add_table(rows=2, cols=2)
            table.rows[0].cells[0].text = "项目"
            table.rows[0].cells[1].text = "技术要求"
            table.rows[1].cells[0].text = "介质耐电压"
            table.rows[1].cells[1].text = "低气压（4.4kPa）时施加150V AC"
            document.save(path)

            classification, _table_source_id = self._classification(path)
            value, basis, source_ids = _classified_indicator_evidence(
                classification,
                ["低气压", "低气压试验"],
            )

            self.assertEqual("", value)
            self.assertEqual("", basis)
            self.assertEqual([], source_ids)

    def test_table_container_heading_is_not_reported_as_an_unlisted_indicator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "technical-requirement.docx"
            document = Document()
            document.add_heading("电气性能要求", level=1)
            table = document.add_table(rows=3, cols=3)
            for cell, text in zip(table.rows[0].cells, ["序号", "项目", "指标"]):
                cell.text = text
            for row, values in zip(
                table.rows[1:],
                [
                    ("1", "工作电流", "15A"),
                    ("2", "耐电压", "低气压时150V AC"),
                ],
            ):
                for cell, text in zip(row.cells, values):
                    cell.text = text
            document.save(path)

            classification, table_source_id = self._classification(path)
            classification["source_blocks"] = [
                block
                for block in classification["source_blocks"]
                if block["id"] == table_source_id
            ]
            classification["classifications"] = [
                item
                for item in classification["classifications"]
                if item["source_id"] == table_source_id
            ]
            existing_rows = [
                ("【电性能】", "", "", "", ""),
                ("工作电流", "15A", "", "15A", "用户要求"),
                ("介质耐电压", "低气压时150V AC", "", "低气压时150V AC", "用户要求"),
            ]

            rows, audit = _dynamic_unlisted_indicator_rows(
                classification,
                existing_rows,
                [],
                {},
                "产品规范",
            )

            self.assertEqual([], rows)
            self.assertEqual([], audit)

    def test_unknown_table_item_is_audited_by_row_name_not_container_heading(self) -> None:
        classification = {
            "source_blocks": [
                {
                    "id": "table-1",
                    "type": "table",
                    "chapter_id": "chapter-1",
                    "heading_text": "电气性能要求",
                    "text": "项目指标未知参数42foo",
                    "table_rows": [
                        ["项目", "指标"],
                        ["未知参数", "42foo"],
                    ],
                }
            ],
            "classifications": [
                {
                    "source_id": "table-1",
                    "chapter_id": "chapter-1",
                    "category": "performance_indicator",
                }
            ],
        }

        rows, audit = _dynamic_unlisted_indicator_rows(
            classification,
            [],
            [],
            {},
            "产品规范",
        )

        self.assertEqual("未知参数", rows[0][0])
        self.assertEqual("42foo", rows[0][1])
        # C51(3): with no specification to compare, preserve the explicit user
        # value. An unregistered name/unit does not justify discarding it.
        self.assertEqual("42foo", rows[0][3])
        self.assertFalse(audit[0]["manual_review_required"])
        self.assertEqual(1, len(audit))
        self.assertEqual("电性能", audit[0]["category"])
        self.assertEqual("未知参数", audit[0]["indicator_name"])
        self.assertNotEqual("电气性能要求", audit[0]["indicator_name"])

    def test_end_contact_profile_does_not_reapply_paragraph_patterns_to_table_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "technical-requirement.docx"
            document = Document()
            document.add_heading("电气性能要求", level=1)
            table = document.add_table(rows=1, cols=3)
            for cell, text in zip(table.rows[0].cells, ["序号", "项目", "指标"]):
                cell.text = text
            source_rows = (
                ("1", "绝缘电阻", "≥1000MΩ"),
                ("2", "接触电阻", "16#:<2.5mΩ Ф0.5：<15mΩ"),
                ("3", "耐电压", "常温常压：500VAC；低气压(4.4Kpa):150V AC  耐电压测试时间5S"),
            )
            for values in source_rows:
                row = table.add_row()
                for cell, text in zip(row.cells, values):
                    cell.text = text
            document.save(path)

            classification, _table_source_id = self._classification(path)
            profile = yaml.safe_load(
                (
                    ROOT
                    / "jonhon_taskbook"
                    / "end_contact_spring_pin_profile.yaml"
                ).read_text(encoding="utf-8")
            )
            technical_document = Document(path)
            content = build_content(
                profile,
                technical_document,
                None,
                parse_doc(technical_document),
                [],
                str(path),
                requirement_classification=classification,
                controlled_product_label="端面接触-弹针连接器",
                product_series="ICTS",
                controlled_product_domain="military",
            )
            rows = content["role:performance_indicator"]["indicator_rows"]
            row_by_name = {
                row[0]: row
                for row in rows
                if row and not str(row[0]).startswith("【")
            }

            self.assertEqual(source_rows[0][2], row_by_name["绝缘电阻"][1])
            self.assertEqual(source_rows[1][2], row_by_name["接触电阻"][1])
            self.assertEqual(source_rows[2][2], row_by_name["介质耐电压"][1])
            self.assertEqual(
                [],
                content["role:performance_indicator"]["dynamic_indicator_audit"],
            )

    def test_dielectric_voltage_fills_existing_short_name_template_row(self) -> None:
        document = Document()
        table = document.add_table(rows=1, cols=5)
        for cell, text in zip(
            table.rows[0].cells,
            ["项目", "用户要求", "标准要求", "拟采用", "依据"],
        ):
            cell.text = text
        category = table.add_row()
        category.cells[0].merge(category.cells[-1]).text = "电性能"
        dielectric = table.add_row()
        dielectric.cells[0].text = "耐电压"

        written = _fill_indicator_table(
            document,
            [
                ("【电性能】", "", "", "", ""),
                (
                    "介质耐电压",
                    "常温常压：500VAC",
                    "",
                    "常温常压：500VAC",
                    "用户要求",
                ),
            ],
        )

        self.assertEqual(1, written)
        self.assertEqual(3, len(table.rows))
        self.assertEqual("耐电压", dielectric.cells[0].text)
        self.assertEqual("常温常压：500VAC", dielectric.cells[1].text)

    def test_delivery_gate_treats_dielectric_voltage_alias_as_same_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            docx_path = Path(directory) / "taskbook.docx"
            audit_path = Path(directory) / "taskbook.indicator_audit.json"
            document = Document()
            table = document.add_table(rows=2, cols=5)
            for cell, text in zip(
                table.rows[0].cells,
                ["项目", "用户要求", "标准要求", "拟采用", "依据"],
            ):
                cell.text = text
            values = (
                "耐电压",
                "常温常压：500VAC；低气压(4.4Kpa):150V AC；耐电压测试时间5S",
                "",
                "常温常压：500VAC；低气压(4.4Kpa):150V AC；耐电压测试时间5S",
                "用户要求",
            )
            for cell, text in zip(table.rows[1].cells, values):
                cell.text = text
            document.save(docx_path)
            audit_path.write_text(
                json.dumps(
                    {
                        "comparison_decisions": [
                            {
                                "indicator_name": "介质耐电压",
                                "user_requirement": values[1],
                                "standard_requirement": values[2],
                                "adopted_requirement": values[3],
                                "basis": values[4],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = audit_indicator_values(
                docx_path,
                audit_path,
                persist=False,
            )

            self.assertTrue(result["passed"], result["blockers"])
            self.assertEqual([], result["blockers"])
            self.assertEqual(1, result["checked_decisions"])
            self.assertEqual(4, result["checked_fields"])


if __name__ == "__main__":
    unittest.main()
