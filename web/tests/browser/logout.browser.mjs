/** Application-scoped logout, with mocked identity/logout APIs and no OA account. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
const user = { userid: 'engineer-1024', name: '梁工程师', display_name: '梁工程师', source: 'smartvision', verified: true };
const authenticated = { auth_enabled: true, authenticated: true, user };
const local = { auth_enabled: false, authenticated: false, user: null };
const anonymous = { auth_enabled: true, authenticated: false, user: null, login_url: '/auth/login' };
const errors = [];

async function open(identity, options = {}) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => errors.push(error.message));
  const state = { calls: [], status: 200, body: { success: true }, gate: null, abort: false, precheckGate: null, prechecks: 0 };
  const rule = { id: 'test-rule', title: '测试规则', group: '生成规则', description: '', revision: 'v1', field_count: 1 };
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/current-user') return route.fulfill({ json: identity });
    if (path === '/api/system/logout') {
      state.calls.push(request.method());
      if (state.gate) await state.gate;
      if (state.abort) return route.abort('failed');
      return route.fulfill({ status: state.status, json: state.body });
    }
    if (path === '/api/rules') return route.fulfill({ json: { items: [rule], can_save: true, blocking_reason: '' } });
    if (path === '/api/rules/test-rule') return route.fulfill({ json: { ...rule, can_save: true, blocking_reason: '',
      data: { description: '原规则' }, fields: [{ path: ['description'], label: '检查说明', section: '业务规则', type: 'string' }], history: [] } });
    if (path === '/api/precheck') {
      state.prechecks += 1;
      if (state.precheckGate) await state.precheckGate;
      return route.fulfill({ status: 503, json: { error: '预检暂不可用' } });
    }
    let response = {};
    if (path === '/api/product_catalog') response = { product_types: [] };
    if (path === '/api/models') response = { success: true, models: [] };
    if (path === '/api/history' || path === '/api/local_defaults') response = [];
    if (options.generation) {
      if (path === '/api/product_catalog') response = { product_types: [{ value: 'rectangular', label: '矩形连接器', enabled: true, domains: [{ value: 'military', label: '军品' }] }] };
      if (path === '/api/models') response = { success: true, models: [{ provider: 'smartvision', model: 'test-model', id: '1', configured: true }] };
      if (path === '/api/llm/status') response = { configured: true };
      if (path === '/api/health') response = { ready_for_generation: true, llm: { configured: true }, runtime: {} };
    }
    return route.fulfill({ json: response });
  });
  await page.route('**/logged-out', route => route.fulfill({
    contentType: 'text/html; charset=utf-8',
    body: '<!doctype html><html lang="zh-CN"><head><title>已退出本应用</title></head><body><h1>已退出本应用</h1><a href="/">重新进入应用</a></body></html>',
  }));
  await page.goto(`${base}/`);
  await page.locator('#workspace-shell').waitFor({ timeout: 8000 }).catch(async reason => {
    console.error('Logout test page:', errors, await page.locator('body').innerText());
    throw reason;
  });
  await page.locator('.sidebar-user-row').getByText(identity.authenticated ? user.display_name : identity.auth_enabled ? '未登录' : '本地模式', { exact: true }).waitFor();
  return { page, state };
}

async function screenshot(page, name) {
  if (!process.env.SCREENSHOT_DIR) return;
  await mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
  await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, name), fullPage: true });
}

try {
  const signed = await open(authenticated);
  const logout = signed.page.getByRole('button', { name: '退出登录', exact: true });
  await logout.waitFor();
  await logout.focus();
  assert.equal(await logout.evaluate(button => button === document.activeElement), true, 'logout is keyboard accessible');
  await signed.page.evaluate(() => {
    localStorage.setItem('logout-test-selection', 'keep-selection');
    sessionStorage.setItem('logout-test-tab', 'keep-tab');
  });
  await screenshot(signed.page, 'logout-desktop.png');
  let release;
  signed.state.gate = new Promise(resolve => { release = resolve; });
  const logoutRequest = signed.page.waitForRequest(request => request.url().endsWith('/api/system/logout'));
  await logout.evaluate(button => { button.click(); button.click(); });
  await logoutRequest;
  assert.equal(await signed.page.getByRole('button', { name: '正在退出登录', exact: true }).isDisabled(), true);
  assert.equal(await signed.page.getByRole('dialog', { name: '正在退出登录', exact: true }).isVisible(), true);
  await signed.page.keyboard.press('Escape');
  assert.equal(await signed.page.getByRole('dialog', { name: '正在退出登录', exact: true }).isVisible(), true, 'pending logout cannot be cancelled after the server request');
  assert.equal(await signed.page.locator('#product-series').evaluate(input => {
    input.focus(); return document.activeElement === input;
  }), false, 'pending modal prevents editing behind logout');
  assert.deepEqual(signed.state.calls, ['POST'], 'duplicate clicks send one logout request');
  assert.equal(new URL(signed.page.url()).pathname, '/', 'stay on the current page until logout succeeds');
  release();
  await signed.page.waitForURL('**/logged-out');
  assert.equal(await signed.page.evaluate(() => localStorage.getItem('logout-test-selection')), 'keep-selection');
  assert.equal(await signed.page.evaluate(() => sessionStorage.getItem('logout-test-tab')), 'keep-tab');
  await signed.page.close();

  const failed = await open(authenticated);
  failed.state.status = 503;
  await failed.page.locator('#sidebar .sidebar-toggle').click();
  const collapsedLogout = failed.page.getByRole('button', { name: '退出登录', exact: true });
  assert.equal(await collapsedLogout.isVisible(), true, 'collapsed sidebar retains an accessible logout control');
  await collapsedLogout.click();
  await failed.page.getByRole('alert').filter({ hasText: '退出登录失败，请重试。' }).waitFor();
  assert.equal(await failed.page.locator('#workspace-shell.sidebar-expanded').count(), 1, 'logout error expands the sidebar so the recovery message stays readable');
  assert.equal(new URL(failed.page.url()).pathname, '/', 'failed logout does not leave the current task');
  assert.equal(await failed.page.getByRole('button', { name: '退出登录', exact: true }).isEnabled(), true);
  await screenshot(failed.page, 'logout-error-desktop.png');
  await failed.page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await failed.page.getByRole('button', { name: '退出登录', exact: true }).isVisible(), true);
  assert.equal(await failed.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await screenshot(failed.page, 'logout-error-mobile.png');
  failed.state.status = 200;
  failed.state.body = { success: false };
  await failed.page.getByRole('button', { name: '退出登录', exact: true }).click();
  await failed.page.getByRole('alert').filter({ hasText: '退出登录失败，请重试。' }).waitFor();
  assert.equal(new URL(failed.page.url()).pathname, '/', 'a failed response body is not treated as successful logout');
  failed.state.body = { success: true };
  failed.state.abort = true;
  await failed.page.getByRole('button', { name: '退出登录', exact: true }).click();
  await failed.page.getByRole('alert').filter({ hasText: '无法连接平台' }).waitFor();
  failed.state.abort = false;
  await failed.page.getByRole('button', { name: '退出登录', exact: true }).click();
  await failed.page.waitForURL('**/logged-out');
  assert.equal(failed.state.calls.length, 4, 'failed requests can be retried without a stuck busy state');
  await failed.page.close();

  const dirty = await open(authenticated);
  const nativeDialogs = [];
  dirty.page.on('dialog', async dialog => { nativeDialogs.push(dialog.type()); await dialog.dismiss(); });
  await dirty.page.locator('button[data-page="rules"]').click();
  await dirty.page.getByLabel('检查说明', { exact: true }).fill('保留这条未保存规则');
  await dirty.page.getByRole('button', { name: '退出登录', exact: true }).click();
  const confirmation = dirty.page.getByRole('dialog', { name: '退出登录前确认', exact: true });
  await confirmation.waitFor();
  assert.equal(dirty.state.calls.length, 0, 'dirty confirmation precedes the logout POST');
  await confirmation.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(dirty.state.calls.length, 0, 'cancel does not clear login cookies');
  assert.equal(await dirty.page.getByLabel('检查说明', { exact: true }).inputValue(), '保留这条未保存规则');
  assert.equal(await dirty.page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented;
  }), true, 'cancelling logout retains the dirty-page guard');
  dirty.state.status = 503;
  await dirty.page.getByRole('button', { name: '退出登录', exact: true }).click();
  await confirmation.getByRole('button', { name: '放弃修改并退出', exact: true }).click();
  await confirmation.getByRole('alert').waitFor();
  await confirmation.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(await dirty.page.getByLabel('检查说明', { exact: true }).inputValue(), '保留这条未保存规则');
  assert.equal(await dirty.page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented;
  }), true, 'a failed logout retains the dirty-page guard');
  dirty.state.status = 200;
  await dirty.page.getByRole('button', { name: '退出登录', exact: true }).click();
  await screenshot(dirty.page, 'logout-confirm-desktop.png');
  await confirmation.getByRole('button', { name: '放弃修改并退出', exact: true }).click();
  await dirty.page.waitForURL('**/logged-out');
  assert.deepEqual(nativeDialogs, [], 'confirmed logout does not show a second native confirmation after clearing cookies');
  assert.equal(dirty.state.calls.length, 2);
  await dirty.page.close();

  const precheck = await open(authenticated, { generation: true });
  await precheck.page.locator('#cover-phase').click();
  await precheck.page.getByRole('option', { name: 'S', exact: true }).click();
  await precheck.page.locator('#product-series').fill('CY');
  for (const kind of ['tech', 'spec']) await precheck.page.locator(`#f-${kind}`).setInputFiles({ name: `${kind}.docx`, mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: Buffer.from('synthetic fixture') });
  let releasePrecheck;
  precheck.state.precheckGate = new Promise(resolve => { releasePrecheck = resolve; });
  const requestPrecheck = precheck.page.waitForRequest(request => new URL(request.url()).pathname === '/api/precheck');
  await precheck.page.locator('#btn-run').click();
  await requestPrecheck;
  await precheck.page.getByRole('button', { name: '退出登录', exact: true }).click();
  await precheck.page.getByRole('alert').filter({ hasText: '资料正在预检' }).waitFor();
  assert.equal(precheck.state.calls.length, 0, 'an in-flight precheck cannot lose its session before it submits the job');
  const failedPrecheck = precheck.page.waitForResponse(response => new URL(response.url()).pathname === '/api/precheck');
  releasePrecheck();
  await (await failedPrecheck).finished();
  await precheck.page.getByRole('button', { name: '退出登录', exact: true }).click();
  await precheck.page.getByRole('dialog', { name: '退出登录前确认', exact: true }).waitFor();
  await precheck.page.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(precheck.state.calls.length, 0, 'a failed precheck restores normal dirty-page confirmation');
  await precheck.page.close();

  for (const identity of [local, anonymous]) {
    const hidden = await open(identity);
    assert.equal(await hidden.page.getByRole('button', { name: '退出登录', exact: true }).count(), 0, 'only an authenticated OA identity has logout');
    assert.deepEqual(hidden.state.calls, []);
    await hidden.page.close();
  }
  assert.deepEqual(errors, []);
  console.log('Logout browser flow passed: OA-only action, one pending POST, app-only navigation, retained storage, keyboard/mobile layout and recoverable failures.');
} finally {
  await browser.close();
}
