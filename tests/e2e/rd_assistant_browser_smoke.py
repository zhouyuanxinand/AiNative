"""Real browser + assistant HTTP + SQLite; model text is synthetic, no external calls."""
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_support import APP, browser_options
sys.path[:0] = [str(APP), str(APP / 'src/service')]
EVIDENCE = APP / 'runtime/xiaohang-integration'


def run():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    # Retain the isolated SQLite fixture with the browser evidence for inspection.
    with tempfile.TemporaryDirectory(prefix='fixture-', dir=EVIDENCE, delete=False) as temp:
        temporary = Path(temp)
        os.environ.update({'JTB_DEMO_MODE': 'true', 'JTB_RD_DB': str(temporary / 'rd.sqlite3'),
                           'JTB_RD_ARTIFACTS': str(temporary / 'artifacts'),
                           'JTB_AUTH_SETTINGS_DB': str(temporary / 'auth.sqlite3'),
                           'JTB_SERVICE_CREDENTIALS_DB': str(temporary / 'credentials.sqlite3')})
        from src.application.factory import create_app
        from src.utils.config_loader import load_config
        from src.service.rd_platform.runtime import get_store
        from src.service.assistant import conversation as assistant
        from src.service.rd_platform.demo import ensure_demo_workspace
        from playwright.sync_api import sync_playwright, expect
        import uvicorn
        app = create_app(replace(load_config(), logs_dir=temporary / 'logs'))
        store = get_store()
        ensure_demo_workspace(store)
        pid = store.list_projects('demo-owner')['items'][0]['id']
        detail = store.detail(pid, 'demo-owner')
        requirement = detail['requirements'][0]
        before_version = detail['project']['version']
        assistant._model_status = lambda: {'configured': True, 'model': 'integration-fixture'}
        def model(system, user):
            body = json.loads(user)
            if 'context' not in body:
                assert 'project' not in body
                return '你好，我是小航，通用对话不会携带项目数据。'
            return json.dumps({'reply': '已整理需求标题修改，请核对草案。', 'operation': {'action': 'save_requirement', 'payload': {'id': requirement['id'], 'title': '浏览器端到端需求', 'content': requirement['content']}}}, ensure_ascii=False)
        assistant._call_model = model
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='error'))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(.1)
        assert server.started
        base = f'http://127.0.0.1:{port}'
        errors = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(**browser_options())
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                page = context.new_page()
                page.set_default_timeout(15000)
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base + '/rd/' + pid, wait_until='networkidle')
                page.get_by_role('button', name='打开小航 AI 助手', exact=True).click()
                box = page.get_by_role('textbox', name='向小航发送问题', exact=True)
                box.fill('把第一条需求标题修改为浏览器端到端需求')
                box.press('Enter')
                expect(page.locator('.xiaohang-proposal')).to_be_visible()
                assert store.detail(pid, 'demo-owner')['project']['version'] == before_version
                page.locator('.xiaohang-proposal').get_by_role('button', name='确认执行').click()
                confirmation = page.get_by_role('dialog', name='确认保存需求？')
                expect(confirmation).to_be_visible()
                confirmation.get_by_role('button', name='确认执行', exact=True).click()
                expect(page.locator('.xiaohang-operation-success')).to_be_visible()
                result = store.detail(pid, 'demo-owner')
                assert result['project']['version'] == before_version + 1
                updated = next(r for r in result['requirements'] if r['id'] == requirement['id'])
                assert updated['title'] == '浏览器端到端需求'
                assert updated['source'] == requirement['source']
                assert updated['acceptance'] == requirement['acceptance']
                page.screenshot(path=str(EVIDENCE / 'confirmed-operation.png'))
                general = page.get_by_role('textbox', name='向小航发送问题', exact=True)
                general.fill('你好')
                general.press('Enter')
                expect(page.locator('.xiaohang-bubble').get_by_text('你好，我是小航，通用对话不会携带项目数据。', exact=True)).to_be_visible()
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(EVIDENCE / 'mobile-general.png'))
                assert not errors, errors
                browser.close()
            (EVIDENCE / 'proof.json').write_text(json.dumps({'passed': True, 'business_writes': 1, 'unconfirmed_writes': 0,
                'preserved_source_and_acceptance': True, 'general_project_context': False, 'page_errors': errors,
                'external_calls': 0, 'viewport': [1440, 390]}, ensure_ascii=False, indent=2), encoding='utf-8')
            print('PASS: real assistant API, preview without business writes, explicit confirmation, preserved fields, general isolation, narrow layout')
        finally:
            server.should_exit = True
            thread.join(timeout=10)


if __name__ == '__main__':
    run()
