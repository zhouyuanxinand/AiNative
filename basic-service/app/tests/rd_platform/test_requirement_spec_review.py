"""Specification recommendations bind explicit decisions to source and row versions."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from service.rd_platform import requirement_recommendations
from service.rd_platform.store import RdError
from test_requirement_confirmation import confirm, requirements_project, clarify_requirement
from test_requirement_reviews import proposed
from test_store import issue, new_store


def adopted_project(store):
    project = requirements_project(store)
    tech = project["cases"][0]["sources"][0]
    return proposed(store, project, [
        {"title": title, "content": content, "source_ids": [tech["id"]],
         "evidence": [{"source_id": tech["id"], "quote": content}]}
        for title, content in [("压力", "0.3 MPa"), ("温度", "42°C")]
    ])


def proposal(case, statuses=("matched", "difference")):
    spec = next(s for s in case["sources"] if s["role"] == "spec")
    items = []
    for row, status in zip(case["requirements"], statuses):
        item = {"requirement_id": row["id"], "requirement_revision": row["revision"],
                "status": status, "text": "原文可核对" if status == "matched" else "请核实适用工况",
                "evidence": [] if status == "not_found" else [{"source_id": spec["id"], "quote": row["content"]}],
                "source_refs": []}
        if status == "matched":
            item["proposed_value"] = row["content"]
        items.append(item)
    return {"items": items, "warnings": [], "model_selection": {"name": "test-model", "provider": "test", "id": "1"}}


def generate(store, project, monkeypatch, statuses=("matched", "difference"), key=None):
    mock = Mock(side_effect=lambda case, directory, actor: proposal(case, statuses))
    monkeypatch.setattr(requirement_recommendations, "propose", mock)
    return issue(store, project, "recommend_requirements", key=key), mock


def decide(store, project, index, decision, **kwargs):
    case = project["cases"][0]
    row = case["requirements"][index]
    return issue(store, project, "review_requirement", {
        "requirement_id": row["id"], "requirement_revision": row["revision"],
        "analysis_id": case["source_analysis"]["id"],
        "recommendation_batch_id": case["requirement_recommendations"]["id"],
        "decision": decision, **kwargs})


def test_generation_is_side_effect_free_for_requirements_and_replays_without_model(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project = adopted_project(store)
    original = deepcopy(project["cases"][0]["requirements"])
    generated, mock = generate(store, project, monkeypatch, key="spec-batch")
    case = generated["cases"][0]
    batch = case["requirement_recommendations"]
    assert case["requirements"] == original
    assert case["requirement_baselines"] == []
    assert batch["status"] == "current" and batch["actor"] == "owner"
    assert batch["source_hashes"] == case["source_analysis"]["source_hashes"]
    assert batch["input_revision"] == case["input_revision"]
    assert mock.call_args.args[1] == store.asset_root / "source_analysis" / project["id"] / case["id"] / batch["id"]
    replay = issue(store, project, "recommend_requirements", key="spec-batch")
    assert replay["cases"][0]["requirement_recommendations"] == batch
    assert mock.call_count == 1


def test_matched_and_difference_decisions_are_explicit_and_preserve_other_rows(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch)
    batch = deepcopy(project["cases"][0]["requirement_recommendations"])
    with pytest.raises(RdError, match="尚未处理"):
        confirm(store, project)
    with pytest.raises(RdError, match="不能直接采纳"):
        decide(store, project, 1, "accept")
    with pytest.raises(RdError, match="不能改写"):
        decide(store, project, 0, "accept", actual_value="999 MPa")
    project = decide(store, project, 0, "accept")
    case = project["cases"][0]
    assert case["requirement_recommendations"]["status"] == "current"
    assert case["requirement_recommendations"]["input_revision"] == case["input_revision"]
    assert case["requirement_recommendations"]["items"] == batch["items"]
    first = case["requirements"][0]
    assert first["review"]["recommendation_batch_id"] == batch["id"]
    assert first["review"]["recommendation_sources"][0]["role"] == "spec"
    with pytest.raises(RdError, match="原因"):
        decide(store, project, 1, "reject")
    project = decide(store, project, 1, "reject", reason="客户工况以需求原文为准")
    # Rejecting a suggestion records a decision but does not adopt an actual result.
    with pytest.raises(RdError, match="澄清"):
        confirm(store, project)
    project = clarify_requirement(store, project, 1)
    confirmed = confirm(store, project)["cases"][0]
    assert confirmed["stage"] == "selection"
    assert confirmed["requirement_baselines"][0]["items"][0]["review"]["recommendation_batch_id"] == batch["id"]


def test_not_found_requires_explicit_clarification_adoption(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch, ("not_found", "not_found"))
    with pytest.raises(RdError, match="无需拒绝"):
        decide(store, project, 0, "reject", reason="找不到")
    with pytest.raises(RdError, match="澄清"):
        confirm(store, project)
    project = clarify_requirement(store, project, 0)
    project = clarify_requirement(store, project, 1)
    assert confirm(store, project)["cases"][0]["stage"] == "selection"


def test_clarification_adoption_resolves_difference_and_keeps_other_suggestions_current(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch)
    project = decide(store, project, 1, "reject", reason="需要进一步向客户核实")
    case = project["cases"][0]
    bid = case["requirement_recommendations"]["id"]
    rid, sid = case["requirements"][1]["id"], case["sources"][0]["id"]
    project = issue(store, project, "open_clarification", {"requirement_id": rid, "source_ids": [sid], "question": "确认温度工况"})
    cid = project["cases"][0]["clarifications"][0]["id"]
    project = issue(store, project, "answer_clarification", {"clarification_id": cid, "source_ids": [sid], "answer": "42°C"})
    project = decide(store, project, 0, "accept")
    project = issue(store, project, "adopt_clarification", {"clarification_id": cid, "requirement_content": "42°C"})
    assert project["cases"][0]["clarifications"][0]["adoption"]["recommendation_batch_id"] == bid
    assert confirm(store, project)["cases"][0]["stage"] == "selection"


def test_ordinary_requirement_edit_stales_batch_and_rejects_old_acceptance(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch)
    row = project["cases"][0]["requirements"][0]
    project = issue(store, project, "save_requirement", {"id": row["id"], "title": row["title"],
        "content": "0.5 MPa", "source_ids": row["source_ids"]})
    assert project["cases"][0]["requirement_recommendations"]["status"] == "stale"
    with pytest.raises(RdError):
        decide(store, project, 0, "accept")
    with pytest.raises(RdError):
        confirm(store, project)


def test_regeneration_versions_batch_and_old_batch_cannot_be_accepted(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch)
    old = deepcopy(project["cases"][0]["requirement_recommendations"])
    project, _ = generate(store, project, monkeypatch)
    assert project["cases"][0]["requirement_recommendations_history"] == [old]
    with pytest.raises(RdError, match="批次"):
        decide(store, project, 0, "accept", recommendation_batch_id=old["id"])


def test_validation_and_authorization_happen_before_model(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project = requirements_project(store)
    mock = Mock()
    monkeypatch.setattr(requirement_recommendations, "propose", mock)
    with pytest.raises(RdError, match="采用"):
        issue(store, project, "recommend_requirements")
    project = adopted_project(new_store(tmp_path / "other"))
    store = new_store(tmp_path / "other")
    with pytest.raises(RdError):
        store.recommend_requirements("stranger", project["id"], project["cases"][0]["id"], project["version"], "outsider")
    with pytest.raises(RdError, match="项目已更新"):
        store.recommend_requirements("owner", project["id"], project["cases"][0]["id"], 0, "stale")
    mock.assert_not_called()


def test_missing_main_spec_and_changed_sources_cannot_use_old_recommendations(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project, mock = generate(store, adopted_project(store), monkeypatch)
    case = project["cases"][0]
    spec = next(s for s in case["sources"] if s["role"] == "spec")
    project = issue(store, project, "delete_source", {"source_id": spec["id"]})
    assert project["cases"][0]["requirement_recommendations"]["status"] == "stale"
    with pytest.raises(RdError):
        decide(store, project, 0, "accept")
    with pytest.raises(RdError):
        issue(store, project, "recommend_requirements")
    assert mock.call_count == 1


def test_unchecked_row_revision_cannot_reuse_batch_item(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project = adopted_project(store)

    def old_item(case, directory, actor):
        result = proposal(case)
        result["items"][0]["requirement_revision"] -= 1
        return result

    monkeypatch.setattr(requirement_recommendations, "propose", old_item)
    project = issue(store, project, "recommend_requirements")
    with pytest.raises(RdError, match="此项需求已变化"):
        decide(store, project, 0, "accept")


def test_model_runs_outside_transaction_and_concurrent_edit_cannot_commit(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project = adopted_project(store)

    def concurrent_edit(case, directory, actor):
        issue(store, project, "save_context", {"context": {"product_series": "NEW"}})
        return proposal(case)

    monkeypatch.setattr(requirement_recommendations, "propose", concurrent_edit)
    with pytest.raises(RdError, match="项目已更新"):
        issue(store, project, "recommend_requirements")
    saved = store.get_project("owner", project["id"])["cases"][0]
    assert saved["context"]["product_series"] == "NEW"
    assert not saved.get("requirement_recommendations")


def test_failed_model_retains_previous_batch_and_confirmed_baseline_is_readonly(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch, ("not_found", "not_found"))
    batch = deepcopy(project["cases"][0]["requirement_recommendations"])
    failing = Mock(side_effect=RdError(502, "模型连接失败"))
    monkeypatch.setattr(requirement_recommendations, "propose", failing)
    with pytest.raises(RdError, match="连接失败"):
        issue(store, project, "recommend_requirements")
    assert store.get_project("owner", project["id"])["cases"][0]["requirement_recommendations"] == batch
    project = clarify_requirement(store, project, 0)
    project = clarify_requirement(store, project, 1)
    project = confirm(store, project)
    with pytest.raises(RdError, match="已确认"):
        issue(store, project, "recommend_requirements")
    with pytest.raises(RdError, match="只读"):
        decide(store, project, 0, "manual", actual_value="0.3 MPa")
    assert failing.call_count == 1


def test_needs_review_accepts_original_not_proposal_and_records_explicit_choice(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project = adopted_project(store)

    def applicability_review(case, directory, actor):
        result = proposal(case, ("needs_review", "matched"))
        result["items"][0]["proposed_value"] = "999 MPa"
        return result

    monkeypatch.setattr(requirement_recommendations, "propose", applicability_review)
    project = issue(store, project, "recommend_requirements")
    case = project["cases"][0]
    original = deepcopy(case["source_analysis"]["requirements"][0])
    untouched = deepcopy(case["requirements"][1])
    assert store.records.explicit_requirement_result(case, case["requirements"][0]) is None
    with pytest.raises(RdError, match="不能改写"):
        decide(store, project, 0, "accept", actual_value="999 MPa")
    project = decide(store, project, 0, "accept")
    case, row = project["cases"][0], project["cases"][0]["requirements"][0]
    assert row["content"] == original["content"] == "0.3 MPa"
    assert row["review"]["actual_value"] == "0.3 MPa"
    assert row["review"]["actual_value_source"] == "original"
    assert row["review"]["recommendation"]["proposed_value"] == "999 MPa"
    assert row["review"]["actor"] == "owner" and row["review"]["created_at"]
    assert case["source_analysis"]["requirements"][0] == original
    assert case["requirements"][1] == untouched
    assert store.records.explicit_requirement_result(case, row) == "0.3 MPa"
    repeated = decide(store, project, 0, "accept")
    assert repeated["cases"][0]["requirements"][0] == row
    project = decide(store, repeated, 0, "reject", reason="适用条件仍需确认")
    case = project["cases"][0]
    assert store.records.explicit_requirement_result(case, case["requirements"][0]) is None
    project = decide(store, project, 0, "accept")
    project = decide(store, project, 1, "accept")
    assert confirm(store, project)["cases"][0]["stage"] == "selection"


def test_needs_review_accepts_original_without_proposed_value(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch, ("needs_review", "needs_review"))
    project = decide(store, project, 0, "accept")
    project = decide(store, project, 1, "accept")
    case = confirm(store, project)["cases"][0]
    assert [row["content"] for row in case["requirements"]] == ["0.3 MPa", "42°C"]
    assert all(row["review"]["actual_value_source"] == "original" for row in case["requirement_baselines"][0]["items"])


@pytest.mark.parametrize("invalid_original", ["missing", "rejected", "duplicate", "placeholder", "dash", "missing_source"])
def test_needs_review_cannot_accept_without_verifiable_original(tmp_path, monkeypatch, invalid_original):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch, ("needs_review", "matched"))
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        rows = raw["cases"][0]["source_analysis"]["requirements"]
        if invalid_original == "missing":
            rows.pop(0)
        elif invalid_original == "rejected":
            rows[0]["status"] = "rejected"
        elif invalid_original == "duplicate":
            rows.append(deepcopy(rows[0]))
        elif invalid_original == "missing_source":
            rows[0]["source_ids"] = ["missing"]
        else:
            rows[0]["content"] = "待澄清" if invalid_original == "placeholder" else "--"
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    with pytest.raises(RdError, match="原始指标"):
        decide(store, project, 0, "accept")
    assert "review" not in store.get_project("owner", project["id"])["cases"][0]["requirements"][0]


@pytest.mark.parametrize("invalid", ["marker", "analysis_id", "analysis_status", "analysis_revision", "analysis_hashes", "original_value"])
def test_needs_review_actual_result_requires_current_original_adoption_proof(tmp_path, monkeypatch, invalid):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch, ("needs_review", "matched"))
    project = decide(store, project, 0, "accept")
    case = deepcopy(project["cases"][0])
    row = case["requirements"][0]
    if invalid == "marker":
        row["review"].pop("actual_value_source")
    elif invalid == "analysis_id":
        row["review"]["analysis_id"] = "other-analysis"
    elif invalid == "analysis_status":
        case["source_analysis"]["status"] = "stale"
    elif invalid == "analysis_revision":
        case["source_analysis"]["adopted_input_revision"] -= 1
    elif invalid == "analysis_hashes":
        case["source_analysis"]["source_hashes"] = {}
    else:
        case["source_analysis"]["requirements"][0]["content"] = "0.6 MPa"
    assert store.records.explicit_requirement_result(case, row) is None


def test_needs_review_keeps_stale_batch_revision_and_source_guards(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch, ("needs_review", "matched"))
    for overrides in ({"analysis_id": "old"}, {"recommendation_batch_id": "old"}, {"requirement_revision": 0}):
        with pytest.raises(RdError) as error:
            decide(store, project, 0, "accept", **overrides)
        assert error.value.status == 409
    cid = project["cases"][0]["id"]
    project = store.add_source("owner", project["id"], cid, project["version"], "replaced", "tech", "新需求.txt", b"new source")
    with pytest.raises(RdError):
        decide(store, project, 0, "accept")


def test_matched_results_automatically_fill_then_freeze_on_unified_confirmation(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project = adopted_project(store)
    originals = deepcopy(project["cases"][0]["source_analysis"]["requirements"])

    def matched_values(case, directory, actor):
        result = proposal(case, ("matched", "matched"))
        for item, value in zip(result["items"], ("0.35 MPa", "45°C")):
            item["proposed_value"] = value
            item["evidence"][0]["quote"] = value
        return result

    monkeypatch.setattr(requirement_recommendations, "propose", matched_values)
    project = issue(store, project, "recommend_requirements")
    case = project["cases"][0]
    assert [row["content"] for row in case["requirements"]] == ["0.3 MPa", "42°C"]
    assert [store.records.explicit_requirement_result(case, row) for row in case["requirements"]] == ["0.35 MPa", "45°C"]
    assert all("review" not in row and "specification_result" not in row for row in case["requirements"])
    project = confirm(store, project)
    case = project["cases"][0]
    assert case["stage"] == "selection"
    assert case["source_analysis"]["requirements"] == originals
    assert case["requirement_baselines"][0]["items"] == case["requirements"]
    assert {source["role"] for source in case["requirement_baselines"][0]["source_refs"]} == {"tech", "spec"}
    assert [store.records.explicit_requirement_result(case, row) for row in case["requirements"]] == ["0.35 MPa", "45°C"]
    for row, item in zip(case["requirements"], case["requirement_recommendations"]["items"]):
        record = row["specification_result"]
        assert row["content"] == record["actual_value"] == item["proposed_value"]
        assert record["source_requirement_revision"] == item["requirement_revision"]
        assert record["requirement_revision"] == row["revision"] == item["requirement_revision"] + 1
        assert record["actor"] == "owner" and record["created_at"]
        assert record["actual_value_source"] == "specification"
        assert "review" not in row and not row.get("review_history")
        assert row["history"][-1]["actual_value_source"] == "specification"
        assert len(row["source_ids"]) == 2
    fixed = deepcopy(case["requirements"])
    # Reconfirmation does not invent a second automatic revision or acceptance.
    assert confirm(store, project)["cases"][0]["requirements"] == fixed


@pytest.mark.parametrize("invalid", ["batch_status", "batch_revision", "batch_hashes", "row_revision", "duplicate", "missing_value", "placeholder", "dash", "no_evidence", "requirement_evidence", "empty_quote"])
def test_matched_automatic_result_rejects_invalid_proof(tmp_path, monkeypatch, invalid):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch, ("matched", "matched"))
    case = deepcopy(project["cases"][0])
    batch, row = case["requirement_recommendations"], case["requirements"][0]
    item = batch["items"][0]
    if invalid == "batch_status":
        batch["status"] = "stale"
    elif invalid == "batch_revision":
        batch["input_revision"] -= 1
    elif invalid == "batch_hashes":
        batch["source_hashes"] = {}
    elif invalid == "row_revision":
        item["requirement_revision"] -= 1
    elif invalid == "duplicate":
        batch["items"].append(deepcopy(item))
    elif invalid == "missing_value":
        item.pop("proposed_value")
    elif invalid in {"placeholder", "dash"}:
        item["proposed_value"] = "待澄清" if invalid == "placeholder" else "--"
    elif invalid == "no_evidence":
        item["evidence"] = []
    elif invalid == "requirement_evidence":
        item["evidence"][0]["source_id"] = case["sources"][0]["id"]
    else:
        item["evidence"][0]["quote"] = "  "
    assert store.records.explicit_requirement_result(case, row) is None


def test_matched_automatic_result_never_overrides_adopted_clarification(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch, ("matched", "matched"))
    project = clarify_requirement(store, project, 0, "0.36 MPa")
    case = project["cases"][0]
    assert store.records.explicit_requirement_result(case, case["requirements"][0]) == "0.36 MPa"
    case = confirm(store, project)["cases"][0]
    assert [row["content"] for row in case["requirements"]] == ["0.36 MPa", "42°C"]
    assert "specification_result" not in case["requirements"][0]
    assert case["clarifications"][0]["adoption"]["requirement_content"] == "0.36 MPa"
    assert case["requirements"][1]["specification_result"]["actual_value"] == "42°C"


def test_matched_proposal_can_resolve_placeholder_original_without_fake_adoption(tmp_path):
    from test_requirement_reviews import review_project
    store = new_store(tmp_path)
    project = review_project(store)
    case, row = project["cases"][0], project["cases"][0]["requirements"][1]
    assert row["content"] == "待澄清"
    assert store.records.explicit_requirement_result(case, row) == "42°C"
    case = confirm(store, project)["cases"][0]
    assert case["requirements"][1]["content"] == "42°C"
    assert case["source_analysis"]["requirements"][1]["content"] == "待澄清"
    assert not case["requirements"][1].get("review")


def test_unified_confirmation_failure_does_not_partially_materialize_matches(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project, _ = generate(store, adopted_project(store), monkeypatch, ("matched", "not_found"))
    original = deepcopy(project["cases"][0])
    with pytest.raises(RdError, match="澄清"):
        confirm(store, project)
    saved = store.get_project("owner", project["id"])["cases"][0]
    assert saved["requirements"] == original["requirements"]
    assert saved["input_revision"] == original["input_revision"]
    assert saved["requirement_baselines"] == []
