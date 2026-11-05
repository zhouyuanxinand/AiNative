"""Exercise persisted platform conversations through HTTP and real SQLite transactions."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jonhon_taskbook import llm_client
from src.common.platform_auth import AuthSettings
from src.controller.rd_controller import router
from src.service.rd_platform.store import RdError, Store


URL = '/api/rd/assistant/conversations'


def make_client(path, *, actor=None, authenticated=False):
    app = FastAPI()
    app.state.auth_settings = AuthSettings(enabled=authenticated)
    app.state.rd_store = Store(path, path.parent / 'assets')
    if actor:
        @app.middleware('http')
        async def identity(request, call_next):
            request.state.current_user = {'userid': actor}
            return await call_next(request)
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_client, 'get_model_status', lambda: {'configured': False})
    monkeypatch.setattr(llm_client, 'chat', lambda *a, **k: pytest.fail('unexpected upstream request'))
    return make_client(tmp_path / 'rd.sqlite3')


def create(client, key='create', source_id=None):
    response = client.post(URL, json={} if source_id is None else {'source_id': source_id},
                           headers={'Idempotency-Key': key})
    assert response.status_code == 200, response.text
    return response.json()


def send(client, conversation, key, message='你好'):
    response = client.post(f"{URL}/{conversation['id']}/messages",
                           json={'message': message, 'expected_version': conversation['version']},
                           headers={'Idempotency-Key': key})
    assert response.status_code == 200, response.text
    return response.json()


def close(client, conversation, key, choice, draft=''):
    return client.post(f"{URL}/{conversation['id']}/close",
                       json={'choice': choice, 'draft': draft, 'expected_version': conversation['version']},
                       headers={'Idempotency-Key': key})


def test_keep_and_end_survive_restart_without_losing_completed_messages(client):
    first = create(client)
    assert first['version'] == 1 and first['messages'] == [] and first['draft'] == ''
    replied = send(client, first, 'question')
    assert replied['message_count'] == 2 and replied['version'] == 2
    assert [item['role'] for item in replied['messages']] == ['user', 'assistant']
    kept = close(client, replied, 'keep', 'keep', '下次继续讨论的草稿')
    assert kept.status_code == 200, kept.text
    assert kept.json() == {'active_id': first['id']}
    restarted = make_client(client.app.state.rd_store.path)
    restarted.cookies.update(client.cookies)
    listing = restarted.get(URL).json()
    assert listing['active_id'] == first['id'] and listing['total'] == 1
    resumed = restarted.get(f"{URL}/{first['id']}").json()
    assert resumed['draft'] == '下次继续讨论的草稿'
    assert resumed['version'] == 3 and resumed['messages'] == replied['messages']
    ended = close(restarted, resumed, 'end', 'end', '这段不应留下')
    assert ended.status_code == 200 and ended.json() == {'active_id': None}
    saved = restarted.get(f"{URL}/{first['id']}").json()
    assert saved['draft'] == '' and saved['messages'] == replied['messages']
    assert restarted.get(URL).json()['active_id'] is None
    fresh = create(restarted, 'new-after-end')
    assert fresh['id'] != first['id'] and fresh['messages'] == []
    assert restarted.get(URL).json()['total'] == 2


def test_context_comes_from_last_twelve_saved_messages_and_versions_conflict(client, monkeypatch):
    from src.service.rd_platform import platform_conversations as conversations
    observed = []
    def answer(actor, message, history):
        observed.append((actor, message, history))
        return {'content': f'回答{len(observed)}', 'mode': 'model', 'actions': []}
    monkeypatch.setattr(conversations, 'ask_platform', answer)
    current = create(client)
    initial = current
    for index in range(8):
        current = send(client, current, f'q-{index}', f'问题{index}')
    assert observed[0][2] == []
    assert observed[-1][2] == [
        {'role': item['role'], 'content': item['content']} for item in current['messages'][2:14]
    ]
    assert observed[0][0].startswith('local:')
    assert current['title'] == '问题0'
    assert current['messages'][-1]['mode'] == 'model'
    stale = client.post(f"{URL}/{current['id']}/messages", headers={'Idempotency-Key': 'stale'},
                        json={'message': '过期版本', 'expected_version': initial['version']})
    assert stale.status_code == 409 and len(observed) == 8
    forged = client.post(f"{URL}/{current['id']}/messages", headers={'Idempotency-Key': 'forged'},
                         json={'message': '伪造历史', 'expected_version': current['version'], 'history': []})
    assert forged.status_code == 422


def test_fork_copies_full_history_and_keeps_source_unchanged(client):
    current = create(client)
    for index in range(23):
        current = send(client, current, f'q-{index}')
    assert len(current['messages']) == 40 and current['message_count'] == 46
    assert current['has_more'] is True
    older = client.get(f"{URL}/{current['id']}?before={current['next_before']}").json()
    assert len(older['messages']) == 6 and older['has_more'] is False and older['next_before'] is None
    source_messages = older['messages'] + current['messages']
    assert close(client, current, 'end-source', 'end').status_code == 200
    source = client.get(f"{URL}/{current['id']}").json()
    forked = create(client, 'fork', source['id'])
    assert forked['id'] != source['id'] and forked['source_id'] == source['id']
    assert source['title'] in forked['title'] and forked['title'] != source['title']
    assert forked['message_count'] == 46 and forked['version'] == 1
    old_fork = client.get(f"{URL}/{forked['id']}?before={forked['next_before']}").json()
    copied = old_fork['messages'] + forked['messages']
    assert [(m['role'], m['content']) for m in copied] == [(m['role'], m['content']) for m in source_messages]
    assert {m['id'] for m in copied}.isdisjoint(m['id'] for m in source_messages)
    assert create(client, 'fork', source['id']) == forked
    send(client, forked, 'fork-question', '怎样上传技术资料？')
    assert client.get(f"{URL}/{source['id']}").json() == source
    inactive = close(client, source, 'change-source', 'keep', '不能覆盖原文')
    assert inactive.status_code == 409


def test_conversation_pages_preserve_older_records(client):
    ids = [create(client, f'create-{index}')['id'] for index in range(23)]
    first, second = client.get(URL).json(), client.get(URL + '?page=2').json()
    assert first['total'] == second['total'] == 23
    assert first['page_size'] == second['page_size'] == 20
    assert first['page'] == 1 and second['page'] == 2
    assert len(first['items']) == 20 and len(second['items']) == 3
    assert {row['id'] for row in first['items'] + second['items']} == set(ids)
    assert first['active_id'] == ids[-1]
    assert all('messages' not in row and 'draft' not in row for row in first['items'])


def test_failures_can_retry_same_key_and_successful_receipt_is_not_repeated(client, monkeypatch):
    from src.service.rd_platform import platform_conversations as conversations
    calls = []
    def answer(*args):
        calls.append(args)
        if len(calls) == 1:
            raise RdError(503, '模型暂时未完成')
        return {'content': '重试成功', 'mode': 'model', 'actions': []}
    monkeypatch.setattr(conversations, 'ask_platform', answer)
    current = create(client)
    path = f"{URL}/{current['id']}/messages"
    payload = {'message': '继续讨论', 'expected_version': 1}
    failed = client.post(path, json=payload, headers={'Idempotency-Key': 'retry'})
    assert failed.status_code == 503
    assert client.get(f"{URL}/{current['id']}").json() == current
    retried = client.post(path, json=payload, headers={'Idempotency-Key': 'retry'})
    assert retried.status_code == 200
    replay = client.post(path, json=payload, headers={'Idempotency-Key': 'retry'})
    assert replay.json() == retried.json() and len(calls) == 2
    conflict = client.post(path, json={**payload, 'message': '另一个问题'}, headers={'Idempotency-Key': 'retry'})
    assert conflict.status_code == 409 and len(calls) == 2
    assert retried.json()['message_count'] == 2
    assert close(client, retried.json(), 'closed', 'end').status_code == 200
    assert close(client, retried.json(), 'closed', 'end').json() == {'active_id': None}
    assert close(client, retried.json(), 'closed', 'keep').status_code == 409
    assert client.post(URL, json={}, headers={'Idempotency-Key': 'retry'}).status_code == 409


def test_local_and_verified_actors_cannot_read_fork_or_mutate_another_history(client):
    original = send(client, create(client), 'q')
    other = make_client(client.app.state.rd_store.path)
    oa = make_client(client.app.state.rd_store.path, actor='oa-user', authenticated=True)
    for stranger in (other, oa):
        assert stranger.get(URL).json()['total'] == 0
        assert stranger.get(f"{URL}/{original['id']}").status_code == 404
        assert stranger.post(URL, json={'source_id': original['id']}, headers={'Idempotency-Key': 'fork'}).status_code == 404
        assert stranger.post(f"{URL}/{original['id']}/messages", headers={'Idempotency-Key': 'q'},
                             json={'message': '偷看', 'expected_version': original['version']}).status_code == 404
        assert close(stranger, original, 'close', 'end').status_code == 404
        assert create(stranger)['id'] != original['id']
    assert client.get(f"{URL}/{original['id']}").json() == original


def test_auth_same_origin_and_input_limits_are_preserved(client):
    assert client.post(URL, json={}).status_code == 400
    assert client.post(URL, json={}, headers={'Idempotency-Key': 'x', 'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.post(URL, json={'actor': 'forged'}, headers={'Idempotency-Key': 'x'}).status_code == 422
    current = create(client)
    for message in (' ', 'x' * 2001, 'bad\x00message'):
        response = client.post(f"{URL}/{current['id']}/messages", headers={'Idempotency-Key': 'invalid'},
                               json={'message': message, 'expected_version': 1})
        assert response.status_code == 422
    assert close(client, current, 'invalid-draft', 'keep', 'x' * 2001).status_code == 422
    assert client.get(URL + '?page=0').status_code == 422
    assert client.get(f"{URL}/{current['id']}?before=0").status_code == 422
    anonymous = make_client(client.app.state.rd_store.path, authenticated=True)
    assert anonymous.get(URL).status_code == 401


def test_pending_reply_serializes_mutations_without_holding_database_lock(client, monkeypatch):
    from src.service.rd_platform import platform_conversations as conversations
    service = conversations.PlatformConversations(client.app.state.rd_store.path)
    current = service.create('actor', 'create')
    entered, release = Event(), Event()
    def answer(*args):
        entered.set()
        assert release.wait(5)
        return {'content': '已回答', 'mode': 'model', 'actions': []}
    monkeypatch.setattr(conversations, 'ask_platform', answer)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.ask, 'actor', current['id'], '问题', 1, 'pending')
        try:
            assert entered.wait(5)
            for operation in (
                lambda: service.ask('actor', current['id'], '问题', 1, 'pending'),
                lambda: service.ask('actor', current['id'], '其他问题', 1, 'other'),
                lambda: service.close('actor', current['id'], 'keep', '', 1, 'close'),
                lambda: service.create('actor', 'new'),
            ):
                with pytest.raises(RdError) as error:
                    operation()
                assert error.value.status == 409
            assert service.get('actor', current['id'])['messages'] == []
            assert service.create('other-actor', 'independent')['message_count'] == 0
        finally:
            release.set()
        assert pending.result()['message_count'] == 2


@pytest.mark.parametrize('recovery', ['retry', 'end'])
def test_expired_pending_lease_fences_late_model_reply(client, monkeypatch, recovery):
    from src.service.rd_platform import platform_conversations as conversations
    service = conversations.PlatformConversations(client.app.state.rd_store.path)
    current = service.create('actor', 'create')
    entered, release = Event(), Event()
    clock = [1000.0]
    monkeypatch.setattr(conversations.time, 'time', lambda: clock[0])
    calls = []
    def answer(*args):
        calls.append(args)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
            return {'content': '不得采用的晚到回复', 'mode': 'model', 'actions': []}
        return {'content': '恢复后的回复', 'mode': 'model', 'actions': []}
    monkeypatch.setattr(conversations, 'ask_platform', answer)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.ask, 'actor', current['id'], '问题', 1, 'pending')
        try:
            assert entered.wait(5)
            clock[0] += 61
            if recovery == 'retry':
                service.ask('actor', current['id'], '问题', 1, 'pending')
            else:
                service.close('actor', current['id'], 'end', '', 1, 'close')
        finally:
            release.set()
        try:
            pending.result()
        except RdError as error:
            assert error.status == 409
    saved = service.get('actor', current['id'])
    assert '晚到回复' not in json.dumps(saved, ensure_ascii=False)
    assert saved['message_count'] == (2 if recovery == 'retry' else 0)
    if recovery == 'retry':
        assert saved['messages'][-1]['content'] == '恢复后的回复'


def test_credentials_are_redacted_before_storage_and_model_context(client, monkeypatch):
    from src.service.rd_platform import platform_conversations as conversations
    observed = []
    def answer(actor, message, history):
        observed.append((message, history))
        return {'content': '不要展示 password=reply-secret', 'mode': 'model', 'actions': []}
    monkeypatch.setattr(conversations, 'ask_platform', answer)
    current = send(client, create(client), 'redacted', '看一下 api_key=input-secret')
    assert close(client, current, 'draft', 'keep', '草稿 access_token=draft-secret').status_code == 200
    saved = client.get(f"{URL}/{current['id']}").json()
    rendered = json.dumps([saved, observed], ensure_ascii=False)
    assert all(secret not in rendered for secret in ('input-secret', 'reply-secret', 'draft-secret'))
