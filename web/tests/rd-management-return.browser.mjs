/** Management list restoration and main navigation; only isolated read responses. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'runtime/management-return/after';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
const pageErrors = [], unexpected = [], writes = [], checks = [];
let checkpoint = 'setup';
page.on('pageerror', error => pageErrors.push(error.message));
const stamp = '2026-11-05T04:00:00Z';
const workflow = { id: 'return-template', version: '1', template_id: 'return-template', template_version: '1', template_digest: 'return-fixed', digest: 'return-fixed', title: '返回验证流程', category: 'project', status: 'published', publication_revision: 1,
  graph: { nodes: [{ id: 'input', title: '资料受理', role: '研发工程师', deliverables: [], position: { x: 0, y: 0 } }], edges: [] }, node_states: { input: 'pending' } };
const cases = Array.from({ length: 12 }, (_, index) => ({ id: 'return-case-' + index, title: '返回筛选工作 ' + String(index + 1).padStart(2, '0'), scenario_id: 'taskbook', stage: 'input', status: index % 2 ? 'completed' : 'active', input_revision: 1,
  context: { product_type: 'liquid_cooling_pipeline', product_domain: 'military' }, sources: [], source_selection: {}, requirements: [], decisions: [], clarifications: [], comparisons: [], workpackages: [], product_route: null, composition_route: null,
  workflow_templates: { project: workflow }, project_workflow_status: { status: index % 2 ? 'completed' : 'pending', terminal_node_id: 'input' },
  business_lifecycle: { policy_version: 'v2', rd_activation_state: 'not_started', local_review_enabled: true, can_record_decision: true, can_confirm_requirements: true },
  reuse_candidates: [{ id: 'candidate-' + index, title: '复用返回候选 ' + String(index + 1).padStart(2, '0'), content: '已保存的隔离复用内容 ' + index, source_ids: [], input_revision: 1, created_at: stamp }],
}));
const project = { id: 'return-project', title: '隔离返回项目', customer_name: '隔离客户', product_name: '液冷管路', owner_id: 'return-owner', members: [], events: [], version: 1, created_at: stamp, updated_at: stamp, cases };
const catalog = { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书', status: 'published' }], project_workflow_templates: [workflow], actions: [], workpackage_definitions: [] };
const emptyDirectory = { items: [], total: 0, page: 1, page_size: 5, total_pages: 1 };
const actionDirectory = Array.from({ length: 6 }, (_, index) => ({ id: 'return-action-' + index, version: 3, name: '固定返回动作 ' + (index + 1), kind: 'team', status: 'published', executable: true, description: '固定版本的隔离动作模板' }));
const fixedAction = actionDirectory[5];
const fixedActionDetail = { ...fixedAction, configuration: { members: [{ resource_id: 'return-check-skill', resource_version: 2 }], inputs: ['固定输入'], outputs: ['核对结果'],
  execution_graph: { nodes: [{ id: 'return-check', title: '固定输入核对', resource_id: 'return-check-skill', resource_version: 2, position: { x: 24, y: 24 } }], edges: [] } } };
const nav = () => page.getByRole('navigation', { name: '研发平台导航', exact: true });
const search = title => page.getByRole('textbox', { name: '搜索' + title + '记录', exact: true });
const range = () => page.locator('.rd-management-page > .rd-pagination > span');
const params = () => new URL(page.url()).searchParams;
const capture = name => page.screenshot({ path: join(output, name + '.png') });
async function show(title) { await page.getByRole('heading', { name: title, level: 1, exact: true }).waitFor(); }
async function module(name, title = name) { await nav().getByRole('button', { name, exact: true }).click(); await show(title); }
async function restored(title, prefix, query, pageNumber) {
  await show(title);
  assert.equal(await search(title).inputValue(), query, 'returning to ' + title + ' restores the committed search');
  assert.equal(params().get(prefix + '_q'), query);
  assert.equal(params().get(prefix + '_page'), String(pageNumber));
}
async function fixedCanvas() {
  const detail = page.getByRole('region', { name: '动作模板完整画布', exact: true });
  await detail.getByRole('heading', { name: fixedAction.name, exact: true }).waitFor();
  await detail.getByRole('button', { name: '固定输入核对，选择节点', exact: true }).waitFor();
  assert(await detail.getByText('固定版本 V3', { exact: true }).isVisible());
  for (const [key, value] of Object.entries({ flow_tab: 'actions', flow_item: fixedAction.id, flow_version: '3', flow_detail: 'canvas', flow_q: '固定返回动作', flow_page: '2' })) {
    assert.equal(params().get(key), value, key + ' preserves the selected fixed action and directory state');
  }
}
try {
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (!['GET', 'HEAD'].includes(request.method())) writes.push({ method: request.method(), path });
    if (request.method() === 'GET') {
      if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
      if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'return-owner', local_mode: true } });
      if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
      if (path === '/api/rd/projects/' + project.id) return route.fulfill({ json: project });
      if (path === '/api/rd/catalog') return route.fulfill({ json: catalog });
      if (path === '/api/rd/catalog/items' && url.searchParams.get('category') === 'actions') {
        const selectedPage = Number(url.searchParams.get('page') || 1), query = url.searchParams.get('q') || '';
        const rows = actionDirectory.filter(action => action.name.includes(query));
        return route.fulfill({ json: { items: rows.slice((selectedPage - 1) * 5, selectedPage * 5), total: rows.length, page: selectedPage, page_size: 5, total_pages: Math.max(1, Math.ceil(rows.length / 5)) } });
      }
      if (path === '/api/rd/catalog/resources/' + fixedAction.id + '/3') return route.fulfill({ json: fixedActionDetail });
      if (path === '/api/rd/catalog/resources/return-check-skill/2') return route.fulfill({ json: { id: 'return-check-skill', version: 2, kind: 'skill', name: '固定输入核对', status: 'published', executable: true } });
      if (['/api/rd/catalog/items', '/api/rd/catalog/resources', '/api/rd/workflow-templates'].includes(path)) return route.fulfill({ json: emptyDirectory });
      if (path === '/api/rd/governance/session') return route.fulfill({ json: { can_edit_workflows: false, can_publish_workflows: false, can_prepare_templates: false, can_review_templates: false, can_publish_templates: false, local_bootstrap: false } });
      if (path === '/api/rd/workspace/session') return route.fulfill({ json: { application_id: 'return-fixture', can_edit_resources: false, can_publish_resources: false, can_manage_application_grants: false, local_bootstrap: false } });
      if (path === '/api/models') return route.fulfill({ json: { success: true, models: [] } });
      if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: 'liquid_cooling_pipeline', label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }] }] } });
      if (path === '/api/rd/assistant/weather') return route.fulfill({ json: { status: 'unavailable', location: '隔离测试', notice: '管理返回测试不读取天气。' } });
      if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: 'input', project_version: 1, input_revision: 1 } } });
    }
    unexpected.push({ method: request.method(), path });
    return route.fulfill({ status: 500, json: { error: '管理返回夹具不允许此请求：' + path } });
  });
  checkpoint = 'management return preserves search, scope and page';
  await page.goto(base + '/?rd_view=management'); await show('研发管理');
  await search('研发管理').fill('返回筛选工作'); await search('研发管理').press('Enter');
  await page.getByRole('combobox', { name: '工作范围', exact: true }).focus();
  await page.getByRole('combobox', { name: '工作范围', exact: true }).press('ArrowDown');
  await page.locator('.ant-select-item-option-content').filter({ hasText: /^已完成案例$/ }).click();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await page.getByText('6–6 / 6 条', { exact: true }).waitFor();
  await page.getByRole('button', { name: '进入工作', exact: false }).click();
  await page.locator('.rd-case-workspace').waitFor();
  assert.equal(params().get('case'), cases[11].id);
  await page.goBack();
  await restored('研发管理', 'management', '返回筛选工作', 2);
  assert.equal(params().get('management_kind'), 'completed');
  assert.equal(await range().innerText(), '6–6 / 6 条');
  assert(await page.locator('.rd-management-filter').getByText('已完成案例', { exact: true }).isVisible());
  await capture('01-management-return-1440');
  await page.goForward(); await page.locator('.rd-case-workspace').waitFor();
  assert.equal(params().get('case'), cases[11].id);
  await page.goBack(); await restored('研发管理', 'management', '返回筛选工作', 2);
  await page.reload(); await restored('研发管理', 'management', '返回筛选工作', 2);
  await page.getByText('6–6 / 6 条', { exact: true }).waitFor();
  checks.push('研发管理进入案例后Back/Forward及刷新保留搜索、已完成范围和第2页');

  checkpoint = 'knowledge return preserves an independent search and page';
  await module('知识管理');
  assert.equal(await search('知识管理').inputValue(), '', 'knowledge does not inherit the management query');
  await search('知识管理').fill('复用返回候选'); await search('知识管理').press('Enter');
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await page.getByText('6–10 / 12 条', { exact: true }).waitFor();
  await page.locator('.rd-candidate-row').first().click();
  await page.getByRole('button', { name: '查看所属成果', exact: false }).click();
  await page.locator('.rd-evidence-panel').waitFor();
  assert.equal(params().get('case'), cases[5].id);
  await page.goBack(); await restored('知识管理', 'knowledge', '复用返回候选', 2);
  assert.equal(await range().innerText(), '6–10 / 12 条');
  assert((await page.locator('.rd-candidate-row').first().innerText()).includes('复用返回候选 06'));
  await page.reload(); await restored('知识管理', 'knowledge', '复用返回候选', 2);
  await page.getByText('6–10 / 12 条', { exact: true }).waitFor();
  await capture('02-knowledge-return-1440');
  checks.push('知识管理返回所属成果后保留独立搜索及第2页，刷新保持目录且不串研发管理筛选');

  checkpoint = 'main module Back and Forward traversal';
  const modules = [['我的工作', '我的工作'], ['项目空间', '项目空间'], ['研发管理', '研发管理'], ['流程管理', '流程管理'], ['知识管理', '知识管理'], ['运营管理', '运营管理'], ['资源工作台', '本地 Workspace']];
  for (const [name, title] of modules) await module(name, title);
  await page.getByText('当前为只读获准目录。资源发布与应用授权由服务端分别验证；主站管理员身份不自动获得资源治理权限。', { exact: true }).waitFor();
  for (let index = modules.length - 2; index >= 0; index--) { await page.goBack(); await show(modules[index][1]); }
  for (let index = 1; index < modules.length; index++) { await page.goForward(); await show(modules[index][1]); }
  await module('研发管理'); await restored('研发管理', 'management', '返回筛选工作', 2);
  await module('知识管理'); await restored('知识管理', 'knowledge', '复用返回候选', 2);
  checks.push('七个主侧栏入口与逐项Back/Forward一致，跨模块往返后两类目录状态仍独立保留');

  checkpoint = 'action detail survives application refresh and module return';
  await module('流程管理');
  await page.getByRole('tab', { name: '动作模板', exact: true }).click();
  const actionSearch = page.getByRole('searchbox', { name: '搜索动作模板', exact: true });
  await actionSearch.fill('固定返回动作'); await actionSearch.press('Enter');
  await page.locator('.rd-flow-directory-footer').getByRole('button', { name: '下一页', exact: true }).click();
  await page.getByRole('button', { name: '打开' + fixedAction.name + '画布', exact: true }).click();
  await fixedCanvas();
  for (let reload = 0; reload < 2; reload++) { await page.reload(); await fixedCanvas(); }
  await module('我的工作');
  await page.goBack(); await show('流程管理'); await fixedCanvas();
  await capture('05-action-detail-return-1440');
  await page.getByRole('button', { name: '返回动作模板', exact: true }).click();
  await page.getByRole('button', { name: '打开' + fixedAction.name + '画布', exact: true }).waitFor();
  assert.equal(await actionSearch.inputValue(), '固定返回动作');
  assert.equal(params().get('flow_page'), '2');
  assert.equal(params().get('flow_detail'), null);
  assert.equal(await page.locator('.rd-action-card-button').count(), 1, 'returning to the directory restores the filtered second page');
  await capture('06-action-directory-return-1440');
  await module('知识管理'); await restored('知识管理', 'knowledge', '复用返回候选', 2);
  checks.push('主应用动作详情连续刷新两次及跨模块Back保留V3固定画布，返回动作目录保留搜索与第2页');

  checkpoint = 'clear, IME and page clamp';
  await search('知识管理').dispatchEvent('compositionstart');
  await search('知识管理').fill('尚未提交的输入');
  await search('知识管理').press('Enter');
  assert.equal(params().get('knowledge_q'), '复用返回候选', 'IME Enter does not commit an unfinished query');
  await search('知识管理').dispatchEvent('compositionend', { data: '尚未提交的输入' });
  await search('知识管理').press('Enter');
  await page.getByText('未找到匹配的复用候选。', { exact: true }).waitFor();
  await page.getByRole('button', { name: '清空搜索', exact: true }).click();
  assert.equal(await search('知识管理').inputValue(), '');
  assert(await search('知识管理').evaluate(element => element === document.activeElement));
  assert.equal(params().get('knowledge_page'), '1');
  await page.goto(base + '/?rd_view=management&management_q=返回筛选工作&management_kind=completed&management_page=99');
  await page.getByText('6–6 / 6 条', { exact: true }).waitFor();
  await page.waitForFunction(() => new URL(location.href).searchParams.get('management_page') === '2');
  await page.setViewportSize({ width: 390, height: 844 }); await search('研发管理').scrollIntoViewIfNeeded(); await capture('03-management-return-390');
  checks.push('搜索支持中文输入法，清空立即重置页码并保留焦点，越界页码在数据就绪后收敛');
  await page.getByRole('button', { name: '上一页', exact: true }).click();
  await page.getByText('1–5 / 6 条', { exact: true }).waitFor();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await page.getByText('6–6 / 6 条', { exact: true }).waitFor();
  await capture('04-pagination-390');
  checks.push('桌面知识管理与窄屏研发管理分页可直接点击，不被默认助手位置遮挡');
  assert.deepEqual(pageErrors, []); assert.deepEqual(unexpected, []); assert.deepEqual(writes, []);
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ status: 'passed', checks, pageErrors, unexpected, writes, realApiRequests: 0, realModelCalls: 0 }, null, 2));
  console.log(JSON.stringify({ status: 'passed', checks, screenshots: output }));
} catch (error) {
  await capture('failure').catch(() => {});
  await writeFile(join(output, 'failure.json'), JSON.stringify({ checkpoint, message: error.message, pageErrors, unexpected, writes, url: page.url(), body: await page.locator('body').innerText().catch(() => '') }, null, 2));
  throw error;
} finally { await browser.close(); }
