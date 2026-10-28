import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5193';
const shotDir = process.env.SCREENSHOT_DIR;
if (shotDir) await mkdir(shotDir, { recursive: true });
const errors = [], requests = [];
const common = { started_at: '2026-10-22T02:20:00Z', finished_at: '2026-10-22T02:25:12Z', duration_ms: 312000,
  username: '测试工程师', userid: 'oa-user-01', request_kind: 'generation', product_type: '矩形低频连接器', product_series: 'CY', model: 'azure/gpt-5',
  files: { tech: '矩形低频技术要求.docx', spec: '矩形低频产品规范.docx', output: '研制任务书_CY.docx' }, error_summary: null, event_count: 5 };
const records = [
  { ...common, request_id: 'request-failed', job_id: 'job-failed', status: 'failed', error_summary: '质量门禁未通过：存在未确认的技术指标' },
  { ...common, request_id: 'request-success', job_id: 'job-success', status: 'success' },
  { ...common, request_id: 'request-running', job_id: 'job-running', status: 'running', finished_at: null, duration_ms: null, event_count: 1 },
];
const entries = [
  { id: 1, timestamp: '2026-10-22T02:20:00Z', level: 'INFO', logger: 'taskbook.request', message: '开始生成研制任务书', job_id: 'job-failed', stage: 'precheck' },
  { id: 2, timestamp: '2026-10-22T02:21:00Z', level: 'INFO', logger: 'taskbook.routing', message: '需求语义分类完成', job_id: 'job-failed', stage: 'semantic_routing' },
  { id: 3, timestamp: '2026-10-22T02:22:00Z', level: 'INFO', logger: 'taskbook.assembly', message: '原文搬运完成', job_id: 'job-failed', stage: 'assembly' },
  { id: 4, timestamp: '2026-10-22T02:24:00Z', level: 'ERROR', logger: 'taskbook.gate', message: '质量门禁未通过', stage: 'quality_gate', exception: 'QualityGateError: 指标引用尚未确认', error_summary: '存在未确认的技术指标' },
  { id: 5, timestamp: '2026-10-22T02:25:12Z', level: 'ERROR', logger: 'taskbook.request', message: '本次生成结束，交付失败', stage: 'completed' },
];
let listMode = 'ready', detailMode = 'ready', runCompleted = false;

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, timezoneId: 'America/New_York' });
  page.setDefaultTimeout(10000);
  page.setDefaultNavigationTimeout(30000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) return route.continue();
    requests.push({ path: url.pathname, params: Object.fromEntries(url.searchParams), headers: route.request().headers() });
    if (url.pathname === '/api/admin/session') return route.fulfill({ json: { authenticated: true, user: { username: 'wangxue', display_name: '测试管理员', userid: 'owner-test' }, can_manage_admins: true } });
    if (url.pathname === '/api/logs/requests') {
      if (listMode === 'error') return route.fulfill({ status: 503, json: { error: '归档服务暂不可用' } });
      let items = listMode === 'empty' ? [] : records.map(item => item.status === 'running' && runCompleted ? { ...item, status: 'success' } : item);
      if (url.searchParams.get('status')) items = items.filter(item => item.status === url.searchParams.get('status'));
      if (url.searchParams.get('q') === '没有结果') items = [];
      return route.fulfill({ json: { items, retention: 50, stats: { total: 3, running: runCompleted ? 0 : 1, success: runCompleted ? 2 : 1, failed: 1 } } });
    }
    if (url.pathname.startsWith('/api/logs/requests/')) {
      if (detailMode === 'expired') return route.fulfill({ status: 404, json: { error: '请求记录已不存在' } });
      if (detailMode === 'error') return route.fulfill({ status: 503, json: { error: '归档暂时不可读' } });
      const id = url.pathname.split('/').at(-1), after = Number(url.searchParams.get('after'));
      const record = records.find(item => item.request_id === id);
      assert.equal(url.searchParams.get('limit'), '500');
      if (id === 'request-running') {
        const result = after ? runCompleted ? [{ ...entries[1], message: '执行成功，文件已生成' }] : [] : [entries[0]];
        return route.fulfill({ json: { request: { ...record, status: runCompleted ? 'success' : 'running', event_count: runCompleted ? 2 : 1 }, entries: result, next_cursor: runCompleted ? 2 : 1, has_more: false } });
      }
      const result = after === 0 ? entries.slice(0, 3) : entries.filter(entry => entry.id > after);
      return route.fulfill({ json: { request: record, entries: result, next_cursor: after === 0 ? 3 : 5, has_more: after === 0 } });
    }
    if (url.pathname === '/api/logs/latest') return route.fulfill({ json: { entries: [{ ...entries[0], message: '服务实时快照' }], returned: 1, limit: 200, source: 'logs/app.log', updated_at: common.started_at, truncated: false } });
    if (url.pathname === '/api/feedback-admin') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20, stats: { total: 0, good: 0, average: 0, poor: 0, good_rate: 0, open: 0, in_progress: 0, resolved: 0 } } });
    if (url.pathname === '/api/settings/auth') return route.fulfill({ json: { settings: { enabled: false, app_id: 9086, platform_base_url: 'https://sv.dcsmartvision.com', public_url: null }, active: { enabled: false }, can_edit: true, version: 1 } });
    return route.fulfill({ status: 404, json: { error: 'Unexpected API' } });
  });
  const nav = page.getByRole('navigation', { name: '管理员导航', exact: true });
  await page.goto(`${base}/admin?view=logs&q=反馈保留词`);
  await page.getByRole('table', { name: '生成请求记录', exact: true }).waitFor();
  assert.equal(requests.filter(item => item.path === '/api/logs/latest').length, 0, 'latest source is not polled by the archive page');
  assert.equal(requests.find(item => item.path === '/api/logs/requests').headers['x-log-viewer'], '1');
  await page.getByText(/最多保留 50 条已完成请求/).waitFor();
  assert.match(await page.locator('.request-log-table time').first().innerText(), /10:20:00/);
  for (const status of ['成功', '失败', '执行中']) assert.equal(await page.locator('.request-log-table').getByText(status, { exact: true }).count(), 1);
  if (shotDir) await page.screenshot({ path: join(shotDir, 'request-list-desktop.png'), fullPage: true });
  await page.getByRole('switch', { name: '每 5 秒自动刷新' }).uncheck();
  await page.getByLabel('请求状态', { exact: true }).click();
  await page.getByRole('option', { name: '失败', exact: true }).click();
  await page.getByLabel('日志关键词', { exact: true }).fill('CY');
  await page.getByRole('button', { name: '查询请求', exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('.request-log-table tbody tr').length === 1);
  assert.equal(new URL(page.url()).searchParams.get('log_status'), 'failed');
  assert.equal(new URL(page.url()).searchParams.get('log_q'), 'CY');
  assert.equal(new URL(page.url()).searchParams.get('q'), '反馈保留词');
  await page.getByRole('button', { name: '查看请求 job-failed', exact: true }).click();
  await page.getByText('开始生成研制任务书', { exact: true }).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('log_request'), 'request-failed');
  assert.match(await page.locator('.request-log-failure').innerText(), /存在未确认的技术指标/);
  await page.getByText('已显示 3 / 5 条日志 · 还有后续记录', { exact: true }).waitFor();
  await page.getByRole('button', { name: '加载后续日志', exact: true }).click();
  await page.getByText('本次生成结束，交付失败', { exact: true }).waitFor();
  await page.getByText('已显示 5 / 5 条日志 · 已显示全部记录', { exact: true }).waitFor();
  assert.equal(requests.find(item => item.path.endsWith('/request-failed') && item.params.after === '3')?.headers['x-log-viewer'], '1');
  assert.equal(await page.locator('.request-log-stream .runtime-log-row').count(), 5);
  await page.getByRole('button', { name: '刷新请求日志', exact: true }).click();
  await page.getByRole('button', { name: '刷新请求日志', exact: true }).waitFor();
  assert.equal(await page.locator('.request-log-stream .runtime-log-row').count(), 5, 'refresh appends without duplicate entries');
  detailMode = 'error';
  await page.getByRole('button', { name: '刷新请求日志', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '请求详情读取失败' }).waitFor();
  assert.equal(await page.locator('.request-log-stream .runtime-log-row').count(), 5);
  detailMode = 'ready';
  await page.getByRole('button', { name: '重试读取', exact: true }).click();
  await page.getByRole('alert').waitFor({ state: 'hidden' });
  if (shotDir) await page.screenshot({ path: join(shotDir, 'request-detail-desktop.png'), fullPage: true });
  await nav.getByRole('link', { name: '用户反馈', exact: true }).click();
  await page.getByText('没有找到反馈记录。', { exact: true }).waitFor();
  const before = requests.filter(item => item.path.startsWith('/api/logs/')).length;
  await page.waitForTimeout(5200);
  assert.equal(requests.filter(item => item.path.startsWith('/api/logs/')).length, before);
  await nav.getByRole('link', { name: '运行日志', exact: true }).click();
  await page.getByText('本次生成结束，交付失败', { exact: true }).waitFor();
  assert.equal(await page.getByRole('switch', { name: '每 5 秒自动刷新' }).isChecked(), false);
  await page.getByRole('button', { name: '← 返回请求列表', exact: true }).click();
  await page.getByRole('button', { name: '查看请求 job-failed', exact: true }).waitFor();
  assert.equal(await page.getByLabel('日志关键词', { exact: true }).inputValue(), 'CY');
  assert.equal(await page.getByRole('button', { name: '查看请求 job-failed', exact: true }).evaluate(element => document.activeElement === element), true);
  await page.goBack();
  await page.getByRole('heading', { name: '请求全过程', exact: true }).waitFor();
  detailMode = 'expired';
  await page.getByRole('button', { name: '刷新请求日志', exact: true }).click();
  await page.getByText('这条请求记录已不存在', { exact: true }).waitFor();
  assert.equal(await page.getByRole('region', { name: '请求全过程日志' }).count(), 0);
  await page.getByRole('button', { name: '返回现有请求', exact: true }).click();
  detailMode = 'ready';
  await page.getByRole('button', { name: '清除日志关键词', exact: true }).click();
  assert.equal(await page.getByLabel('日志关键词', { exact: true }).inputValue(), '');
  assert.equal(new URL(page.url()).searchParams.has('log_q'), false);
  listMode = 'error';
  await page.getByRole('button', { name: '刷新请求列表', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '请求记录读取失败' }).waitFor();
  await page.getByRole('table', { name: '生成请求记录', exact: true }).waitFor();
  listMode = 'empty';
  await page.getByRole('button', { name: '重试请求列表', exact: true }).click();
  await page.getByText('没有符合条件的请求', { exact: true }).waitFor();
  await page.getByRole('button', { name: '清除筛选', exact: true }).click();
  await page.getByText('暂无生成请求记录', { exact: true }).waitFor();
  listMode = 'ready';
  await page.getByRole('button', { name: '刷新请求列表', exact: true }).click();
  await page.getByRole('button', { name: '查看请求 job-running', exact: true }).click();
  await page.getByText('已显示 1 / 1 条日志 · 请求仍在执行', { exact: true }).waitFor();
  await page.getByRole('switch', { name: '每 5 秒自动刷新' }).check();
  runCompleted = true;
  await page.getByText('执行成功，文件已生成', { exact: true }).waitFor();
  await page.getByText('已显示 2 / 2 条日志 · 已显示全部记录', { exact: true }).waitFor();
  await nav.getByRole('link', { name: '用户反馈', exact: true }).click();
  const beforePaused = requests.filter(item => item.path.startsWith('/api/logs/')).length;
  await page.waitForTimeout(5200);
  assert.equal(requests.filter(item => item.path.startsWith('/api/logs/')).length, beforePaused, 'active polling stops when hidden');
  await nav.getByRole('link', { name: '运行日志', exact: true }).click();
  await page.getByRole('button', { name: '服务实时日志', exact: true }).click();
  await page.getByText('服务实时快照', { exact: true }).waitFor();
  await page.getByRole('button', { name: '生成请求记录', exact: true }).click();
  await page.getByText('执行成功，文件已生成', { exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  if (shotDir) await page.screenshot({ path: join(shotDir, 'request-detail-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: '← 返回请求列表', exact: true }).click();
  await page.getByRole('table', { name: '生成请求记录', exact: true }).waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  if (shotDir) await page.screenshot({ path: join(shotDir, 'request-list-mobile.png'), fullPage: true });
  await page.goto(`${base}/admin?view=logs&log_request=request-failed&log_status=failed`);
  await page.getByText('开始生成研制任务书', { exact: true }).waitFor();
  assert.equal(await page.getByRole('heading', { name: '请求全过程', exact: true }).isVisible(), true);
  await page.goto(`${base}/logs`);
  await page.getByRole('link', { name: '返回研制任务书平台', exact: true }).waitFor();
  await page.getByText('服务实时快照', { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log('Request log browser passed: archive list/detail, status/Beijing time, URL filters/history, full cursor pagination, append deduplication, failures/retry/expired/empty, running-to-success polling, inactive stop, realtime compatibility, mobile screenshots.');
} finally { await browser.close(); }
