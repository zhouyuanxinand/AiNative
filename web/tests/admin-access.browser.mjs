/** OA identities and APIs are fixtures: this suite never creates deployed administrators. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5193';
const shotDir = process.env.SCREENSHOT_DIR;
if (shotDir) await mkdir(shotDir, { recursive: true });
const owner = { authenticated: true, user: { username: 'wangxue', display_name: '王雪', userid: 'fixture-owner' }, can_manage_admins: true };
const member = { authenticated: true, user: { username: 'zhangsan', display_name: '张三', userid: 'fixture-member' }, can_manage_admins: false };
const ownerRecord = { username: 'wangxue', created_at: '2026-10-22T02:20:00Z', created_by: 'system', is_owner: true };
const requests = [], errors = [];
let mode = 'unauth', releaseSession, holdSession = null, failedDelete = false, revokeLogs = false;
let members = [ownerRecord];

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, timezoneId: 'America/New_York' });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    requests.push({ path, method: request.method(), headers: request.headers(), body: request.postDataJSON() });
    if (path === '/api/admin/session') {
      if (holdSession) await holdSession;
      if (mode === 'unauth') return route.fulfill({ status: 401, json: { code: 'AUTH_REQUIRED', error: '请先完成 OA 登录。', login_url: '/admin/auth/login' } });
      if (mode === 'denied') return route.fulfill({ status: 403, json: { code: 'ADMIN_FORBIDDEN', username: 'removed-user', error: '当前账号不在管理员名单中。' } });
      if (mode === 'error') return route.fulfill({ status: 503, json: { error: '问学身份验证暂不可用。' } });
      return route.fulfill({ json: mode === 'member' ? member : owner });
    }
    if (path === '/api/admin/logout') {
      assert.equal(request.headers()['x-admin-action'], '1');
      mode = 'unauth'; return route.fulfill({ json: { success: true } });
    }
    if (path === '/api/admin/members') {
      if (request.method() === 'POST') {
        assert.equal(request.headers()['x-admin-action'], '1');
        const username = request.postDataJSON().username.trim().toLowerCase();
        if (members.some(item => item.username === username)) return route.fulfill({ status: 409, json: { error: '该账号已在管理员名单中。' } });
        const added = { username, created_at: '2026-10-22T03:10:00Z', created_by: 'wangxue', is_owner: false }; members.push(added);
        return route.fulfill({ status: 201, json: { member: added } });
      }
      return route.fulfill({ json: { items: members, can_manage_admins: mode !== 'member' } });
    }
    if (path.startsWith('/api/admin/members/')) {
      assert.equal(request.method(), 'DELETE'); assert.equal(request.headers()['x-admin-action'], '1');
      if (failedDelete) return route.fulfill({ status: 503, json: { error: '名单保存失败，请重试。' } });
      members = members.filter(item => item.username !== decodeURIComponent(path.split('/').at(-1)));
      return route.fulfill({ json: { success: true } });
    }
    if (path === '/api/feedback-admin') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20,
      stats: { total: 0, good: 0, average: 0, poor: 0, good_rate: 0, open: 0, in_progress: 0, resolved: 0 } } });
    if (path === '/api/logs/requests') {
      if (revokeLogs) return route.fulfill({ status: 403, json: { code: 'ADMIN_FORBIDDEN', username: 'zhangsan', error: '管理员权限已移除。' } });
      return route.fulfill({ json: { items: [], retention: 50, stats: { total: 0, running: 0, success: 0, failed: 0 } } });
    }
    return route.fulfill({ status: 404, json: { error: 'Unexpected API' } });
  });

  holdSession = new Promise(resolve => { releaseSession = resolve; });
  await page.goto(`${base}/admin?view=logs`);
  await page.getByRole('heading', { name: '正在验证管理员身份', exact: true }).waitFor();
  assert.equal(requests.filter(item => item.path !== '/api/admin/session').length, 0, 'no sensitive calls before OA/session check');
  releaseSession(); holdSession = null;
  await page.getByRole('heading', { name: '登录管理员页面', exact: true }).waitFor();
  assert.equal(await page.getByRole('link', { name: '使用 OA／问学登录', exact: true }).getAttribute('href'), '/admin/auth/login');
  assert.equal(await page.locator('input[type=password]').count(), 0, 'OA passwords never collected locally');
  assert.equal(await page.getByRole('navigation', { name: '管理员导航', exact: true }).count(), 0);
  if (shotDir) await page.screenshot({ path: join(shotDir, 'admin-login-desktop.png'), fullPage: true });
  mode = 'denied'; await page.getByRole('button', { name: '重新验证', exact: true }).click();
  await page.getByRole('heading', { name: '当前账号没有管理员权限', exact: true }).waitFor();
  await page.getByText('removed-user', { exact: true }).waitFor();
  assert.equal(requests.filter(item => item.path !== '/api/admin/session').length, 0);
  mode = 'error'; await page.getByRole('button', { name: '重新验证', exact: true }).click();
  await page.getByRole('heading', { name: '暂时无法验证管理员身份', exact: true }).waitFor();
  assert.equal(await page.getByRole('link', { name: /OA/ }).count(), 0);

  mode = 'owner'; await page.goto(`${base}/admin?view=admins`);
  const nav = page.getByRole('navigation', { name: '管理员导航', exact: true });
  const table = page.getByRole('table', { name: '管理员权限名单', exact: true });
  await table.waitFor();
  assert.equal(requests.filter(item => item.path === '/api/feedback-admin' || item.path === '/api/logs/requests').length, 0, 'direct members route does not load other panels');
  assert.equal(await nav.getByRole('link', { name: '管理员名单', exact: true }).getAttribute('aria-current'), 'page');
  await page.getByRole('button', { name: '统一登录设置', exact: true }).waitFor();
  assert.match(await table.innerText(), /10:20:00/, 'member authorization timestamps use Beijing time');
  assert.equal(await page.getByRole('button', { name: '移除管理员 wangxue', exact: true }).count(), 0);
  await page.getByLabel('OA 登录账号', { exact: true }).fill('中文姓名');
  await page.getByRole('button', { name: '添加管理员', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '不要填写中文姓名' }).waitFor();
  assert.equal(requests.filter(item => item.method === 'POST').length, 0);
  await page.getByLabel('OA 登录账号', { exact: true }).fill('wangxue');
  await page.getByRole('button', { name: '添加管理员', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '该账号已在管理员名单中' }).waitFor();
  await page.getByLabel('OA 登录账号', { exact: true }).fill(' ZhangSan ');
  await page.getByRole('button', { name: '添加管理员', exact: true }).click();
  await table.getByText('zhangsan', { exact: true }).waitFor();
  assert.equal(await page.getByLabel('OA 登录账号', { exact: true }).inputValue(), '');
  if (shotDir) await page.screenshot({ path: join(shotDir, 'admin-members-desktop.png'), fullPage: true });
  await page.getByRole('button', { name: '移除管理员 zhangsan', exact: true }).click();
  await page.getByRole('dialog', { name: '移除管理员权限', exact: true }).getByRole('button', { name: '取消', exact: true }).click();
  assert.equal(requests.filter(item => item.method === 'DELETE').length, 0);
  await page.getByRole('button', { name: '移除管理员 zhangsan', exact: true }).click(); failedDelete = true;
  await page.getByRole('button', { name: '确认移除', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '名单保存失败' }).waitFor();
  failedDelete = false; await page.getByRole('button', { name: '确认移除', exact: true }).click();
  await page.getByText('已移除 zhangsan 的管理员权限。', { exact: true }).waitFor();
  assert.equal(await table.getByText('zhangsan', { exact: true }).count(), 0);

  await page.getByLabel('OA 登录账号', { exact: true }).fill('未保存草稿');
  await nav.getByRole('link', { name: '运行日志', exact: true }).click();
  await nav.getByRole('link', { name: '管理员名单', exact: true }).click();
  assert.equal(await page.getByLabel('OA 登录账号', { exact: true }).inputValue(), '未保存草稿');
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await page.getByRole('dialog', { name: '退出管理员页面', exact: true }).getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(requests.filter(item => item.path === '/api/admin/logout').length, 0);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.getByRole('button', { name: '管理菜单', exact: false }).click();
  assert.equal(await nav.getByRole('link', { name: '管理员名单', exact: true }).isVisible(), true);
  if (shotDir) await page.screenshot({ path: join(shotDir, 'admin-members-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await page.getByRole('button', { name: '放弃修改并退出', exact: true }).click();
  await page.getByRole('heading', { name: '登录管理员页面', exact: true }).waitFor();

  mode = 'member'; await page.goto(`${base}/admin?view=admins`);
  await table.waitFor();
  assert.equal(await page.getByRole('button', { name: '统一登录设置', exact: true }).count(), 0);
  assert.equal(await page.getByRole('form', { name: '添加管理员', exact: true }).count(), 0);
  await page.getByText('当前名单只读。仅 wangxue 可以添加或移除管理员。', { exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: /移除管理员/ }).count(), 0);
  if (shotDir) await page.screenshot({ path: join(shotDir, 'admin-members-readonly-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: '管理菜单', exact: false }).click();
  await nav.getByRole('link', { name: '运行日志', exact: true }).click();
  await page.getByRole('button', { name: '刷新请求列表', exact: true }).waitFor();
  revokeLogs = true; await page.getByRole('button', { name: '刷新请求列表', exact: true }).click();
  await page.getByRole('heading', { name: '当前账号没有管理员权限', exact: true }).waitFor();
  const logCount = requests.filter(item => item.path === '/api/logs/requests').length;
  await page.waitForTimeout(5300);
  assert.equal(requests.filter(item => item.path === '/api/logs/requests').length, logCount, 'revoked session removes sensitive panels and stops polling');
  assert.equal(await page.locator('.request-logs-view').count(), 0);
  if (shotDir) await page.screenshot({ path: join(shotDir, 'admin-denied-mobile.png'), fullPage: true });

  revokeLogs = false; mode = 'owner'; await page.goto(`${base}/admin?view=admins`); await table.waitFor();
  mode = 'unauth'; await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await page.getByRole('heading', { name: '登录管理员页面', exact: true }).waitFor();
  assert.equal(await table.count(), 0, 'focus session recheck removes expired page content');
  assert.deepEqual(errors, []);
  console.log('Admin access browser passed: initial gate, OA-only login, denied/outage, owner CRUD, immutable owner, readonly admin, draft logout, responsive layout, revocation and session expiry.');
} finally { await browser.close(); }
