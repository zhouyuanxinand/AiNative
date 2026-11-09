"""A fixed report decision and an owner activation remain separate facts."""
import json

import pytest

from service.rd_platform.store import Store
from test_requirement_confirmation import requirements_project, confirm, clarify_requirement
from test_store import issue, fixture_comparison


CONTEXT = {"product_type": "liquid_cooling_pipeline", "product_domain": "military", "development_process": "改型II", "cover_phase": "S", "product_series": "YLZJ", "organization_scope": "non_central_research"}


def local_store(tmp_path):
    return Store(tmp_path / "rd.sqlite3", tmp_path / "assets", local_review_enabled=True)


def selection_project(store, route="modification"):
    project = confirm(store, clarify_requirement(store, requirements_project(store, CONTEXT)))
    sid = project["cases"][0]["sources"][0]["id"]
    for axis, value in (("product", route), ("composition", "direct")):
        project, comparison_id = fixture_comparison(store, project, axis)
        project = issue(store, project, "record_route_decision", {"axis": axis, "value": value, "rationale": "人工核对", "source_ids": [sid], "comparison_id": comparison_id})
    return project


def prepare(store, project):
    return issue(store, project, "prepare_selection_review", {"expected_input_revision": project["cases"][0]["input_revision"]})


def decide(store, project, verdict="approved"):
    bundle = project["cases"][0]["review_bundles"][-1]
    return issue(store, project, "record_selection_decision", {"bundle_id": bundle["id"], "bundle_digest": bundle["digest"], "verdict": verdict, "scope": "当前固定选型报告", "rationale": "项目负责人核对原始依据"})


def activate(store, project):
    return issue(store, project, "authorize_rd_start", {"selection_decision_id": project["cases"][0]["business_lifecycle"]["current_selection_decision_id"], "scope": "当前改型策划", "rationale": "按已批准选型差异启动"})


def activated_project(store):
    return activate(store, decide(store, prepare(store, selection_project(store))))


def test_route_report_decision_and_start_do_not_collapse_to_one_approval(tmp_path):
    store = local_store(tmp_path)
    project = selection_project(store)
    assert project["cases"][0]["business_lifecycle"]["rd_activation_state"] == "not_started"
    project = prepare(store, project)
    bundle = project["cases"][0]["review_bundles"][-1]
    assert bundle["report"]["statistics"] == {"matches": 1, "total": 1, "partial": 0, "gap": 0, "unknown": 0, "match_ratio": 1.0}
    assert bundle["report"]["rows"][0]["candidate_value"] == "0.3 MPa"
    project = decide(store, project)
    case = project["cases"][0]
    assert case["stage"] == "selection" and case["business_lifecycle"]["rd_project_code"] is None
    decision = case["decisions"][-1]
    assert decision["electronic_signature"] is False and decision["review_mode"] == "local_review"
    assert decision["bundle_digest"] == bundle["digest"]
    project = activate(store, project)
    case = project["cases"][0]
    assert case["stage"] == "planning" and case["business_lifecycle"]["rd_activation_state"] == "active"
    assert case["business_lifecycle"]["rd_project_code"].startswith("RD-")
    assert case["rd_activations"][0]["selection_decision_id"] == decision["id"]
    assert case["workpackages"] == []


def test_direct_selection_enters_delivery_without_rd_identity_or_packages(tmp_path):
    store = local_store(tmp_path)
    project = decide(store, prepare(store, selection_project(store, "direct")))
    case = project["cases"][0]
    assert case["stage"] == "delivery"
    assert case["business_lifecycle"]["rd_project_code"] is None and not case["workpackages"]
    with pytest.raises(Exception) as error:
        activate(store, project)
    assert error.value.status == 422


def test_changed_report_or_route_prevents_start_with_old_approval(tmp_path):
    store = local_store(tmp_path)
    approved = decide(store, prepare(store, selection_project(store)))
    replaced = prepare(store, approved)
    with pytest.raises(Exception) as error:
        activate(store, replaced)
    assert error.value.status == 409
    approved = decide(store, replaced)
    case = approved["cases"][0]
    changed = issue(store, approved, "record_route_decision", {"axis": "product", "value": "new", "rationale": "重新核对路线", "source_ids": [case["sources"][0]["id"]], "comparison_id": case["product_route"]["comparison_id"]})
    with pytest.raises(Exception) as error:
        activate(store, changed)
    assert error.value.status == 409
    assert changed["cases"][0]["decisions"][-2]["invalidated_reason"]


def test_rejected_selection_can_form_new_report_but_cannot_start(tmp_path):
    store = local_store(tmp_path)
    project = decide(store, prepare(store, selection_project(store)), "rejected")
    with pytest.raises(Exception) as error:
        activate(store, project)
    assert error.value.status == 409
    assert prepare(store, project)["cases"][0]["review_bundles"][-1]["status"] == "submitted"


def test_default_store_does_not_accept_local_or_forged_formal_decision(tmp_path):
    store = Store(tmp_path / "rd.sqlite3", tmp_path / "assets")
    project = prepare(store, selection_project(store))
    with pytest.raises(Exception) as error:
        decide(store, project)
    assert error.value.status == 403
    bundle = project["cases"][0]["review_bundles"][-1]
    with pytest.raises(Exception) as error:
        issue(store, project, "record_selection_decision", {"bundle_id": bundle["id"], "bundle_digest": bundle["digest"], "verdict": "approved", "scope": "伪造正式签署", "rationale": "本人是管理员", "review_mode": "formal_review", "electronic_signature": True})
    assert error.value.status in {403, 422}


def test_project_member_cannot_make_owner_decision(tmp_path):
    store = local_store(tmp_path)
    project = prepare(store, selection_project(store))
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        raw["members"] = ["member"]
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    bundle = project["cases"][0]["review_bundles"][-1]
    with pytest.raises(Exception) as error:
        store.command("member", project["id"], project["version"], "member-decision", "record_selection_decision", {"case_id": project["cases"][0]["id"], "bundle_id": bundle["id"], "bundle_digest": bundle["digest"], "verdict": "approved", "scope": "无资格", "rationale": "成员可写项目"})
    assert error.value.status == 403


def test_wrong_digest_is_rejected_and_lost_start_response_replays_once(tmp_path):
    store = local_store(tmp_path)
    project = prepare(store, selection_project(store))
    bundle = project["cases"][0]["review_bundles"][-1]
    with pytest.raises(Exception) as error:
        issue(store, project, "record_selection_decision", {"bundle_id": bundle["id"], "bundle_digest": "other", "verdict": "approved", "scope": "范围", "rationale": "依据"})
    assert error.value.status == 409
    approved = decide(store, project)
    first = activate(store, approved)
    assert activate(store, approved) == first
    assert len(store.get_project("owner", project["id"])["cases"][0]["rd_activations"]) == 1


def test_owner_capability_is_project_scoped_read_projection(tmp_path):
    store = local_store(tmp_path)
    project = selection_project(store)
    assert project["cases"][0]["business_lifecycle"]["can_record_decision"] is True
    with store._connection() as db:
        raw = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
        raw["members"] = ["member"]
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(raw), project["id"]))
    assert store.get_project("member", project["id"])["cases"][0]["business_lifecycle"]["can_record_decision"] is False


def test_oa_mode_cannot_use_accidentally_enabled_local_review_store(tmp_path):
    from test_http import make_client
    from src.service.rd_platform.store import Store as HttpStore
    client = make_client(tmp_path, auth=True)
    client.app.state.rd_store = HttpStore(tmp_path / "rd.sqlite3", tmp_path / "assets", local_review_enabled=True)
    project = client.app.state.rd_store.create_project("owner", "OA项目")
    @client.app.middleware("http")
    async def identity(request, call_next):
        request.state.rd_actor = "owner"
        return await call_next(request)
    response = client.post(f"/api/rd/projects/{project['id']}/commands", json={"expected_version": project["version"], "command": "record_selection_decision", "data": {}}, headers={"Idempotency-Key": "oa-local-denied"})
    assert response.status_code == 403
