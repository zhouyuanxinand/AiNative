"""Evidence outcomes, durable stops and bounded retrieval (no model involved)."""
from copy import deepcopy

import pytest
from docx import Document

from src.service.rd_platform import completion
from src.service.rd_platform.completion_loop import run_completion, obligation_key


@pytest.fixture
def evidence(tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("安全性要求：试验温度 20℃\n", encoding="utf-8")
    source = {"id": "source1", "role": "tech", "path": str(path), "version": 1,
              "sha256": completion.sha256(path)}
    snapshot = {"sources": [source], "project_id": "p", "case_id": "c"}
    blocks = completion.evidence_blocks([source], tmp_path)
    tpl = Document()
    tpl.add_heading("安全性要求", 1)
    tpl.add_paragraph("【人工填写】")
    tpl.add_heading("验收要求", 1)  # Unmarked empty section must also be scanned.
    template = tmp_path / "tpl.docx"
    tpl.save(template)
    ledger = completion.build_completion_ledger(template, {}, blocks)
    return snapshot, ledger, blocks


def test_exact_evidence_accepted_but_unmarked_missing_section_stays_blocked(evidence):
    checkpoints = []
    ledger, session = run_completion(*evidence, checkpoints.append, lambda: False)
    assert next(r for r in ledger if r["title"] == "安全性要求")["status"] == "evidence_ready"
    assert next(r for r in ledger if r["title"] == "验收要求")["status"] == "blocked"
    assert session["stop_reason"] == "no_new_evidence"
    assert len(session["rounds"]) == 2
    assert session["usage"]["model_calls"] == 0
    assert checkpoints[-1]["completion_checkpoint"] == session


def test_converged_is_evidence_readiness_only(evidence):
    snapshot, ledger, blocks = evidence
    ledger, session = run_completion(snapshot, ledger[:1], blocks, lambda _: True, lambda: False)
    assert session["stop_reason"] == "converged"
    assert not session["remaining"]
    assert "delivery_approved" not in session


@pytest.mark.parametrize("changed", ["sha256", "version", "location", "quote", "match"])
def test_provider_cannot_forge_fixed_identity_or_approved_mapping(evidence, changed):
    snapshot, ledger, blocks = evidence
    candidate = deepcopy(ledger[0]["candidates"][0])
    candidate[changed] = {"line": 999} if changed == "location" else "forged"
    result, session = run_completion(snapshot, ledger[:1], blocks, lambda _: True, lambda: False,
                                     provider=lambda *_: [candidate])
    assert result[0]["status"] == "blocked"
    assert session["rounds"][0]["obligations"][0]["rejected"]


def test_conflicting_values_never_resolved_by_source_order(evidence):
    snapshot, ledger, blocks = evidence
    second = {**blocks[0], "quote": "安全性要求：试验温度 30℃", "location": {"line": 2}}
    blocks.append(second)
    ledger[0]["candidates"].append({**second, "quote": "试验温度 30℃", "match": "explicit_label"})
    result, session = run_completion(snapshot, ledger[:1], blocks, lambda _: True, lambda: False)
    assert result[0]["status"] == "blocked"
    assert session["stop_reason"] == "conflict"
    assert len(session["rounds"][0]["obligations"][0]["rejected"]) == 2


def test_changed_sources_invalidate_adoptions_and_save_terminal_receipt(evidence):
    snapshot, ledger, blocks = evidence
    events = []
    def provider(row, _):
        from pathlib import Path
        Path(snapshot["sources"][0]["path"]).write_text("changed", encoding="utf-8")
        return row["candidates"]
    result, session = run_completion(snapshot, ledger[:1], blocks, events.append, lambda: False, provider=provider)
    assert session["stop_reason"] == "source_invalid"
    assert result[0]["status"] == "blocked"
    assert not any(c["adopted"] for c in result[0]["candidates"])
    assert events[-1]["completion_checkpoint"]["stop_reason"] == "source_invalid"


def test_cancel_after_saved_round_retains_round_evidence(evidence):
    events, cancellation = [], [False]
    def progress(payload):
        events.append(payload)
        cancellation[0] = True
    _, session = run_completion(*evidence, progress, lambda: cancellation[0])
    assert session["stop_reason"] == "cancelled"
    assert len(session["rounds"]) == 1
    assert events[-1]["completion_checkpoint"]["rounds"] == session["rounds"]


@pytest.mark.parametrize("policy,reason", [({"max_queries": 1}, "budget_exhausted"),
                                          ({"max_rounds": 1}, "max_rounds")])
def test_budgets_stop_and_save(evidence, policy, reason):
    snapshot, ledger, blocks = evidence
    snapshot["completion_policy"] = policy
    events = []
    _, session = run_completion(snapshot, ledger, blocks, events.append, lambda: False,
                                provider=lambda row, _: row["candidates"])
    assert session["stop_reason"] == reason
    assert events[-1]["completion_checkpoint"]["stop_reason"] == reason


def local_requirements(tmp_path, count, empty_count=0):
    path = tmp_path / "many-requirements.txt"
    path.write_text("\n".join(f"要求{i}：试验值{i}" for i in range(count)), encoding="utf-8")
    source = {"id": "requirements", "role": "tech", "path": str(path), "version": 1,
              "sha256": completion.sha256(path)}
    snapshot = {"sources": [source], "project_id": "p", "case_id": "c"}
    blocks = completion.evidence_blocks([source], tmp_path)
    rows = [{"slot_id": f"missing-{i}", "title": f"待补章节{i}", "kind": "empty_section",
             "status": "blocked", "candidates": []} for i in range(empty_count)]
    rows.extend({"slot_id": f"requirement-{i}", "title": f"要求{i}", "kind": "case_requirement",
                 "requirement_id": str(i), "status": "evidence_ready",
                 "candidates": [{**block, "match": "case_requirement_exact_source", "adopted": True}]}
                for i, block in enumerate(blocks))
    return snapshot, rows, blocks


def test_full_local_source_review_does_not_spend_provider_queries(tmp_path):
    snapshot, ledger, blocks = local_requirements(tmp_path, 63, empty_count=54)
    events = []
    result, session = run_completion(snapshot, ledger, blocks, events.append, lambda: False)
    assert all(row["status"] == "evidence_ready" for row in result if row["kind"] == "case_requirement")
    assert all(row["status"] == "blocked" for row in result if row["kind"] == "empty_section")
    assert session["stop_reason"] == "no_new_evidence"
    assert session["usage"]["queries"] == 0
    assert session["usage"]["local_checks"] == 171
    assert session["usage"]["candidates"] == 63
    assert session["usage"]["model_calls"] == 0
    assert len(session["remaining"]) == 54
    assert events[-1]["completion_checkpoint"] == session


@pytest.mark.parametrize("count,reason,remaining", [(100, "converged", 0), (101, "budget_exhausted", 1)])
def test_provider_query_limit_allows_last_permitted_call(tmp_path, count, reason, remaining):
    snapshot, ledger, blocks = local_requirements(tmp_path, count)
    calls = []
    def provider(row, _):
        calls.append(row["requirement_id"])
        return row["candidates"]
    result, session = run_completion(snapshot, ledger, blocks, lambda _: True, lambda: False, provider=provider)
    assert session["stop_reason"] == reason
    assert session["usage"]["queries"] == 100
    assert len(calls) == 100
    assert len(session["remaining"]) == remaining
    assert sum(row["status"] == "evidence_ready" for row in result) == 100


def test_cached_provider_result_needs_no_additional_query_at_limit(evidence):
    snapshot, ledger, blocks = evidence
    snapshot["completion_policy"] = {"max_queries": 1}
    repeated = deepcopy(ledger[0])
    repeated["slot_id"] = "another-template-slot"
    result, session = run_completion(snapshot, [ledger[0], repeated], blocks, lambda _: True,
                                     lambda: False, provider=lambda row, _: row["candidates"])
    assert session["stop_reason"] == "converged"
    assert session["usage"]["queries"] == 1
    assert all(row["status"] == "evidence_ready" for row in result)


@pytest.mark.parametrize("count,reason", [(200, "converged"), (201, "budget_exhausted")])
def test_candidate_limit_allows_last_permitted_validation(tmp_path, count, reason):
    snapshot, ledger, blocks = local_requirements(tmp_path, count)
    result, session = run_completion(snapshot, ledger, blocks, lambda _: True, lambda: False)
    assert session["stop_reason"] == reason
    assert session["usage"]["queries"] == 0
    assert session["usage"]["candidates"] == 200
    assert sum(row["status"] == "evidence_ready" for row in result) == 200
    assert len(session["remaining"]) == count - 200


def test_partial_candidate_scan_never_adopts_or_resumes_past_unchecked_conflict(tmp_path):
    snapshot, ledger, blocks = local_requirements(tmp_path, 2)
    row = ledger[0]
    row["candidates"] = [{**block, "match": "explicit_label", "adopted": False} for block in blocks]
    snapshot["completion_policy"] = {"max_candidates": 1}
    events = []
    result, session = run_completion(snapshot, [row], blocks, events.append, lambda: False)
    assert session["stop_reason"] == "budget_exhausted"
    assert session["usage"]["candidates"] == 1
    assert result[0]["status"] == "blocked"
    assert len(result[0]["candidates"]) == 2
    assert all(candidate["adopted"] is False for candidate in result[0]["candidates"])
    assert session["rounds"][0]["obligations"][0]["accepted"] == []
    assert session["rounds"][0]["obligations"][0]["candidate_scan_complete"] is False
    assert len(session["remaining"]) == 1
    assert events[-1]["completion_checkpoint"] == session

    resumed, receipt = run_completion(snapshot, [row], blocks, lambda _: True, lambda: False, resume=session)
    assert resumed[0]["status"] == "blocked"
    assert receipt["stop_reason"] == "budget_exhausted"
    assert receipt["usage"]["candidates"] == 1
    assert len(receipt["remaining"]) == 1


def test_deadline_permission_and_initial_cancel_have_receipts(evidence):
    for kwargs, reason in [({"permission_valid": lambda: False}, "permission_revoked"),
                           ({"clock": iter([0, 121, 122]).__next__}, "deadline_exceeded")]:
        events = []
        _, session = run_completion(*evidence, events.append, lambda: False, **kwargs)
        assert session["stop_reason"] == reason
        assert events[-1]["completion_checkpoint"]["stop_reason"] == reason


def test_stable_keys_ignore_scan_index_and_resume_never_readopts_rejections(evidence):
    snapshot, ledger, blocks = evidence
    row = ledger[0]
    assert obligation_key(row) == obligation_key({**row, "id": "new-display-id"})
    row["candidates"][0]["role"] = "reference"
    blocks[0]["role"] = "reference"
    _, first = run_completion(snapshot, ledger[:1], blocks, lambda _: True, lambda: False)
    _, resumed = run_completion(snapshot, ledger[:1], blocks, lambda _: True, lambda: False, resume=first)
    assert resumed["rounds"][-1]["obligations"][0]["rejected"][0]["reason"] == "previously_rejected"
    snapshot["sources"][0]["version"] = 2
    with pytest.raises(completion.EvidenceBlocked, match="恢复"):
        run_completion(snapshot, ledger, blocks, lambda _: True, lambda: False, resume=first)


def test_table_field_uses_exact_source_but_ambiguous_columns_remain_unfilled(evidence):
    snapshot, ledger, blocks = evidence
    row = deepcopy(ledger[0])
    row.update(kind="empty_table_cell", column_count=2, field_label="安全性要求")
    result, session = run_completion(snapshot, [row], blocks, lambda _: True, lambda: False)
    assert result[0]["status"] == "evidence_ready"
    row["column_count"] = 4
    result, session = run_completion(snapshot, [row], blocks, lambda _: True, lambda: False)
    assert result[0]["status"] == "blocked"
    assert session["rounds"][0]["obligations"][0]["rejected"][0]["reason"] == "table_column_mapping_required"


def test_resumed_source_invalidation_does_not_rewrite_saved_rounds(evidence):
    from pathlib import Path
    snapshot, ledger, blocks = evidence
    saved = []
    def checkpoint(payload):
        saved.append(payload["completion_checkpoint"])
        return False
    run_completion(snapshot, ledger, blocks, checkpoint, lambda: False)
    original = deepcopy(saved[0])
    Path(snapshot["sources"][0]["path"]).write_text("source changed after persisted round", encoding="utf-8")
    result, session = run_completion(snapshot, ledger, blocks, lambda _: True, lambda: False, resume=saved[0])
    assert session["stop_reason"] == "source_invalid"
    assert session["rounds"] == original["rounds"]
    assert saved[0] == original
    assert all(c.get("adopted") is False for row in result for c in row.get("candidates", []))
