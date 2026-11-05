/** URL restoration and edit-preservation checks; every API request uses isolated fixtures. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'runtime/workflow-template-location';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1500, height: 980 } });
page.setDefaultTimeout(15000);
const errors = [], unexpected = [], requests = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
const fixed = (id, version, category = 'research') => ({
  id, version, category, title: id === 'fixture-a' ? '固定模板甲 V' + version : '固定模板乙',
  head_version: '2', available_versions: ['2', '1'], status: 'published', digest: id + '-' + version,
  publication_revision: 1, product_route: 'modification',
  graph: { nodes: [{ id: 'taskbook', title: '研制任务书策划', role: version === '1' ? '研发工程师' : '质量工程师', position: { x: 20, y: 20 }, deliverables: ['任务书'] }], edges: [] },
});
const html = `<!doctype html><html lang="zh-CN"><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><div id="fixture"></div><script type="module">
const refresh = await import('/@react-refresh'); refresh.default.injectIntoGlobalHook(window);
window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => type => type; window.__vite_plugin_react_preamble_installed__ = true;
const React = (await import('/node_modules/.vite/deps/react.js')).default;
const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
const { WorkflowTemplateWorkbench } = await import('/src/features/rd/WorkflowTemplateWorkbench.tsx');
const { PlatformTheme } = await import('/src/components/ui/PlatformTheme.tsx');
for (const css of ['/src/styles.css','/src/features/rd/rd.css','/src/features/rd/rdApplicationShell.css']) await import(css);
createRoot(document.getElementById('fixture')).render(React.createElement(PlatformTheme, null, React.createElement('main', { className: 'rd-page-content' }, React.createElement(WorkflowTemplateWorkbench, { onOpenCase: () => {} }))));
</script></body></html>`;
await page.route(url => url.pathname === '/flows', route => route.fulfill({ contentType: 'text/html', body: html }));
await page.route('**/api/**', route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname;
  requests.push({ path, search: url.search, method: request.method() });
  const json = data => route.fulfill({ json: data });
  if (request.method() !== 'GET') { unexpected.push(path); return route.fulfill({ status: 500, json: { error: '本测试不允许写入' } }); }
  if (path === '/api/rd/session') return json({ actor_id: 'local:fixture-client', local_mode: true });
  if (path === '/api/rd/governance/session') return json({ can_edit_workflows: true, can_publish_workflows: true });
  if (path === '/api/rd/catalog/items') return json({ items: [], total_pages: 1, page: 1, total: 0, page_size: 5 });
  if (path === '/api/rd/workflow-templates') {
    const pageNumber = Number(url.searchParams.get('page') || 1);
    const category = url.searchParams.get('category');
    return json({ items: [fixed(pageNumber === 2 ? 'fixture-a' : 'fixture-b', '2', category)], total: 2, total_pages: 2, page: pageNumber, page_size: 1 });
  }
  if (path.endsWith('/history')) {
    const pageNumber = Number(url.searchParams.get('page') || 1);
    return json({ items: [fixed('fixture-a', pageNumber === 2 ? '1' : '2')], events: [], usages: [], total: 2, total_pages: 2, page: pageNumber, page_size: 1 });
  }
  const match = path.match(/^\/api\/rd\/workflow-templates\/([^/]+)\/([^/]+)$/);
  if (match) {
    if (!['fixture-a','fixture-b'].includes(match[1]) || !['1','2','latest'].includes(match[2])) return route.fulfill({ status: 404, json: { error: '指定流程模板或版本不存在' } });
    return json(fixed(match[1], match[2] === 'latest' ? '2' : match[2]));
  }
  unexpected.push(path); return route.fulfill({ status: 500, json: { error: '未模拟的请求' } });
});
const params = () => new URL(page.url()).searchParams;
const select = async (label, option) => { await page.getByRole('combobox', { name: label, exact: true }).press('ArrowDown'); await page.getByRole('option', { name: option, exact: true }).click(); };
const initial = '/flows?workflow_category=research&workflow_q=固定&workflow_page=2&workflow_item=fixture-a&workflow_version=1&workflow_detail=history&workflow_history_page=2&workflow_compare=2';
try {
  await page.goto(base + initial);
  await page.getByRole('heading', { name: '固定模板甲 V1', exact: true }).waitFor();
  await page.locator('.rd-template-diff-list').waitFor();
  assert.equal(await page.getByLabel('查找流程模板').inputValue(), '固定');
  assert.equal(await page.getByRole('button', { name: '版本与回溯', exact: true }).getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('.rd-template-list .rd-template-pagination').innerText(), '上一页\n2/2\n下一页');
  assert((await page.locator('.rd-template-history .rd-template-pagination').innerText()).includes('2/2'));
  assert((await page.locator('.rd-template-diff-list').innerText()).includes('质量工程师'));
  await page.reload();
  await page.locator('.rd-template-diff-list').waitFor();
  await page.getByRole('heading', { name: '固定模板甲 V1', exact: true }).waitFor();
  assert.equal(params().get('workflow_version'), '1');
  assert.equal(params().get('workflow_history_page'), '2');
  assert.equal(params().get('workflow_compare'), '2');
  checks.push('reload restores category, query, directory page, explicit fixed version, history page and comparison');

  await page.getByRole('button', { name: '较新记录', exact: true }).click();
  await page.waitForFunction(() => !new URL(location.href).searchParams.has('workflow_history_page'));
  await page.getByRole('button', { name: '流程画布', exact: true }).click();
  assert.equal(params().has('workflow_detail'), false);
  await select('查看固定版本', 'V2 · 最新修订');
  await page.getByRole('heading', { name: '固定模板甲 V2', exact: true }).waitFor();
  assert.equal(params().get('workflow_version'), '2');
  await page.getByRole('button', { name: '编辑新版本', exact: true }).click();
  await page.getByLabel('流程名称', { exact: true }).fill('仍未保存的画布修改');
  await page.getByRole('button', { name: '版本与回溯', exact: true }).click();
  await page.getByText('当前编辑已保留。这里展示保存过的历史，返回画布可继续修改。', { exact: true }).waitFor();
  await page.getByRole('button', { name: '流程画布', exact: true }).click();
  assert.equal(await page.getByLabel('流程名称', { exact: true }).inputValue(), '仍未保存的画布修改');
  await select('流程用途', '选型阶段流程');
  await page.getByRole('dialog').getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(params().get('workflow_category'), 'research');
  assert.equal(await page.getByLabel('流程名称', { exact: true }).inputValue(), '仍未保存的画布修改');
  await page.getByRole('button', { name: '取消编辑', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '放弃修改', exact: true }).click();
  checks.push('tabs preserve unsaved edits; category switch retains the existing leave guard');

  await page.locator('.rd-template-list').getByRole('button', { name: '上一页', exact: true }).click();
  await page.getByRole('heading', { name: '固定模板乙', exact: true }).waitFor();
  await page.waitForFunction(() => new URL(location.href).searchParams.get('workflow_item') === 'fixture-b');
  assert.equal(params().has('workflow_page'), false);
  assert.equal(params().has('workflow_compare'), false);
  await page.getByLabel('查找流程模板').fill('乙');
  await page.waitForFunction(() => new URL(location.href).searchParams.get('workflow_q') === '乙');
  await page.reload();
  await page.getByRole('heading', { name: '固定模板乙', exact: true }).waitFor();
  assert.equal(await page.getByLabel('查找流程模板').inputValue(), '乙');
  checks.push('directory changes update URL, reset dependent selection state and restore filters on reload');

  await page.goto(base + '/flows?workflow_category=research&workflow_item=missing-template&workflow_version=1');
  await page.getByRole('alert').filter({ hasText: '指定流程模板或版本不存在' }).waitFor();
  assert.equal(await page.locator('.rd-template-detail-head').count(), 0);
  assert.equal(params().get('workflow_item'), 'missing-template');
  await page.getByRole('button', { name: '重试读取', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '指定流程模板或版本不存在' }).waitFor();
  assert.equal(await page.locator('.rd-template-detail-head').count(), 0);
  checks.push('an explicit missing template remains a truthful error and never falls back to the first item');
  await page.goto(base + '/flows?workflow_category=research&workflow_item=fixture-a');
  await page.getByRole('heading', { name: '固定模板甲 V2', exact: true }).waitFor();
  await page.waitForFunction(() => new URL(location.href).searchParams.get('workflow_version') === '2');
  checks.push('an unversioned template URL resolves once and pins the actual returned version');
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
  const receipt = { passed: true, checks, errors, unexpected, actualBusinessWrites: 0 };
  await writeFile(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt));
} catch (error) {
  await page.screenshot({ path: join(output, 'failure.png'), fullPage: true });
  await writeFile(join(output, 'failure.json'), JSON.stringify({ error: error.message, url: page.url(), body: await page.locator('body').innerText(), errors, unexpected, requests }, null, 2));
  throw error;
} finally { await browser.close(); }
