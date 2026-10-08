"""Failed and cancelled jobs retain evidence across a server restart."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jonhon_taskbook.template_registry import TemplateSelection

from src import pipeline_cli
from src.controller import taskbook_controller as controller


@pytest.fixture
def worker(tmp_path, monkeypatch):
    state = controller._RuntimeState()
    state.upload_dir = tmp_path / "uploads"
    state.output_dir = tmp_path / "outputs"
    state.upload_dir.mkdir()
    state.output_dir.mkdir()
    monkeypatch.setattr(controller, "_STATE", state)
    files = {}
    for role, suffix in (("tech", ".docx"), ("spec", ".docx"), ("template", ".docx"), ("mapping", ".yaml"), ("profile", ".yaml")):
        path = tmp_path / (role + suffix)
        path.write_text("fixture", encoding="utf-8")
        files[role] = str(path)
    selection = TemplateSelection("rf_standard_interface", "射频连接器", "military", "军品", files["template"], files["profile"], files["mapping"], True)

    @contextmanager
    def model_scope(*args):
        yield SimpleNamespace(provider="smartvision", model="azure/gpt-5", model_id="4771")

    monkeypatch.setattr(controller.llm_client, "model_scope", model_scope)
    jid = "26c4677f0f"
    state.jobs[jid] = controller._job_record()
    app = FastAPI()
    app.include_router(controller.router)

    def run():
        controller._run_job(jid, files["tech"], files["spec"], selection, str(state.output_dir / "result.docx"), True)

    return state, jid, run, TestClient(app)


@pytest.mark.parametrize("raise_exception", [False, True])
def test_failed_worker_is_persisted_without_an_artifact_and_restored(worker, monkeypatch, raise_exception):
    state, jid, run, client = worker
    message = "需求语义分类失败: LLM 未返回可解析的 JSON"

    def fail_pipeline(**kwargs):
        kwargs["cb"]("需求原文块语义分类")
        if raise_exception:
            raise RuntimeError(message)
        return {"ok": False, "error": message, "out": kwargs["out_path"], "meta": {}}

    monkeypatch.setattr(pipeline_cli, "run_pipeline", fail_pipeline)
    run()
    assert state.jobs[jid]["status"] == "error"
    manifests = list(state.output_dir.glob("*.job.json"))
    assert len(manifests) == 1
    saved = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert saved["status"] == "error" and saved["error"] == message
    assert saved["result"]["meta"]["llm_model"] == "azure/gpt-5"
    assert saved["result"]["meta"]["selected_product_type"] == "rf_standard_interface"
    assert not saved.get("artifact_sha256")
    assert "需求原文块语义分类" in saved["log"]
    assert not list(state.output_dir.glob("*.docx"))
    saved["result"].setdefault("meta", {})["runtime_process_id"] = -1
    manifests[0].write_text(json.dumps(saved), encoding="utf-8")
    state.jobs.clear()
    controller._restore_completed_jobs()
    assert state.jobs[jid]["status"] == "error"
    assert state.jobs[jid]["error"] == message
    response = client.get(f"/api/status/{jid}").json()
    assert response["status"] == "error" and response["error"] == message
    history = client.get("/api/history").json()
    assert history[0]["jid"] == jid and history[0]["status"] == "error"
    assert history[0]["current_runtime"] is False
    assert controller._job_artifact(jid, "docx") is None


@pytest.mark.parametrize("cancel_before_start", [False, True])
def test_cancelled_worker_is_persisted_without_running_further_steps(worker, monkeypatch, cancel_before_start):
    state, jid, run, client = worker
    calls = []

    def cancelled_pipeline(**kwargs):
        calls.append("pipeline")
        state.jobs[jid]["cancel_requested"] = True
        kwargs["cb"]("next step")
        pytest.fail("Cancellation should interrupt this step")

    monkeypatch.setattr(pipeline_cli, "run_pipeline", cancelled_pipeline)
    state.jobs[jid]["cancel_requested"] = cancel_before_start
    run()
    assert calls == ([] if cancel_before_start else ["pipeline"])
    assert state.jobs[jid]["status"] == "cancelled"
    manifests = list(state.output_dir.glob("*.job.json"))
    assert len(manifests) == 1
    state.jobs.clear()
    controller._restore_completed_jobs()
    assert state.jobs[jid]["status"] == "cancelled"
    assert client.get("/api/history").json()[0]["status"] == "cancelled"
    assert controller._job_artifact(jid, "docx") is None


def test_string_error_snapshot_restores_as_failure_without_success_or_download(worker):
    state, jid, _, client = worker
    state.jobs.clear()
    (state.output_dir / f"{jid}.job.json").write_text(json.dumps({"jid": jid, "status": "error", "result": "LLM 未返回可解析的 JSON", "log": ["语义分类失败"]}), encoding="utf-8")
    controller._restore_completed_jobs()
    assert state.jobs[jid]["status"] == "error"
    assert state.jobs[jid]["error"] == "LLM 未返回可解析的 JSON"
    assert client.get("/api/history").json()[0]["status"] == "error"
    assert client.get(f"/api/status/{jid}").json()["error"] == "LLM 未返回可解析的 JSON"
    assert controller._job_artifact(jid, "docx") is None
