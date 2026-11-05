/** Read-only screenshots against the running local platform, never a generation or publish command. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'file:///C:/Users/周园鑫/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'docs/rd-platform/verification/screenshots/2026-11-03-antd-flow/actual';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1680, height: 1080 } });
page.setDefaultTimeout(15000);
const errors = [], writes = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
await page.route('**/api/**', route => {
  if (!new URL(route.request().url()).pathname.startsWith('/api/')) return route.continue();
  if (route.request().method() !== 'GET') {
    writes.push(route.request().method() + ' ' + new URL(route.request().url()).pathname);
    return route.fulfill({ status: 405, json: { error: '只读界面检查不允许写入。' } });
  }
  return route.continue();
});
const snap = async name => { await page.screenshot({ path: join(output, name + '.png'), animations: 'disabled' }); };
async function fits(selector) {
  await page.waitForFunction(selector => {
    const canvas = document.querySelector(selector);
    if (!canvas) return false;
    const bounds = canvas.getBoundingClientRect(), nodes = [...canvas.querySelectorAll('.rd-graph-node')];
    return nodes.length > 0 && nodes.every(node => { const rect = node.getBoundingClientRect(); return rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1 && rect.top >= bounds.top - 1 && rect.bottom <= bounds.bottom + 1; });
  }, selector);
}
try {
  await page.goto(base + '/?rd_view=flows&flow_tab=actions');
  await page.getByRole('button', { name: '打开上下文解析专家团画布', exact: true }).waitFor();
  await page.getByRole('button', { name: '刷新项目', exact: true }).waitFor();
  assert(await page.locator('.rd-flow-management .ant-btn').count() > 0, 'real Ant Design buttons render');
  assert(await page.locator('style[data-platform-theme="ant-design"]').count() > 0, 'platform theme mounted');
  await snap('01-action-directory');
  await page.getByRole('button', { name: '打开上下文解析专家团画布', exact: true }).click();
  await fits('.rd-action-detail .rd-graph-scroll');
  assert.equal(await page.locator('.rd-action-detail .rd-graph-node').count(), 1);
  await snap('02-single-action-canvas');
  await page.getByRole('button', { name: '返回动作模板', exact: true }).click();
  await page.getByRole('button', { name: '打开任务书编制专家团画布', exact: true }).click();
  await fits('.rd-action-detail .rd-graph-scroll');
  assert.equal(await page.locator('.rd-action-detail .rd-graph-node').count(), 5);
  await snap('03-five-step-action-canvas');
  checks.push('actual action directory opens the saved single and five-step fixed-version graphs; all nodes fit the viewport');
  await page.getByRole('tab', { name: '流程模板', exact: true }).click();
  await fits('.rd-template-detail .rd-graph-scroll');
  const directoryControls = await page.locator('.rd-template-directory-tools').evaluate(el => [el.querySelector('input'), el.querySelector('.ant-select-selector'), el.querySelector('button')].map(node => ({ top: node.getBoundingClientRect().top, height: node.getBoundingClientRect().height })));
  assert(directoryControls.every(control => Math.abs(control.height - 32) <= 1 && Math.abs(control.top - directoryControls[0].top) <= 1), 'workflow search, category and refresh share aligned 32px control bounds');
  checks.push('workflow directory search, category and refresh controls share aligned 32px bounds');
  const workflowNodeCount = await page.locator('.rd-template-detail .rd-graph-node').count();
  await snap('04-workflow-template-canvas');
  await page.getByRole('button', { name: '版本与回溯', exact: true }).click();
  await page.locator('.rd-template-version-list li').first().waitFor();
  await snap('05-workflow-history');
  checks.push('workflow directory and canvas share one work surface; fixed history remains accessible');
  await page.getByRole('button', { name: '流程画布', exact: true }).click();
  await page.setViewportSize({ width: 1024, height: 900 });
  await fits('.rd-template-detail .rd-graph-scroll');
  assert.equal(await page.locator('.rd-template-workbench').evaluate(el => getComputedStyle(el).gridTemplateColumns.trim().split(/\s+/).length), 1);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await snap('06-workflow-1024px');
  await page.setViewportSize({ width: 390, height: 844 });
  await fits('.rd-template-detail .rd-graph-scroll');
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await page.locator('.rd-template-detail').scrollIntoViewIfNeeded();
  await snap('07-workflow-390px');
  checks.push('1050px single-column breakpoint and 390px flow canvas fit without page horizontal overflow');
  await page.setViewportSize({ width: 1680, height: 1080 });
  await page.getByRole('tab', { name: '智能体与 Skill', exact: true }).click();
  await page.locator('.rd-flow-resource-card').first().waitFor();
  await snap('08-resource-directory');
  await page.getByRole('tab', { name: '报告模板', exact: true }).click();
  await page.locator('.rd-flow-resource-card').first().waitFor();
  await snap('09-report-directory');
  assert.deepEqual(errors, []); assert.deepEqual(writes, []);
  const receipt = { passed: true, mode: 'actual local platform, read-only', actualWrites: 0, checks, workflowNodeCount, errors, writes };
  await writeFile(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt));
} catch (error) {
  await snap('failure');
  await writeFile(join(output, 'failure.json'), JSON.stringify({ message: error.message, errors, writes, text: await page.locator('body').innerText() }, null, 2));
  throw error;
} finally { await browser.close(); }
