"""New controlled headings remain stable when display numbering changes."""
from pathlib import Path

import pytest
from docx import Document

from jonhon_taskbook.template_registry import resolve_template_selection
from jonhon_taskbook.template_scanner import scan_template_tree, semantic_title
from jonhon_taskbook.template_versions import validate_replacement


@pytest.mark.parametrize("heading, expected", [
    ("4.1.5.2信号要求", "信号要求"),
    ("9.2 信号要求", "信号要求"),
    ("3D端面", "3D端面"),
    ("2.5mm接口", "2.5mm接口"),
])
def test_attached_chapter_numbers_do_not_become_heading_identity(heading, expected):
    assert semantic_title(heading) == expected


def test_real_board_signal_slot_survives_display_renumbering(tmp_path):
    selected = resolve_template_selection("printed_board_assembly", "military")
    before = scan_template_tree(selected.template_path)
    signal_before = next(node for node in before if node["title"] == "信号要求")
    document = Document(selected.template_path)
    document.paragraphs[signal_before["paragraph_index"]].text = "9.7.1信号要求"
    changed = tmp_path / "renumbered.docx"
    document.save(changed)
    signal_after = next(node for node in scan_template_tree(str(changed)) if node["title"] == "信号要求")
    assert signal_before["id"] == signal_after["id"]
    validation = validate_replacement(changed, Path(selected.category_mapping_path), Path(selected.template_path))
    assert validation["passed"], validation["problems"]
