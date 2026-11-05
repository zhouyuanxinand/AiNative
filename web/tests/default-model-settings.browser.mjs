/** Settings behavior uses synthetic responses; no live settings or model requests are written. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const credentials = { model: { base_url: 'https://models.example.invalid/open/', app_id: 'demo-app', tenant_id: 'demo-tenant', api_key: 'synthetic-key' } };
const models = ['5505', '5506'].map(id => ({ provider: 'smartvision', model: 'azure/gpt-5.4', id, vendor: 'Azure', configured: true }));
let current = { selection: { provider: 'smartvision', name: 'old-model', id: '' }, source: 'deployment', requires_selection: true };
let catalogReads = 0, failCatalog = false, failSave = true, failRead = false;
const writes = [], errors = [];
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/settings/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    assert.equal(request.headers()['x-credential-settings'], '1');
    if (path === '/api/settings/credentials/default-model') {
      if (request.method() === 'PUT') {
        writes.push(request.postDataJSON());
        if (failSave) { failSave = false; return route.fulfill({ status: 503, json: { error: '测试默认模型未保存，请重试。' } }); }
        current = { selection: request.postDataJSON(), source: 'settings', requires_selection: false };
      } else if (failRead) return route.fulfill({ status: 503, json: { error: '测试默认模型暂不可读。' } });
      return route.fulfill({ json: current });
    }
    if (path === '/api/settings/credentials') return route.fulfill({ json: { defaults: credentials, effective: credentials, overridden: ['model'], history: [] } });
    if (path === '/api/settings/auth') return route.fulfill({ json: {
      settings: { enabled: false, app_id: 9192, platform_base_url: 'https://login.example.invalid', public_url: null },
      active: { enabled: false }, can_edit: false, version: 1, requires_restart: false,
    } });
    return route.fulfill({ status: 503, json: { error: '未提供的测试设置操作' } });
  });
  await page.route('**/api/models', route => {
    catalogReads += 1;
    return route.fulfill({ json: failCatalog ? { success: false, error: '测试目录不可用' } : { success: true, models } });
  });
  await page.goto(`${base}/?rd_view=system`);
  const trigger = page.getByRole('button', { name: '服务凭证设置', exact: true });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: '服务凭证设置', exact: true });
  const card = dialog.getByRole('region', { name: '平台默认模型', exact: true });
  await card.getByText('待确认', { exact: true }).waitFor();
  assert.equal(catalogReads, 0, 'opening settings does not contact the model directory');
  assert.equal(await dialog.getByRole('button', { name: '保存凭证', exact: true }).isDisabled(), true);
  await card.getByRole('button', { name: '选择默认模型', exact: true }).click();
  const picker = card.getByRole('combobox', { name: '选择默认模型', exact: true });
  await picker.waitFor();
  const confirm = card.getByRole('button', { name: '确认默认模型', exact: true });
  assert.equal(await confirm.isDisabled(), true, 'directory never silently selects its first model');
  await picker.click();
  await dialog.getByRole('option', { name: 'Azure · azure/gpt-5.4 · ID 5505', exact: true }).click();
  await page.keyboard.press('Escape');
  await dialog.getByText('尚有未保存的修改，是否放弃？').waitFor();
  await dialog.getByRole('button', { name: '继续编辑', exact: true }).click();
  await confirm.click();
  await card.getByRole('alert').filter({ hasText: '测试默认模型未保存' }).waitFor();
  assert.equal(await confirm.isDisabled(), false, 'failed save retains the selected model for retry');
  await confirm.click();
  await card.getByRole('status').filter({ hasText: '默认模型已确认' }).waitFor();
  assert.deepEqual(writes, Array(2).fill({ provider: 'smartvision', name: 'azure/gpt-5.4', id: '5505' }));
  await card.getByText('已生效', { exact: true }).waitFor();
  if (output) await page.screenshot({ path: join(output, 'default-model-desktop.png') });
  await dialog.getByRole('button', { name: '关闭凭证设置', exact: true }).click();
  await trigger.click();
  await card.getByText('azure/gpt-5.4', { exact: true }).waitFor();
  await dialog.getByLabel('API Key', { exact: true }).fill('synthetic-draft-key');
  assert.equal(await card.getByRole('button', { name: '更改默认模型', exact: true }).isDisabled(), true);
  await card.getByText('请先保存下方凭证，再选择此环境的默认模型。', { exact: true }).waitFor();
  await dialog.getByRole('button', { name: '关闭凭证设置', exact: true }).click();
  await dialog.getByRole('button', { name: '放弃修改', exact: true }).click();
  await trigger.click();
  await card.getByRole('button', { name: '更改默认模型', exact: true }).waitFor();
  failCatalog = true;
  await card.getByRole('button', { name: '更改默认模型', exact: true }).click();
  await card.getByRole('alert').filter({ hasText: '测试目录不可用' }).waitFor();
  await card.getByText('azure/gpt-5.4', { exact: true }).waitFor();
  failCatalog = false;
  await card.getByRole('button', { name: '更改默认模型', exact: true }).click();
  await picker.waitFor();
  assert.equal(await confirm.isDisabled(), true, 'unchanged saved choice has no duplicate write');
  await picker.focus(); await page.keyboard.press('ArrowDown');
  await dialog.getByRole('option', { name: 'Azure · azure/gpt-5.4 · ID 5506', exact: true }).click();
  assert.equal(await confirm.isDisabled(), false);
  await card.getByRole('button', { name: '取消选择', exact: true }).click();
  await card.getByRole('button', { name: '更改默认模型', exact: true }).click();
  await picker.waitFor();
  assert.equal(await confirm.isDisabled(), true, 'cancelled draft does not reappear when editing again');
  assert.match(await card.locator('.ant-select-selection-item').innerText(), /5505/);
  await card.getByRole('button', { name: '取消选择', exact: true }).click();

  for (const viewport of [{ width: 1024, height: 768 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await dialog.locator('.credentials-body').evaluate(element => { element.scrollTop = 0; });
    const bounds = await dialog.boundingBox();
    assert(bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= viewport.width + 1 && bounds.y + bounds.height <= viewport.height + 1);
    assert(await dialog.locator('.credentials-body').evaluate(element => element.scrollWidth <= element.clientWidth + 1));
    const footer = await dialog.locator('.credentials-footer').boundingBox();
    assert(footer.y + footer.height <= viewport.height, 'footer stays reachable');
    if (output) await page.screenshot({ path: join(output, `default-model-${viewport.width}.png`) });
  }
  await dialog.getByRole('button', { name: '统一登录设置', exact: true }).click();
  const auth = page.getByRole('dialog', { name: '统一登录设置', exact: true });
  await auth.getByLabel('登录应用 ID', { exact: true }).waitFor();
  assert.equal(await auth.getByRole('button', { name: '保存登录配置', exact: true }).isDisabled(), true);
  assert(await auth.locator('.credentials-body').evaluate(element => element.scrollWidth <= element.clientWidth + 1));
  if (output) await page.screenshot({ path: join(output, 'auth-settings-mobile.png') });
  await page.keyboard.press('Escape');
  await auth.waitFor({ state: 'detached' });
  await card.getByText('azure/gpt-5.4', { exact: true }).waitFor();
  await dialog.getByRole('button', { name: '关闭凭证设置', exact: true }).click();
  failRead = true;
  await trigger.click();
  await card.getByRole('button', { name: '重新读取默认模型', exact: true }).waitFor();
  failRead = false;
  await card.getByRole('button', { name: '重新读取默认模型', exact: true }).click();
  await card.getByText('已生效', { exact: true }).waitFor();
  assert.equal(writes.length, 2, 'checking layouts and login settings never writes a model');
  assert.deepEqual(errors, []);
  console.log('PASS default model: explicit catalog choice, complete identity, retries, persisted display, draft protection, credential isolation, desktop/mobile, nested read-only login settings.');
} finally { await browser.close(); }
