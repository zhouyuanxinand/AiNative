/** Long-document navigation uses synthetic API data; no real task is changed. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
const artifacts = process.env.TEST_ARTIFACT_DIR || '../basic-service/app/runtime/navigation-fix';
await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const paragraph = (id, text, heading_level = 0) => ({ id, kind: 'paragraph', text, heading_level, editable: true, can_delete: true, images: [] });
const chapters = Array.from({ length: 8 }, (_, i) => i + 1);
function projection(prefix) {
  const blocks = chapters.flatMap(i => [paragraph(`${prefix}-${i}`, `${i} 专项要求`, 1),
    ...Array.from({ length: 12 }, (_, j) => paragraph(`${prefix}-${i}-${j}`, `${i}.${j + 1} ${j === 8 ? '待确认：' : ''}试验要求及原文技术数据，保留条件、阈值和考核标准。`.repeat(3)))]);
  return { document_id: prefix, sha256: prefix, format: 'docx', view_mode: 'content', blocks,
    outline: chapters.map(i => ({ id: `${prefix}-${i}`, text: `${i} 专项要求`, level: 1 })), sections: [], warnings: [] };
}
const output = projection('out');
const source = projection('src');
// Keep the original final pending paragraph while exercising a target inside
// the document's independently scrollable wide table.
output.blocks.unshift({ id: 'out-wide-table', kind: 'table', rows: [{ cells: Array.from({ length: 12 }, (_, i) => ({
  id: `out-cell-${i}`, colspan: 1, rowspan: 1,
  blocks: [paragraph(`out-cell-paragraph-${i}`, i === 11 ? '待确认：右侧表格目标' : `字段${i}`)],
})) }] });
const bundle = { jid: 'navigation-fixture', title: '长文档目录定位 · 合成测试', selection: {}, warnings: [],
  baseline_revision_id: 'baseline', current_revision_id: 'baseline',
  assets: [{ id: 'tech', role: 'tech', label: '需求文件', name: '测试需求.docx', format: 'docx', available: true, url: '/source.docx' }],
  revisions: [{ id: 'baseline', created_at: '2026-10-27T12:00:00+08:00', sha256: 'baseline', annotations: [],
    checks: { status: 'needs_review', issues: [{ message: '核对末章条件', element_id: 'out-8-8', severity: 'warning' }] } }] };
const links = chapters.map(i => ({ output_element_ids: [`out-${i}`], source_asset_id: 'tech', source_element_ids: [`src-${i}`], status: 'verified', label: '来源证据' }));

async function assertNavigationVisible(page, mobile, name) {
  const state = await page.evaluate(mobile => {
    const selector = mobile ? '.review-mobile-switch' : '.review-outline';
    const rect = document.querySelector(selector).getBoundingClientRect();
    return { scrollY, scrollX, top: rect.top, bottom: rect.bottom, viewport: innerHeight, width: document.documentElement.scrollWidth, viewportWidth: innerWidth };
  }, mobile);
  assert.equal(state.scrollY, 0, `${name}: document navigation must not scroll the page: ${JSON.stringify(state)}`);
  assert.equal(state.scrollX, 0, `${name}: no horizontal page jump`);
  assert.ok(state.top >= 0 && state.bottom <= state.viewport + 1, `${name}: chapter navigation remains in the viewport: ${JSON.stringify(state)}`);
  assert.ok(state.width <= state.viewportWidth, `${name}: no horizontal overflow`);
}

async function settledScrollTop(locator) {
  return locator.evaluate(element => new Promise((resolve, reject) => {
    let previous = element.scrollTop, stableFrames = 0;
    const started = performance.now();
    function sample() {
      const current = element.scrollTop;
      stableFrames = Math.abs(current - previous) < 0.5 ? stableFrames + 1 : 0;
      previous = current;
      if (stableFrames >= 5) resolve(current);
      else if (performance.now() - started > 3000) reject(new Error('Document scroll did not settle'));
      else requestAnimationFrame(sample);
    }
    requestAnimationFrame(sample);
  }));
}

async function assertMobileReadingPosition(page, scenario) {
  const sourcePane = page.locator('.review-source-panel .review-document-scroll');
  const outputPane = page.locator('.review-output-panel .review-document-scroll');
  await settledScrollTop(sourcePane);
  const sourceBefore = await sourcePane.evaluate(element => {
    element.scrollBy({ top: 240, behavior: 'instant' }); return element.scrollTop;
  });
  await page.getByRole('button', { name: '任务书', exact: true }).click();
  await page.getByRole('button', { name: '来源', exact: true }).click();
  const sourceAfter = await settledScrollTop(sourcePane);

  await page.getByRole('button', { name: '任务书', exact: true }).click();
  await settledScrollTop(outputPane);
  const outputBefore = await outputPane.evaluate(element => {
    element.scrollBy({ top: 240, behavior: 'instant' }); return element.scrollTop;
  });
  await page.getByRole('button', { name: '来源', exact: true }).click();
  await page.getByRole('button', { name: '任务书', exact: true }).click();
  const outputAfter = await settledScrollTop(outputPane);
  assert.ok(Math.abs(sourceAfter - sourceBefore) <= 1 && Math.abs(outputAfter - outputBefore) <= 1,
    `${scenario}: reading positions changed after panel round trips: ${JSON.stringify({ sourceBefore, sourceAfter, outputBefore, outputAfter })}`);
}

try {
  for (const scenario of [
    { name: 'desktop', mobile: false, legacy: false },
    { name: 'legacy-viewport', mobile: false, legacy: true },
    { name: 'mobile', mobile: true, legacy: false },
    { name: 'mobile-legacy-reduced-motion', mobile: true, legacy: true, reduced: true },
  ]) {
    const context = await browser.newContext({ viewport: scenario.mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 }, reducedMotion: scenario.reduced ? 'reduce' : 'no-preference' });
    const page = await context.newPage(); page.setDefaultTimeout(10000);
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    // Simulate a browser that discards unsupported dynamic viewport declarations.
    // Keep the real production CSS and any preceding vh fallback intact.
    if (scenario.legacy) await page.route('**/taskbookReview.css*', async route => {
      const response = await route.fetch();
      const body = (await response.text()).replace(/height:100dvh;/g, '');
      await route.fulfill({ response, body });
    });
    await page.route('**/api/review/**', route => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith('/editor/status')) return route.fulfill({ json: { configured: false, message: '未配置' } });
      if (url.pathname.endsWith('/document')) return route.fulfill({ json: url.searchParams.has('asset_id') ? source : output });
      if (url.pathname.endsWith('/links')) return route.fulfill({ json: { links, warnings: [] } });
      return route.fulfill({ json: bundle });
    });
    await page.goto(`${base}/review/navigation-fixture`);
    await page.locator('#review-output-out-1').waitFor();
    await page.locator('#review-source-src-1').waitFor({ state: 'attached' });
    for (const chapter of [7, 1, 8]) {
      if (scenario.mobile) await page.getByRole('button', { name: '目录', exact: true }).click();
      await page.locator('.review-outline').getByRole('button', { name: `${chapter} 专项要求`, exact: true }).click();
      await page.waitForFunction(id => {
        const target = document.getElementById(id).getBoundingClientRect();
        const pane = document.querySelector('.review-output-panel .review-document-scroll').getBoundingClientRect();
        return target.top >= pane.top - 1 && target.top < pane.bottom;
      }, `review-output-out-${chapter}`);
      await assertNavigationVisible(page, scenario.mobile, `${scenario.name} chapter ${chapter}`);
    }
    if (scenario.mobile) {
      await page.getByRole('button', { name: '来源', exact: true }).click();
      await page.waitForFunction(() => {
        const target = document.getElementById('review-source-src-8').getBoundingClientRect();
        const pane = document.querySelector('.review-source-panel .review-document-scroll').getBoundingClientRect();
        return target.top >= pane.top && target.top < pane.bottom;
      });
      await assertMobileReadingPosition(page, scenario.name);
      await page.getByRole('button', { name: '目录', exact: true }).click();
    } else {
      await page.locator('#review-source-src-6').click();
      await page.waitForFunction(() => {
        const target = document.getElementById('review-output-out-6').getBoundingClientRect();
        const pane = document.querySelector('.review-output-panel .review-document-scroll').getBoundingClientRect();
        return target.top >= pane.top && target.top < pane.bottom;
      });
    }
    await assertNavigationVisible(page, scenario.mobile, `${scenario.name} linked source`);
    await page.locator('.review-small-tabs').getByRole('button', { name: /待核对/ }).click();
    await page.locator('.review-outline nav button').last().click();
    await assertNavigationVisible(page, scenario.mobile, `${scenario.name} pending requirement`);
    await page.screenshot({ path: path.join(artifacts, `review-${scenario.name}.png`) });

    if (scenario.mobile) await page.getByRole('button', { name: '目录', exact: true }).click();
    const tableTarget = page.locator('.review-outline nav').getByRole('button', { name: '待确认：右侧表格目标', exact: true });
    await tableTarget.scrollIntoViewIfNeeded();
    const outlineBefore = await page.locator('.review-outline nav').evaluate(element => element.scrollTop);
    await tableTarget.click();
    await page.waitForFunction(() => {
      const target = document.getElementById('review-output-out-cell-paragraph-11').getBoundingClientRect();
      const pane = document.querySelector('.review-output-panel .review-document-scroll').getBoundingClientRect();
      const table = document.getElementById('review-output-out-wide-table').getBoundingClientRect();
      return target.top >= pane.top - 1 && target.bottom <= pane.bottom + 1
        && target.left >= Math.max(pane.left, table.left) - 1 && target.right <= Math.min(pane.right, table.right) + 1;
    });
    assert.equal(await page.locator('.review-outline nav').evaluate(element => element.scrollTop), outlineBefore,
      `${scenario.name}: locating a table cell must not move the outline`);
    await assertNavigationVisible(page, scenario.mobile, `${scenario.name} rightmost table cell`);
    await page.screenshot({ path: path.join(artifacts, `review-${scenario.name}-wide-table.png`) });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ scenario: scenario.name, passed: true }));
    await context.close();
  }
} finally { await browser.close(); }
