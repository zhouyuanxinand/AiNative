from tests.support.paths import APP_ROOT
import json
from pathlib import Path

import pytest
from docx import Document
from jonhon_taskbook.fill import fill
from jonhon_taskbook.product_router import load_profile
from jonhon_taskbook.template_variant_policy import apply_template_variant_policy

SERVICE_ROOT = APP_ROOT / "src/service"
PROFILE_ROOT = SERVICE_ROOT / "jonhon_taskbook"
TEMPLATE_ROOT = PROFILE_ROOT / "resources/templates"
SINGLE_BUDGET_PRODUCTS = (
    "filter_connector",
    "liquid_cooling_pipeline",
    "liquid_cooling_chassis",
)


@pytest.mark.parametrize("product_id", SINGLE_BUDGET_PRODUCTS)
@pytest.mark.parametrize("organization_scope", ("non_central_research", "central_research"))
def test_real_single_budget_template_scope(product_id, organization_scope, tmp_path):
    profile_path = PROFILE_ROOT / f"{product_id}_profile.yaml"
    profile, _, _ = load_profile("", explicit_profile=str(profile_path))
    template_path = TEMPLATE_ROOT / profile["template_source"]["file"]
    mapping_path = SERVICE_ROOT / "config" / profile["semantic_routing"]["category_mapping"]
    tech_path = tmp_path / "empty_tech.docx"
    spec_path = tmp_path / "empty_spec.docx"
    output_path = tmp_path / "candidate.docx"
    Document().save(tech_path)
    Document().save(spec_path)

    def fill_candidate():
        fill(
            str(tech_path),
            str(spec_path),
            str(template_path),
            str(output_path),
            str(profile_path),
            category_mapping_path=str(mapping_path),
            requirement_classification={"source_blocks": [], "classifications": []},
            organization_scope=organization_scope,
            preserve_unfilled_template=True,
            finalize=False,
        )

    if organization_scope == "central_research":
        with pytest.raises(ValueError, match="不支持产品归属范围 'central_research'"):
            fill_candidate()
        assert not output_path.exists()
        return

    fill_candidate()
    audit = json.loads(
        output_path.with_suffix(".template_variant_audit.json").read_text(encoding="utf-8")
    )
    assert audit["passed"]
    assert Path(audit["policy_path"]).name == "single_budget_template_variant_policy.yaml"
    assert all(not group["removed"] for group in audit["groups"])
    budget_headings = [
        paragraph.text.strip().rstrip("：:")
        for paragraph in Document(output_path).paragraphs
        if paragraph.style.name.startswith("Heading") and "研制经费预算" in paragraph.text
    ]
    assert budget_headings == ["研制经费预算"]


@pytest.mark.parametrize("organization_scope", ("non_central_research", "central_research"))
def test_default_two_budget_policy_retains_selected_branch(organization_scope, tmp_path):
    template = Document(TEMPLATE_ROOT / "connector_taskbook.docx")
    audit = apply_template_variant_policy(
        template,
        organization_scope=organization_scope,
        out_path=tmp_path / "existing_product.docx",
    )
    assert audit["passed"]
    assert Path(audit["policy_path"]).name == "template_variant_policy.yaml"
    assert all(set(group["matched_after"]) == {organization_scope} for group in audit["groups"])
    assert all(len(group["removed"]) == 1 for group in audit["groups"])
