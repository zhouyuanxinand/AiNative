from __future__ import annotations
from tests.support.paths import APP_ROOT

import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml
from jonhon_taskbook.rule_editor import (
    RuleConflictError,
    RuleEditor,
    RuleNotFoundError,
    RuleValidationError,
)

SERVICE = APP_ROOT / "src" / "service"


@pytest.fixture
def editor(tmp_path):
    config = tmp_path / "config"
    package = tmp_path / "package"
    shutil.copytree(SERVICE / "config", config)
    package.mkdir()
    for path in (SERVICE / "jonhon_taskbook").glob("*_profile.yaml"):
        shutil.copy2(path, package / path.name)
    return RuleEditor(config, package, tmp_path / "history")


def patch(path, value):
    return [{"path": path, "value": value}]


def test_registry_contains_live_families_and_profiles_only(editor):
    items = editor.list_rules()["items"]
    ids = {item["id"] for item in items}
    assert len([name for name in ids if name.endswith("_profile")]) == 27
    assert len([name for name in ids if name.endswith("_requirement_categories")]) == 12
    assert len(ids) == 47
    assert {"optical_cable_assembly_profile", "liquid_cooling_connector_profile",
            "optical_cable_assembly_requirement_categories",
            "liquid_cooling_connector_requirement_categories"} <= ids
    assert {"project_profile", "template_catalog", "section_policy", "template_artifact_rules"}.isdisjoint(ids)
    assert all(item["field_count"] > 0 for item in items)
    assert all("path" not in item for item in items)
    assert "仅用于新模板" in editor.get_rule("taskbook_requirement_taxonomy")["description"]


def test_profile_registry_rejects_catalog_path_escape(editor, tmp_path):
    path = editor.config_dir / "template_catalog.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["product_types"]["bad"] = {"label": "bad", "enabled": True, "domains": {"military": {"profile": "../outside_profile.yaml"}}}
    (tmp_path / "outside_profile.yaml").write_text("product_type: not registered", encoding="utf-8")
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert "outside_profile" not in {item["id"] for item in editor.list_rules()["items"]}
    with pytest.raises(RuleNotFoundError):
        editor.get_rule("../outside_profile")


def test_preview_has_human_readable_diff_and_never_writes(editor):
    rule_id = "failure_mode_policy"
    before = editor.get_rule(rule_id)
    content = (editor.config_dir / f"{rule_id}.yaml").read_bytes()
    result = editor.validate_changes(rule_id, patch(["no_applicable_record", "text"], "没有本系列历史故障"), before["revision"])
    assert result["valid"]
    assert result["changes"][0]["before"] == "未查询到历史故障信息"
    assert result["changes"][0]["after"] == "没有本系列历史故障"
    assert result["changes"][0]["label"]
    assert (editor.config_dir / f"{rule_id}.yaml").read_bytes() == content
    assert not editor.history_root.exists()


def test_save_persists_and_restore_creates_audited_revision(editor):
    rule_id = "failure_mode_policy"
    first = editor.get_rule(rule_id)
    saved = editor.save_rule(rule_id, patch(["no_applicable_record", "text"], "未找到精确匹配的历史故障"), first["revision"], "修改业务提示")
    assert saved["revision"] != first["revision"]
    fresh_editor = RuleEditor(editor.config_dir, editor.package_root, editor.history_root)
    assert fresh_editor.get_rule(rule_id)["data"]["no_applicable_record"]["text"] == "未找到精确匹配的历史故障"
    assert len(saved["history"]) == 2
    assert saved["history"][0]["is_current"] is True
    restored = fresh_editor.restore_rule(rule_id, first["revision"], saved["revision"], "恢复说明")
    assert restored["revision"] == first["revision"]
    assert restored["data"] == first["data"]
    assert len(restored["history"]) == 3
    assert restored["history"][0]["restored_from"] == first["revision"]
    assert sum(item["is_current"] for item in restored["history"]) == 1


@pytest.mark.parametrize("rule_id,path,value", [
    ("failure_mode_policy", ["matching", "auto_similar_record_recall"], True),
    ("failure_mode_policy", ["no_applicable_record", "action"], "execute"),
    ("connector_profile", ["semantic_routing", "copy_source_text_only"], False),
    ("connector_profile", ["semantic_routing", "category_mapping"], "../../bad.yaml"),
    ("connector_profile", ["profile_id"], "another"),
    ("qa_gate", ["warn_if", "cover_doc_number_empty"], False),
])
def test_protected_and_ineffective_fields_cannot_be_patched(editor, rule_id, path, value):
    initial = editor.get_rule(rule_id)
    with pytest.raises(RuleValidationError, match="不允许编辑"):
        editor.save_rule(rule_id, patch(path, value), initial["revision"])
    assert editor.get_rule(rule_id)["revision"] == initial["revision"]
    assert not editor.history_root.exists()


@pytest.mark.parametrize("value", [-1, True, 1.5, "3", 10001])
def test_threshold_validation_rejects_invalid_values_without_mutation(editor, value):
    initial = editor.get_rule("qa_gate")
    with pytest.raises(RuleValidationError, match="整数"):
        editor.save_rule("qa_gate", patch(["block_if", "red_text_count_gt"], value), initial["revision"])
    assert editor.get_rule("qa_gate")["revision"] == initial["revision"]


@pytest.mark.parametrize("path,value", [
    (["categories", "source_and_function", "target_heading_level"], 10),
    (["categories", "technical_support", "source_content_patterns"], ["("]),
    (["exact_fragment_routing", "target_categories"], ["made_up_category"]),
    (["categories", "source_and_function", "target_heading_keywords"], []),
    (["categories", "source_and_function", "definition"], " "),
])
def test_category_business_validation(editor, path, value):
    initial = editor.get_rule("connector_requirement_categories")
    with pytest.raises(RuleValidationError):
        editor.save_rule("connector_requirement_categories", patch(path, value), initial["revision"])
    assert editor.get_rule("connector_requirement_categories")["revision"] == initial["revision"]


def test_cross_field_evidence_and_reference_validation(editor):
    rule_id = "development_process_policy"
    initial = editor.get_rule(rule_id)
    changes = [{"path": ["quality_section_evidence", 0, key], "value": []}
               for key in ("evidence_roles", "leaf_evidence_roles", "indicator_signals")]
    with pytest.raises(RuleValidationError, match="不能同时为空"):
        editor.save_rule(rule_id, changes, initial["revision"])
    with pytest.raises(RuleValidationError, match="未登记的引用"):
        editor.validate_changes("standard_applicability", patch(["prefix_allowed_domains", "CCAR"], ["unknown"]))
    with pytest.raises(RuleValidationError, match="未登记的引用"):
        editor.validate_changes("rf_contact_profile", patch(["indicator_sources", "reference_families"], ["unknown"]))


def test_process_section_rules_expose_retention_choices_and_linked_appendix(editor):
    detail = editor.get_rule("development_process_policy")
    fields = {tuple(field["path"]): field for field in detail["fields"]}
    rules = detail["data"]["section_retention_rules"]
    assert rules[0]["keep_processes"] == ["全新"]
    assert rules[1]["keep_processes"] == ["全新", "改型I"]
    assert rules[1]["linked_semantic_titles"] == ["附录A"]
    for index in (0, 1):
        field = fields[("section_retention_rules", index, "keep_processes")]
        assert field["type"] == "string_list"
        assert field["options"] == ["全新", "改型I", "改型II", "改型III"]
        assert "未勾选" in field["description"]


@pytest.mark.parametrize("key,value,message", [
    ("semantic_titles", [], "至少保留一项"),
    ("keep_processes", ["未登记流程"], "未登记的引用"),
    ("keep_processes", ["全新", "全新"], "重复值"),
])
def test_process_section_edits_validate_before_writing(editor, key, value, message):
    rule_id = "development_process_policy"
    initial = editor.get_rule(rule_id)
    with pytest.raises(RuleValidationError, match=message):
        editor.save_rule(rule_id, patch(["section_retention_rules", 0, key], value), initial["revision"])
    assert editor.get_rule(rule_id)["revision"] == initial["revision"]


def test_fragment_limits_follow_effective_runtime_range(editor):
    for key, value in (("min_text_length", 7), ("max_fragments_per_block", 1)):
        with pytest.raises(RuleValidationError, match="整数"):
            editor.validate_changes("rf_connector_requirement_categories", patch(["exact_fragment_routing", key], value))
    with pytest.raises(RuleValidationError, match="至少保留两项"):
        editor.validate_changes("rf_connector_requirement_categories", patch(["exact_fragment_routing", "target_categories"], ["other"]))


def test_template_branches_must_remain_distinguishable(editor):
    data = editor.get_rule("template_variant_policy")["data"]
    first = data["mutually_exclusive_groups"][0]["variants"]["non_central_research"]["heading_markers"]
    with pytest.raises(RuleValidationError, match="不同分支"):
        editor.validate_changes("template_variant_policy", patch(["mutually_exclusive_groups", 0, "variants", "central_research", "heading_markers"], first))


@pytest.mark.parametrize("path,value", [
    (["indicator_map", "电性能", 0, "tech_kws"], ["工作电压", "额定电压"]),
    (["indicator_map", "电性能", 0, "tech_kws"], ["工作电压", "额定电流"]),
    (["indicator_map", "电性能", 0, "related_kws"], ["工作电压"]),
])
def test_product_indicator_changes_pass_runtime_profile_validation_before_saving(editor, path, value):
    rule_id = "connector_profile"
    initial = editor.get_rule(rule_id)
    before = (editor.package_root / f"{rule_id}.yaml").read_bytes()
    with pytest.raises(RuleValidationError, match="指标配置未通过"):
        editor.validate_changes(rule_id, patch(path, value), initial["revision"])
    with pytest.raises(RuleValidationError, match="指标配置未通过"):
        editor.save_rule(rule_id, patch(path, value), initial["revision"])
    assert (editor.package_root / f"{rule_id}.yaml").read_bytes() == before
    assert not editor.history_root.exists()


def test_unused_template_field_label_is_not_editable(editor):
    path = ["fields", "organization_scope", "label"]
    for rule_id in ("template_variant_policy", "single_budget_template_variant_policy"):
        detail = editor.get_rule(rule_id)
        assert path not in [field["path"] for field in detail["fields"]]
        with pytest.raises(RuleValidationError, match="不允许编辑"):
            editor.validate_changes(rule_id, patch(path, "新名称"), detail["revision"])
        assert not any(field["path"][0] == "fields" for field in detail["fields"])


def test_reference_catalog_exposes_consumed_aliases_not_ignored_related_terms(editor):
    detail = editor.get_rule("connector_indicator_catalog")
    assert detail["fields"]
    assert all(field["path"][-1] == "exact_aliases" for field in detail["fields"])
    with pytest.raises(RuleValidationError, match="不允许编辑"):
        editor.validate_changes("connector_indicator_catalog", patch(["common", "electrical", 0, "related_terms"], ["运行中不会使用"]))


def test_reference_catalog_exact_aliases_are_validated_as_indicator_vocabulary(editor):
    rule_id = "connector_indicator_catalog"
    initial = editor.get_rule(rule_id)
    entries = initial["data"]["common"]["environmental"]
    humidity_index = next(i for i, item in enumerate(entries) if item["name"] == "湿热")
    path = ["common", "environmental", humidity_index, "exact_aliases"]
    with pytest.raises(RuleValidationError, match="相关概念不能作为精确同义词"):
        editor.save_rule(rule_id, patch(path, ["潮湿"]), initial["revision"])
    assert editor.get_rule(rule_id)["revision"] == initial["revision"]
    assert not editor.history_root.exists()


def test_reference_options_include_business_labels_but_keep_stable_values(editor):
    def field_for(rule_id, path):
        return next(field for field in editor.get_rule(rule_id)["fields"] if field["path"] == path)

    domains = field_for("standard_applicability", ["prefix_allowed_domains", "CCAR"])
    assert "airworthiness" in domains["options"]
    assert domains["option_labels"]["airworthiness"] == "适航"
    families = field_for("rf_contact_profile", ["indicator_sources", "reference_families"])
    assert families["option_labels"]["common"] == "通用"
    categories = field_for("rf_connector_requirement_categories", ["exact_fragment_routing", "target_categories"])
    assert categories["option_labels"]["source_and_function"] == "来源和功能"
    roles = field_for("development_process_policy", ["quality_section_evidence", 0, "evidence_roles"])
    assert roles["option_labels"]["reliability"] == "可靠性要求"


def test_audit_write_failure_restores_original_file(editor, monkeypatch):
    from jonhon_taskbook import rule_editor

    initial = editor.get_rule("failure_mode_policy")
    actual_write = rule_editor._atomic_write

    def failing_write(path, content):
        if path.name == "history.json":
            raise OSError("simulated audit storage failure")
        actual_write(path, content)

    monkeypatch.setattr(rule_editor, "_atomic_write", failing_write)
    with pytest.raises(OSError, match="audit storage"):
        editor.save_rule("failure_mode_policy", patch(["no_applicable_record", "text"], "测试修改"), initial["revision"])
    assert editor.get_rule("failure_mode_policy")["revision"] == initial["revision"]


def test_new_keyword_is_consumed_by_runtime_mapping_loader(editor):
    from jonhon_taskbook.requirement_classifier import load_category_mapping

    rule_id = "rf_connector_requirement_categories"
    initial = editor.get_rule(rule_id)
    path = ["categories", "source_and_function", "source_heading_keywords"]
    saved = editor.save_rule(rule_id, patch(path, ["客户任务背景"]), initial["revision"])
    mapping = load_category_mapping(editor.config_dir / f"{rule_id}.yaml")
    assert mapping["categories"]["source_and_function"]["source_heading_keywords"] == ["客户任务背景"]
    assert mapping["categories"]["source_and_function"]["definition"] == initial["data"]["categories"]["source_and_function"]["definition"]
    assert saved["revision"] != initial["revision"]


def test_optimistic_concurrency_prevents_lost_updates_across_instances(editor):
    initial = editor.get_rule("failure_mode_policy")
    other = RuleEditor(editor.config_dir, editor.package_root, editor.history_root)

    def save(service, text):
        try:
            service.save_rule("failure_mode_policy", patch(["no_applicable_record", "text"], text), initial["revision"])
            return "saved"
        except RuleConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(save, editor, "更新一")
        b = pool.submit(save, other, "更新二")
    assert sorted([a.result(), b.result()]) == ["conflict", "saved"]
    assert len(editor.list_history("failure_mode_policy")) == 2


def test_restore_rejects_tampered_history_and_stale_revision(editor):
    initial = editor.get_rule("failure_mode_policy")
    saved = editor.save_rule("failure_mode_policy", patch(["no_applicable_record", "text"], "业务说明更新"), initial["revision"])
    with pytest.raises(RuleConflictError):
        editor.restore_rule("failure_mode_policy", initial["revision"], initial["revision"])
    snapshot = editor.history_root / "failure_mode_policy" / f"{initial['revision']}.yaml"
    snapshot.write_text("no_applicable_record: {text: 篡改}\n", encoding="utf-8")
    with pytest.raises(RuleValidationError, match="校验失败"):
        editor.restore_rule("failure_mode_policy", initial["revision"], saved["revision"])
    assert editor.get_rule("failure_mode_policy")["revision"] == saved["revision"]
