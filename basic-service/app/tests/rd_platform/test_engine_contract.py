"""The RD adapter preserves the original engine's labels and condition contract."""
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
from pathlib import Path

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


def test_bound_pipeline_receives_exact_context_and_assets(tmp_path, monkeypatch):
    """Pin the liquid-pipeline boundary; a stub output is not document QA."""
    from jonhon_taskbook import llm_client
    from jonhon_taskbook.template_registry import PROJECT_ROOT, resolve_template_selection
    from src.service.rd_platform.business_binding import document_template, business_fingerprint

    context = {
        'product_type': 'liquid_cooling_pipeline', 'product_domain': 'military',
        'development_process': '改型II', 'cover_phase': 'S', 'product_series': 'YLZJ',
        'organization_scope': 'non_central_research',
    }
    # Reverse input order so accidentally using positional sources cannot pass.
    spec = source(tmp_path, '产品规范：工作压力0.3MPa。', role='spec', sid='spec')
    tech = source(tmp_path, '技术要求：液冷管路工作压力0.3MPa。', sid='tech')
    snap = snapshot([spec, tech], context)
    snap.update(actor_id='local:contract-test', product_route={'value': 'modification'},
                model_selection={'provider': 'contract-provider', 'name': 'contract-model', 'id': 'fixed-model-id'})
    binding = {
        'id': 'liquid-pipeline-binding', 'status': 'current', 'context': deepcopy(context),
        'requirements_snapshot': [], 'source_snapshots': deepcopy(snap['sources']),
        'product_route': deepcopy(snap['product_route']), 'composition_route': deepcopy(snap['composition_route']),
        'workflow': {'id': 'flow', 'version': 1, 'nodes': ['taskbook'], 'product_route': 'modification'},
        'document_template': document_template(context),
    }
    binding['fingerprint'] = business_fingerprint(binding)
    snap['taskbook_binding'] = binding
    plan, done = plan_and_completion(snap, tmp_path)
    seen = engine_calls(monkeypatch)
    model_status_calls, model_scope_calls = [], []

    def model_status(*args):
        model_status_calls.append(args)
        return {'configured': True}

    def model_scope(*args):
        model_scope_calls.append(args)
        return nullcontext()

    monkeypatch.setattr(llm_client, 'get_model_status', model_status)
    monkeypatch.setattr(llm_client, 'model_scope', model_scope)
    result = run('generate', snap, tmp_path, {'template_plan': plan, 'content_completion': done})
    assert len(seen) == 1
    call = seen[0]
    assert {key: call[key] for key in (
        'selected_product_type', 'selected_product_domain', 'development_process',
        'cover_phase', 'product_series', 'organization_scope',
    )} == {
        'selected_product_type': context['product_type'], 'selected_product_domain': context['product_domain'],
        **{key: context[key] for key in ('development_process', 'cover_phase', 'product_series', 'organization_scope')},
    }
    selected = resolve_template_selection('liquid_cooling_pipeline', 'military')
    assert call['selected_product_type_label'] == selected.product_type_label
    for role, original in [('tech', tech), ('spec', spec)]:
        assert Path(call[role + '_path']).read_bytes() == Path(original['path']).read_bytes()
    for kind, argument in [('template', 'tpl_path'), ('profile', 'profile_path'), ('mapping', 'category_mapping_path')]:
        asset = plan['assets'][kind]
        assert call[argument] == asset['path']
        assert Path(call[argument]).is_relative_to(tmp_path / 'work')
        assert hashlib.sha256(Path(call[argument]).read_bytes()).hexdigest() == binding['document_template']['assets'][kind]['sha256']
    rules = {'rule_' + path.stem: path for path in (PROJECT_ROOT / 'config').glob('*.yaml')}
    assert {kind for kind in plan['assets'] if kind.startswith('rule_')} == set(rules)
    for kind, original in rules.items():
        assert plan['assets'][kind]['sha256'] == hashlib.sha256(original.read_bytes()).hexdigest()
        assert Path(plan['assets'][kind]['path']).read_bytes() == original.read_bytes()
    assert call['use_llm'] is True
    assert call['preserve_unfilled_template'] is True
    assert call['formal_output'] is True
    assert callable(call['cb'])
    assert call['indicator_clarifications'] == {}
    expected_model = ('contract-provider', 'contract-model', 'fixed-model-id')
    assert model_status_calls == [expected_model]
    assert model_scope_calls == [expected_model]
    receipt = json.loads(Path(result['result']['receipt']['path']).read_text(encoding='utf-8'))
    assert receipt['context'] == context
    assert receipt['binding_id'] == binding['id']
    assert receipt['business_fingerprint'] == binding['fingerprint']
    assert receipt['source_hashes'] == {item['id']: item['sha256'] for item in snap['sources']}
    assert {kind: item['sha256'] for kind, item in receipt['assets'].items()} == {
        kind: item['sha256'] for kind, item in plan['assets'].items()
    }
    assert result['status'] == 'blocked'
    assert result['result']['ok'] is False


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
