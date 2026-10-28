import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
const homeUrl = new URL('/', base).toString();
const logsUrl = new URL('/logs', base).toString();
const logAliasUrl = new URL('/log', base).toString();
const screenshotDir = process.env.SCREENSHOT_DIR;
if (screenshotDir) await mkdir(screenshotDir, { recursive: true });

const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(10000);
const errors = [];
const requests = [];
let failNext = false;
let delayNextMs = 0;
let entries = [
  {
    timestamp: '2026-09-21T10:15:30+08:00',
    level: 'INFO',
    logger: 'taskbook.pipeline',
    message: '初始日志快照',
    correlation_id: 'run-initial',
    method: 'POST',
    path: '/api/jobs',
    status_code: 200,
    duration_ms: 128,
  },
  {
    timestamp: '2026-09-21T10:15:31+08:00',
    level: 'ERROR',
    logger: 'taskbook.pipeline',
    message: '用于排查的异常日志',
    correlation_id: 'run-initial',
    event: 'taskbook_job_failed',
    job_id: 'job-visible',
    stage: 'quality_gate',
    process_classification: '改型II',
    model: 'deepseek-v4-flash',
    error_type: 'DeliveryGateBlocked',
    error_summary: '质量门禁未通过：缺少来源覆盖',
    exception: 'RuntimeError: synthetic failure',
  },
];

page.on('pageerror', error => errors.push(error.message));
page.on('console', message => {
  if (message.type() === 'error' && !/Failed to load resource/.test(message.text())) errors.push(message.text());
});

await page.route('**/api/logs/latest?*', async route => {
  const request = route.request();
  requests.push({ url: request.url(), header: request.headers()['x-log-viewer'], method: request.method() });
  if (failNext) {
    failNext = false;
    return route.fulfill({ status: 503, json: { error: '日志服务暂时不可用' } });
  }
  const delay = delayNextMs;
  delayNextMs = 0;
  if (delay) await new Promise(resolve => setTimeout(resolve, delay));
  return route.fulfill({ json: {
    entries,
    returned: entries.length,
    limit: 200,
    source: 'runtime/taskbook-service.log',
    updated_at: '2026-09-21T10:15:32+08:00',
    truncated: entries.length >= 200,
    filtered_transport: 23,
  } });
});

try {
  await page.goto(homeUrl);
  await page.getByRole('heading', { name: '研制任务书平台', exact: true }).waitFor();
  assert.equal(await page.locator('button[data-page="runtime-logs"]').count(), 0, 'home navigation does not expose logs as a business page');
  assert.equal(await page.getByRole('button', { name: '运行日志', exact: true }).count(), 0, 'home has no runtime-log navigation button');
  assert.equal(requests.length, 0, 'home does not load the diagnostics log feed');

  await page.goto(logsUrl);
  await page.getByRole('heading', { name: '运行日志', exact: true }).waitFor();
  await page.getByText('初始日志快照', { exact: true }).waitFor();

  assert.equal(await page.locator('#workspace-shell').count(), 0, 'standalone logs do not mount the task workspace');
  assert.equal(await page.locator('.top-nav, #sidebar').count(), 0, 'standalone logs have no business navigation or task sidebar');
  assert.equal(await page.getByRole('link', { name: '返回研制任务书平台', exact: true }).getAttribute('href'), '/');

  assert.ok(requests.length >= 1, 'latest logs are requested when the page opens');
  for (const request of requests) {
    assert.equal(request.method, 'GET');
    assert.equal(request.header, '1');
    assert.equal(new URL(request.url).searchParams.get('limit'), '200');
  }
  assert.equal(await page.getByText('ERROR', { exact: true }).count(), 1);
  assert.equal(await page.getByText('关联 ID：run-initial', { exact: true }).count(), 2);
  assert.match(await page.locator('.runtime-log-context').first().innerText(), /POST.*\/api\/jobs.*200.*128 ms/s);
  const diagnosticContext = await page.locator('.runtime-log-context').nth(1).innerText();
  assert.match(diagnosticContext, /任务 ID\s*job-visible/);
  assert.match(diagnosticContext, /阶段\s*quality_gate/);
  assert.match(diagnosticContext, /研制流程\s*改型II/);
  assert.match(diagnosticContext, /错误类型\s*DeliveryGateBlocked/);
  assert.match(diagnosticContext, /错误摘要\s*质量门禁未通过/);
  assert.match(await page.locator('.runtime-log-exception').innerText(), /synthetic failure/);
  assert.match(await page.locator('.runtime-log-meta').innerText(), /已过滤 23 条底层网络调试记录/);
  assert.equal(await page.getByRole('switch', { name: '每 5 秒自动刷新', exact: true }).isChecked(), true);

  if (screenshotDir) await page.screenshot({ path: join(screenshotDir, 'runtime-logs-desktop.png'), fullPage: true });

  entries = [{
    timestamp: '2026-09-21T10:20:00+08:00', level: 'WARNING', logger: 'taskbook.delivery',
    message: '刷新后的最新日志', correlation_id: 'run-latest', stage: 'quality_gate',
  }];
  delayNextMs = 5500;
  const requestsBeforeSlowRefresh = requests.length;
  await page.getByRole('button', { name: '刷新最新日志', exact: true }).click();
  await page.waitForTimeout(5200);
  assert.equal(requests.length, requestsBeforeSlowRefresh + 1, 'automatic refresh reuses an in-flight request instead of aborting or duplicating it');
  await page.getByText('刷新后的最新日志', { exact: true }).waitFor();
  await page.getByRole('switch', { name: '每 5 秒自动刷新', exact: true }).uncheck();
  assert.equal(await page.getByText('初始日志快照', { exact: true }).count(), 0, 'refresh replaces the old snapshot');
  assert.match(await page.locator('.runtime-log-meta').innerText(), /1 条记录.*刷新于/);

  failNext = true;
  await page.getByRole('button', { name: '刷新最新日志', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '日志服务暂时不可用' }).waitFor();
  assert.equal(await page.getByText('刷新后的最新日志', { exact: true }).count(), 1, 'failed refresh keeps the last snapshot');
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await page.getByRole('alert').waitFor({ state: 'detached' });

  entries = [];
  await page.getByRole('button', { name: '刷新最新日志', exact: true }).click();
  await page.getByText('当前没有可显示的日志', { exact: true }).waitFor();

  entries = [{
    timestamp: '2026-09-21T10:25:00+08:00', level: 'ERROR', logger: 'taskbook.semantic_orchestrator',
    message: '移动端也需要完整显示用于直接排查的最新日志内容，较长消息应自然换行。',
    correlation_id: 'run-mobile-long-correlation-id', path: '/api/jobs/example/status', status_code: 500,
  }];
  await page.getByRole('button', { name: '刷新最新日志', exact: true }).click();
  await page.getByText(/移动端也需要完整显示/).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'mobile page has no horizontal overflow');
  if (screenshotDir) await page.screenshot({ path: join(screenshotDir, 'runtime-logs-mobile.png'), fullPage: true });

  await page.goto(logAliasUrl);
  await page.getByRole('heading', { name: '运行日志', exact: true }).waitFor();
  await page.getByText(/移动端也需要完整显示/).waitFor();
  assert.equal(await page.locator('#workspace-shell').count(), 0, '/log alias also opens the standalone diagnostics page');

  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ passed: true, requests: requests.length, standalone: true, alias: true, snapshotReplacement: true, retainedAfterError: true, mobile: true }));
} finally {
  await browser.close();
}
