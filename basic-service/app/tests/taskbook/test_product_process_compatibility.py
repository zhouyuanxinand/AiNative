"""Nested controlled templates keep source-backed quality leaves in改型 flows."""
from tests.support.paths import APP_ROOT
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from jonhon_taskbook.fill import _apply_process_specific_sections, fill
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks
from jonhon_taskbook.template_scanner import heading_level, semantic_title

SERVICE = APP_ROOT / 'src/service'
TEMPLATES = SERVICE / 'jonhon_taskbook/resources/templates'
PROCESSES = ('全新', '改型I', '改型II', '改型III')


def titles(document):
    return [semantic_title(p.text) for p in document.paragraphs if heading_level(p)]


@pytest.mark.parametrize('family', ('optical_connector', 'system_integration'))
@pytest.mark.parametrize('process', PROCESSES)
def test_real_templates_remove_failure_and_quality_subtrees_by_process(tmp_path, family, process):
    document = Document(TEMPLATES / f'{family}_taskbook.docx')
    audit = _apply_process_specific_sections(
        document, {}, process, '合成产品', '未匹配合成系列', str(tmp_path / 'out.docx'),
    )
    headings = titles(document)
    failure = [t for t in headings if t in ('初步失效模式分析', '初步的失效模式分析')]
    assert bool(failure) == (process in ('全新', '改型I'))
    assert any(t == '通用质量特性要求' for t in headings) == (process == '全新')
    assert any(t.startswith(('安全性要求', '安全性定性要求')) for t in headings) == (process == '全新')
    assert any(t == '工艺要求' for t in headings)
    assert any('任务书编制依据' in t for t in headings)
    assert document.element.body.find(qn('w:sectPr')) is not None
    if family == 'system_integration':
        assert '质量保证与控制要求' in headings
        assert any(t.startswith('质量要求') for t in headings)
        assert any(t.startswith('标准化要求') for t in headings)
    if process in ('改型II', '改型III'):
        assert audit['deleted_failure_section_nodes'] > 0


@pytest.mark.parametrize('role,parent', [
    ('reliability_quantitative', '可靠性要求'),
    ('reliability_qualitative', '可靠性要求'),
    ('maintainability_quantitative', '维修性要求'),
    ('maintainability_qualitative', '维修性要求'),
    ('testability_quantitative', '测试性要求'),
    ('testability_qualitative', '测试性要求'),
    ('supportability_quantitative', '保障性要求'),
    ('supportability_qualitative', '保障性要求'),
    ('safety_quantitative', '安全性要求'),
    ('safety_qualitative', '安全性要求'),
    *[(role, '环境适应性要求') for role in (
        'high_temperature', 'low_temperature', 'thermal_shock', 'damp_heat',
        'mold', 'salt_spray', 'acid_atmosphere', 'vibration', 'shock',
        'acceleration', 'electromagnetic_environment', 'special_environment',
    )],
])
def test_individual_system_leaf_retains_only_its_quality_parent(tmp_path, role, parent):
    document = Document(TEMPLATES / 'system_integration_taskbook.docx')
    classification = {
        'source_blocks': [{'id': 'source', 'text': '本次来源明确提出的验证要求。'}],
        'classifications': [{'source_id': 'source', 'category': role}],
    }
    _apply_process_specific_sections(document, classification, '改型II', '合成产品', '合成系列', str(tmp_path / 'out.docx'))
    headings = titles(document)
    retained = [title for title in ('可靠性要求', '维修性要求', '测试性要求', '保障性要求', '安全性要求', '环境适应性要求') if any(t == title or t.startswith(title + '（') for t in headings)]
    assert retained == [parent]


@pytest.mark.parametrize('family', ('optical_connector', 'system_integration'))
@pytest.mark.parametrize('process', ('改型I', '改型II', '改型III'))
def test_real_fill_keeps_quantitative_and_qualitative_evidence_in_nested_slots(tmp_path, family, process):
    source = Document()
    roles = ['reliability_quantitative', 'reliability_qualitative']
    if family == 'optical_connector':
        roles.append('reliability_test')
        profile = 'optical_connector'
    else:
        roles += [f'{parent}_{kind}' for parent in ('maintainability', 'testability', 'supportability', 'safety') for kind in ('quantitative', 'qualitative')]
        roles.append('high_temperature')
        profile = 'mounting_frame'
    evidence = {}
    for index, role in enumerate(roles):
        source.add_heading(role, 1)
        body = f'验证输入{index}：该项设计必须满足本次协议指定要求并记录验证结果。'
        source.add_paragraph(body)
        evidence[role] = body
    tech, spec, out = (tmp_path / name for name in ('tech.docx', 'spec.docx', 'out.docx'))
    source.save(tech)
    Document().save(spec)
    blocks = extract_source_blocks(str(tech), 'tech')
    classification = {
        'source_blocks': blocks,
        'classifications': [{'source_id': b['id'], 'category': b['heading_text']} for b in blocks],
    }
    fill(
        str(tech), str(spec), str(TEMPLATES / f'{family}_taskbook.docx'), str(out),
        str(SERVICE / f'jonhon_taskbook/{profile}_profile.yaml'),
        finalize=False, requirement_classification=classification,
        category_mapping_path=str(SERVICE / f'config/{family}_requirement_categories.yaml'),
        development_process=process, controlled_product_domain='military',
        product_series='未匹配合成系列',
    )
    generated = Document(out)
    text = [p.text for p in generated.paragraphs]
    for role, body in evidence.items():
        assert text.count(body) == (2 if role == 'high_temperature' else 1), (role, body)
    assert '通用质量特性要求' in titles(generated)


def test_quality_pruning_preserves_same_titles_in_other_business_sections(tmp_path):
    document = Document()
    document.add_heading('技术要求', 1)
    document.add_heading('安全性要求', 2)
    document.add_paragraph('技术接口中的安全约束需要保留。')
    document.add_heading('可靠性要求验证计划', 2)
    document.add_paragraph('同名标题片段不是六性章。')
    document.add_heading('初步失效模式分析', 2)
    document.add_paragraph('独立技术子章不应按顶层历史故障章删除。')
    document.add_heading('通用质量特性要求', 1)
    document.add_heading('安全性要求', 2)
    document.add_paragraph('应删除的六性模板示例。')
    document.add_heading('另外的受控质量要求', 2)
    document.add_paragraph('六性删空之后仍必须保留此未受删除规则管理的子章。')
    document.add_heading('工艺要求', 1)
    document.add_paragraph('材料要求按既有逻辑保留。')
    _apply_process_specific_sections(document, {}, '改型II', '合成产品', '合成系列', str(tmp_path / 'out.docx'))
    text = '\n'.join(p.text for p in document.paragraphs)
    assert '应删除的六性模板示例。' not in text
    for body in ('技术接口中的安全约束需要保留。', '同名标题片段不是六性章。', '独立技术子章不应按顶层历史故障章删除。', '六性删空之后仍必须保留此未受删除规则管理的子章。', '材料要求按既有逻辑保留。'):
        assert body in text


def test_unresolved_or_empty_leaf_assignment_does_not_retain_quality_section(tmp_path):
    document = Document(TEMPLATES / 'optical_connector_taskbook.docx')
    classification = {
        'source_blocks': [{'id': 'empty', 'text': ''}],
        'classifications': [
            {'source_id': 'missing', 'category': 'reliability_quantitative'},
            {'source_id': 'empty', 'category': 'reliability_test'},
        ],
    }
    _apply_process_specific_sections(document, classification, '改型I', '合成产品', '合成系列', str(tmp_path / 'out.docx'))
    assert '可靠性要求' not in titles(document)
