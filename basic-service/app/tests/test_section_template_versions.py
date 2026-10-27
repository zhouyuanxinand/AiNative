"""Replacement validation for actual technical sections and container rules."""
from pathlib import Path

import pytest
import yaml
from docx import Document

from jonhon_taskbook.template_versions import validate_replacement


SERVICE = Path(__file__).resolve().parents[1] / "src/service"
TEMPLATES = SERVICE / "jonhon_taskbook/resources/templates"


@pytest.mark.parametrize("family,leaf", [
    ("printed_board_assembly", "insertion_loss"),
    ("system_integration", "insulation_resistance"),
])
def test_actual_section_template_validates_without_a_writable_parent_and_rejects_missing_leaf(tmp_path, family, leaf):
    template = TEMPLATES / f"{family}_taskbook.docx"
    mapping_path = SERVICE / "config" / f"{family}_requirement_categories.yaml"
    mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    performance = mapping["categories"]["performance_indicator"]
    assert performance["container_only"]
    assert not performance.get("target_heading_keywords")
    accepted = validate_replacement(template, mapping_path, template)
    assert accepted["passed"], accepted["problems"]
    assert leaf in {item["category"] for item in accepted["matches"]}
    assert "performance_indicator" not in {item["category"] for item in accepted["matches"]}

    document = Document(template)
    title = mapping["categories"][leaf]["target_heading_keywords"][0]
    paragraphs = [paragraph for paragraph in document.paragraphs if paragraph.text.strip() == title]
    assert len(paragraphs) == 1
    paragraph = paragraphs[0]
    paragraph._p.getparent().remove(paragraph._p)
    changed = tmp_path / "missing-leaf.docx"
    document.save(changed)
    rejected = validate_replacement(changed, mapping_path, template)
    assert not rejected["passed"]
    assert any(mapping["categories"][leaf]["label"] in message for message in rejected["problems"])


@pytest.mark.parametrize("targets", [[], ["not_configured"], ["performance_indicator"]])
def test_section_container_cannot_skip_or_point_at_nonwritable_technical_leaves(tmp_path, targets):
    template = TEMPLATES / "printed_board_assembly_taskbook.docx"
    mapping_path = SERVICE / "config/printed_board_assembly_requirement_categories.yaml"
    mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    mapping["categories"]["performance_indicator"]["block_target_categories"] = targets
    changed = tmp_path / "mapping.yaml"
    changed.write_text(yaml.safe_dump(mapping, allow_unicode=True), encoding="utf-8")
    rejected = validate_replacement(template, changed, template)
    assert not rejected["passed"]
    assert any("章节式技术要求" in message for message in rejected["problems"])
