from tests.support.paths import APP_ROOT
import json
from pathlib import Path

import pytest
from docx import Document
from jonhon_taskbook.fill import fill
from jonhon_taskbook.product_router import load_profile

from pipeline_cli import _run_delivery_gate_stage

SERVICE_ROOT = APP_ROOT / "src/service"
PROFILE_ROOT = SERVICE_ROOT / "jonhon_taskbook"


@pytest.mark.parametrize("development_process", ("改型I", "改型II", "改型III"))
def test_chassis_quality_section_removal_is_respected_by_delivery_gate(
    development_process, tmp_path
):
    profile_path = PROFILE_ROOT / "liquid_cooling_chassis_profile.yaml"
    profile, _, _ = load_profile("", explicit_profile=str(profile_path))
    template_path = PROFILE_ROOT / "resources/templates" / profile["template_source"]["file"]
    mapping_path = SERVICE_ROOT / "config" / profile["semantic_routing"]["category_mapping"]
    tech_path = tmp_path / "empty_tech.docx"
    spec_path = tmp_path / "empty_spec.docx"
    output_path = tmp_path / "chassis.docx"
    Document().save(tech_path)
    Document().save(spec_path)
    classification = {"source_blocks": [], "classifications": []}

    fill(
        str(tech_path),
        str(spec_path),
        str(template_path),
        str(output_path),
        str(profile_path),
        category_mapping_path=str(mapping_path),
        requirement_classification=classification,
        development_process=development_process,
        organization_scope="non_central_research",
        preserve_unfilled_template=True,
        finalize=False,
    )

    process_audit = json.loads(
        output_path.with_suffix(".process_rule_audit.json").read_text(encoding="utf-8")
    )
    assert "通用质量特性要求" in process_audit["deleted_semantic_headings"]
    assert not any(
        "通用质量特性要求" in paragraph.text
        for paragraph in Document(output_path).paragraphs
    )

    # 真实流水线阶段读取 fill 的删除审计，再将排除条件传入 run_delivery_gate。
    gate = _run_delivery_gate_stage(
        str(output_path),
        {
            "meta": {
                "template_path": str(template_path),
                "formal_output": False,
                "preserve_unfilled_template": True,
            }
        },
        profile,
        classification,
    )
    assert not any(
        "通用质量特性要求" in heading
        for heading in gate["scan"]["missing_headings"]
    )
    assert not any(
        defect["code"] == "MISSING_SECTION"
        and "通用质量特性要求" in defect["text"]
        for defect in gate["scan"]["defects"]
    )
