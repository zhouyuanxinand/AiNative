"""HTTP feedback records bind to trusted task state without generation or network calls."""
import importlib
import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jonhon_taskbook.template_registry import TemplateSelection

from src import pipeline_cli
from src.controller import taskbook_controller


def job():
    return {"status": "blocked", "error": "质量门禁未通过", "result": {
        "out": "D:/private/输出任务书.docx", "report": "D:/private/输出任务书.report.html", "delivery_status": "blocked",
        "meta": {"selected_product_type": "filter_connector", "selected_product_type_label": "滤波连接器",
            "product_domain": "military", "product_domain_label": "军品", "qa_ok": False,
            "original_filenames": {"tech": "原始技术要求.docx", "spec": "原始规格书.docx"},
            "llm_model_provider": "smartvision", "llm_model": "azure/gpt-5", "llm_model_id": "4771",
            "api_key": "TOP-SECRET", "base_url": "https://private.example", "inputs": {"tech": "tech.docx", "spec": "spec.docx", "tpl": "模板.docx"}}},
        "replay": {"selection": {"product_type": "filter_connector", "product_type_label": "滤波连接器", "product_domain": "military", "product_domain_label": "军品", "template_path": "D:/private/模板.docx"},
            "options": {"development_process": "全新", "cover_phase": "初样", "product_series": "J599L", "organization_scope": "central_research", "model_provider": "smartvision", "model_name": "azure/gpt-5", "model_id": "4771", "api_key": "TOP-SECRET"},
            "files": {"tech": {"name": "replay_tech.docx", "original_name": "备用技术要求.docx"}, "spec": {"name": "replay_spec.docx"}}}}


@pytest.fixture
def api(tmp_path, monkeypatch):
    controller = importlib.import_module("src.controller.feedback_controller")
    store = importlib.import_module("jonhon_taskbook.feedback_store").FeedbackStore(tmp_path / "feedback.sqlite3")
    monkeypatch.setattr(controller, "get_feedback_store", lambda: store)
    state = taskbook_controller._RuntimeState()
    state.output_dir = tmp_path / "outputs"
    state.output_dir.mkdir()
    state.jobs["123456789a"] = job()
    monkeypatch.setattr(taskbook_controller, "_STATE", state)
    public = FastAPI()
    public.include_router(controller.public_router)
    admin = FastAPI()
    admin.include_router(controller.admin_router)
    with TestClient(public) as client, TestClient(admin) as admin_client:
        yield client, admin_client, store, state


def fields(**change):
    return {"jid": "123456789a", "username": "张工", "rating": "poor", "comment": "表格需完善", **change}


def test_public_submit_captures_actual_selection_original_names_and_no_secrets(api):
    client, admin, _, state = api
    response = client.post("/api/feedback", json=fields())
    assert response.status_code == 200, response.text
    record = response.json()["record"]
    assert record["snapshot"] == {"jid": "123456789a", "job_status": "blocked", "parameters": {
        "product_type": "filter_connector", "product_type_label": "滤波连接器", "product_domain": "military", "product_domain_label": "军品",
        "development_process": "全新", "cover_phase": "初样", "product_series": "J599L", "organization_scope": "central_research",
        "model_provider": "smartvision", "model_name": "azure/gpt-5", "model_id": "4771", "template_name": "模板.docx"},
        "files": {"tech": "原始技术要求.docx", "spec": "原始规格书.docx", "output": "输出任务书.docx", "report": "输出任务书.report.html"},
        "delivery_status": "blocked", "qa_ok": False, "error": "质量门禁未通过"}
    encoded = json.dumps(record)
    assert "TOP-SECRET" not in encoded and "private" not in encoded and "base_url" not in encoded
    state.jobs["123456789a"]["replay"]["options"]["product_series"] = "CHANGED"
    assert admin.get(f'/api/feedback-admin/{record["id"]}').json()["record"]["snapshot"] == record["snapshot"]


def test_public_routes_do_not_expose_admin_reads_or_mutations(api):
    client, _, _, _ = api
    for method, path in [("get", "/api/feedback-admin"), ("post", "/api/feedback-admin"), ("put", "/api/feedback-admin/1"), ("delete", "/api/feedback-admin/1")]:
        assert getattr(client, method)(path).status_code == 404
    assert client.get("/api/feedback").status_code == 405


def test_admin_full_crud_and_version_conflict_json(api):
    _, admin, _, _ = api
    created = admin.post("/api/feedback-admin", json=fields(status="in_progress", handling_note="核查中"))
    assert created.status_code == 200, created.text
    record = created.json()["record"]
    endpoint = f'/api/feedback-admin/{record["id"]}'
    edited = admin.put(endpoint, json={"username": "李工", "rating": "average", "comment": "已验证", "status": "resolved", "handling_note": "已修正", "expected_version": 1})
    assert edited.status_code == 200, edited.text
    updated = edited.json()["record"]
    assert updated["version"] == 2 and updated["status"] == "resolved"
    assert updated["snapshot"] == record["snapshot"] and updated["created_at"] == record["created_at"]
    assert admin.put(endpoint, json={"comment": "过期", "expected_version": 1}).status_code == 409
    assert admin.delete(endpoint, params={"expected_version": 1}).status_code == 409
    assert admin.delete(endpoint, params={"expected_version": 2}).json() == {"ok": True}
    assert admin.get(endpoint).status_code == 404
    assert admin.get("/api/feedback-admin").json()["stats"]["total"] == 0


def test_http_validation_unknown_jobs_and_retry_deduplication(api):
    client, admin, _, _ = api
    payload = fields(request_id=str(uuid.uuid4()))
    original = client.post("/api/feedback", json=payload).json()["record"]
    assert client.post("/api/feedback", json=payload).json()["record"]["id"] == original["id"]
    assert client.post("/api/feedback", json={**payload, "rating": "good"}).status_code == 409
    for change in ({"snapshot": {}}, {"created_at": "1999-01-01"}, {"updated_at": "1999-01-01"},
                   {"username": ""}, {"username": ["张工"]}, {"username": "x" * 81}, {"rating": "bad"},
                   {"rating": ["good"]}, {"comment": {}}, {"comment": "x" * 4001}, {"request_id": 42}):
        response = client.post("/api/feedback", json=fields(**change))
        assert response.status_code == 400 and "error" in response.json()
    assert client.post("/api/feedback", json=fields(jid="aaaaaaaaaa")).status_code == 404
    assert client.post("/api/feedback", content="[]").status_code == 400
    assert client.post("/api/feedback", content='{"broken":').status_code == 400
    assert client.post("/api/feedback", content="x" * 65537).status_code == 400
    for params in ({"page_size": 101}, {"page": 0}, {"date_from": "invalid"}, {"rating": "bad"}):
        response = admin.get("/api/feedback-admin", params=params)
        assert response.status_code == 400 and "error" in response.json()


def test_persisted_manifest_is_found_after_memory_cleanup_and_paths_cannot_escape(api, tmp_path):
    client, _, _, state = api
    (state.output_dir / "old-result.job.json").write_text(json.dumps({"jid": "abcdef0123", **job()}), encoding="utf-8")
    response = client.post("/api/feedback", json=fields(jid="abcdef0123"))
    assert response.status_code == 200, response.text
    assert response.json()["record"]["snapshot"]["files"]["tech"] == "原始技术要求.docx"
    outside = tmp_path / "outside.job.json"
    outside.write_text(json.dumps({"jid": "aaaaaaaaaa", **job()}), encoding="utf-8")
    assert client.post("/api/feedback", json=fields(jid="../outside")).status_code == 404
    assert client.post("/api/feedback", json=fields(jid="aaaaaaaaaa")).status_code == 404


def test_failed_job_uses_diagnostic_context_and_replay_original_names(api):
    client, _, _, state = api
    state.jobs["123456789a"] = {"status": "error", "error": "模型调用失败", "result": {},
        "diagnostic_context": {"product_type": "rf_standard_interface", "product_domain": "military", "process_classification": "改型", "model": "azure/gpt-5"},
        "replay": {"files": {"tech": {"name": "replay_tech.docx", "original_name": "真实技术要求.docx"}, "spec": {"name": "replay_spec.docx", "original_name": "真实规格书.docx"}}}}
    response = client.post("/api/feedback", json=fields())
    assert response.status_code == 200, response.text
    saved = response.json()["record"]["snapshot"]
    assert saved["parameters"]["product_type"] == "rf_standard_interface"
    assert saved["parameters"]["development_process"] == "改型"
    assert saved["parameters"]["model_name"] == "azure/gpt-5"
    assert saved["files"]["tech"] == "真实技术要求.docx" and saved["files"]["spec"] == "真实规格书.docx"
    assert saved["error"] == "模型调用失败" and saved["job_status"] == "error"


@pytest.mark.parametrize("prefix", ["sk_", "sk-"])
def test_error_snapshot_redacts_standalone_and_quoted_credentials_before_persisting(api, prefix):
    client, admin, _, state = api
    synthetic_key = prefix + "synthetic_feedback_secret_123456"
    state.jobs["123456789a"]["error"] = (
        f'模型鉴权失败 {synthetic_key}; {{"api_key":"synthetic-quoted-secret"}} '
        'refresh_token=synthetic-refresh-secret https://private.example/v1 D:/private/client.json'
    )
    response = client.post("/api/feedback", json=fields())
    assert response.status_code == 200, response.text
    record = response.json()["record"]
    saved = admin.get(f'/api/feedback-admin/{record["id"]}').json()["record"]
    error = saved["snapshot"]["error"]
    assert "模型鉴权失败" in error
    assert synthetic_key not in error
    assert "synthetic-quoted-secret" not in error and "synthetic-refresh-secret" not in error
    assert "private.example" not in error and "D:/private" not in error


def test_admin_http_filters_and_stats_apply_before_pagination(api):
    client, admin, _, _ = api
    client.post("/api/feedback", json=fields(username="张工", rating="good"))
    client.post("/api/feedback", json=fields(username="张工", rating="average"))
    admin.post("/api/feedback-admin", json=fields(username="李工", rating="poor", status="resolved"))
    response = admin.get("/api/feedback-admin", params={"q": "张工", "page_size": 1}).json()
    assert response["total"] == 2 and len(response["items"]) == 1
    assert response["stats"]["good"] == response["stats"]["average"] == 1
    assert response["stats"]["good_rate"] == 0.5
    assert admin.get("/api/feedback-admin", params={"status": "resolved", "rating": "poor"}).json()["total"] == 1


def test_unavailable_database_returns_json_error(api):
    _, admin, store, _ = api
    store.path.unlink()
    store.path.mkdir()
    response = admin.get("/api/feedback-admin")
    assert response.status_code == 503 and "error" in response.json()


def test_deeply_nested_body_is_rejected_without_server_error(api):
    client, _, _, _ = api
    response = client.post("/api/feedback", content='{"comment":' + '[' * 20000 + '0' + ']' * 20000 + '}')
    assert response.status_code == 400 and "error" in response.json()


@pytest.mark.parametrize("outcome", ["error", "exception", "cancelled"])
def test_worker_retains_original_upload_names_for_feedback_after_failed_execution(api, tmp_path, monkeypatch, outcome):
    client, _, _, state = api
    state.upload_dir = tmp_path / "uploads"
    state.upload_dir.mkdir()
    state.config_dir = tmp_path / "config"
    state.config_dir.mkdir()
    paths = {}
    for role in ("tech", "spec", "template", "mapping", "profile"):
        path = tmp_path / (role + ".docx")
        path.write_text("source fixture", encoding="utf-8")
        paths[role] = str(path)
    selection = TemplateSelection("rf_standard_interface", "射频连接器", "military", "军品", paths["template"], paths["profile"], paths["mapping"], True)
    taskbook_controller._register_job("123456789a", selection=selection, development_process="改型")
    state.jobs["123456789a"]["result"]["meta"]["original_filenames"] = {"tech": "真实上传技术要求.docx", "spec": "真实上传规格书.docx"}

    @contextmanager
    def model_scope(*args):
        yield SimpleNamespace(provider="smartvision", model="azure/gpt-5", model_id="4771")

    def fail_pipeline(**kwargs):
        if outcome == "exception":
            raise RuntimeError("模型调用失败")
        if outcome == "cancelled":
            state.jobs["123456789a"]["cancel_requested"] = True
            kwargs["cb"]("继续执行")
        return {"ok": False, "error": "模型调用失败", "out": kwargs["out_path"], "meta": {}}

    monkeypatch.setattr(taskbook_controller.llm_client, "model_scope", model_scope)
    monkeypatch.setattr(pipeline_cli, "run_pipeline", fail_pipeline)
    taskbook_controller._run_job("123456789a", paths["tech"], paths["spec"], selection, str(state.output_dir / "task.docx"), True, development_process="改型")
    assert state.jobs["123456789a"]["status"] == ("cancelled" if outcome == "cancelled" else "error")
    response = client.post("/api/feedback", json=fields())
    assert response.status_code == 200, response.text
    saved = response.json()["record"]["snapshot"]
    assert saved["files"]["tech"] == "真实上传技术要求.docx" and saved["files"]["spec"] == "真实上传规格书.docx"
    assert saved["parameters"]["product_type"] == "rf_standard_interface"
    assert saved["parameters"]["model_name"] == "azure/gpt-5"
    state.jobs.clear()
    restored = client.post("/api/feedback", json=fields()).json()["record"]["snapshot"]
    assert restored == saved
