"""Rule edits pass the HTTP boundary and change the real runtime consumer."""
from tests.support.paths import APP_ROOT

import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jonhon_taskbook import development_process_policy, failure_mode_policy
from jonhon_taskbook.rule_editor import RuleEditor

from src.controller import taskbook_controller as controller


@pytest.fixture
def rule_api(tmp_path, monkeypatch):
    service = APP_ROOT / "src" / "service"
    config = tmp_path / "config"
    package = tmp_path / "jonhon_taskbook"
    config.mkdir()
    package.mkdir()
    for root, target in (
        (service / "config", config),
        (service / "jonhon_taskbook", package),
    ):
        for source in root.glob("*.yaml"):
            shutil.copy2(source, target / source.name)
    state = controller._RuntimeState()
    state.config_dir = config
    state.package_root = package
    state.rule_editor = RuleEditor(config, package, tmp_path / "history")
    monkeypatch.setattr(controller, "_STATE", state)
    monkeypatch.setattr(
        failure_mode_policy, "POLICY_PATH", config / "failure_mode_policy.yaml"
    )
    monkeypatch.setattr(
        development_process_policy, "POLICY_PATH", config / "development_process_policy.yaml"
    )
    controller._invalidate_rule_caches()
    app = FastAPI()
    app.include_router(controller.router)
    with TestClient(app) as client:
        yield client, state, config
    controller._invalidate_rule_caches()


def change_request(revision, value="本产品及系列暂无匹配故障记录"):
    return {
        "expected_revision": revision,
        "changes": [{"path": ["no_applicable_record", "text"], "value": value}],
        "note": "完善故障信息说明",
    }


def test_save_and_restore_change_cached_runtime_policy_without_restart(rule_api):
    client, _, config = rule_api
    endpoint = "/api/rules/failure_mode_policy"
    before = (config / "failure_mode_policy.yaml").read_bytes()
    original_text = failure_mode_policy.failure_no_match_policy()["text"]
    original = client.get(endpoint).json()
    body = change_request(original["revision"])
    checked = client.post(endpoint + "/validate", json=body)
    assert checked.status_code == 200 and checked.json()["valid"]
    assert checked.json()["changes"][0]["before"] == original_text
    assert (config / "failure_mode_policy.yaml").read_bytes() == before

    response = client.put(endpoint, json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["can_save"] and saved["revision"] != original["revision"]
    assert (
        failure_mode_policy.failure_no_match_policy()["text"]
        == body["changes"][0]["value"]
    )
    assert client.put(endpoint, json=body).status_code == 409

    restored = client.post(
        endpoint + "/restore",
        json={
            "expected_revision": saved["revision"],
            "revision": original["revision"],
            "note": "恢复原说明",
        },
    )
    assert restored.status_code == 200, restored.text
    assert (config / "failure_mode_policy.yaml").read_bytes() == before
    assert failure_mode_policy.failure_no_match_policy()["text"] == original_text
    records = client.get(endpoint + "/history").json()["items"]
    assert len(records) == 3
    assert records[0]["is_current"] and records[0]["note"] == "恢复原说明"


@pytest.mark.parametrize("status", ["queued", "running", "cancelling"])
def test_active_jobs_allow_validation_but_prevent_rule_publication(rule_api, status):
    client, state, config = rule_api
    endpoint = "/api/rules/failure_mode_policy"
    initial = client.get(endpoint).json()
    controller._register_job("0123456789")
    state.jobs["0123456789"]["status"] = status
    assert (
        state.jobs["0123456789"]["result"]["meta"]["rule_revisions"][
            "failure_mode_policy"
        ]
        == initial["revision"]
    )
    before = (config / "failure_mode_policy.yaml").read_bytes()
    assert client.get("/api/rules").json()["can_save"] is False
    assert client.get(endpoint).json()["can_save"] is False
    body = change_request(initial["revision"])
    assert client.post(endpoint + "/validate", json=body).status_code == 200
    failed = client.put(endpoint, json=body)
    assert failed.status_code == 409 and "任务" in failed.json()["error"]
    assert (config / "failure_mode_policy.yaml").read_bytes() == before
    state.jobs["0123456789"]["status"] = "done"
    assert client.put(endpoint, json=body).status_code == 200


def test_invalid_edits_never_change_live_rules(rule_api):
    client, _, config = rule_api
    endpoint = "/api/rules/failure_mode_policy"
    initial = client.get(endpoint).json()
    before = (config / "failure_mode_policy.yaml").read_bytes()
    invalid = change_request(initial["revision"], "")
    assert client.put(endpoint, json=invalid).status_code == 422
    invalid["changes"] = [
        {"path": ["matching", "mode"], "value": "guess_similar_product"}
    ]
    assert client.put(endpoint, json=invalid).status_code == 422
    assert client.put(endpoint, json={"changes": []}).status_code == 422
    assert client.put(endpoint, content="invalid-json").status_code == 422
    assert client.get("/api/rules/not_a_rule").status_code == 404
    assert (config / "failure_mode_policy.yaml").read_bytes() == before


def test_directory_contains_real_generation_rules_and_no_unwired_configs(rule_api):
    client, _, _ = rule_api
    response = client.get("/api/rules")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert {
        "rf_connector_requirement_categories",
        "rf_standard_interface_profile",
        "development_process_policy",
        "qa_gate",
    } <= ids
    assert not {"section_policy", "template_artifact_rules", "project_profile"} & ids
    assert all(item["field_count"] > 0 for item in response.json()["items"])


def test_process_rule_publication_changes_generation_and_linked_appendix_without_restart(rule_api, tmp_path):
    from docx import Document
    from jonhon_taskbook.fill import _apply_process_specific_sections

    client, _, _ = rule_api
    endpoint = "/api/rules/development_process_policy"
    original = client.get(endpoint).json()

    def generate():
        document = Document()
        for heading, level in (("产品运行场景识别", 2), ("工艺要求", 1), ("附录A", 1)):
            document.add_heading(heading, level)
            document.add_paragraph(f"{heading}正文")
        _apply_process_specific_sections(
            document, {}, "改型II", "滤波连接器", "验证系列", str(tmp_path / "out.docx"),
        )
        return [paragraph.text for paragraph in document.paragraphs]

    # Warm the cached runtime policy before publication, just as a completed job would.
    assert "产品运行场景识别" not in generate()
    payload = {
        "expected_revision": original["revision"],
        "changes": [{"path": ["section_retention_rules", 1, "keep_processes"], "value": ["全新", "改型I", "改型II"]}],
        "note": "验证运行场景规则动态修改",
    }
    assert client.post(endpoint + "/validate", json=payload).status_code == 200
    assert "附录A" not in generate()
    response = client.put(endpoint, json=payload)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert "产品运行场景识别" in generate()
    assert "附录A" in generate()
    restored = client.post(endpoint + "/restore", json={
        "expected_revision": saved["revision"], "revision": original["revision"],
        "note": "恢复业务规则",
    })
    assert restored.status_code == 200, restored.text
    assert generate() == ["工艺要求", "工艺要求正文"]
