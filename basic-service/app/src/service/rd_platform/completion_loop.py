"""Bounded evidence-only completion inside one delegated worker action.

The provider retrieves fixed source quotes; it cannot supply engineering facts or
approve a mapping. Checkpoints are full, replayable session receipts, persisted
by Store.progress under its current claim fence before any further round.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import time

from . import completion


DEFAULT_POLICY = {"max_rounds": 3, "max_queries": 100, "max_candidates": 200, "max_seconds": 120}
RULE = {"id": "fixed-local-exact-evidence", "version": 1,
        "mapping": ["explicit_label", "exact_heading", "case_requirement_exact_source"]}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def obligation_key(entry):
    return digest({key: entry.get(key) for key in
                   ("slot_id", "semantic_path", "kind", "location", "field_label", "requirement_id")})


def fixed_policy(snapshot):
    raw = snapshot.get("completion_policy") or {}
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT_POLICY):
        raise completion.EvidenceBlocked("补缺策略包含未知控制值")
    policy = dict(DEFAULT_POLICY)
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise completion.EvidenceBlocked("补缺运行预算必须为正数")
        if key != "max_seconds" and (not isinstance(value, int) or value > DEFAULT_POLICY[key]):
            raise completion.EvidenceBlocked("补缺控制值超过受托策略上限")
        policy[key] = min(value, DEFAULT_POLICY[key])
    total = (snapshot.get("budget") or {}).get("max_seconds")
    if total is not None:
        if isinstance(total, bool) or not isinstance(total, (int, float)) or total <= 0:
            raise completion.EvidenceBlocked("工作包总预算无效")
        policy["max_seconds"] = min(policy["max_seconds"], total)
    return policy


def run_completion(snapshot, ledger, blocks, progress, cancelled, *, provider=None,
                   resume=None, clock=time.monotonic, permission_valid=lambda: True, asset_refs=None):
    """Return a ledger plus a durable receipt. No model calls/tokens are implied.

    ``provider`` is a trusted in-process retrieval adapter, never request code.
    It receives only obligations and fixed blocks, and returns candidate lists
    keyed by stable obligation key. The default is the current local lookup.
    """
    policy = fixed_policy(snapshot)
    refs = [{key: source.get(key) for key in ("id", "version", "sha256", "role")}
            for source in snapshot.get("sources", [])]
    input_ref = digest({"project_id": snapshot.get("project_id"), "case_id": snapshot.get("case_id"),
                        "sources": refs, "context": snapshot.get("context"),
                        "assets": asset_refs or {},
                        "requirements": snapshot.get("requirements"), "clarifications": snapshot.get("clarifications"),
                        "obligations": [{k: v for k, v in row.items() if k != "candidates"} for row in ledger]})
    ledger = deepcopy(ledger)
    for row in ledger:
        row["obligation_key"] = obligation_key(row)
        if row.get("status") == "evidence_ready":
            row["status"] = "blocked"  # Revalidate even the first scan's candidates.
            for candidate in row.get("candidates", []):
                candidate["adopted"] = False
    session = {"schema_version": "1.0", "input_digest": input_ref, "sources": refs,
               "policy": policy, "rule": RULE, "provider": {"id": "local-fixed-source", "version": 1,
               "binding_mode": "local_real"}, "rounds": [], "rejected_fingerprints": [],
               "usage": {"queries": 0, "local_checks": 0, "candidates": 0, "elapsed_seconds": 0, "model_calls": 0},
               "remaining": [], "stop_reason": None}
    session["session_id"] = digest({"input": input_ref, "policy": policy, "rule": RULE})
    if resume:
        if any(resume.get(k) != session[k] for k in ("input_digest", "sources", "policy", "rule", "provider")):
            raise completion.EvidenceBlocked("补缺恢复的输入、来源或策略已变化")
        session = {key: deepcopy(resume[key]) for key in session if key in resume}
        session["stop_reason"] = None
        accepted_by_key = {r["obligation_key"]: r["accepted"] for round_ in session["rounds"]
                           for r in round_["obligations"] if r["accepted"]}
        for row in ledger:
            if row["obligation_key"] in accepted_by_key:
                row.update(status="evidence_ready", candidates=deepcopy(accepted_by_key[row["obligation_key"]]))
    session["usage"].setdefault("local_checks", 0)
    started, prior_seconds = clock(), session["usage"]["elapsed_seconds"]
    rejected = set(session["rejected_fingerprints"])

    def pending():
        return [row for row in ledger if row.get("status") == "blocked"]

    def checkpoint(reason=None):
        session["usage"]["elapsed_seconds"] = round(prior_seconds + max(0, clock() - started), 6)
        session["remaining"] = [row["obligation_key"] for row in pending()]
        session["rejected_fingerprints"] = sorted(rejected)
        session["stop_reason"] = reason
        return progress({"completion_checkpoint": deepcopy(session)}) is not False

    def control():
        if cancelled():
            return "cancelled"
        if not permission_valid():
            return "permission_revoked"
        try:
            completion.validate_sources(snapshot)
        except completion.EvidenceBlocked:
            return "source_invalid"
        if prior_seconds + clock() - started >= policy["max_seconds"]:
            return "deadline_exceeded"
        return None

    stop, query_cache = control(), {}
    if stop is None and not pending():
        stop = "converged"
    while stop is None and len(session["rounds"]) < policy["max_rounds"]:
        if not pending():
            stop = "converged"
            break
        records, added, conflict = [], 0, False
        if provider is not None:
            query_cache = {}
        for row in pending():
            stop = control()
            if stop:
                break
            key = row["obligation_key"]
            if provider is None:
                # The ledger has already collected these fixed local candidates.
                # Validating them (including an empty result) is not a retrieval
                # call. Candidate and time budgets still bound this work.
                session["usage"]["local_checks"] += 1
                candidates = row.get("candidates", [])
            else:
                query_key = digest({k: row.get(k) for k in ("title", "field_label", "kind", "requirement_id")})
                if query_key not in query_cache:
                    if session["usage"]["queries"] >= policy["max_queries"]:
                        stop = "budget_exhausted"
                        break
                    session["usage"]["queries"] += 1
                    query_cache[query_key] = provider(deepcopy(row), deepcopy(blocks))
                candidates = query_cache[query_key]
            accepted, rejected_records = [], []
            for candidate in candidates:
                if session["usage"]["candidates"] >= policy["max_candidates"]:
                    stop = "budget_exhausted"
                    break
                candidate = deepcopy(candidate)
                fingerprint = digest({"obligation_key": key, "candidate": {k: v for k, v in candidate.items() if k != "adopted"}})
                session["usage"]["candidates"] += 1
                reason = "previously_rejected" if fingerprint in rejected else _candidate_error(row, candidate, blocks)
                if reason:
                    rejected.add(fingerprint)
                    rejected_records.append({"candidate": candidate, "fingerprint": fingerprint, "reason": reason})
                else:
                    candidate["adopted"] = True
                    accepted.append(candidate)
            if stop == "budget_exhausted":
                # An unchecked candidate may conflict with those already seen.
                # Keep the obligation intact, and never checkpoint a partial
                # adoption that recovery would mistake for completed evidence.
                row["status"] = "blocked"
                for candidate in row.get("candidates", []):
                    candidate["adopted"] = False
                records.append({"obligation_key": key, "query": {"title": row.get("title"),
                                "field_label": row.get("field_label"), "rule_id": RULE["id"]},
                                "accepted": [], "rejected": rejected_records, "candidate_scan_complete": False})
                break
            if len({c["quote"] for c in accepted if c.get("match") == "explicit_label"}) > 1:
                conflict = True
                for candidate in accepted:
                    fingerprint = digest({"obligation_key": key, "candidate": {k: v for k, v in candidate.items() if k != "adopted"}})
                    rejected.add(fingerprint)
                    rejected_records.append({"candidate": {**candidate, "adopted": False}, "fingerprint": fingerprint, "reason": "conflicting_values"})
                accepted = []
            if accepted:
                row.update(status="evidence_ready", candidates=deepcopy(accepted),
                           reason="固定来源、定位及确定性映射已核验；原引擎装配后仍需交付复核")
                added += 1
            else:
                row["candidates"] = [{**r["candidate"], "adopted": False} for r in rejected_records]
            records.append({"obligation_key": key, "query": {"title": row.get("title"), "field_label": row.get("field_label"),
                            "rule_id": RULE["id"]}, "accepted": accepted, "rejected": rejected_records})
            if stop:
                break
        session["rounds"].append({"round": len(session["rounds"]) + 1, "obligations": records,
                                  "eliminated": added, "remaining": [r["obligation_key"] for r in pending()]})
        # Check immediately after retrieval, before accepting the round as current.
        stop = control() or stop
        if stop in {"source_invalid", "permission_revoked"}:
            for row in ledger:
                if row.get("status") == "evidence_ready":
                    row["status"] = "blocked"
                    for c in row.get("candidates", []):
                        c["adopted"] = False
            session["rounds"][-1].update(invalidated_by=stop, eliminated=0,
                                          remaining=[r["obligation_key"] for r in pending()])
        stop = stop or ("conflict" if conflict else "converged" if not pending() else "no_new_evidence" if not added else None)
        if not checkpoint(stop):
            # The Store owns the authoritative cancellation/lease terminal receipt.
            session["stop_reason"] = "cancelled" if cancelled() else "permission_revoked"
            return ledger, session
        stop = control() or stop
    stop = stop or "max_rounds"
    if stop in {"source_invalid", "permission_revoked"}:
        for row in ledger:
            if row.get("status") == "evidence_ready":
                row["status"] = "blocked"
                for candidate in row.get("candidates", []):
                    candidate["adopted"] = False
    checkpoint(stop)
    return ledger, session


def _candidate_error(row, candidate, blocks):
    if row.get("kind") == "missing_mandatory_section":
        return "controlled_structure_change_required"
    if row.get("column_count", 0) > 2:
        return "table_column_mapping_required"
    quote = candidate.get("quote")
    fixed = [b for b in blocks if all(candidate.get(k) == b.get(k) for k in
             ("source_id", "version", "sha256", "location", "role")) and quote and quote in b.get("quote", "")]
    if not fixed:
        return "source_identity_or_location_invalid"
    if completion.PLACEHOLDER.search(quote):
        return "unresolved_placeholder"
    if candidate.get("role") not in {"tech", "spec"} and not candidate.get("adoption"):
        return "unapproved_reference"
    # Do not trust a provider's claim that a semantic mapping was approved.
    original = row.get("candidates", [])
    if not any(all(candidate.get(k) == old.get(k) for k in
                   ("source_id", "version", "sha256", "location", "quote", "match", "adoption")) for old in original):
        return "unapproved_mapping"
    if candidate.get("match") not in RULE["mapping"]:
        return "unapproved_mapping"
    return None
