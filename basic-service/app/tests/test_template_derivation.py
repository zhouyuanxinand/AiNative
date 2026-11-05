"""Synthetic fixtures exercise complete derivation without claiming qualification."""
from copy import deepcopy
import json

from docx import Document
import pytest
import yaml

from jonhon_taskbook.template_derivation import (
    prepare_derivation_candidate, digest, file_hash, full_manifest,
    core_asset_digest, record_regression_evidence,
)
from jonhon_taskbook.template_outline_editor import build_template_edit_plan
from jonhon_taskbook.asset_lifecycle import ControlledAssetLifecycle
from rd_platform.completion import evidence_blocks


@pytest.fixture
def derivation(tmp_path):
    baseline = tmp_path / "baseline.docx"
    doc = Document()
    doc.add_heading("技术指标", 1)
    doc.add_heading("其他要求", 1)
    doc.save(baseline)
    taxonomy = tmp_path / "taxonomy.yaml"
    taxonomy.write_text(yaml.safe_dump({"categories": {"performance_indicator": {"label": "技术指标"}, "other": {"label": "其他要求"}}}, allow_unicode=True), encoding="utf-8")
    source = tmp_path / "fixture_target.txt"
    source.write_text("指标：测试夹具频率 10GHz\n方法：测试夹具方法 A\n判据：测试夹具偏差 1dB\n", encoding="utf-8")
    target = {"product_type": "fixture_high_frequency", "product_label": "测试夹具高频产品",
              "domain": "military", "domain_label": "测试领域", "version": "v1"}
    applicability = {k: target[k] for k in ("product_type", "domain")}
    sources = [{"id": "fixture_source", "version": 1, "sha256": file_hash(source), "role": "tech",
                "path": str(source), "applicability": applicability}]
    blocks = evidence_blocks(sources, tmp_path)
    edit_plan = build_template_edit_plan(str(baseline), '在“技术指标”之后新增“目标测试方法”', allow_llm=False)
    profile = tmp_path / "target_profile.yaml"
    profile.write_text(yaml.safe_dump({"product_type": target["product_type"], "semantic_routing": {"copy_source_text_only": True},
                       "indicator_sources": {"workbook": False, "reference_families": []},
                       "professional_evidence_contract": {"indicators": {"labels": ["指标"]}, "methods": {"labels": ["方法"]}, "criteria": {"labels": ["判据"]}},
                       "indicator_map": {"测试指标": [{"name": "测试夹具频率", "tech_kws": ["测试夹具频率"]}]},
                       "delivery_gate": {"required_headings": ["技术指标", "目标测试方法"], "min_indicator_rows": 1},
                       "qa_profile": {"required_headings": ["技术指标"]}}, allow_unicode=True), encoding="utf-8")
    mapping = tmp_path / "target_mapping.yaml"
    mapping.write_text(yaml.safe_dump({"categories": {"performance_indicator": {"label": "技术指标", "target_heading_keywords": ["技术指标"], "target_heading_level": 1},
                                                    "other": {"label": "其他要求", "target_heading_keywords": ["其他要求"], "target_heading_level": 1}}}, allow_unicode=True), encoding="utf-8")
    rule = {"id": "fixture_rule", "version": 1, "status": "published", "approval": {"actor": "fixture_reviewer"},
            "publication": {"actor": "fixture_publisher"}, "asset_bindings": {"profile_sha256": file_hash(profile), "mapping_sha256": file_hash(mapping)},
            "applicability": applicability, "operations": edit_plan["operations"]}
    rule["digest"] = digest(rule)
    package = {"applicability": applicability, "edit_plan": edit_plan,
               "rule_refs": [{k: rule[k] for k in ("id", "version", "digest")}],
               "professional_evidence": {key: [{k: blocks[index][k] for k in ("source_id", "version", "sha256", "location", "quote")}]
                                         for index, key in enumerate(("indicators", "methods", "criteria"))}}
    def mapper(_, payload):
        slots = {s["title"]: s["id"] for s in json.loads(payload)["slots"]}
        return {"mappings": [{"category": key, "target_slot": slots[title], "confidence": .99, "reason": "synthetic fixture"}
                             for key, title in (("performance_indicator", "技术指标"), ("other", "其他要求"))]}
    return {"baseline": {"id": "fixture_baseline", "version": 1, "template": str(baseline), "sha256": file_hash(baseline)},
            "target": target, "difference_package": package, "sources": sources, "approved_rules": [rule],
            "output_dir": str(tmp_path / "candidate"), "taxonomy_path": taxonomy, "chat_json_fn": mapper,
            "target_profile_path": profile, "target_mapping_path": mapping}


def test_complete_synthetic_derivation_builds_all_target_assets(derivation):
    receipt = prepare_derivation_candidate(**derivation, fixture=True)
    assert receipt["status"] == "validated" and receipt["fixture"] is True
    assert receipt["publish_ready"] is False
    root = __import__("pathlib").Path(derivation["output_dir"])
    report = json.loads((root / "onboarding_report.json").read_text(encoding="utf-8"))
    assert all((root / f).is_file() for f in report["files"].values())
    assert {"approved_rules.json", "difference_package.json", "source_manifest.json"}.issubset(report["derivation_assets"])
    profile = yaml.safe_load((root / report["files"]["profile"]).read_text(encoding="utf-8"))
    assert set(profile["professional_evidence"]) == {"indicators", "methods", "criteria"}
    assert any(p.text == "目标测试方法" for p in Document(root / report["files"]["template"]).paragraphs)


@pytest.mark.parametrize("missing", ["indicators", "methods", "criteria"])
def test_missing_professional_evidence_is_blocked(derivation, missing):
    derivation["difference_package"]["professional_evidence"][missing] = []
    receipt = prepare_derivation_candidate(**derivation)
    assert receipt["status"] == "blocked"
    assert any(missing in reason for reason in receipt["validation"]["blockers"])


def test_rename_only_cannot_publish_high_frequency_identity(derivation):
    plan = build_template_edit_plan(derivation["baseline"]["template"], '把“技术指标”改为“高频技术指标”', allow_llm=False)
    derivation["difference_package"]["edit_plan"] = plan
    receipt = prepare_derivation_candidate(**derivation)
    assert receipt["status"] == "blocked"
    assert any("仅修改名称" in r for r in receipt["validation"]["blockers"])


def test_stale_rule_and_inapplicable_source_are_blocked(derivation):
    derivation["approved_rules"][0]["operations"] = []
    derivation["sources"][0]["applicability"] = {"product_type": "low_frequency", "domain": "military"}
    receipt = prepare_derivation_candidate(**derivation)
    assert receipt["status"] == "blocked"
    assert any("差异规则" in r for r in receipt["validation"]["blockers"])
    assert any("专业来源" in r for r in receipt["validation"]["blockers"])


def test_indicator_quote_cannot_be_relabelled_as_method_and_criterion(derivation):
    indicator = derivation["difference_package"]["professional_evidence"]["indicators"]
    derivation["difference_package"]["professional_evidence"]["methods"] = deepcopy(indicator)
    derivation["difference_package"]["professional_evidence"]["criteria"] = deepcopy(indicator)
    receipt = prepare_derivation_candidate(**derivation)
    assert receipt["status"] == "blocked"
    assert any("语义映射" in reason for reason in receipt["validation"]["blockers"])


def lifecycle_for(derivation, tmp_path):
    candidate = __import__("pathlib").Path(derivation["output_dir"])
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(yaml.safe_dump({"product_types": {"unrelated": {"enabled": True, "domains": {"civil": {"template": "keep.docx"}}}}}), encoding="utf-8")
    return ControlledAssetLifecycle(candidate_root=candidate.parent, catalog_path=catalog,
                                    template_root=tmp_path / "templates", mapping_root=tmp_path / "mapping",
                                    profile_root=tmp_path / "profiles", audit_root=tmp_path / "audit")


def evidence_for(candidate):
    def runner(root, case):
        (root / "fixture_run.docx").write_bytes(b"synthetic fixture output, not production engineering")
        return {"engine": "src.pipeline_cli.run_pipeline", "checks": [{"id": "fixture", "passed": True}], "outputs": [{"file": "fixture_run.docx"}]}
    regression = record_regression_evidence(candidate, runner=runner, cases=[{"fixture_source": "test"}])
    (candidate / "page.png").write_bytes(b"synthetic fixture image")
    visual = {"asset_digest": core_asset_digest(candidate), "reviewer": "fixture_reviewer", "conclusion": "passed",
              "regression_sha256": regression["sha256"],
              "pages": [{"file": "page.png", "sha256": file_hash(candidate / "page.png")}]}
    (candidate / "visual.json").write_text(json.dumps(visual), encoding="utf-8")
    return {"regression": regression, "visual": {"file": "visual.json", "sha256": file_hash(candidate / "visual.json")}}


def test_boolean_reviews_cannot_approve_legacy_candidate(derivation, tmp_path):
    prepare_derivation_candidate(**derivation)
    lifecycle = lifecycle_for(derivation, tmp_path)
    with pytest.raises(ValueError, match="摘要|证据"):
        lifecycle.review("candidate", approved=True, reviewer="r", reason="test", regression_passed=True, visual_review_passed=True)


def test_full_manifest_changes_invalidate_approval(derivation, tmp_path):
    prepare_derivation_candidate(**derivation)
    lifecycle = lifecycle_for(derivation, tmp_path)
    candidate = __import__("pathlib").Path(derivation["output_dir"])
    evidence = evidence_for(candidate)
    lifecycle.review("candidate", approved=True, reviewer="r", reason="fixture-only unit test", regression_passed=True,
                     visual_review_passed=True, evidence_manifest=evidence, expected_manifest_digest=full_manifest(candidate)["digest"])
    (candidate / "approved_rules.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="完整资产"):
        lifecycle.publish("candidate", publisher="p", expected_target_digest=lifecycle.describe("candidate")["target_digest"])


def test_target_scoped_publish_and_rollback_preserve_unrelated_later_changes(derivation, tmp_path):
    prepare_derivation_candidate(**derivation)
    lifecycle = lifecycle_for(derivation, tmp_path)
    candidate = __import__("pathlib").Path(derivation["output_dir"])
    evidence = evidence_for(candidate)
    lifecycle.review("candidate", approved=True, reviewer="r", reason="synthetic lifecycle test", regression_passed=True,
                     visual_review_passed=True, evidence_manifest=evidence, expected_manifest_digest=full_manifest(candidate)["digest"])
    target = lifecycle.describe("candidate")["target_digest"]
    with pytest.raises(ValueError, match="冲突"):
        lifecycle.publish("candidate", publisher="p", expected_target_digest="stale")
    lifecycle.publish("candidate", publisher="p", expected_target_digest=target)
    catalog = yaml.safe_load(lifecycle.catalog_path.read_text(encoding="utf-8"))
    catalog["product_types"]["unrelated"]["domains"]["civil"]["template"] = "new_unrelated.docx"
    catalog["product_types"]["fixture_high_frequency"]["domains"]["civil"] = {"template": "later_civil.docx"}
    published_target = deepcopy(catalog["product_types"]["fixture_high_frequency"]["domains"]["military"])
    catalog["product_types"]["fixture_high_frequency"]["domains"]["military"]["template"] = "later_target.docx"
    lifecycle.catalog_path.write_text(yaml.safe_dump(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="后续发布"):
        lifecycle.rollback("candidate", actor="r", reason="cannot overwrite subsequent target")
    catalog["product_types"]["fixture_high_frequency"]["domains"]["military"] = published_target
    lifecycle.catalog_path.write_text(yaml.safe_dump(catalog), encoding="utf-8")
    lifecycle.rollback("candidate", actor="r", reason="fixture test")
    after = yaml.safe_load(lifecycle.catalog_path.read_text(encoding="utf-8"))
    assert after["product_types"]["unrelated"]["domains"]["civil"]["template"] == "new_unrelated.docx"
    assert after["product_types"]["fixture_high_frequency"]["domains"] == {"civil": {"template": "later_civil.docx"}}


def test_catalog_cannot_publish_different_assets_than_the_reviewed_bundle(derivation, tmp_path):
    prepare_derivation_candidate(**derivation)
    lifecycle = lifecycle_for(derivation, tmp_path)
    candidate = __import__("pathlib").Path(derivation["output_dir"])
    patch_path = candidate / "catalog_patch.yaml"
    patch = yaml.safe_load(patch_path.read_text(encoding="utf-8"))
    patch["product_types"]["fixture_high_frequency"]["domains"]["military"]["profile"] = "unreviewed_profile.yaml"
    patch_path.write_text(yaml.safe_dump(patch), encoding="utf-8")
    evidence = evidence_for(candidate)
    lifecycle.review("candidate", approved=True, reviewer="r", reason="synthetic contract test", regression_passed=True,
                     visual_review_passed=True, evidence_manifest=evidence, expected_manifest_digest=full_manifest(candidate)["digest"])
    with pytest.raises(ValueError, match="目标绑定"):
        lifecycle.publish("candidate", publisher="p", expected_target_digest=lifecycle.describe("candidate")["target_digest"])


def test_fixture_candidate_cannot_receive_production_approval(derivation, tmp_path):
    prepare_derivation_candidate(**derivation, fixture=True)
    lifecycle = lifecycle_for(derivation, tmp_path)
    candidate = __import__("pathlib").Path(derivation["output_dir"])
    evidence = evidence_for(candidate)
    with pytest.raises(ValueError, match="夹具"):
        lifecycle.review("candidate", approved=True, reviewer="r", reason="fixture", regression_passed=True,
                         visual_review_passed=True, evidence_manifest=evidence, expected_manifest_digest=full_manifest(candidate)["digest"])


def test_original_pipeline_adapter_preserves_engine_contract_with_synthetic_runner(derivation, monkeypatch):
    from jonhon_taskbook.template_derivation import OriginalPipelineRegressionRunner
    from jonhon_taskbook import llm_client
    import src.pipeline_cli
    prepare_derivation_candidate(**derivation, fixture=True)
    captured, fail_first = [], [True]
    def fake_pipeline(**kwargs):
        captured.append(kwargs)
        if fail_first[0]:
            fail_first[0] = False
            raise RuntimeError("synthetic provider failure")
        doc = Document()
        doc.add_paragraph("synthetic contract fixture only")
        doc.save(kwargs["out_path"])
        return {"ok": True, "delivery_status": "approved"}
    monkeypatch.setattr(src.pipeline_cli, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(llm_client, "get_model_status", lambda *_: {"configured": True})
    from contextlib import nullcontext
    monkeypatch.setattr(llm_client, "model_scope", lambda *_: nullcontext())
    sources = [derivation["sources"][0], {**derivation["sources"][0], "id": "fixture_spec", "role": "spec"}]
    context = {"product_type": derivation["target"]["product_type"], "product_domain": "military", "development_process": "改型II",
               "cover_phase": "S", "product_series": "FIXTURE", "organization_scope": "non_central_research"}
    runner = OriginalPipelineRegressionRunner(actor_id="local:fixture", model_selection={"provider": "fixture", "name": "fixture"})
    with pytest.raises(ValueError, match="失败尝试已留存"):
        record_regression_evidence(derivation["output_dir"], runner=runner,
                                   cases=[{"context": context, "sources": sources}], fixture=True)
    evidence = record_regression_evidence(derivation["output_dir"], runner=runner,
                                          cases=[{"context": context, "sources": sources}], fixture=True)
    assert evidence["file"] == "regression_evidence.json"
    assert len(captured) == 2 and captured[0]["out_path"] != captured[1]["out_path"]
    call = captured[1]
    assert call["use_llm"] is True and call["formal_output"] is True and call["preserve_unfilled_template"] is True
    assert call["selected_product_type"] == context["product_type"]
    assert call["development_process"] == "改型II" and call["cover_phase"] == "S"
    assert call["product_series"] == "FIXTURE" and call["organization_scope"] == "non_central_research"
    candidate = __import__("pathlib").Path(derivation["output_dir"])
    stored = json.loads((candidate / evidence["file"]).read_text(encoding="utf-8"))
    assert all("path" not in source for source in stored["runs"][0]["case"]["sources"])
    failed = [json.loads(p.read_text(encoding="utf-8")) for p in (candidate / "regression").rglob("regression_receipt.json")]
    assert any(r.get("error_type") == "RuntimeError" and r["ok"] is False for r in failed)
