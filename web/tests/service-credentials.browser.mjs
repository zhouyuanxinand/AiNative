/** Browser behavior uses synthetic credentials; live platform settings are never changed. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
const screenshotDir = process.env.SCREENSHOT_DIR;
if (screenshotDir) await mkdir(screenshotDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const defaults = {
  model: { base_url: 'https://test.example/open/', app_id: 'test-app', api_key: '', tenant_id: 'test-tenant' },
};
const secret = 'synthetic-browser-secret';
const errors = [];
let saved = Object.fromEntries(Object.keys(defaults).map(key => [key, null]));
let failNextSave = false;
let failNextLoad = false;
let settingsReads = 0;
let modelReads = 0;
let saves = 0;
const receipt = {};
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  const healthy = await (await page.request.get(base + '/api/health')).json();
  await page.route('**/api/settings/credentials', async route => {
    const request = route.request();
    assert.equal(request.headers()['x-credential-settings'], '1');
    if (request.method() === 'PUT') {
      if (failNextSave) {
        failNextSave = false;
        return route.fulfill({ status: 503, json: { error: '凭证未保存，请重试。' } });
      }
      saved = request.postDataJSON();
      saves += 1;
    } else {
      settingsReads += 1;
      if (failNextLoad) {
        return route.fulfill({ status: 503, json: { error: '凭证读取失败，请重试。' } });
      }
    }
    return route.fulfill({ json: {
      defaults, effective: Object.fromEntries(Object.entries(defaults).map(([key, value]) => [key, saved[key] || value])),
      overridden: Object.keys(saved).filter(key => saved[key] !== null),
      history: [],
    } });
  });
  await page.route('**/api/models', route => {
    modelReads += 1;
    return route.fulfill({ json: { success: true, models: [{
      provider: saved.model ? 'smartvision' : 'dashscope', model: saved.model ? 'azure/gpt-5' : 'qwen-plus', id: '', vendor: saved.model ? '神州问学' : '阿里云 DashScope', configured: saved.model !== null,
    }] } });
  });
  await page.route('**/api/llm/status?*', route => route.fulfill({ json: { configured: saved.model !== null, provider: 'dashscope', model: 'qwen-plus' } }));
  await page.route('**/api/health', route => route.fulfill({ json: { ...healthy, ready_for_generation: saved.model !== null, llm: { configured: saved.model !== null } } }));
  await page.goto(base);
  const trigger = page.getByRole('button', { name: '服务凭证设置', exact: true });
  await trigger.waitFor();
  assert.equal(settingsReads, 0, 'credentials must only load on explicit open');
  assert.equal(await page.getByRole('button', { name: '查看受控生成策略与规则' }).count(), 0);
  const triggerBox = await trigger.boundingBox();
  assert.ok(triggerBox.x < 360 && triggerBox.y > 850, 'settings stays in sidebar footer');
  if (screenshotDir) await page.screenshot({ path: join(screenshotDir, 'settings-entry-desktop.png') });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: '服务凭证设置' });
  await dialog.getByRole('button', { name: '恢复本组默认' }).waitFor();
  assert.equal(await dialog.getByRole('tab').count(), 1);
  assert.equal(await dialog.getByRole('tab', { name: '模型', exact: true }).count(), 1);
  const save = dialog.getByRole('button', { name: '保存凭证', exact: true });
  assert.equal(await save.isDisabled(), true);
  const key = dialog.getByLabel('API Key', { exact: true });
  await key.fill(secret);
  assert.equal(await key.getAttribute('type'), 'password');
  await dialog.getByRole('button', { name: '显示API Key' }).click();
  assert.equal(await key.getAttribute('type'), 'text');
  await dialog.getByRole('button', { name: '隐藏API Key' }).click();
  await page.keyboard.press('Escape');
  await dialog.getByText('尚有未保存的修改，是否放弃？').waitFor();
  await dialog.getByRole('button', { name: '继续编辑' }).click();
  failNextSave = true;
  await save.click();
  await dialog.getByRole('alert').filter({ hasText: '凭证未保存' }).waitFor();
  assert.equal(await key.inputValue(), secret);
  assert.equal(saves, 0);
  const modelReadsBeforeSave = modelReads;
  await save.click();
  await dialog.getByRole('status').filter({ hasText: '已保存。' }).waitFor();
  assert.equal(saved.model.api_key, secret);
  await page.locator('#model-picker-status').filter({ hasText: '已就绪' }).waitFor({ state: 'attached' });
  assert.ok(modelReads > modelReadsBeforeSave);
  assert.equal(await key.getAttribute('type'), 'password');
  assert.equal(await save.isDisabled(), true);
  if (screenshotDir) await page.screenshot({ path: join(screenshotDir, 'settings-desktop.png') });
  assert.equal(await page.evaluate(value =>
    [...Object.values(localStorage), ...Object.values(sessionStorage)].some(item => item.includes(value)), secret), false);
  await dialog.getByRole('button', { name: '关闭凭证设置' }).click();
  await trigger.click();
  await key.waitFor();
  assert.equal(await key.inputValue(), secret);
  await dialog.getByRole('button', { name: '恢复本组默认' }).click();
  assert.equal(await key.inputValue(), '');
  await save.click();
  await dialog.getByRole('status').filter({ hasText: '已保存。' }).waitFor();
  assert.equal(saved.model, null);
  await page.locator('#model-picker-status').filter({ hasText: '调用凭据未配置' }).waitFor({ state: 'attached' });
  await dialog.getByRole('button', { name: '关闭凭证设置' }).click();
  failNextLoad = true;
  await trigger.click();
  await dialog.getByRole('button', { name: '重新加载' }).waitFor();
  failNextLoad = false;
  await dialog.getByRole('button', { name: '重新加载' }).click();
  await dialog.getByRole('button', { name: '恢复本组默认' }).waitFor();
  assert.equal(await dialog.getByRole('alert').count(), 0);
  receipt.desktop = true;
  receipt.saveFailureKeepsEdits = true;
  receipt.persistAndRestore = true;
  receipt.catalogAndReadinessRefresh = true;
  receipt.noCredentialsInBrowserStorage = true;
  receipt.loadRetry = true;

  await page.setViewportSize({ width: 390, height: 844 });
  const bounds = await dialog.boundingBox();
  assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390);
  assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= 844);
  assert.equal(await dialog.evaluate(element => element.scrollWidth > element.clientWidth), false);
  assert.equal(await dialog.getByRole('button', { name: '关闭', exact: true }).isVisible(), true);
  await dialog.getByRole('button', { name: '关闭', exact: true }).focus();
  for (let index = 0; index < 12; index++) {
    await page.keyboard.press('Tab');
    assert.equal(await dialog.evaluate(element => element.contains(document.activeElement)), true, 'focus stays inside modal');
  }
  if (screenshotDir) await page.screenshot({ path: join(screenshotDir, 'settings-mobile.png') });
  await page.keyboard.press('Escape');
  await dialog.waitFor({ state: 'detached' });
  assert.equal(await trigger.evaluate(element => document.activeElement === element), true);
  receipt.mobile = true;
  receipt.keyboardAndFocus = true;
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ ...receipt, saves, passed: true }));
} finally {
  await browser.close();
}
