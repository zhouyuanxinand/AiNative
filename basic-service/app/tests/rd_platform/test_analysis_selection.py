"""Source-analysis adoption imports originals; spec decisions belong to their own batch."""
import pytest

from tests.rd_platform.test_source_analysis import analyze, command, install_model, setup_case


def _propose(tmp_path, monkeypatch):
    metrics = [('额定电压', '24 V'), ('接口路数', '8 路')]
    text = '\n'.join(f'{title}：{value}。' for title, value in metrics)
    client, project = setup_case(tmp_path, source_text=text)
    tech = project['cases'][0]['sources'][0]['id']
    cid = project['cases'][0]['id']
    response = client.post(f"/api/rd/projects/{project['id']}/cases/{cid}/sources",
        data={'expected_version': project['version'], 'role': 'spec'},
        files={'file': ('组件规范.txt', text.encode())}, headers={'Idempotency-Key': 'spec'})
    assert response.status_code == 200, response.text
    project = response.json()
    spec = next(item['id'] for item in project['cases'][0]['sources'] if item['role'] == 'spec')
    payload = install_model(monkeypatch, tech)
    payload['requirements'] = [
        {'title': title, 'content': f'{title}：{value}。', 'evidence': [{'source_id': tech, 'quote': f'{title}：{value}。'}],
         'recommendation': {'text': f'核对{title}', 'proposed_value': value, 'evidence': [{'source_id': spec, 'quote': f'{title}：{value}。'}]}}
        for title, value in metrics]
    response = analyze(client, project)
    assert response.status_code == 200, response.text
    return client, response.json()


def test_source_adoption_cannot_also_accept_an_enhancement(tmp_path, monkeypatch):
    client, project = _propose(tmp_path, monkeypatch)
    proposal = project['cases'][0]['source_analysis']
    response = client.post(f"/api/rd/projects/{project['id']}/commands", json={
        'expected_version': project['version'], 'command': 'adopt_source_analysis',
        'data': {'case_id': project['cases'][0]['id'], 'analysis_id': proposal['id'], 'accept_recommendations': [1]}},
        headers={'Idempotency-Key': 'cannot-select-enhancement'})
    assert response.status_code == 422 and '规范建议批次' in response.text
    current = client.get(f"/api/rd/projects/{project['id']}").json()
    assert current['version'] == project['version']
    assert current['cases'][0]['requirements'] == []
    assert current['cases'][0]['source_analysis'] == proposal
    case = command(client, project, 'adopt_source_analysis', analysis_id=proposal['id'], accept_recommendations=[])['cases'][0]
    originals, rows = case['source_analysis']['requirements'], case['requirements']
    assert [row['content'] for row in originals] == ['额定电压：24 V。', '接口路数：8 路。']
    assert rows[0]['content'] == originals[0]['content'] and not rows[0].get('review')
    assert rows[1]['content'] == originals[1]['content'] and not rows[1].get('review')
    assert case['source_analysis']['status'] == 'adopted'
    assert case['decisions'] == []


@pytest.mark.parametrize('selection', [[0, 98], [1], None, True])
def test_invalid_or_outdated_selection_does_not_import_any_rows(tmp_path, monkeypatch, selection):
    client, project = _propose(tmp_path, monkeypatch)
    case = project['cases'][0]
    path = f"/api/rd/projects/{project['id']}"
    response = client.post(path + '/commands', json={'expected_version': project['version'], 'command': 'adopt_source_analysis',
        'data': {'case_id': case['id'], 'analysis_id': case['source_analysis']['id'], 'accept_recommendations': selection}},
        headers={'Idempotency-Key': 'invalid-choice'})
    assert response.status_code == 422
    current = client.get(path).json()
    assert current['version'] == project['version']
    assert current['cases'][0]['requirements'] == [] and current['cases'][0]['source_analysis']['status'] == 'proposed'
