/** History switching uses intercepted, synthetic credentials; live settings remain untouched. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
const screenshotDir = process.env.SCREENSHOT_DIR;
if (screenshotDir) await mkdir(screenshotDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const values = {
  public: { base_url: 'https://public.example/open/', app_id: 'public-app', api_key: 'synthetic-public-secret', tenant_id: 'public-tenant' },
  internal: { base_url: 'http://internal.example/open/', app_id: 'internal-app', api_key: 'synthetic-internal-secret', tenant_id: 'internal-tenant' },
  previous: { base_url: 'https://previous.example/open/', app_id: 'previous-app', api_key: 'synthetic-previous-secret', tenant_id: 'previous-tenant' },
};
let activeId = 'public';
let entries = Object.entries(values).map(([id, item]) => ({
  id, name: { public: '测试外网', internal: '测试内网', previous: '过往配置' }[id],
  base_url: item.base_url, app_id: item.app_id, tenant_id: item.tenant_id,
  created_at: '2026-09-20T00:00:00Z', last_used_at: id === 'public' ? '2026-09-20T01:00:00Z' : null,
  source: id === 'internal' ? 'preset' : 'saved',
}));
const response = () => ({
  defaults: { model: values.public }, effective: { model: values[activeId] },
  overridden: activeId === 'public' ? [] : ['model'],
  history: entries.map(item => ({ ...item, active: item.id === activeId })),
});
let settingsReads = 0;
let modelReads = 0;
let activations = 0;
let deletions = 0;
let failActivation = true;
let failDeletion = true;
const pageErrors = [];
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => pageErrors.push(error.message));
  const healthy = await (await page.request.get(base + '/api/health')).json();
  await page.route('**/api/settings/credentials**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    assert.equal(request.headers()['x-credential-settings'], '1');
    if (path.endsWith('/activate')) {
      assert.equal(request.method(), 'POST');
      activations += 1;
      await new Promise(resolve => setTimeout(resolve, 250));
      if (failActivation) {
        failActivation = false;
        return route.fulfill({ status: 503, json: { error: '切换失败，请重试。' } });
      }
      activeId = path.split('/').at(-2);
      return route.fulfill({ json: response() });
    }
    if (request.method() === 'DELETE') {
      deletions += 1;
      if (failDeletion) {
        failDeletion = false;
        return route.fulfill({ status: 503, json: { error: '删除失败，请重试。' } });
      }
      entries = entries.filter(item => item.id !== path.split('/').at(-1));
      return route.fulfill({ json: response() });
    }
    assert.equal(request.method(), 'GET', 'this test must not save live or synthetic form edits');
    settingsReads += 1;
    return route.fulfill({ json: response() });
  });
  await page.route('**/api/models', route => {
    modelReads += 1;
    return route.fulfill({ json: { success: true, models: [{ provider: 'smartvision', model: 'qwen-test', id: '', vendor: '神州问学', configured: true }] } });
  });
  await page.route('**/api/llm/status?*', route => route.fulfill({ json: { configured: true, provider: 'smartvision', model: 'qwen-test' } }));
  await page.route('**/api/health', route => route.fulfill({ json: { ...healthy, ready_for_generation: true, llm: { configured: true } } }));
  await page.goto(base);
  const trigger = page.getByRole('button', { name: '服务凭证设置', exact: true });
  await trigger.waitFor();
  assert.equal(settingsReads, 0);
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: '服务凭证设置' });
  const picker = dialog.locator('#credentials-history-picker-native');
  const pickerTrigger = dialog.locator('#credentials-history-picker');
  const key = dialog.getByLabel('API Key', { exact: true });
  await picker.waitFor();
  await pickerTrigger.waitFor();
  assert.equal(await pickerTrigger.getAttribute('aria-haspopup'), 'listbox');
  assert.equal(await picker.evaluate(element => getComputedStyle(element).opacity), '0');
  await dialog.locator('label[for="credentials-history-picker"]').click();
  assert.equal(await pickerTrigger.evaluate(element => document.activeElement === element), true);
  assert.equal(await picker.inputValue(), 'public');
  assert.equal(await dialog.getByRole('button', { name: '当前使用', exact: true }).isDisabled(), true);
  assert.equal(await dialog.getByRole('button', { name: '删除记录', exact: true }).isDisabled(), true);
  await key.fill('synthetic-unsaved-secret');
  await dialog.getByRole('button', { name: '显示API Key' }).click();
  await pickerTrigger.click();
  const historyMenu = dialog.locator('#credentials-history-picker-menu');
  const menuBox = await historyMenu.boundingBox();
  const dialogBox = await dialog.boundingBox();
  assert.ok(menuBox && dialogBox && menuBox.y >= dialogBox.y && menuBox.y + menuBox.height <= dialogBox.y + dialogBox.height,
    'styled history menu stays in the dialog rather than being clipped by the scroll body');
  if (screenshotDir) await page.screenshot({ path: join(screenshotDir, 'history-select-menu-desktop.png') });
  await page.keyboard.press('Escape');
  assert.equal(await dialog.isVisible(), true, 'Escape closes only the menu');
  assert.equal(await pickerTrigger.getAttribute('aria-expanded'), 'false');
  assert.equal(await pickerTrigger.evaluate(element => document.activeElement === element), true);
  await pickerTrigger.click();
  await historyMenu.getByRole('option', { name: /测试内网/ }).click();
  assert.equal(await key.inputValue(), 'synthetic-unsaved-secret', 'selecting history preserves unsaved form');
  assert.equal(activations, 0);
  assert.equal(await dialog.getByLabel('服务地址（Base URL）').inputValue(), values.public.base_url);
  const use = dialog.getByRole('button', { name: '使用此凭证', exact: true });
  await use.click();
  await dialog.getByText('当前表单有未保存的修改。', { exact: false }).waitFor();
  assert.equal(activations, 0, 'dirty switch requires explicit confirmation');
  await dialog.locator('.credentials-history').getByRole('button', { name: '取消', exact: true }).click();
  await use.click();
  await dialog.getByRole('button', { name: '放弃修改并切换', exact: true }).click();
  await dialog.getByRole('alert').filter({ hasText: '切换失败' }).waitFor();
  assert.equal(await key.inputValue(), 'synthetic-unsaved-secret');
  assert.equal(activeId, 'public');
  const beforeSwitch = modelReads;
  await use.click();
  await dialog.getByRole('button', { name: '放弃修改并切换', exact: true }).click();
  assert.equal(await dialog.getByRole('button', { name: '正在切换…', exact: true }).isDisabled(), true);
  await dialog.getByRole('status').filter({ hasText: '已切换到“测试内网”' }).waitFor();
  await page.waitForFunction(() => document.querySelector('#model-picker-status')?.textContent?.includes('已就绪'));
  assert.equal(activations, 2);
  assert.ok(modelReads > beforeSwitch, 'activation refreshes actual model catalog');
  assert.equal(await key.inputValue(), values.internal.api_key);
  assert.equal(await key.getAttribute('type'), 'password', 'switch remasks sensitive input');
  assert.equal(await picker.inputValue(), 'internal');
  assert.equal(await dialog.getByRole('button', { name: '保存凭证', exact: true }).isDisabled(), true);
  assert.equal(await dialog.getByRole('button', { name: '删除记录', exact: true }).isDisabled(), true);

  await key.fill('synthetic-draft-after-switch');
  await pickerTrigger.click();
  await historyMenu.getByRole('option', { name: /过往配置/ }).click();
  const beforeDelete = modelReads;
  await dialog.getByRole('button', { name: '删除记录', exact: true }).click();
  assert.equal(deletions, 0, 'delete requires confirmation');
  await dialog.getByRole('button', { name: '确认删除', exact: true }).click();
  await dialog.getByRole('alert').filter({ hasText: '删除失败' }).waitFor();
  assert.equal(await picker.locator('option').count(), 3);
  assert.equal(await key.inputValue(), 'synthetic-draft-after-switch');
  await dialog.getByRole('button', { name: '删除记录', exact: true }).click();
  await dialog.getByRole('button', { name: '确认删除', exact: true }).click();
  await dialog.getByRole('status').filter({ hasText: '已删除“过往配置”' }).waitFor();
  assert.equal(await picker.locator('option').count(), 2);
  assert.equal(await key.inputValue(), 'synthetic-draft-after-switch', 'deletion does not overwrite unsaved form');
  assert.equal(activeId, 'internal');
  assert.equal(modelReads, beforeDelete, 'history-only deletion must not refresh models');
  assert.equal(await dialog.getByRole('button', { name: '保存凭证', exact: true }).isDisabled(), false);
  await page.keyboard.press('Escape');
  await dialog.getByRole('button', { name: '放弃修改', exact: true }).click();
  await trigger.click();
  await picker.waitFor();
  assert.equal(await picker.inputValue(), 'internal');
  assert.equal(await key.inputValue(), values.internal.api_key);
  assert.equal(await picker.locator('option').count(), 2);
  await page.setViewportSize({ width: 390, height: 844 });
  await pickerTrigger.click();
  await historyMenu.getByRole('option', { name: /测试外网/ }).waitFor();
  assert.equal(await dialog.evaluate(element => element.scrollWidth > element.clientWidth), false);
  if (screenshotDir) await page.screenshot({ path: join(screenshotDir, 'history-select-menu-mobile.png') });
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(() => [...Object.values(localStorage), ...Object.values(sessionStorage)]
    .some(item => /synthetic-.*secret|synthetic-draft/.test(item))), false);
  assert.deepEqual(pageErrors, []);
  console.log(JSON.stringify({ passed: true, historySelectionPreservesDraft: true, dirtySwitchConfirmation: true,
    switchFailureKeepsDraft: true, activationRefreshesModels: true, secretsRemasked: true,
    deleteConfirmationAndFailure: true, deletionPreservesDraftAndActiveSettings: true,
    noSecretsInBrowserStorage: true, reopenUsesServerState: true, activations, deletions }));
} finally {
  await browser.close();
}
