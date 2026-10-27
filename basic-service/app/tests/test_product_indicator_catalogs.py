import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from docx import Document
from jonhon_taskbook.business_value_gate import audit_indicator_values
from jonhon_taskbook.extractor import parse_doc
from jonhon_taskbook.fill import (
    _fill_indicator_table,
    _runtime_indicator_map,
    build_content,
)
from jonhon_taskbook.indicator_catalog_loader import load_reference_indicator_catalog

ROOT = Path(__file__).resolve().parents[1] / "src" / "service"


def classified_requirement(title: str, text: str) -> dict:
    return {
        "source_blocks": [
            {"id": "requirement", "heading_text": title, "section": title, "text": text}
        ],
        "classifications": [
            {"source_id": "requirement", "category": "performance_indicator"}
        ],
    }


class ProductIndicatorCatalogTests(unittest.TestCase):
    def test_specialized_profiles_distinguish_mechanical_and_thermal_shock(self) -> None:
        profile_ids = (
            "rf_contact", "rf_hybrid", "rf_standard_interface", "filter_connector",
            "cable_assembly", "liquid_cooling_pipeline", "liquid_cooling_chassis",
        )
        measurements = {"冲击": "冲击：20 g，11 ms。", "温度冲击": "温度冲击：循环 100 次。"}
        display_values = {"冲击": "20 g，11 ms。", "温度冲击": "循环 100 次。"}
        for profile_id in profile_ids:
            profile = yaml.safe_load(
                (ROOT / "jonhon_taskbook" / f"{profile_id}_profile.yaml").read_text(encoding="utf-8")
            )
            for selected in (("冲击",), ("温度冲击",), ("冲击", "温度冲击")):
                for metric_headings in (False, True):
                    with self.subTest(profile=profile_id, metrics=selected, headings=metric_headings):
                        tech = Document()
                        blocks = []
                        for name in selected:
                            heading = name if metric_headings else "技术指标"
                            tech.add_heading(heading, level=1)
                            tech.add_paragraph(measurements[name])
                            blocks.append({
                                "id": name, "heading_text": heading,
                                "section": heading, "text": measurements[name],
                            })
                        classification = {
                            "source_blocks": blocks,
                            "classifications": [
                                {"source_id": name, "category": "performance_indicator"}
                                for name in selected
                            ],
                        }
                        content = build_content(
                            profile, tech, None, parse_doc(tech), [], "",
                            requirement_classification=classification,
                        )["role:performance_indicator"]
                        rows = {
                            row[0]: row[1] for row in content["indicator_rows"]
                            if not row[0].startswith("【")
                        }
                        self.assertEqual({name: display_values[name] for name in selected}, rows)
                        self.assertEqual(
                            {name: measurements[name] for name in selected},
                            {fact["indicator_name"]: fact["source_value"]
                             for fact in content["input_indicator_facts"]},
                        )

    def test_product_weight_prose_retains_its_source_value(self) -> None:
        profile = yaml.safe_load(
            (ROOT / "jonhon_taskbook" / "low_frequency_circular_profile.yaml").read_text(encoding="utf-8")
        )
        text = "产品重量不大于 50 g。"
        tech = Document()
        tech.add_heading("技术指标", level=1)
        tech.add_paragraph(text)
        content = build_content(
            profile, tech, None, parse_doc(tech), [], "",
            requirement_classification=classified_requirement("技术指标", text),
        )["role:performance_indicator"]
        rows = {row[0]: row[1] for row in content["indicator_rows"] if not row[0].startswith("【")}
        self.assertEqual({"重量": text}, rows)

    def test_workbook_selection_is_independent_of_reference_families(self) -> None:
        classification = classified_requirement("爆破压力", "爆破压力不低于 3 MPa。")
        vocabulary = {"流体性能": [{"name": "爆破压力"}]}
        with patch("jonhon_taskbook.fill.taxonomy_indicator_map", return_value=vocabulary):
            for enabled in (False, True):
                with self.subTest(workbook=enabled):
                    profile = {
                        "indicator_sources": {"workbook": enabled, "reference_families": []},
                        "indicator_map": {},
                    }
                    actual = _runtime_indicator_map(profile, [], classification)
                    names = {item["name"] for items in actual.values() for item in items}
                    self.assertEqual({"爆破压力"} if enabled else set(), names)

    def test_hydraulic_pressure_uses_only_the_product_vocabulary(self) -> None:
        profile = {
            "indicator_sources": {"workbook": False, "reference_families": []},
            "indicator_map": {
                "流体性能": [{"name": "耐压", "tech_kws": ["耐压"], "std_kws": ["耐压"]}]
            },
        }
        classification = classified_requirement("耐压", "承受 2 MPa 压力，无泄漏。")

        actual = _runtime_indicator_map(profile, [], classification)

        self.assertEqual(profile["indicator_map"], actual)
        self.assertNotIn("电性能", actual)
        self.assertNotIn("介质耐电压", {item["name"] for items in actual.values() for item in items})

    def test_disabled_sources_do_not_add_even_a_matching_unconfigured_indicator(self) -> None:
        profile = {
            "indicator_sources": {"workbook": False, "reference_families": []},
            "indicator_map": {},
        }
        classification = classified_requirement("耐压", "液压耐压 2 MPa；重量不超过 50 g。")

        self.assertEqual({}, _runtime_indicator_map(profile, [], classification))

    def test_a_longer_pressure_metric_does_not_activate_an_electrical_alias(self) -> None:
        profile = {
            "indicator_sources": {"workbook": False, "reference_families": ["common"]},
            "semantic_structures": {"performance_indicator": {"mode": "indicator_table"}},
            "indicator_map": {
                "电性能": [{"name": "介质耐电压", "tech_kws": ["介质耐电压", "耐电压", "耐压"]}]
            },
        }
        tech = Document()
        tech.add_paragraph("耐压深度：100 m。")
        classification = classified_requirement("技术指标", "耐压深度：100 m。")

        content = build_content(
            profile, tech, None, parse_doc(tech), [], "", requirement_classification=classification
        )

        rows = content["role:performance_indicator"]["indicator_rows"]
        actual = [row for row in rows if not row[0].startswith("【")]
        self.assertEqual(["耐压深度"], [row[0] for row in actual])
        self.assertNotIn("介质耐电压", [row[0] for row in actual])
        self.assertEqual("【人工填写】", actual[0][3])

    def test_thermal_template_keeps_ambient_working_and_medium_temperatures_separate(self) -> None:
        measurements = {
            "环境温度": "-40～85 ℃",
            "工作温度": "-20～60 ℃",
            "工作介质温度": "5～40 ℃",
        }
        profile = {
            "indicator_sources": {"workbook": False, "reference_families": []},
            "semantic_structures": {"performance_indicator": {"mode": "indicator_table"}},
            "indicator_map": {
                "热性能": [{"name": name, "tech_kws": [name]} for name in measurements]
            },
        }
        blocks = [
            {"id": name, "heading_text": name, "text": value}
            for name, value in measurements.items()
        ]
        classification = {
            "source_blocks": blocks,
            "classifications": [
                {"source_id": block["id"], "category": "performance_indicator"}
                for block in blocks
            ],
        }
        tech = Document()
        for name, value in measurements.items():
            tech.add_heading(name, level=1)
            tech.add_paragraph(value)
        content = build_content(
            profile, tech, None, parse_doc(tech), [], "", requirement_classification=classification
        )["role:performance_indicator"]

        output = Document()
        table = output.add_table(rows=1, cols=5)
        for cell, heading in zip(table.rows[0].cells, ["项目", "用户要求", "标准要求", "拟采用", "依据"]):
            cell.text = heading
        for name in measurements:
            table.add_row().cells[0].text = name

        self.assertEqual(3, _fill_indicator_table(output, content["indicator_rows"]))
        self.assertEqual(4, len(table.rows))
        self.assertEqual(
            measurements,
            {row.cells[0].text: row.cells[1].text for row in table.rows[1:]},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thermal.docx"
            output.save(path)
            path.with_suffix(".indicator_audit.json").write_text(
                json.dumps({"comparison_decisions": content["indicator_comparison_audit"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            result = audit_indicator_values(path, persist=False)
            self.assertTrue(result["passed"], result)

    def test_identically_named_rf_and_optical_metrics_keep_the_selected_category(self) -> None:
        classification = classified_requirement("插入损耗", "插入损耗不超过 0.5 dB。")
        for family, category in (("high_frequency", "高频性能"), ("optical", "光性能")):
            with self.subTest(family=family):
                profile = {
                    "indicator_sources": {"workbook": False, "reference_families": [family]},
                    "indicator_map": {},
                }

                actual = _runtime_indicator_map(profile, [], classification)

                self.assertEqual([category], list(actual))
                self.assertEqual(["插入损耗"], [item["name"] for item in actual[category]])
                self.assertEqual(family, actual[category][0]["catalog_family"])

    def test_family_selection_still_requires_classified_performance_evidence(self) -> None:
        classification = classified_requirement("引用标准", "插入损耗试验标准。")
        classification["classifications"][0]["category"] = "standards_reference"
        profile = {
            "indicator_sources": {"workbook": False, "reference_families": ["high_frequency"]},
            "indicator_map": {},
        }

        self.assertEqual({}, _runtime_indicator_map(profile, [], classification))

    def test_unknown_family_fails_even_without_performance_evidence(self) -> None:
        profile = {
            "indicator_sources": {"workbook": False, "reference_families": ["missing_family"]},
            "indicator_map": {},
        }

        with self.assertRaisesRegex(ValueError, "未知.*missing_family"):
            _runtime_indicator_map(profile, [], {"source_blocks": [], "classifications": []})

    def test_family_declared_in_the_resource_can_be_selected_without_code_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.yaml"
            path.write_text(
                yaml.safe_dump({
                    "fluid": {
                        "流体性能": [{"name": "爆破压力", "target_role": "performance_indicator.fluid"}]
                    }
                }, allow_unicode=True),
                encoding="utf-8",
            )

            entries = load_reference_indicator_catalog(path, families=["fluid"])

            self.assertEqual(["爆破压力"], [entry["name"] for entry in entries])
            self.assertEqual("流体性能", entries[0]["category"])
            self.assertEqual("fluid", entries[0]["catalog_family"])

    def test_existing_profiles_retain_the_default_vocabulary(self) -> None:
        classification = classified_requirement(
            "技术指标", "重量不超过 50 g；频率范围 1～3 GHz；端面质量满足输入要求。"
        )
        for filename in ("connector_profile.yaml", "end_contact_spring_pin_profile.yaml"):
            with self.subTest(profile=filename):
                profile = yaml.safe_load((ROOT / "jonhon_taskbook" / filename).read_text(encoding="utf-8"))
                explicit_legacy = {
                    **profile,
                    "indicator_sources": {
                        "workbook": True,
                        "reference_families": ["common", "high_frequency", "optical"],
                    },
                }

                actual = _runtime_indicator_map(profile, [], classification)

                self.assertEqual(_runtime_indicator_map(explicit_legacy, [], classification), actual)
                by_name = {item["name"]: category for category, items in actual.items() for item in items}
                self.assertIn("重量", by_name)
                self.assertIn("频率范围", by_name)
                self.assertIn("端面质量", by_name)

    def test_invalid_source_config_does_not_fall_back_to_defaults(self) -> None:
        for sources in (None, {"workbook": "false"}, {"reference_families": None},
                        {"reference_families": "optical"}, {"reference_families": [""]}):
            with self.subTest(sources=sources), self.assertRaises((TypeError, ValueError)):
                _runtime_indicator_map({"indicator_sources": sources}, [], {})
