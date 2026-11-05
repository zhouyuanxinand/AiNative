from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.platform_auth import AuthSettings
from src.controller.rd_controller import router, RdRoute
from src.service.rd_platform.store import Store


def make_client(tmp_path, auth=False):
    app = FastAPI()
    app.state.config = SimpleNamespace(max_upload_bytes=1024, logs_dir=tmp_path / "logs")
    app.state.auth_settings = AuthSettings(enabled=auth)
    app.state.rd_store = Store(tmp_path / "rd.sqlite3", tmp_path / "assets")
    app.include_router(router)
    return TestClient(app)


def create(client):
    response = client.post("/api/rd/projects", json={"title": "ICTS研制", "context": {}})
    assert response.status_code == 200, response.text
    return response.json()


def test_oa_mode_requires_server_identity(tmp_path):
    client = make_client(tmp_path, auth=True)
    assert client.get("/api/rd/projects").status_code == 401
    assert client.post("/api/rd/projects", json={"title": "x", "actor": "wangxue"}).status_code in {401, 422}


def test_local_clients_have_separate_project_visibility(tmp_path):
    client = make_client(tmp_path)
    project = create(client)
    assert len(client.get("/api/rd/projects").json()["projects"]) == 1
    stranger = make_client(tmp_path)
    assert stranger.get("/api/rd/projects").json()["projects"] == []
    assert stranger.get("/api/rd/projects/" + project["id"]).status_code in {403, 404}


def test_create_case_requires_key_and_preserves_dual_routes(tmp_path):
    client = make_client(tmp_path)
    project = create(client)
    endpoint = "/api/rd/projects/" + project["id"] + "/commands"
    payload = {"expected_version": project["version"], "command": "create_case",
               "data": {"scenario_id": "taskbook", "title": "任务书案例"}}
    assert client.post(endpoint, json=payload).status_code == 400
    result = client.post(endpoint, json=payload, headers={"Idempotency-Key": "case1"})
    assert result.status_code == 200, result.text
    case = result.json()["cases"][0]
    assert case["stage"] == "input"
    assert case["product_route"] is None
    assert case["composition_route"] is None
    assert client.post(endpoint, json=payload, headers={"Idempotency-Key": "case1"}).json() == result.json()


def test_forged_workspace_manager_is_rejected(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/api/rd/workspace/session").json()["can_publish_resources"] is False
    assert client.get("/api/rd/workspace/resources").status_code == 403
    response = client.post("/api/rd/workspace/resources", json={"operation": "publish",
       "kind": "team", "name": "伪造权限", "can_manage": True},
       headers={"X-User": "wangxue"})
    assert response.status_code in {403, 422}


def test_cross_site_mutation_is_rejected(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/rd/projects", json={"title": "x"},
                           headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403


def test_examples_are_labelled_not_real_provider_results(tmp_path):
    response = make_client(tmp_path).get("/api/rd/contracts")
    assert response.status_code == 200
    assert response.json()["execution_mode"] == "contract_example"
    assert response.json()["connected"] is False


def test_project_create_http_replays_same_intent(tmp_path):
    client = make_client(tmp_path)
    headers = {"Idempotency-Key": "project-replay"}
    payload = {"title": "可重放项目"}
    first = client.post("/api/rd/projects", json=payload, headers=headers)
    replay = client.post("/api/rd/projects", json=payload, headers=headers)
    assert replay.json() == first.json()
    assert len(client.get("/api/rd/projects").json()["projects"]) == 1


def test_session_establishes_one_cookie_before_parallel_reads(tmp_path):
    client = make_client(tmp_path)
    result = client.get("/api/rd/session")
    assert result.status_code == 200
    actor = result.json()["actor_id"]
    assert actor.startswith("local:")
    original_cookie = client.cookies.get("jtb_rd_local_client")
    client.get("/api/rd/projects")
    client.get("/api/rd/catalog")
    assert client.cookies.get("jtb_rd_local_client") == original_cookie


def test_case_assistant_http_is_scoped_persistent_and_read_only(tmp_path):
    client = make_client(tmp_path)
    project = create(client)
    project = client.post("/api/rd/projects/" + project["id"] + "/commands",
        headers={"Idempotency-Key": "assistant-case"},
        json={"expected_version": project["version"], "command": "create_case",
              "data": {"scenario_id": "taskbook", "title": "只读助手案例"}}).json()
    case = project["cases"][0]
    url = f"/api/rd/projects/{project['id']}/cases/{case['id']}/assistant"
    assert client.get(url).status_code == 200
    payload = {"message": "当前该做什么", "topic": ""}
    reply = client.post(url, json=payload, headers={"Idempotency-Key": "question1"})
    assert reply.status_code == 200, reply.text
    assert reply.json()["reply"]["mode"] == "local_guidance"
    assert len(client.get(url).json()["messages"]) == 2
    assert client.get("/api/rd/projects/" + project["id"]).json()["version"] == project["version"]
    assert client.post(url, json=payload, headers={"Idempotency-Key": "question1"}).json()["reply"] == reply.json()["reply"]
    assert client.get(url.replace(case["id"], "unknown-case")).status_code == 404
