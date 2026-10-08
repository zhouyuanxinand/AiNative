import io
import pytest
import yaml
from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from jonhon_taskbook import failure_database as database_module
from jonhon_taskbook.failure_database import FailureDatabase
from jonhon_taskbook.failure_mode_matcher import match_failure_modes_with_audit
from jonhon_taskbook.fill import _fill_failure_mode_table
from src.controller import failure_database_controller as controller


@pytest.fixture
def failure_api(tmp_path, monkeypatch):
    workbook = Workbook()
    workbook.active.title = '故障分类词典'
    workbook.active.append(['说明'])
    sheet = workbook.create_sheet('现场历史')
    sheet.append(['数据所属产品的产品名称', '所属型号', '故障描述', '故障原因', '设计改进措施', '质量问题单号'])
    sheet.append(['滤波连接器-滤波连接器-接触件', 'J599/20FC04', '接触不良', '松动', '改进装配', 'QA-01'])
    sheet.append(['滤波连接器-滤波连接器-接触件', 'J599/21MTA', '绝缘失效', '', '', 'QA-02'])
    sheet.append([None] * 6)
    seed = tmp_path / 'seed.xlsx'
    workbook.save(seed)
    workbook.close()
    catalog = tmp_path / 'catalog.yaml'
    catalog.write_text(yaml.safe_dump({'product_types': {
        'filter_connector': {'label': '滤波连接器'},
        'rf_standard_interface': {'label': '射频连接器-标准界面射频连接器'},
    }}, allow_unicode=True), encoding='utf-8')
    store = FailureDatabase(tmp_path / 'failures.sqlite3', seed_path=seed, catalog_path=catalog)
    monkeypatch.setattr(controller, 'get_failure_database', lambda: store)
    monkeypatch.setattr(database_module, 'get_failure_database', lambda: store)
    application = FastAPI()
    application.include_router(controller.router)
    with TestClient(application) as client:
        yield client, store


def fields(**overrides):
    return {'product_type': 'filter_connector', 'product_name': '滤波连接器',
            'product_series': 'J599L', 'product_model': 'J599L-01', 'failure_location': '接触件',
            'failure_mode': '接触件脱落\n信号中断', 'failure_analysis': '固定结构不足',
            'improvement': '增加限位结构\n完成验证后固化工艺', **overrides}


def test_http_crud_is_persistent_and_changes_generated_failure_evidence(failure_api):
    client, store = failure_api
    seed_before = store.seed_path.read_bytes()
    assert match_failure_modes_with_audit('滤波连接器', 'J599L')[0] == []
    response = client.post('/api/failures', json=fields())
    assert response.status_code == 200, response.text
    created = response.json()
    record_id = created['id']
    records, audit = match_failure_modes_with_audit('滤波连接器', 'J599L')
    assert len(records) == 1
    assert records[0]['record_id'] == record_id
    assert records[0]['source_records'][0]['record_version'] == 1
    original_digest = audit['database_sha256']
    changed = client.put(f'/api/failures/{record_id}', json={**fields(improvement='更新改进措施\n保留经验'), 'expected_version': 1})
    assert changed.status_code == 200, changed.text
    assert changed.json()['version'] == 2
    assert client.get(f'/api/failures/{record_id}').json()['improvement'] == '更新改进措施\n保留经验'
    matches, latest = match_failure_modes_with_audit('滤波连接器', 'J599L')
    assert latest['database_revision'] > audit['database_revision']
    assert latest['database_sha256'] != original_digest
    doc = Document()
    table = doc.add_table(rows=2, cols=5)
    for cell, name in zip(table.rows[0].cells, ['数据所属产品', '失效部位', '失效模式', '失效分析', '可靠性设计方法']):
        cell.text = name
    assert _fill_failure_mode_table(doc, matches) == 1
    output = io.BytesIO()
    doc.save(output)
    assert Document(io.BytesIO(output.getvalue())).tables[0].cell(1, 4).text == '更新改进措施\n保留经验'
    # An explicitly assigned series is not widened back to the model prefix.
    assert all(record.get('record_id') != record_id for record in match_failure_modes_with_audit('滤波连接器', 'J599')[0])
    assert match_failure_modes_with_audit('射频连接器-标准界面射频连接器', 'J599L')[0] == []
    response = client.delete(f'/api/failures/{record_id}?expected_version=2')
    assert response.status_code == 200 and response.json()['deleted']
    assert client.get(f'/api/failures/{record_id}').status_code == 404
    assert match_failure_modes_with_audit('滤波连接器', 'J599L')[0] == []
    restarted = FailureDatabase(store.path, seed_path=store.seed_path, catalog_path=store.catalog_path)
    assert restarted.search()['total'] == 2
    assert restarted.options()['imported_count'] == 2
    assert store.seed_path.read_bytes() == seed_before


def test_import_preserves_all_source_columns_and_does_not_guess_series(failure_api):
    client, store = failure_api
    options = client.get('/api/failures/options').json()
    assert options['total'] == options['imported_count'] == 2
    record = client.get('/api/failures/1').json()
    assert record['source_data']['质量问题单号'] == 'QA-01'
    assert record['product_series'] == ''
    assert record['product_model'] == 'J599/20FC04'
    assert record['source_sheet'] == '现场历史' and record['source_row'] == 2
    assert len(match_failure_modes_with_audit('滤波连接器', 'J599')[0]) == 2
    incomplete = client.get('/api/failures/2').json()
    assert incomplete['improvement'] == incomplete['failure_analysis'] == ''
    assert next(product['count'] for product in store.options()['products'] if product['id'] == 'filter_connector') == 2


def test_stale_edit_delete_and_invalid_fields_do_not_overwrite_records(failure_api):
    client, store = failure_api
    created = client.post('/api/failures', json=fields()).json()
    endpoint = '/api/failures/' + str(created['id'])
    updated = client.put(endpoint, json={**fields(failure_mode='已确认的故障'), 'expected_version': 1})
    assert updated.status_code == 200
    assert client.put(endpoint, json={**fields(), 'expected_version': 1}).status_code == 409
    assert client.delete(endpoint + '?expected_version=1').status_code == 409
    assert client.get(endpoint).json()['failure_mode'] == '已确认的故障'
    before = store.search()['total']
    for change in ({'failure_mode': ' '}, {'product_type': 'missing'}, {'product_model': '', 'product_series': ''},
                   {'product_name': 12}, {'extra': 'not allowed'}, {'improvement': 'x' * 20001}):
        assert client.post('/api/failures', json=fields(**change)).status_code == 400
    assert client.put(endpoint, json=[]).status_code == 400
    assert store.search()['total'] == before


def test_query_filters_literal_keywords_and_pagination(failure_api):
    client, _ = failure_api
    client.post('/api/failures', json=fields(failure_mode='寿命 100% 测试'))
    client.post('/api/failures', json=fields(product_series='J599LM', product_model='J599LM-01', improvement='额外经验'))
    client.post('/api/failures', json=fields(product_type='rf_standard_interface', product_name='射频连接器', product_series='SMA', product_model='SMA-01'))
    result = client.get('/api/failures', params={'product_type': 'filter_connector', 'series': 'J599L', 'page_size': 1}).json()
    assert result['total'] == 2 and result['pages'] == 2 and len(result['items']) == 1
    other = client.get('/api/failures', params={'product_type': 'filter_connector', 'series': 'J599L', 'page_size': 1, 'page': 2}).json()
    assert other['items'][0]['id'] != result['items'][0]['id']
    assert client.get('/api/failures', params={'q': '100%'}).json()['total'] == 1
    assert client.get('/api/failures', params={'q': "' OR 1=1 --"}).json()['total'] == 0
    assert client.get('/api/failures', params={'q': '额外经验'}).json()['total'] == 1
    assert client.get('/api/failures?page_size=101').status_code == 422
