/** Run against Vite: PLAYWRIGHT_MODULE may point at an existing Playwright installation. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true });
const failures = [];
const error = '需求语义分类失败：LLM 未返回可解析的 JSON。';

try {
  for (const transport of ['sse', 'poll']) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    let failed = false;
    await page.route('**/api/**', (route) => {
      const pathname = new URL(route.request().url()).pathname;
      if (!pathname.startsWith('/api/')) return route.continue();
      let response = {};
      if (pathname === '/api/product_catalog') response = { product_types: [] };
      if (pathname === '/api/models') response = { success: true, models: [] };
      if (pathname === '/api/history' || pathname === '/api/local_defaults') response = [];
      if (pathname === '/api/history' && failed) response = [{ jid: 'failed-ui-replay', status: 'error', error, product: '射频连接器失败任务' }];
      if (pathname.startsWith('/api/indicator_review/')) response = { manual_review_required: [], comparison_decisions: [], indicator_clarifications: {} };
      if (pathname.startsWith('/api/status/')) {
        response = { status: transport === 'poll' ? 'error' : 'running', error,
          log: [`❌ ${error}`], log_count: 1, log_offset: 0 };
      }
      return route.fulfill({ json: response });
    });
    await page.addInitScript(() => {
      window.EventSource = class {
        constructor() { window.testEventSource = this; }
        close() { this.closed = true; }
      };
    });
    await page.goto(process.env.TEST_BASE_URL || 'http://127.0.0.1:5173/');
    await page.locator('#workspace-shell').waitFor();
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('taskbook:replay-started', { detail: { jid: 'failed-ui-replay' } })));
    await page.locator('#btn-cancel').waitFor();
    failed = true;
    await page.evaluate(({ transport, error }) => {
      const es = window.testEventSource;
      const emit = (data, lastEventId = '') => es.onmessage({ data: JSON.stringify(data), lastEventId });
      emit({ type: 'log', msg: `❌ ${error}` }, '1');
      if (transport === 'sse') emit({ type: 'error', msg: error });
      else es.onerror();
    }, { transport, error });
    await page.locator('#btn-progress-reset').waitFor();
    const heading = await page.locator('#progress-card h2').innerText();
    const live = await page.locator('#progress-live').innerText();
    const errorLogs = await page.locator('#log-box > div').filter({ hasText: error }).count();
    for (const [description, check] of [
      ['terminal heading', () => assert.match(heading, /失败/)],
      ['no RUNNING label', () => assert.doesNotMatch(heading, /RUNNING/)],
      ['terminal live status', () => assert.match(live, /失败/)],
      ['single error log', () => assert.equal(errorLogs, 1)],
      ['result describes failure', async () => assert.match(await page.locator('#result-empty').innerText(), /失败/)],
      ['header describes stop', async () => assert.match(await page.locator('.flow-progress').innerText(), /已停止/)],
      ['consistent progress bars', async () => assert.equal(await page.locator('#prog-bar').evaluate((element) => element.style.width), await page.locator('#flow-progress-value').evaluate((element) => element.style.width))],
      ['failed history refreshed', async () => {
        await page.locator('#sidebar-history-list .sidebar-item').waitFor({ timeout: 1500 });
        await page.locator('button[data-review="history"]').click({ timeout: 1500 });
        assert.equal(await page.locator('#history-grid').isVisible(), true, 'history failure details must be visible');
        assert.match(await page.locator('#history-grid').innerText(), /需求语义分类失败/);
        assert.equal(await page.locator('#history-grid a[href*="/api/download/"]').count(), 0);
        await page.locator('button[data-review="result"]').click();
      }],
    ]) {
      try { await check(); }
      catch (failure) { failures.push(`${transport}: ${description}: ${failure.message}`); }
    }
    if (transport === 'sse' && process.env.SCREENSHOT_DIR) {
      await mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
      await page.waitForTimeout(400); // Let the existing progress transition finish before visual capture.
      await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'job-failure-desktop.png'), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.locator('#sidebar .sidebar-toggle').click();
      await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'job-failure-mobile.png'), fullPage: true });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'mobile horizontal overflow');
      await page.setViewportSize({ width: 1440, height: 1000 });
    }
    // A late heartbeat/error from the closed connection must not overwrite the terminal UI.
    await page.evaluate(({ error }) => {
      const es = window.testEventSource;
      window.previousEventSource = es;
      es.onmessage({ data: JSON.stringify({ type: 'heartbeat', stage: '仍在处理' }) });
      es.onmessage({ data: JSON.stringify({ type: 'error', msg: error }) });
    }, { error });
    assert.match(await page.locator('#progress-live').innerText(), /失败/);
    assert.equal(await page.locator('#log-box > div').filter({ hasText: error }).count(), 1);
    await page.locator('#btn-progress-reset').click();
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('taskbook:replay-started', { detail: { jid: 'next-job' } })));
    await page.locator('#btn-cancel').waitFor();
    await page.evaluate(({ error }) => window.previousEventSource.onmessage({ data: JSON.stringify({ type: 'error', msg: error }) }), { error });
    assert.match(await page.locator('#progress-card h2').innerText(), /正在执行/);
    assert.equal(await page.locator('#log-box > div').count(), 0);
    await page.evaluate(() => window.testEventSource.onmessage({ data: JSON.stringify({ type: 'done', result: {} }) }));
    await page.locator('#result-card').waitFor();
    assert.equal(await page.locator('#result-title').innerText(), '生成完成');
    for (const terminal of ['cancelled', 'blocked']) {
      await page.evaluate((terminal) => window.dispatchEvent(new CustomEvent('taskbook:replay-started', { detail: { jid: `next-${terminal}` } })), terminal);
      await page.locator('#btn-cancel').waitFor();
      await page.evaluate((terminal) => window.testEventSource.onmessage({ data: JSON.stringify({ type: terminal, result: { delivery_status: terminal } }) }), terminal);
      if (terminal === 'cancelled') {
        await page.locator('#btn-progress-reset').waitFor();
        assert.match(await page.locator('#progress-card h2').innerText(), /已停止/);
        assert.doesNotMatch(await page.locator('#progress-card h2').innerText(), /失败/);
      } else {
        await page.locator('#result-card').waitFor();
        assert.match(await page.locator('#result-title').innerText(), /未通过交付门禁/);
      }
    }
    await page.close();
  }
} finally {
  await browser.close();
}

if (failures.length) {
  console.error(failures.join('\n'));
  process.exitCode = 1;
} else {
  console.log('PASS: SSE/poll failure, history refresh, error deduplication, late events, retry, success, cancellation and blocked delivery.');
}
