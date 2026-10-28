"""A customer's specification can be the task's requirement source."""
import json

import pytest

from jonhon_taskbook.semantic_orchestrator import (
    _document_previews, _require_expected_document_roles, _verify_roles,
)


def source(label, name, text, kind='paragraph'):
    return {'id': f'{label}-{name}', 'source': label, 'text': text, 'type': kind}


BLOCKS = [
    source('tech', 'title', '部件规格承认书'),
    source('tech', 'requirements', '该部件规格经双方确认无误，达成一致。工作压力 0.3 MPa，流量 0.8 L/min。', 'table'),
    source('spec', 'title', '液冷组件产品规范'),
    source('spec', 'scope', '本规范规定了液冷组件的技术要求、试验方法、质量保证规定、包装和运输等。'),
]


def assess(roles=('product_specification', 'product_specification'), confidence=0.95, cross_source=False):
    def model(_system, user):
        documents = json.loads(user)['documents']
        return {'documents': [
            {'label': doc['label'], 'role': role, 'confidence': confidence,
             'evidence_source_ids': documents[1-index]['sample_source_ids'] if cross_source else doc['sample_source_ids']}
            for index, (doc, role) in enumerate(zip(documents, roles))
        ]}
    return _verify_roles(BLOCKS, model)


@pytest.mark.parametrize('roles', [
    ('product_specification', 'product_specification'),
    ('product_specification', 'technical_requirement'),
    ('technical_requirement', 'product_specification'),
])
def test_document_form_never_swaps_the_users_requirement_and_specification(roles):
    result = assess(roles)
    _require_expected_document_roles(result)
    tech, spec = result['documents']
    assert tech['role'] == 'technical_requirement'
    assert spec['role'] == 'product_specification'
    assert tech['detected_role'] == roles[0]
    assert spec['detected_role'] == roles[1]
    assert tech['evidence_source_ids'] == ['tech-title', 'tech-requirements']
    assert spec['evidence_source_ids'] == ['spec-title', 'spec-scope']
    if roles[0] == 'product_specification':
        assert result['warnings']


def test_another_documents_evidence_cannot_satisfy_role_gate():
    result = assess(('technical_requirement', 'product_specification'), cross_source=True)
    with pytest.raises(ValueError, match='原文证据'):
        _require_expected_document_roles(result)


def test_cover_titles_alone_cannot_satisfy_role_gate():
    def model(_system, _user):
        return {'documents': [
            {'label': 'tech', 'role': 'product_specification', 'confidence': .99,
             'evidence_source_ids': ['tech-title']},
            {'label': 'spec', 'role': 'product_specification', 'confidence': .99,
             'evidence_source_ids': ['spec-title']},
        ]}

    result = _verify_roles(BLOCKS, model)

    with pytest.raises(ValueError, match='正文证据'):
        _require_expected_document_roles(result)


def test_long_body_prose_without_numbers_or_punctuation_is_valid_role_evidence():
    blocks = [
        source('tech', 'body', '本文件描述液冷系统泵体总成从设计制造到试验检验验收和交付的全过程质量控制工作'),
        source('spec', 'body', '本规范覆盖液冷系统泵体总成的设计制造试验检验验收包装运输以及后续服务相关活动'),
    ]

    def model(_system, user):
        documents = json.loads(user)['documents']
        return {'documents': [
            {'label': doc['label'], 'role': 'product_specification', 'confidence': .95,
             'evidence_source_ids': doc['sample_source_ids']}
            for doc in documents
        ]}

    result = _verify_roles(blocks, model)

    _require_expected_document_roles(result)


@pytest.mark.parametrize('role,confidence', [('template', .98), ('unknown', .8), ('technical_requirement', .2)])
def test_template_unknown_or_low_confidence_is_still_blocked(role, confidence):
    result = assess((role, 'product_specification'), confidence=confidence)
    with pytest.raises(ValueError, match='门禁失败'):
        _require_expected_document_roles(result)


def test_missing_or_duplicate_document_assessment_is_still_blocked():
    result = assess()
    result['documents'] = [result['documents'][0], result['documents'][0]]
    with pytest.raises(ValueError, match='角色结果数量'):
        _require_expected_document_roles(result)


def test_invalid_extra_assessment_cannot_be_filtered_out_before_duplicate_check():
    def model(_system, user):
        documents = json.loads(user)['documents']
        return {'documents': [
            {'label': doc['label'], 'role': 'technical_requirement' if doc['label'] == 'tech'
             else 'product_specification', 'confidence': .95,
             'evidence_source_ids': doc['sample_source_ids']}
            for doc in documents
        ] + [{'label': 'tech', 'role': 'nonsense', 'confidence': .95,
              'evidence_source_ids': documents[0]['sample_source_ids']}]}

    result = _verify_roles(BLOCKS, model)
    with pytest.raises(ValueError, match='角色结果数量'):
        _require_expected_document_roles(result)


def test_role_preview_includes_body_after_a_long_cover_and_toc():
    blocks = [source('tech', f'cover-{index}', f'目录项{index} 页码') for index in range(40)]
    blocks += [source('tech', 'body', '工作压力不得低于 0.3 MPa，泄漏率不得大于规定值；双方以本规格承认书验收。', 'table')]
    preview = _document_previews(blocks)[0]
    assert 'tech-body' in preview['sample_source_ids']
    assert '工作压力' in preview['preview']


def test_role_preview_includes_short_requirement_after_long_cover_and_toc():
    blocks = [source('tech', f'cover-{index}', f'目录项{index} 页码') for index in range(40)]
    blocks += [source('tech', f'short-requirement-{index}', f'工作压力应≥{index + 1} MPa。')
               for index in range(40)]

    preview = _document_previews(blocks)[0]

    assert 'tech-short-requirement-39' in preview['sample_source_ids']
    assert len(preview['sample_source_ids']) <= 20
    assert all(len(sample['text']) <= 900 for sample in preview['samples'])


def test_fabricated_evidence_not_in_the_actual_preview_is_rejected():
    blocks = [source('tech', str(i), f'第{i}条约定内容' * 10) for i in range(100)]
    blocks += [block for block in BLOCKS if block['source'] == 'spec']
    def model(_system, user):
        documents = json.loads(user)['documents']
        shown = set(documents[0]['sample_source_ids'])
        unshown = next(block['id'] for block in blocks if block['source']=='tech' and block['id'] not in shown)
        return {'documents': [
            {'label': 'tech', 'role': 'technical_requirement', 'confidence': .99, 'evidence_source_ids': [unshown]},
            {'label': 'spec', 'role': 'product_specification', 'confidence': .99, 'evidence_source_ids': documents[1]['sample_source_ids']},
        ]}
    result = _verify_roles(blocks, model)
    with pytest.raises(ValueError, match='原文证据'):
        _require_expected_document_roles(result)
