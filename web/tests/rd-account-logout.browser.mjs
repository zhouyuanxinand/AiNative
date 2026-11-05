/** Current account dock and shared logout guard, with isolated identity/logout APIs. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = '../runtime/rd-account-logout';
await mkdir(output, { recursive: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.setDefaultTimeout(10000);
let identity = { auth_enabled: false, authenticated: false, user: null };
let requests = 0, status = 200, release;
let gate = Promise.resolve();
const errors = [], unexpected = [], dialogs = [];
page.on('pageerror', error => errors.push(error.message));
page.on('dialog', async dialog => { dialogs.push(dialog.type()); await dialog.dismiss(); });
await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname;
  if (!path.startsWith('/api/')) return route.continue();
  if (path === '/api/current-user') return route.fulfill({ json: identity });
  if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'logout-fixture', local_mode: true } });
  if (path === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [], actions: [], workpackage_definitions: [] } });
  if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [] } });
  if (path === '/api/rd/assistant/weather') return route.fulfill({ status: 503, json: { error: 'Weather disabled in logout fixture' } });
  if (path === '/api/system/logout' && route.request().method() === 'POST') {
    requests++; await gate;
    return route.fulfill({ status, json: { success: status === 200 } });
  }
  unexpected.push(path); return route.fulfill({ status: 500 });
});
await page.route('**/logged-out', route => route.fulfill({ contentType: 'text/html', body: '<h1>已退出本应用</h1><a href="/">重新进入应用</a>' }));
const open = async () => { await page.goto(base + '/tests/fixtures/rd-account.html'); await page.getByText('本地模式', { exact: true }).waitFor(); };
const exit = () => page.getByRole('button', { name: '退出应用', exact: true });
try {
  await open();
  assert.equal(await exit().count(), 1, 'local mode exposes its exit action');
  const bounds = await exit().boundingBox(), settings = await page.getByRole('button', { name: '系统管理', exact: true }).boundingBox();
  assert(bounds.x + bounds.width <= settings.x && settings.x - bounds.x - bounds.width < 10, 'exit is immediately beside settings');
  await page.evaluate(() => localStorage.setItem('logout-preservation', 'retained'));
  gate = new Promise(resolve => { release = resolve; });
  await exit().focus(); await page.keyboard.press('Enter');
  await page.getByRole('dialog', { name: '正在退出应用' }).waitFor();
  await page.keyboard.press('Escape');
  assert.equal(requests, 1); assert(await page.getByRole('dialog', { name: '正在退出应用' }).isVisible());
  release(); gate = Promise.resolve();
  await page.waitForURL('**/logged-out');
  assert.equal(await page.evaluate(() => localStorage.getItem('logout-preservation')), 'retained');
  assert.deepEqual(dialogs, []);

  await open(); await page.getByRole('textbox', { name: '未保存内容' }).fill('需要保留的草稿');
  await exit().click(); await page.getByRole('dialog', { name: '退出应用前确认' }).waitFor();
  await page.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(requests, 1); assert.equal(await page.getByRole('textbox').inputValue(), '需要保留的草稿');
  status = 503; await exit().click(); await page.getByRole('button', { name: '放弃修改并退出' }).click();
  await page.getByRole('alert').filter({ hasText: '退出应用失败' }).waitFor();
  assert.equal(requests, 2); assert.equal(await page.getByRole('textbox').inputValue(), '需要保留的草稿');
  assert(await page.evaluate(() => { const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented; }));
  status = 200; await page.getByRole('button', { name: '放弃修改并退出' }).click();
  await page.waitForURL('**/logged-out'); assert.equal(requests, 3); assert.deepEqual(dialogs, []);

  await open(); await page.getByRole('checkbox', { name: '模拟操作处理中' }).check();
  await page.getByRole('button', { name: '切换侧栏' }).click();
  await exit().click(); await page.getByRole('alert').filter({ hasText: '操作尚未完成' }).waitFor();
  assert.equal(requests, 3); assert.equal(await page.locator('.is-sidebar-collapsed').count(), 0);
  await page.getByRole('checkbox').uncheck();
  await page.setViewportSize({ width: 390, height: 844 });
  for (const button of [exit(), page.getByRole('button', { name: '系统管理', exact: true })]) {
    const rect = await button.boundingBox(); assert(rect.x >= 0 && rect.x + rect.width <= 390);
  }

  identity = { auth_enabled: true, authenticated: true, user: { userid: 'test-user', name: '工程师', display_name: '工程师', source: 'smartvision', verified: true } };
  await page.reload(); await page.getByRole('button', { name: '退出登录', exact: true }).waitFor();
  assert.equal(await exit().count(), 0);
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await page.waitForURL('**/logged-out'); assert.equal(requests, 4);
  identity = { auth_enabled: true, authenticated: false, user: null, login_url: '/auth/login' };
  await page.goto(base + '/tests/fixtures/rd-account.html'); await page.getByText('未登录', { exact: true }).waitFor();
  assert.equal(await page.locator('[data-application-logout]').count(), 0);
  identity = { auth_enabled: false, authenticated: false, user: null };
  await page.goto(base + '/rd'); await exit().waitFor();
  assert.equal(await page.locator('.rd-platform-heading strong').innerText(), 'AI Native研发管理平台');
  assert((await page.title()).endsWith(' · AI Native研发管理平台'));
  await page.screenshot({ path: output + '/local-mobile.png' });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('separator', { name: '调整侧栏宽度' }).waitFor();
  assert(await exit().evaluate(element => {
    const rect = element.getBoundingClientRect(), rail = element.closest('.rd-sidebar').getBoundingClientRect();
    return rect.x >= rail.x && rect.right <= rail.right && rect.bottom <= innerHeight;
  }));
  await page.screenshot({ path: output + '/local-desktop.png' });
  await exit().click(); await page.waitForURL('**/logged-out'); assert.equal(requests, 5);
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
  console.log('PASS rd account: local/OA exit, settings alignment, pending lock, draft cancel/failure/retry, busy guard, storage retention, collapsed/mobile controls, anonymous state');
} finally { release?.(); await browser.close(); }
