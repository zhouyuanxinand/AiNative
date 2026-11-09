"""Saved quotations resolve to real document coordinates without re-analysis."""
from copy import deepcopy
from io import BytesIO
import json

import pytest
from docx import Document

from tests.rd_platform.test_http import make_client
from tests.rd_platform.test_source_analysis import command


def _case(tmp_path, name, content):
    client = make_client(tmp_path)
    client.app.state.config.max_upload_bytes = 1024 * 1024
    project = client.post('/api/rd/projects', json={'title': '原文定位'}).json()
    project = command(client, project, 'create_case', scenario_id='taskbook', title='定位案例')
    cid = project['cases'][0]['id']
    response = client.post(f"/api/rd/projects/{project['id']}/cases/{cid}/sources",
        data={'expected_version': project['version'], 'role': 'tech'},
        files={'file': (name, content)}, headers={'Idempotency-Key': 'source'})
    assert response.status_code == 200, response.text
    return client, response.json()


def _document():
    doc = Document()
    doc.add_heading('技术要求', level=1)  # B0001: headings are valid quoted evidence too.
    doc.add_paragraph('工作压力：0.3 MPa。')
    doc.add_paragraph('')
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = '项目', '指标'
    table.cell(1, 0).text, table.cell(1, 1).text = '工作温度', '5℃～70℃'
    doc.add_paragraph('重复内容')
    doc.add_paragraph('重复内容')
    doc.add_paragraph('第一段。')
    doc.add_paragraph('第二段。')
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _seed(client, project, quotes, *, update=None):
    """Seed the persisted legacy shape; no model-generated locators are available."""
    store = client.app.state.rd_store
    with store._connection() as db:
        saved = json.loads(db.execute('SELECT payload FROM projects WHERE id=?', (project['id'],)).fetchone()[0])
        case = saved['cases'][0]
        sid = case['sources'][0]['id']
        case['source_analysis'] = {'id': 'saved-analysis', 'status': 'proposed',
            'source_hashes': {sid: case['sources'][0]['sha256']}, 'context': {},
            'requirements': [{'title': f'指标{index}', 'content': quote,
                              'evidence': [{'source_id': sid, 'quote': quote}]} for index, quote in enumerate(quotes)]}
        if update:
            update(case)
        payload = json.dumps(saved, ensure_ascii=False)
        db.execute('UPDATE projects SET payload=? WHERE id=?', (payload, project['id']))
    return saved, payload


def _url(project):
    return f"/api/rd/projects/{project['id']}/cases/{project['cases'][0]['id']}/evidence-locations"


def _items(client, project):
    result = client.get(_url(project))
    assert result.status_code == 200, result.text
    return {item['quote']: item for item in result.json()['items']}


def test_docx_coordinates_include_headings_tables_and_all_ambiguous_locations(tmp_path):
    client, project = _case(tmp_path, '要求.docx', _document())
    quotes = ['技术要求', '工作压力：0.3 MPa。', '工作温度 | 5℃～70℃', '重复内容', '没有这段原文']
    project, before = _seed(client, project, quotes)
    result = _items(client, project)
    assert result['技术要求']['locations'] == [{'id': 'B0001', 'label': '正文块 1', 'body_index': 0}]
    assert result['工作压力：0.3 MPa。']['locations'][0]['id'] == 'B0002'
    assert result['工作温度 | 5℃～70℃']['locations'] == [
        {'id': 'B0004-R002', 'label': '正文块 4 · 表格第 2 行', 'body_index': 3, 'row': 1}]
    assert result['重复内容']['status'] == 'ambiguous'
    assert [loc['id'] for loc in result['重复内容']['locations']] == ['B0005', 'B0006']
    assert result['没有这段原文']['status'] == 'not_found'
    assert result['没有这段原文']['locations'] == []
    assert result['技术要求']['source_version'] == 1
    assert result['技术要求']['coordinate_space'] == 'original'
    assert result['技术要求']['source_sha256'] == project['cases'][0]['sources'][0]['sha256']
    with client.app.state.rd_store._connection() as db:
        assert db.execute('SELECT payload FROM projects WHERE id=?', (project['id'],)).fetchone()[0] == before
    assert str(tmp_path) not in json.dumps(result)


def test_quote_across_paragraphs_is_one_location_range_not_ambiguity(tmp_path):
    client, project = _case(tmp_path, '要求.docx', _document())
    _seed(client, project, ['第一段。\n第二段。'])
    item = _items(client, project)['第一段。\n第二段。']
    assert item['status'] == 'located'
    assert [loc['id'] for loc in item['locations']] == ['B0007', 'B0008']


def test_text_preserves_real_line_numbers_and_normalizes_only_whitespace(tmp_path):
    client, project = _case(tmp_path, '要求.md', '\ufeff第一行\n\n压力：0.3 MPa\n第四行'.encode('utf-8'))
    _seed(client, project, ['压力：0.3MPa', '压力：0.4MPa'])
    result = _items(client, project)
    assert result['压力：0.3MPa']['locations'] == [{'id': 'L0003', 'label': '第 3 行', 'line': 3}]
    assert result['压力：0.4MPa']['status'] == 'not_found'


def test_collects_context_and_review_snapshot_without_inventing_project_or_filename_positions(tmp_path):
    client, project = _case(tmp_path, '要求.txt', '指标1\n指标2\n指标3\n指标4'.encode())
    def update(case):
        sid = case['sources'][0]['id']
        case['source_analysis']['context'] = {'product_series': {'candidates': [{
            'evidence': [{'source_id': sid, 'quote': '指标2'}]}]}}
        case['context_provenance'] = {'cover_phase': {'analysis_id': 'saved-analysis', 'evidence': [
            {'source_id': 'project_brief', 'quote': '项目登记'},
            {'source_id': sid, 'quote': '要求.txt', 'kind': 'source_filename'}]}}
        case['requirements'] = [{'id': 'r1', 'title': '已采用', 'content': '指标4', 'source_ids': [sid],
            'revision': 2, 'analysis_id': 'saved-analysis', 'evidence': [{'source_id': sid, 'quote': '指标3'}],
            'review': {'analysis_id': 'saved-analysis', 'decision': 'accept', 'recommendation': {
                'evidence': [{'source_id': sid, 'quote': '指标4'}]}}}]
    _seed(client, project, ['指标1', '指标1'], update=update)
    result = _items(client, project)
    assert set(result) == {'指标1', '指标2', '指标3', '指标4', '项目登记', '要求.txt'}
    assert all(result[f'指标{i}']['status'] == 'located' for i in range(1, 5))
    assert result['项目登记']['status'] == result['要求.txt']['status'] == 'unavailable'
    assert result['项目登记']['locations'] == result['要求.txt']['locations'] == []


def test_unauthorized_and_unknown_case_never_disclose_evidence(tmp_path):
    client, project = _case(tmp_path, '要求.txt', b'private text')
    _seed(client, project, ['private text'])
    stranger = make_client(tmp_path)
    assert stranger.get(_url(project)).status_code in {403, 404}
    assert client.get(_url(project).replace(project['cases'][0]['id'], 'unknown')).status_code == 404


def test_deleted_source_keeps_historical_coordinates_and_changed_bytes_are_rejected(tmp_path):
    client, project = _case(tmp_path, '要求.txt', '历史指标'.encode())
    project, _ = _seed(client, project, ['历史指标'])
    source = project['cases'][0]['sources'][0]
    project = command(client, project, 'delete_source', source_id=source['id'])
    item = _items(client, project)['历史指标']
    assert item['source_state'] == 'deleted' and item['locations'][0]['id'] == 'L0001'
    from pathlib import Path
    Path(source['path']).write_text('改动后的指标', encoding='utf-8')
    item = _items(client, project)['历史指标']
    assert item['status'] == 'unavailable' and item['reason'] == '原文件校验不一致'


def _normalized_cache(client, project, name='old-analysis'):
    store = client.app.state.rd_store
    case = project['cases'][0]
    source = case['sources'][0]
    folder = (store.asset_root / 'source_analysis' / project['id'] / case['id'] / name /
              'normalized' / source['id'] / f"{source['id']}-{source['sha256'][:12]}")
    folder.mkdir(parents=True)
    (folder / 'normalized.docx').write_bytes(_document())
    manifest = {'source_sha256': source['sha256'], 'status': 'needs_review', 'method': 'word_com',
                'normalized_path': str(folder / 'normalized.docx'), 'requires_review': True}
    (folder / 'source-evidence.json').write_text(json.dumps(manifest), encoding='utf-8')
    return folder, manifest


def test_legacy_doc_uses_its_saved_analysis_copy_without_conversion_or_model(tmp_path, monkeypatch):
    client, project = _case(tmp_path, '旧版要求.doc', b'legacy fixture bytes')
    def update(case):
        previous = deepcopy(case['source_analysis'])
        previous['id'] = 'old-analysis'
        case['source_analysis_history'] = [previous]
        case['source_analysis']['requirements'] = []
        case['requirements'] = [{'id': 'r', 'title': '工作压力', 'content': '0.3 MPa', 'revision': 1,
            'source_ids': [case['sources'][0]['id']], 'analysis_id': 'old-analysis',
            'evidence': [{'source_id': case['sources'][0]['id'], 'quote': '工作压力：0.3 MPa。'}]}]
    project, before = _seed(client, project, ['工作压力：0.3 MPa。'], update=update)
    folder, _ = _normalized_cache(client, project)
    from jonhon_taskbook import input_normalizer, llm_client
    def forbidden(*args, **kwargs):
        pytest.fail('读取定位不得重新转换文档或调用模型')
    monkeypatch.setattr(input_normalizer, 'normalize_input', forbidden)
    monkeypatch.setattr(llm_client, 'chat_json', forbidden)
    files_before = sorted(str(path) for path in client.app.state.rd_store.asset_root.rglob('*'))
    item = _items(client, project)['工作压力：0.3 MPa。']
    assert item['status'] == 'located' and item['locations'][0]['id'] == 'B0002'
    assert item['coordinate_space'] == 'normalized' and item['analysis_id'] == 'old-analysis'
    assert len(item['normalized_sha256']) == 64
    assert sorted(str(path) for path in client.app.state.rd_store.asset_root.rglob('*')) == files_before
    with client.app.state.rd_store._connection() as db:
        assert db.execute('SELECT payload FROM projects WHERE id=?', (project['id'],)).fetchone()[0] == before
    assert folder.exists()


@pytest.mark.parametrize('problem', ['missing_cache', 'wrong_hash', 'corrupt_copy', 'wrong_analysis_hash'])
def test_unavailable_legacy_index_is_not_guessed(tmp_path, problem):
    client, project = _case(tmp_path, '旧版要求.doc', b'legacy fixture bytes')
    def update(case):
        if problem == 'wrong_analysis_hash':
            sid = case['sources'][0]['id']
            case['source_analysis']['source_hashes'][sid] = '0' * 64
    project, _ = _seed(client, project, ['工作压力：0.3 MPa。'], update=update)
    if problem != 'missing_cache':
        folder, manifest = _normalized_cache(client, project, name='saved-analysis')
        if problem == 'wrong_hash':
            manifest['source_sha256'] = '0' * 64
        if problem == 'corrupt_copy':
            (folder / 'normalized.docx').write_bytes(b'not a DOCX')
        (folder / 'source-evidence.json').write_text(json.dumps(manifest), encoding='utf-8')
    item = _items(client, project)['工作压力：0.3 MPa。']
    assert item['status'] == 'unavailable' and item['locations'] == [] and item['reason']


def test_one_missing_source_does_not_hide_other_file_locations(tmp_path):
    from pathlib import Path
    client, project = _case(tmp_path, '要求.txt', '原始指标'.encode())
    project, _ = _seed(client, project, ['原始指标'])
    cid = project['cases'][0]['id']
    response = client.post(f"/api/rd/projects/{project['id']}/cases/{cid}/sources",
        data={'expected_version': project['version'], 'role': 'spec'},
        files={'file': ('规范.txt', '规范指标'.encode())}, headers={'Idempotency-Key': 'spec'})
    assert response.status_code == 200, response.text
    project = response.json()
    def update(case):
        source = case['sources'][1]
        case['source_analysis']['source_hashes'][source['id']] = source['sha256']
        case['source_analysis']['requirements'][0]['recommendation'] = {
            'evidence': [{'source_id': source['id'], 'quote': '规范指标'}]}
    project, _ = _seed(client, project, ['原始指标'], update=update)
    Path(project['cases'][0]['sources'][0]['path']).unlink()
    result = _items(client, project)
    assert result['原始指标']['status'] == 'unavailable'
    assert result['原始指标']['reason'] == '原文件不存在'
    assert result['规范指标']['status'] == 'located'
    assert result['规范指标']['locations'][0]['id'] == 'L0001'


def test_source_path_outside_assets_is_not_read_even_with_matching_hash(tmp_path):
    client, project = _case(tmp_path, '要求.txt', '原始指标'.encode())
    outside = tmp_path / 'outside.txt'
    outside.write_text('原始指标', encoding='utf-8')
    def update(case):
        case['sources'][0]['path'] = str(outside)
    _seed(client, project, ['原始指标'], update=update)
    item = _items(client, project)['原始指标']
    assert item['status'] == 'unavailable' and not item['locations']


def test_relocated_legacy_manifest_never_follows_old_absolute_paths(tmp_path):
    client, project = _case(tmp_path, '旧版要求.doc', b'legacy fixture bytes')
    project, _ = _seed(client, project, ['工作压力：0.3 MPa。'])
    folder, manifest = _normalized_cache(client, project, name='saved-analysis')
    manifest['normalized_path'] = 'Z:/old-server/normalized.docx'
    (folder / 'source-evidence.json').write_text(json.dumps(manifest), encoding='utf-8')
    item = _items(client, project)['工作压力：0.3 MPa。']
    assert item['status'] == 'located' and item['locations'][0]['id'] == 'B0002'
    assert 'old-server' not in json.dumps(item)


def test_merged_table_cell_quotes_keep_the_actual_row_coordinate(tmp_path):
    doc = Document()
    table = doc.add_table(rows=2, cols=3)
    table.cell(1, 0).merge(table.cell(1, 1)).text = '环境试验'
    table.cell(1, 2).text = '高低温循环'
    buffer = BytesIO()
    doc.save(buffer)
    client, project = _case(tmp_path, '合并单元格.docx', buffer.getvalue())
    _seed(client, project, ['环境试验 | 环境试验 | 高低温循环'])
    item = _items(client, project)['环境试验 | 环境试验 | 高低温循环']
    assert item['status'] == 'located' and item['locations'][0]['id'] == 'B0001-R002'


@pytest.mark.parametrize('new_copy_missing', [False, True])
def test_same_legacy_quote_keeps_its_own_analysis_coordinates(tmp_path, new_copy_missing):
    client, project = _case(tmp_path, '重复分析.doc', b'legacy fixture bytes')
    quote = '工作压力：0.3 MPa。'
    def update(case):
        previous = deepcopy(case['source_analysis'])
        previous['id'] = 'old-analysis'
        case['source_analysis_history'] = [previous]
        evidence = [{'source_id': case['sources'][0]['id'], 'quote': quote}]
        case['context_provenance'] = {'product_series': {
            'analysis_id': 'old-analysis', 'evidence': deepcopy(evidence)}}
        case['requirements'] = [{'id': 'r', 'title': '工作压力', 'content': quote, 'revision': 1,
            'source_ids': [case['sources'][0]['id']], 'analysis_id': 'old-analysis', 'evidence': evidence,
            'review': {'analysis_id': 'old-analysis', 'decision': 'accept', 'recommendation': {
                'evidence': deepcopy(evidence)}}}]
    project, _ = _seed(client, project, [quote], update=update)
    _normalized_cache(client, project, name='old-analysis')
    if not new_copy_missing:
        folder, _ = _normalized_cache(client, project, name='saved-analysis')
        doc = Document()
        for text in ['新增封面', '新增说明', '技术要求', quote]:
            doc.add_paragraph(text)
        doc.save(folder / 'normalized.docx')
    response = client.get(_url(project))
    assert response.status_code == 200, response.text
    items = [item for item in response.json()['items'] if item['quote'] == quote]
    assert len(items) == 2
    by_analysis = {item['analysis_id']: item for item in items}
    old = by_analysis['old-analysis']
    assert old['status'] == 'located' and old['locations'][0]['id'] == 'B0002'
    new = by_analysis['saved-analysis']
    if new_copy_missing:
        assert new['status'] == 'unavailable' and new['locations'] == []
    else:
        assert new['status'] == 'located' and new['locations'][0]['id'] == 'B0004'


def _preview(client, project, item, location_id=None, **changes):
    params = {key: item[key] for key in ('source_id', 'quote', 'source_sha256', 'analysis_id', 'normalized_sha256')
              if item.get(key) is not None}
    params['location_id'] = location_id or (item['locations'][0]['id'] if item['locations'] else 'L0001')
    params.update(changes)
    return client.get(_url(project).replace('evidence-locations', 'evidence-preview'), params=params)


def test_spec_review_batches_and_review_snapshot_keep_their_own_doc_coordinates(tmp_path):
    client, project = _case(tmp_path, '规范.doc', b'legacy spec bytes')
    quote = '工作压力：0.3 MPa。'
    def update(case):
        source = case['sources'][0]
        source['role'] = 'spec'
        old = {'id': 'spec-old', 'source_hashes': {source['id']: source['sha256']},
               'items': [{'requirement_id': 'r', 'evidence': [{'source_id': source['id'], 'quote': quote}]}]}
        new = deepcopy(old)
        new['id'] = 'spec-new'
        case['requirement_recommendations_history'] = [old]
        case['requirement_recommendations'] = new
        case['requirements'] = [{'id': 'r', 'analysis_id': 'saved-analysis', 'review': {
            'analysis_id': 'saved-analysis', 'recommendation_batch_id': 'spec-old',
            'recommendation': deepcopy(old['items'][0])}}]
    project, _ = _seed(client, project, [], update=update)
    _normalized_cache(client, project, name='spec-old')
    folder, _ = _normalized_cache(client, project, name='spec-new')
    doc = Document()
    doc.add_paragraph('新版规范说明')
    doc.add_paragraph('指标正文')
    doc.add_paragraph(quote)
    doc.save(folder / 'normalized.docx')
    response = client.get(_url(project))
    assert response.status_code == 200, response.text
    items = response.json()['items']
    assert len(items) == 2  # A reviewed citation shares its actual batch, not the source analysis.
    by_batch = {item['analysis_id']: item for item in items}
    assert by_batch['spec-old']['locations'][0]['id'] == 'B0002'
    assert by_batch['spec-new']['locations'][0]['id'] == 'B0003'
    for item in items:
        assert item['status'] == 'located' and item['coordinate_space'] == 'normalized'
        preview = _preview(client, project, item)
        assert preview.status_code == 200, preview.text
        assert preview.json()['selected_location_id'] == item['locations'][0]['id']


@pytest.mark.parametrize('quote,anchor', [
    ('技术要求', 'B0001'), ('工作压力：0.3MPa。', 'B0002'),
    ('工作温度 | 5℃～70℃', 'B0004-R002'), ('重复内容', 'B0006'),
    ('第一段。\n第二段。', 'B0008'),
])
def test_preview_uses_locator_coordinates_and_exact_text_highlights(tmp_path, quote, anchor):
    client, project = _case(tmp_path, '要求.docx', _document())
    _, before = _seed(client, project, [quote])
    item = _items(client, project)[quote]
    response = _preview(client, project, item, anchor)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    data = response.json()
    assert data['locations'] == item['locations']
    assert data['selected_location_id'] == anchor
    selected = next(block for block in data['blocks'] if block['id'] == anchor)
    assert any(segment['highlighted'] for segment in selected['segments'])
    for block in data['blocks']:
        assert ''.join(segment['text'] for segment in block['segments']) == block['text']
    if quote == '重复内容':
        assert [block['id'] for block in data['blocks'] if any(s['highlighted'] for s in block['segments'])] == ['B0005', 'B0006']
    assert str(tmp_path) not in response.text and 'path' not in data
    with client.app.state.rd_store._connection() as db:
        assert db.execute('SELECT payload FROM projects WHERE id=?', (project['id'],)).fetchone()[0] == before


def test_preview_preserves_text_line_numbers_and_returns_html_as_plain_text(tmp_path):
    quote = '<script>alert("😀")</script> 压力：0.3 MPa'
    client, project = _case(tmp_path, '要求.md', f'第一行\n\n{quote}\n第四行'.encode())
    _seed(client, project, [quote.replace('0.3 MPa', '0.3MPa')])
    item = next(iter(_items(client, project).values()))
    response = _preview(client, project, item)
    assert response.status_code == 200, response.text
    block = next(block for block in response.json()['blocks'] if block['id'] == 'L0003')
    assert block['text'] == quote and block['line'] == 3
    assert block['segments'] == [{'text': quote, 'highlighted': True}]


@pytest.mark.parametrize('changes,status', [
    ({'source_sha256': '0' * 64}, 409), ({'quote': 'arbitrary unsaved text'}, 404),
    ({'analysis_id': 'other-analysis'}, 404), ({'location_id': 'B9999'}, 404),
    ({'source_id': '../../other-source'}, 404),
])
def test_preview_rejects_stale_or_unsaved_reference_identity(tmp_path, changes, status):
    client, project = _case(tmp_path, '要求.docx', _document())
    _seed(client, project, ['技术要求'])
    response = _preview(client, project, _items(client, project)['技术要求'], **changes)
    assert response.status_code == status, response.text
    assert 'blocks' not in response.json()


def test_preview_authorizes_project_and_case_before_reading_blocks(tmp_path):
    client, project = _case(tmp_path, '要求.txt', b'private text')
    _seed(client, project, ['private text'])
    item = _items(client, project)['private text']
    stranger = make_client(tmp_path)
    assert _preview(stranger, project, item).status_code in {403, 404}
    unknown = deepcopy(project)
    unknown['cases'][0]['id'] = 'unknown'
    assert _preview(client, unknown, item).status_code == 404


def test_preview_retains_deleted_marker_and_refuses_changed_source_bytes(tmp_path):
    from pathlib import Path
    client, project = _case(tmp_path, '要求.txt', '旧版指标'.encode())
    project, _ = _seed(client, project, ['旧版指标'])
    item = _items(client, project)['旧版指标']
    source = project['cases'][0]['sources'][0]
    command(client, project, 'delete_source', source_id=source['id'])
    data = _preview(client, project, item).json()
    assert data['source_state'] == 'deleted' and data['source_version'] == 1
    Path(source['path']).write_text('changed bytes', encoding='utf-8')
    data = _preview(client, project, item).json()
    assert data['status'] == 'unavailable' and data['blocks'] == []
    assert data['reason'] == '原文件校验不一致'


def test_preview_legacy_copy_is_bound_to_analysis_and_normalized_hash(tmp_path):
    client, project = _case(tmp_path, '要求.doc', b'legacy document')
    project, _ = _seed(client, project, ['工作压力：0.3 MPa。'])
    folder, _ = _normalized_cache(client, project, name='saved-analysis')
    item = _items(client, project)['工作压力：0.3 MPa。']
    response = _preview(client, project, item)
    assert response.status_code == 200, response.text
    assert response.json()['coordinate_space'] == 'normalized'
    assert response.json()['normalized_sha256'] == item['normalized_sha256']
    doc = Document()
    doc.add_paragraph('改动说明')
    doc.add_paragraph(item['quote'])
    doc.save(folder / 'normalized.docx')
    assert _preview(client, project, item).status_code == 409


def test_preview_unsupported_source_offers_reason_without_content(tmp_path):
    client, project = _case(tmp_path, '要求.pdf', b'unsupported PDF fixture')
    _seed(client, project, ['不可读指标'])
    item = _items(client, project)['不可读指标']
    response = _preview(client, project, item)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'unavailable'
    assert response.json()['blocks'] == [] and response.json()['reason']


def test_preview_same_quote_keeps_each_retained_analysis_copy(tmp_path):
    client, project = _case(tmp_path, '重复分析.doc', b'legacy document')
    quote = '工作压力：0.3 MPa。'
    def update(case):
        previous = deepcopy(case['source_analysis'])
        previous['id'] = 'old-analysis'
        case['source_analysis_history'] = [previous]
        case['context_provenance'] = {'product_series': {'analysis_id': 'old-analysis',
            'evidence': [{'source_id': case['sources'][0]['id'], 'quote': quote}]}}
    project, _ = _seed(client, project, [quote], update=update)
    _normalized_cache(client, project, name='old-analysis')
    folder, _ = _normalized_cache(client, project, name='saved-analysis')
    doc = Document()
    for text in ['新增封面', '新增说明', '技术要求', quote]:
        doc.add_paragraph(text)
    doc.save(folder / 'normalized.docx')
    items = client.get(_url(project)).json()['items']
    assert len(items) == 2
    for item in items:
        data = _preview(client, project, item).json()
        expected = 'B0002' if item['analysis_id'] == 'old-analysis' else 'B0004'
        assert data['selected_location_id'] == expected
        assert data['normalized_sha256'] == item['normalized_sha256']
        assert next(block for block in data['blocks'] if block['id'] == expected)['segments'] == [
            {'text': quote, 'highlighted': True}]
    assert items[0]['normalized_sha256'] != items[1]['normalized_sha256']
