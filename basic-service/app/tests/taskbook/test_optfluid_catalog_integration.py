"""The two newly supplied templates work with existing version management."""
import io
import shutil
from pathlib import Path

import pytest
import yaml
from docx import Document

from jonhon_taskbook.template_registry import resolve_template_selection
from jonhon_taskbook.template_versions import TemplateVersions


PRODUCTS = ("optical_cable_assembly", "liquid_cooling_connector")


@pytest.mark.parametrize("product", PRODUCTS)
def test_supplied_templates_can_be_replaced_and_restored_without_changing_rules(tmp_path, product):
    templates, config = tmp_path / "templates", tmp_path / "config"
    templates.mkdir()
    config.mkdir()
    catalog = {"product_types": {}}
    for key in PRODUCTS:
        selection = resolve_template_selection(key, "military")
        template, mapping = Path(selection.template_path), Path(selection.category_mapping_path)
        shutil.copy2(template, templates / template.name)
        shutil.copy2(mapping, config / mapping.name)
        catalog["product_types"][key] = {
            "label": selection.product_type_label, "enabled": True, "domains": {"military": {
                "label": "军品", "template": template.name,
                "category_mapping": mapping.name, "profile": Path(selection.profile_path).name,
            }},
        }
    catalog_path = config / "template_catalog.yaml"
    catalog_path.write_text(yaml.safe_dump(catalog, allow_unicode=True), encoding="utf-8")
    manager = TemplateVersions(catalog_path, templates, config, tmp_path / "history")
    other = next(key for key in PRODUCTS if key != product)
    other_before = manager.current(other, "military")
    original, _ = manager.current_file(product, "military")
    original_bytes = original.read_bytes()
    rules_before = {path.name: path.read_bytes() for path in config.glob("*_requirement_categories.yaml")}

    modified = Document(original)
    modified.add_paragraph("受控模板动态修订示例，仅改变正文说明。")
    payload = io.BytesIO()
    modified.save(payload)
    staged = manager.stage(product, "military", "更新后的受控模板.docx", payload.getvalue(), version="新版")
    candidate = staged["version"]
    assert candidate["status"] == "ready", candidate["validation"]["problems"]
    assert manager.current_file(product, "military")[0].read_bytes() == original_bytes
    activated = manager.activate(candidate["id"], expected_revision=candidate["base_revision"])
    assert activated["current"]["version_id"] == candidate["id"]
    assert manager.current_file(product, "military")[0].read_bytes() == payload.getvalue()
    assert manager.current(other, "military") == other_before

    original_version = next(version for version in activated["versions"] if version["id"] != candidate["id"])
    restarted = TemplateVersions(catalog_path, templates, config, tmp_path / "history")
    restarted.activate(original_version["id"], expected_revision=activated["current"]["revision"])
    assert restarted.current_file(product, "military")[0].read_bytes() == original_bytes
    after = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    binding = after["product_types"][product]["domains"]["military"]
    assert binding["profile"] == catalog["product_types"][product]["domains"]["military"]["profile"]
    assert {path.name: path.read_bytes() for path in config.glob("*_requirement_categories.yaml")} == rules_before
