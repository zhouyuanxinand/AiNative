"""Task lifecycle logs remain useful, bounded and safe for UI diagnosis."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jonhon_taskbook.template_registry import TemplateSelection

from src import pipeline_cli
from src.common.request_context import correlation_id_var, job_id_var, job_stage_var
from src.controller import taskbook_controller as controller


@pytest.fixture
def diagnostic_worker(tmp_path, monkeypatch):
    state = controller._RuntimeState()
    state.upload_dir = tmp_path / "uploads"
    state.output_dir = tmp_path / "outputs"
    state.upload_dir.mkdir()
    state.output_dir.mkdir()
    monkeypatch.setattr(controller, "_STATE", state)

    files = {}
    for role, suffix in (
        ("tech", ".docx"),
        ("spec", ".docx"),
        ("template", ".docx"),
        ("mapping", ".yaml"),
        ("profile", ".yaml"),
    ):
        path = tmp_path / f"{role}{suffix}"
        path.write_text("fixture", encoding="utf-8")
        files[role] = str(path)

    selection = TemplateSelection(
        "filter_connector",
        "滤波连接器",
        "military",
        "军品",
        files["template"],
        files["profile"],
        files["mapping"],
        True,
    )

    @contextmanager
    def model_scope(*_args, **_kwargs):
        yield SimpleNamespace(
            provider="smartvision", model="deepseek-v4-flash", model_id="401"
        )

    monkeypatch.setattr(controller.llm_client, "model_scope", model_scope)
    jid = "26c4677f0f"
    token = correlation_id_var.set("request-correlation-123")
    try:
        controller._register_job(
            jid,
            selection=selection,
            development_process="改型II",
            model_provider="smartvision",
            model_name="deepseek-v4-flash",
            model_id="401",
        )
    finally:
        correlation_id_var.reset(token)

    def run():
        controller._run_job(
            jid,
            files["tech"],
            files["spec"],
            selection,
            str(state.output_dir / "result.docx"),
            True,
            development_process="改型II",
            model_provider="smartvision",
            model_name="deepseek-v4-flash",
            model_id="401",
        )

    return state, jid, run, selection


def _task_records(caplog):
    return [
        record
        for record in caplog.records
        if str(getattr(record, "event", "")).startswith("taskbook_")
    ]


def _docx_bytes(text: str) -> bytes:
    stream = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(stream)
    return stream.getvalue()


def test_success_logs_stable_stages_once_with_required_context(
    diagnostic_worker, monkeypatch, caplog
):
    state, jid, run, _selection = diagnostic_worker
    caplog.set_level(logging.INFO, logger="src.controller.taskbook")

    def successful_pipeline(**kwargs):
        kwargs["cb"]("[ 0.1s] 🗂 需求原文块语义分类…")
        kwargs["cb"]("[ 0.2s] 全量分类: 18/18")
        kwargs["cb"]("不会映射的普通进度：uploaded source body must stay private")
        return {
            "ok": True,
            "out": kwargs["out_path"],
            "warnings": [],
            "meta": {},
        }

    monkeypatch.setattr(pipeline_cli, "run_pipeline", successful_pipeline)
    run()

    records = _task_records(caplog)
    events = [record.event for record in records]
    assert events.count("taskbook_job_started") == 1
    assert events.count("taskbook_job_completed") == 1
    semantic = [
        record
        for record in records
        if record.event == "taskbook_job_stage_entered"
        and record.stage == "semantic_classification"
    ]
    assert len(semantic) == 1
    assert state.jobs[jid]["status"] == "done"

    required = {
        "job_id",
        "stage",
        "event",
        "product_type",
        "product_domain",
        "process_classification",
        "model",
        "duration_ms",
        "error_type",
    }
    for record in records:
        assert required <= set(record.__dict__)
        assert record.job_id == jid
        assert record.product_type == "filter_connector"
        assert record.product_domain == "military"
        assert record.process_classification == "改型II"
    assert all("uploaded source body" not in record.getMessage() for record in records)
    assert correlation_id_var.get() == "-"
    assert job_id_var.get() == "-"
    assert job_stage_var.get() == "-"


def test_worker_exception_keeps_traceback_but_omits_secret_response(
    diagnostic_worker, monkeypatch, caplog
):
    state, jid, run, _selection = diagnostic_worker
    caplog.set_level(logging.INFO, logger="src.controller.taskbook")
    sensitive_failure = "API Key: sk_synthetic_test_crede model output raw response"

    def failing_pipeline(**_kwargs):
        raise RuntimeError(sensitive_failure)

    monkeypatch.setattr(pipeline_cli, "run_pipeline", failing_pipeline)
    run()

    failures = [
        record
        for record in _task_records(caplog)
        if record.event == "taskbook_job_failed"
    ]
    assert len(failures) == 1
    failure = failures[0]
    assert failure.error_type == "RuntimeError"
    assert failure.error_summary.endswith("model output [detail omitted]")
    assert "sk_QN50" not in failure.error_summary
    assert failure.exc_info and failure.exc_info[2] is not None
    assert "sk_QN50" not in caplog.text
    assert "model output raw response" not in caplog.text
    assert state.jobs[jid]["status"] == "error"


def test_blocked_and_cancelled_jobs_have_distinct_terminal_events(
    diagnostic_worker, monkeypatch, caplog
):
    state, _jid, run, _selection = diagnostic_worker
    caplog.set_level(logging.INFO, logger="src.controller.taskbook")
    output = state.output_dir / "result.docx"

    def blocked_pipeline(**kwargs):
        output.write_bytes(b"review artifact")
        return {
            "ok": False,
            "delivery_status": "blocked",
            "error": "质量门禁未通过",
            "out": kwargs["out_path"],
            "warnings": ["review"],
            "meta": {},
        }

    monkeypatch.setattr(pipeline_cli, "run_pipeline", blocked_pipeline)
    run()
    blocked = [r for r in _task_records(caplog) if r.event == "taskbook_job_blocked"]
    assert len(blocked) == 1
    assert blocked[0].error_type == "DeliveryGateBlocked"
    assert blocked[0].error_summary == "质量门禁未通过"

    cancel_jid = "16c4677f0e"
    controller._register_job(
        cancel_jid,
        selection=_selection,
        development_process="全新",
        model_provider="smartvision",
        model_name="deepseek-v4-flash",
    )
    app = FastAPI()
    app.include_router(controller.router)
    client = TestClient(app)
    response = client.post(f"/api/cancel/{cancel_jid}")
    assert response.status_code == 200 and response.json()["accepted"] is True
    controller._run_job(
        cancel_jid,
        str(output),
        str(output),
        _selection,
        str(state.output_dir / "cancelled.docx"),
        True,
    )
    events = [r.event for r in _task_records(caplog)]
    assert "taskbook_job_cancel_requested" in events
    assert "taskbook_job_cancelled" in events
    assert state.jobs[cancel_jid]["status"] == "cancelled"


def test_precheck_rejection_is_correlated_without_logging_upload_content(
    diagnostic_worker, monkeypatch, caplog
):
    _state, _jid, _run, _selection = diagnostic_worker
    caplog.set_level(logging.INFO, logger="src.controller.taskbook")

    def reject_selection(*_args, **_kwargs):
        raise ValueError("unsupported selection")

    monkeypatch.setattr(controller, "resolve_template_selection", reject_selection)
    app = FastAPI()
    app.include_router(controller.router)
    response = TestClient(app).post(
        "/api/precheck",
        data={
            "product_type": "filter_connector",
            "product_domain": "military",
            "development_process": "全新",
            "organization_scope": "non_central_research",
            "cover_phase": "F",
            "model_provider": "smartvision",
            "model_name": "deepseek-v4-flash",
        },
        files={
            "tech": ("tech.docx", b"confidential requirement content"),
            "spec": ("spec.docx", b"confidential product content"),
        },
    )
    assert response.status_code == 400
    records = _task_records(caplog)
    assert [r.event for r in records] == [
        "taskbook_precheck_started",
        "taskbook_precheck_rejected",
    ]
    assert records[0].job_id.startswith("precheck-")
    assert records[1].error_type == "ValueError"
    assert records[1].error_summary == "unsupported selection"
    assert "confidential requirement content" not in caplog.text
    assert "confidential product content" not in caplog.text


def test_upload_submission_logs_accepted_job_without_file_contents(
    diagnostic_worker, monkeypatch, caplog
):
    _state, _jid, _run, selection = diagnostic_worker
    caplog.set_level(logging.INFO, logger="src.controller.taskbook")
    monkeypatch.setattr(
        controller, "resolve_template_selection", lambda *_args, **_kwargs: selection
    )
    monkeypatch.setattr(
        controller.llm_client,
        "get_model_status",
        lambda *_args, **_kwargs: {
            "configured": True,
            "model": "deepseek-v4-flash",
        },
    )
    monkeypatch.setattr(controller, "_run_job", lambda *_args, **_kwargs: None)
    app = FastAPI()
    app.include_router(controller.router)
    response = TestClient(app).post(
        "/api/submit",
        data={
            "product_type": "filter_connector",
            "product_domain": "military",
            "development_process": "改型II",
            "organization_scope": "non_central_research",
            "cover_phase": "F",
            "use_llm": "true",
            "model_provider": "smartvision",
            "model_name": "deepseek-v4-flash",
            "model_id": "401",
        },
        files={
            "tech": ("tech.docx", _docx_bytes("confidential requirement")),
            "spec": ("spec.docx", _docx_bytes("confidential product specification")),
        },
    )
    assert response.status_code == 200
    submitted = [
        record
        for record in _task_records(caplog)
        if record.event == "taskbook_job_submitted"
    ]
    assert len(submitted) == 1
    assert submitted[0].job_id == response.json()["jid"]
    assert submitted[0].submission_kind == "upload"
    assert submitted[0].stage == "queued"
    assert "confidential requirement" not in caplog.text
    assert "confidential product specification" not in caplog.text
