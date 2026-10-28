from __future__ import annotations
from tests.support.paths import APP_ROOT

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
    _runtime_indicator_map,
)
from jonhon_taskbook.requirement_classifier import (
    _apply_configured_heading_constraints,
    _partition_mixed_blocks_with_llm,
    load_category_mapping,
)
from jonhon_taskbook.semantic_orchestrator import _configured_category_slots
from jonhon_taskbook.spec_extractor import extract_spec_chapter3_tables
from jonhon_taskbook.template_scanner import scan_template_tree


ROOT = APP_ROOT / "src" / "service"


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

    def test_installation_usage_notes_remain_one_atomic_other_module(self) -> None:
        mapping_path = ROOT / "config" / "connector_requirement_categories.yaml"
        mapping = load_category_mapping(str(mapping_path))
        categories = mapping["categories"]
        chapter = {
            "id": "installation_notes",
            "heading_text": "安装使用注意事项",
            "parent_headings": ["技术要求"],
        }
        resolved = _apply_configured_heading_constraints(
            [chapter],
            {
                "installation_notes": {
                    "source_id": "installation_notes",
                    "category": "safety",
                    "confidence": 0.88,
                    "method": "llm",
                    "reason": "mixed safety and installation semantics",
                }
            },
            categories,
        )
        self.assertEqual("other", resolved["installation_notes"]["category"])

        text = (
            "2）使用期间，应保持连接器插头与连接器插座合面清洁、无油污，"
            "每次连接前，应确认无凝露及污物后方可连接。"
        )
        blocks = [
            {
                "id": "installation-note-2",
                "chapter_id": "installation_notes",
                "type": "paragraph",
                "heading_text": "安装使用注意事项",
                "section": "安装使用注意事项：",
                "text": text,
                "has_drawing": False,
            }
        ]
        assignments = [
            {
                "source_id": "installation-note-2",
                "chapter_id": "installation_notes",
                "category": "other",
                "confidence": 0.95,
                "method": "llm+configured_heading_constraint",
                "reason": "controlled source heading",
            }
        ]

        def unexpected_llm_call(_system: str, _user: str) -> dict:
            self.fail("atomic installation notes must not invoke fragment routing")

        routed_blocks, routed_assignments, audit = _partition_mixed_blocks_with_llm(
            blocks,
            assignments,
            categories,
            mapping["exact_fragment_routing"],
            unexpected_llm_call,
        )

        self.assertEqual(text, routed_blocks[0]["text"])
        self.assertEqual("other", routed_assignments[0]["category"])
        self.assertEqual([], audit)

    def test_material_and_batch_quantity_modules_are_atomic_other_requirements(self) -> None:
        mapping_path = ROOT / "config" / "connector_requirement_categories.yaml"
        mapping = load_category_mapping(str(mapping_path))
        categories = mapping["categories"]
        cases = (
            (
                "material_selection",
                "元器件和原材料选用要求",
                "元器件和原材料应优先选用成熟、稳定且满足受控标准的产品。",
                "process_requirement",
            ),
            (
                "development_batch_quantity",
                "研制批产品数量要求",
                "研制批产品数量为3套，按任务书约定完成交付。",
                "schedule",
            ),
        )
        chapters = [
            {"id": source_id, "heading_text": heading, "parent_headings": ["技术要求"]}
            for source_id, heading, _text, _wrong_category in cases
        ]
        initial = {
            source_id: {
                "source_id": source_id,
                "category": wrong_category,
                "confidence": 0.92,
                "method": "llm",
                "reason": "plausible but rule-inconsistent semantic guess",
            }
            for source_id, _heading, _text, wrong_category in cases
        }
        resolved = _apply_configured_heading_constraints(chapters, initial, categories)
        for source_id, _heading, _text, _wrong_category in cases:
            self.assertEqual("other", resolved[source_id]["category"])

        slots = scan_template_tree(
            str(
                ROOT
                / "jonhon_taskbook"
                / "resources"
                / "templates"
                / "connector_taskbook.docx"
            )
        )
        resolved_slots = _configured_category_slots(slots, str(mapping_path))
        other_slot = next(slot for slot in slots if slot["id"] == resolved_slots["other"])
        self.assertEqual("其他要求", other_slot["title"])
        self.assertEqual("顾客的特殊要求 / 其他要求", other_slot["semantic_path"])

        blocks = [
            {
                "id": source_id,
                "chapter_id": source_id,
                "type": "paragraph",
                "heading_text": heading,
                "section": heading,
                "text": text,
                "has_drawing": False,
            }
            for source_id, heading, text, _wrong_category in cases
        ]
        assignments = [resolved[source_id] for source_id, *_rest in cases]

        def unexpected_llm_call(_system: str, _user: str) -> dict:
            self.fail("7-22 atomic other modules must not invoke fragment routing")

        routed_blocks, routed_assignments, audit = _partition_mixed_blocks_with_llm(
            blocks,
            assignments,
            categories,
            mapping["exact_fragment_routing"],
            unexpected_llm_call,
        )

        self.assertEqual(
            [case[2] for case in cases],
            [block["text"] for block in routed_blocks],
        )
        self.assertTrue(all(item["category"] == "other" for item in routed_assignments))
        self.assertEqual([], audit)

    def test_weight_is_routed_to_the_other_indicator_subtable(self) -> None:
        profile = yaml.safe_load(
            (ROOT / "jonhon_taskbook" / "connector_profile.yaml").read_text(
                encoding="utf-8"
            )
        )
        classification = {
            "source_blocks": [
                {
                    "id": "weight",
                    "heading_text": "重量",
                    "section": "重量",
                    "text": "产品重量不大于50 g。",
                }
            ],
            "classifications": [
                {"source_id": "weight", "category": "performance_indicator"}
            ],
        }
        indicator_map = _runtime_indicator_map(profile, [], classification)
        other_names = {item.get("name") for item in indicator_map.get("其他", [])}
        mechanical_names = {
            item.get("name") for item in indicator_map.get("机械性能", [])
        }
        self.assertIn("重量", other_names)
        self.assertNotIn("重量", mechanical_names)

        document = Document()
        table = document.add_table(rows=1, cols=5)
        for cell, text in zip(
            table.rows[0].cells, ["项目", "用户要求", "标准要求", "拟采用", "依据"]
        ):
            cell.text = text
        category = table.add_row()
        category.cells[0].merge(category.cells[-1]).text = "机械性能"
        item = table.add_row()
        item.cells[0].text = "插拔力"

        written = _fill_indicator_table(
            document,
            [
                ("【其他】", "", "", "", ""),
                ("重量", "≤50 g", "", "≤50 g", "技术要求"),
            ],
        )
        rows = [row.cells[0].text for row in table.rows]

        self.assertEqual(1, written)
        self.assertIn("其他", rows)
        self.assertIn("重量", rows)
        self.assertGreater(rows.index("重量"), rows.index("其他"))

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
