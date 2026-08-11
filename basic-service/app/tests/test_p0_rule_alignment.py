from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml
from docx import Document

from jonhon_taskbook.extractor import parse_doc
from jonhon_taskbook.fill import (
    _build_spec_table_ledger,
    _collect_standards,
    _fill_indicator_table,
    _match_spec_table_indicator,
)
from jonhon_taskbook.requirement_classifier import (
    _apply_configured_heading_constraints,
    load_category_mapping,
)
from jonhon_taskbook.semantic_orchestrator import _configured_category_slots
from jonhon_taskbook.spec_extractor import extract_spec_chapter3_tables
from jonhon_taskbook.template_scanner import scan_template_tree


ROOT = Path(__file__).resolve().parents[1] / "src" / "service"


class P0RuleAlignmentTests(unittest.TestCase):
    def test_template_standards_are_merged_and_deduplicated(self) -> None:
        tech = Document()
        tech.add_paragraph("GJB 1-2000 技术要求标准")
        spec = Document()
        spec.add_paragraph("GJB 2-2001 产品规范标准")
        template = Document()
        template.add_paragraph("GJB 1-2000 技术要求标准")
        template.add_paragraph("GJB 3-2002 模板标准")

        lines = _collect_standards(
            tech,
            spec,
            parse_doc(tech),
            parse_doc(spec),
            ["GJB"],
            template_doc=template,
            include_template=True,
        )

        self.assertEqual(1, sum(line.startswith("GJB 1-2000") for line in lines))
        self.assertTrue(any(line.startswith("GJB 3-2002") for line in lines))
        profile = yaml.safe_load(
            (ROOT / "jonhon_taskbook" / "connector_profile.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("merge_template", profile["standards_policy"])

    def test_acceptance_delivery_and_appearance_use_rule_targets(self) -> None:
        mapping_path = ROOT / "config" / "connector_requirement_categories.yaml"
        categories = load_category_mapping(str(mapping_path))["categories"]
        chapters = [
            {"id": "acceptance", "heading_text": "验收要求", "parent_headings": []},
            {"id": "delivery", "heading_text": "交付要求", "parent_headings": []},
            {"id": "appearance", "heading_text": "外观要求", "parent_headings": []},
        ]
        resolved = _apply_configured_heading_constraints(chapters, {}, categories)

        self.assertEqual("technical_support", resolved["acceptance"]["category"])
        self.assertEqual("technical_support", resolved["delivery"]["category"])
        self.assertEqual("appearance_requirement", resolved["appearance"]["category"])
        self.assertEqual(
            "条件保障要求",
            categories["technical_support"]["target_heading_keywords"][0],
        )
        self.assertEqual(
            "产品的功能用途",
            categories["appearance_requirement"]["target_parent_heading"],
        )
        slots = scan_template_tree(
            str(ROOT / "jonhon_taskbook" / "resources" / "templates" / "connector_taskbook.docx")
        )
        resolved_slots = _configured_category_slots(slots, str(mapping_path))
        slot_by_id = {slot["id"]: slot for slot in slots}
        self.assertEqual(
            "条件保障要求",
            slot_by_id[resolved_slots["technical_support"]]["title"],
        )
        self.assertEqual(
            "其他",
            slot_by_id[resolved_slots["appearance_requirement"]]["title"],
        )

    def test_scoped_specification_requires_an_exact_controlled_match(self) -> None:
        ledger = {
            "额定电流": [
                {
                    "name": "额定电流",
                    "value": "3 A",
                    "scope": "适用于J599A系列",
                    "section": "技术指标",
                    "caption": "表1",
                }
            ]
        }
        indicator = {"name": "额定电流", "std_kws": ["额定电流"]}

        matched = _match_spec_table_indicator(
            ledger, indicator, product_series="J599A"
        )
        unmatched = _match_spec_table_indicator(
            ledger, indicator, product_series="J599"
        )
        disabled = _match_spec_table_indicator(
            ledger, indicator, product_series="J599A", allow_scoped=False
        )

        self.assertEqual("scoped", matched["selection"])
        self.assertFalse(matched["inapplicable"])
        self.assertTrue(unmatched["inapplicable"])
        self.assertTrue(disabled["inapplicable"])

    def test_template_indicator_aliases_fill_existing_rows_without_cloning(self) -> None:
        document = Document()
        table = document.add_table(rows=1, cols=5)
        for cell, text in zip(
            table.rows[0].cells, ["项目", "用户要求", "标准要求", "拟采用", "依据"]
        ):
            cell.text = text

        mechanical = table.add_row()
        mechanical.cells[0].merge(mechanical.cells[-1]).text = "机械性能"
        total_force = table.add_row()
        total_force.cells[0].text = "总分离力或分离扭矩"

        environmental = table.add_row()
        environmental.cells[0].merge(environmental.cells[-1]).text = "环境性能"
        low_pressure = table.add_row()
        low_pressure.cells[0].text = "低温低气压"

        written = _fill_indicator_table(
            document,
            [
                ("【机械性能】", "", "", "", ""),
                ("总分离力", "20 N", "≤25 N", "20 N", "用户要求；产品规范"),
                ("【环境性能】", "", "", "", ""),
                ("低气压", "54 kPa", "54 kPa", "54 kPa", "用户要求；产品规范"),
            ],
        )

        self.assertEqual(2, written)
        self.assertEqual(5, len(table.rows))
        self.assertEqual("总分离力或分离扭矩", total_force.cells[0].text)
        self.assertEqual("20 N", total_force.cells[1].text)
        self.assertEqual("低温低气压", low_pressure.cells[0].text)
        self.assertEqual("54 kPa", low_pressure.cells[1].text)

    def test_spec_method_is_preserved_in_structured_standard_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "spec.docx"
            document = Document()
            document.add_heading("技术指标", level=1)
            table = document.add_table(rows=2, cols=4)
            for cell, text in zip(
                table.rows[0].cells, ["项目", "要求", "试验方法", "适用型号"]
            ):
                cell.text = text
            for cell, text in zip(
                table.rows[1].cells,
                ["接触电阻", "≤5 mΩ", "按GJB 1217试验", "J599A系列"],
            ):
                cell.text = text
            document.save(path)

            items = extract_spec_chapter3_tables(str(path))
            ledger = _build_spec_table_ledger(str(path))

        self.assertEqual(1, len(items))
        self.assertEqual("按GJB 1217试验", items[0].test_method)
        self.assertIn("试验方法：按GJB 1217试验", items[0].standard_text)
        self.assertEqual("J599A系列", items[0].applicable_model)
        self.assertEqual("≤5 mΩ", ledger["接触电阻"][0]["value"])
        self.assertIn("试验方法：按GJB 1217试验", ledger["接触电阻"][0]["display_value"])


if __name__ == "__main__":
    unittest.main()
