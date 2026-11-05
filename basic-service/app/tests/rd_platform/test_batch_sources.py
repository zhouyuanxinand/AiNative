"""A batch preserves every file and adopts only explicit primary inputs."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from service.rd_platform.store import RdError
from test_http import make_client
from test_store import case_project, issue, new_store


def manifest():
    return [
        {"id": "queued-tech", "name": "需求.txt", "role": "tech", "primary": True},
        {"id": "queued-extra-tech", "name": "补充需求.txt", "role": "tech", "primary": False},
        {"id": "queued-spec", "name": "产品规范.txt", "role": "spec", "primary": True},
        {"id": "queued-extra-spec", "name": "补充规范.txt", "role": "spec", "primary": False},
    ]


def files_for(items):
    return [(item["name"], ("source bytes " + item["id"]).encode()) for item in items]


def batch(store, project, items=None, files=None, *, key="batch", actor="owner", cid=None):
    items = manifest() if items is None else items
    return store.add_sources(actor, project["id"], cid or project["cases"][0]["id"], project["version"],
                             key, items, files_for(items) if files is None else files)


def http_case(client):
    project = client.post("/api/rd/projects", json={"title": "批量资料项目"}).json()
    response = client.post(f"/api/rd/projects/{project['id']}/commands",
        json={"expected_version": project["version"], "command": "create_case",
              "data": {"scenario_id": "taskbook", "title": "批量资料案例"}},
        headers={"Idempotency-Key": "case"})
    assert response.status_code == 200, response.text
    return response.json()


def post_batch(client, project, items=None, files=None, *, key="batch", headers=None):
    items = manifest() if items is None else items
    pairs = files_for(items) if files is None else files
    case = project["cases"][0]
    return client.post(f"/api/rd/projects/{project['id']}/cases/{case['id']}/sources/batch",
        data={"expected_version": project["version"], "manifest": json.dumps(items, ensure_ascii=False)},
        files=[("files", (name, content, "text/plain")) for name, content in pairs],
        headers={"Idempotency-Key": key, **(headers or {})})


def test_batch_keeps_all_files_and_adopts_one_primary_per_role_once(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    old_revision = project["cases"][0]["input_revision"]
    result = batch(store, project)
    case = result["cases"][0]
    assert result["version"] == project["version"] + 1
    assert case["input_revision"] == old_revision + 1
    assert len(case["sources"]) == 4
    by_client = {source["client_id"]: source for source in case["sources"]}
    assert set(by_client) == {item["id"] for item in manifest()}
    assert case["source_selection"] == {"tech": by_client["queued-tech"]["id"], "spec": by_client["queued-spec"]["id"]}
    for item in manifest():
        source = by_client[item["id"]]
        assert source["id"] != item["id"]
        assert source["role"] == (item["role"] if item["primary"] else "reference")
        assert source["document_category"] == item["role"]
        assert store.source_path("owner", result["id"], case["id"], source["id"]).read_bytes() == ("source bytes " + item["id"]).encode()
    active = store._active_sources(case)
    assert [source["role"] for source in active].count("tech") == 1
    assert [source["role"] for source in active].count("spec") == 1
    assert len(active) == 4
    assert result["events"][-1]["type"] == "sources_added"
    assert new_store(tmp_path).get_project("owner", result["id"]) == result


def test_supplementary_batch_keeps_existing_primary_selections(tmp_path):
    store = new_store(tmp_path)
    project = batch(store, case_project(store))
    selected = deepcopy(project["cases"][0]["source_selection"])
    items = [{"id": "new-extra", "name": "新补充需求.txt", "role": "tech", "primary": False}]
    result = batch(store, project, items, key="supplements")
    assert result["cases"][0]["source_selection"] == selected
    extra = result["cases"][0]["sources"][-1]
    assert extra["role"] == "reference" and extra["document_category"] == "tech"
    assert result["cases"][0]["input_revision"] == project["cases"][0]["input_revision"] + 1


@pytest.mark.parametrize("role", ["tech", "spec"])
def test_batch_requires_explicit_primary_when_category_has_no_current_primary(tmp_path, role):
    store = new_store(tmp_path)
    project = case_project(store)
    items = [{"id": "unselected", "name": "待确认主文件.txt", "role": role, "primary": False}]
    with pytest.raises(RdError) as failure:
        batch(store, project, items)
    assert failure.value.status == 422 and "主文件" in str(failure.value)
    assert store.get_project("owner", project["id"]) == project
    assert not [path for path in (tmp_path / "assets/sources").rglob("*") if path.is_file()]


def test_missing_primary_in_one_category_rejects_the_entire_http_batch(tmp_path):
    client = make_client(tmp_path)
    project = http_case(client)
    items = manifest()
    items[2]["primary"] = False
    response = post_batch(client, project, items)
    assert response.status_code == 422 and "主文件" in response.text
    assert client.get(f"/api/rd/projects/{project['id']}").json() == project


def test_reference_only_batch_does_not_require_an_unrelated_primary(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    items = [{"id": "reference", "name": "补充资料.txt", "role": "reference", "primary": False}]
    result = batch(store, project, items)
    assert len(result["cases"][0]["sources"]) == 1
    assert result["cases"][0]["sources"][0]["role"] == "reference"
    assert result["cases"][0]["source_selection"] == project["cases"][0]["source_selection"]


def test_batch_replay_precedes_version_check_and_never_duplicates_files(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    first = batch(store, project)
    assert batch(new_store(tmp_path), project) == first
    assert len([path for path in (tmp_path / "assets/sources").rglob("*") if path.is_file()]) == 4
    assert len(new_store(tmp_path).get_project("owner", project["id"])["cases"][0]["sources"]) == 4
    changed = manifest()
    changed[1]["role"] = "reference"
    with pytest.raises(RdError) as failure:
        batch(store, project, changed)
    assert failure.value.status == 409


@pytest.mark.parametrize("change", ["duplicate-id", "duplicate-primary", "unknown-role", "reference-primary", "nonboolean-primary", "forged-field", "missing-content", "filename-mismatch", "file-count"])
def test_invalid_batch_is_rejected_before_any_source_is_saved(tmp_path, change):
    store = new_store(tmp_path)
    project = case_project(store)
    items, pairs = manifest(), files_for(manifest())
    if change == "duplicate-id": items[1]["id"] = items[0]["id"]
    elif change == "duplicate-primary": items[1]["primary"] = True
    elif change == "unknown-role": items[1]["role"] = "admin"
    elif change == "reference-primary": items[1].update(role="reference", primary=True)
    elif change == "nonboolean-primary": items[1]["primary"] = "false"
    elif change == "forged-field": items[0]["path"] = "outside"
    elif change == "missing-content": pairs[-1] = (pairs[-1][0], b"")
    elif change == "filename-mismatch": pairs[-1] = ("another.txt", pairs[-1][1])
    elif change == "file-count": pairs.pop()
    with pytest.raises(RdError) as failure:
        batch(store, project, items, pairs)
    assert failure.value.status == 422
    assert store.get_project("owner", project["id"]) == project
    assert not list((tmp_path / "assets/sources").rglob("*"))


def test_failed_batch_file_write_rolls_back_metadata_and_new_bytes(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    project = case_project(store)
    original = Path.write_bytes
    calls = 0
    def fail_second(path, content):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated full disk")
        return original(path, content)
    monkeypatch.setattr(Path, "write_bytes", fail_second)
    with pytest.raises(OSError):
        batch(store, project)
    assert store.get_project("owner", project["id"]) == project
    assert not [path for path in (tmp_path / "assets/sources").rglob("*") if path.is_file()]


def test_batch_respects_cas_case_identity_and_project_access(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    updated = issue(store, project, "save_context", {"context": {"product_series": "new"}})
    for params, expected in [({}, 409), ({"cid": "other-case"}, 404), ({"actor": "outsider"}, 404)]:
        with pytest.raises(RdError) as failure:
            batch(store, updated if params else project, **params)
        assert failure.value.status == expected
    assert len(store.get_project("owner", project["id"])["cases"][0]["sources"]) == 0


def test_batch_rejects_completed_case(tmp_path):
    store = new_store(tmp_path)
    project = case_project(store)
    with store._transaction() as db:
        saved = store._load(db, project["id"])
        saved["cases"][0]["status"] = "completed"
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(saved), project["id"]))
    with pytest.raises(RdError) as failure:
        batch(store, project)
    assert failure.value.status == 409


def test_batch_http_returns_project_and_keeps_original_single_upload_contract(tmp_path):
    client = make_client(tmp_path)
    project = http_case(client)
    response = post_batch(client, project)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["id"] == project["id"] and len(result["cases"][0]["sources"]) == 4
    assert post_batch(client, project).json() == result
    case = result["cases"][0]
    old_spec = case["source_selection"]["spec"]
    single = client.post(f"/api/rd/projects/{result['id']}/cases/{case['id']}/sources",
        data={"expected_version": result["version"], "role": "tech"}, files={"file": ("新需求.txt", b"replacement")},
        headers={"Idempotency-Key": "single"})
    assert single.status_code == 200, single.text
    updated = single.json()["cases"][0]
    assert updated["source_selection"]["tech"] == updated["sources"][-1]["id"]
    assert updated["source_selection"]["spec"] == old_spec


def test_batch_http_limits_and_cross_origin_rejection_do_not_partially_save(tmp_path):
    client = make_client(tmp_path)
    project = http_case(client)
    assert post_batch(client, project, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    oversized = [(item["name"], b"x" * 400) for item in manifest()]
    assert post_batch(client, project, files=oversized).status_code == 413
    assert client.get(f"/api/rd/projects/{project['id']}").json() == project
