"""Review archives remain reproducible and edits never overwrite generation evidence."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil

from docx import Document
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jonhon_taskbook.review_store import ReviewStore, ReviewConflictError, digest
from jonhon_taskbook.review_document import document_projection
from jonhon_taskbook.review_checks import review_links
from src.controller import review_controller, taskbook_controller


def write_docx(path, text="接触电阻不得大于 8 mΩ。"):
    document = Document()
    document.add_heading("技术要求", 1)
    document.add_paragraph(text)
    document.save(path)
    return path


@pytest.fixture
def archive(tmp_path):
    jid = "1234567890"
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    jobdir = uploads / jid
    jobdir.mkdir(parents=True)
    outputs.mkdir()
    files = {}
    for key in ("tech", "spec", "template", "effective_template"):
        path = write_docx(jobdir / (key + ".docx"))
        files[key] = {"name": path.name, "sha256": digest(path)}
    for key, text in {
        "profile": "technical_requirements_mode: sections\n",
        "mapping": "categories: {}\n",
        "rule_qa_gate": "block_if: {}\nwarn_if: {}\n",
        "rule_development_process_policy": "section_retention_rules: []\n",
    }.items():
        path = jobdir / (key + ".yaml")
        path.write_text(text, encoding="utf-8")
        files[key] = {"name": path.name, "sha256": digest(path)}
    out = write_docx(outputs / "taskbook.docx")
    out.with_suffix(".coverage_ledger.json").write_text(json.dumps({
        "source_file": "tech.docx", "blocks": [{
            "block_id": "src-1", "block_type": "paragraph", "source_section": "技术要求",
            "summary": "接触电阻", "raw_text": "接触电阻不得大于 8 mΩ。",
            "source_body_index": 1, "covered": True, "output_body_indices": [1],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    job = {"status": "done", "result": {"out": str(out), "meta": {}, "delivery_status": "approved"},
           "replay": {"files": files, "selection": {"product_type": "filter_connector"},
                      "options": {"development_process": "全新", "product_series": "J599L"}}}
    roots = {"upload_dir": uploads, "output_dir": outputs}
    store = ReviewStore(outputs / "reviews")
    store.ensure_review(jid, job, roots)
    return store, jid, job, roots


def test_archive_survives_expired_uploads_and_reopening(archive):
    store, jid, _, roots = archive
    original = store.revision_path(jid, "baseline").read_bytes()
    source = store.asset_path(jid, "tech").read_bytes()
    shutil.rmtree(roots["upload_dir"])
    reopened = ReviewStore(store.root)
    assert reopened.ensure_review(jid)["current_revision_id"] == "baseline"
    assert reopened.asset_path(jid, "tech").read_bytes() == source
    assert reopened.revision_path(jid, "baseline").read_bytes() == original


def test_old_missing_sources_are_explicit_not_taken_from_current_template(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    out = write_docx(outputs / "old.docx")
    current = write_docx(tmp_path / "current.docx", "不应作为历史依据")
    store = ReviewStore(outputs / "reviews")
    bundle = store.ensure_review("1234567890", {"status": "blocked", "result": {"out": str(out)},
        "replay": {"selection": {"template_path": str(current)}, "files": {}}},
        {"upload_dir": tmp_path / "uploads", "output_dir": outputs})
    assert not any(item["available"] for item in bundle["assets"])
    assert any("历史任务" in warning for warning in bundle["warnings"])


def test_tampered_source_is_not_archived(tmp_path, archive):
    _, _, job, roots = archive
    job["replay"]["files"]["tech"]["sha256"] = "wrong"
    store = ReviewStore(tmp_path / "separate")
    bundle = store.ensure_review("1234567890", job, roots)
    tech = next(item for item in bundle["assets"] if item["id"] == "tech")
    assert not tech["available"] and "哈希" in tech["missing_reason"]


def test_two_writers_cannot_overwrite_each_other(archive, tmp_path):
    store, jid, _, _ = archive
    baseline = store.revision_path(jid, "baseline").read_bytes()
    changed = write_docx(tmp_path / "changed.docx", "接触电阻不得大于 5 mΩ。")
    def save():
        try:
            return ReviewStore(store.root).save_revision(jid, "baseline", changed)
        except ReviewConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: save(), range(2)))
    assert results.count("conflict") == 1
    assert len(store.get_review(jid)["revisions"]) == 2
    assert store.revision_path(jid, "baseline").read_bytes() == baseline


def test_restore_creates_revision_without_erasing_history(archive, tmp_path):
    store, jid, _, _ = archive
    edited = store.save_revision(jid, "baseline", write_docx(tmp_path / "changed.docx", "人工改写"))
    restored = store.restore_revision(jid, "baseline", edited["current_revision_id"])
    assert len(restored["revisions"]) == 3
    assert restored["current_revision_id"] not in {"baseline", edited["current_revision_id"]}
    assert store.revision_path(jid, restored["current_revision_id"]).read_bytes() == store.revision_path(jid, "baseline").read_bytes()


def test_recheck_uses_current_content_and_never_rewrites_baseline(archive, tmp_path, monkeypatch):
    from jonhon_taskbook import llm_client
    store, jid, _, _ = archive
    before = store.revision_path(jid, "baseline").read_bytes()
    # No generation route is invoked; checks operate on immutable XML and archived rules.
    monkeypatch.setattr(llm_client, "model_scope", lambda *args: pytest.fail("must not call model"))
    baseline_report = store.check_revision(jid, "baseline")
    assert baseline_report["results"]["coverage"]["covered"] == 1
    edited = store.save_revision(jid, "baseline", write_docx(tmp_path / "changed.docx", "此段已经删除原指标。"))
    report = store.check_revision(jid, edited["current_revision_id"])
    assert report["results"]["coverage"]["covered"] == 0
    assert any(item["code"] == "source_unverified" for item in report["issues"])
    assert report["delivery_approved"] is False
    assert store.revision_path(jid, "baseline").read_bytes() == before
    assert store.revision(jid, "baseline")["checks"] == baseline_report


def test_links_recompute_after_edits_instead_of_using_original_indices(archive, tmp_path):
    store, jid, _, _ = archive
    links = review_links(store, jid, "baseline")["links"]
    requirement = next(item for item in links if item["source_asset_id"] == "tech" and "接触电阻" in item["label"])
    assert requirement["status"] == "verified"
    revised = store.save_revision(jid, "baseline", write_docx(tmp_path / "changed.docx", "原位置换成了其他要求。"))
    links = review_links(store, jid, revised["current_revision_id"])["links"]
    requirement = next(item for item in links if item["source_asset_id"] == "tech" and "接触电阻" in item["label"])
    assert requirement["status"] == "unmapped" and requirement["output_element_ids"] == []


def test_review_api_edits_conflicts_annotations_and_download(archive, monkeypatch):
    store, jid, job, roots = archive
    state = taskbook_controller._RuntimeState()
    state.output_dir = roots["output_dir"]
    state.upload_dir = roots["upload_dir"]
    state.jobs[jid] = job
    monkeypatch.setattr(taskbook_controller, "_STATE", state)
    app = FastAPI()
    app.include_router(review_controller.router)
    with TestClient(app) as client:
        document = client.get(f"/api/review/{jid}/document?revision_id=baseline").json()
        paragraph = next(item for item in document["blocks"] if "接触电阻" in item.get("text", ""))
        response = client.post(f"/api/review/{jid}/revisions", json={"expected_revision_id": "baseline", "operations": [
            {"op": "replace_text", "element_id": paragraph["id"], "text": "接触电阻不得大于 5 mΩ。"}]})
        assert response.status_code == 200, response.text
        rid = response.json()["current_revision_id"]
        assert client.post(f"/api/review/{jid}/revisions/baseline/restore", json={"expected_revision_id": "baseline"}).status_code == 409
        assert client.get(f"/api/review/{jid}/revisions/{rid}/download").content == store.revision_path(jid, rid).read_bytes()
        newdoc = client.get(f"/api/review/{jid}/document?revision_id={rid}").json()
        newpara = next(item for item in newdoc["blocks"] if "接触电阻" in item.get("text", ""))
        saved = client.post(f"/api/review/{jid}/revisions/{rid}/annotations", json={"element_id": newpara["id"], "status": "checked", "note": "已核对"})
        assert saved.status_code == 200
        assert saved.json()["annotations"][0]["note"] == "已核对"
        assert store.revision(jid, "baseline")["annotations"] == []
        assert client.post(f"/api/review/{jid}/revisions/{rid}/annotations", json={"element_id": paragraph["id"], "status": "checked"}).status_code == 400


def test_paths_are_limited_to_archive_and_known_revision(archive):
    store, jid, _, _ = archive
    for invalid in ("../secret", "/secret", "..", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            store.directory(invalid)
        with pytest.raises(ValueError):
            store.revision_path(jid, invalid)
    with pytest.raises(FileNotFoundError):
        store.asset_path(jid, "unknown")


def test_indicator_value_change_is_detected_against_archived_decision(archive, tmp_path):
    _, jid, job, roots = archive
    original = Path(job["result"]["out"])
    document = Document(original)
    table = document.add_table(rows=2, cols=4)
    for cell, value in zip(table.rows[0].cells, ("项目", "用户要求", "拟采用指标", "依据")):
        cell.text = value
    for cell, value in zip(table.rows[1].cells, ("接触电阻", "≤8 mΩ", "≤8 mΩ", "技术协议")):
        cell.text = value
    document.save(original)
    original.with_suffix(".indicator_audit.json").write_text(json.dumps({"comparison_decisions": [{
        "indicator_name": "接触电阻", "user_requirement": "≤8 mΩ", "adopted_requirement": "≤8 mΩ", "basis": "技术协议",
    }]}, ensure_ascii=False), encoding="utf-8")
    store = ReviewStore(tmp_path / "numeric-review")
    store.ensure_review(jid, job, roots)
    assert store.check_revision(jid, "baseline")["results"]["indicator_values"]["passed"]
    document.tables[0].rows[1].cells[2].text = "≤80 mΩ"
    changed = tmp_path / "numeric.docx"
    document.save(changed)
    bundle = store.save_revision(jid, "baseline", changed)
    report = store.check_revision(jid, bundle["current_revision_id"])
    assert report["status"] == "failed"
    defect = next(item for item in report["issues"] if item["code"] == "indicator_indicator_value_mismatch")
    assert "≤80 mΩ" in defect["message"] and "≤8 mΩ" in defect["message"]
    assert not store.revision_path(jid, bundle["current_revision_id"]).with_suffix(".business_value_audit.json").exists()


def test_check_execution_error_is_distinct_from_document_failure(archive, monkeypatch):
    import jonhon_taskbook.review_checks as checks
    store, jid, _, _ = archive
    monkeypatch.setattr(checks, "_ledger", lambda *args: (_ for _ in ()).throw(RuntimeError("forced")))
    report = store.check_revision(jid, "baseline")
    assert report["status"] == "error"
    assert report["issues"][-1]["code"] == "check_execution_error"


def test_repeated_source_text_never_claims_unique_source_location(archive, tmp_path):
    _, jid, job, roots = archive
    tech = roots["upload_dir"] / jid / "tech.docx"
    document = Document(tech)
    document.add_paragraph("接触电阻不得大于 8 mΩ。")
    document.save(tech)
    job["replay"]["files"]["tech"]["sha256"] = digest(tech)
    store = ReviewStore(tmp_path / "repeated")
    store.ensure_review(jid, job, roots)
    links = review_links(store, jid, "baseline")["links"]
    matching = [item for item in links if item["source_asset_id"] == "tech" and "接触电阻" in item["label"]]
    assert len(matching) == 2 and all(item["status"] == "candidate" for item in matching)


def test_coverage_does_not_resolve_duplicate_output_positions(archive, tmp_path):
    store, jid, _, _ = archive
    changed = tmp_path / "duplicate.docx"
    write_docx(changed)
    document = Document(changed)
    document.add_heading("其他要求", 1)
    document.add_paragraph("接触电阻不得大于 8 mΩ。")
    document.save(changed)
    bundle = store.save_revision(jid, "baseline", changed)
    links = review_links(store, jid, bundle["current_revision_id"])["links"]
    requirement = next(item for item in links if item["source_asset_id"] == "tech" and "接触电阻" in item["label"])
    assert requirement["status"] == "candidate"
    assert len(requirement["output_element_ids"]) == 2


def test_tampered_evidence_is_not_used_for_revision_checks(archive, tmp_path):
    _, jid, job, roots = archive
    evidence = Path(job["result"]["out"]).with_suffix(".coverage_ledger.json")
    job["sidecar_sha256"] = {".coverage_ledger.json": digest(evidence)}
    evidence.write_text('{"source_file":"tech.docx","blocks":[]}', encoding="utf-8")
    store = ReviewStore(tmp_path / "tampered-evidence")
    bundle = store.ensure_review(jid, job, roots)
    item = next(item for item in bundle["assets"] if item["id"] == "evidence_coverage_ledger")
    assert item["available"] is False and "哈希" in item["missing_reason"]
    report = store.check_revision(jid, "baseline")
    assert any(issue["code"] == "coverage_evidence_missing" for issue in report["issues"])


@pytest.mark.parametrize("process,expected_exclusion", [("全新", False), ("改型II", True)])
def test_template_omission_respects_archived_process_rule(archive, tmp_path, process, expected_exclusion):
    import yaml
    _, jid, job, roots = archive
    jobdir = roots["upload_dir"] / jid
    template = jobdir / "effective_template.docx"
    document = Document(template)
    document.add_heading("产品需求分解（QFD质量功能分解）", 1)
    document.add_paragraph("质量功能分解的固定模板要求。")
    document.save(template)
    policy = jobdir / "rule_development_process_policy.yaml"
    policy.write_text(yaml.safe_dump({"section_retention_rules": [{
        "id": "qfd", "label": "产品需求分解", "semantic_titles": ["产品需求分解"],
        "keep_processes": ["全新"], "linked_semantic_titles": [],
    }]}, allow_unicode=True), encoding="utf-8")
    for key in ("effective_template", "rule_development_process_policy"):
        job["replay"]["files"][key]["sha256"] = digest(jobdir / job["replay"]["files"][key]["name"])
    job["replay"]["options"]["development_process"] = process
    store = ReviewStore(tmp_path / "rule-review")
    store.ensure_review(jid, job, roots)
    links = review_links(store, jid, "baseline")["links"]
    qfd = next(item for item in links if item["source_asset_id"] == "effective_template" and "固定模板要求" in item["label"])
    assert bool(qfd.get("rule_excluded")) == expected_exclusion
    report = store.check_revision(jid, "baseline")
    assert any(issue["code"] == "process_section_missing" for issue in report["issues"]) is not expected_exclusion
