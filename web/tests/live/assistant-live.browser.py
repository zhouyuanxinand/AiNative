"""Manual live acceptance: minimal real model question, masked settings and logout.

Uses its own browser context. Does not change credentials or production projects.
"""
import asyncio
import json
from pathlib import Path
import sys

from playwright.async_api import async_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
from browser_support import ROOT, BASE, browser_options
EVIDENCE = ROOT / 'basic-service/app/runtime/xiaohang-live'


async def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    proof = {}
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(**browser_options())
        context = await browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = await context.new_page()
        page.set_default_timeout(90000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(BASE + '/', wait_until='networkidle')
        account = page.locator('.platform-account')
        await expect(account.get_by_role('button', name='退出登录', exact=True)).to_be_visible()
        await expect(account.get_by_role('button', name='服务凭证设置', exact=True)).to_be_visible()
        await account.get_by_role('button', name='服务凭证设置', exact=True).click()
        settings = page.locator('dialog.credentials-dialog')
        await expect(settings).to_be_visible()
        await expect(settings.locator('input[type=password]').first).to_be_visible()
        proof['settings'] = 'opens existing component; secrets masked; no settings saved'
        await settings.get_by_role('button', name='关闭凭证设置', exact=True).click()
        await page.get_by_role('button', name='打开小航 AI 助手', exact=True).click()
        assert await page.get_by_role('button', name='通用助手', exact=True).count() == 0
        assert await page.get_by_role('button', name='平台助手', exact=True).count() == 0
        box = page.get_by_role('textbox', name='向小航发送问题', exact=True)
        await box.fill('你好，请只用一句话介绍你自己。')
        async with page.expect_response(lambda response: response.url.endswith('/api/assistant/chat') and response.request.method == 'POST') as response_info:
            await box.press('Enter')
        response = await response_info.value
        assert response.status == 200, response.status
        answer = await response.json()
        assert answer['source'] == 'model' and answer['model'] == 'qwen-plus' and answer['reply'].strip()
        assert answer.get('proposal') is None
        assert response.request.post_data_json['mode'] == 'auto'
        await expect(page.locator('.xiaohang-bubble').get_by_text(answer['reply'], exact=True)).to_be_visible()
        proof['general'] = {'source': answer['source'], 'model': answer['model'], 'replied': True, 'project_context_sent': False}
        platform = page.get_by_role('textbox', name='向小航发送问题', exact=True)
        await platform.fill('研发管理平台的定位是什么？请简短说明。')
        async with page.expect_response(lambda response: response.url.endswith('/api/assistant/chat') and response.request.method == 'POST') as response_info:
            await platform.press('Enter')
        response = await response_info.value
        assert response.status == 200
        answer = await response.json()
        assert answer['source'] == 'model' and answer['model'] == 'qwen-plus'
        assert answer.get('proposal') is None
        proof['platform'] = {'source': answer['source'], 'model': answer['model'], 'replied': True, 'operations_executed': 0}
        await expect(page.locator('.xiaohang-bubble').get_by_text(answer['reply'], exact=True)).to_be_visible()
        await page.screenshot(path=str(EVIDENCE / 'desktop-live.png'))
        await page.get_by_role('button', name='收起小航对话', exact=True).click()
        await account.get_by_role('button', name='退出登录', exact=True).click()
        await page.wait_for_url('**/logged-out')
        identity = await (await context.request.get(BASE + '/api/current-user')).json()
        assert identity['authenticated'] is False
        assert (await context.request.get(BASE + '/api/rd/workspace')).status == 401
        await page.reload(wait_until='networkidle')
        assert (await (await context.request.get(BASE + '/api/current-user')).json())['authenticated'] is False
        await page.locator('a[href="/auth/login"]').click()
        await page.wait_for_url(BASE + '/')
        assert (await (await context.request.get(BASE + '/api/current-user')).json())['authenticated'] is True
        proof['logout'] = 'ends session, APIs deny, reload stays logged out, explicit reentry restores session'
        assert not errors, errors
        proof['page_errors'] = errors
        await browser.close()
    (EVIDENCE / 'proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
