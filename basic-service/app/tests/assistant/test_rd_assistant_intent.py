"""Auto intent resolves before any permission-scoped project lookup."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.controller import assistant_controller, rd_dependencies
from src.service.assistant import conversation as assistant
from src.service.rd_platform.store import RdStore


@pytest.fixture
def auto_client(tmp_path, monkeypatch):
    store = RdStore(tmp_path / 'rd.sqlite3', tmp_path / 'artifacts')
    actor = {'user_id': 'owner', 'display_name': '负责人'}
    detail = store.create_project(actor, {'name': '不应进入分类器的项目资料', 'customer': '私有客户', 'product': '连接器'}, 'create')
    app = FastAPI()
    app.include_router(assistant_controller.router)
    app.dependency_overrides[rd_dependencies.require_actor] = lambda: actor
    monkeypatch.setattr(assistant_controller, 'get_store', lambda: store)
    monkeypatch.setattr(assistant, '_model_status', lambda: {'configured': True, 'model': 'test-model'})
    with TestClient(app) as client:
        yield client, store, actor, detail['project']['id']


@pytest.mark.parametrize('question', ['你好', '解释Python异步编程', 'React项目需求怎么设计？', '介绍动态规划算法', '帮我写作一首诗', '今天的天气怎么样？', 'VS Code Workspace怎么配置？', '当前项目里用Python怎么实现快速排序算法？', '写个Python函数演示如何修改第一条需求标题'])
def test_clear_general_questions_never_load_project_context(auto_client, monkeypatch, question):
    client, store, _, pid = auto_client
    for method in ('detail', 'list_projects', 'workspace'):
        monkeypatch.setattr(store, method, lambda *_a, **_kw: pytest.fail('General questions cannot read project data'))
    monkeypatch.setattr(assistant, '_call_intent_model', lambda *_: pytest.fail('Clear general intent needs no model classification'))
    calls = []
    monkeypatch.setattr(assistant, '_call_model', lambda system, user: calls.append(json.loads(user)) or '这是通用回答。')
    response = client.post('/api/assistant/chat', json={'mode': 'auto', 'message': question, 'project_id': pid})
    assert response.status_code == 200
    assert response.json()['mode'] == 'general' and response.json()['intent'] == 'general_chat'
    assert response.json()['actions'] == [] and response.json().get('proposal') is None
    assert 'context' not in calls[0] and pid not in json.dumps(calls)


def test_default_auto_preserves_project_operation_confirmation(auto_client, monkeypatch):
    client, store, actor, pid = auto_client
    d = store.detail(pid, actor['user_id'])
    d = store.execute(pid, actor, 'save_requirement', {'title': '旧标题', 'content': '原正文'}, d['project']['version'], 'requirement')
    rid = d['requirements'][0]['id']
    monkeypatch.setattr(assistant, '_call_intent_model', lambda *_: pytest.fail('Explicit project action needs no classifier'))
    monkeypatch.setattr(assistant, '_call_model', lambda *_: json.dumps({'reply': '请核对标题。', 'operation': {'action': 'save_requirement', 'payload': {'id': rid, 'title': '可靠性验收'}}}))
    response = client.post('/api/assistant/chat', json={'message': '将第一条需求标题修改为可靠性验收', 'project_id': pid})
    assert response.status_code == 200
    assert response.json()['mode'] == 'platform' and response.json()['intent'] == 'business_operation'
    assert response.json()['proposal']['requires_confirmation'] is True
    assert store.detail(pid, actor['user_id']) == d


@pytest.mark.parametrize('question', ['请将第一条需求标题修改为React接口验证', '把第一条需求标题改成Python代码示例', '请为当前项目新增React接口验证需求'])
def test_technology_words_in_business_write_values_keep_project_intent(auto_client, monkeypatch, question):
    client, _, _, pid = auto_client
    monkeypatch.setattr(assistant, '_call_intent_model', lambda *_: pytest.fail('Explicit record write needs no classifier'))
    monkeypatch.setattr(assistant, '_call_model', lambda *_: '{"reply":"请补充具体验收条件。","operation":null}')
    response = client.post('/api/assistant/chat', json={'message': question, 'project_id': pid})
    assert response.status_code == 200
    assert response.json()['mode'] == 'platform' and response.json()['intent'] == 'business_operation'


def test_bare_workspace_word_does_not_force_business_context(auto_client, monkeypatch):
    client, store, _, pid = auto_client
    for method in ('detail', 'list_projects', 'workspace'):
        monkeypatch.setattr(store, method, lambda *_a, **_kw: pytest.fail('Ambiguous workspace resolved general cannot read projects'))
    calls = []
    monkeypatch.setattr(assistant, '_call_intent_model', lambda *_: calls.append(True) or '{"mode":"general","intent":"general_chat"}')
    monkeypatch.setattr(assistant, '_call_model', lambda *_: '请问指哪类工作区？')
    response = client.post('/api/assistant/chat', json={'message': '介绍一下Workspace', 'project_id': pid})
    assert response.status_code == 200 and response.json()['mode'] == 'general' and calls == [True]


def test_ambiguous_classifier_uses_only_bounded_visible_conversation(auto_client, monkeypatch):
    client, store, _, pid = auto_client
    for method in ('detail', 'list_projects', 'workspace'):
        monkeypatch.setattr(store, method, lambda *_a, **_kw: pytest.fail('Resolved general intent cannot load project data'))
    calls = []
    def classify(system, user):
        calls.append(json.loads(user))
        return json.dumps({'mode': 'general', 'intent': 'general_chat'})
    monkeypatch.setattr(assistant, '_call_intent_model', classify)
    monkeypatch.setattr(assistant, '_call_model', lambda *_: '可以，我们先说清楚问题。')
    history = [{'role': 'user', 'content': '讨论写一篇游记'}, {'role': 'assistant', 'content': '可以从旅程结构入手。'}]
    response = client.post('/api/assistant/chat', json={'mode': 'auto', 'message': '能进一步说明吗？', 'project_id': pid, 'history': history})
    assert response.status_code == 200 and response.json()['mode'] == 'general'
    assert calls[0]['question'] == '能进一步说明吗？'
    assert calls[0]['history'] == history
    assert set(calls[0]) == {'question', 'history'}
    assert pid not in json.dumps(calls) and '不应进入分类器的项目资料' not in json.dumps(calls, ensure_ascii=False)


def test_model_recognizes_business_followup_from_conversation(auto_client, monkeypatch):
    client, _, _, pid = auto_client
    histories = []
    def classify(system, user):
        histories.append(json.loads(user)['history'])
        return '{"mode":"platform","intent":"business_question"}'
    monkeypatch.setattr(assistant, '_call_intent_model', classify)
    monkeypatch.setattr(assistant, '_call_model', lambda *_: '{"reply":"请从固定成果进入工程审签。","operation":null}')
    history = [{'role': 'user', 'content': '当前项目的任务书送审后怎么推进？'}, {'role': 'assistant', 'content': '需要由指定独立评审核对。'}]
    response = client.post('/api/assistant/chat', json={'mode': 'auto', 'message': '那接下来呢？', 'history': history, 'project_id': pid})
    assert response.status_code == 200 and response.json()['mode'] == 'platform'
    assert response.json()['intent'] == 'business_question' and response.json()['actions']
    assert histories == [history]


def test_unavailable_classifier_has_safe_history_fallback_and_no_fabricated_action(auto_client, monkeypatch):
    client, store, actor, pid = auto_client
    before = store.detail(pid, actor['user_id'])
    monkeypatch.setattr(assistant, '_model_status', lambda: {'configured': False})
    response = client.post('/api/assistant/chat', json={'mode': 'auto', 'message': '那下一步呢？', 'project_id': pid,
        'history': [{'role': 'user', 'content': '当前项目怎么完成工程审签？'}]})
    assert response.status_code == 200 and response.json()['mode'] == 'platform'
    assert response.json()['source'] == 'platform-guide' and response.json().get('proposal') is None
    assert store.detail(pid, actor['user_id']) == before
    assert client.post('/api/assistant/chat', json={'mode': 'auto', 'message': '你好', 'project_id': pid}).status_code == 503


@pytest.mark.parametrize('classification', ['not-json', '{"mode":"admin","intent":"execute_shell"}', '{"mode":"platform","operation":{"action":"delete_project"}}'])
def test_invalid_classifier_never_becomes_a_project_operation(auto_client, monkeypatch, classification):
    client, store, _, pid = auto_client
    for method in ('detail', 'list_projects', 'workspace'):
        monkeypatch.setattr(store, method, lambda *_a, **_kw: pytest.fail('Invalid classifier must not read project data'))
    monkeypatch.setattr(assistant, '_call_intent_model', lambda *_: classification)
    monkeypatch.setattr(assistant, '_call_model', lambda *_: '请说明需要帮助的内容。')
    response = client.post('/api/assistant/chat', json={'mode': 'auto', 'message': '帮我处理一下吧', 'project_id': pid})
    assert response.status_code == 200 and response.json()['mode'] == 'general'
    assert response.json().get('proposal') is None
