"""Feedback keeps the actual submitted context even if a queued task is cancelled."""
from io import BytesIO
from dataclasses import replace

from docx import Document
from fastapi.testclient import TestClient
from jonhon_taskbook.feedback_store import FeedbackStore
from jonhon_taskbook.template_registry import TemplateSelection

from src.controller import feedback_controller, taskbook_controller
from src.common.admin_access_store import AdminAccessStore
from src.common.platform_auth import AuthSettings
from src.feedback_main import create_app as create_admin_app
from src.main import create_app
from src.utils.config_loader import get_config


def test_queued_cancelled_submission_has_complete_server_snapshot_and_isolated_crud(tmp_path, monkeypatch):
    state = taskbook_controller._RuntimeState()
    state.upload_dir = tmp_path / "uploads"
    state.output_dir = tmp_path / "outputs"
    state.output_dir.mkdir()
    state.upload_dir.mkdir()
    monkeypatch.setattr(taskbook_controller, "_STATE", state)
    monkeypatch.setattr(taskbook_controller, "_llm_submission_error", lambda *_: None)
    selection = TemplateSelection("low_frequency_rectangular", "低频连接器-矩形低频", "military", "军品",
                                  str(tmp_path / "connector_taskbook.docx"), None, str(tmp_path / "mapping.yaml"), True)
    monkeypatch.setattr(taskbook_controller, "resolve_template_selection", lambda *_: selection)
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    monkeypatch.setattr(feedback_controller, "get_feedback_store", lambda: store)
    original_run = taskbook_controller._run_job

    def cancelled_before_start(jid, *args, **kwargs):
        state.jobs[jid]["cancel_requested"] = True
        original_run(jid, *args, **kwargs)

    monkeypatch.setattr(taskbook_controller, "_run_job", cancelled_before_start)
    source = BytesIO()
    document = Document()
    document.add_paragraph("CY产品技术要求")
    document.save(source)
    config = replace(get_config(), output_dir=state.output_dir, logs_dir=tmp_path / "logs")
    client = TestClient(create_app(config))
    submitted = client.post("/api/submit", data={
        "product_type": selection.product_type, "product_domain": "military",
        "development_process": "全新", "product_series": "CY", "organization_scope": "central_research",
        "cover_phase": "S", "model_provider": "smartvision", "model_name": "deepseek-v4-flash", "model_id": "123",
    }, files={"tech": ("CY需求.docx", source.getvalue()), "spec": ("CY规范.docx", source.getvalue())})
    assert submitted.status_code == 200, submitted.text
    jid = submitted.json()["jid"]
    assert state.jobs[jid]["status"] == "cancelled"
    feedback = client.post("/api/feedback", json={"jid": jid, "username": "测试工程师", "rating": "poor", "comment": "任务在排队中被停止"})
    assert feedback.status_code == 200, feedback.text
    record = feedback.json()["record"]
    parameters = record["snapshot"]["parameters"]
    assert parameters == {
        "product_type": selection.product_type, "product_type_label": selection.product_type_label,
        "product_domain": "military", "product_domain_label": "军品", "development_process": "全新",
        "product_series": "CY", "organization_scope": "central_research", "cover_phase": "S",
        "model_provider": "smartvision", "model_name": "deepseek-v4-flash", "model_id": "123",
        "template_name": "connector_taskbook.docx",
    }
    assert record["snapshot"]["files"]["tech"] == "CY需求.docx"
    assert record["snapshot"]["files"]["spec"] == "CY规范.docx"
    assert client.get("/api/feedback-admin").status_code == 404
    state.jobs.clear()
    # Use the real admin session contract with an isolated store, without OA calls.
    access = AdminAccessStore(tmp_path / "admin-access.sqlite3")
    auth = AuthSettings(enabled=True, app_id=127, platform_base_url="https://oa.example.test",
                        callback_hosts=("testserver",))
    session = access.create_session(username="wangxue", userid="snapshot-admin", display_name="测试管理员",
                                    app_id=auth.app_id, base_url=auth.platform_base_url, origin="http://testserver")
    admin = TestClient(create_admin_app(config, auth_settings=auth, admin_store=access),
                       cookies={"jtb_admin_session": session})
    detail = admin.get(f'/api/feedback-admin/{record["id"]}')
    assert detail.status_code == 200 and detail.json()["record"] == record
    recreated = admin.post("/api/feedback-admin", json={"jid": jid, "username": "复核人员", "rating": "average"})
    assert recreated.status_code == 200, recreated.text
    assert recreated.json()["record"]["snapshot"] == record["snapshot"]
