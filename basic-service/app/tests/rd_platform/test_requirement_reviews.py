"""Source-faithful enhancement decisions are distinct from adoption and baseline confirmation."""
import json
from copy import deepcopy

import pytest

from service.rd_platform.store import RdError
from test_requirement_confirmation import requirements_project, confirm, clarify_requirement
from test_store import issue, new_store


def proposed(store, project, rows):
    case = project["cases"][0]
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        raw["cases"][0]["source_analysis"] = {"id": "analysis-1", "status": "proposed", "input_revision": case["input_revision"],
            "source_hashes": {s["id"]: s["sha256"] for s in case["sources"]}, "context": {}, "requirements": rows}
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    return issue(store, project, "adopt_source_analysis", {"analysis_id": "analysis-1"})


def review_project(store):
    project = requirements_project(store)
    tech = project["cases"][0]["sources"][0]
    rows = [{"title": title, "content": value, "source_ids": [tech["id"]], "evidence": [{"source_id": tech["id"], "quote": value}]}
            for title, value in [("压力", "0.3 MPa"), ("温度", "待澄清")]]
    return spec_batch(store, proposed(store, project, rows), {"压力": "0.4 MPa", "温度": "42°C"})


def spec_batch(store, project, values):
    """Persist the independent comparison result before testing review commands."""
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        case = raw["cases"][0]
        spec = next(source for source in case["sources"] if source["role"] == "spec")
        case["requirement_recommendations"] = {"id": "spec-batch-1", "status": "current", "input_revision": case["input_revision"],
            "source_hashes": {source["id"]: source["sha256"] for source in case["sources"]},
            "items": [{"requirement_id": row["id"], "requirement_revision": row["revision"], "status": "matched",
                "text": "核对规范值", "proposed_value": values[row["title"]],
                "evidence": [{"source_id": spec["id"], "quote": values[row["title"]]}]}
                for row in case["requirements"] if row["title"] in values]}
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    return store.get_project("owner", project["id"])


def decide(store, project, index, decision, **overrides):
    case = project["cases"][0]
    row = case["requirements"][index]
    batch = case.get("requirement_recommendations")
    return issue(store, project, "review_requirement", {"requirement_id": row["id"], "requirement_revision": row["revision"],
                 **({"recommendation_batch_id": batch["id"]} if batch else {}),
                 "analysis_id": "analysis-1", "decision": decision, **overrides})


def test_nonempty_original_is_not_an_explicit_actual_result(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    original = deepcopy(project["cases"][0]["requirements"])
    with pytest.raises(RdError, match="澄清") as error:
        confirm(store, project)
    assert error.value.status == 422
    saved = store.get_project("owner", project["id"])["cases"][0]
    assert saved["requirements"] == original
    assert saved["requirement_baselines"] == []


def test_manual_command_cannot_bypass_clarification(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    original = deepcopy(project["cases"][0]["requirements"])
    with pytest.raises(RdError, match="澄清") as error:
        decide(store, project, 0, "manual", analysis_id=None, actual_value="0.35 MPa")
    assert error.value.status == 422
    assert store.get_project("owner", project["id"])["cases"][0]["requirements"] == original


def test_reject_has_no_actual_value_and_does_not_close_nonempty_requirement(tmp_path):
    store = new_store(tmp_path)
    project = review_project(store)
    project = decide(store, project, 1, "accept")
    project = decide(store, project, 0, "reject", reason="需核实客户工况")
    row = project["cases"][0]["requirements"][0]
    assert row["content"] == "0.3 MPa"
    assert row["review"]["actual_value"] is None
    with pytest.raises(RdError, match="澄清"):
        confirm(store, project)


def test_replacing_accept_with_reject_revokes_actual_value_but_preserves_history(tmp_path):
    store = new_store(tmp_path)
    project = review_project(store)
    project = decide(store, project, 1, "accept")
    project = decide(store, project, 0, "accept")
    project = decide(store, project, 0, "reject", reason="需重新核实")
    row = project["cases"][0]["requirements"][0]
    assert row["content"] == "0.4 MPa"
    assert row["review"]["actual_value"] is None
    assert [review["decision"] for review in row["review_history"]] == ["accept", "reject"]
    assert row["review_history"][0]["actual_value"] == "0.4 MPa"
    with pytest.raises(RdError, match="澄清"):
        confirm(store, project)


def test_review_is_explicit_source_versioned_and_does_not_reset_other_rows(tmp_path):
    store = new_store(tmp_path)
    project = review_project(store)
    case = project["cases"][0]
    # Verified matches are now ready for unified confirmation; old explicit
    # decisions remain auditable and must still respect revision/source checks.
    assert [store.records.explicit_requirement_result(case, row) for row in case["requirements"]] == ["0.4 MPa", "42°C"]
    assert [row["content"] for row in case["requirements"]] == ["0.3 MPa", "待澄清"]
    assert all("review" not in row for row in case["requirements"])
    with pytest.raises(RdError):
        decide(store, project, 0, "accept", actual_value="999 MPa")
    project = decide(store, project, 0, "accept")
    case = project["cases"][0]
    first = case["requirements"][0]
    assert first["content"] == "0.4 MPa" and first["review"]["actor"] == "owner"
    assert first["source_ids"] == [s["id"] for s in case["sources"]]
    assert case["source_analysis"]["requirements"][0]["content"] == "0.3 MPa"
    with pytest.raises(RdError, match="原因"):
        decide(store, project, 1, "reject")
    project = decide(store, project, 1, "reject", reason="工况未确定，请核实")
    assert project["cases"][0]["requirements"][1]["content"] == "待澄清"
    with pytest.raises(RdError, match="澄清"):
        confirm(store, project)
    project = clarify_requirement(store, project, 1, "45°C")
    case = confirm(store, project)["cases"][0]
    assert case["stage"] == "selection" and case["decisions"] == []
    fixed = case["requirement_baselines"][0]["items"]
    assert fixed[0]["review"] == first["review"]
    assert [r["decision"] for r in fixed[1]["review_history"]] == ["reject"]
    assert fixed[1]["review_history"][0]["actual_value"] is None
    assert case["clarifications"][-1]["adoption"]["requirement_content"] == "45°C"
    with pytest.raises(RdError):
        decide(store, store.get_project("owner", project["id"]), 1, "accept")


def test_rejects_stale_revision_stale_analysis_and_replaced_sources(tmp_path):
    store = new_store(tmp_path)
    project = review_project(store)
    for overrides in ({"analysis_id": "other-analysis"}, {"requirement_revision": 0}, {"requirement_revision": True}):
        with pytest.raises(RdError) as error:
            decide(store, project, 0, "accept", **overrides)
        assert error.value.status == 409
    project = store.add_source("owner", project["id"], project["cases"][0]["id"], project["version"],
                               "new-spec", "spec", "新规范.txt", b"new reference")
    with pytest.raises(RdError):
        decide(store, project, 0, "accept")
    with pytest.raises(RdError):
        confirm(store, project)


def test_ordinary_requirement_without_analysis_can_use_adopted_clarification(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    project = clarify_requirement(store, project, 0, "手工核实值")
    assert "review" not in project["cases"][0]["requirements"][0]
    assert confirm(store, project)["cases"][0]["stage"] == "selection"


def test_second_clarification_adoption_preserves_current_spec_batch_and_other_rows(tmp_path):
    store = new_store(tmp_path)
    project = decide(store, review_project(store), 1, "accept")
    other = deepcopy(project["cases"][0]["requirements"][1])
    project = clarify_requirement(store, project, 0, "0.35 MPa")
    first = deepcopy(project["cases"][0]["clarifications"][-1])
    project = clarify_requirement(store, project, 0, "0.36 MPa")
    case = project["cases"][0]
    row = case["requirements"][0]
    assert case["clarifications"][0] == first
    assert case["requirements"][1] == other
    assert case["clarifications"][-1]["adoption"].get("recommendation_batch_id") == "spec-batch-1"
    assert store.records.explicit_requirement_result(case, row) == "0.36 MPa"
    assert [entry["content"] for entry in row["history"][-2:]] == ["0.35 MPa", "0.36 MPa"]
    assert confirm(store, project)["cases"][0]["requirement_baselines"][0]["items"][0]["content"] == "0.36 MPa"


@pytest.mark.parametrize("change", ["history", "answer_source"])
def test_second_clarification_cannot_inherit_batch_from_invalid_previous_adoption(tmp_path, change):
    store = new_store(tmp_path)
    project = decide(store, review_project(store), 1, "accept")
    project = clarify_requirement(store, project, 0, "0.35 MPa")
    with store._connection() as db:
        raw = store._load(db, project["id"], "owner")
        case = raw["cases"][0]
        if change == "history":
            case["requirements"][0]["history"][-1].pop("clarification_id")
        else:
            case["clarifications"][0]["answer_source_snapshots"][0]["sha256"] = "changed"
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    project = clarify_requirement(store, store.get_project("owner", project["id"]), 0, "0.36 MPa")
    case = project["cases"][0]
    assert not case["clarifications"][-1]["adoption"].get("recommendation_batch_id")
    assert store.records.explicit_requirement_result(case, case["requirements"][0]) is None
    with pytest.raises(RdError, match="建议|澄清"):
        confirm(store, project)


def test_reviewing_one_row_preserves_an_answer_for_another_and_never_adopts_it(tmp_path):
    store = new_store(tmp_path)
    project = review_project(store)
    case = project["cases"][0]
    sid, rid = case["sources"][0]["id"], case["requirements"][1]["id"]
    project = issue(store, project, "open_clarification", {"requirement_id": rid, "source_ids": [sid], "question": "温度工况？"})
    cid = project["cases"][0]["clarifications"][0]["id"]
    project = issue(store, project, "answer_clarification", {"clarification_id": cid, "source_ids": [sid], "answer": "45°C"})
    project = decide(store, project, 0, "reject", reason="保留原值")
    case = project["cases"][0]
    answer = case["clarifications"][0]
    assert answer["status"] == "answered" and answer["input_revision"] == case["input_revision"]
    with pytest.raises(RdError, match="必需澄清"):
        confirm(store, project)
    project = issue(store, project, "adopt_clarification", {"clarification_id": cid, "requirement_content": "45°C"})
    # The adopted clarification itself now resolves the independent batch item.
    assert project["cases"][0]["requirements"][1]["content"] == "45°C"
    assert project["cases"][0]["clarifications"][0]["adoption"]["recommendation_batch_id"] == "spec-batch-1"
    with pytest.raises(RdError, match="澄清"):
        confirm(store, project)
    project = clarify_requirement(store, project, 0)
    assert confirm(store, project)["cases"][0]["requirement_baselines"][0]["items"][0]["content"] == "0.3 MPa"


@pytest.mark.parametrize("content", ["防水等级：待澄清。", "防水等级: 待补充；", "待确认。", "待确认（客户未反馈）", "防水等级：待澄清 (客户未反馈)。"])
def test_rejecting_labelled_placeholder_still_requires_an_actual_result(tmp_path, content):
    store = new_store(tmp_path)
    project = requirements_project(store)
    tech = project["cases"][0]["sources"][0]
    project = proposed(store, project, [{"title": "防水等级", "content": content, "source_ids": [tech["id"]],
        "evidence": [{"source_id": tech["id"], "quote": content}]}])
    project = spec_batch(store, project, {"压力": "0.3 MPa", "防水等级": "IP68"})
    project = decide(store, project, 0, "accept")
    project = decide(store, project, 1, "reject", reason="不适用于当前工况")
    assert project["cases"][0]["requirements"][1]["content"] == content
    with pytest.raises(RdError, match="完成需求澄清"):
        confirm(store, project)
    assert not store.get_project("owner", project["id"])["cases"][0]["requirement_baselines"]
    project = clarify_requirement(store, project, 1, "防水等级：IP67。")
    assert confirm(store, project)["cases"][0]["stage"] == "selection"


def test_explanatory_body_with_clarification_words_is_not_a_placeholder(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    value = "防水等级：IP67，待澄清事项采用单独记录管理。"
    project = clarify_requirement(store, project, 0, value)
    assert confirm(store, project)["cases"][0]["requirement_baselines"][0]["items"][0]["content"] == value


def legacy_self_recommendation(store):
    project = requirements_project(store)
    tech = project["cases"][0]["sources"][0]
    return proposed(store, project, [{"title": "压力", "content": "0.3 MPa", "source_ids": [tech["id"]],
        "evidence": [{"source_id": tech["id"], "quote": "0.3 MPa"}],
        "recommendation": {"text": "请核对所引条款的适用条件", "proposed_value": "0.3 MPa",
                           "evidence": [{"source_id": tech["id"], "quote": "0.3 MPa"}]}}])


def test_source_extraction_recommendation_does_not_create_a_spec_review_gate(tmp_path):
    store = new_store(tmp_path)
    project = legacy_self_recommendation(store)
    original = deepcopy(project["cases"][0]["requirements"])
    analysis = deepcopy(project["cases"][0]["source_analysis"])
    with pytest.raises(RdError, match="澄清"):
        confirm(store, project)
    case = store.get_project("owner", project["id"])["cases"][0]
    assert store.records.explicit_requirement_result(case, case["requirements"][0]) is None
    assert case["requirements"] == original
    assert case["source_analysis"] == analysis


@pytest.mark.parametrize("decision", ["accept", "reject"])
def test_source_extraction_recommendation_cannot_be_accepted_or_rejected_as_spec(tmp_path, decision):
    store = new_store(tmp_path)
    project = legacy_self_recommendation(store)
    with pytest.raises(RdError, match="规范建议批次"):
        decide(store, project, 0, decision, reason="保留原值")
    assert store.get_project("owner", project["id"])["cases"][0]["requirements"] == project["cases"][0]["requirements"]


def test_clarification_result_does_not_copy_source_extraction_recommendation(tmp_path):
    store = new_store(tmp_path)
    project = legacy_self_recommendation(store)
    project = clarify_requirement(store, project, 0, "0.35 MPa")
    row = project["cases"][0]["requirements"][0]
    assert row["content"] == "0.35 MPa"
    assert "review" not in row and not row.get("review_history")
    assert confirm(store, project)["cases"][0]["stage"] == "selection"


def test_legacy_adopted_value_and_review_history_survive_without_a_spec_batch(tmp_path):
    from service.rd_platform.lifecycle import digest
    store = new_store(tmp_path)
    project = legacy_self_recommendation(store)
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        case = raw["cases"][0]
        row = case["requirements"][0]
        row["content"] = "0.35 MPa"
        row["review"] = {"decision": "accept", "analysis_id": "analysis-1", "actual_value": "0.35 MPa",
                         "requirement_revision": row["revision"], "actor": "owner"}
        row["review_history"] = [deepcopy(row["review"])]
        case["source_analysis_history"] = [deepcopy(case["source_analysis"])]
        case["source_analysis"]["status"] = "stale"
        expected_row = deepcopy(row)
        expected_history = deepcopy(case["source_analysis_history"])
        fixed = {"input_revision": case["input_revision"], "items": deepcopy(case["requirements"]),
                 "source_refs": store.records._sources(case, row["source_ids"]), "scope": "历史确认需求"}
        case["requirement_baselines"] = [{"id": "historical-baseline", "revision": 1, **fixed,
            "digest": digest(fixed), "status": "current", "actor": "owner", "created_at": "2026-11-05T10:00:00"}]
        case["business_lifecycle"]["current_requirement_baseline_id"] = "historical-baseline"
        case["stage"] = "selection"
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    project = store.get_project("owner", project["id"])
    case = project["cases"][0]
    assert case["requirements"][0] == expected_row
    assert case["requirement_baselines"][0]["items"][0] == expected_row
    assert case["source_analysis_history"] == expected_history
    with store._connection() as db:
        internal = store._load(db, project["id"], "owner")["cases"][0]
    assert store.lifecycle.current_baseline(internal)["items"][0] == expected_row


def test_answered_clarification_has_no_actual_result_until_explicit_adoption(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    row = project["cases"][0]["requirements"][0]
    project = issue(store, project, "open_clarification", {"requirement_id": row["id"],
        "source_ids": row["source_ids"], "question": "确认压力"})
    cid = project["cases"][0]["clarifications"][-1]["id"]
    project = issue(store, project, "answer_clarification", {"clarification_id": cid,
        "source_ids": row["source_ids"], "answer": "0.35 MPa"})
    case = project["cases"][0]
    assert case["requirements"][0]["content"] == "0.3 MPa"
    assert store.records.explicit_requirement_result(case, case["requirements"][0]) is None
    with pytest.raises(RdError, match="必需澄清"):
        confirm(store, project)
    project = issue(store, project, "adopt_clarification", {"clarification_id": cid, "requirement_content": "0.35 MPa"})
    case = project["cases"][0]
    assert store.records.explicit_requirement_result(case, case["requirements"][0]) == "0.35 MPa"
    assert confirm(store, project)["cases"][0]["stage"] == "selection"


@pytest.mark.parametrize("change", ["content", "revision", "history", "answer_source", "legacy_manual"])
def test_explicit_result_cannot_be_reused_after_revision_or_evidence_change(tmp_path, change):
    store = new_store(tmp_path)
    project = clarify_requirement(store, requirements_project(store))
    with store._connection() as db:
        raw = store._load(db, project["id"], "owner")
        case = raw["cases"][0]
        row = case["requirements"][0]
        if change == "content":
            row["content"] = "0.4 MPa"
        elif change == "revision":
            row["revision"] += 1
        elif change == "history":
            row["history"][-1].pop("clarification_id")
        elif change == "answer_source":
            case["clarifications"][0]["answer_source_snapshots"][0]["sha256"] = "wrong"
        else:
            case["clarifications"] = []
            row["review"] = {"decision": "manual", "actual_value": row["content"], "requirement_revision": row["revision"]}
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    project = store.get_project("owner", project["id"])
    case = project["cases"][0]
    assert store.records.explicit_requirement_result(case, case["requirements"][0]) is None
    with pytest.raises(RdError, match="澄清"):
        confirm(store, project)


def test_new_source_requires_clarification_review_without_a_spec_batch(tmp_path):
    store = new_store(tmp_path)
    project = clarify_requirement(store, requirements_project(store))
    project = store.add_source("owner", project["id"], project["cases"][0]["id"], project["version"],
        "new-reference", "reference", "工况补充.txt", b"new conditions")
    case = project["cases"][0]
    assert store.records.explicit_requirement_result(case, case["requirements"][0]) is None
    with pytest.raises(RdError, match="澄清"):
        confirm(store, project)


def test_legacy_clarification_answer_from_reference_is_stale_when_tech_is_replaced(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    project = store.add_source("owner", project["id"], project["cases"][0]["id"], project["version"],
        "answer-reference", "reference", "客户答复.txt", b"confirmed pressure")
    case = project["cases"][0]
    row, answer_source = case["requirements"][0], case["sources"][-1]
    project = issue(store, project, "open_clarification", {"requirement_id": row["id"],
        "source_ids": row["source_ids"], "question": "确认适用压力"})
    clarification_id = project["cases"][0]["clarifications"][-1]["id"]
    project = issue(store, project, "answer_clarification", {"clarification_id": clarification_id,
        "source_ids": [answer_source["id"]], "answer": "0.35 MPa"})
    project = issue(store, project, "adopt_clarification", {"clarification_id": clarification_id,
        "requirement_content": "0.35 MPa"})
    with store._connection() as db:
        raw = store._load(db, project["id"], "owner")
        raw["cases"][0]["clarifications"][-1]["adoption"].pop("source_hashes")
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    project = store.get_project("owner", project["id"])
    case = project["cases"][0]
    assert store.records.explicit_requirement_result(case, case["requirements"][0]) == "0.35 MPa"
    project = store.add_source("owner", project["id"], case["id"], project["version"],
        "replacement-tech", "tech", "新版需求.txt", b"changed conditions")
    case = project["cases"][0]
    assert answer_source["id"] in {source["id"] for source in store._active_sources(case)}
    assert store.records.explicit_requirement_result(case, case["requirements"][0]) is None
    with pytest.raises(RdError):
        confirm(store, project)


def test_ordinary_content_edit_does_not_create_an_actual_result(tmp_path):
    store = new_store(tmp_path)
    project = clarify_requirement(store, requirements_project(store))
    row = project["cases"][0]["requirements"][0]
    project = issue(store, project, "save_requirement", {"id": row["id"], "title": row["title"],
        "content": "0.4 MPa", "source_ids": row["source_ids"]})
    with pytest.raises(RdError, match="澄清"):
        confirm(store, project)
    assert project["cases"][0]["requirements"][0]["content"] == "0.4 MPa"


def test_legacy_stage_gate_retains_historical_nonempty_value_semantics(tmp_path):
    store = new_store(tmp_path)
    case = requirements_project(store)["cases"][0]
    case["business_lifecycle"]["policy_version"] = "legacy_v1"
    store.records.check_requirement_reviews(case)


def legacy_review_project(store):
    project = review_project(store)
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        case = raw["cases"][0]
        case["business_lifecycle"]["policy_version"] = "legacy_v1"
        case["stage"] = "requirements"
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    return store.get_project("owner", project["id"])


def test_legacy_unified_stage_confirmation_materializes_verified_spec_values(tmp_path):
    store = new_store(tmp_path)
    project = legacy_review_project(store)
    case = project["cases"][0]
    original = deepcopy(case["source_analysis"]["requirements"])
    project = issue(store, project, "advance_stage", {"stage": "requirements", "verdict": "approved",
        "rationale": "核对规范后统一确认", "source_ids": [source["id"] for source in case["sources"]]})
    case = project["cases"][0]
    assert case["stage"] == "selection"
    assert [row["content"] for row in case["requirements"]] == ["0.4 MPa", "42°C"]
    assert all(row["specification_result"]["actual_value_source"] == "specification" for row in case["requirements"])
    assert all("review" not in row for row in case["requirements"])
    assert case["source_analysis"]["requirements"] == original
    assert [store.records.explicit_requirement_result(case, row) for row in case["requirements"]] == ["0.4 MPa", "42°C"]


def test_legacy_explicit_rejection_is_not_replaced_by_an_automatic_match(tmp_path):
    store = new_store(tmp_path)
    project = decide(store, legacy_review_project(store), 0, "reject", reason="适用条件需澄清")
    case = project["cases"][0]
    with pytest.raises(RdError, match="尚未处理"):
        issue(store, project, "advance_stage", {"stage": "requirements", "verdict": "approved",
            "rationale": "确认", "source_ids": [source["id"] for source in case["sources"]]})
    saved = store.get_project("owner", project["id"])["cases"][0]
    assert saved["stage"] == "requirements"
    assert saved["requirements"] == case["requirements"]
    assert all("specification_result" not in row for row in saved["requirements"])


@pytest.mark.parametrize("content", ["--", "待确认", "压力：待澄清。"])
def test_clarification_placeholder_cannot_be_confirmed_as_an_actual_value(tmp_path, content):
    store = new_store(tmp_path)
    project = clarify_requirement(store, requirements_project(store), content=content)
    case = project["cases"][0]
    assert store.records.explicit_requirement_result(case, case["requirements"][0]) is None
    with pytest.raises(RdError, match="澄清"):
        confirm(store, project)
