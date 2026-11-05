"""Source-faithful enhancement decisions are distinct from adoption and baseline confirmation."""
import json

import pytest

from service.rd_platform.store import RdError
from test_requirement_confirmation import requirements_project, confirm
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
    tech, spec = project["cases"][0]["sources"]
    rows = [{"title": title, "content": value, "source_ids": [tech["id"]], "evidence": [{"source_id": tech["id"], "quote": value}],
             "recommendation": {"text": "核对规范值", "proposed_value": recommended,
                                "evidence": [{"source_id": spec["id"], "quote": recommended}]}}
            for title, value, recommended in [("压力", "0.3 MPa", "0.4 MPa"), ("温度", "待澄清", "42°C")]]
    return proposed(store, project, rows)


def decide(store, project, index, decision, **overrides):
    row = project["cases"][0]["requirements"][index]
    return issue(store, project, "review_requirement", {"requirement_id": row["id"], "requirement_revision": row["revision"],
                 "analysis_id": "analysis-1", "decision": decision, **overrides})


def test_review_is_explicit_source_versioned_and_does_not_reset_other_rows(tmp_path):
    store = new_store(tmp_path)
    project = review_project(store)
    with pytest.raises(RdError, match="建议"):
        confirm(store, project)
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
    project = decide(store, project, 1, "manual", actual_value="45°C", reason="客户已澄清工况")
    case = confirm(store, project)["cases"][0]
    assert case["stage"] == "selection" and case["decisions"] == []
    fixed = case["requirement_baselines"][0]["items"]
    assert fixed[0]["review"] == first["review"]
    assert [r["decision"] for r in fixed[1]["review_history"]] == ["reject", "manual"]
    assert fixed[1]["review"]["actual_value"] == "45°C"
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


def test_ordinary_manual_requirement_without_analysis_needs_no_model_decision(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    project = decide(store, project, 0, "manual", analysis_id=None, actual_value="手工核实值")
    assert project["cases"][0]["requirements"][0]["review"]["recommendation"] is None
    assert confirm(store, project)["cases"][0]["stage"] == "selection"


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
    project = decide(store, project, 1, "manual", actual_value="45°C")
    assert confirm(store, project)["cases"][0]["requirement_baselines"][0]["items"][0]["content"] == "0.3 MPa"


@pytest.mark.parametrize("content", ["防水等级：待澄清。", "防水等级: 待补充；", "待确认。", "待确认（客户未反馈）", "防水等级：待澄清 (客户未反馈)。"])
def test_rejecting_labelled_placeholder_still_requires_an_actual_result(tmp_path, content):
    store = new_store(tmp_path)
    project = requirements_project(store)
    tech, spec = project["cases"][0]["sources"]
    project = proposed(store, project, [{"title": "防水等级", "content": content, "source_ids": [tech["id"]],
        "evidence": [{"source_id": tech["id"], "quote": content}],
        "recommendation": {"text": "核对防水等级", "proposed_value": "IP68", "evidence": [{"source_id": spec["id"], "quote": "IP68"}]}}])
    project = decide(store, project, 1, "reject", reason="不适用于当前工况")
    assert project["cases"][0]["requirements"][1]["content"] == content
    with pytest.raises(RdError, match="完成需求澄清"):
        confirm(store, project)
    assert not store.get_project("owner", project["id"])["cases"][0]["requirement_baselines"]
    project = decide(store, project, 1, "manual", actual_value="防水等级：IP67。", reason="客户已澄清")
    assert confirm(store, project)["cases"][0]["stage"] == "selection"


def test_explanatory_body_with_clarification_words_is_not_a_placeholder(tmp_path):
    store = new_store(tmp_path)
    project = requirements_project(store)
    value = "防水等级：IP67，待澄清事项采用单独记录管理。"
    project = decide(store, project, 0, "manual", analysis_id=None, actual_value=value)
    assert confirm(store, project)["cases"][0]["requirement_baselines"][0]["items"][0]["content"] == value
