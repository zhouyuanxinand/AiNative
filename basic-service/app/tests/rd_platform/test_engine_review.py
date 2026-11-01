"""A downloadable review document must never imply formal delivery approval."""
import json
from contextlib import nullcontext
from pathlib import Path

from docx import Document
import pytest

from tests.rd_platform.test_executors import source, snapshot, run, verification_fixture


@pytest.mark.parametrize('completion,engine_ok', [
    ({'ready': False, 'generation_ready': True, 'ledger': [{'status': 'blocked', 'title': '计划日期尚缺依据'}]}, True),
    ({'ready': False, 'generation_ready': True, 'ledger': [], 'conversion_review': {'requires_review': True}}, True),
    ({'ready': True, 'generation_ready': True, 'ledger': [{'status': 'blocked', 'title': '未完成内容'}]}, True),
    ({'ready': True, 'generation_ready': True, 'ledger': []}, False),
])
def test_review_docx_is_returned_but_workpackage_generation_remains_blocked(tmp_path, monkeypatch, completion, engine_ok):
    from jonhon_taskbook import llm_client
    from src import pipeline_cli
    docs = [source(tmp_path, '工作压力0.3MPa', sid='tech'),
            source(tmp_path, '工作压力0.3MPa', role='spec', sid='spec')]
    snap = snapshot(docs)
    snap['actor_id'] = 'local:review-test'
    plan = run('template_plan', snap, tmp_path)['result']
    observed = []
    def pipeline(**kwargs):
        observed.append(kwargs)
        document = Document()
        document.add_paragraph('工作压力0.3MPa；尚待完成工程复核。')
        document.save(kwargs['out_path'])
        return {'ok': engine_ok, 'delivery_status': 'delivered' if engine_ok else 'blocked',
                'meta': {'qa_ok': engine_ok, 'configured_qa_ok': engine_ok,
                         'semantic_integrity_ok': engine_ok, 'delivery_gate_result': {'passed': engine_ok}}}
    # Only the external engine boundary is substituted; adapter artifact hashing,
    # result classification and executor status are exercised unchanged.
    monkeypatch.setattr(pipeline_cli, 'run_pipeline', pipeline)
    monkeypatch.setattr(llm_client, 'get_model_status', lambda *a: {'configured': True})
    monkeypatch.setattr(llm_client, 'model_scope', lambda *a: nullcontext())
    outcome = run('generate', snap, tmp_path, {'template_plan': plan, 'content_completion': completion})
    assert observed and observed[0]['formal_output'] is True
    assert outcome['status'] == 'blocked'
    assert outcome['result']['ok'] is False
    assert outcome['result']['delivery_status'] == 'review_required'
    docx = next(item for item in outcome['artifacts'] if item['kind'] == 'taskbook')
    assert Document(docx['path']).paragraphs[0].text.startswith('工作压力0.3MPa')
    receipt = next(item for item in outcome['artifacts'] if item['kind'] == 'engine_receipt')
    saved = json.loads(Path(receipt['path']).read_text(encoding='utf-8'))
    assert saved['completion_review']['ready'] == completion['ready']
    assert saved['completion_review']['unresolved_count'] == sum(item['status'] == 'blocked' for item in completion['ledger'])
    assert outcome['blocked_reasons']


def test_verify_cannot_promote_review_document_even_when_engine_evidence_says_passed(tmp_path):
    snap, previous = verification_fixture(tmp_path)
    previous['content_completion'].update(ready=False, generation_ready=True,
        conversion_review={'requires_review': True})
    outcome = run('verify', snap, tmp_path, previous)
    assert outcome['status'] == 'blocked'
    assert outcome['result']['delivery_approved'] is False
    assert any('适用内容账' in reason for reason in outcome['blocked_reasons'])


def test_generation_without_review_readiness_never_calls_pipeline(tmp_path, monkeypatch):
    from src import pipeline_cli
    monkeypatch.setattr(pipeline_cli, 'run_pipeline', lambda **kwargs: pytest.fail('generation must not start without readiness'))
    docs = [source(tmp_path, '工作压力0.3MPa', sid='tech'),
            source(tmp_path, '工作压力0.3MPa', role='spec', sid='spec')]
    snap = snapshot(docs)
    plan = run('template_plan', snap, tmp_path)['result']
    outcome = run('generate', snap, tmp_path, {'template_plan': plan,
        'content_completion': {'ready': False, 'generation_ready': False, 'ledger': []}})
    assert outcome['status'] == 'blocked' and outcome['artifacts'] == []
