"""Human clarification, selection evidence, delivery and reuse keep distinct facts."""
import hashlib
import json
import sqlite3

import pytest

from test_store import case_project, issue, new_store
from test_runtime import finish_taskbook_with_document, submitted, approve_engineering, upload_engineering_evidence


def requirements_project(store):
    project = case_project(store)
    cid = project["cases"][0]["id"]
    project = store.add_source("owner", project["id"], cid, project["version"], "source", "tech", "要求.txt", b"original evidence")
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "save_requirement", {"title": "需求A", "content": "原始采用值", "source_ids": [sid]})
    return issue(store, project, "advance_stage", {"stage": "input", "verdict": "approved", "rationale": "核对来源", "source_ids": [sid]})


def selection_project(store):
    project = requirements_project(store)
    sid = project["cases"][0]["sources"][0]["id"]
    return issue(store, project, "advance_stage", {"stage": "requirements", "verdict": "approved", "rationale": "需求确认", "source_ids": [sid]})


def comparison_data(project, kind="product", assessment="unknown"):
    case = project["cases"][0]
    sid = case["sources"][0]["id"]
    return {"kind": kind, "title": "逐项人工核对", "source_ids": [sid], "rows": [
        {"requirement_id": item["id"], "assessment": assessment, "candidate_value": "", "reason": "已核对资料，但候选值没有明确证据", "source_ids": [sid]}
        for item in case["requirements"]]}


def delivery_project(tmp_path):
    store, project = submitted(tmp_path)
    finish_taskbook_with_document(store)
    project = store.get_project("owner", project["id"])
    sid = project["cases"][0]["sources"][0]["id"]
    project = approve_engineering(store, project)
    for stage in ("design", "verification"):
        project = issue(store, project, "advance_stage", {"stage": stage, "verdict": "approved", "rationale": "本人核对资料及当前成果", "source_ids": [sid], "artifact_ids": ["taskbook"]})
    return store, project


def record_acceptance(store, project, outcome="accepted"):
    return issue(store, project, "record_delivery", {"artifact_ids": ["taskbook"], "recipient": "测试接收单位", "receipt": "本人登记的回执记录，不是收件人电子签名",
        "feedback": "要求整改" if outcome == "revision_required" else "收到本次固定成果", "outcome": outcome,
        "source_ids": [project["cases"][0]["sources"][0]["id"]]})


def knowledge_project(tmp_path):
    store, project = delivery_project(tmp_path)
    project = record_acceptance(store, project)
    sid = project["cases"][0]["sources"][0]["id"]
    return store, issue(store, project, "advance_stage", {"stage": "delivery", "verdict": "approved", "rationale": "本人核对交付回执", "source_ids": [sid], "artifact_ids": ["taskbook"]})


def test_clarification_answer_is_separate_until_adoption_versions_the_requirement(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    case = project["cases"][0]
    requirement, sid = case["requirements"][0], case["sources"][0]["id"]
    project = issue(store, project, "open_clarification", {"requirement_id": requirement["id"], "question": "请确认该要求适用条件", "source_ids": [sid]})
    clarification = project["cases"][0]["clarifications"][0]
    assert clarification["status"] == "open" and clarification["required"] is True
    assert clarification["source_snapshots"][0]["sha256"] == hashlib.sha256(b"original evidence").hexdigest()
    project = issue(store, project, "answer_clarification", {"clarification_id": clarification["id"], "answer": "人工依据资料澄清的答复", "source_ids": [sid]})
    assert project["cases"][0]["requirements"][0]["content"] == "原始采用值"
    project = issue(store, project, "adopt_clarification", {"clarification_id": clarification["id"], "requirement_content": "用户明确采用的修订要求"})
    case = project["cases"][0]
    assert case["stage"] == "input" and case["requirements"][0]["revision"] == 2
    assert [item["content"] for item in case["requirements"][0]["history"]] == ["原始采用值", "用户明确采用的修订要求"]
    assert all(item["actor"] == "owner" for item in case["requirements"][0]["history"])
    assert case["clarifications"][0]["status"] == "adopted"
    assert case["clarifications"][0]["adoption"]["requirement_revision"] == 2
    assert new_store(tmp_path).get_project("owner", project["id"])["cases"][0]["requirements"][0]["history"] == case["requirements"][0]["history"]


def test_required_unadopted_clarification_prevents_requirement_confirmation(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    requirement = project["cases"][0]["requirements"][0]
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "open_clarification", {"requirement_id": requirement["id"], "question": "适用条件未知", "source_ids": [sid]})
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "requirements", "verdict": "approved", "rationale": "尚未采用澄清", "source_ids": [sid]})
    assert error.value.status == 422
    with pytest.raises(Exception) as error:
        issue(store, project, "adopt_clarification", {"clarification_id": project["cases"][0]["clarifications"][0]["id"], "requirement_content": "没有答复不能直接采用"})
    assert error.value.status == 409


def test_old_clarification_cannot_be_adopted_after_its_requirement_changed(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    requirement = project["cases"][0]["requirements"][0]
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "open_clarification", {"requirement_id": requirement["id"], "question": "先前版本的问题", "source_ids": [sid]})
    cid = project["cases"][0]["clarifications"][0]["id"]
    project = issue(store, project, "answer_clarification", {"clarification_id": cid, "answer": "先前版本答复", "source_ids": [sid]})
    project = issue(store, project, "save_requirement", {**requirement, "content": "已单独更新"})
    with pytest.raises(Exception) as error:
        issue(store, project, "adopt_clarification", {"clarification_id": cid, "requirement_content": "不能覆盖新的要求"})
    assert error.value.status == 409


def test_comparison_counts_unknown_rows_in_the_denominator_without_predefined_thresholds(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "save_requirement", {"title": "需求B", "content": "第二项要求", "source_ids": [sid]})
    data = comparison_data(project)
    data["rows"][0].update(assessment="match", candidate_value="资料中已明确的候选值", reason="逐项人工核对一致")
    project = issue(store, project, "save_comparison", data)
    comparison = project["cases"][0]["comparisons"][0]
    assert comparison["status"] == "manual_record"
    assert comparison["statistics"] == {"matches": 1, "total": 2, "partial": 0, "gap": 0, "unknown": 1, "match_ratio": 0.5}
    assert comparison["revision"] == 1 and comparison["sha256"]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign_source", "invalid_assessment"])
def test_comparison_rejects_incomplete_or_unsubstantiated_rows(tmp_path, mutation):
    store = new_store(tmp_path)
    project = selection_project(store)
    project = issue(store, project, "save_comparison", comparison_data(project))
    data = comparison_data(project)
    data["id"] = project["cases"][0]["comparisons"][0]["id"]
    if mutation == "missing":
        data["rows"] = []
    elif mutation == "duplicate":
        data["rows"].append(dict(data["rows"][0]))
    elif mutation == "foreign_source":
        data["rows"][0]["source_ids"] = ["source-from-another-case"]
    else:
        data["rows"][0]["assessment"] = "90_percent"
    with pytest.raises(Exception) as error:
        issue(store, project, "save_comparison", data)
    assert error.value.status == 422


def test_direct_product_route_cannot_claim_unresolved_comparison_rows_satisfy_requirements(tmp_path):
    store = new_store(tmp_path)
    project = selection_project(store)
    project = issue(store, project, "save_comparison", comparison_data(project, assessment="partial"))
    comparison = project["cases"][0]["comparisons"][0]
    with pytest.raises(Exception) as error:
        issue(store, project, "record_route_decision", {"axis": "product", "value": "direct", "rationale": "局部符合不能声称直接满足", "source_ids": comparison["source_ids"], "comparison_id": comparison["id"]})
    assert error.value.status == 422
    project = issue(store, project, "record_route_decision", {"axis": "product", "value": "modification", "rationale": "依据差异作出改型决定", "source_ids": comparison["source_ids"], "comparison_id": comparison["id"]})
    assert project["cases"][0]["product_route"]["value"] == "modification"


def test_comparison_revision_is_bound_to_route_and_changes_invalidate_the_old_decision(tmp_path):
    store = new_store(tmp_path)
    project = selection_project(store)
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "save_comparison", comparison_data(project))
    comparison = project["cases"][0]["comparisons"][0]
    with pytest.raises(Exception) as error:
        issue(store, project, "record_route_decision", {"axis": "composition", "value": "direct", "rationale": "不能把产品比对当任务书比对", "source_ids": [sid], "comparison_id": comparison["id"]})
    assert error.value.status == 422
    project = issue(store, project, "record_route_decision", {"axis": "product", "value": "new", "rationale": "本人依据逐项核对决定", "source_ids": [sid], "comparison_id": comparison["id"]})
    route = project["cases"][0]["product_route"]
    assert route["comparison_revision"] == 1 and route["comparison_sha256"] == comparison["sha256"]
    project = issue(store, project, "save_comparison", comparison_data(project, kind="document"))
    document_comparison_id = project["cases"][0]["comparisons"][-1]["id"]
    project = issue(store, project, "record_route_decision", {"axis": "composition", "value": "direct", "rationale": "人工独立决定编制策略", "source_ids": [sid], "comparison_id": document_comparison_id})
    assert project["cases"][0]["composition_route"]["comparison_id"] == document_comparison_id
    project = issue(store, project, "advance_stage", {"stage": "selection", "verdict": "approved", "rationale": "两项决定已确认", "source_ids": [sid]})
    changed = comparison_data(project, assessment="gap")
    changed["id"] = comparison["id"]
    project = issue(store, project, "save_comparison", changed)
    case = project["cases"][0]
    assert case["stage"] == "selection" and case["product_route"] is None
    assert case["comparisons"][0]["revision"] == 2 and case["comparisons"][0]["sha256"] != comparison["sha256"]
    assert case["comparisons"][0]["history"][0]["sha256"] == comparison["sha256"]
    assert any(item.get("comparison_id") == comparison["id"] and item.get("invalidated_at") for item in case["decisions"])
    assert any(item["kind"] == "stage" and item["stage"] == "selection" and item.get("invalidated_at") for item in case["decisions"])


def test_delivery_requires_a_current_accepted_record_and_retains_manual_attestation(tmp_path):
    store, project = delivery_project(tmp_path)
    sid = project["cases"][0]["sources"][0]["id"]
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "delivery", "verdict": "approved", "rationale": "没有真实回执", "source_ids": [sid]})
    assert error.value.status == 422
    project = record_acceptance(store, project, outcome="revision_required")
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "delivery", "verdict": "approved", "rationale": "整改反馈不能直接放行", "source_ids": [sid]})
    assert error.value.status == 422
    project = record_acceptance(store, project)
    delivery = project["cases"][0]["deliveries"][-1]
    assert delivery["status"] == "manual_record" and delivery["electronic_signature"] is False
    assert delivery["artifacts"][0]["sha256"] == hashlib.sha256(b"actual result fixture").hexdigest()
    project = issue(store, project, "advance_stage", {"stage": "delivery", "verdict": "approved", "rationale": "本人核对已登记回执", "source_ids": [sid]})
    assert project["cases"][0]["stage"] == "knowledge"


def test_later_revision_feedback_cannot_be_hidden_by_an_earlier_accepted_receipt(tmp_path):
    store, project = delivery_project(tmp_path)
    project = record_acceptance(store, project)
    project = record_acceptance(store, project, outcome="revision_required")
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "delivery", "verdict": "approved", "rationale": "不能忽略后续整改反馈", "source_ids": [project["cases"][0]["sources"][0]["id"]]})
    assert error.value.status == 422


def test_reuse_is_a_case_local_candidate_and_knowledge_does_not_publish_it(tmp_path):
    store, project = knowledge_project(tmp_path)
    sid = project["cases"][0]["sources"][0]["id"]
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "knowledge", "verdict": "approved", "rationale": "尚无复用候选", "source_ids": [sid]})
    assert error.value.status == 422
    project = issue(store, project, "prepare_reuse", {"title": "本案例经验候选", "content": "有来源、待治理的经验记录", "source_ids": [sid], "artifact_ids": ["taskbook"]})
    candidate = project["cases"][0]["reuse_candidates"][0]
    assert candidate["status"] == "candidate" and candidate["scope"] == "case" and candidate["published"] is False
    assert candidate["input_revision"] == project["cases"][0]["input_revision"]
    project = issue(store, project, "advance_stage", {"stage": "knowledge", "verdict": "approved", "rationale": "候选已准备，未对外发布", "source_ids": [sid]})
    assert project["cases"][0]["status"] == "completed"
    assert project["cases"][0]["reuse_candidates"][0]["published"] is False


def test_input_change_cannot_discard_a_required_question_and_fresh_answer_can_resolve_it(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    requirement = project["cases"][0]["requirements"][0]
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "open_clarification", {"requirement_id": requirement["id"], "question": "尚未解决的适用条件", "source_ids": [sid]})
    clarification_id = project["cases"][0]["clarifications"][0]["id"]
    project = issue(store, project, "save_requirement", {**requirement, "content": "修改后仍需确认的问题"})
    project = issue(store, project, "advance_stage", {"stage": "input", "verdict": "approved", "rationale": "重新核对输入", "source_ids": [sid]})
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "requirements", "verdict": "approved", "rationale": "不能因问题过期而当作已解决", "source_ids": [sid]})
    assert error.value.status == 422
    project = issue(store, project, "answer_clarification", {"clarification_id": clarification_id, "answer": "针对当前需求版本的明确答复", "source_ids": [sid]})
    project = issue(store, project, "adopt_clarification", {"clarification_id": clarification_id, "requirement_content": "针对当前版本明确采用的要求"})
    for stage in ("input", "requirements"):
        project = issue(store, project, "advance_stage", {"stage": stage, "verdict": "approved", "rationale": "已核对并采用澄清", "source_ids": [sid]})
    assert project["cases"][0]["stage"] == "selection"


def test_comparison_for_old_input_cannot_be_bound_to_a_new_decision(tmp_path):
    store = new_store(tmp_path)
    project = selection_project(store)
    project = issue(store, project, "save_comparison", comparison_data(project))
    comparison_id = project["cases"][0]["comparisons"][0]["id"]
    project = issue(store, project, "save_context", {"context": {"product_series": "updated-input"}})
    sid = project["cases"][0]["sources"][0]["id"]
    for stage in ("input", "requirements"):
        project = issue(store, project, "advance_stage", {"stage": stage, "verdict": "approved", "rationale": "按新输入重新确认", "source_ids": [sid]})
    with pytest.raises(Exception) as error:
        issue(store, project, "record_route_decision", {"axis": "product", "value": "new", "rationale": "旧比对不能绿新输入", "source_ids": [sid], "comparison_id": comparison_id})
    assert error.value.status == 409


def test_reuse_gate_rechecks_the_fixed_candidate_artifact_hash(tmp_path):
    store, project = knowledge_project(tmp_path)
    case = project["cases"][0]
    sid = case["sources"][0]["id"]
    project = issue(store, project, "prepare_reuse", {"title": "待治理候选", "content": "引用固定成果", "source_ids": [sid], "artifact_ids": ["taskbook"]})
    artifact = store.artifact_path("owner", project["id"], case["id"], case["workpackages"][0]["id"], "taskbook")
    artifact.write_bytes(b"tampered after preparing the candidate")
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "knowledge", "verdict": "approved", "rationale": "候选所用文件已变不能通过", "source_ids": [sid]})
    assert error.value.status == 409


def test_explicit_nonpublication_reason_needs_evidence_and_never_publishes(tmp_path):
    store, project = knowledge_project(tmp_path)
    sid = project["cases"][0]["sources"][0]["id"]
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "knowledge", "verdict": "approved", "rationale": "明确不发布", "source_ids": [sid], "no_publish_reason": "资料受限", "no_publish_source_ids": []})
    assert error.value.status == 422
    project = issue(store, project, "advance_stage", {"stage": "knowledge", "verdict": "approved", "rationale": "本人记录不发布处置", "source_ids": [sid], "no_publish_reason": "依据来源限制，不对外发布", "no_publish_source_ids": [sid]})
    disposition = project["cases"][0]["reuse_disposition"]
    assert disposition["kind"] == "not_publish" and disposition["actor"] == "owner" and disposition["published"] is False


@pytest.mark.parametrize("axis,value", [("product", "direct"), ("product", "new"), ("composition", "adapt")])
def test_new_route_commands_require_a_current_comparison_instead_of_legacy_warning_bypass(tmp_path, axis, value):
    store = new_store(tmp_path)
    project = selection_project(store)
    sid = project["cases"][0]["sources"][0]["id"]
    with pytest.raises(Exception) as error:
        issue(store, project, "record_route_decision", {"axis": axis, "value": value, "rationale": "省略比对不能作为历史兼容通道", "source_ids": [sid]})
    assert error.value.status == 422 and "逐项比对" in error.value.detail
    unchanged = store.get_project("owner", project["id"])
    assert unchanged["cases"][0][f"{axis}_route"] is None


def test_saved_legacy_unbound_decision_is_readable_with_warning_and_read_does_not_rewrite_it(tmp_path):
    store = new_store(tmp_path)
    project = selection_project(store)
    sid = project["cases"][0]["sources"][0]["id"]
    with sqlite3.connect(store.path) as db:
        payload = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        case = payload["cases"][0]
        legacy = {"value": "direct", "rationale": "原版本已保存的历史人工决定", "source_ids": [sid], "actor": "historical-user", "created_at": "2026-10-20T08:00:00+00:00", "input_revision": case["input_revision"]}
        case["product_route"] = legacy
        case["decisions"].append({"id": "legacy-route", "kind": "route", "axis": "product", "stage": "selection", **legacy})
        case["warnings"] = []
        saved = json.dumps(payload, ensure_ascii=False)
        db.execute("UPDATE projects SET payload=? WHERE id=?", (saved, project["id"]))
    read = store.get_project("owner", project["id"])
    assert read["cases"][0]["product_route"] == legacy
    assert any(item["code"] == "product_route_without_comparison" for item in read["cases"][0]["warnings"])
    listed = store.list_projects("owner")[0]
    assert any(item["code"] == "product_route_without_comparison" for item in listed["cases"][0]["warnings"])
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0] == saved


def test_explicit_nonpublication_choice_has_priority_over_an_existing_candidate(tmp_path):
    store, project = knowledge_project(tmp_path)
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "prepare_reuse", {"title": "旧的准备候选", "content": "尚未采用且未发布", "source_ids": [sid], "artifact_ids": ["taskbook"]})
    previous_candidates = project["cases"][0]["reuse_candidates"]
    project = issue(store, project, "advance_stage", {"stage": "knowledge", "verdict": "approved", "rationale": "本次明确选择不发布", "source_ids": [sid],
        "no_publish_reason": "依据本次资料限制，不采用已有候选作为本次处置", "no_publish_source_ids": [sid]})
    disposition = project["cases"][0]["reuse_disposition"]
    assert disposition["kind"] == "not_publish" and disposition["reason"] == "依据本次资料限制，不采用已有候选作为本次处置"
    assert project["cases"][0]["reuse_candidates"] == previous_candidates


def test_invalid_explicit_nonpublication_reason_is_not_replaced_by_a_candidate(tmp_path):
    store, project = knowledge_project(tmp_path)
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "prepare_reuse", {"title": "准备候选", "content": "仍需明确处置", "source_ids": [sid], "artifact_ids": ["taskbook"]})
    with pytest.raises(Exception) as error:
        issue(store, project, "advance_stage", {"stage": "knowledge", "verdict": "approved", "rationale": "明确不发布但理由未填写", "source_ids": [sid], "no_publish_reason": "", "no_publish_source_ids": [sid]})
    assert error.value.status == 422


def test_direct_product_uses_source_backed_closeout_and_delivery_receipt(tmp_path):
    from test_store import evidence_project
    store = new_store(tmp_path)
    project = evidence_project(store, product_route="direct")
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "advance_stage", {"stage": "planning", "verdict": "approved", "scope": "按已选成熟产品范围交付", "rationale": "当前逐项指标全部满足", "source_ids": [sid]})
    assert project["cases"][0]["stage"] == "delivery"
    cid = project["cases"][0]["id"]
    project = store.add_source("owner", project["id"], cid, project["version"], "receipt-upload", "reference", "客户接收回执.txt", b"customer acceptance receipt")
    receipt = project["cases"][0]["sources"][-1]["id"]
    project = issue(store, project, "record_delivery", {"artifact_ids": [], "source_ids": [receipt], "outcome": "accepted", "recipient": "客户", "receipt": "已核对上传回执"})
    project = issue(store, project, "advance_stage", {"stage": "delivery", "verdict": "approved", "rationale": "实际回执确认", "source_ids": [receipt]})
    assert project["cases"][0]["stage"] == "knowledge"
    assert project["cases"][0]["deliveries"][0]["inventory_connected"] is False


def test_engineering_nodes_are_real_evidence_records_in_dependency_order(tmp_path):
    store, project = submitted(tmp_path)
    finish_taskbook_with_document(store)
    project = store.get_project("owner", project["id"])
    sid = project["cases"][0]["sources"][0]["id"]
    data = {"node_id": "integration", "verdict": "approved", "summary": "核对整体集成记录", "source_ids": [sid], "artifact_ids": []}
    with pytest.raises(Exception) as error:
        issue(store, project, "record_engineering_node", data)
    assert error.value.status == 422
    for node in ("scheme", "detail", "integration"):
        project, professional_sid = upload_engineering_evidence(store, project, node + "-专业设计报告")
        project = issue(store, project, "record_engineering_node", {**data, "node_id": node, "source_ids": [professional_sid]})
    assert len(project["cases"][0]["engineering_records"]) == 3
    assert all(record["electronic_signature"] is False for record in project["cases"][0]["engineering_records"])
    project = issue(store, project, "advance_stage", {"stage": "design", "verdict": "approved", "rationale": "设计资料核对通过", "source_ids": [sid]})
    assert project["cases"][0]["stage"] == "verification"


def test_engineering_rejection_or_prerequisite_revision_blocks_design_exit(tmp_path):
    store, project = submitted(tmp_path)
    finish_taskbook_with_document(store)
    project = approve_engineering(store, store.get_project("owner", project["id"]))
    sid = project["cases"][0]["sources"][0]["id"]
    decision = {"stage": "design", "verdict": "approved", "rationale": "exit", "source_ids": [sid]}
    project, sid = upload_engineering_evidence(store, project, "方案修订报告")
    for verdict in ("rejected", "approved"):
        project = issue(store, project, "record_engineering_node", {"node_id": "scheme", "verdict": verdict, "summary": "方案核对发生新修订", "source_ids": [sid], "artifact_ids": []})
        with pytest.raises(Exception) as error:
            issue(store, project, "advance_stage", decision)
        assert error.value.status == 422
    for node in ("detail", "integration"):
        project = issue(store, project, "record_engineering_node", {"node_id": node, "verdict": "approved", "summary": "重新核对上游修订", "source_ids": [sid], "artifact_ids": []})
    assert issue(store, project, "advance_stage", decision)["cases"][0]["stage"] == "verification"


def test_supplementary_engineering_upload_keeps_taskbook_and_quality_inputs_fixed(tmp_path):
    store, project = submitted(tmp_path)
    finish_taskbook_with_document(store)
    project = store.get_project("owner", project["id"])
    cid = project["cases"][0]["id"]
    original = project["cases"][0]["workpackages"][0]["snapshot"]
    project = store.add_source("owner", project["id"], cid, project["version"], "engineering-report", "reference", "方案评审记录.txt", b"actual engineering report")
    sid = project["cases"][0]["sources"][-1]["id"]
    project = issue(store, project, "record_engineering_node", {"node_id": "scheme", "verdict": "approved", "summary": "核对上传方案报告", "source_ids": [sid], "artifact_ids": []})
    assert project["cases"][0]["taskbook_binding"]["status"] == "current"
    project = issue(store, project, "pull_workpackage", {"definition_id": "quality_check"})
    wid = project["cases"][0]["workpackages"][-1]["id"]
    project = issue(store, project, "submit_workpackage", {"workpackage_id": wid})
    quality = project["cases"][0]["workpackages"][-1]["snapshot"]
    assert quality["sources"] == original["sources"]
    assert quality["taskbook_binding"] == original["taskbook_binding"]
    assert store.claim_node()["action_id"] == "verify"


def test_profile_change_preserves_sealed_case_stage_and_engineering_history(tmp_path):
    store, project = knowledge_project(tmp_path)
    sid = project["cases"][0]["sources"][0]["id"]
    project = issue(store, project, "advance_stage", {"stage": "knowledge", "verdict": "approved", "rationale": "不发布，保留人工历史", "source_ids": [sid], "no_publish_reason": "当前不具备发布依据", "no_publish_source_ids": [sid]})
    before = project["cases"][0]
    project = store.command("owner", project["id"], project["version"], "profile-after-seal", "save_project_profile", {"customer_name": "新客户业务上下文"})
    case = project["cases"][0]
    assert case["status"] == "completed" and case["stage"] == "knowledge"
    assert case["product_route"] == before["product_route"]
    assert case["engineering_records"] == before["engineering_records"]
    assert case["workpackages"][0]["snapshot"] == before["workpackages"][0]["snapshot"]
    assert case["taskbook_binding"]["status"] == "stale"


def test_engineering_approval_needs_new_professional_deliverable_not_original_requirements(tmp_path):
    store, project = submitted(tmp_path)
    finish_taskbook_with_document(store)
    project = store.get_project("owner", project["id"])
    sid = project["cases"][0]["sources"][0]["id"]
    data = {"node_id": "scheme", "verdict": "approved", "summary": "方案审核", "source_ids": [sid], "artifact_ids": []}
    with pytest.raises(Exception) as error:
        issue(store, project, "record_engineering_node", data)
    assert error.value.status == 422
    with pytest.raises(Exception) as error:
        issue(store, project, "record_engineering_node", {**data, "artifact_ids": ["taskbook"]})
    assert error.value.status == 422
    rejected = issue(store, project, "record_engineering_node", {**data, "verdict": "rejected"})
    assert rejected["cases"][0]["engineering_records"][-1]["verdict"] == "rejected"
