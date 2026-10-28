"""Initial checks and repair candidates use the same complete delivery gates."""

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document

import pipeline_cli as pipeline
from jonhon_taskbook import (
    business_value_gate, delivery_gate, fill, html_reporter, input_normalizer,
    media_injector, postprocess, product_router, requirement_classifier,
    semantic_integrity_gate, semantic_orchestrator,
)


@pytest.fixture
def generation(tmp_path, monkeypatch):
    source = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph("工作温度：5℃～42℃")
    document.save(source)
    profile = tmp_path / "profile.yaml"
    profile.write_text("technical_requirements_mode: table\n", encoding="utf-8")
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text("categories: {}\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    state = SimpleNamespace(
        calls=[], snapshots=[], auto_calls=[], repair=False, configured_ok=False,
        requires_review=False, fail_semantic=False, plan={"decisions": []},
    )

    def normalize(path, *_args):
        return input_normalizer.NormalizedInput(
            Path(path), Path(path), "docx", (), state.requires_review,
        )

    monkeypatch.setattr(input_normalizer, "normalize_input", normalize)
    monkeypatch.setattr(requirement_classifier, "build_requirement_classification", lambda *a, **k: {
        "passed": True, "summary": {"source_count": 2, "classified_count": 2},
    })
    monkeypatch.setattr(semantic_orchestrator, "build_semantic_plan", lambda *a, **k: state.plan)
    monkeypatch.setattr(product_router, "load_profile", lambda **k: (
        {"technical_requirements_mode": "table"}, "test", "test",
    ))
    monkeypatch.setattr(fill, "fill", lambda tech, spec, tpl, out, *a, **k: Document(tpl).save(out))
    monkeypatch.setattr(semantic_orchestrator, "apply_semantic_plan", lambda *a, **k: {
        "passed": True, "inserted": [], "skipped": [],
        "counts": {"inserted": 0, "verified_present": 0, "safe_skipped": 0, "blocking_skipped": 0},
    })
    monkeypatch.setattr(semantic_orchestrator, "review_semantic_decisions", lambda *a, **k: {"issues": []})
    monkeypatch.setattr(media_injector, "inject_media", lambda *a, **k: 0)
    monkeypatch.setattr(postprocess, "postprocess", lambda *a, **k: {
        "red_cleared": 0, "hl_cleared": 0, "date_cleared": 0, "para_deleted": 0,
    })
    monkeypatch.setattr(pipeline, "_run_final_placeholder_sweep", lambda *a, **k: 0)

    def coverage(tech, path, *_args, **_kwargs):
        state.calls.append("coverage")
        Path(path).with_suffix(".coverage_ledger.json").write_text(json.dumps({
            "blocks": [{"block_id": "source-a", "covered": True},
                       {"block_id": "source-b", "covered": True}],
        }), encoding="utf-8")
        return True

    def configured(path, *_args, **_kwargs):
        state.calls.append("configured")
        return {"passed": state.configured_ok, "blocked": not state.configured_ok,
                "block_reasons": [] if state.configured_ok else ["图题「图28 示例图」附近无图片对象（图题孤立）"],
                "warnings": [], "sidecar": str(Path(path).with_suffix(".configured_qa_gate.json"))}

    def semantic(path, plan, *_args, **_kwargs):
        state.calls.append("semantic")
        assert Path(path).with_suffix(".coverage_ledger.json").is_file()
        if state.fail_semantic:
            raise RuntimeError("semantic validation unavailable")
        return {"passed": bool(plan), "checked": [],
                "violations": [] if plan else [{"code": "MISSING_SEMANTIC_AUDIT_INPUT"}],
                "output_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                "sidecar": str(Path(path).with_suffix(".semantic_integrity_gate.json"))}

    def values(path):
        state.calls.append("business")
        return {"passed": True, "checked_decisions": 1, "blockers": [],
                "sidecar": str(Path(path).with_suffix(".business_value_audit.json"))}

    def deliver(*_args, **_kwargs):
        state.calls.append("delivery")
        return {"passed": True, "deliverable": True, "blockers": [], "warnings": []}

    monkeypatch.setattr(fill, "run_coverage_and_qa", coverage)
    monkeypatch.setattr(pipeline, "_run_configured_qa_gate", configured)
    monkeypatch.setattr(semantic_integrity_gate, "run_semantic_integrity_gate", semantic)
    monkeypatch.setattr(business_value_gate, "audit_indicator_values", values)
    monkeypatch.setattr(delivery_gate, "run_delivery_gate", deliver)
    monkeypatch.setattr(html_reporter, "generate_report", lambda path: str(Path(path).with_suffix(".html")))

    def repair(path, plan, classification, *, evaluate, max_rounds, cb):
        state.auto_calls.append((path, plan, classification, max_rounds))
        initial = evaluate(path)
        state.snapshots.append(initial)
        final = initial
        if state.repair:
            state.configured_ok = True
            final = evaluate(path)
            state.snapshots.append(final)
        return {"snapshot": final, "audit_path": str(tmp_path / "repair.json"),
                "rounds": [], "accepted_rounds": int(state.repair),
                "stop_reason": "passed" if final["qa_ok"] else "no_action"}

    monkeypatch.setitem(sys.modules, "jonhon_taskbook.auto_repair", SimpleNamespace(run_auto_repair=repair))

    def run():
        return pipeline.run_pipeline(
            str(source), str(source), str(source), str(output),
            profile_path=str(profile), category_mapping_path=str(mapping),
            cb=lambda _: None,
        )

    return state, run


def test_repair_rechecks_every_gate_and_returns_only_final_gate_state(generation):
    state, run = generation
    state.repair = True
    result = run()
    assert len(state.auto_calls) == 1
    assert state.auto_calls[0][3] == 2
    assert state.calls == ["coverage", "configured", "semantic", "business", "delivery"] * 2
    assert result["ok"] is True
    assert result["meta"]["qa_ok"] is True
    assert not any("配置 QA 门禁有阻断项" in message for message in result["warnings"])
    assert state.snapshots[0]["qa_ok"] is False
    assert state.snapshots[1]["qa_ok"] is True
    assert set(state.snapshots[1]["covered_source_ids"]) == {"source-a", "source-b"}
    assert state.snapshots[0]["blocking_keys"]
    assert state.snapshots[1]["blocking_keys"] == []
    assert result["sidecars"]["auto_repair"].endswith("repair.json")


def test_candidate_cannot_clear_manual_input_review_requirement(generation):
    state, run = generation
    state.repair = True
    state.requires_review = True
    result = run()
    assert len(state.snapshots) == 2
    assert all(snapshot["delivery_gate_ok"] is False for snapshot in state.snapshots)
    assert result["ok"] is False
    assert result["delivery_status"] == "blocked"
    assert result["meta"]["source_review_required"] is True
    assert any("逐页复核" in str(value) for value in state.snapshots[-1]["blocking_keys"])


@pytest.mark.parametrize("mode", ["empty_plan", "gate_exception"])
def test_incomplete_or_failed_semantic_check_stays_blocked(generation, mode):
    state, run = generation
    state.configured_ok = True
    if mode == "empty_plan":
        state.plan = {}
    else:
        state.fail_semantic = True
    result = run()
    assert len(state.snapshots) == 1
    assert result["ok"] is False
    assert result["meta"]["semantic_integrity_ok"] is False
    assert state.snapshots[0]["blocking_keys"]
    assert state.snapshots[0]["semantic_integrity"]["passed"] is False
def test_quality_keys_distinguish_different_cells_of_one_source():
    from src.pipeline_cli import _quality_issue_key

    first = {"code": "SOURCE_EVIDENCE_MISSING_FROM_TARGET", "source_id": "tech-t-1",
             "target_slot": "env", "source_coordinates": {"table_row": 2, "column": 1},
             "source_fragments": ["环境温度", "5℃～42℃"]}
    second = {**first, "source_coordinates": {"table_row": 3, "column": 1},
              "source_fragments": ["工作温度", "5℃～70℃"]}
    assert _quality_issue_key("semantic", first) != _quality_issue_key("semantic", second)
