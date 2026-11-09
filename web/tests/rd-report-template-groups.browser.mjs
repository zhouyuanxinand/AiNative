/** Product-grouped report templates with a complete isolated directory; no real downloads or writes. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || path.resolve('runtime/rd-report-template-groups');
await mkdir(output, { recursive: true });
const stamp = '2026-11-06T02:00:00Z';
const productName = index => `隔离产品 ${String(index).padStart(2, '0')}`;
const productId = index => `product-${String(index).padStart(2, '0')}`;
function template(index, domain, domainName, filename) {
  return { product_type_id: productId(index), product_type: productName(index), product_domain_id: domain, product_domain: domainName,
    template: filename, filename, version: `V${index}.${domain}`, version_id: `${index}-${domain}`, updated_at: stamp,
    sha256: `${index}-${domain}`, revision: `${index}-${domain}` };
}
const fullDirectory = [
  template(1, 'military', '军品', '通用任务书.docx'),
  ...Array.from({ length: 12 }, (_, index) => template(index + 2, 'military', '军品', `产品${index + 2}任务书.docx`)),
  // Deliberately separated in the response, with repeated filenames across domains.
  template(1, 'civil', '民品', '通用任务书.docx'),
  template(1, 'aviation', '航空', '航空任务书专用.docx'),
];
const action = { id: 'action-fixture', title: '动作隔离目录', name: '动作隔离目录', kind: 'team', version: '1', executable: true, status: 'published', description: '只验证报告目录切换后的状态隔离。' };
let mode = 'full', holdNext = false, releaseHeld, startedHeld, heldFinished;
let heldPayload;
const reads = [], writes = [], pageErrors = [], fixtureErrors = [], checks = [];
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
page.on('pageerror', error => pageErrors.push(error.message));
const panel = () => page.getByRole('tabpanel', { name: '报告模板', exact: true });
const cards = () => panel().locator('.rd-report-product-card');
const card = index => cards().filter({ hasText: productName(index) });
const openCard = index => panel().getByRole('button', { name: `查看${productName(index)}报告模板`, exact: true });
const search = () => page.getByLabel('搜索报告模板', { exact: true });
const back = () => page.getByRole('button', { name: '返回产品类型', exact: true });
const productFilter = () => page.getByRole('combobox', { name: '筛选产品类型', exact: true });
const downloads = () => panel().getByRole('link', { name: /下载/ });
const url = patch => {
  const value = new URL('/?rd_view=flows&flow_tab=reports', base);
  for (const [key, item] of Object.entries(patch || {})) value.searchParams.set('flow_' + key, item);
  return value.href;
};
const currentParam = name => new URL(page.url()).searchParams.get('flow_' + name);
async function capture(name) { await page.screenshot({ path: path.join(output, name + '.png') }); }
async function chooseProduct(name) {
  await productFilter().locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').click();
  await page.getByRole('option', { name, exact: true }).click();
}
async function noOverflow() {
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'document fits the viewport');
  assert(await page.locator('.rd-application-shell').evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'application shell fits the viewport');
}
async function verifyProductOne() {
  await page.getByRole('heading', { name: productName(1), exact: true }).waitFor();
  assert.equal(await downloads().count(), 3, 'details retain all mappings, including duplicate filenames across domains');
  assert.deepEqual((await downloads().evaluateAll(links => links.map(link => link.getAttribute('href')))).sort(),
    ['aviation', 'civil', 'military'].map(domain => `/api/templates/${productId(1)}/${domain}/download`).sort(), 'download URLs retain the existing product/domain authorization path');
  for (const domain of ['军品', '民品', '航空']) await panel().getByRole('heading', { name: domain, exact: true }).waitFor();
  assert.equal(await panel().getByText('通用任务书.docx', { exact: true }).count(), 2);
  assert.equal(await search().count(), 0, 'the product detail does not display the directory search');
}
try {
  await page.route('**/api/**', async route => {
    const request = route.request(), requestUrl = new URL(request.url()), pathname = requestUrl.pathname;
    if (!pathname.startsWith('/api/')) return route.continue();
    try {
      if (!['GET', 'HEAD'].includes(request.method())) { writes.push({ method: request.method(), pathname }); throw new Error('Unexpected API write'); }
      if (pathname === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
      if (pathname === '/api/rd/session') return route.fulfill({ json: { actor_id: 'report-fixture', local_mode: true } });
      if (pathname === '/api/rd/projects') return route.fulfill({ json: { projects: [] } });
      if (pathname === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [], actions: [action], workpackage_definitions: [] } });
      if (pathname === '/api/rd/assistant/weather') return route.fulfill({ status: 503, json: { error: '隔离测试不读取天气。' } });
      if (pathname === '/api/templates') {
        reads.push(requestUrl.href);
        assert.equal(requestUrl.search, '', 'group counts use the complete directory, never a server page');
        if (holdNext) {
          holdNext = false;
          const payload = structuredClone(heldPayload);
          await new Promise(resolve => { releaseHeld = resolve; startedHeld(); });
          await route.fulfill({ json: payload }); heldFinished(); return;
        }
        if (mode === 'error') return route.fulfill({ status: 503, json: { error: '隔离目录暂不可用' } });
        return route.fulfill({ json: mode === 'empty' ? [] : fullDirectory });
      }
      if (pathname === '/api/rd/catalog/items') {
        assert.notEqual(requestUrl.searchParams.get('category'), 'reports', 'report grouping cannot use the paginated catalog endpoint');
        return route.fulfill({ json: { items: [action], total: 1, total_pages: 1, page: 1, page_size: 5 } });
      }
      throw new Error(`Unexpected API read: ${pathname}`);
    } catch (error) { fixtureErrors.push(error.message); return route.fulfill({ status: 500, json: { error: error.message } }); }
  });

  await page.goto(url()); await cards().first().waitFor();
  assert.equal(await cards().count(), 12, 'product pagination uses twelve complete groups');
  await card(1).getByText('军品 / 民品 / 航空', { exact: true }).waitFor();
  assert.match(await card(1).innerText(), /3\s*(?:份|个|项)\s*模板|模板\s*3/);
  assert.equal(await downloads().count(), 0, 'individual file downloads belong to product details');
  await openCard(1).focus(); await page.keyboard.press('Enter');
  await verifyProductOne();
  assert.equal(currentParam('item'), productId(1));
  await capture('01-product-detail-desktop');
  await back().click(); await cards().first().waitFor();
  checks.push('complete mappings group into product cards; keyboard opens domain sections and preserves download URLs');

  await search().fill('航空任务书专用'); await search().press('Enter');
  await page.waitForFunction(() => new URL(location.href).searchParams.get('flow_q') === '航空任务书专用');
  assert.equal(await cards().count(), 1);
  assert.match(await card(1).innerText(), /3\s*(?:份|个|项)\s*模板|模板\s*3/, 'searching a single filename retains the complete group count');
  await openCard(1).click(); await verifyProductOne();
  await back().click();
  assert.equal(await search().inputValue(), '航空任务书专用');
  assert.equal(await cards().count(), 1);
  checks.push('filename search returns complete product groups and survives detail return');

  await search().fill('隔离产品'); await search().press('Enter');
  await page.waitForFunction(() => new URL(location.href).searchParams.get('flow_q') === '隔离产品');
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await card(13).waitFor(); assert.equal(await cards().count(), 1);
  await openCard(13).click(); await back().waitFor();
  assert.equal(currentParam('page'), '2'); assert.equal(currentParam('q'), '隔离产品');
  await page.reload(); await back().waitFor();
  await page.getByRole('heading', { name: productName(13), exact: true }).waitFor();
  assert.equal(await downloads().count(), 1);
  await back().click(); await card(13).waitFor();
  assert.equal(currentParam('page'), '2'); assert.equal(await search().inputValue(), '隔离产品');
  checks.push('second-page product detail survives reload and returns to the same query and page');

  await chooseProduct(productName(13));
  await card(13).waitFor();
  assert.equal(await cards().count(), 1, 'product selection combines with the existing search');
  assert.equal(currentParam('product'), productId(13));
  assert.equal(currentParam('page') || '1', '1', 'selecting a product resets the second directory page');
  assert.equal(currentParam('q'), '隔离产品');
  await page.reload(); await card(13).waitFor();
  assert.equal(currentParam('product'), productId(13));
  assert.equal(await productFilter().locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').innerText(), productName(13));
  await openCard(13).click(); await back().waitFor();
  await page.reload(); await back().waitFor();
  assert.equal(currentParam('product'), productId(13));
  await back().click(); await card(13).waitFor();
  assert.equal(currentParam('product'), productId(13));
  assert.equal(await search().inputValue(), '隔离产品');
  assert.equal(await cards().count(), 1);
  await search().fill('产品13任务书'); await search().press('Enter');
  await page.waitForFunction(() => new URL(location.href).searchParams.get('flow_q') === '产品13任务书');
  assert.equal(await cards().count(), 1);
  await search().fill('航空任务书专用'); await search().press('Enter');
  await page.waitForFunction(() => new URL(location.href).searchParams.get('flow_q') === '航空任务书专用');
  await page.getByRole('button', { name: '重置筛选', exact: true }).waitFor();
  assert.equal(await cards().count(), 0, 'search and product filters intersect rather than replacing one another');
  await page.getByRole('button', { name: '重置筛选', exact: true }).click();
  await cards().first().waitFor();
  assert.equal(await search().inputValue(), '');
  assert.equal(currentParam('product') || '', '');
  assert.equal(currentParam('q') || '', '');
  assert.equal(await cards().count(), 12);
  await chooseProduct(productName(13)); await card(13).waitFor();
  assert.equal(await cards().count(), 1);
  await chooseProduct('全部产品类型'); await cards().first().waitFor();
  assert.equal(currentParam('product') || '', '');
  assert.equal(await cards().count(), 12);
  checks.push('product dropdown resets pagination, persists through reload and detail return, combines with search, and clears back to all products');

  await page.goto(url({ item: productId(1) })); await verifyProductOne();
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await panel().scrollIntoViewIfNeeded(); await noOverflow();
    await capture(`02-detail-mobile-${width}`);
    await back().click(); await cards().first().waitFor();
    await card(1).scrollIntoViewIfNeeded(); await noOverflow();
    await capture(`03-cards-mobile-${width}`);
    await openCard(1).click(); await verifyProductOne();
  }
  checks.push('product cards and detail remain usable without horizontal overflow at 390px and 320px');

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(url({ item: 'missing-product', q: '隔离产品', page: '2' }));
  await back().waitFor();
  await panel().getByRole('heading', { name: '该产品暂无可用模板', exact: true }).waitFor();
  assert.equal(await downloads().count(), 0);
  await back().click(); await card(13).waitFor();
  assert.equal(await search().inputValue(), '隔离产品'); assert.equal(currentParam('page'), '2');
  checks.push('missing product detail has an explicit return to the preserved directory context');

  await page.goto(url()); await cards().first().waitFor();
  mode = 'empty'; await page.getByRole('button', { name: '刷新目录', exact: true }).click();
  await cards().first().waitFor({ state: 'hidden' });
  await panel().getByText(/暂无.*模板|暂无.*记录/).waitFor();
  assert.equal(await cards().count(), 0);
  mode = 'error'; await page.getByRole('button', { name: '刷新目录', exact: true }).click();
  await panel().getByRole('alert').filter({ hasText: '隔离目录暂不可用' }).waitFor();
  mode = 'full'; await panel().getByRole('button', { name: /重试读取|重新读取|重试/ }).click();
  await cards().first().waitFor(); assert.equal(await cards().count(), 12);
  checks.push('empty and failed directory loads offer refresh or retry and recover full groups');

  holdNext = true;
  heldPayload = [{ ...fullDirectory[0], product_type_id: 'stale-product', product_type: '迟到污染产品' }];
  const heldStarted = new Promise(resolve => { startedHeld = resolve; });
  const heldComplete = new Promise(resolve => { heldFinished = resolve; });
  await page.getByRole('button', { name: '刷新目录', exact: true }).click(); await heldStarted;
  await page.getByRole('tab', { name: '动作模板', exact: true }).click();
  await page.getByRole('button', { name: '打开动作隔离目录画布', exact: true }).waitFor();
  releaseHeld(); await heldComplete;
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await page.getByRole('tab', { name: '动作模板', exact: true }).getAttribute('aria-selected'), 'true');
  assert.equal(await page.getByText('迟到污染产品', { exact: true }).count(), 0);
  await page.getByRole('tab', { name: '报告模板', exact: true }).click(); await cards().first().waitFor();
  assert.equal(await cards().count(), 12); assert.equal(await page.getByText('迟到污染产品', { exact: true }).count(), 0);
  checks.push('late report reads cannot overwrite another tab or a fresh report directory');
  assert.equal(writes.length, 0); assert.equal(fixtureErrors.length, 0); assert.equal(pageErrors.length, 0);
  await capture('04-final-product-cards');
} catch (error) {
  pageErrors.push(error.stack || String(error));
  await capture('failure').catch(() => {});
} finally {
  const receipt = { passed: checks.length === 8 && !pageErrors.length && !fixtureErrors.length && !writes.length, checks, pageErrors, fixtureErrors, templateReads: reads, writes };
  await writeFile(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt, null, 2));
  await browser.close();
  if (!receipt.passed) process.exitCode = 1;
}
