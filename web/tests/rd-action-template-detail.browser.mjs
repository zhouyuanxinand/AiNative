/** Real action directory/detail components; all API traffic is isolated and read-only. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'file:///C:/Users/周园鑫/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'docs/rd-platform/verification/screenshots/2026-11-03-action-template-detail';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(8000);
const errors = [], writes = [], reads = [], checks = [];
let singleFailure = 503;
page.on('pageerror', error => errors.push(error.message));
const single = { id: 'context-team', version: 2, name: '上下文解析专家团', kind: 'team', status: 'published', executable: true, description: '核对项目业务参数' };
const multi = { id: 'taskbook-team', version: 3, name: '任务书编制专家团', kind: 'team', status: 'published', executable: true, description: '已发布的三个执行步骤' };
const membersOnly = { id: 'members-only-team', version: 1, name: '待编排动作模板', kind: 'team', status: 'published', executable: false, description: '仅登记固定成员，尚未配置执行图' };
const singleGraph = { nodes: [{ id: 'resolve', resource_id: 'resolve_context', resource_version: 1 }], edges: [] };
const multiGraph = { nodes: [{ id: 'resolve', resource_id: 'resolve_context', resource_version: 1, position: { x: 0, y: 0 } }, { id: 'generate', action_id: 'generate', action_version: '1', position: { x: 540, y: 0 } }, { id: 'review', resource_id: 'verify', resource_version: 2, title: '复核报告', position: { x: 1080, y: 260 } }], edges: [{ id: 'rg', source: 'resolve', target: 'generate' }, { id: 'gv', source: 'generate', target: 'review' }] };
const catalog = { stages: [], scenarios: [], workpackage_definitions: [], actions: [{ id: 'resolve_context', version: '1', title: '登记上下文' }, { id: 'generate', version: '1', title: '生成研制任务书' }, { id: 'verify', version: '1', title: '旧版校验名称' }] };
await page.route('**/__action-detail-fixture**', route => route.fulfill({ contentType: 'text/html', body: '<html lang="zh-CN"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="fixture"></div></body></html>' }));
await page.route('**/api/**', async route => {
  const request = route.request(), url = new URL(request.url());
  if (!url.pathname.startsWith('/api/')) return route.continue();
  if (request.method() !== 'GET') { writes.push(request.method() + ' ' + url.pathname); return route.fulfill({ status: 500, json: { error: '禁止真实写入' } }); }
  reads.push(url.pathname + url.search);
  if (url.pathname === '/api/rd/session') return route.fulfill({ json: { actor_id: 'local:action-fixture', local_mode: true } });
  if (url.pathname === '/api/rd/catalog/items') {
    const p = Number(url.searchParams.get('page') || 1), q = url.searchParams.get('q') || '';
    return route.fulfill({ json: { items: p === 2 && q === '解析' ? [single] : [multi, single], page: p, page_size: 5, total: 6, total_pages: 2 } });
  }
  if (url.pathname === '/api/rd/catalog/resources/context-team/2') {
    if (singleFailure) return route.fulfill({ status: singleFailure, json: { error: singleFailure === 503 ? '固定版本暂时无法读取' : '资源版本不存在或未授权。' } });
    return route.fulfill({ json: { ...single, configuration: { members: [{ resource_id: 'resolve_context', resource_version: 1 }], inputs: ['需求资料'], outputs: ['上下文结果'], execution_graph: singleGraph } } });
  }
  if (url.pathname === '/api/rd/catalog/resources/taskbook-team/3') return route.fulfill({ json: { ...multi, configuration: { members: [{ resource_id: 'resolve_context', resource_version: 1 }, { resource_id: 'generate', resource_version: 1 }, { resource_id: 'verify', resource_version: 2 }], inputs: ['固定来源与业务决定'], outputs: ['任务书与质量报告'], execution_graph: multiGraph } } });
  if (url.pathname === '/api/rd/catalog/resources/resolve_context/1') return route.fulfill({ json: { id: 'resolve_context', version: 1, kind: 'skill', name: '上下文解析', description: '读取固定资料' } });
  if (url.pathname === '/api/rd/catalog/resources/verify/2') return route.fulfill({ json: { id: 'verify', version: 2, kind: 'skill', name: '新版质量核查', description: '固定复核' } });
  if (url.pathname === '/api/rd/catalog/resources/members-only-team/1') return route.fulfill({ json: { ...membersOnly, configuration: { members: [{ resource_id: 'resolve_context', resource_version: 1 }], inputs: null, outputs: null, execution_graph: null } } });
  if (url.pathname === '/api/rd/catalog/resources/invalid-team/1') return route.fulfill({ json: { ...membersOnly, id: 'invalid-team', configuration: { members: [], inputs: null, outputs: null, execution_graph: { nodes: 'invalid', edges: [] } } } });
  return route.fulfill({ status: 404, json: { error: '资源版本不存在或未授权。' } });
});
async function open(query = 'flow_tab=actions&flow_q=解析&flow_page=2') {
  await page.goto(base + '/__action-detail-fixture?' + query);
  await page.evaluate(async catalog => {
    const refresh = await import('/@react-refresh'); refresh.default.injectIntoGlobalHook(window); window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => type => type; window.__vite_plugin_react_preamble_installed__ = true;
    const React = (await import('/node_modules/.vite/deps/react.js')).default;
    const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
    const { FlowManagement } = await import('/src/features/rd/FlowManagement.tsx');
    const { PlatformTheme } = await import('/src/components/ui/PlatformTheme.tsx');
    for (const css of ['/src/styles.css', '/src/features/rd/rd.css', '/src/features/rd/rdApplicationShell.css']) await import(css);
    createRoot(document.getElementById('fixture')).render(React.createElement(PlatformTheme, null, React.createElement('main', { className: 'rd-shell rd-application-shell', style: { display: 'block', padding: '24px' } }, React.createElement(FlowManagement, { catalog, catalogLoading: false, catalogError: '', projects: [], onRefreshCatalog() {}, onOpenCase() {}, onOpenWorkspace() {} }))));
  }, catalog);
}
const snap = name => page.screenshot({ path: join(output, name), animations: 'disabled' });
async function fits() {
  await page.waitForFunction(() => {
    const canvas = document.querySelector('.rd-action-detail .rd-graph-scroll');
    if (!canvas) return false;
    const viewport = canvas.getBoundingClientRect();
    return [...canvas.querySelectorAll('.rd-graph-node')].every(node => { const rect = node.getBoundingClientRect(); return rect.left >= viewport.left - 1 && rect.right <= viewport.right + 1 && rect.top >= viewport.top - 1 && rect.bottom <= viewport.bottom + 1; });
  });
}
try {
  await open();
  await page.getByRole('button', { name: '打开上下文解析专家团画布', exact: true }).waitFor();
  assert.equal(await page.locator('.rd-flow-card-grid .rd-graph-editor').count(), 0);
  assert(await page.locator('.rd-action-card-button').first().evaluate(button => {
    const bounds = button.getBoundingClientRect();
    return [...button.children].every(child => { const rect = child.getBoundingClientRect(); return rect.top >= bounds.top - 1 && rect.bottom <= bounds.bottom + 1; });
  }), 'action card heading, description and entry stay inside the clickable card');
  await snap('00-action-directory.png');
  await page.getByRole('button', { name: '打开上下文解析专家团画布', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '固定版本暂时无法读取' }).waitFor();
  assert.equal(await page.locator('.rd-flow-card-grid').count(), 0);
  assert.equal(new URL(page.url()).searchParams.get('flow_version'), '2');
  assert.equal(new URL(page.url()).searchParams.get('flow_page'), '2');
  singleFailure = 0;
  await page.getByRole('button', { name: '重试读取动作模板', exact: true }).click();
  await page.getByRole('button', { name: '上下文解析，选择节点', exact: true }).waitFor();
  await page.getByText('单动作封装 · 1 个执行步骤', { exact: true }).waitFor();
  assert.equal(await page.locator('.rd-action-detail .rd-graph-node').count(), 1);
  assert.equal(await page.locator('.rd-action-detail .rd-graph-node').getByText('执行步骤', { exact: true }).count(), 1);
  assert.equal(await page.getByRole('button', { name: '新增节点', exact: true }).count(), 0);
  await fits(); await snap('01-single-action-full-canvas.png');
  await page.getByRole('button', { name: '返回动作模板', exact: true }).click();
  assert.equal(await page.getByLabel('搜索动作模板', { exact: true }).inputValue(), '解析');
  assert.equal(new URL(page.url()).searchParams.get('flow_page'), '2');
  assert.equal(new URL(page.url()).searchParams.get('flow_item'), 'context-team');
  assert.equal(new URL(page.url()).searchParams.get('flow_version'), '2');
  await page.getByRole('button', { name: '打开上下文解析专家团画布', exact: true }).waitFor();
  await page.getByText('单动作封装 · 1 个执行步骤', { exact: true }).waitFor();
  checks.push('card opens fixed-version full canvas; retry succeeds; single action stays single; return preserves query, page and selection');
  await page.getByRole('button', { name: '清空搜索', exact: true }).click();
  await page.getByRole('button', { name: '打开任务书编制专家团画布', exact: true }).click();
  await page.getByRole('button', { name: '生成研制任务书，选择节点', exact: true }).waitFor();
  assert.deepEqual(await page.locator('.rd-action-detail .rd-graph-node strong').allTextContents(), ['上下文解析', '生成研制任务书', '复核报告']);
  await page.getByText('多步骤编排 · 3 个执行步骤', { exact: true }).waitFor();
  assert.equal(await page.getByText('待配置负责角色', { exact: true }).count(), 0);
  await fits(); await snap('02-multi-action-full-canvas.png');
  await page.getByText('固定成员与输入输出', { exact: true }).click();
  await page.getByText('新版质量核查', { exact: true }).waitFor();
  assert.equal(await page.getByText('旧版校验名称', { exact: true }).count(), 0);
  await page.getByText('固定成员与输入输出', { exact: true }).click();
  await page.setViewportSize({ width: 390, height: 760 }); await fits();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await snap('03-action-canvas-narrow.png');
  checks.push('multi-step graph uses saved or fixed-version member titles, registered action fallback, and auto-fit desktop/narrow layouts');
  await page.setViewportSize({ width: 1440, height: 1000 });
  singleFailure = 403;
  await open('flow_tab=actions&flow_item=context-team&flow_version=2&flow_detail=canvas&flow_q=解析&flow_page=2');
  await page.getByRole('alert').filter({ hasText: '未授权' }).waitFor();
  assert.equal(await page.locator('.rd-action-detail .rd-graph-node').count(), 0);
  await page.getByRole('button', { name: '返回动作模板', exact: true }).waitFor();
  await snap('04-detail-permission-error.png');
  checks.push('direct fixed-version URL handles permission failure without stale graph or write requests');
  singleFailure = 0;
  await open();
  const singleCard = page.getByRole('button', { name: '打开上下文解析专家团画布', exact: true });
  await singleCard.waitFor();
  await page.getByLabel('搜索动作模板', { exact: true }).fill('上下文');
  await singleCard.click();
  await page.waitForTimeout(450); // Let the previous 300ms search debounce fire if it was not cancelled.
  await page.getByRole('button', { name: '上下文解析，选择节点', exact: true }).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('flow_q'), '上下文');
  assert.equal(new URL(page.url()).searchParams.get('flow_page'), '1');
  assert.equal(new URL(page.url()).searchParams.get('flow_item'), 'context-team');
  await page.getByRole('button', { name: '返回动作模板', exact: true }).click();
  assert.equal(await page.getByLabel('搜索动作模板', { exact: true }).inputValue(), '上下文');
  assert.equal(new URL(page.url()).searchParams.get('flow_page'), '1');
  checks.push('opening a card during pending search commits search and selection atomically; detail survives debounce and return uses page 1');
  await open('flow_tab=actions&flow_item=members-only-team&flow_version=1&flow_detail=canvas');
  await page.getByText('尚无执行图', { exact: true }).waitFor();
  await page.getByText('尚未接入执行能力', { exact: true }).waitFor();
  assert.equal(await page.getByRole('alert').count(), 0);
  assert.equal(await page.locator('.rd-action-detail .rd-graph-node').count(), 0);
  await page.getByText('固定成员与输入输出', { exact: true }).click();
  await page.getByText('上下文解析', { exact: true }).waitFor();
  assert.equal(await page.getByText('未提供说明。', { exact: true }).count(), 2);
  await snap('05-members-only-empty-graph.png');
  await open('flow_tab=actions&flow_item=invalid-team&flow_version=1&flow_detail=canvas');
  await page.getByRole('alert').filter({ hasText: '执行图暂时无法展示' }).waitFor();
  assert.equal(await page.getByText('尚无执行图', { exact: true }).count(), 0);
  checks.push('members-only unbound template accepts null optional projection without fake graph; malformed nonempty graph remains an error');
  assert.deepEqual(errors, []); assert.deepEqual(writes, []);
  assert(reads.some(path => path === '/api/rd/catalog/resources/context-team/2'));
  assert(!reads.some(path => path.includes('/latest')));
  const receipt = { passed: true, isolated: true, actualWrites: 0, checks, errors, writes, fixedDetailReads: reads.filter(path => path.includes('/catalog/resources/')) };
  await writeFile(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2)); console.log(JSON.stringify(receipt));
} catch (error) { await snap('failure.png'); console.log((await page.locator('body').innerText()).slice(0, 7000)); throw error; } finally { await browser.close(); }
