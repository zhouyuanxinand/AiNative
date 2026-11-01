"""Indicator rendering preserves source exponents without editing source values."""
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Pt

from jonhon_taskbook.fill import _fill_indicator_table, fill
from jonhon_taskbook.postprocess import postprocess
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks


def indicator_table(columns=4):
    document = Document()
    headers = ['项目', '用户要求指标', '拟采用指标', '依据']
    if columns == 5:
        headers.insert(2, '标准要求指标')
    table = document.add_table(rows=2, cols=columns)
    for cell, label in zip(table.rows[0].cells, headers):
        cell.text = label
    table.cell(1, 0).text = '泄漏测试'
    for cell in table.rows[1].cells[1:]:
        cell.paragraphs[0].add_run('旧占位').font.size = Pt(10.5)
    return document, table


def scientific_source(multiplier='7', exponent='-8', power='3', *, label=True):
    document = Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = '项目', '指标'
    table.cell(1, 0).text = '泄漏测试'
    paragraph = table.cell(1, 1).paragraphs[0]
    paragraph.add_run(('试验条件：保持2min。\n泄漏值' if label else '') + '≤' + multiplier + '×10')
    paragraph.add_run(exponent).font.superscript = True
    paragraph.add_run('Pa.m')
    paragraph.add_run(power).font.superscript = True
    paragraph.add_run('/s。')
    return document, table.cell(1, 1).text


def vertical_runs(cell):
    return [(r.text, 'superscript' if r.font.superscript else 'subscript')
            for p in cell.paragraphs for r in p.runs if r.font.superscript or r.font.subscript]


@pytest.mark.parametrize('columns', [4, 5])
def test_user_and_adopted_cells_retain_source_exponents_and_text(columns):
    source, value = scientific_source()
    source_xml = source.element.xml
    output, table = indicator_table(columns)
    _fill_indicator_table(output, [('泄漏测试', value, '', value, '用户要求')],
                          source_documents={'tech': source})
    for index in (1, 3 if columns == 5 else 2):
        cell = table.cell(1, index)
        assert cell.text == value
        assert vertical_runs(cell) == [('-8', 'superscript'), ('3', 'superscript')]
        assert all(r.font.size.pt == 10.5 for p in cell.paragraphs for r in p.runs)
    assert source.element.xml == source_xml


def test_standard_adoption_uses_its_own_document_format_and_retains_manual_marker():
    tech, user = scientific_source('7', '-8')
    spec, standard = scientific_source('4', '-9')
    output, table = indicator_table(5)
    adopted = '【人工填写】\n规范候选：' + standard
    _fill_indicator_table(output, [('泄漏测试', user, standard, adopted, '需确认')],
                          source_documents={'tech': tech, 'spec': spec})
    assert vertical_runs(table.cell(1, 1)) == [('-8', 'superscript'), ('3', 'superscript')]
    for index in (2, 3):
        assert vertical_runs(table.cell(1, index)) == [('-9', 'superscript'), ('3', 'superscript')]
    assert table.cell(1, 3).text == adopted
    marker = next(r for p in table.cell(1, 3).paragraphs for r in p.runs if '【人工填写】' in r.text)
    assert str(marker.font.color.rgb) == 'FF0000'


def test_subscripts_survive_label_removal_and_plain_model_numbers_stay_plain():
    source = Document()
    p = source.add_paragraph('介质：H')
    p.add_run('2').font.subscript = True
    p.add_run('O；接口型号M3-12。')
    output, table = indicator_table()
    value = 'H2O；接口型号M3-12。'
    _fill_indicator_table(output, [('泄漏测试', value, '', value, '用户要求')], source_documents={'tech': source})
    assert table.cell(1, 1).text == value
    assert vertical_runs(table.cell(1, 1)) == [('2', 'subscript')]


def test_does_not_guess_exponents_from_unformatted_text_or_isolated_footnote():
    source = Document()
    source.add_paragraph('接口型号M3-12；代号10-6；面积3m2。')
    source.add_paragraph().add_run('3').font.superscript = True
    output, table = indicator_table()
    value = '接口型号M3-12；代号10-6；面积3m2。'
    _fill_indicator_table(output, [('泄漏测试', value, '', value, '用户要求')], source_documents={'tech': source})
    assert table.cell(1, 1).text == value
    assert vertical_runs(table.cell(1, 1)) == []


@pytest.mark.parametrize('value', ['3', '-8', '3/s'])
def test_numeric_substring_of_other_metric_is_not_formatting_evidence(value):
    source, _ = scientific_source()
    output, table = indicator_table()
    _fill_indicator_table(output, [('泄漏测试', value, '', value, '用户要求')], source_documents={'tech': source})
    assert table.cell(1, 1).text == value
    assert vertical_runs(table.cell(1, 1)) == []


def test_conflicting_plain_source_expression_is_not_assumed_superscript():
    source, value = scientific_source(label=False)
    source.add_paragraph(value)
    output, table = indicator_table()
    _fill_indicator_table(output, [('泄漏测试', value, '', value, '用户要求')], source_documents={'tech': source})
    assert vertical_runs(table.cell(1, 1)) == []


def test_real_fill_and_postprocess_preserve_indicator_source_superscripts(tmp_path):
    root = Path(__file__).resolve().parents[1] / 'src/service'
    tech, value = scientific_source()
    tech_path, spec_path, output = [tmp_path / name for name in ['tech.docx', 'spec.docx', 'out.docx']]
    tech.save(tech_path)
    Document().save(spec_path)
    blocks = extract_source_blocks(str(tech_path), 'tech')
    classification = {'source_blocks': blocks, 'classifications': [
        {'source_id': b['id'], 'category': 'performance_indicator'} for b in blocks]}
    fill(str(tech_path), str(spec_path), str(root / 'jonhon_taskbook/resources/templates/liquid_cooling_pipeline_taskbook.docx'),
         str(output), str(root / 'jonhon_taskbook/liquid_cooling_pipeline_profile.yaml'),
         category_mapping_path=str(root / 'config/liquid_cooling_pipeline_requirement_categories.yaml'),
         requirement_classification=classification, controlled_product_label='液冷产品-液冷管路',
         controlled_product_domain='military', product_series='FORMAT-TEST',
         organization_scope='non_central_research', development_process='改型II', finalize=False)
    postprocess(str(output), preserve_template_guidance=True)
    document = Document(output)
    table = next(t for t in document.tables if '用户要求' in ''.join(c.text for c in t.rows[0].cells))
    row = next(r for r in table.rows if r.cells[0].text == '泄漏测试')
    assert row.cells[1].text.replace('\n', '') == value.replace('\n', '')
    assert vertical_runs(row.cells[1]) == [('-8', 'superscript'), ('3', 'superscript')]
    # This deliberately unregistered indicator still requires classification
    # review. Restoring source typography must not invent its adoption.
    assert row.cells[2].text == '【人工填写】'
