/** Homepage facts and responsive actions; every API response is isolated. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'runtime/home-experience/after';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
const pageErrors = [], unexpected = [], writes = [], checks = [];
page.on('pageerror', error => pageErrors.push(error.message));
const stamp = '2026-11-05T04:00:00Z';
const ids = ['input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start', 'taskbook'];
const template = () => ({ id: 'home-template', version: '2', template_id: 'home-template', template_version: '2', template_digest: 'home-fixed', title: '研制任务书生成流程', category: 'project', status: 'published', digest: 'home-fixed', publication_revision: 1,
  graph: { nodes: ids.map((id, index) => ({ id, title: id, role: '研发工程师', deliverables: [], position: { x: index * 240, y: 0 } })), edges: ids.slice(1).map((id, index) => ({ id: 'edge-' + id, source: ids[index], target: id })) }, node_states: Object.fromEntries(ids.map(id => [id, 'completed'])) });
const packageValue = (id, status, extra = {}) => ({ id, title: '执行记录 ' + id, definition_id: 'taskbook', definition_version: '2', stage: 'planning', status, run_id: 'run-' + id, plan_revision: 1, nodes: [], snapshot: { input_revision: 3, submitted_at: stamp }, artifacts: [], obligations: [], blocked_reasons: ['待补齐当前确认依据'], ...extra });
const caseValue = (id, title, extra = {}) => ({ id, title, scenario_id: 'taskbook', stage: 'planning', status: 'active', input_revision: 3, context: { product_type: 'liquid_cooling_pipeline', product_domain: 'military' }, sources: [], source_selection: {}, requirements: [], decisions: [], clarifications: [], comparisons: [], workpackages: [], product_route: null, composition_route: null,
  business_lifecycle: { policy_version: 'v2', rd_activation_state: 'active', local_review_enabled: true, can_record_decision: true, can_confirm_requirements: true }, workflow_templates: { project: template() }, project_workflow_status: { status: 'pending', terminal_node_id: 'taskbook' }, ...extra });
const active = caseValue('active', '待核对流程 · 当前任务书证据缺口', { project_workflow_status: { status: 'blocked', terminal_node_id: 'taskbook', reason: '当前验证缺少确认依据，请进入工作包补齐。' } });
active.workflow_templates.project.node_execution_refs = { taskbook: { workpackage_id: 'current-a', run_id: 'run-current-a', step_instance_ids: [] }, input: { workpackage_id: 'current-b', run_id: 'run-current-b', step_instance_ids: [] } };
active.workpackages = [packageValue('old-input', 'failed', { snapshot: { input_revision: 1 } }), packageValue('old-unbound', 'failed'), packageValue('current-a', 'blocked'), packageValue('current-b', 'failed')];
const historicalOnly = caseValue('historical-only', '历史失败已不适用的流程');
historicalOnly.workpackages = [packageValue('historical-only', 'failed')];
const completed = caseValue('completed', '已完成流程', { project_workflow_status: { status: 'completed', terminal_node_id: 'taskbook' } });
completed.workpackages = [packageValue('completed-old', 'failed')];
const project = { id: 'home-project', title: '首页隔离项目 · 长名称验证多流程状态与可见办理入口', customer_name: '隔离客户', product_name: '液冷管路', owner_id: 'owner.fixture', updated_at: stamp, members: [], version: 1, events: [], cases: [active, historicalOnly, completed] };
const emptyProject = { id: 'home-empty-project', title: '尚未选择流程的项目', owner_id: '', members: [], version: 1, events: [], cases: [] };
const completedProject = { ...project, id: 'home-completed-project', title: '固定流程已完成的项目', cases: [completed] };
const catalog = { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书', status: 'published' }], actions: [], workpackage_definitions: [], project_workflow_templates: [template()] };
let mode = 'populated', releaseLoading;
let loadingGate = Promise.resolve();
const snap = name => page.screenshot({ path: join(output, name + '.png') });
const home = () => page.locator('.rd-platform-home');
const recent = () => page.getByRole('region', { name: '最近项目', exact: true });
async function openHome() {
  await page.goto(base + '/?rd_view=home');
  await home().getByRole('heading', { name: '我的工作', exact: true }).waitFor();
}
async function noOverflow() {
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'homepage never causes document horizontal overflow');
  assert(await page.locator('.rd-home-project-table').evaluate(element => element.scrollWidth <= element.clientWidth + 1), 'recent project actions fit within the visible panel without horizontal scrolling');
}
async function visibleRecentActions() {
  const actions = recent().getByRole('button', { name: /^(继续办理|查看成果|进入项目)$/ });
  assert.equal(await actions.count(), 3, 'each recent project has exactly one visible action');
  for (const button of await actions.all()) {
    const bounds = await button.boundingBox();
    assert(bounds && bounds.x >= 0 && bounds.x + bounds.width <= (await page.viewportSize()).width, 'project action stays within the viewport horizontally');
    if (bounds.y >= 0 && bounds.y + bounds.height <= (await page.viewportSize()).height) {
      assert(await button.evaluate(element => {
        const rect = element.getBoundingClientRect();
        return element.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
      }), 'visible project actions remain reachable beside floating controls');
    }
  }
}
try {
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (!['GET', 'HEAD'].includes(request.method())) writes.push({ method: request.method(), path });
    if (request.method() === 'GET') {
      if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
      if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'owner.fixture', local_mode: true } });
      if (path === '/api/rd/catalog') {
        if (mode === 'loading') await loadingGate;
        if (mode === 'catalog-error') return route.fulfill({ status: 503, json: { error: '隔离目录暂不可用' } });
        return route.fulfill({ json: mode === 'empty-catalog' ? { ...catalog, project_workflow_templates: [] } : catalog });
      }
      if (path === '/api/rd/projects') {
        if (mode === 'loading') await loadingGate;
        if (mode === 'error') return route.fulfill({ status: 503, json: { error: '隔离项目读取失败' } });
        return route.fulfill({ json: { projects: mode === 'empty' || mode === 'empty-catalog' ? [] : [project, completedProject, emptyProject] } });
      }
      if (path === '/api/rd/projects/' + project.id) return route.fulfill({ json: project });
      if (path === '/api/rd/projects/' + emptyProject.id) return route.fulfill({ json: emptyProject });
      if (path === '/api/rd/projects/' + completedProject.id) return route.fulfill({ json: completedProject });
      if (path === '/api/rd/catalog/items') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 5, total_pages: 1 } });
      if (path === '/api/rd/assistant/weather') return route.fulfill({ json: { status: 'unavailable', location: '隔离测试', notice: '天气不属于首页验证范围。' } });
      if (path === '/api/models') return route.fulfill({ json: { success: true, models: [] } });
      if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: 'liquid_cooling_pipeline', label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }] }] } });
      if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: 'planning', project_version: 1, input_revision: 3 } } });
    }
    unexpected.push({ method: request.method(), path });
    return route.fulfill({ status: 500, json: { error: '首页隔离测试未预期请求' } });
  });
  await openHome();
  await recent().getByRole('button', { name: project.title, exact: true }).waitFor();
  await snap('01-home-1440');
  const attention = page.getByRole('region', { name: '需关注', exact: true });
  assert.equal(await attention.locator('.rd-attention-list > button').count(), 1, 'attention deduplicates by workflow and excludes historical, unbound and completed failures');
  assert((await attention.innerText()).includes(active.title));
  assert(!(await attention.innerText()).includes(historicalOnly.title));
  assert(!(await attention.innerText()).includes(completed.title));
  assert((await recent().innerText()).includes('编排与生成'), 'home uses the same current workface label as workflow cards');
  assert((await recent().innerText()).includes('未记录'), 'a missing update timestamp stays explicit');
  const completedRow = recent().getByRole('row').filter({ has: page.getByRole('button', { name: completedProject.title, exact: true }) });
  assert((await completedRow.innerText()).includes('流程已完成'), 'fixed workflow completion takes precedence over the legacy active case status');
  assert.equal(await completedRow.getByRole('button', { name: '查看成果', exact: true }).count(), 1);
  await noOverflow(); await visibleRecentActions();
  checks.push('当前关注按流程去重，排除历史/未绑定/已完成失败，步骤与流程卡一致，缺少时间明确标注');
  await page.setViewportSize({ width: 390, height: 844 });
  await recent().scrollIntoViewIfNeeded(); await noOverflow(); await visibleRecentActions(); await snap('02-home-390');
  await page.setViewportSize({ width: 800, height: 1000 });
  await noOverflow(); await visibleRecentActions(); await snap('02-home-800');
  for (const button of await recent().getByRole('button', { name: /^(继续办理|查看成果|进入项目)$/ }).all()) {
    assert(await button.locator('span').last().evaluate(element => {
      const range = document.createRange(); range.selectNodeContents(element);
      return range.getClientRects().length <= 1;
    }), 'project action labels remain readable on one line at intermediate widths');
  }
  checks.push('1440、800与390最近项目无横滚，项目名、当前办理步骤和唯一办理入口可见');

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => localStorage.setItem('rd:case-resume:v1:owner.fixture:home-project:active', 'sources'));
  await attention.locator('.rd-attention-list > button').focus();
  await page.keyboard.press('Enter');
  await page.getByRole('heading', { name: '工作包编排与执行', level: 1, exact: true }).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('case'), active.id);
  checks.push('键盘启用关注入口直接进入对应流程的工作包办理面，覆盖旧继续位置且导航不产生写请求');

  mode = 'empty'; await openHome();
  await home().getByRole('heading', { name: '暂无项目记录', exact: true }).waitFor();
  await page.waitForFunction(() => !document.querySelector('.rd-home-intro button')?.disabled);
  assert(await home().getByRole('button', { name: '新建项目', exact: true }).isEnabled());
  await snap('03-empty-1440');
  await page.setViewportSize({ width: 390, height: 844 }); await home().scrollIntoViewIfNeeded(); await snap('04-empty-390');

  mode = 'error'; await openHome();
  await recent().getByRole('alert').waitFor();
  assert.equal(await home().getByRole('heading', { name: '暂无项目记录', exact: true }).count(), 0, 'read failure is not rendered as an empty list');
  await snap('05-error-390');
  await page.setViewportSize({ width: 1440, height: 1000 }); await snap('06-error-1440');
  mode = 'populated'; await recent().getByRole('button', { name: '重新读取', exact: true }).click();
  await recent().getByRole('button', { name: project.title, exact: true }).waitFor();
  mode = 'error'; await recent().getByRole('button', { name: '刷新', exact: true }).click();
  await recent().getByRole('alert').waitFor();
  assert((await recent().innerText()).includes('当前显示上次读取的项目记录。'));
  assert(await recent().getByRole('button', { name: project.title, exact: true }).isVisible(), 'failed refresh preserves readable prior records');
  await snap('07-stale-error-1440');
  checks.push('空记录、读取失败与重新读取分别呈现，重试恢复项目；刷新失败保留旧记录并说明来源');

  mode = 'loading'; loadingGate = new Promise(resolve => { releaseLoading = resolve; });
  await page.setViewportSize({ width: 1440, height: 1000 }); await openHome();
  await recent().getByRole('status').waitFor();
  assert(await home().getByRole('button', { name: '新建项目', exact: true }).isDisabled());
  assert(!(await home().innerText()).includes('查看与发布'), 'loading catalog is not mislabeled as missing templates');
  await snap('08-loading-1440');
  await page.setViewportSize({ width: 390, height: 844 }); await home().scrollIntoViewIfNeeded(); await snap('09-loading-390');
  mode = 'populated'; releaseLoading();
  await recent().getByRole('button', { name: project.title, exact: true }).waitFor();
  await page.waitForFunction(() => !document.querySelector('.rd-home-intro button')?.disabled);
  checks.push('项目与目录读取中保留明确状态，创建条件就绪后恢复按钮');

  mode = 'empty-catalog'; await openHome();
  await home().getByRole('heading', { name: '暂无项目记录', exact: true }).waitFor();
  await page.waitForFunction(() => !document.querySelector('.rd-home-start-note[role="status"]'));
  assert(await home().getByRole('button', { name: '新建项目', exact: true }).isDisabled());
  assert.match(await home().innerText(), /暂无.*已发布流程模板/);
  await snap('10-empty-catalog-390');

  mode = 'catalog-error'; await openHome();
  await page.getByRole('alert').filter({ hasText: '隔离目录暂不可用' }).waitFor();
  assert(await home().getByRole('button', { name: '新建项目', exact: true }).isDisabled());
  assert(!(await home().innerText()).includes('暂无已发布流程模板'), 'catalog failure stays distinct from an empty catalog');
  await snap('11-catalog-error-390');
  checks.push('空目录与目录失败互不混淆，统一禁用无法创建的入口');
  assert.deepEqual(pageErrors, []); assert.deepEqual(unexpected, []); assert.deepEqual(writes, []);
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ status: 'passed', checks, pageErrors, unexpected, writes, realApiRequests: 0, realModelCalls: 0 }, null, 2));
  console.log(JSON.stringify({ status: 'passed', checks, screenshots: output }));
} catch (error) {
  await snap('failure').catch(() => {});
  await writeFile(join(output, 'failure.json'), JSON.stringify({ message: error.message, pageErrors, unexpected, writes, body: await page.locator('body').innerText().catch(() => '') }, null, 2));
  throw error;
} finally { releaseLoading?.(); await browser.close(); }
