"""Evidence and real-engine boundaries of local RD actions."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

from docx import Document
import pytest


CONTEXT = {
    "product_type": "low_frequency_rectangular", "product_domain": "military",
    "development_process": "全新", "cover_phase": "S", "product_series": "TEST-A",
    "organization_scope": "non_central_research",
}


def source(tmp_path, text, role="tech", sid="s1", **extra):
    path = tmp_path / f"{sid}.docx"
    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    doc.save(path)
    return {"id": sid, "name": path.name, "role": role, "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "version": 1, **extra}


def snapshot(sources=(), context=None):
    return {"project_id": "p1", "case_id": "c1", "workpackage_id": "w1",
            "context": dict(CONTEXT if context is None else context), "sources": list(sources),
            "product_route": {"value": "new"}, "composition_route": {"value": "direct"},
            "execution_mode": "local_real", "model_selection": {}, "requirements": []}


def run(action, snap, tmp_path, previous=None, **kwargs):
    from src.service.rd_platform.executors import execute
    return execute(action, snap, previous or {}, tmp_path / "work", lambda *a: None,
                   kwargs.get("cancelled", lambda: False))


def test_blank_context_is_blocked_without_business_defaults(tmp_path):
    result = run("resolve_context", snapshot(context={}), tmp_path)
    assert result["status"] == "blocked"
    assert all(not value for value in result["result"]["context"].values())
    assert {item["field"] for item in result["obligations"]} == set(CONTEXT)


def test_context_resolves_only_explicit_local_evidence_with_locations(tmp_path):
    doc = source(tmp_path, "产品类型：低频连接器-矩形低频\n产品领域：军品\n研制流程：全新\n研制阶段：S\n产品系列：TEST-A\n组织范围：非中央研究院产品")
    result = run("resolve_context", snapshot([doc], {}), tmp_path)
    assert result["status"] == "completed"
    assert result["result"]["context"] == CONTEXT
    for evidence in result["result"]["context_provenance"].values():
        assert evidence["source_id"] == "s1"
        assert evidence["location"]["body_index"] >= 0
        assert evidence["quote"]


def test_ambiguous_context_remains_unresolved(tmp_path):
    docs = [source(tmp_path, "研制阶段：S", sid="s1"), source(tmp_path, "研制阶段：D", sid="s2")]
    result = run("resolve_context", snapshot(docs, {**CONTEXT, "cover_phase": ""}), tmp_path)
    assert result["status"] == "blocked"
    assert result["result"]["context"]["cover_phase"] == ""
    assert len(result["result"]["candidates"]["cover_phase"]) == 2


def test_source_mutation_blocks_every_action(tmp_path):
    doc = source(tmp_path, "产品系列：TEST-A")
    Path(doc["path"]).write_bytes(b"changed after submit")
    result = run("consistency", snapshot([doc]), tmp_path)
    assert result["status"] == "blocked"
    assert "hash" in str(result["blocked_reasons"]).lower()


def test_cross_case_evidence_is_blocked(tmp_path):
    doc = source(tmp_path, "产品系列：TEST-A", case_id="another-case")
    assert run("consistency", snapshot([doc]), tmp_path)["status"] == "blocked"


def test_product_identity_mismatch_blocks_consistency(tmp_path):
    doc = source(tmp_path, "产品系列：OTHER-B")
    result = run("consistency", snapshot([doc]), tmp_path)
    assert result["status"] == "blocked"
    assert "OTHER-B" in str(result["blocked_reasons"])


def test_product_route_conflict_is_not_repaired_using_composition_route(tmp_path):
    snap = snapshot()
    snap["product_route"] = {"value": "modification"}
    snap["composition_route"] = {"value": "new"}
    result = run("resolve_context", snap, tmp_path)
    assert result["status"] == "blocked"
    assert result["result"]["context"]["development_process"] == "全新"


def test_template_plan_pins_controlled_assets_and_keeps_two_routes(tmp_path):
    snap = snapshot()
    before = deepcopy(snap)
    result = run("template_plan", snap, tmp_path)
    assert result["status"] == "completed"
    assert snap == before
    plan = result["result"]
    assert plan["product_route"]["value"] == "new"
    assert plan["composition_route"]["value"] == "direct"
    assert plan["selection"]["product_type"] == CONTEXT["product_type"]
    assert {item["kind"] for item in result["artifacts"]} >= {"template", "profile", "mapping", "template_plan"}
    for artifact in result["artifacts"]:
        path = Path(artifact["path"])
        assert path.is_relative_to(tmp_path / "work")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]


def test_missing_high_frequency_template_blocks_without_identity_substitution(tmp_path):
    snap = snapshot(context={**CONTEXT, "product_type": "high_frequency_connector"})
    result = run("template_plan", snap, tmp_path)
    assert result["status"] == "blocked"
    assert result["result"]["context"]["product_type"] == "high_frequency_connector"
    assert result["result"]["candidate_asset_requirements"]


def test_explicit_source_applicability_builds_independent_candidate_assets(tmp_path):
    doc = source(tmp_path, "产品类型：high_frequency_connector\n产品领域：military\n模板基线：rf_standard_interface/military\n模板适用产品：high_frequency_connector\n模板适用领域：military\n模板适配依据：沿用射频标准接口产品任务书结构和指标词表，具体指标数值由本次技术要求提供。")
    snap = snapshot([doc], {**CONTEXT, "product_type": "high_frequency_connector"})
    snap["composition_route"] = {"value": "adapt", "source_ids": ["s1"], "rationale": "依据适用声明适配"}
    result = run("template_plan", snap, tmp_path)
    assert result["status"] == "blocked"
    plan = result["result"]
    assert plan["context"]["product_type"] == "high_frequency_connector"
    assert plan["product_route"]["value"] == "new"
    assert plan["applicability"]["source_id"] == "s1"
    assert plan["applicability"]["baseline"] == "rf_standard_interface/military"
    assert plan["publish_ready"] is False
    assert plan["applicability"]["engineering_applicability_validated"] is False
    assert {item["kind"] for item in result["artifacts"]} >= {"candidate_seed_template", "candidate_seed_profile", "candidate_seed_mapping", "applicability"}


def test_contract_example_mode_cannot_become_real_success(tmp_path):
    snap = snapshot()
    snap["execution_mode"] = "contract_example"
    assert run("resolve_context", snap, tmp_path)["status"] == "blocked"


def custom_plan(tmp_path):
    tpl = tmp_path / "template.docx"
    doc = Document()
    doc.add_heading("产品组成", 1)
    doc.add_paragraph("【人工填写】")
    doc.add_heading("任务进度要求", 1)
    doc.add_paragraph("待补充")
    doc.add_heading("安全性要求", 1)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "要求"
    table.cell(1, 0).text = "防火要求"
    doc.save(tpl)
    return {"selection": {"template_path": str(tpl), "product_type": CONTEXT["product_type"],
                          "product_domain": "military"},
            "assets": {"template": {"path": str(tpl), "sha256": hashlib.sha256(tpl.read_bytes()).hexdigest()}},
            "context": dict(CONTEXT)}


def test_completion_records_all_gap_kinds_and_local_candidates(tmp_path):
    plan = custom_plan(tmp_path)
    doc = source(tmp_path, "产品组成：产品由壳体、绝缘体和接触件组成。")
    result = run("content_completion", snapshot([doc]), tmp_path, {"template_plan": plan})
    assert result["status"] == "blocked"
    ledger = result["result"]["ledger"]
    assert {item["kind"] for item in ledger} >= {"manual_marker", "placeholder", "empty_table_cell"}
    composition = next(item for item in ledger if item["title"] == "产品组成")
    assert composition["status"] == "evidence_ready"
    assert composition["candidates"][0]["source_id"] == "s1"
    assert composition["candidates"][0]["quote"] == "产品由壳体、绝缘体和接触件组成。"
    assert all(item["status"] == "blocked" for item in ledger if item["title"] != "产品组成")
    assert any(item["kind"] == "completion_ledger" for item in result["artifacts"])


def test_reference_only_content_is_a_candidate_not_engine_design_input(tmp_path):
    doc = source(tmp_path, "产品组成：产品由壳体和接触件组成。", role="reference")
    result = run("content_completion", snapshot([doc]), tmp_path, {"template_plan": custom_plan(tmp_path)})
    entry = next(item for item in result["result"]["ledger"] if item["title"] == "产品组成")
    assert entry["status"] == "blocked"
    assert entry["candidates"][0]["role"] == "reference"


def test_generate_requires_completed_evidence_ledger(tmp_path):
    result = run("generate", snapshot(), tmp_path, {"content_completion": {"status": "blocked", "ledger": []}})
    assert result["status"] == "blocked"
    assert not any(item["kind"] == "taskbook" for item in result["artifacts"])


def test_verify_does_not_accept_unverifiable_success_boolean(tmp_path):
    result = run("verify", snapshot(), tmp_path, {"generate": {"ok": True, "qa_ok": True}})
    assert result["status"] == "blocked"
    assert result["result"]["delivery_approved"] is False


def test_cancelled_action_does_not_publish_artifacts(tmp_path):
    result = run("template_plan", snapshot(), tmp_path, cancelled=lambda: True)
    assert result["status"] == "blocked"
    assert result["artifacts"] == []


def test_unknown_action_cannot_report_completed(tmp_path):
    assert run("remote_ontology_success", snapshot(), tmp_path)["status"] == "failed"


def test_uploaded_source_blob_without_suffix_uses_original_name(tmp_path):
    doc = source(tmp_path, "产品系列：TEST-A")
    blob = tmp_path / "source-opaque-id"
    Path(doc["path"]).rename(blob)
    doc["path"] = str(blob)
    result = run("consistency", snapshot([doc]), tmp_path)
    assert result["status"] == "completed"
    assert result["result"]["consistent"] is True


def test_applicability_excludes_non_selected_budget_branch(tmp_path):
    tpl = tmp_path / "branches.docx"
    doc = Document()
    doc.add_heading("研制经费预算（适用于非中央研究院产品）", 1)
    doc.add_paragraph("受控预算管理条文")
    doc.add_heading("研制经费预算及经济性分析（适用于中央研究院产品）", 1)
    doc.add_paragraph("【人工填写】")
    doc.save(tpl)
    from src.service.rd_platform.completion import build_completion_ledger
    ledger = build_completion_ledger(tpl, CONTEXT, [])
    assert not any("中央研究院产品）" in item["title"] and "非中央" not in item["title"] for item in ledger)


def test_completion_invented_source_candidate_with_placeholder_stays_blocked(tmp_path):
    doc = source(tmp_path, "产品组成：待补充")
    result = run("content_completion", snapshot([doc]), tmp_path, {"template_plan": custom_plan(tmp_path)})
    item = next(item for item in result["result"]["ledger"] if item["title"] == "产品组成")
    assert item["status"] == "blocked"


def test_controlled_rule_change_after_planning_blocks_generation(tmp_path):
    from src.service.rd_platform.engine_bridge import check_assets
    from src.service.rd_platform.completion import EvidenceBlocked
    origin = tmp_path / "rule.yaml"
    origin.write_text("version: 1", encoding="utf-8")
    copy = tmp_path / "fixed-rule.yaml"
    copy.write_bytes(origin.read_bytes())
    pinned = {"rule": {"path": str(copy), "original_path": str(origin), "sha256": hashlib.sha256(copy.read_bytes()).hexdigest()}}
    origin.write_text("version: 2", encoding="utf-8")
    with pytest.raises(EvidenceBlocked):
        check_assets(pinned, check_original=True)


@pytest.mark.parametrize("actor,expected_user", [("oa-login-userid-123", "oa-login-userid-123"), ("local:browser-session", "")])
@pytest.mark.parametrize("completion_state", [
    {"ready": True, "ledger": []},
    {"ready": False, "generation_ready": True, "ledger": [{"status": "blocked", "title": "进度日期缺少依据"}]},
])
def test_real_pipeline_is_invoked_and_failure_is_never_promoted(tmp_path, monkeypatch, actor, expected_user, completion_state):
    from contextlib import nullcontext
    from jonhon_taskbook import llm_client, requirement_classifier
    docs = [source(tmp_path, "产品系列：TEST-A\n产品组成：产品由接触件组成。", sid="tech"),
            source(tmp_path, "产品系列：TEST-A", role="spec", sid="spec")]
    snap = snapshot(docs)
    snap["actor_id"] = actor
    plan = run("template_plan", snap, tmp_path)["result"]
    observed, observed_users = [], []
    def stop_at_real_semantic_boundary(path, *args, **kwargs):
        observed.append(Path(path).read_bytes())
        observed_users.append(llm_client.model_user_id_var.get())
        raise RuntimeError(f"controlled test stops at external semantic boundary: {tmp_path}")
    monkeypatch.setattr(llm_client, "get_model_status", lambda *a: {"configured": True})
    monkeypatch.setattr(llm_client, "model_scope", lambda *a: nullcontext())
    monkeypatch.setattr(requirement_classifier, "build_requirement_classification", stop_at_real_semantic_boundary)
    before = [Path(doc["path"]).read_bytes() for doc in docs]
    result = run("generate", snap, tmp_path, {"template_plan": plan, "content_completion": completion_state})
    assert observed == [before[0]]
    assert observed_users == [expected_user]
    assert result["status"] == "blocked"
    assert result["result"]["ok"] is False
    assert str(tmp_path) not in result["result"]["error"]
    assert any(item["kind"] == "engine_receipt" for item in result["artifacts"])
    assert [Path(doc["path"]).read_bytes() for doc in docs] == before
    import json
    def has_server_path(value):
        if isinstance(value, dict):
            return any(has_server_path(item) for item in value.values())
        if isinstance(value, list):
            return any(has_server_path(item) for item in value)
        return isinstance(value, str) and (str(tmp_path) in value or "src\\service\\config" in value)
    for item in result["artifacts"]:
        if Path(item["path"]).suffix == ".json":
            assert not has_server_path(json.loads(Path(item["path"]).read_text(encoding="utf-8")))


def test_content_gaps_allow_original_engine_review_copy_without_delivery_approval(tmp_path):
    docs = [source(tmp_path, "本次技术要求：液冷管路工作压力0.3MPa。", sid="tech"),
            source(tmp_path, "产品规范：工作压力0.3MPa。", role="spec", sid="spec")]
    snap = snapshot(docs)
    plan = run("template_plan", snap, tmp_path)["result"]
    result = run("content_completion", snap, tmp_path, {"template_plan": plan})
    assert result["status"] == "completed"
    assert result["result"]["generation_ready"] is True
    assert result["result"]["ready"] is False
    assert result["obligations"]
    assert all(item["status"] == "blocked" for item in result["obligations"])


def test_consistency_without_any_source_is_blocked(tmp_path):
    result = run("consistency", snapshot(), tmp_path)
    assert result["status"] == "blocked"
    assert result["result"]["consistent"] is False


def verification_fixture(tmp_path, text="原文设计输入"):
    import json
    from src.service.rd_platform.engine_bridge import artifact, write_json
    source_doc = source(tmp_path, "产品系列：TEST-A")
    snap = snapshot([source_doc])
    output = tmp_path / "output.docx"
    doc = Document()
    doc.add_heading("产品组成", 1)
    doc.add_paragraph(text)
    doc.save(output)
    profile = tmp_path / "profile.yaml"
    profile.write_text("product_type: test\ntechnical_requirements_mode: sections\n", encoding="utf-8")
    qa = tmp_path / "qa.yaml"
    qa.write_text("block_if: {}\nwarn_if: {}\n", encoding="utf-8")
    plan = {"context": dict(CONTEXT), "selection": {"template_path": str(output), "profile_path": str(profile)},
            "assets": {"template": artifact(output, "template"), "profile": artifact(profile, "profile"),
                       "rule_qa_gate": artifact(qa, "rule_qa_gate")}}
    coverage = output.with_suffix(".coverage_ledger.json")
    coverage.write_text(json.dumps({"blocks": [{"block_id": "original-1", "covered": True}]}), encoding="utf-8")
    out = artifact(output, "taskbook")
    saved = {"project_id": snap["project_id"], "case_id": snap["case_id"], "workpackage_id": snap["workpackage_id"],
             "source_hashes": {source_doc["id"]: source_doc["sha256"]}, "output": out,
             "evidence": [out, artifact(coverage, "engine_evidence")],
             "engine_result": {"ok": True, "meta": {"qa_ok": True, "configured_qa_ok": True,
                 "semantic_integrity_ok": True, "delivery_gate_result": {"passed": True}}}}
    receipt = write_json(tmp_path / "receipt.json", saved, "engine_receipt")
    return snap, {"template_plan": plan, "content_completion": {"ready": True, "ledger": []},
                  "generate": {"output": out, "receipt": receipt, "evidence": saved["evidence"], "workpackage_id": snap["workpackage_id"]}}


def test_verify_reexecutes_actual_qa_on_hashed_engine_evidence(tmp_path):
    snap, previous = verification_fixture(tmp_path)
    result = run("verify", snap, tmp_path, previous)
    assert result["status"] == "completed"
    assert result["result"]["delivery_approved"] is True
    assert result["result"]["qa"]["blocked"] is False


def test_verify_blocks_remaining_placeholders_even_if_engine_report_passed(tmp_path):
    snap, previous = verification_fixture(tmp_path, "【人工填写】")
    result = run("verify", snap, tmp_path, previous)
    assert result["status"] == "blocked"
    assert result["result"]["delivery_approved"] is False
    assert any("占位" in str(item) for item in result["blocked_reasons"])


def test_verify_rejects_changed_coverage_sidecar(tmp_path):
    snap, previous = verification_fixture(tmp_path)
    Path(previous["generate"]["output"]["path"]).with_suffix(".coverage_ledger.json").write_text("{}", encoding="utf-8")
    assert run("verify", snap, tmp_path, previous)["status"] == "blocked"


def test_quality_package_reruns_fixed_upstream_generation_in_same_case(tmp_path):
    snap, previous = verification_fixture(tmp_path)
    snap["upstream_workpackage_id"] = snap["workpackage_id"]
    snap["workpackage_id"] = "new-quality-package"
    assert run("verify", snap, tmp_path, previous)["status"] == "completed"


def test_quality_package_cannot_adopt_an_unbound_upstream_receipt(tmp_path):
    snap, previous = verification_fixture(tmp_path)
    snap["workpackage_id"] = "new-quality-package"
    assert run("verify", snap, tmp_path, previous)["status"] == "blocked"


def test_profile_mandatory_section_missing_from_template_is_a_gap(tmp_path):
    from src.service.rd_platform.completion import build_completion_ledger
    plan = custom_plan(tmp_path)
    ledger = build_completion_ledger(plan["selection"]["template_path"], CONTEXT, [],
                                    profile={"delivery_gate": {"required_headings": ["频率性能验证"]}})
    item = next(item for item in ledger if item["title"] == "频率性能验证")
    assert item["kind"] == "missing_mandatory_section" and item["status"] == "blocked"


def test_case_requirements_without_exact_source_evidence_remain_blocked(tmp_path):
    doc = source(tmp_path, "产品组成：产品由壳体和接触件组成。")
    snap = snapshot([doc])
    snap["requirements"] = [{"id": "r1", "title": "接口要求", "content": "应配置三个独立接口", "source_ids": ["s1"]}]
    result = run("content_completion", snap, tmp_path, {"template_plan": custom_plan(tmp_path)})
    entries = [item for item in result["result"]["ledger"] if item["kind"] == "case_requirement"]
    assert len(entries) == 1 and entries[0]["requirement_id"] == "r1"
    assert entries[0]["status"] == "blocked"


def test_distinct_equal_byte_sidecars_have_distinct_artifact_ids(tmp_path):
    from src.service.rd_platform.engine_bridge import artifact
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    first.write_text("{}", encoding="utf-8")
    second.write_bytes(first.read_bytes())
    assert artifact(first, "engine_evidence")["id"] != artifact(second, "engine_evidence")["id"]


@pytest.mark.parametrize("composition_route", ["adapt", "new"])
def test_structural_composition_route_without_controlled_change_plan_is_blocked(tmp_path, composition_route):
    snap = snapshot()
    snap["composition_route"] = {"value": composition_route}
    result = run("template_plan", snap, tmp_path)
    assert result["status"] == "blocked"
    assert result["result"]["composition_route"]["value"] == composition_route
    assert result["result"]["product_route"]["value"] == "new"
    assert any("结构" in str(item) for item in result["blocked_reasons"])


def test_downloadable_plan_json_uses_logical_artifact_references(tmp_path):
    import json
    result = run("template_plan", snapshot(), tmp_path)
    plan_file = next(item for item in result["artifacts"] if item["kind"] == "template_plan")
    content = Path(plan_file["path"]).read_text(encoding="utf-8")
    assert str(tmp_path) not in content
    assert '"original_path"' not in content
    assert '"template_path"' not in content
    exported = json.loads(content)
    assert exported["assets"]["template"]["sha256"] == result["result"]["assets"]["template"]["sha256"]
    assert Path(result["result"]["selection"]["template_path"]).is_file()


def test_verify_requires_every_adopted_source_candidate_in_output(tmp_path):
    snap, previous = verification_fixture(tmp_path, "第一条技术输入")
    previous["content_completion"]["ledger"] = [{"id": "g1", "title": "产品组成", "status": "evidence_ready", "candidates": [
        {"source_id": "s1", "role": "tech", "quote": "第一条技术输入", "adopted": True},
        {"source_id": "s1", "role": "tech", "quote": "第二条技术输入", "adopted": True},
    ]}]
    result = run("verify", snap, tmp_path, previous)
    assert result["status"] == "blocked"
    assert any("第二条技术输入" in str(item) for item in result["blocked_reasons"])
