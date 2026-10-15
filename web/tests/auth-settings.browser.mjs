/** Unified-login configuration is mocked; these tests never change deployed login settings. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5191';
const initial = { enabled: false, app_id: 9192, platform_base_url: 'https://sv.dcsmartvision.com', public_url: null };
const modelDefaults = { model: { base_url: 'https://models.example/open/', app_id: 'model-app-id', api_key: 'synthetic-model-key', tenant_id: 'model-tenant' } };
const pageErrors = [];

async function open({ admin = false, editable = true, active = initial, settings = initial } = {}) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(7000);
  page.on('pageerror', error => pageErrors.push(error.message));
  const state = { settings: structuredClone(settings), active, can_edit: editable, version: 1, requires_restart: false,
    reads: 0, writes: [], fail: 0, modelWrites: [], modelReads: 0, gate: null };
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/settings/auth') {
      assert.equal(request.headers()['x-credential-settings'], '1');
      if (request.method() === 'PUT') {
        const fields = request.postDataJSON(); state.writes.push(fields);
        if (state.gate) await state.gate;
        if (state.fail) return route.fulfill({ status: state.fail, json: { error: state.fail === 409 ? '登录配置已被其他人修改，请读取最新配置。' : '登录配置暂未保存，请重试。' } });
        const { expected_version, ...saved } = fields;
        assert.equal(expected_version, state.version);
        state.settings = saved; state.version += 1; state.requires_restart = true;
      } else state.reads += 1;
      return route.fulfill({ json: { settings: state.settings, active: state.active, can_edit: state.can_edit,
        version: state.version, requires_restart: state.requires_restart } });
    }
    if (path === '/api/settings/credentials') {
      if (request.method() === 'PUT') state.modelWrites.push(request.postDataJSON());
      return route.fulfill({ json: { defaults: modelDefaults, effective: modelDefaults, overridden: [], history: [] } });
    }
    if (path === '/api/models') { state.modelReads += 1; return route.fulfill({ json: { success: true, models: [] } }); }
    if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
    if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [] } });
    if (path === '/api/history' || path === '/api/local_defaults') return route.fulfill({ json: [] });
    if (path === '/api/feedback-admin') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20,
      stats: { total: 0, good: 0, average: 0, poor: 0, good_rate: 0, open: 0, in_progress: 0, resolved: 0 } } });
    return route.fulfill({ json: {} });
  });
  await page.goto(`${base}/${admin ? 'feedback' : ''}`);
  if (!admin) {
    await page.getByRole('button', { name: '服务凭证设置', exact: true }).click();
    await page.getByRole('dialog', { name: '服务凭证设置', exact: true }).getByLabel('API Key', { exact: true }).fill('synthetic-model-unsaved-draft');
  }
  await page.getByRole('button', { name: '统一登录设置', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '统一登录设置', exact: true });
  await dialog.getByLabel('登录应用 ID', { exact: true }).waitFor();
  return { page, dialog, state };
}

try {
  const local = await open();
  const { page, dialog, state } = local;
  assert.equal(await dialog.getByLabel('登录应用 ID', { exact: true }).inputValue(), '9192');
  assert.equal(await dialog.getByLabel('回跳地址', { exact: true }).inputValue(), '');
  assert.equal(await dialog.getByLabel('启用统一登录', { exact: true }).isChecked(), false);
  assert.match(await dialog.innerText(), /本地.*直接使用/);
  if (process.env.SCREENSHOT_DIR) {
    await mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'auth-settings-local-desktop.png') });
  }
  await dialog.getByLabel('神州问学地址', { exact: true }).fill('http://smartvision.internal:8080');
  const initialModelReads = state.modelReads;
  await dialog.getByRole('button', { name: '保存登录配置', exact: true }).click();
  await dialog.getByText('已保存，重启平台后生效', { exact: true }).waitFor();
  assert.equal(state.writes[0].public_url, null, 'local configuration accepts an empty callback origin');
  assert.equal(state.writes[0].enabled, false);
  assert.equal(state.modelWrites.length, 0, 'auth save never submits model credentials');
  assert.equal(state.modelReads, initialModelReads, 'auth save never refreshes the model catalog');
  assert.match(await dialog.innerText(), /当前生效：本地模式/);

  await dialog.getByLabel('启用统一登录', { exact: true }).check();
  await dialog.getByRole('button', { name: '保存登录配置', exact: true }).click();
  await dialog.getByRole('alert').filter({ hasText: '启用统一登录时，请填写回跳地址' }).waitFor();
  assert.equal(state.writes.length, 1, 'enabled login cannot save without a callback');
  assert.equal(await dialog.getByLabel('回跳地址', { exact: true }).evaluate(input => document.activeElement === input), true);
  for (const invalid of ['https://tasks.example/path', 'https://tasks.example?token=secret', 'https://name:secret@tasks.example', 'https://tasks.example#token']) {
    await dialog.getByLabel('回跳地址', { exact: true }).fill(invalid);
    await dialog.getByRole('button', { name: '保存登录配置', exact: true }).click();
    await dialog.getByRole('alert').waitFor();
    assert.equal(state.writes.length, 1, 'callback paths and credentials are rejected before a request');
  }
  await dialog.getByLabel('回跳地址', { exact: true }).fill('https://tasks.example:18130');
  await dialog.getByRole('button', { name: '保存登录配置', exact: true }).click();
  await dialog.getByText('已保存，重启平台后生效', { exact: true }).waitFor();
  assert.equal(state.writes[1].expected_version, 2);
  assert.deepEqual(Object.keys(state.writes[1]).sort(), ['app_id', 'enabled', 'expected_version', 'platform_base_url', 'public_url']);
  assert.equal(state.writes[1].public_url, 'https://tasks.example:18130');

  await dialog.getByLabel('回跳地址', { exact: true }).fill('https://draft.example:18130');
  state.fail = 503;
  await dialog.getByRole('button', { name: '保存登录配置', exact: true }).click();
  await dialog.getByRole('alert').filter({ hasText: '暂未保存' }).waitFor();
  assert.equal(await dialog.getByLabel('回跳地址', { exact: true }).inputValue(), 'https://draft.example:18130');
  state.fail = 409;
  await dialog.getByRole('button', { name: '保存登录配置', exact: true }).click();
  await dialog.getByRole('button', { name: '读取最新配置', exact: true }).click();
  await dialog.getByText('读取最新配置会放弃当前未保存的修改。', { exact: true }).waitFor();
  const readsBeforeConfirm = state.reads;
  await dialog.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(state.reads, readsBeforeConfirm, 'conflict reload needs explicit discard confirmation');
  assert.equal(await dialog.getByLabel('回跳地址', { exact: true }).inputValue(), 'https://draft.example:18130');
  state.settings = { ...state.settings, public_url: 'https://server.example:18130' }; state.version = 10; state.fail = 0;
  await dialog.getByRole('button', { name: '读取最新配置', exact: true }).click();
  await dialog.getByRole('button', { name: '放弃修改并读取', exact: true }).click();
  await page.waitForFunction(expected => Array.from(document.querySelectorAll('.auth-settings-dialog input')).some(input => input.value === expected), 'https://server.example:18130');
  assert.equal(await dialog.getByLabel('回跳地址', { exact: true }).inputValue(), 'https://server.example:18130');

  await dialog.getByLabel('回跳地址', { exact: true }).fill('https://unsaved.example');
  await page.keyboard.press('Escape');
  await dialog.getByText('尚有未保存的统一登录配置，是否放弃？', { exact: true }).waitFor();
  await dialog.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(await dialog.getByLabel('回跳地址', { exact: true }).inputValue(), 'https://unsaved.example');
  await page.keyboard.press('Escape');
  await dialog.getByRole('button', { name: '放弃修改', exact: true }).click();
  const modelDialog = page.getByRole('dialog', { name: '服务凭证设置', exact: true });
  assert.equal(await modelDialog.getByLabel('API Key', { exact: true }).inputValue(), 'synthetic-model-unsaved-draft', 'auth dialog preserves the parent model draft');
  assert.equal(await modelDialog.locator('form form').count(), 0, 'settings forms are never nested');
  await page.close();

  const readonly = await open({ editable: false, active: { ...initial, enabled: true, public_url: 'https://live.example' },
    settings: { ...initial, enabled: true, public_url: 'https://live.example' } });
  assert.equal(await readonly.dialog.getByLabel('启用统一登录', { exact: true }).isDisabled(), true);
  assert.equal(await readonly.dialog.getByLabel('回跳地址', { exact: true }).isEditable(), false);
  assert.match(await readonly.dialog.innerText(), /请通过反馈管理端口维护/);
  assert.equal(await readonly.dialog.getByRole('button', { name: '保存登录配置', exact: true }).isDisabled(), true);
  await readonly.page.close();

  const admin = await open({ admin: true, active: null });
  assert.equal(await admin.dialog.getByLabel('回跳地址', { exact: true }).isEditable(), true, 'private management entry can maintain login settings');
  await admin.dialog.getByLabel('回跳地址', { exact: true }).fill('http://localhost:18130');
  let releaseSave;
  admin.state.gate = new Promise(resolve => { releaseSave = resolve; });
  await admin.dialog.getByRole('button', { name: '保存登录配置', exact: true }).click();
  await admin.dialog.getByRole('button', { name: '正在保存…', exact: true }).waitFor();
  assert.equal(await admin.dialog.getByRole('button', { name: '关闭统一登录设置', exact: true }).isDisabled(), true);
  await admin.page.keyboard.press('Escape');
  assert.equal(await admin.dialog.isVisible(), true, 'pending saves block closing');
  releaseSave();
  await admin.dialog.getByText('已保存，重启平台后生效', { exact: true }).waitFor();
  await admin.page.setViewportSize({ width: 390, height: 844 });
  await admin.dialog.getByLabel('回跳地址', { exact: true }).focus();
  await admin.dialog.getByLabel('回跳地址', { exact: true }).scrollIntoViewIfNeeded();
  const callbackBox = await admin.dialog.getByLabel('回跳地址', { exact: true }).boundingBox();
  const footerBox = await admin.dialog.locator('.credentials-footer').boundingBox();
  assert.ok(callbackBox.y + callbackBox.height <= footerBox.y + 1, 'callback input can scroll fully above the fixed footer (within CSS pixel rounding)');
  assert.equal(await admin.dialog.evaluate(element => element.scrollWidth > element.clientWidth), false, 'narrow settings dialog does not overflow');
  assert.equal(await admin.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  if (process.env.SCREENSHOT_DIR) {
    await mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
    await admin.page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'auth-settings-mobile.png') });
  }
  await admin.page.close();
  assert.deepEqual(pageErrors, []);
  console.log('Auth settings browser passed: local empty URL, enable validation, origin checks, independent saves, failures/conflicts, readonly active login, private administration, dirty close, pending close and mobile.');
} finally { await browser.close(); }
