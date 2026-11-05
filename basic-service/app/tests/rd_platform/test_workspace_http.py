"""The HTTP boundary never derives capability roles from RD administrator status."""
import pytest
from fastapi.testclient import TestClient

from tests.rd_platform.test_http import make_client


def roles(client, monkeypatch, publish=False, grant=False):
    actor = client.get('/api/rd/session').json()['actor_id']
    monkeypatch.setenv('JTB_RD_WORKSPACE_PUBLISHERS', actor if publish else '')
    monkeypatch.setenv('JTB_RD_WORKSPACE_GRANT_MANAGERS', actor if grant else '')


def post(client, endpoint, payload, key='write'):
    return client.post('/api/rd/workspace/' + endpoint, json=payload, headers={'Idempotency-Key': key})


def test_default_catalog_is_filtered_summary_and_management_is_private(tmp_path):
    client = make_client(tmp_path)
    session = client.get('/api/rd/workspace/session').json()
    assert session['application_id'] == 'rd-platform-local'
    assert session['can_publish_resources'] is False
    assert session['can_manage_application_grants'] is False
    assert client.get('/api/rd/workspace/resources').status_code == 403
    page = client.get('/api/rd/catalog/resources').json()
    assert page['total'] == 10 and len(page['items']) == 5 and page['page_size'] == 5
    assert all('configuration' not in item for item in page['items'])
    assert len(client.get('/api/rd/catalog/resources?page=2').json()['items']) == 5
    assert client.get('/api/rd/catalog/resources/missing/1').status_code == 404


def test_publication_and_application_grant_require_separate_roles(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    roles(client, monkeypatch, publish=True)
    resource = post(client, 'resources', {'id': 'http-skill', 'name': 'HTTP资源', 'kind': 'skill', 'configuration': {}, 'expected_version': 0}, 'save')
    assert resource.status_code == 200, resource.text
    item = resource.json()
    payload = {'id': item['id'], 'version': 1, 'expected_version': 1, 'operation': 'publish', 'expected_state_revision': item['publication_revision'], 'expected_control_revision': item['control_revision']}
    published = post(client, 'resources', payload, 'publish')
    assert published.status_code == 200, published.text
    assert published.json()['version'] == 1
    assert post(client, 'resources', payload, 'publish').json() == published.json()
    grant = {'id': item['id'], 'version': 1, 'operation': 'grant', 'expected_revision': 0}
    assert post(client, 'grants', grant, 'denied').status_code == 403
    assert client.get('/api/rd/catalog/resources/http-skill/1').status_code == 404
    roles(client, monkeypatch, grant=True)
    assert post(client, 'resources', payload, 'other-publish').status_code == 403
    assert post(client, 'grants', grant, 'allow').status_code == 200
    assert client.get('/api/rd/catalog/resources/http-skill/1').status_code == 200
    assert client.get('/api/rd/workspace/resources/http-skill/latest').json()['version'] == 1
    assert post(client, 'grants', {**grant, 'operation': 'revoke', 'expected_revision': 1}, 'revoke').status_code == 200
    assert client.get('/api/rd/catalog/resources/http-skill/1').status_code == 404
    assert client.get('/api/rd/catalog/resources?q=http').json()['total'] == 0


def test_old_admin_cookie_and_client_permissions_do_not_grant_roles(tmp_path, monkeypatch):
    from src.common.admin_auth import ADMIN_COOKIE
    client = make_client(tmp_path)
    roles(client, monkeypatch)
    client.cookies.set(ADMIN_COOKIE, 'not-a-role')
    response = post(client, 'resources', {'name': 'forged', 'kind': 'skill', 'can_manage': True}, 'forged')
    assert response.status_code == 403
    assert client.get('/api/rd/workspace/resources?can_manage=true').status_code == 403


def test_client_application_id_cannot_redirect_authority(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    roles(client, monkeypatch, grant=True)
    grant = {'id': 'generate', 'version': 1, 'operation': 'revoke', 'expected_revision': 1, 'application_id': 'foreign'}
    assert post(client, 'grants', grant).status_code == 422
    assert client.get('/api/rd/catalog/resources/generate/1?application_id=foreign').status_code == 200


def test_catalog_selection_and_paginated_views_agree_after_revocation(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    roles(client, monkeypatch, grant=True)
    assert post(client, 'grants', {'id': 'generate', 'version': 1, 'operation': 'revoke', 'expected_revision': 1}).status_code == 200
    bootstrap = client.get('/api/rd/catalog').json()
    assert all(item['id'] != 'generate' for item in bootstrap['actions'])
    assert all(item['id'] != 'taskbook' for item in bootstrap['workpackage_definitions'])
    assert client.get('/api/rd/catalog/items?category=actions&q=generate').json()['total'] == 0
    assert client.get('/api/rd/catalog/items?category=workpackages&q=taskbook').json()['total'] == 0


@pytest.mark.parametrize('query', ['page=0', 'page_size=51', 'page_size=0', 'kind=bad'])
def test_paging_validation(tmp_path, query):
    assert make_client(tmp_path).get('/api/rd/catalog/resources?' + query).status_code == 422


def test_local_bootstrap_is_loopback_only_and_never_oa(tmp_path, monkeypatch):
    monkeypatch.setenv('JTB_RD_LOCAL_WORKSPACE_ADMIN', '1')
    client = make_client(tmp_path)
    assert client.get('/api/rd/workspace/session').json()['local_bootstrap'] is False
    local = TestClient(client.app, client=('127.0.0.1', 51000))
    assert local.get('/api/rd/workspace/session').json()['can_manage_application_grants'] is True
    oa = make_client(tmp_path / 'oa', auth=True)
    @oa.app.middleware('http')
    async def verified_oa(request, call_next):
        request.state.current_user = {'userid': 'oa-user', 'username': 'OA用户'}
        return await call_next(request)
    local_oa = TestClient(oa.app, client=('127.0.0.1', 51000))
    assert local_oa.get('/api/rd/workspace/session').json()['local_bootstrap'] is False
