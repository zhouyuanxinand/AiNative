"""HTTP first-scenario acceptance; real model generation has separate evidence."""
from test_http import make_client, create


CONTEXT = {"product_type": "liquid_cooling_pipeline", "product_domain": "military", "development_process": "改型II",
           "cover_phase": "S", "product_series": "YLZJ", "organization_scope": "non_central_research"}


def command(client, project, name, *, key=None, expected_status=200, **data):
    if project["cases"] and name != "create_case":
        data.setdefault("case_id", project["cases"][0]["id"])
    response = client.post(f"/api/rd/projects/{project['id']}/commands",
        json={"expected_version": project["version"], "command": name, "data": data},
        headers={"Idempotency-Key": key or f"http-v2-{project['version']}-{name}"})
    assert response.status_code == expected_status, response.text
    return response.json()


def selected(client, route, product_type="liquid_cooling_pipeline"):
    client.app.state.rd_store.local_review_enabled = True
    project = command(client, create(client), "create_case", scenario_id="taskbook", title="HTTP v2首链")
    project = command(client, project, "save_context", context={**CONTEXT, "product_type": product_type,
        "development_process": "全新" if route == "new" else "改型II"})
    cid = project["cases"][0]["id"]
    for role in ("tech", "spec"):
        response = client.post(f"/api/rd/projects/{project['id']}/cases/{cid}/sources", data={"expected_version": project["version"], "role": role},
            files={"file": (role + ".txt", "工作压力：0.3MPa。".encode())}, headers={"Idempotency-Key": "source-" + role})
        assert response.status_code == 200, response.text
        project = response.json()
    sid = project["cases"][0]["sources"][0]["id"]
    project = command(client, project, "save_requirement", title="工作压力", content="工作压力：0.3MPa。", source_ids=[sid])
    project = command(client, project, "confirm_requirements", expected_input_revision=project["cases"][0]["input_revision"], scope="当前原文条目", source_ids=[sid])
    for axis, kind, value in (("product", "product", route), ("composition", "document", "direct")):
        project = command(client, project, "save_comparison", kind=kind, title="HTTP逐项比较", source_ids=[sid], rows=[{
            "requirement_id": project["cases"][0]["requirements"][0]["id"], "assessment": "match" if route == "direct" else "unknown",
            "candidate_value": "工作压力：0.3MPa。" if route == "direct" else "", "reason": "按上传原文核对；未知不判符合", "source_ids": [sid]}])
        project = command(client, project, "record_route_decision", axis=axis, value=value, rationale="按明确范围办理", source_ids=[sid], comparison_id=project["cases"][0]["comparisons"][-1]["id"])
    project = command(client, project, "prepare_selection_review", expected_input_revision=project["cases"][0]["input_revision"])
    bundle = project["cases"][0]["review_bundles"][-1]
    return command(client, project, "record_selection_decision", bundle_id=bundle["id"], bundle_digest=bundle["digest"], verdict="approved", scope="本地验证", rationale="负责人核对固定报告，非电子审签")


def activate(client, project):
    return command(client, project, "authorize_rd_start", selection_decision_id=project["cases"][0]["business_lifecycle"]["current_selection_decision_id"], scope="本地策划", rationale="承接当前差异")


def test_direct_http_route_finishes_selection_without_rd_workpackage(tmp_path):
    client = make_client(tmp_path)
    project = selected(client, "direct")
    case = project["cases"][0]
    assert case["stage"] == "delivery" and case["workpackages"] == []
    assert case["business_lifecycle"]["rd_project_code"] is None
    command(client, project, "pull_workpackage", definition_id="taskbook", expected_status=422)
    assert case["review_bundles"][-1]["report"]["statistics"]["matches"] == 1


def test_modification_http_replays_submission_and_fences_cancelled_result(tmp_path):
    client = make_client(tmp_path)
    project = activate(client, selected(client, "modification"))
    project = command(client, project, "adopt_taskbook_flow", workflow_id="taskbook-modification-v1", workflow_version="1", scope="改型任务书", rationale="固定原模板与当前输入")
    project = command(client, project, "pull_workpackage", definition_id="taskbook")
    wid = project["cases"][0]["workpackages"][-1]["id"]
    before = project
    submitted = command(client, before, "submit_workpackage", key="lost-submit-response", workpackage_id=wid)
    assert command(client, before, "submit_workpackage", key="lost-submit-response", workpackage_id=wid) == submitted
    package = submitted["cases"][0]["workpackages"][-1]
    assert package["stage"] == "planning" and package["definition_version"] == "2"
    store = client.app.state.rd_store
    claim = store.claim_node()
    current = client.get(f"/api/rd/projects/{project['id']}").json()
    cancelled = command(client, current, "cancel_workpackage", workpackage_id=wid)
    assert store.complete_node(claim, {"status": "completed", "result": {}, "artifacts": []}) is False
    assert cancelled["cases"][0]["workpackages"][-1]["status"] == "cancelled"
    assert cancelled["cases"][0]["stage"] == "planning"


def test_new_http_route_missing_assets_does_not_choose_another_template(tmp_path):
    client = make_client(tmp_path)
    project = activate(client, selected(client, "new", product_type="unregistered_liquid_variant"))
    command(client, project, "adopt_taskbook_flow", workflow_id="taskbook-new-v1", workflow_version="1", scope="新产品任务书", rationale="等待目标受控资产", expected_status=422)
    current = client.get(f"/api/rd/projects/{project['id']}").json()["cases"][0]
    assert current["taskbook_binding"] is None and current["workpackages"] == []
    assert current["context"]["product_type"] == "unregistered_liquid_variant"
    assert current["review_bundles"][-1]["report"]["statistics"]["unknown"] == 1
