"""The RD adapter preserves the original engine's labels and condition contract."""
from contextlib import nullcontext
from copy import deepcopy

import pytest
from docx import Document

from tests.rd_platform.test_executors import source, snapshot, run


def adopted_case(tmp_path, conditions='规格：#22D；条件：-55℃'):
    original = '接触电阻：不大于 10 mΩ。'
    adopted = '接触电阻：不大于 10 mΩ；' + conditions
    docs = [source(tmp_path, original, sid='tech'),
            source(tmp_path, '接触电阻：规格 #22D，条件 -55℃，不大于 10 mΩ。', role='spec', sid='spec'),
            source(tmp_path, adopted, role='reference', sid='reply')]
    requirement = {'id':'R1', 'revision':2, 'title':'接触电阻', 'content':adopted,
                   'source_ids':['tech','reply'], 'history':[{'revision':2, 'clarification_id':'C1'}]}
    record = {'id':'C1', 'status':'adopted', 'requirement_id':'R1',
              'answer':conditions, 'answer_source_ids':['reply'],
              'answer_source_snapshots':[{key:docs[2][key] for key in ('id','version','sha256')}],
              'adoption':{'requirement_revision':2,'requirement_content':adopted}}
    snap = snapshot(docs)
    snap.update(actor_id='local:contract-test', requirements=[requirement], clarifications=[record])
    return snap


def plan_and_completion(snap, tmp_path):
    plan = run('template_plan', snap, tmp_path)['result']
    completed = run('content_completion', snap, tmp_path, {'template_plan':plan})['result']
    assert completed['generation_ready'] is True
    return plan, completed


def engine_calls(monkeypatch):
    from jonhon_taskbook import llm_client
    from src import pipeline_cli
    seen = []
    def pipeline(**kwargs):
        seen.append(kwargs)
        document = Document()
        document.add_paragraph('边界测试复核稿')
        document.save(kwargs['out_path'])
        return {'ok':False,'out':kwargs['out_path'],'delivery_status':'blocked','meta':{},'warnings':[]}
    monkeypatch.setattr(pipeline_cli, 'run_pipeline', pipeline)
    monkeypatch.setattr(llm_client, 'get_model_status', lambda *a:{'configured':True})
    monkeypatch.setattr(llm_client, 'model_scope', lambda *a:nullcontext())
    return seen


def test_bound_template_plan_and_pipeline_keep_product_label_separate_from_domain(tmp_path, monkeypatch):
    from src.service.rd_platform.business_binding import document_template, business_fingerprint
    from jonhon_taskbook.template_registry import resolve_template_selection
    snap = adopted_case(tmp_path)
    binding = {'id':'binding1','status':'current','context':snap['context'],
               'requirements_snapshot':deepcopy(snap['requirements']), 'source_snapshots':deepcopy(snap['sources']),
               'product_route':snap['product_route'], 'composition_route':snap['composition_route'],
               'workflow':{'id':'flow','version':1,'nodes':['taskbook'],'product_route':'new'},
               'document_template':document_template(snap['context'])}
    binding['fingerprint'] = business_fingerprint(binding)
    snap['taskbook_binding'] = binding
    plan, done = plan_and_completion(snap, tmp_path)
    expected = resolve_template_selection(snap['context']['product_type'],snap['context']['product_domain']).product_type_label
    assert plan['selection']['product_type_label'] == expected
    # Previously saved plans may still contain the combined display title.
    plan['selection']['product_type_label'] = expected + ' / 军品'
    seen = engine_calls(monkeypatch)
    result = run('generate', snap, tmp_path, {'template_plan':plan,'content_completion':done})
    assert seen[0]['selected_product_type_label'] == expected
    assert seen[0]['selected_product_domain'] == 'military'
    assert result['status'] == 'blocked'  # Forwarding context is not delivery approval.


def test_current_adopted_source_backed_conditions_reach_real_engine_boundary(tmp_path, monkeypatch):
    snap = adopted_case(tmp_path)
    plan, done = plan_and_completion(snap, tmp_path)
    seen = engine_calls(monkeypatch)
    run('generate', snap, tmp_path, {'template_plan':plan,'content_completion':done})
    assert seen[0]['indicator_clarifications'] == {'接触电阻':'规格：#22D；条件：-55℃'}


@pytest.mark.parametrize(('adopted_conditions', 'answer'), [
    ('规格：#22D', '规格：#22'),
    ('温度：85℃～125℃', '温度：85℃'),
    ('档位：10', '档位：1'),
    ('不适用条件：85℃', '条件：85℃'),
])
def test_partial_condition_fields_or_values_cannot_reach_engine(tmp_path, monkeypatch, adopted_conditions, answer):
    snap = adopted_case(tmp_path, adopted_conditions)
    snap['clarifications'][0]['answer'] = answer
    plan, done = plan_and_completion(snap, tmp_path)
    seen = engine_calls(monkeypatch)
    run('generate', snap, tmp_path, {'template_plan':plan,'content_completion':done})
    assert seen[0]['indicator_clarifications'] == {}


def test_complete_condition_fields_allow_spacing_colons_and_sentence_end(tmp_path, monkeypatch):
    snap = adopted_case(tmp_path, '规格: #22D；温度：85 ℃。')
    snap['clarifications'][0]['answer'] = '规格：#22D；温度：85℃'
    plan, done = plan_and_completion(snap, tmp_path)
    seen = engine_calls(monkeypatch)
    run('generate', snap, tmp_path, {'template_plan':plan,'content_completion':done})
    assert seen[0]['indicator_clarifications'] == {'接触电阻':'规格：#22D；温度：85℃'}


@pytest.mark.parametrize('invalid', ['unadopted', 'stale_requirement', 'changed_source', 'missing_history',
                                    'not_in_adopted_content', 'engineering_value', 'unmapped_indicator'])
def test_unverified_or_noncondition_clarifications_cannot_become_engine_overrides(tmp_path, monkeypatch, invalid):
    snap = adopted_case(tmp_path)
    requirement, clarification = snap['requirements'][0], snap['clarifications'][0]
    if invalid == 'unadopted':
        clarification['status'] = 'answered'
    elif invalid == 'stale_requirement':
        requirement['revision'] += 1
    elif invalid == 'changed_source':
        clarification['answer_source_snapshots'][0]['sha256'] = 'stale-hash'
    elif invalid == 'missing_history':
        requirement['history'] = []
    elif invalid == 'not_in_adopted_content':
        clarification['answer'] = '条件：85℃'
    elif invalid == 'engineering_value':
        clarification['answer'] = '接触电阻：0 mΩ'
    elif invalid == 'unmapped_indicator':
        requirement['title'] = '关于电气性能的综合澄清'
    plan, done = plan_and_completion(snap, tmp_path)
    seen = engine_calls(monkeypatch)
    run('generate', snap, tmp_path, {'template_plan':plan,'content_completion':done})
    assert seen[0]['indicator_clarifications'] == {}
