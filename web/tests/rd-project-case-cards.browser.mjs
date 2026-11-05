/** Project card UI and navigation; every API is fulfilled by an isolated fixture. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'docs/rd-platform/verification/screenshots/2026-11-04-batch-sources-case-cards/cards';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
const pageErrors = [], unexpected = [], writes = [], checks = [];
page.on('pageerror', error => pageErrors.push(error.message));
const ids = ['input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start', 'taskbook'];
const titles = ['资料受理', '需求确认', '成熟产品比对', '选型决定', '研发启动依据', '研制任务书生成'];
const template = states => ({ id: 'taskbook-generation', version: '2', template_id: 'taskbook-generation', template_version: '2', template_digest: 'card-fixed', title: '研制任务书生成流程', category: 'project', status: 'published', digest: 'card-fixed', publication_revision: 1,
  graph: { nodes: ids.map((id, index) => ({ id, title: titles[index], role: '研发工程师', deliverables: [], position: { x: index * 240, y: 0 } })), edges: ids.slice(1).map((id, index) => ({ id: 'edge-' + id, source: ids[index], target: id })) }, node_states: states });
const stamp = '2026-11-04T04:00:00Z';
const source = (id, role) => ({ id, role, name: id + '.docx', version: 1, sha256: id, size: 1024, created_at: stamp });
const caseValue = (id, title, extra = {}) => ({ id, title, scenario_id: 'taskbook', stage: 'input', status: 'active', input_revision: 3, context: { product_type: 'liquid_cooling_pipeline', product_domain: 'military' }, sources: [], source_selection: {}, requirements: [], decisions: [], clarifications: [], comparisons: [], workpackages: [], product_route: null, composition_route: null,
  business_lifecycle: { policy_version: 'v2', rd_activation_state: 'not_started', local_review_enabled: true, can_record_decision: true, can_confirm_requirements: true }, workflow_templates: { project: template(Object.fromEntries(ids.map(id => [id, 'pending']))) }, project_workflow_status: { status: 'pending', terminal_node_id: 'taskbook' }, ...extra });
const packageValue = (id, status, extra = {}) => ({ id, title: '任务书执行', definition_id: 'taskbook', definition_version: '2', stage: 'planning', status, run_id: 'run-' + id, plan_revision: 1, nodes: [{ id: 'generate', action_id: 'generate', action_version: '1', depends_on: [], required: true, status }, { id: 'verify', action_id: 'verify', action_version: '1', depends_on: ['generate'], required: true, status, result: { delivery_approved: status === 'completed' } }], snapshot: { input_revision: 3, submitted_at: stamp }, artifacts: [{ id: 'artifact-' + id, name: id + '-任务书.docx', kind: 'taskbook' }], obligations: [], blocked_reasons: [], ...extra });
const pending = caseValue('pending', '需求核对 · 轻量化液冷管路研发任务书');
pending.sources = [source('old-tech', 'tech'), source('tech', 'tech'), source('spec', 'spec'), source('reference', 'reference')]; pending.source_selection = { tech: 'tech', spec: 'spec' };
pending.requirements = [{ id: 'r1', title: '压力要求', content: '0.3 MPa', source_ids: ['tech'] }, { id: 'old-r', title: '历史压力', content: '旧记录', source_ids: ['old-tech'] }];
pending.workflow_templates.project.node_states.input = 'completed';
const blocked = caseValue('blocked', '等待证据核对 · 超长流程名称用于验证窄屏完整换行和操作始终可达', { stage: 'planning', project_workflow_status: { status: 'blocked', terminal_node_id: 'taskbook', reason: '验证发现缺少确认签字，请补充当前证据。' } });
blocked.workflow_templates.project.node_states = Object.fromEntries(ids.map(id => [id, id === 'taskbook' ? 'blocked' : 'completed']));
blocked.workflow_templates.project.node_execution_refs = { taskbook: { workpackage_id: 'current', run_id: 'run-current', step_instance_ids: ['generate', 'verify'] } };
blocked.workpackages = [packageValue('historical', 'failed', { planned_end: '2020-01-01', blocked_reasons: ['不应出现在卡片上的旧绑定异常'] }), packageValue('current', 'blocked', { planned_end: '2026-11-20', blocked_reasons: ['缺少确认签字'] })];
const completed = caseValue('completed', '已完成 · 固定版本成果', { stage: 'planning', project_workflow_status: { status: 'completed', terminal_node_id: 'taskbook' } });
completed.workflow_templates.project.node_states = Object.fromEntries(ids.map(id => [id, 'completed']));
completed.workflow_templates.project.node_execution_refs = { taskbook: { workpackage_id: 'done', run_id: 'run-done', step_instance_ids: ['generate', 'verify'] } };
completed.workpackages = [packageValue('done', 'completed'), packageValue('completed-historical', 'failed', { blocked_reasons: ['已完成流程的旧执行异常'] })];
const unknown = caseValue('unknown', '节点状态尚未返回的流程'); delete unknown.workflow_templates.project.node_states;
unknown.workpackages = [packageValue('unknown-historical', 'failed', { stage: 'input', blocked_reasons: ['旧执行不应计入项目关注数'] })];
const project = { id: 'cards-fixture', title: '隔离项目 · 业务流程卡片', customer_name: '隔离客户 · 航空研究院', product_name: '轻量化液冷管路', owner_id: 'owner.fixture', updated_at: stamp, can_delete: true, members: [], version: 1, events: [], cases: [pending, blocked, completed, unknown] };
const emptyProject = { id: 'empty-cards-fixture', title: '隔离项目 · 尚无流程', owner_id: '', members: [], version: 1, events: [], cases: [] };
const catalog = { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书', status: 'published' }], actions: [], workpackage_definitions: [], project_workflow_templates: [template({})] };
const pageUrl = base + '/?rd_view=projects&project=' + project.id;
const card = name => page.getByRole('article', { name, exact: true });
const projectFact = (name, section, label) => card(name).locator(section).locator('dt').filter({ hasText: new RegExp('^' + label + '$') }).locator('xpath=following-sibling::dd');
const snap = name => page.screenshot({ path: join(output, name + '.png') });
async function list() { await page.goto(pageUrl); await card(pending.title).waitFor(); }
async function projectList() {
  await page.goto(base + '/?rd_view=projects');
  await page.getByRole('button', { name: project.title, exact: true }).waitFor();
}
async function noOverflow() {
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  assert(await page.locator('.rd-application-shell').evaluate(element => element.scrollWidth <= element.clientWidth + 1));
}
async function overviewLayout(name) {
  const overview = card(name);
  const heading = await overview.locator(':scope > header').boundingBox();
  const facts = await overview.locator('.rd-project-overview-body').boundingBox();
  assert(heading && facts && heading.y + heading.height <= facts.y + 1, 'project heading and facts stack vertically without a split card');
  const countLabels = await overview.locator('.rd-project-overview-counts dt').evaluateAll(labels => labels.map(label => label.getBoundingClientRect().top));
  assert.equal(countLabels.length, 3);
  assert(Math.max(...countLabels) - Math.min(...countLabels) <= 1, 'all three project counts stay on one readable row');
}
try {
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (!['GET', 'HEAD'].includes(request.method())) writes.push({ method: request.method(), path });
    if (request.method() === 'GET') {
      if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
      if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'owner.fixture', local_mode: true } });
      if (path === '/api/rd/catalog') return route.fulfill({ json: catalog });
      if (path === '/api/rd/catalog/items') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 5, total_pages: 1 } });
      if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [project, emptyProject] } });
      if (path === '/api/rd/projects/' + project.id) return route.fulfill({ json: project });
      if (path === '/api/rd/projects/' + emptyProject.id) return route.fulfill({ json: emptyProject });
      if (path === '/api/rd/assistant/weather') return route.fulfill({ json: { status: 'unavailable', location: '隔离测试', notice: '天气不属于卡片验证范围。' } });
      if (path === '/api/models') return route.fulfill({ json: { success: true, models: [] } });
      if (path === '/api/rd/projects/cards-fixture/cases/pending/evidence-locations') return route.fulfill({ json: { items: [] } });
      if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: 'liquid_cooling_pipeline', label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }] }] } });
      if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: 'input', project_version: 1, input_revision: 3 } } });
    }
    unexpected.push({ method: request.method(), path });
    return route.fulfill({ status: 500, json: { error: '隔离卡片未预期请求' } });
  });
  await projectList();
  assert.equal(await page.locator('.rd-project-overview-counts').count(), 2, 'each project overview exposes counts for all its workflows');
  await card(project.title).waitFor();
  assert.equal(await projectFact(project.title, '.rd-project-overview-profile', '客户').innerText(), project.customer_name);
  assert.equal(await projectFact(project.title, '.rd-project-overview-profile', '产品').innerText(), project.product_name);
  for (const [label, value] of [['业务流程', '4'], ['已完成', '1'], ['需关注', '1']]) {
    assert.equal(await projectFact(project.title, '.rd-project-overview-counts', label).innerText(), value);
  }
  assert.equal(await projectFact(project.title, '.rd-project-overview-meta', '项目负责人').innerText(), project.owner_id);
  assert.match(await projectFact(project.title, '.rd-project-overview-meta', '最近更新').innerText(), /2026[/-]11[/-]0?4.*12:00/);
  assert.equal(await card(project.title).locator('.rd-project-continue').count(), 2, 'project previews still stop at two workflows');
  const pendingPreview = card(project.title).locator('.rd-project-continue').filter({ hasText: pending.title });
  assert(!(await pendingPreview.innerText()).includes('需关注'), 'a workflow without a current attention reason has no warning');
  assert((await card(project.title).locator('.rd-project-continue').filter({ hasText: blocked.title }).innerText()).includes('需关注'));
  assert.equal(await page.locator('.rd-project-case-card').count(), 0, 'workflow progress cards remain inside the project detail');
  for (const label of ['业务流程', '已完成', '需关注']) {
    assert.equal(await projectFact(emptyProject.title, '.rd-project-overview-counts', label).innerText(), '0');
  }
  for (const label of ['客户', '产品']) {
    assert.equal(await projectFact(emptyProject.title, '.rd-project-overview-profile', label).innerText(), '未填写');
  }
  assert.equal(await projectFact(emptyProject.title, '.rd-project-overview-meta', '项目负责人').innerText(), '未设置');
  assert.equal(await projectFact(emptyProject.title, '.rd-project-overview-meta', '最近更新').innerText(), '未记录');
  await noOverflow(); await overviewLayout(project.title); await overviewLayout(emptyProject.title); await snap('06-project-overview-1440');
  checks.push('外层项目卡显示客户、产品、全部4个流程及1已完成/1需关注、负责人和记录更新时间；历史失败不污染关注数，空项目汇总为0且缺值明确');

  await pendingPreview.click();
  await page.getByRole('navigation', { name: '办理步骤', exact: true }).getByRole('button', { name: '资料识别', exact: true }).and(page.locator('[aria-current="step"]')).waitFor();
  await projectList(); await card(project.title).getByRole('button', { name: '查看项目', exact: true }).click();
  await card(unknown.title).waitFor();
  assert.equal(await page.locator('.rd-project-case-card').count(), 4);
  await projectList(); await card(project.title).getByRole('button', { name: project.title, exact: true }).click();
  await card(pending.title).waitFor();
  await projectList();
  await card(project.title).getByRole('button', { name: '删除项目“' + project.title + '”', exact: true }).click();
  const deleteDialog = page.getByRole('dialog', { name: '删除项目', exact: true });
  await deleteDialog.waitFor();
  assert((await deleteDialog.innerText()).includes('包含 4 个业务流程'));
  await deleteDialog.getByRole('button', { name: '取消', exact: true }).click();
  await deleteDialog.waitFor({ state: 'hidden' });
  await card(project.title).waitFor();
  assert.equal(writes.length, 0, 'overview navigation and cancelling deletion never write');
  checks.push('外层继续办理、查看项目和标题入口均可导航，删除入口显示本项目范围且取消后保留项目，零写请求');

  const search = page.getByRole('textbox', { name: '搜索项目、客户、产品或业务流程', exact: true });
  await search.fill(unknown.title);
  await page.getByText('1 个项目', { exact: true }).waitFor();
  await card(project.title).waitFor();
  assert.equal(await projectFact(project.title, '.rd-project-overview-counts', '业务流程').innerText(), '4');
  assert.equal(await card(project.title).locator('.rd-project-continue').count(), 2);
  await search.fill(emptyProject.title);
  await card(emptyProject.title).waitFor();
  await card(project.title).waitFor({ state: 'hidden' });
  await card(emptyProject.title).getByRole('button', { name: '进入项目选择流程模板', exact: true }).click();
  await page.getByRole('heading', { name: '选择流程模板开始', exact: true }).waitFor();
  await projectList();
  await search.fill('不存在的隔离项目');
  await page.getByRole('heading', { name: '没有找到匹配的项目', exact: true }).waitFor();
  await page.getByRole('button', { name: '清空项目搜索', exact: true }).click();
  await page.getByText('2 个项目', { exact: true }).waitFor();
  await card(project.title).getByRole('button', { name: '查看全部 4 个流程', exact: true }).click();
  await card(unknown.title).waitFor();
  assert.equal(await page.locator('.rd-project-case-card').count(), 4);
  checks.push('搜索涵盖未预览流程与空项目，汇总仍按完整项目；清空搜索恢复列表，查看全部展示4个内层流程');

  await projectList(); await page.setViewportSize({ width: 390, height: 844 });
  await card(project.title).scrollIntoViewIfNeeded(); await noOverflow(); await overviewLayout(project.title); await snap('07-project-overview-390');
  await card(emptyProject.title).scrollIntoViewIfNeeded(); await noOverflow(); await overviewLayout(emptyProject.title); await snap('08-project-overview-missing-390');
  await card(project.title).getByRole('button', { name: '查看全部 4 个流程', exact: true }).scrollIntoViewIfNeeded();
  await card(project.title).getByRole('button', { name: '查看全部 4 个流程', exact: true }).click();
  await card(unknown.title).waitFor();
  assert.equal(await page.locator('.rd-project-case-card').count(), 4);
  await page.setViewportSize({ width: 1440, height: 1000 });
  checks.push('外层项目卡1440/390无页面横向溢出，窄屏项目汇总、长流程名称、缺值及查看全部入口可达');

  await list();
  assert.equal(await page.locator('.rd-project-case-card').count(), 4);
  await card(pending.title).getByText('已完成 1 / 6 个节点', { exact: true }).waitFor();
  assert((await card(pending.title).innerText()).includes('3 份资料 · 1 条需求'));
  assert((await card(blocked.title).innerText()).includes('2026-11-20'));
  assert((await card(blocked.title).innerText()).includes('1 份成果 · 未登记'));
  assert(!(await card(blocked.title).innerText()).includes('2020-01-01'));
  assert(!(await card(blocked.title).innerText()).includes('旧绑定异常'));
  await card(blocked.title).getByText('验证发现缺少确认签字，请补充当前证据。', { exact: true }).waitFor();
  await card(completed.title).getByRole('button', { name: '查看成果', exact: true }).waitFor();
  assert.equal(await card(unknown.title).locator('.ant-progress').count(), 0);
  assert((await card(unknown.title).innerText()).includes('未记录'));
  await noOverflow(); await snap('01-case-cards-1440');
  checks.push('真实固定节点进度、当前资料需求、当前执行引用、受阻原因和缺值均按记录展示；历史成果及旧截止不混入');

  await card(pending.title).getByRole('button', { name: '继续办理', exact: true }).click();
  await page.getByRole('navigation', { name: '办理步骤', exact: true }).getByRole('button', { name: '资料识别', exact: true }).and(page.locator('[aria-current="step"]')).waitFor();
  await list(); await card(pending.title).getByRole('button', { name: '查看流程', exact: true }).click();
  await page.getByRole('region', { name: '项目固定流程', exact: true }).waitFor();
  await list();
  const more = card(pending.title).getByRole('button', { name: pending.title + '更多操作', exact: true });
  await more.focus(); await page.keyboard.press('Enter');
  await page.getByRole('menuitem', { name: '资料依据', exact: true }).waitFor();
  await page.getByRole('menuitem', { name: '资料依据', exact: true }).click();
  await page.getByRole('heading', { name: '资料与依据', exact: true }).waitFor();
  await list(); await card(completed.title).getByRole('button', { name: '查看成果', exact: true }).click();
  await page.getByRole('heading', { name: '研制任务书生成成果', exact: true }).waitFor();
  assert.equal(writes.length, 0, 'all card actions only navigate');
  checks.push('继续办理、完成查看成果、查看流程、键盘打开更多及资料依据均进入真实工作面，零写请求');

  await list(); await page.setViewportSize({ width: 390, height: 844 });
  await card(pending.title).scrollIntoViewIfNeeded(); await noOverflow(); await snap('02-case-cards-390');
  await card(blocked.title).scrollIntoViewIfNeeded(); await noOverflow(); await snap('03-blocked-card-390');
  await card(blocked.title).getByRole('button', { name: blocked.title + '更多操作', exact: true }).click();
  await page.getByRole('menuitem', { name: '资料依据', exact: true }).waitFor(); await snap('04-card-actions-390');
  await page.keyboard.press('Escape');
  project.owner_id = ''; await list(); await card(unknown.title).scrollIntoViewIfNeeded();
  assert.equal(await card(unknown.title).getByText('未设置', { exact: true }).count(), 2);
  await noOverflow(); await snap('05-card-missing-values-390');
  checks.push('1440/390布局无页面横向溢出，长名称完整换行；负责人和计划缺失显示未设置，窄屏更多菜单可达');
  assert.deepEqual(pageErrors, []); assert.deepEqual(unexpected, []); assert.deepEqual(writes, []);
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ status: 'passed', checks, pageErrors, unexpected, writes, realApiRequests: 0, realModelCalls: 0 }, null, 2));
  console.log(JSON.stringify({ status: 'passed', checks, screenshots: output }));
} catch (error) {
  await snap('failure').catch(() => {});
  await writeFile(join(output, 'failure.json'), JSON.stringify({ message: error.message, pageErrors, unexpected, writes, body: await page.locator('body').innerText().catch(() => '') }, null, 2));
  throw error;
} finally { await browser.close(); }
