"""Stable page references resolve authorized current facts, never client facts."""
import json

import pytest

from jonhon_taskbook import llm_client
from tests.rd_platform.test_http import make_client
from tests.rd_platform.test_source_analysis import command, setup_case


def ref(project, route_id="case.materials", **extra):
    return {"schema_version": 1, "route_id": route_id, "project_id": project["id"],
            "case_id": project["cases"][0]["id"], **extra}


def resolve(client, page_ref):
    return client.post("/api/rd/navigation/context", json=page_ref)


def test_catalog_exposes_only_structured_read_only_navigation(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/rd/navigation/catalog")
    assert response.status_code == 200
    catalog = response.json()
    routes = {item["route_id"]: item for item in catalog["routes"]}
    assert routes["case.requirements"]["path_template"] == "/projects/{project_id}/flows/{case_id}/requirements"
    assert routes["case.resume"]["scope"] == "case"
    assert routes["research.customers"]["path_template"] == "/research/customers"
    assert all(item["read_only"] for item in catalog["capabilities"])
    assert "http://" not in response.text and "https://" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_context_uses_current_saved_counts_and_preserves_business_records(tmp_path):
    client, project = setup_case(tmp_path)
    project = command(client, project, "save_requirement", title="工作压力", content="0.3 MPa",
                      source_ids=[project["cases"][0]["sources"][0]["id"]])
    project = command(client, project, "pull_workpackage", definition_id="input_check")
    wid = project["cases"][0]["workpackages"][0]["id"]
    store = client.app.state.rd_store
    with store._connection() as db:
        before = db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0]
    page_ref = ref(project, "case.execution", workpackage_id=wid)
    response = resolve(client, page_ref)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["page_ref"] == page_ref
    assert data["context"]["project_version"] == project["version"]
    assert data["context"]["input_revision"] == project["cases"][0]["input_revision"]
    assert data["context"]["stage"] == "input"
    assert data["context"]["counts"] == {"sources": 1, "active_sources": 1, "requirements": 1, "workpackages": 1}
    assert ref(project, "case.requirements") in data["navigation"]
    assert data["read_only"] is True
    assert str(tmp_path) not in response.text
    with store._connection() as db:
        assert db.execute("SELECT payload FROM projects WHERE id=?", (project["id"],)).fetchone()[0] == before


def test_project_and_platform_contexts_do_not_invent_case_context(tmp_path):
    client, project = setup_case(tmp_path)
    result = resolve(client, {"schema_version": 1, "route_id": "project", "project_id": project["id"]})
    assert result.status_code == 200
    assert result.json()["context"] == {"project_version": project["version"], "counts": {"cases": 1}}
    assert ref(project, "case.resume") in result.json()["navigation"]
    platform = resolve(client, {"schema_version": 1, "route_id": "work"})
    assert platform.status_code == 200
    assert platform.json()["context"] == {}
    assert all("project_id" not in item for item in platform.json()["navigation"])


@pytest.mark.parametrize("payload", [
    {"schema_version": 2, "route_id": "work"},
    {"schema_version": True, "route_id": "work"},
    {"schema_version": "1", "route_id": "work"},
    {"schema_version": 1, "route_id": "unknown"},
    {"schema_version": 1, "route_id": "work", "project_id": "p"},
    {"schema_version": 1, "route_id": "project", "case_id": "c"},
    {"schema_version": 1, "route_id": "case.requirements", "project_id": "p"},
    {"schema_version": 1, "route_id": "case.requirements", "project_id": "p", "case_id": "c", "workpackage_id": "w"},
    {"schema_version": 1, "route_id": "case.materials", "project_id": "../secret", "case_id": "c"},
    {"schema_version": 1, "route_id": "work", "stage": "approved"},
    {"schema_version": 1, "route_id": "work", "url": "https://example.invalid"},
])
def test_reference_rejects_unknown_routes_forged_facts_and_inconsistent_scope(tmp_path, payload):
    response = resolve(make_client(tmp_path), payload)
    assert response.status_code == 422, response.text


def test_context_cannot_cross_actor_project_case_or_workpackage_scope(tmp_path):
    client, project = setup_case(tmp_path)
    assert resolve(make_client(tmp_path), ref(project)).status_code == 404
    assert resolve(client, ref(project, case_id="missing")).status_code == 404
    assert resolve(client, ref(project, "case.execution", workpackage_id="missing")).status_code == 404
    other = client.post("/api/rd/projects", json={"title": "另一个项目"}).json()
    assert resolve(client, ref(project, project_id=other["id"])).status_code == 404
    project = command(client, project, "pull_workpackage", definition_id="input_check")
    wid = project["cases"][0]["workpackages"][0]["id"]
    created = client.post(f"/api/rd/projects/{project['id']}/commands",
        json={"expected_version": project["version"], "command": "create_case",
              "data": {"scenario_id": "taskbook", "title": "另一个流程"}},
        headers={"Idempotency-Key": "second-case"})
    assert created.status_code == 200, created.text
    project = created.json()
    assert resolve(client, ref(project, "case.execution", case_id=project["cases"][1]["id"],
                               workpackage_id=wid)).status_code == 404


def test_navigation_context_keeps_existing_auth_and_same_origin_boundary(tmp_path):
    client = make_client(tmp_path, auth=True)
    assert client.get("/api/rd/navigation/catalog").status_code == 401
    assert resolve(client, {"schema_version": 1, "route_id": "work"}).status_code == 401
    client = make_client(tmp_path, auth=False)
    assert client.post("/api/rd/navigation/context", json={"schema_version": 1, "route_id": "work"},
                       headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_assistant_reference_is_a_position_hint_and_part_of_request_identity(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    project = command(client, project, "save_context", context={}, model_selection={
        "provider": "smartvision", "name": "test-model", "id": "model-1"})
    calls = []
    monkeypatch.setattr(llm_client, "get_model_status", lambda *args: {"configured": True})
    def answer(system, user, **kwargs):
        calls.append(json.loads(user))
        return "请核对当前资料。"
    monkeypatch.setattr(llm_client, "chat", answer)
    url = f"/api/rd/projects/{project['id']}/cases/{project['cases'][0]['id']}/assistant"
    payload = {"message": "核对需求", "page_ref": ref(project)}
    first = client.post(url, json=payload, headers={"Idempotency-Key": "nav"})
    assert first.status_code == 200, first.text
    assert first.json()["navigation"] == {"target": "requirements", "page_ref": ref(project, "case.requirements")}
    assert calls[0]["case_summary"]["page_ref"] == ref(project)
    assert "不是业务依据" in calls[0]["case_summary"]["page_ref_scope"]
    assert client.post(url, json=payload, headers={"Idempotency-Key": "nav"}).json()["reply"] == first.json()["reply"]
    changed = {**payload, "page_ref": ref(project, "case.requirements")}
    assert client.post(url, json=changed, headers={"Idempotency-Key": "nav"}).status_code == 409
    assert len(calls) == 1
    assert client.get("/api/rd/projects/" + project["id"]).json()["version"] == project["version"]


def test_assistant_rejects_foreign_reference_before_model_or_message_write(tmp_path, monkeypatch):
    client, project = setup_case(tmp_path)
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: pytest.fail("unexpected model request"))
    url = f"/api/rd/projects/{project['id']}/cases/{project['cases'][0]['id']}/assistant"
    for page_ref in (ref(project, case_id="missing"), {"schema_version": 1, "route_id": "work"}):
        response = client.post(url, json={"message": "下一步", "page_ref": page_ref},
                               headers={"Idempotency-Key": "invalid"})
        assert response.status_code in {404, 422}
    assert client.get(url).json()["messages"] == []
