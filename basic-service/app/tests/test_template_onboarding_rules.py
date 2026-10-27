import json

import pytest
import yaml
from docx import Document
from jonhon_taskbook.fill import _runtime_indicator_map, fill
from jonhon_taskbook.product_router import load_profile
from jonhon_taskbook.requirement_classifier import build_requirement_classification
from jonhon_taskbook.template_onboarding import (
    prepare_template_candidate,
    validate_candidate_mapping,
)


@pytest.fixture
def candidate(tmp_path):
    taxonomy = {
        "categories": {
            "technical_support": {
                "label": "保障要求",
                "definition": "随产品提供的资料及备件",
                "source_heading_keywords": ["配套资料"],
                "source_content_patterns": ["随产品提供.*(?:说明书|合格证)"],
                "content_priority": 100,
                "write_mode": "dynamic_children",
                "empty_policy": "clear_body",
                "target_heading_keywords": ["旧保障章节"],
                "target_heading_level": 4,
                "target_parent_heading": "旧父章节",
            },
            "performance_indicator": {
                "label": "技术指标",
                "write_mode": "indicator_table",
            },
            "other": {
                "label": "其他要求",
                "source_content_patterns": ["随产品提供"],
                "content_priority": 1,
                "empty_policy": "fill_none",
                "target_parent_heading": "旧父章节",
            },
        },
    }
    taxonomy_path = tmp_path / "taxonomy.yaml"
    taxonomy_path.write_text(yaml.safe_dump(taxonomy, allow_unicode=True), encoding="utf-8")
    template_path = tmp_path / "customer.docx"
    template = Document()
    template.add_heading("供货约定", level=1)
    template.add_heading("配套保障资料", level=2)
    template.add_paragraph("模板保障占位正文")
    template.add_heading("验收性能清单", level=1)
    template.add_heading("附加约定", level=1)
    template.add_paragraph("模板附加要求占位正文")
    template.add_heading("研制经费预算（适用于非中央研究院产品）", level=1)
    template.add_heading("研制经费预算及经济性分析（适用于中央研究院产品）", level=1)
    template.add_heading("任务书编制依据", level=1)
    template.save(template_path)

    def map_live_slots(_system, user):
        payload = json.loads(user)
        titles = {
            "technical_support": "配套保障资料",
            "performance_indicator": "验收性能清单",
            "other": "附加约定",
        }
        by_title = {slot["title"]: slot["id"] for slot in payload["slots"]}
        return {
            "mappings": [
                {
                    "category": category,
                    "target_slot": by_title[title],
                    "confidence": 0.99,
                    "reason": "test mapping from supplied live titles",
                }
                for category, title in titles.items()
            ]
        }

    output = tmp_path / "candidate"
    report = prepare_template_candidate(
        str(template_path),
        str(output),
        product_type="candidate_product",
        product_label="候选产品",
        domain="military",
        domain_label="军品",
        version="v1",
        taxonomy_path=taxonomy_path,
        chat_json_fn=map_live_slots,
    )
    return report, output, taxonomy_path


def test_candidate_mapping_keeps_delivery_source_rules(candidate, tmp_path):
    report, output, taxonomy_path = candidate
    mapping_path = output / report["files"]["mapping"]
    validation = validate_candidate_mapping(
        str(output / report["files"]["template"]),
        str(mapping_path),
        taxonomy_path=taxonomy_path,
    )
    assert validation["passed"], validation["problems"]
    source_path = tmp_path / "delivery.docx"
    source = Document()
    source.add_heading("交付范围", level=1)
    source.add_paragraph("随产品提供使用说明书、合格证。")
    source.save(source_path)

    def classify_as_other(system, user):
        payload = json.loads(user)
        if payload["node"] == "source_structure":
            return {"headings": []}
        assert payload["node"] == "requirement_classification"
        assert "随产品提供的资料及备件" in system
        return {
            "classifications": [
                {
                    "source_id": block["source_id"],
                    "category": "other",
                    "confidence": 0.9,
                    "reason": "broad delivery chapter",
                }
                for block in payload["blocks"]
            ]
        }

    classification = build_requirement_classification(
        str(source_path), str(mapping_path), chat_json_fn=classify_as_other
    )
    assert classification["passed"]
    assert [item["category"] for item in classification["classifications"]] == [
        "technical_support"
    ]


def test_candidate_mapping_clear_body_is_consumed_by_fill(candidate, tmp_path):
    report, output, _ = candidate
    tech_path = tmp_path / "empty_tech.docx"
    spec_path = tmp_path / "empty_spec.docx"
    Document().save(tech_path)
    Document().save(spec_path)
    filled_path = tmp_path / "filled.docx"
    fill(
        str(tech_path),
        str(spec_path),
        str(output / report["files"]["template"]),
        str(filled_path),
        str(output / report["files"]["profile"]),
        category_mapping_path=str(output / report["files"]["mapping"]),
        requirement_classification={"source_blocks": [], "classifications": []},
        preserve_unfilled_template=True,
        finalize=False,
    )
    paragraphs = [paragraph.text for paragraph in Document(filled_path).paragraphs]
    assert "配套保障资料" in paragraphs
    assert "模板保障占位正文" not in paragraphs
    assert "模板附加要求占位正文" not in paragraphs
    assert "无。" in paragraphs


def test_candidate_profile_requires_explicit_indicator_configuration(candidate):
    report, output, _ = candidate
    profile, _, _ = load_profile(
        "", explicit_profile=str(output / report["files"]["profile"])
    )
    classification = {
        "source_blocks": [{
            "id": "performance",
            "heading_text": "技术指标",
            "text": "额定电流：17 A；产品重量：50 g；频率范围：1 GHz。",
        }],
        "classifications": [{
            "source_id": "performance", "category": "performance_indicator"
        }],
    }
    assert _runtime_indicator_map(profile, [], classification) == {}
    assert profile["delivery_gate"] == {
        "min_indicator_rows": 0,
        "min_interface_fills": 0,
        "required_headings": ["附加约定", "验收性能清单", "配套保障资料"],
    }
    assert profile["integration_status"] == "configured_pending_regression"
    catalog_patch = yaml.safe_load(
        (output / report["files"]["catalog_patch"]).read_text(encoding="utf-8")
    )
    assert not catalog_patch["product_types"]["candidate_product"]["enabled"]
    assert not report["publish_ready"]
