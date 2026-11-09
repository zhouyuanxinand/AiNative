"""Filename classification is advisory and cannot alter persisted case inputs."""
from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest

from jonhon_taskbook import llm_client
from test_batch_sources import http_case
from test_http import make_client
from test_store import issue


def endpoint(project):
    return f"/api/rd/projects/{project['id']}/cases/{project['cases'][0]['id']}/sources/classify"


def classify(client, project, names, **extra):
    return client.post(endpoint(project), json={"files": [{"id": str(index), "name": name} for index, name in enumerate(names)], **extra})


def model(monkeypatch, response, calls):
    monkeypatch.setattr(llm_client, "get_model_status", lambda *args: {"configured": True})
    @contextmanager
    def scope(provider, name, model_id):
        calls.append((provider, name, model_id))
        yield SimpleNamespace(model_id=model_id)
    monkeypatch.setattr(llm_client, "model_scope", scope)
    def chat(system, user, **kwargs):
        calls.append(json.loads(user))
        if isinstance(response, Exception):
            raise response
        return response
    monkeypatch.setattr(llm_client, "chat_json", chat)


def test_filename_rules_classify_clear_names_and_leave_ambiguous_names_unknown_without_writes(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    project = http_case(client)
    monkeypatch.setattr(llm_client, "chat_json", lambda *args, **kwargs: pytest.fail("rules must not request a model"))
    response = classify(client, project, ["ABC技术要求.docx", "产品规范.pdf", "参考手册.docx", "技术要求与产品规范.docx", "scan003.pdf"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert [item["role"] for item in result["items"]] == ["tech", "spec", "reference", "unknown", "unknown"]
    assert [item["id"] for item in result["items"]] == ["0", "1", "2", "3", "4"]
    assert all(item["reason"] for item in result["items"])
    assert result["warnings"] == []
    assert client.get(f"/api/rd/projects/{project['id']}").json() == project


def test_optional_model_only_sees_unknown_names_and_uses_explicit_selection(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    project = http_case(client)
    calls = []
    model(monkeypatch, {"items": [{"id": "1", "role": "spec", "reason": "文件名包含标准编号"}]}, calls)
    selected = {"provider": "vendor", "name": "actual-model", "id": "stable-model-id"}
    response = classify(client, project, ["需求.docx", "ABC001.pdf"], use_model=True, model_selection=selected)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [(item["role"], item["method"]) for item in items] == [("tech", "filename"), ("spec", "model")]
    assert calls[0] == ("vendor", "actual-model", "stable-model-id")
    assert calls[1]["files"] == [{"id": "1", "name": "ABC001.pdf"}]
    assert client.get(f"/api/rd/projects/{project['id']}").json() == project


@pytest.mark.parametrize('use_model', [False, True])
def test_requirement_document_names_are_classified_without_model(tmp_path, monkeypatch, use_model):
    client = make_client(tmp_path)
    project = http_case(client)
    monkeypatch.setattr(llm_client, 'get_model_status', lambda *a, **k: pytest.fail('explicit filenames need no model'))
    monkeypatch.setattr(llm_client, 'chat_json', lambda *a, **k: pytest.fail('explicit filenames need no model'))
    names = ['CY43技术要求（受控）.docx', 'YLZJ-469技术协议_V2.doc',
             '连接器沟通指导书（确认版）.pdf', 'ABC-123技术规格书20261105.docx']
    response = classify(client, project, names, use_model=use_model)
    assert response.status_code == 200, response.text
    result = response.json()
    assert [(item['id'], item['role'], item['method']) for item in result['items']] == [
        (str(index), 'tech', 'filename') for index in range(4)]
    assert result['warnings'] == []
    assert client.get(f"/api/rd/projects/{project['id']}").json() == project


@pytest.mark.parametrize('use_model', [False, True])
def test_specbook_names_are_requirements_without_model(tmp_path, monkeypatch, use_model):
    client = make_client(tmp_path)
    project = http_case(client)
    monkeypatch.setattr(llm_client, 'get_model_status', lambda *a, **k: pytest.fail('specbook filenames need no model'))
    monkeypatch.setattr(llm_client, 'chat_json', lambda *a, **k: pytest.fail('specbook filenames need no model'))
    names = ['xxx规格书.docx', 'YLZJ-BG-469液冷组件规格书(JONHON受控).doc',
             'CY43产品规格书_V2.pdf', '连接器技术规格书.docx', '产品规格.pdf', '液冷产品规范.doc']
    response = classify(client, project, names, use_model=use_model)
    assert response.status_code == 200, response.text
    result = response.json()
    assert [(item['id'], item['role'], item['method']) for item in result['items']] == [
        (str(index), role, 'filename') for index, role in enumerate(['tech', 'tech', 'tech', 'tech', 'spec', 'spec'])]
    assert result['warnings'] == []
    assert client.get(f"/api/rd/projects/{project['id']}").json() == project


def test_specbook_and_explicit_specification_in_same_name_stay_ambiguous(tmp_path):
    client = make_client(tmp_path)
    project = http_case(client)
    response = classify(client, project, ['产品规格书与产品规范.docx'])
    assert response.status_code == 200, response.text
    assert response.json()['items'][0]['role'] == 'unknown'
    assert client.get(f"/api/rd/projects/{project['id']}").json() == project


def test_model_uses_case_saved_selection_when_no_override_is_supplied(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    project = http_case(client)
    actor = client.get("/api/rd/session").json()["actor_id"]
    store = client.app.state.rd_store
    project = store.command(actor, project["id"], project["version"], "model", "save_context", {
        "case_id": project["cases"][0]["id"], "context": {},
        "model_selection": {"provider": "saved-vendor", "name": "saved-model", "id": "saved-id"}})
    calls = []
    model(monkeypatch, {"items": [{"id": "0", "role": "reference", "reason": "资料附件"}]}, calls)
    assert classify(client, project, ["scan.pdf"], use_model=True).status_code == 200
    assert calls[0] == ("saved-vendor", "saved-model", "saved-id")


@pytest.mark.parametrize("reply", [RuntimeError("transport failed"), {"items": [{"id": "forged", "role": "tech", "reason": "x"}]}, {"items": [{"id": "0", "role": "admin", "reason": "x"}]}, {"items": []}])
def test_model_failure_or_invalid_identity_preserves_unknown_and_warns(tmp_path, monkeypatch, reply):
    client = make_client(tmp_path)
    project = http_case(client)
    calls = []
    model(monkeypatch, reply, calls)
    response = classify(client, project, ["scan.pdf"], use_model=True)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["items"][0]["id"] == "0" and result["items"][0]["role"] == "unknown"
    assert result["warnings"]
    assert "transport failed" not in json.dumps(result)
    assert client.get(f"/api/rd/projects/{project['id']}").json() == project


def test_missing_model_credentials_leave_manual_classification_available(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    project = http_case(client)
    monkeypatch.setattr(llm_client, "get_model_status", lambda *args: {"configured": False})
    monkeypatch.setattr(llm_client, "chat_json", lambda *args, **kwargs: pytest.fail("no credentials"))
    response = classify(client, project, ["需求.docx", "scan.pdf"], use_model=True)
    assert response.status_code == 200
    assert [item["role"] for item in response.json()["items"]] == ["tech", "unknown"]
    assert response.json()["warnings"]


def test_classification_checks_project_case_access_and_same_origin(tmp_path):
    client = make_client(tmp_path)
    project = http_case(client)
    payload = {"files": [{"id": "a", "name": "需求.docx"}]}
    stranger = make_client(tmp_path)
    assert stranger.post(endpoint(project), json=payload).status_code == 404
    assert client.post(endpoint(project).replace(project["cases"][0]["id"], "other-case"), json=payload).status_code == 404
    assert client.post(endpoint(project), json=payload, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


@pytest.mark.parametrize("payload", [
    {"files": []}, {"files": [{"id": "same", "name": "a"}, {"id": "same", "name": "b"}]},
    {"files": [{"id": "a", "name": "a", "role": "tech"}]},
    {"files": [{"id": "a", "name": "a"}], "use_model": "true"},
    {"files": [{"id": "a", "name": "a"}], "model_selection": {"provider": "x", "name": "x", "id": "x", "api_key": "forged"}},
])
def test_classification_rejects_invalid_queue_or_client_credentials(tmp_path, payload):
    client = make_client(tmp_path)
    project = http_case(client)
    assert client.post(endpoint(project), json=payload).status_code == 422
