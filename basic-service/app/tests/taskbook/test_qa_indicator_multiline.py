"""Several source passages may form one governed indicator user requirement."""
from tests.support.paths import APP_ROOT

import json
from pathlib import Path

from docx import Document
from jonhon_taskbook.fill import fill
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks

SERVICE_ROOT = APP_ROOT / "src/service"
PROFILE = SERVICE_ROOT / "jonhon_taskbook/liquid_cooling_pipeline_profile.yaml"
TEMPLATE = SERVICE_ROOT / "jonhon_taskbook/resources/templates/liquid_cooling_pipeline_taskbook.docx"
MAPPING = SERVICE_ROOT / "config/liquid_cooling_pipeline_requirement_categories.yaml"


def test_multiline_indicator_user_requirement_is_backed_by_each_source_passage(tmp_path):
    tech_path = tmp_path / "tech.docx"
    spec_path = tmp_path / "spec.docx"
    output = tmp_path / "taskbook.docx"
    tech = Document()
    tech.add_heading("散热性能", level=1)
    for index, passage in enumerate((
        "温度测量点：",
        "400W×2、入液42℃的测试结果：",
        "热阻测试结果：",
    )):
        tech.add_paragraph(passage)
        if index == 0:
            measurements = tech.add_table(rows=1, cols=2)
            measurements.cell(0, 0).text = "测点"
            measurements.cell(0, 1).text = "历史样本值50.91℃"
    tech.save(tech_path)
    Document().save(spec_path)
    source_blocks = extract_source_blocks(str(tech_path), "tech")
    classification = {
        "source_blocks": source_blocks,
        "classifications": [
            {"source_id": block["id"], "category": "performance_indicator"}
            for block in source_blocks
        ],
    }

    fill(
        str(tech_path), str(spec_path), str(TEMPLATE), str(output), str(PROFILE),
        category_mapping_path=str(MAPPING), requirement_classification=classification,
        controlled_product_label="液冷产品-液冷管路", controlled_product_domain="military",
        product_series="SYNTHETIC", development_process="全新", finalize=False,
    )

    audit = json.loads(output.with_suffix(".indicator_audit.json").read_text(encoding="utf-8"))
    decision = next(item for item in audit["comparison_decisions"] if item["indicator_name"] == "散热性能")
    assert decision["user_requirement"] == "温度测量点：\n400W×2、入液42℃的测试结果：\n热阻测试结果："
    assert "散热性能" not in audit["unbacked_output_names"]
    assert decision["manual_review_required"] is True
    assert audit["passed"] is False
