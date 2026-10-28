"""Replace/restore real Word templates through HTTP without altering rules."""
import io
from pathlib import Path

import pytest
import yaml
from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jonhon_taskbook.template_versions import TemplateVersions
from src.controller import taskbook_controller as controller


def template_bytes(text="初始正文", *, required_heading=True, columns=4):
    document = Document()
    if required_heading:
        document.add_heading("工艺要求", 1)
    document.add_paragraph(text)
    document.add_heading("技术指标", 1)
    table = document.add_table(rows=2, cols=columns)
    headers = ["项目", "用户要求指标", "拟采用指标", "依据"]
    for cell, header in zip(table.rows[0].cells, headers):
        cell.text = header
    table.cell(1, 0).text = "阻抗"
    result = io.BytesIO()
    document.save(result)
    return result.getvalue()


@pytest.fixture
def version_api(tmp_path, monkeypatch):
    templates, config = tmp_path / "templates", tmp_path / "config"
    templates.mkdir()
    config.mkdir()
    (templates / "initial.docx").write_bytes(template_bytes())
    mapping = {
        "categories": {"process_requirement": {
            "label": "工艺要求", "target_heading_keywords": ["工艺要求"], "target_heading_level": 1,
            "atomic_source_heading_keywords": ["材质与表面处理"],
        }},
        "semantic_roles": {"performance_indicator": {
            "label": "技术指标", "target_heading_keywords": ["技术指标"], "target_heading_level": 1,
        }},
    }
    (config / "mapping.yaml").write_text(yaml.safe_dump(mapping, allow_unicode=True), encoding="utf-8")
    domain = {"label": "军品", "template": "initial.docx", "category_mapping": "mapping.yaml",
              "profile": "original_profile.yaml", "preserve_unfilled_template": True}
    catalog = {"product_types": {
        "filter": {"label": "滤波连接器", "enabled": True,
                   "domains": {"military": dict(domain), "civil": dict(domain, label="民机")}},
        "other": {"label": "其他连接器", "enabled": True, "domains": {"military": dict(domain)}},
    }}
    path = config / "template_catalog.yaml"
    path.write_text(yaml.safe_dump(catalog, allow_unicode=True), encoding="utf-8")
    state = controller._RuntimeState()
    state.template_versions = TemplateVersions(path, templates, config, tmp_path / "history")
    monkeypatch.setattr(controller, "_STATE", state)
    application = FastAPI()
    application.include_router(controller.router)
    with TestClient(application) as client:
        yield client, state, catalog


def upload(client, text="新模板", **kwargs):
    data = {"product_type": kwargs.pop("product", "filter"), "product_domain": "military",
            "version": text, "note": "更新模板"}
    return client.post("/api/templates/versions", data=data, files={
        "template": (kwargs.pop("filename", "新模板.docx"), template_bytes(text, **kwargs)),
    })


def activate(client, version_id, revision):
    return client.post(f"/api/templates/versions/{version_id}/activate",
                       data={"expected_revision": revision, "actor": "tester"})


def history(client, product="filter"):
    return client.get(f"/api/templates/{product}/military/versions").json()


def test_upload_activate_download_restore_preserve_other_bindings_and_material_rules(version_api):
    client, state, original = version_api
    manager = state.template_versions
    old_file = (manager.template_root / "initial.docx").read_bytes()
    rules = (manager.mapping_root / "mapping.yaml").read_bytes()
    directory = client.get("/api/templates")
    assert directory.status_code == 200 and len(directory.json()) == 3
    filter_military = next(item for item in directory.json()
                           if item["product_type_id"] == "filter" and item["product_domain_id"] == "military")
    assert filter_military["revision"] == history(client)["current"]["revision"]
    staged = upload(client)
    assert staged.status_code == 200, staged.text
    candidate = staged.json()["version"]
    assert candidate["status"] == "ready"
    assert history(client)["current"]["template"] == "initial.docx"
    download = client.get(f"/api/templates/versions/{candidate['id']}/download")
    assert download.status_code == 200
    assert Document(io.BytesIO(download.content)).paragraphs[1].text == "新模板"
    response = activate(client, candidate["id"], candidate["base_revision"])
    assert response.status_code == 200, response.text
    active = response.json()
    assert active["current"]["version_id"] == candidate["id"]
    assert manager.current_file("filter", "military")[0].read_bytes() == download.content
    current_download = client.get("/api/templates/filter/military/download")
    assert current_download.content == download.content
    # A different product can update independently before this one is restored.
    other = upload(client, "其他模板", product="other").json()["version"]
    assert activate(client, other["id"], other["base_revision"]).status_code == 200
    prior = next(r for r in active["versions"] if r["version"] == "初始版本")
    restored = activate(client, prior["id"], active["current"]["revision"])
    assert restored.status_code == 200, restored.text
    assert manager.current_file("filter", "military")[0].read_bytes() == old_file
    assert history(client, "other")["current"]["version_id"] == other["id"]
    after = yaml.safe_load(manager.catalog_path.read_text(encoding="utf-8"))
    assert after["product_types"]["filter"]["domains"]["civil"] == original["product_types"]["filter"]["domains"]["civil"]
    assert after["product_types"]["filter"]["domains"]["military"]["profile"] == "original_profile.yaml"
    assert (manager.mapping_root / "mapping.yaml").read_bytes() == rules
    assert (manager.template_root / "initial.docx").read_bytes() == old_file
    # Metadata survives a fresh manager instance; published files stay immutable.
    fresh = TemplateVersions(manager.catalog_path, manager.template_root, manager.mapping_root, manager.history_root)
    assert len(fresh.history("filter", "military")["versions"]) == 2


def test_missing_required_section_blocks_activation_without_catalog_change(version_api):
    client, state, _ = version_api
    before = state.template_versions.catalog_path.read_bytes()
    response = upload(client, required_heading=False)
    assert response.status_code == 200
    candidate = response.json()["version"]
    assert candidate["status"] == "invalid"
    assert any("工艺要求" in message for message in candidate["validation"]["problems"])
    assert activate(client, candidate["id"], candidate["base_revision"]).status_code == 400
    assert state.template_versions.catalog_path.read_bytes() == before


def test_stale_upload_and_changed_archived_file_cannot_replace_current_template(version_api):
    client, state, _ = version_api
    first = upload(client, "一").json()["version"]
    second = upload(client, "二").json()["version"]
    assert activate(client, first["id"], first["base_revision"]).status_code == 200
    current = history(client)["current"]
    assert activate(client, second["id"], second["base_revision"]).status_code == 409
    assert activate(client, second["id"], current["revision"]).status_code == 409
    third = upload(client, "三").json()["version"]
    (state.template_versions.history_root / third["id"] / "template.docx").write_bytes(template_bytes("已改动"))
    assert activate(client, third["id"], current["revision"]).status_code == 400
    assert history(client)["current"]["version_id"] == first["id"]


def test_renamed_docx_is_accepted_and_invalid_uploads_rejected(version_api):
    client, _, _ = version_api
    assert upload(client, filename="受控模板.doc").status_code == 200
    for filename, payload in [("模板.pdf", b"%PDF-"), ("模板.doc", b"invalid"), ("模板.docx", b"")]:
        response = client.post("/api/templates/versions",
            data={"product_type": "filter", "product_domain": "military"},
            files={"template": (filename, payload)})
        assert response.status_code == 400
    assert client.get("/api/templates/versions/not-a-version/download").status_code == 400
    assert client.get("/api/templates/versions/" + "a" * 32 + "/download").status_code == 404


def test_swapped_indicator_columns_are_not_treated_as_a_compatible_template(version_api):
    client, _, _ = version_api
    doc = Document(io.BytesIO(template_bytes()))
    doc.tables[0].cell(0, 1).text = "拟采用指标"
    doc.tables[0].cell(0, 2).text = "用户要求指标"
    data = io.BytesIO()
    doc.save(data)
    response = client.post("/api/templates/versions",
        data={"product_type": "filter", "product_domain": "military"},
        files={"template": ("columns.docx", data.getvalue())})
    assert response.status_code == 200
    version = response.json()["version"]
    assert any("列顺序" in problem for problem in version["validation"]["problems"])
    assert activate(client, version["id"], version["base_revision"]).status_code == 400


def section_template_bytes(*, required_heading=True):
    document = Document()
    document.add_heading("工艺要求", 1)
    document.add_paragraph("来源工艺要求")
    if required_heading:
        document.add_heading("技术指标", 1)
    document.add_heading("电气性能", 2)
    document.add_paragraph("按需求原文填写章节式技术要求。")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


@pytest.mark.parametrize("mode,expected", [("table", "invalid"), ("sections", "ready"), ("sectons", "invalid")])
def test_indicator_table_requirement_follows_explicit_mapping_mode(version_api, mode, expected):
    client, state, _ = version_api
    mapping_path = state.template_versions.mapping_root / "mapping.yaml"
    mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    mapping["technical_requirements_mode"] = mode
    mapping_path.write_text(yaml.safe_dump(mapping, allow_unicode=True), encoding="utf-8")
    response = client.post("/api/templates/versions",
        data={"product_type": "filter", "product_domain": "military"},
        files={"template": ("章节式模板.docx", section_template_bytes())})
    assert response.status_code == 200, response.text
    version = response.json()["version"]
    assert version["status"] == expected
    assert version["validation"]["technical_requirements_mode"] == mode
    activation = activate(client, version["id"], version["base_revision"])
    assert activation.status_code == (200 if expected == "ready" else 400), activation.text
    if expected == "ready":
        path = state.template_versions.current_file("filter", "military")[0]
        assert Document(path).tables == []
        assert "电气性能" in [paragraph.text for paragraph in Document(path).paragraphs]


@pytest.mark.parametrize("remove_rule", [False, True])
def test_section_mode_still_requires_unique_technical_destination(version_api, remove_rule):
    client, state, _ = version_api
    mapping_path = state.template_versions.mapping_root / "mapping.yaml"
    mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    mapping["technical_requirements_mode"] = "sections"
    if remove_rule:
        mapping["semantic_roles"].pop("performance_indicator")
    mapping_path.write_text(yaml.safe_dump(mapping, allow_unicode=True), encoding="utf-8")
    response = client.post("/api/templates/versions",
        data={"product_type": "filter", "product_domain": "military"},
        files={"template": ("缺技术目标.docx", section_template_bytes(required_heading=False))})
    assert response.status_code == 200, response.text
    version = response.json()["version"]
    assert version["status"] == "invalid"
    assert any("技术指标" in problem for problem in version["validation"]["problems"])
    assert activate(client, version["id"], version["base_revision"]).status_code == 400
