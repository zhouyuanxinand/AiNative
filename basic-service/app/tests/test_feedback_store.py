"""Feedback survives restarts and administrative edits retain generation evidence."""
import importlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest


def store_at(path):
    return importlib.import_module("jonhon_taskbook.feedback_store").FeedbackStore(path)


def fields(**overrides):
    return {"jid": "123456789a", "username": "张工", "rating": "good", "comment": "结果可用", **overrides}


def snapshot():
    return {"jid": "123456789a", "job_status": "done", "parameters": {"product_type": "filter_connector"},
            "files": {"tech": "原技术要求.docx", "spec": "原规格书.docx", "output": "任务书.docx", "report": "任务书.report.html"},
            "delivery_status": "approved", "qa_ok": True, "error": ""}


def test_reopened_store_keeps_server_time_and_immutable_snapshot(tmp_path):
    before = datetime.now(timezone.utc)
    store = store_at(tmp_path / "feedback.sqlite3")
    evidence = snapshot()
    created = store.create(fields(), snapshot=evidence)
    evidence["parameters"]["product_type"] = "changed"
    after = datetime.now(timezone.utc)
    assert before <= datetime.fromisoformat(created["created_at"]) <= after
    assert created["updated_at"] == created["created_at"]
    assert created["status"] == "open" and created["version"] == 1
    reopened = store_at(store.path)
    edited = reopened.update(created["id"], {"username": "李工", "rating": "average", "comment": "需完善",
        "status": "in_progress", "handling_note": "已安排核查", "expected_version": 1})
    assert edited["snapshot"]["parameters"]["product_type"] == "filter_connector"
    assert edited["created_at"] == created["created_at"] and edited["updated_at"] >= created["updated_at"]
    assert edited["version"] == 2 and edited["handling_note"] == "已安排核查"
    assert store.get(created["id"]) == edited


def test_request_id_deduplicates_across_connections_and_rejects_changed_payload(tmp_path):
    store = store_at(tmp_path / "feedback.sqlite3")
    payload = fields(request_id=str(uuid.uuid4()))
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda _: store_at(store.path).create(payload, snapshot=snapshot()), range(4)))
    assert len({record["id"] for record in records}) == 1
    assert store.search()["total"] == 1
    conflict = importlib.import_module("jonhon_taskbook.feedback_store").FeedbackConflictError
    with pytest.raises(conflict):
        store.create({**payload, "comment": "另一个反馈"}, snapshot=snapshot())


def test_filtered_stats_cover_all_matched_rows_and_search_treats_percent_literally(tmp_path):
    store = store_at(tmp_path / "feedback.sqlite3")
    store.create(fields(comment="评审 100%"), snapshot=snapshot())
    second = store.create(fields(username="张工", rating="average", comment="评审需完善"), snapshot=snapshot())
    store.update(second["id"], {"status": "in_progress", "expected_version": 1})
    third = store.create(fields(username="王工", rating="poor", comment="评审有误"), snapshot=snapshot())
    store.update(third["id"], {"status": "resolved", "expected_version": 1})
    store.create(fields(username="其他", comment="无关"), snapshot=snapshot())
    result = store.search(q="评审", page_size=1)
    assert result["total"] == 3 and len(result["items"]) == 1
    assert result["stats"] == {"total": 3, "good": 1, "average": 1, "poor": 1,
        "good_rate": 1 / 3, "open": 1, "in_progress": 1, "resolved": 1}
    assert result["items"][0]["id"] != store.search(q="评审", page_size=1, page=2)["items"][0]["id"]
    assert store.search(q="100%")["total"] == 1
    assert store.search(q="' OR 1=1 --")["total"] == 0
    assert store.search(rating="average", status="in_progress")["total"] == 1
    today = datetime.now(timezone.utc).date().isoformat()
    assert store.search(date_from=today, date_to=today)["total"] == 4
    assert store.search(date_to="2000-01-01")["total"] == 0


def test_stale_versions_cannot_overwrite_or_delete_and_deleted_rows_disappear(tmp_path):
    store = store_at(tmp_path / "feedback.sqlite3")
    conflict = importlib.import_module("jonhon_taskbook.feedback_store").FeedbackConflictError
    record = store.create(fields(), snapshot=snapshot())
    store.update(record["id"], {"comment": "最新", "expected_version": 1})
    with pytest.raises(conflict):
        store.update(record["id"], {"comment": "过期", "expected_version": 1})
    with pytest.raises(conflict):
        store.delete(record["id"], 1)
    assert store.get(record["id"])["comment"] == "最新"
    assert store.delete(record["id"], 2) == {"ok": True}
    with pytest.raises(FileNotFoundError):
        store.get(record["id"])
    assert store.search()["total"] == store.search()["stats"]["total"] == 0


@pytest.mark.parametrize("change", [{"username": " "}, {"username": "x" * 81}, {"rating": "excellent"},
    {"comment": "x" * 4001}, {"created_at": "1999-01-01"}, {"snapshot": {}}, {"request_id": "not-uuid"},
    {"status": "resolved"}, {"username": 3}])
def test_public_create_rejects_invalid_and_server_owned_fields(tmp_path, change):
    store = store_at(tmp_path / "feedback.sqlite3")
    with pytest.raises(ValueError):
        store.create(fields(**change), snapshot=snapshot())
    assert store.search()["total"] == 0


@pytest.mark.parametrize("filters", [{"rating": "wrong"}, {"status": "wrong"}, {"page": 0},
    {"page_size": 101}, {"date_from": "wrong"}, {"date_from": "2026-10-02", "date_to": "2026-10-01"}])
def test_search_rejects_invalid_ranges(tmp_path, filters):
    with pytest.raises(ValueError):
        store_at(tmp_path / "feedback.sqlite3").search(**filters)
