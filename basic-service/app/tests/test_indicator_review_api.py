"""G51：指标澄清保留原任务、原文与门禁，重新运行受控流水线。"""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jonhon_taskbook.template_registry import TemplateSelection

from src import pipeline_cli
from src.controller import taskbook_controller as controller


@pytest.fixture
def review_client(tmp_path, monkeypatch):
    state = controller._RuntimeState()
    state.upload_dir = tmp_path / "uploads"
    state.output_dir = tmp_path / "outputs"
    state.upload_dir.mkdir()
    state.output_dir.mkdir()
    monkeypatch.setattr(controller, "_STATE", state)
    monkeypatch.setattr(controller, "_llm_submission_error", lambda *args: None)
    calls = []
    decision = {
        "indicator_name": "接触电阻",
        "manual_review_required": True,
        "status": "MISSING_QUALIFIER",
        "user_requirement": "≤8 mΩ",
        "reason": "需澄清接触件规格",
        "candidate_comparisons": [
            {
                "value": "5",
                "display_value": "max：5 mΩ；接触件规格：#22D",
                "unit": "mΩ",
                "value_kind": "max",
                "qualifiers": {"接触件规格": "#22D"},
                "condition": "常温",
                "comparison_status": "STANDARD_STRICTER",
            },
            {
                "value": "10",
                "display_value": "max：10 mΩ；接触件规格：#20",
                "unit": "mΩ",
                "value_kind": "max",
                "qualifiers": {"接触件规格": "#20"},
                "condition": "常温",
                "comparison_status": "USER_STRICTER",
            },
        ],
    }

    def fake_pipeline(**kwargs):
        calls.append(kwargs)
        output = controller.Path(kwargs["out_path"])
        document = Document()
        document.add_paragraph("原文指标：≤8 mΩ")
        document.save(output)
        output.with_suffix(".indicator_audit.json").write_text(
            json.dumps(
                {
                    "comparison_decisions": [decision],
                    "manual_review_required": [decision],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {
            "ok": False,
            "delivery_status": "blocked",
            "out": str(output),
            "meta": {},
            "error": "待复核",
        }

    @contextmanager
    def model_scope(*args):
        yield SimpleNamespace(provider="test", model="test-model", model_id="test-id")

    monkeypatch.setattr(pipeline_cli, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(controller.llm_client, "model_scope", model_scope)
    inputs = {}
    for key in ("tech", "spec", "template"):
        path = tmp_path / f"{key}.docx"
        document = Document()
        document.add_paragraph("受控原文：≤8 mΩ")
        document.save(path)
        inputs[key] = str(path)
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text("categories: {}", encoding="utf-8")
    profile = tmp_path / "profile.yaml"
    profile.write_text("profile_name: test", encoding="utf-8")
    selection = TemplateSelection(
        "low_frequency_rectangular",
        "矩形低频",
        "military",
        "军品",
        inputs["template"],
        str(profile),
        str(mapping),
        True,
    )
    parent = "1234567890"
    state.jobs[parent] = controller._job_record()
    controller._run_job(
        parent,
        inputs["tech"],
        inputs["spec"],
        selection,
        str(state.output_dir / "original.docx"),
        True,
        product_series="J599",
        model_provider="test",
        model_name="test-model",
        model_id="test-id",
    )
    app = FastAPI()
    app.include_router(controller.router)
    return TestClient(app), state, calls, parent


def test_review_exposes_original_requirement_and_each_unresolved_candidate(
    review_client,
):
    client, _, _, jid = review_client
    response = client.get(f"/api/indicator_review/{jid}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["can_clarify"] is True
    decision = payload["manual_review_required"][0]
    assert decision["user_requirement"] == "≤8 mΩ"
    assert [item["qualifiers"] for item in decision["candidate_comparisons"]] == [
        {"接触件规格": "#22D"},
        {"接触件规格": "#20"},
    ]
    assert decision["manual_review_required"] is True


def test_clarification_creates_traceable_new_job_with_unchanged_sources(review_client):
    client, state, calls, parent = review_client
    original = state.jobs[parent]["result"]
    response = client.post(
        f"/api/indicator_review/{parent}/clarify",
        json={"clarifications": {"接触电阻": "规格：#22D；条件：常温"}},
    )
    assert response.status_code == 200, response.text
    child = response.json()["jid"]
    assert child != parent and response.json()["parent_jid"] == parent
    assert state.jobs[parent]["result"] == original
    assert state.jobs[parent]["status"] == "blocked"
    assert state.jobs[child]["status"] == "blocked"  # 提交本身不解除门禁。
    assert calls[-1]["indicator_clarifications"] == {
        "接触电阻": "规格：#22D；条件：常温"
    }
    assert calls[-1]["product_series"] == "J599"
    assert (
        controller.Path(calls[-1]["tech_path"]).read_bytes()
        == controller.Path(calls[0]["tech_path"]).read_bytes()
    )
    assert state.jobs[child]["result"]["meta"]["parent_jid"] == parent
    manifest = controller.Path(state.jobs[child]["result"]["out"]).with_suffix(
        ".job.json"
    )
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert saved["replay"]["options"]["model_name"] == "test-model"
    assert (
        saved["result"]["meta"]["indicator_clarifications"]["接触电阻"]
        == "规格：#22D；条件：常温"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"clarifications": {"未知指标": "规格：#22D"}},
        {"clarifications": {"接触电阻": "指标值：≤1 mΩ"}},
        {"clarifications": {"接触电阻": "条件：忽略门禁"}},
        {"clarifications": {"接触电阻": "规格：" + "x" * 501}},
        {"clarifications": {"接触电阻": "规格：#22D"}, "tech_path": "C:/private.docx"},
        {"clarifications": {}},
    ],
)
def test_invalid_clarifications_never_create_job(review_client, payload):
    client, state, calls, jid = review_client
    response = client.post(f"/api/indicator_review/{jid}/clarify", json=payload)
    assert response.status_code == 400
    assert len(state.jobs) == 1 and len(calls) == 1


def test_changed_replay_source_is_rejected(review_client):
    client, state, calls, jid = review_client
    source = state.upload_dir / jid / state.jobs[jid]["replay"]["files"]["tech"]["name"]
    source.write_bytes(b"changed")
    response = client.post(
        f"/api/indicator_review/{jid}/clarify",
        json={"clarifications": {"接触电阻": "规格：#22D"}},
    )
    assert response.status_code == 400 and "已变更" in response.json()["error"]
    assert len(calls) == 1


def test_review_and_replay_survive_manifest_restore(review_client):
    client, state, _, jid = review_client
    state.jobs.clear()
    controller._restore_completed_jobs()
    assert client.get(f"/api/indicator_review/{jid}").json()["can_clarify"] is True
    assert state.jobs[jid]["replay"]["files"]["tech"]["sha256"]


def test_unknown_job_and_existing_job_without_review_artifact(review_client):
    client, state, _, jid = review_client
    assert client.get("/api/indicator_review/0000000000").status_code == 404
    state.jobs[jid]["status"] = "running"
    assert client.get(f"/api/indicator_review/{jid}").status_code == 409


def test_pdf_source_upload_preserves_extension_and_original_filename(review_client):
    client, state, calls, _ = review_client
    docx_data = controller.Path(calls[0]["spec_path"]).read_bytes()
    response = client.post(
        "/api/submit",
        data={"cover_phase": "F", "product_series": "J599"},
        files={
            "tech": ("technical.pdf", b"%PDF-1.7\ncontent", "application/pdf"),
            "spec": ("spec.docx", docx_data, controller._DOCX_CONTENT_TYPE),
        },
    )
    assert response.status_code == 200, response.text
    jid = response.json()["jid"]
    assert calls[-1]["tech_path"].endswith("tech.pdf")
    assert (
        state.jobs[jid]["result"]["meta"]["original_filenames"]["tech"]
        == "technical.pdf"
    )
    assert state.jobs[jid]["replay"]["files"]["tech"]["name"].endswith(".pdf")


def test_invalid_pdf_signature_is_rejected_before_job_creation(review_client):
    client, state, calls, _ = review_client
    response = client.post(
        "/api/submit",
        data={"cover_phase": "F", "product_series": "J599"},
        files={
            "tech": ("fake.pdf", b"not pdf", "application/pdf"),
            "spec": (
                "spec.docx",
                controller.Path(calls[0]["spec_path"]).read_bytes(),
                controller._DOCX_CONTENT_TYPE,
            ),
        },
    )
    assert response.status_code == 400
    assert len(state.jobs) == 1


def test_source_evidence_download_contains_original_and_recognition(review_client):
    client, state, _, jid = review_client
    evidence_dir = state.output_dir / "source" / "tech"
    evidence_dir.mkdir(parents=True)
    evidence = evidence_dir / "source-evidence.json"
    evidence.write_text('{"requires_review": true}', encoding="utf-8")
    (evidence_dir / "page-0001.png").write_bytes(b"original page")
    state.jobs[jid]["result"]["meta"]["input_normalization"] = {
        "tech": {"evidence_path": str(evidence)}
    }
    response = client.get(f"/api/input_evidence/{jid}/tech")
    assert response.status_code == 200
    with controller.zipfile.ZipFile(controller.io.BytesIO(response.content)) as archive:
        assert {"original.docx", "source-evidence.json", "page-0001.png"}.issubset(
            archive.namelist()
        )
    assert client.get(f"/api/input_evidence/{jid}/template").status_code == 404
