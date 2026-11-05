import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const output = process.env.SCREENSHOT_DIR || 'runtime/rd-project-directory';
await mkdir(output, { recursive: true });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const errors = [], unexpected = [], writes = [], checks = [];
const stamp = index => `2026-11-0${index + 1}T08:00:00Z`;
const workflow = status => ({ id: 'taskbook-generation', title: '任务书编制流程', version: '1', template_id: 'taskbook-generation', template_version: '1', template_digest: 'fixed', category: 'project', status: 'published', graph: { nodes: [{ id: 'input', title: '资料受理', role: '工程师', deliverables: [], position: { x: 0, y: 0 } }], edges: [] }, node_states: { input: status === 'completed' ? 'completed' : 'pending' } });
const flow = (index, status) => ({ id: `flow-${index}`, title: '研发流程', scenario_id: 'taskbook', stage: 'input', status: 'active', context: {}, input_revision: 1, sources: [], source_selection: {}, requirements: [], workpackages: [], decisions: [], clarifications: [], comparisons: [], deliveries: [], reuse_candidates: [], product_route: null, composition_route: null,
  workflow_templates: { project: workflow(status) }, project_workflow_status: { status, terminal_node_id: 'input', ...(status === 'blocked' ? { reason: '等待确认来源' } : {}) } });
const projects = ['empty', 'pending', 'completed', 'blocked', 'pending', 'completed', 'pending'].map((status, index) => ({ id: `p${index}`, title: `项目${index}`, customer_name: '航空客户', product_name: '液冷组件', owner_id: `local:owner${index}`, version: 1, members: [], events: [], cases: status === 'empty' ? [] : [flow(index, status)], updated_at: stamp(index), can_delete: false }));
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
page.on('pageerror', error => errors.push(error.message));
await page.route('**/api/**', route => {
  const request = route.request(), path = new URL(request.url()).pathname;
  if (!path.startsWith('/api/')) return route.continue();
  if (request.method() !== 'GET') { writes.push(path); return route.fulfill({ status: 500, json: { error: 'Unexpected write' } }); }
  if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
  if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'local:owner', local_mode: true } });
  if (path === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [], actions: [], workpackage_definitions: [] } });
  if (path === '/api/rd/projects') return route.fulfill({ json: { projects } });
  const project = projects.find(project => path === '/api/rd/projects/' + project.id);
  if (project) return route.fulfill({ json: project });
  if (path === '/api/rd/assistant/weather') return route.fulfill({ json: { status: 'unavailable', location: '隔离验证' } });
  unexpected.push(path); return route.fulfill({ status: 503, json: { error: 'Unexpected request' } });
});
const select = async (label, option) => { await page.locator('.ant-select').filter({ has: page.getByRole('combobox', { name: label, exact: true }) }).locator('.ant-select-selector').click(); await page.getByRole('option', { name: option, exact: true }).click(); };
const cardNames = () => page.locator('.rd-project-overview-card h3').allTextContents();
try {
  await page.goto(base + '/projects');
  await page.locator('.rd-project-overview-card').first().waitFor();
  assert.deepEqual(await cardNames(), ['项目6', '项目5', '项目4', '项目3', '项目2']);
  assert.equal(await page.locator('.rd-sidebar-case').count(), 0);
  assert.equal(await page.locator('.rd-project-overview-meta dd').first().innerText(), '本地用户');
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await page.waitForURL(/page=2/);
  assert.deepEqual(await cardNames(), ['项目1', '项目0']);
  checks.push('recent-update ordering, bounded paging, friendly local owner and no empty sidebar context');

  await select('状态', '需关注');
  await page.waitForURL(/status=attention/);
  assert.deepEqual(await cardNames(), ['项目3']);
  assert.equal(new URL(page.url()).searchParams.has('page'), false);
  await select('状态', '已完成');
  await page.waitForURL(/status=completed/);
  assert.deepEqual(await cardNames(), ['项目5', '项目2']);
  await select('排序', '按项目名称');
  await page.waitForURL(/sort=name/);
  assert.deepEqual(await cardNames(), ['项目2', '项目5']);
  await page.getByRole('button', { name: '紧凑列表', exact: true }).click();
  await page.locator('.rd-project-table-scroll').waitFor();
  const beforeDetail = page.url();
  await page.getByRole('button', { name: '项目2', exact: true }).click();
  await page.waitForURL('**/projects/p2');
  await page.getByRole('heading', { name: '项目2', exact: true }).waitFor();
  await page.getByRole('navigation', { name: '当前位置' }).getByRole('button', { name: '项目空间', exact: true }).click();
  await page.waitForURL(beforeDetail);
  await page.reload();
  await page.locator('.rd-project-table-scroll').waitFor();
  assert.equal(await page.locator('.rd-project-table-scroll .ant-table-tbody > tr').count(), 2);
  checks.push('status and sort reset paging; compact view and all directory choices survive detail return and reload');

  await page.getByRole('textbox', { name: '搜索项目、客户、产品或业务流程' }).fill('无匹配');
  await page.getByRole('heading', { name: '没有找到匹配的项目' }).waitFor();
  await page.getByRole('button', { name: '清除筛选', exact: true }).click();
  await page.waitForFunction(() => !new URL(location.href).searchParams.has('status') && !new URL(location.href).searchParams.has('q'));
  assert.equal(await page.getByRole('textbox', { name: '搜索项目、客户、产品或业务流程' }).inputValue(), '');
  assert.equal(new URL(page.url()).searchParams.get('layout'), 'list');
  await page.screenshot({ path: join(output, 'desktop-list.png') });
  await page.getByRole('button', { name: '卡片', exact: true }).click();
  await page.locator('.rd-project-overview-card').first().waitFor();
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    assert(await page.locator('.rd-application-shell').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
    assert((await page.locator('.rd-page-content').boundingBox()).y < 270);
    await page.screenshot({ path: join(output, `mobile-${width}.png`) });
  }
  checks.push('no-results can clear filters without losing layout; 390/320px shell has no overflow and earlier content');
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, []); assert.deepEqual(writes, []);
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ passed: true, checks, errors, unexpected, writes }, null, 2));
  console.log(JSON.stringify({ passed: true, checks }));
} finally { await browser.close(); }
