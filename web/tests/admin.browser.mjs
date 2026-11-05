/** Local browser integration; API fixtures never change deployed feedback or login settings. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5192';
const errors = [];
const record = { id: 1, version: 1, created_at: '2026-10-22T01:20:00Z', updated_at: '2026-10-22T01:20:00Z',
  username: '工程测试用户', rating: 'average', comment: '请复核环境适应性描述。', status: 'open', handling_note: '',
  identity: { userid: 'test-user', name: '工程测试用户', source: 'smartvision', verified: true },
  snapshot: { jid: 'test-task-01', job_status: 'done', parameters: { product_type_label: '矩形低频连接器', product_series: 'CY', model_name: '工程模型' },
    files: { tech: '需求文件.docx', spec: '产品规范.docx', output: '研制任务书.docx' }, delivery_status: 'delivered', qa_ok: true, error: '' } };
const snapshot = { entries: [{ timestamp: '2026-10-22T01:20:00Z', level: 'ERROR', logger: 'taskbook.workflow',
  message: '演示任务需要人工核查', job_id: 'test-task-01', stage: 'quality_gate', error_type: 'ExampleError',
  exception: 'ExampleError: demonstration only' }], returned: 1, limit: 200, source: 'logs/app.log', updated_at: '2026-10-22T01:20:01Z', truncated: false };

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, timezoneId: 'America/New_York' });
  page.setDefaultTimeout(8000);
  page.setDefaultNavigationTimeout(30000);
  page.on('pageerror', error => errors.push(error.message));
  // Older intranet Chrome versions lack this property. Keep all navigation
  // checks in that environment so URL parameters cannot silently disappear.
  await page.addInitScript(() => { delete URLSearchParams.prototype.size; });
  const requests = [];
  let logsMode = 'ready';
  let listMode = 'ready';
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/') && !url.pathname.startsWith('/admin/api/')) return route.continue();
    requests.push({ path: url.pathname, url: url.href, headers: request.headers() });
    if (url.pathname === '/api/admin/session') return route.fulfill({ json: { authenticated: true, user: { username: 'wangxue', display_name: '测试管理员', userid: 'owner-test' }, can_manage_admins: true } });
    if (url.pathname === '/api/admin/members') return route.fulfill({ json: { items: [
      { username: 'wangxue', is_owner: true, created_at: '2026-10-22T01:20:00Z', created_by: 'system' },
    ], can_manage_admins: true } });
    if (url.pathname === '/admin/api/help-resources') return route.fulfill({ json: { items: [] } });
    if (url.pathname === '/api/logs/latest') {
      if (logsMode === 'error') return route.fulfill({ status: 503, json: { error: '日志源暂不可用' } });
      return route.fulfill({ json: logsMode === 'empty' ? { ...snapshot, entries: [], returned: 0 } : snapshot });
    }
    if (url.pathname === '/api/feedback-admin/1') return route.fulfill({ json: { record } });
    if (url.pathname === '/api/feedback-admin') {
      if (listMode === 'error') return route.fulfill({ status: 503, json: { error: '反馈服务暂不可用' } });
      const items = listMode === 'empty' ? [] : [record];
      return route.fulfill({ json: { items, total: items.length, page: 1, page_size: 20,
        stats: { total: items.length, good: 0, average: items.length, poor: 0, good_rate: 0, open: items.length, in_progress: 0, resolved: 0 } } });
    }
    if (url.pathname === '/admin/api/settings/auth') return route.fulfill({ json: { settings: { enabled: false, app_id: 9086, platform_base_url: 'https://sv.dcsmartvision.com', public_url: null },
      active: { enabled: false, app_id: 9086, platform_base_url: 'https://sv.dcsmartvision.com', public_url: null }, can_edit: true, version: 1, requires_restart: false } });
    return route.fulfill({ status: 404, json: { error: 'Unexpected API' } });
  });
  const nav = page.getByRole('navigation', { name: '管理员导航', exact: true });
  await page.goto(`${base}/admin?q=CY&log_source=service`);
  await page.getByRole('table', { name: '生成效果反馈列表' }).waitFor();
  assert.equal(await page.evaluate(() => 'size' in URLSearchParams.prototype), false);
  assert.equal(await nav.getByRole('link', { name: '用户反馈', exact: true }).getAttribute('aria-current'), 'page');
  assert.equal(requests.filter(item => item.path === '/api/current-user').length, 0);
  assert.equal(requests.filter(item => item.path === '/api/logs/latest').length, 0, 'inactive logs never start polling');
  const sidebar = await page.getByRole('complementary', { name: '管理员侧边栏' }).boundingBox();
  const content = await page.locator('.admin-main').boundingBox();
  assert.ok(sidebar.x + sidebar.width <= content.x, 'desktop uses a left sidebar');
  await page.getByLabel('关键词', { exact: true }).fill('尚未查询的草稿');
  await nav.getByRole('link', { name: '运行日志', exact: true }).click();
  await page.getByText('演示任务需要人工核查', { exact: true }).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('q'), 'CY');
  assert.equal(new URL(page.url()).searchParams.get('view'), 'logs');
  assert.equal(requests.find(item => item.path === '/api/logs/latest').headers['x-log-viewer'], '1');
  assert.match(await page.locator('.runtime-log-row time').innerText(), /09:20:00/, 'logs show Beijing time regardless of browser time zone');
  if (process.env.SCREENSHOT_DIR) { await mkdir(process.env.SCREENSHOT_DIR, { recursive: true }); await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'admin-logs-desktop.png'), fullPage: true }); }
  await page.getByRole('switch', { name: '每 5 秒自动刷新' }).uncheck();
  logsMode = 'error';
  await page.getByRole('button', { name: '刷新最新日志', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '日志读取失败' }).waitFor();
  logsMode = 'empty';
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await page.getByText('当前没有可显示的日志', { exact: true }).waitFor();
  logsMode = 'ready';
  await page.getByRole('button', { name: '刷新最新日志', exact: true }).click();
  await page.getByText('演示任务需要人工核查', { exact: true }).waitFor();
  await page.goBack();
  await page.getByRole('table', { name: '生成效果反馈列表' }).waitFor();
  assert.equal(await page.getByLabel('关键词', { exact: true }).inputValue(), '尚未查询的草稿', 'switching preserves uncommitted filters');
  await page.goForward();
  await page.getByText('演示任务需要人工核查', { exact: true }).waitFor();
  assert.equal(await page.getByRole('switch', { name: '每 5 秒自动刷新' }).isChecked(), false, 'log preference survives switches');
  await page.getByRole('switch', { name: '每 5 秒自动刷新' }).check();
  await nav.getByRole('link', { name: '用户反馈', exact: true }).click();
  await page.getByRole('table', { name: '生成效果反馈列表' }).waitFor();
  const beforeWait = requests.filter(item => item.path === '/api/logs/latest').length;
  await page.waitForTimeout(5200);
  assert.equal(requests.filter(item => item.path === '/api/logs/latest').length, beforeWait, 'inactive log panel does not poll');

  await page.getByRole('button', { name: '编辑反馈 1', exact: true }).click();
  await page.getByLabel('意见与建议', { exact: false }).fill('保留尚未保存的反馈意见');
  await page.goBack();
  await page.getByText('演示任务需要人工核查', { exact: true }).waitFor();
  assert.equal(await page.getByRole('dialog', { name: '编辑反馈', exact: true }).isVisible(), false, 'inactive modal is removed from the top layer');
  await page.goForward();
  await page.getByRole('dialog', { name: '编辑反馈', exact: true }).waitFor();
  assert.equal(await page.getByLabel('意见与建议', { exact: false }).inputValue(), '保留尚未保存的反馈意见');
  await page.getByRole('button', { name: '关闭详情', exact: true }).click();
  await page.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(await page.getByLabel('意见与建议', { exact: false }).inputValue(), '保留尚未保存的反馈意见');
  await page.getByRole('button', { name: '关闭详情', exact: true }).click();
  await page.getByRole('button', { name: '放弃修改', exact: true }).click();
  await page.getByLabel('关键词', { exact: true }).fill('提交筛选');
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await page.getByRole('table', { name: '生成效果反馈列表' }).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('q'), '提交筛选');
  await nav.getByRole('link', { name: '运行日志', exact: true }).focus();
  await page.keyboard.press('Enter');
  await page.getByText('演示任务需要人工核查', { exact: true }).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('q'), '提交筛选');
  await nav.getByRole('link', { name: '用户反馈', exact: true }).click();
  await page.getByRole('table', { name: '生成效果反馈列表' }).waitFor();
  if (process.env.SCREENSHOT_DIR) await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'admin-feedback-desktop.png'), fullPage: true });

  async function assertView(view, label) {
    await page.getByRole('heading', { name: view === 'feedback' ? '问题反馈管理' : label, exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get('view'), view === 'feedback' ? null : view);
    assert.equal(new URL(page.url()).searchParams.get('q'), '提交筛选');
    assert.equal(new URL(page.url()).searchParams.get('log_source'), 'service');
    assert.equal(await nav.getByRole('link', { name: label, exact: true }).getAttribute('aria-current'), 'page');
    assert.equal(await nav.locator('[aria-current="page"]').count(), 1);
    if (view === 'resources') await page.getByText('暂无操作资料', { exact: true }).waitFor();
    else if (view === 'admins') await page.getByRole('table', { name: '管理员权限名单', exact: true }).waitFor();
    else if (view === 'logs') await page.getByText('演示任务需要人工核查', { exact: true }).waitFor();
    else await page.getByRole('table', { name: '生成效果反馈列表', exact: true }).waitFor();
  }
  const destinations = [['resources', '操作资料上传'], ['admins', '管理员名单'], ['logs', '运行日志'], ['feedback', '用户反馈']];
  for (const [view, label] of destinations) {
    await nav.getByRole('link', { name: label, exact: true }).click();
    await assertView(view, label);
    if (process.env.SCREENSHOT_DIR && (view === 'resources' || view === 'admins')) {
      await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, `admin-${view}-desktop.png`), fullPage: true, animations: 'disabled' });
    }
  }
  for (const [view, label] of destinations.slice(0, -1).reverse()) {
    await page.goBack();
    await assertView(view, label);
  }
  for (const [view, label] of destinations.slice(1)) {
    await page.goForward();
    await assertView(view, label);
  }
  const ratingSelect = page.locator('#feedback-rating-filter');
  await ratingSelect.focus();
  await ratingSelect.press('ArrowDown');
  await page.waitForFunction(() => Math.abs(document.getElementById('feedback-rating-filter').closest('.ant-select').getBoundingClientRect().width - document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)').getBoundingClientRect().width) <= 1);
  const selectBox = await page.locator('.ant-select').filter({ has: ratingSelect }).boundingBox();
  const optionBox = await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)').boundingBox();
  assert.ok(Math.abs(selectBox.width - optionBox.width) <= 1);
  await page.keyboard.press('Escape');
  listMode = 'error';
  await page.getByRole('button', { name: '刷新列表', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '反馈服务暂不可用' }).waitFor();
  listMode = 'empty';
  await page.getByRole('button', { name: '重试加载', exact: true }).click();
  await page.getByText('没有找到反馈记录。', { exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.equal(await nav.isVisible(), false);
  await page.getByRole('button', { name: '管理菜单', exact: false }).click();
  assert.equal(await nav.isVisible(), true);
  if (process.env.SCREENSHOT_DIR) await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'admin-menu-mobile.png'), fullPage: true });
  await nav.getByRole('link', { name: '运行日志', exact: true }).click();
  await page.getByText('演示任务需要人工核查', { exact: true }).waitFor();
  assert.equal(await nav.isVisible(), false);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  if (process.env.SCREENSHOT_DIR) await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'admin-logs-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: '统一登录设置', exact: true }).click();
  await page.getByRole('dialog', { name: '统一登录设置', exact: true }).getByLabel('登录应用 ID', { exact: true }).waitFor();
  await page.keyboard.press('Escape');
  await page.goto(`${base}/feedback?q=旧链接&rating=poor`);
  await page.getByText('没有找到反馈记录。', { exact: true }).waitFor();
  assert.equal(new URL(page.url()).pathname, '/admin');
  assert.equal(new URL(page.url()).searchParams.get('q'), '旧链接');
  await page.goto(`${base}/admin?view=logs&q=CY&log_source=service`);
  await page.getByText('演示任务需要人工核查', { exact: true }).waitFor();
  assert.match(await page.title(), /运行日志 · 管理员页面/);
  await page.goto(`${base}/logs`);
  await page.getByRole('heading', { name: '运行日志', exact: true }).waitFor();
  await page.getByRole('link', { name: '返回研制任务书平台', exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log('Unified admin browser passed without URLSearchParams.size: all four sidebar views, URL history, filter/editor drafts, polling lifecycle, API errors/empty/recovery, Beijing time, keyboard/select, mobile, settings and legacy routes.');
} finally { await browser.close(); }
