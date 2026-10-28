"""Project context must survive every legacy job route and fixed-file capture."""
import hashlib
import io
import json
from pathlib import Path

import pytest
from docx import Document
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from jonhon_taskbook.review_store import ReviewStore
from src.service.rd_platform import integration


class DomainStore:
    def __init__(self, root):
        self.artifact_root = root / "artifacts"
        self.bindings = {}
        self.payload = None

    def generation(self, jid):
        return self.bindings.get(jid)

    def authorize_generation(self, jid, actor_id, write=False):
        if actor_id not in {"engineer", "reader"} or (write and actor_id != "engineer"):
            from src.service.rd_platform.store import RdError
            raise RdError(403, "无权限")
        return self.bindings[jid]

    def detail(self, pid, actor_id):
        return {"project": {"id": pid, "current_baseline_id": "b1"}, "tasks": [
            {"id": "t1", "baseline_id": "b1", "assignee_id": "engineer", "status": "in_progress"}]}

    def bind_generation(self, pid, tid, actor, jid, inputs):
        result = dict(project_id=pid, task_id=tid, baseline_id="b1", actor_id=actor["user_id"], inputs=inputs)
        self.bindings[jid] = result
        return result

    def register_artifact(self, pid, tid, actor, payload, expected_version, request_key):
        self.payload = payload
        return {"registered": True, "payload": payload}


@pytest.fixture
def domain(tmp_path):
    store = DomainStore(tmp_path)
    store.bind_generation("p1", "t1", {"user_id": "engineer"}, "1234567890", {})
    return store


@pytest.mark.parametrize("path,method", [
    ("status", "GET"), ("stream", "GET"), ("download", "GET"),
    ("report", "GET"), ("report/{jid}/download", "GET"), ("cancel", "POST"),
    ("input_evidence/{jid}/tech", "GET"), ("indicator_review/{jid}/clarify", "POST"),
    ("review/{jid}", "GET"), ("review/{jid}/assets/tech", "GET"),
    ("review/{jid}/revisions/baseline/download", "GET"),
    ("review/{jid}/editor/session/file", "GET"),
    ("review/{jid}/editor/session/callback", "POST"),
])
def test_legacy_routes_deny_anonymous_and_nonmembers(domain, path, method):
    path = path.format(jid="1234567890") if "{jid}" in path else path + "/1234567890"
    app = FastAPI()
    app.add_middleware(integration.RdJobAccessMiddleware, store_getter=lambda: domain)
    @app.api_route("/api/{rest:path}", methods=["GET", "POST"])
    def fallback(rest: str):
        return {"leaked": True}
    with TestClient(app) as client:
        response = client.request(method, "/api/" + path)
        assert response.status_code == 401


def test_member_reads_but_cannot_mutate_and_payload_actor_is_irrelevant(domain):
    app = FastAPI()
    app.add_middleware(integration.RdJobAccessMiddleware, store_getter=lambda: domain)
    @app.middleware("http")
    async def identity(request, call_next):
        request.state.current_user = {"userid": "reader", "verified": True, "name": "Reader"}
        return await call_next(request)
    @app.api_route("/api/review/{jid}", methods=["GET", "POST"])
    def fallback(jid: str):
        return {"ok": True}
    with TestClient(app) as client:
        assert client.get("/api/review/1234567890").status_code == 200
        assert client.post("/api/review/1234567890", json={"actor": "engineer"}).status_code == 403
        assert client.get("/api/review/standalone").status_code == 200


def test_submission_context_rejects_stale_baseline_and_unconfirmed_inputs(domain):
    actor = {"user_id": "engineer", "display_name": "Engineer"}
    with pytest.raises(Exception, match="基线"):
        integration.validate_submission(domain, actor, "p1", "t1", "old", True)
    with pytest.raises(Exception, match="确认"):
        integration.validate_submission(domain, actor, "p1", "t1", "b1", False)
    assert integration.validate_submission(domain, actor, "p1", "t1", "b1", True)["id"] == "t1"


@pytest.fixture
def revision(tmp_path, monkeypatch):
    root = tmp_path / "output"
    root.mkdir()
    source = root / "taskbook.docx"
    document = Document()
    document.add_paragraph("固定需求")
    document.save(source)
    reviews = ReviewStore(root / "reviews")
    reviews.ensure_review("1234567890", {"status": "done", "result": {"out": str(source)}},
                          {"output_dir": root, "upload_dir": tmp_path / "uploads"})
    from src.controller import review_controller
    monkeypatch.setattr(review_controller, "get_store", lambda: reviews)
    monkeypatch.setattr(review_controller, "ensure_review", lambda jid: reviews.get_review(jid))
    return reviews


def test_capture_requires_exact_revision_qa_and_copies_immutable_bytes(domain, revision):
    actor = {"user_id": "engineer", "display_name": "Engineer"}
    with pytest.raises(Exception, match="检查|QA"):
        integration.capture_artifact(domain, "p1", "t1", actor, "1234567890", "baseline", 1, "key")
    bundle = revision.get_review("1234567890")
    item = bundle["revisions"][0]
    item["checks"] = {"status": "passed", "revision_id": "wrong", "sha256": item["sha256"]}
    revision._write("1234567890", bundle)
    with pytest.raises(Exception, match="检查|QA"):
        integration.capture_artifact(domain, "p1", "t1", actor, "1234567890", "baseline", 1, "key")
    item["checks"].update(revision_id="baseline", scope="revision_deterministic")
    revision._write("1234567890", bundle)
    integration.capture_artifact(domain, "p1", "t1", actor, "1234567890", "baseline", 1, "key")
    payload = domain.payload
    copied = Path(payload["file_ref"])
    assert copied.is_relative_to(domain.artifact_root)
    assert payload["sha256"] == hashlib.sha256(copied.read_bytes()).hexdigest()
    assert payload["quality_status"] == "passed"
    assert payload["quality_evidence"]["checks"]["revision_id"] == "baseline"
    assert copied != revision.revision_path("1234567890", "baseline")
    original = copied.read_bytes()
    revision.revision_path("1234567890", "baseline").write_bytes(b"changed")
    assert copied.read_bytes() == original


@pytest.fixture
def upload_app(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.controller import taskbook_controller as jobs
    from src.service.rd_platform.store import RdStore
    from tests.support.rd_project import prepared
    store = RdStore(tmp_path / "rd.sqlite3")
    detail = prepared(store)
    state = jobs._RuntimeState()
    state.upload_dir = tmp_path / "uploads"
    state.output_dir = tmp_path / "outputs"
    state.upload_dir.mkdir()
    state.output_dir.mkdir()
    monkeypatch.setattr(jobs, "_STATE", state)
    monkeypatch.setattr(integration, "get_rd_store", lambda: store)
    monkeypatch.setattr(jobs, "_llm_submission_error", lambda *args: None)
    monkeypatch.setattr(jobs, "resolve_template_selection", lambda *args: SimpleNamespace(
        product_type="filter_connector", product_type_label="滤波连接器", product_domain="military",
        product_domain_label="军用", template_path="controlled.docx"))
    executed = []
    def run(jid, *args, **kwargs):
        # Evidence is binding existence before worker invocation; no model call.
        executed.append((jid, store.generation(jid)))
    monkeypatch.setattr(jobs, "_run_job", run)
    app = FastAPI()
    app.add_middleware(integration.RdJobAccessMiddleware, store_getter=lambda: store)
    @app.middleware("http")
    async def identity(request, call_next):
        uid = request.headers.get("Test-User", "engineer")
        request.state.current_user = {"userid": uid, "name": uid, "verified": True}
        return await call_next(request)
    app.include_router(jobs.router)
    from src.controller import review_controller, rd_controller
    monkeypatch.setattr(rd_controller, "get_store", lambda: store)
    app.include_router(review_controller.router)
    from src.controller import review_editor_controller
    app.include_router(review_editor_controller.router)
    app.include_router(rd_controller.router)
    form = {"rd_project": detail["project"]["id"], "rd_task": detail["tasks"][0]["id"],
            "rd_baseline_id": detail["project"]["current_baseline_id"], "rd_inputs_confirmed": "true", "use_llm": "false", "cover_phase": "F"}
    document = Document()
    document.add_paragraph("资料")
    output = io.BytesIO()
    document.save(output)
    return app, store, form, output.getvalue(), executed


def test_uploaded_project_job_binds_before_worker_and_retry_does_not_run_twice(upload_app):
    app, store, form, data, executed = upload_app
    files = {key: (key + ".docx", data) for key in ("tech", "spec")}
    with TestClient(app) as client:
        headers = {"Idempotency-Key": "intent-1"}
        first = client.post("/api/submit", data=form, files=files, headers=headers)
        assert first.status_code == 200, first.text
        jid = first.json()["jid"]
        assert executed == [(jid, store.generation(jid))]
        binding = store.generation(jid)
        assert binding["project_id"] == form["rd_project"]
        assert binding["inputs"]["files"]["tech"]["sha256"] == hashlib.sha256(data).hexdigest()
        second = client.post("/api/submit", data=form, files=files, headers=headers)
        assert second.json() == first.json()
        assert len(executed) == 1
        changed = client.post("/api/submit", data={**form, "product_series": "changed"}, files=files, headers=headers)
        assert changed.status_code == 409
        assert len(executed) == 1
        # Server-side attribution cannot be changed with a forged actor field.
        assert client.get(f"/api/status/{jid}", headers={"Test-User": "stranger"}).status_code == 404
        history = client.get("/api/history?include_legacy=true", headers={"Test-User": "stranger"})
        assert history.json() == []
        assert client.get("/api/history?include_legacy=true").json()[0]["jid"] == jid


def prepare_clarification_replay(client, form, data):
    """Real archived inputs/audit; the fixture worker only records execution."""
    from jonhon_taskbook.template_registry import TemplateSelection
    from src.controller import taskbook_controller as jobs
    response = client.post("/api/submit", data=form, files={key: (key + ".docx", data)
                           for key in ("tech", "spec")}, headers={"Idempotency-Key": "clarify-parent"})
    assert response.status_code == 200, response.text
    jid = response.json()["jid"]
    directory = jobs._STATE.upload_dir / jid
    files = {}
    for key, suffix in (("tech", ".docx"), ("spec", ".docx"), ("template", ".docx"), ("mapping", ".yaml"), ("profile", ".yaml")):
        path = directory / (key + suffix)
        path.write_bytes(data if suffix == ".docx" else b"{}")
        files[key] = {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    selection = TemplateSelection("filter_connector", "滤波连接器", "military", "军用",
        str(directory / "template.docx"), str(directory / "profile.yaml"), str(directory / "mapping.yaml"), True)
    output = jobs._STATE.output_dir / "clarify-parent.docx"
    output.write_bytes(data)
    output.with_suffix(".indicator_audit.json").write_text(json.dumps({"comparison_decisions": [
        {"indicator_name": "接触电阻", "manual_review_required": True}]}), encoding="utf-8")
    jobs._STATE.jobs[jid].update(status="done", result={"out": str(output), "meta": {}},
        replay={"files": files, "selection": selection.to_dict(), "options": {
            "development_process": "全新", "cover_phase": "F", "template_edit_plan": None,
            "template_edit_confirmed": False, "fail_on_regression": False}})
    return jid


def test_bound_clarification_retry_returns_same_job_without_second_worker(upload_app):
    app, store, form, data, executed = upload_app
    with TestClient(app) as client:
        parent = prepare_clarification_replay(client, form, data)
        url = f"/api/indicator_review/{parent}/clarify"
        body = {"clarifications": {"接触电阻": "条件：常温"}}
        first = client.post(url, json=body, headers={"Idempotency-Key": "clarify-intent"})
        second = client.post(url, json=body, headers={"Idempotency-Key": "clarify-intent"})
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert first.json()["parent_jid"] == parent
        assert len(executed) == 2
        assert executed[-1][1]["inputs"]["parameters"]["parent_jid"] == parent
        detail = store.detail(form["rd_project"], "engineer")
        assert len(detail["generations"]) == 2
        assert len([e for e in detail["events"] if e["action"] == "bind_generation"]) == 2
        from tests.support.rd_project import command
        command(store, detail, "remove_member", {"user_id": "engineer"})
        assert client.post(url, json=body, headers={"Idempotency-Key": "clarify-intent"}).status_code == 404
        assert len(executed) == 2


def test_bound_clarification_same_key_changed_conditions_conflicts(upload_app):
    app, store, form, data, executed = upload_app
    with TestClient(app) as client:
        parent = prepare_clarification_replay(client, form, data)
        url = f"/api/indicator_review/{parent}/clarify"
        assert client.post(url, json={"clarifications": {"接触电阻": "条件：常温"}},
                           headers={"Idempotency-Key": "clarify-intent"}).status_code == 200
        changed = client.post(url, json={"clarifications": {"接触电阻": "条件：低温"}},
                              headers={"Idempotency-Key": "clarify-intent"})
        assert changed.status_code == 409, changed.text
        assert len(executed) == 2
        assert len(store.detail(form["rd_project"], "engineer")["generations"]) == 2


def test_project_local_defaults_rejected_and_standalone_upload_preserved(upload_app):
    app, store, form, data, executed = upload_app
    with TestClient(app) as client:
        assert client.post("/api/submit_local", data=form).status_code == 422
        files = {key: (key + ".docx", data) for key in ("tech", "spec")}
        assert client.post("/api/submit", data={**form, "rd_inputs_confirmed": "false"}, files=files,
                           headers={"Idempotency-Key": "unconfirmed"}).status_code == 422
        standalone = client.post("/api/submit", data={"use_llm": "false", "cover_phase": "F"}, files=files)
        assert standalone.status_code == 200
        assert store.generation(standalone.json()["jid"]) is None
        assert len(executed) == 1


def test_bound_revision_audit_uses_verified_identity(upload_app, monkeypatch):
    app, store, form, data, _ = upload_app
    with TestClient(app) as client:
        response = client.post("/api/submit", data=form,
            files={key: (key + ".docx", data) for key in ("tech", "spec")}, headers={"Idempotency-Key": "review"})
        jid = response.json()["jid"]
        from src.controller import taskbook_controller as jobs, review_controller
        out = jobs._STATE.output_dir / "generated.docx"
        out.write_bytes(data)
        jobs._STATE.jobs[jid].update(status="done", result={"out": str(out), "meta": {}})
        bundle = client.get(f"/api/review/{jid}").json()
        response = client.post(f"/api/review/{jid}/revisions/upload", data={"expected_revision_id": "baseline", "actor": "owner"}, files={"file": ("edit.docx", data)})
        assert response.status_code == 200, response.text
        assert response.json()["revisions"][-1]["actor"] == "engineer"


def test_real_revision_check_can_pass_without_model_and_capture_to_sqlite(upload_app, tmp_path):
    app, store, form, data, _ = upload_app
    from src.controller import taskbook_controller as jobs, review_controller
    from tests.support.rd_project import ENGINEER, REVIEWER, command
    with TestClient(app) as client:
        response = client.post("/api/submit", data=form,
            files={key: (key + ".docx", data) for key in ("tech", "spec")}, headers={"Idempotency-Key": "capture"})
        jid = response.json()["jid"]
        jobdir = jobs._STATE.upload_dir / jid
        document = Document()
        document.add_paragraph("固定需求")
        table = document.add_table(rows=2, cols=4)
        for cell, text in zip(table.rows[0].cells, ["项目", "用户要求", "拟采用", "依据"]):
            cell.text = text
        for cell, text in zip(table.rows[1].cells, ["接触电阻", "5mΩ", "5mΩ", "客户协议"]):
            cell.text = text
        out = jobs._STATE.output_dir / "passed.docx"
        document.save(out)
        replay_files = {}
        for name, value in {"profile": "{}", "rule_qa_gate": "block_if: {}\nwarn_if: {}\n"}.items():
            path = jobdir / (name + ".yaml")
            path.write_text(value, encoding="utf-8")
            replay_files[name] = {"name": path.name}
        template = jobdir / "template.docx"
        template.write_bytes(out.read_bytes())
        replay_files["effective_template"] = {"name": template.name}
        out.with_suffix(".coverage_ledger.json").write_text(json.dumps({"source_file": "tech.docx", "blocks": [
            {"block_id": "s1", "raw_text": "固定需求", "summary": "固定需求", "source_section": "技术要求", "block_type": "paragraph", "covered": True}]}), encoding="utf-8")
        out.with_suffix(".indicator_audit.json").write_text(json.dumps({"comparison_decisions": [
            {"indicator_name": "接触电阻", "user_requirement": "5mΩ", "adopted_requirement": "5mΩ", "basis": "客户协议"}]}), encoding="utf-8")
        jobs._STATE.jobs[jid].update(status="done", result={"out": str(out), "meta": {"qa_ok": True}, "delivery_status": "approved"}, replay={"files": replay_files})
        checks = client.post(f"/api/review/{jid}/revisions/baseline/check")
        assert checks.status_code == 200
        assert checks.json()["status"] == "passed", checks.text
        edited = Document(out)
        edited.add_paragraph("补充工程说明，不改变需求指标。")
        edited_path = tmp_path / "edited.docx"
        edited.save(edited_path)
        updated = client.post(f"/api/review/{jid}/revisions/upload", data={"expected_revision_id": "baseline"},
                              files={"file": ("edited.docx", edited_path.read_bytes())})
        revision_id = updated.json()["current_revision_id"]
        standalone_checks = review_controller.get_store().check_revision(jid, revision_id)
        assert standalone_checks["status"] == "needs_review"
        checks = client.post(f"/api/review/{jid}/revisions/{revision_id}/check")
        assert checks.json()["status"] == "passed", checks.text
        assert checks.json()["delivery_approved"] is False
        detail = store.detail(form["rd_project"], "engineer")
        capture_url = f"/api/rd/projects/{form['rd_project']}/tasks/{form['rd_task']}/artifacts"
        capture_body = {"jid": jid, "revision_id": revision_id, "expected_version": detail["project"]["version"]}
        response = client.post(capture_url, headers={"Idempotency-Key": "fixed"}, json=capture_body)
        assert response.status_code == 200, response.text
        detail = response.json()
        artifact = detail["artifacts"][0]
        assert artifact["quality_evidence"]["checks"] == checks.json()
        assert artifact["quality_evidence"]["rules_fingerprint"]
        # Rechecking updates the live report, but a retry returns the original
        # immutable artifact/evidence rather than creating another version.
        repeated_checks = client.post(f"/api/review/{jid}/revisions/{revision_id}/check")
        assert repeated_checks.json()["checked_at"] != checks.json()["checked_at"]
        replay = client.post(capture_url, headers={"Idempotency-Key": "fixed"}, json=capture_body)
        assert replay.json() == detail
        url = f"/api/rd/projects/{form['rd_project']}/artifacts/{artifact['id']}/download?approved=true"
        assert client.get(url).status_code == 409
        detail = command(store, detail, "submit_review", {"task_id": form["rd_task"], "artifact_id": artifact["id"]}, ENGINEER)
        command(store, detail, "decide_review", {"review_id": detail["reviews"][0]["id"], "decision": "approved", "comment": "已核对"}, REVIEWER)
        approved = client.get(url)
        assert approved.status_code == 200
        assert hashlib.sha256(approved.content).hexdigest() == artifact["sha256"]
        assert client.get(url, headers={"Test-User": "stranger"}).status_code == 404


def test_office_capabilities_recheck_server_session_actor_after_membership_removal(upload_app, monkeypatch):
    from urllib.parse import urlsplit
    from jonhon_taskbook.review_editor import sign_token
    from src.controller import taskbook_controller as jobs, review_editor_controller
    from tests.support.rd_project import command
    app, store, form, data, _ = upload_app
    monkeypatch.setenv("JTB_REVIEW_EDITOR_URL", "http://editor.test")
    monkeypatch.setenv("JTB_REVIEW_PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("JTB_REVIEW_EDITOR_SECRET", "test-only-not-production-secret-123456789")
    with TestClient(app) as client:
        submitted = client.post("/api/submit", data=form, files={key: (key + ".docx", data) for key in ("tech", "spec")}, headers={"Idempotency-Key": "office"})
        jid = submitted.json()["jid"]
        out = jobs._STATE.output_dir / "office.docx"
        out.write_bytes(data)
        jobs._STATE.jobs[jid].update(status="done", result={"out": str(out), "meta": {}})
        opened = client.post(f"/api/review/{jid}/editor", json={"revision_id": "baseline", "mode": "edit"})
        assert opened.status_code == 200, opened.text
        config = opened.json()["config"]
        file_url = urlsplit(config["document"]["url"])
        # Document server has no enterprise identity, only the signed capability.
        assert client.get(file_url.path + "?" + file_url.query, headers={"Test-User": "stranger"}).status_code == 200
        session = review_editor_controller._editor()._session(jid, opened.json()["session_id"])
        assert session["rd_actor_id"] == "engineer"
        callback_path = urlsplit(config["editorConfig"]["callbackUrl"]).path
        token = sign_token({"key": session["key"], "status": 1}, "test-only-not-production-secret-123456789")
        assert client.post(callback_path, json={"token": token}, headers={"Test-User": "stranger"}).status_code == 200
        detail = store.detail(form["rd_project"], "owner")
        command(store, detail, "remove_member", {"user_id": "engineer"})
        assert client.get(file_url.path + "?" + file_url.query).status_code == 404
        assert client.post(callback_path, json={"token": token}).status_code == 404


def test_bound_job_cannot_leak_snapshot_into_separate_feedback_admin_store(domain, monkeypatch):
    from types import SimpleNamespace
    from src.controller import feedback_controller
    monkeypatch.setattr(integration, "get_rd_store", lambda: domain)
    monkeypatch.setattr(feedback_controller, "_resolve_job", lambda *args, **kwargs: {"status": "done"})
    monkeypatch.setattr(feedback_controller, "get_feedback_store", lambda: SimpleNamespace(create=lambda *args, **kwargs: {}))
    with pytest.raises(ValueError, match="项目"):
        feedback_controller._create({"jid": "1234567890", "rating": "good", "username": "stranger"})
