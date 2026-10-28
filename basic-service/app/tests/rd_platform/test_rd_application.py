from fastapi.testclient import TestClient


def test_rd_auth_expiry_returns_actionable_detail(tmp_path, monkeypatch):
    monkeypatch.setenv('JTB_AUTH_SETTINGS_DB', str(tmp_path / 'auth.sqlite3'))
    monkeypatch.setenv('JTB_AUTH_ENABLED', 'true')
    monkeypatch.setenv('JTB_AUTH_PUBLIC_URL', 'http://testserver')
    from src.main import create_app
    with TestClient(create_app()) as client:
        response = client.get('/api/rd/projects')
        assert response.status_code == 401
        assert response.json()['detail'] == '未登录或登录已失效'
        assert response.json()['auth_required'] is True


def test_rd_routes_are_mounted_and_anonymous_writes_are_denied(monkeypatch):
    monkeypatch.setenv('JTB_AUTH_ENABLED', 'false')
    from src.main import create_app
    with TestClient(create_app()) as client:
        response = client.get('/api/rd/projects')
        assert response.status_code == 401
        assert isinstance(response.json()['detail'], str)
        response = client.post('/api/rd/projects', json={'name': '匿名项目', 'customer': '客户', 'product': '连接器'}, headers={'Idempotency-Key': 'anonymous'})
        assert response.status_code == 401


def test_rd_deep_links_serve_application_shell(monkeypatch):
    monkeypatch.setenv('JTB_AUTH_ENABLED', 'false')
    from src.main import create_app
    with TestClient(create_app()) as client:
        for path in ['/rd', '/rd/project-example', '/rd/project-example/tasks/task-example', '/taskbook', '/requirements', '/tasks', '/artifacts', '/approvals']:
            response = client.get(path)
            assert response.status_code == 200
            assert 'text/html' in response.headers['content-type']


def test_demo_factory_is_usable_without_oa(tmp_path, monkeypatch):
    monkeypatch.setenv('JTB_DEMO_MODE', 'true')
    monkeypatch.setenv('JTB_AUTH_ENABLED', 'true')
    monkeypatch.setenv('JTB_AUTH_SETTINGS_DB', str(tmp_path / 'auth.sqlite3'))
    monkeypatch.setenv('JTB_RD_DB', str(tmp_path / 'demo.sqlite3'))
    monkeypatch.setenv('JTB_RD_ARTIFACTS', str(tmp_path / 'artifacts'))
    from src.common.platform_auth import PlatformTokenVerifier
    async def reject_network(*_args):
        raise AssertionError('Demo must never call OA')
    monkeypatch.setattr(PlatformTokenVerifier, '__call__', reject_network)
    from src.main import create_app
    with TestClient(create_app()) as client:
        assert client.get('/api/current-user').json()['user']['source'] == 'mock'
        assert client.get('/api/demo/status').json()['enabled'] is True
        workspace = client.get('/api/rd/workspace').json()
        assert len(workspace['projects']) == 3
        assert client.post('/api/demo/identity', json={'user_id': 'demo-engineer'}).status_code == 200
        assert client.get('/api/current-user').json()['user']['userid'] == 'demo-engineer'
