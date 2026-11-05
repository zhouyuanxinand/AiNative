"""Persist a catalog identity and exercise it through the real assistant client."""
import os

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jonhon_taskbook import llm_client as llm
from src.common.platform_auth import AuthSettings
from src.controller.rd_controller import router as rd_router
from src.controller.service_credentials_controller import router

URL = '/api/settings/credentials/default-model'
HEADERS = {'X-Credential-Settings': '1'}
SELECTION = {'provider': 'smartvision', 'name': 'openai/Qwen3.6-35B', 'id': '5660'}


@pytest.fixture
def client(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith(('MODEL_', 'AI_', 'JTB_', 'AZURE_', 'OPENAI_')):
            monkeypatch.delenv(key)
    for key, value in {'MODEL_BASE_URL': 'https://models.example/open/', 'MODEL_APP_ID': 'app',
                       'MODEL_API_KEY': 'secret', 'MODEL_TENANT_ID': 'tenant',
                       'MODEL_NAME': 'openai/qwen3.6',
                       'JTB_SERVICE_CREDENTIALS_DB': str(tmp_path / 'settings.sqlite3')}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(llm, '_runtime_config', None)
    monkeypatch.setattr(llm.httpx, 'get', lambda url, **kwargs: httpx.Response(
        200, request=httpx.Request('GET', url),
        json={'data': [{'model': SELECTION['name'], 'id': SELECTION['id']},
                       {'model': SELECTION['name'], 'id': 'other-deployment'}]}))
    app = FastAPI()
    app.state.auth_settings = AuthSettings(enabled=False)
    app.include_router(router)
    app.include_router(rd_router)
    return TestClient(app)


def test_saved_default_drives_real_chat_payload_and_preserves_explicit_selection(client, monkeypatch):
    initial = client.get(URL, headers=HEADERS)
    assert initial.status_code == 200
    assert initial.json()['requires_selection'] is True
    response = client.put(URL, headers=HEADERS, json=SELECTION)
    assert response.status_code == 200, response.text
    assert response.json() == {'selection': SELECTION, 'source': 'settings', 'requires_selection': False}
    assert 'secret' not in response.text
    assert llm.get_status()['model'] == SELECTION['name']
    requests = []
    def chat(url, **kwargs):
        requests.append(kwargs['json'])
        return httpx.Response(200, request=httpx.Request('POST', url),
                              json={'choices': [{'message': {'content': '你好，我们接着聊。'}, 'finish_reason': 'stop'}]})
    monkeypatch.setattr(llm.httpx, 'post', chat)
    # No mocked model resolver/chat: persistence must reach the actual HTTP boundary.
    result = client.post('/api/rd/assistant/chat', json={
        'message': '聊聊如何安排一天的工作',
        'history': [{'role': 'user', 'content': '我上午想先处理设计问题。'}],
    })
    assert result.status_code == 200, result.text
    assert result.json()['mode'] == 'model'
    assert requests[0]['model'] == SELECTION['name']
    assert requests[0]['extra_parameters'] == {'model_id': SELECTION['id']}
    assert '我上午想先处理设计问题' in requests[0]['messages'][1]['content']
    with llm.model_scope('smartvision', 'project-model', '77'):
        assert llm.chat('system', 'question')
    assert requests[1]['model'] == 'project-model'
    assert requests[1]['extra_parameters']['model_id'] == '77'
    assert client.get(URL, headers=HEADERS).json()['selection'] == SELECTION


@pytest.mark.parametrize('question', ['你好', '请解释需求追溯这个概念', '热力学中的温度是什么？'])
def test_configured_assistant_uses_model_for_free_conversation(client, monkeypatch, question):
    assert client.put(URL, headers=HEADERS, json=SELECTION).status_code == 200
    observed = []
    monkeypatch.setattr(llm, 'chat', lambda system, user, **kwargs: observed.append(user) or '这是针对当前提问的回答。')
    response = client.post('/api/rd/assistant/chat', json={'message': question})
    assert response.status_code == 200
    assert response.json()['mode'] == 'model'
    assert question in observed[0]


def test_incomplete_default_does_not_send_invalid_request(client, monkeypatch):
    monkeypatch.setattr(llm.httpx, 'post', lambda *a, **k: pytest.fail('invalid model must not reach upstream'))
    response = client.post('/api/rd/assistant/chat', json={'message': '聊聊如何安排一天的工作'})
    assert response.status_code == 200
    assert response.json()['mode'] == 'local_guidance'
    assert '默认模型' in response.json()['content']
    assert '设置' in response.json()['content']


@pytest.mark.parametrize('selection', [
    {**SELECTION, 'id': ''}, {**SELECTION, 'id': '0'}, {**SELECTION, 'id': '999'},
    {**SELECTION, 'name': 'openai/qwen3.6'}, {**SELECTION, 'provider': 'unconfigured'},
    {**SELECTION, 'extra': 'ignored'},
])
def test_default_requires_exact_available_catalog_identity(client, selection):
    response = client.put(URL, headers=HEADERS, json=selection)
    assert response.status_code == 400, response.text
    assert client.get(URL, headers=HEADERS).json()['source'] == 'deployment'


def test_credential_environment_switch_does_not_reuse_another_model_id(client, monkeypatch):
    assert client.put(URL, headers=HEADERS, json=SELECTION).status_code == 200
    monkeypatch.setenv('MODEL_TENANT_ID', 'another-tenant')
    assert client.get(URL, headers=HEADERS).json()['requires_selection'] is True
    monkeypatch.setenv('MODEL_TENANT_ID', 'tenant')
    assert client.get(URL, headers=HEADERS).json()['selection'] == SELECTION


@pytest.mark.parametrize('model_id', ['0', '-1', 'not-a-model-id'])
def test_invalid_deployment_id_does_not_reach_upstream(client, monkeypatch, model_id):
    monkeypatch.setenv('MODEL_ID', model_id)
    monkeypatch.setattr(llm.httpx, 'post', lambda *a, **k: pytest.fail('invalid ID reached upstream'))
    assert client.get(URL, headers=HEADERS).json()['requires_selection'] is True
    response = client.post('/api/rd/assistant/chat', json={'message': '聊聊如何安排一天的工作'})
    assert response.status_code == 200
    assert response.json()['mode'] == 'local_guidance'
    assert '默认模型' in response.json()['content']


def test_priority_change_between_existing_connections_does_not_reuse_model_id(client, monkeypatch):
    primary = llm._base_config()
    secondary = llm.make_config(provider='smartvision', api_key='another-secret', app_id='another-app',
                                endpoint='https://another.example/open/opi-maas/v1/chat/completions',
                                model='secondary-default')
    monkeypatch.setattr(llm, '_effective_configs', lambda: [primary, secondary])
    assert client.put(URL, headers=HEADERS, json=SELECTION).status_code == 200
    llm.configure_runtime(secondary, verify=False)
    assert client.get(URL, headers=HEADERS).json()['requires_selection'] is True
    assert llm.get_status()['model'] == 'secondary-default'


def test_failed_catalog_keeps_saved_default(client, monkeypatch):
    assert client.put(URL, headers=HEADERS, json=SELECTION).status_code == 200
    def fail(*args, **kwargs):
        raise httpx.ConnectError('secret transport details')
    monkeypatch.setattr(llm.httpx, 'get', fail)
    response = client.put(URL, headers=HEADERS, json=SELECTION)
    assert response.status_code == 503
    assert 'secret' not in response.text
    assert client.get(URL, headers=HEADERS).json()['selection'] == SELECTION


@pytest.mark.parametrize('headers', [{}, {**HEADERS, 'Sec-Fetch-Site': 'cross-site'}])
def test_default_settings_use_existing_same_site_boundary(client, headers):
    assert client.get(URL, headers=headers).status_code == 403
    assert client.put(URL, headers=headers, json=SELECTION).status_code == 403
