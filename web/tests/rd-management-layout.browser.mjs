/** Read-only checks against the live application; never create or alter project data. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [], writes = [], measurements = [];
page.on('pageerror', error => errors.push(error.message));
page.on('request', request => { if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) writes.push({ method: request.method(), path: new URL(request.url()).pathname }); });
const snap = async name => { if (output) await page.screenshot({ path: join(output, name) }); };
async function boxes(view) {
  const search = await page.locator('.rd-management-tools .rd-search').boundingBox();
  const select = await page.locator('.rd-management-tools .select-trigger').boundingBox();
  measurements.push({ view, width: page.viewportSize().width, search, select });
  return { search, select };
}
try {
  for (const [view, title, label] of [['management', '研发管理', '工作范围'], ['operations', '运营管理', '运行状态']]) {
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.goto(`${base}/?rd_view=${view}`);
    await page.getByRole('heading', { name: title, exact: true }).waitFor();
    await page.locator('.rd-management-data-state .rd-loading').waitFor({ state: 'hidden' });
    await page.locator('.rd-management-tools').scrollIntoViewIfNeeded();
    const { search, select } = await boxes(view);
    assert(Math.abs(search.y - select.y) <= 1, `${title}: search/select top edges align (${search.y} vs ${select.y})`);
    assert(Math.abs(search.height - select.height) <= 1, `${title}: search/select heights align`);
    const searchLabel = await page.locator('label[for="rd-management-search"]').boundingBox();
    const selectLabel = await page.locator('#rd-management-filter-label').boundingBox();
    assert(Math.abs(searchLabel.y - selectLabel.y) <= 1, `${title}: labels align as well as controls (${searchLabel.y} vs ${selectLabel.y})`);
    await snap(`${view}-desktop.png`);
    await page.getByRole('button', { name: new RegExp(`^${label} `) }).click();
    await page.getByRole('listbox').waitFor();
    await page.waitForFunction(() => {
      const trigger = document.querySelector('.rd-management-tools .select-trigger');
      const box = trigger?.getBoundingClientRect(), menu = document.getElementById(trigger?.getAttribute('aria-controls'))?.getBoundingClientRect();
      return box && menu && Math.abs(box.width - menu.width) <= 1 && Math.abs(box.x - menu.x) <= 1;
    });
    await snap(`${view}-select-open.png`);
    await page.keyboard.press('Escape');
    await page.getByLabel(`搜索${title}记录`, { exact: true }).fill('没有匹配的项目-布局复核');
    await page.getByRole('button', { name: '清空搜索', exact: true }).click();
    assert.equal(await page.getByLabel(`搜索${title}记录`, { exact: true }).inputValue(), '');
    assert(await page.getByLabel(`搜索${title}记录`, { exact: true }).evaluate(el => el === document.activeElement));
    await page.setViewportSize({ width: 390, height: 520 });
    await page.locator('.rd-management-tools').scrollIntoViewIfNeeded();
    const mobile = await boxes(view);
    assert(Math.abs(mobile.search.x - mobile.select.x) <= 1 && Math.abs(mobile.search.width - mobile.select.width) <= 1, `${title}: stacked controls share full width`);
    assert(mobile.select.y >= mobile.search.y + mobile.search.height, `${title}: stacked controls do not overlap`);
    assert(await page.locator('.rd-application-shell').evaluate(el => el.scrollWidth <= el.clientWidth + 1), `${title}: no page-level horizontal overflow`);
    await snap(`${view}-mobile.png`);
    await page.getByRole('button', { name: new RegExp(`^${label} `) }).click();
    await page.getByRole('listbox').waitFor();
    await page.keyboard.press('Escape');
  }
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto(`${base}/?rd_view=knowledge`);
  await page.getByRole('heading', { name: '知识管理', exact: true }).waitFor();
  await page.getByLabel('搜索知识管理记录', { exact: true }).waitFor();
  assert.equal(await page.locator('.rd-management-filter').count(), 0);
  await snap('knowledge-desktop.png');
  await page.goto(`${base}/?rd_view=workspace`);
  await page.getByRole('heading', { name: '本地 Workspace', exact: true }).waitFor();
  await page.locator('.rd-workspace-tools').scrollIntoViewIfNeeded();
  const workspaceSearch = await page.locator('.rd-workspace-tools .rd-search').boundingBox();
  const workspaceSelect = await page.locator('.rd-workspace-tools .select-trigger').boundingBox();
  assert(Math.abs(workspaceSearch.y - workspaceSelect.y) <= 1 && Math.abs(workspaceSearch.height - workspaceSelect.height) <= 1, 'workspace filters share a row and height on desktop');
  await snap('workspace-desktop.png');
  await page.setViewportSize({ width: 390, height: 520 });
  await page.locator('.rd-workspace-tools').scrollIntoViewIfNeeded();
  const workspaceNarrowSearch = await page.locator('.rd-workspace-tools .rd-search').boundingBox();
  const workspaceNarrowSelect = await page.locator('.rd-workspace-tools .select-trigger').boundingBox();
  assert(Math.abs(workspaceNarrowSearch.width - workspaceNarrowSelect.width) <= 1 && workspaceNarrowSelect.y >= workspaceNarrowSearch.y + workspaceNarrowSearch.height, 'workspace mobile filters stack at full width');
  assert(await page.locator('.rd-application-shell').evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'workspace remains within the viewport');
  await snap('workspace-mobile.png');
  await page.getByRole('button', { name: '资源目录类型', exact: true }).click();
  await page.getByRole('listbox').waitFor();
  await page.keyboard.press('Escape');
  assert.deepEqual(errors, []);
  assert.deepEqual(writes, []);
  if (output) await writeFile(join(output, 'layout-receipt.json'), JSON.stringify({ passed: true, mocked: false, measurements, errors, writes }, null, 2));
  console.log(JSON.stringify({ passed: true, mocked: false, measurements, errors, writes }));
} finally { await browser.close(); }
