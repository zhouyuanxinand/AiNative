from copy import deepcopy
from pathlib import Path

import pytest

from src.service.rd_platform.completion import EvidenceBlocked
from tests.rd_platform.test_executors import CONTEXT
from tests.rd_platform.test_executors import snapshot, run


def bound_snapshot():
    from src.service.rd_platform.business_binding import document_template, business_fingerprint
    snap = snapshot()
    binding = {'id': 'bind-1', 'status': 'current', 'context': deepcopy(snap['context']),
               'requirements_snapshot': [], 'source_snapshots': [],
               'product_route': deepcopy(snap['product_route']),
               'composition_route': deepcopy(snap['composition_route']),
               'workflow': {'id': 'research-new', 'version': 1, 'product_route': 'new',
                            'nodes': [{'id': 'taskbook'}]},
               'document_template': document_template(CONTEXT)}
    binding['fingerprint'] = business_fingerprint(binding)
    snap['taskbook_binding'] = binding
    return snap


def test_document_template_keeps_controlled_identity_and_hashes():
    from src.service.rd_platform.business_binding import document_template
    result = document_template(CONTEXT)
    assert result['product_type'] == CONTEXT['product_type']
    assert set(result['assets']) == {'template', 'profile', 'mapping'}
    assert result['template_sha256'] == result['assets']['template']['sha256']


def test_unknown_identity_cannot_borrow_a_different_product_template():
    from src.service.rd_platform.business_binding import document_template
    with pytest.raises(EvidenceBlocked):
        document_template({**CONTEXT, 'product_type': 'unknown-high-frequency'})


def test_fingerprint_ignores_storage_paths_but_keeps_business_choices():
    from src.service.rd_platform.business_binding import business_fingerprint
    original = {'context': CONTEXT, 'assets': {'template': {'path': 'C:/a', 'sha256': 'fixed'}}}
    moved = deepcopy(original)
    moved['assets']['template']['path'] = 'D:/b'
    assert business_fingerprint(original) == business_fingerprint(moved)
    moved['context']['product_series'] = 'CHANGED'
    assert business_fingerprint(original) != business_fingerprint(moved)


@pytest.mark.parametrize('change', ['context', 'requirements', 'route', 'workflow', 'asset'])
def test_binding_rejects_changed_business_input_and_asset_bytes(tmp_path, change):
    from src.service.rd_platform.business_binding import verify_binding, business_fingerprint
    snap = bound_snapshot()
    assert verify_binding(snap)['id'] == 'bind-1'
    if change == 'context':
        snap['context']['product_series'] = 'other'
    elif change == 'requirements':
        snap['requirements'] = [{'id': 'new', 'content': 'new requirement'}]
    elif change == 'route':
        snap['product_route']['value'] = 'modification'
    elif change == 'workflow':
        snap['taskbook_binding']['workflow']['product_route'] = 'modification'
        snap['taskbook_binding']['fingerprint'] = business_fingerprint(snap['taskbook_binding'])
    else:
        local = tmp_path / 'changed.docx'
        local.write_bytes(b'changed')
        snap['taskbook_binding']['document_template']['assets']['template']['path'] = str(local)
    with pytest.raises(EvidenceBlocked):
        verify_binding(snap)


def test_bound_template_plan_does_not_resolve_live_catalog_again(tmp_path, monkeypatch):
    from jonhon_taskbook import template_registry
    snap = bound_snapshot()
    def changed_catalog(*args):
        raise AssertionError('must use fixed adopted assets')
    monkeypatch.setattr(template_registry, 'resolve_template_selection', changed_catalog)
    result = run('template_plan', snap, tmp_path)
    assert result['status'] == 'completed'
    assert result['result']['binding_id'] == 'bind-1'
    assert result['result']['business_fingerprint'] == snap['taskbook_binding']['fingerprint']


def test_verify_cannot_adopt_a_receipt_from_different_business_binding(tmp_path):
    from tests.rd_platform.test_executors import verification_fixture
    snap, previous = verification_fixture(tmp_path)
    binding = bound_snapshot()['taskbook_binding']
    from src.service.rd_platform.business_binding import business_fingerprint
    binding['source_snapshots'] = deepcopy(snap['sources'])
    binding['fingerprint'] = business_fingerprint(binding)
    snap['taskbook_binding'] = binding
    previous['template_plan'].update(binding_id=binding['id'], business_fingerprint=binding['fingerprint'])
    result = run('verify', snap, tmp_path, previous)
    assert result['status'] == 'blocked'
    assert any('业务选择' in reason for reason in result['blocked_reasons'])


def test_matching_business_receipt_survives_real_qa_recheck(tmp_path):
    import json
    from tests.rd_platform.test_executors import verification_fixture
    from src.service.rd_platform.business_binding import business_fingerprint
    from src.service.rd_platform.engine_bridge import write_json
    snap, previous = verification_fixture(tmp_path)
    binding = bound_snapshot()['taskbook_binding']
    binding['source_snapshots'] = deepcopy(snap['sources'])
    # Bind the controlled fixture assets; this test exercises QA, not a model.
    mapping = tmp_path / 'mapping.yaml'
    mapping.write_text('categories: []', encoding='utf-8')
    from src.service.rd_platform.engine_bridge import artifact
    previous['template_plan']['assets']['mapping'] = artifact(mapping, 'mapping')
    for kind in ('template', 'profile', 'mapping'):
        asset = previous['template_plan']['assets'][kind]
        binding['document_template']['assets'][kind] = deepcopy(asset)
        binding['document_template'][kind + '_sha256'] = asset['sha256']
    binding['fingerprint'] = business_fingerprint(binding)
    snap['taskbook_binding'] = binding
    identity = {'binding_id': binding['id'], 'business_fingerprint': binding['fingerprint']}
    previous['template_plan'].update(identity)
    previous['generate'].update(identity)
    receipt = previous['generate']['receipt']
    saved = json.loads(Path(receipt['path']).read_text(encoding='utf-8'))
    saved.update(identity)
    previous['generate']['receipt'] = write_json(receipt['path'], saved, 'engine_receipt')
    assert run('verify', snap, tmp_path, previous)['status'] == 'completed'
