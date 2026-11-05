/** Navigation, history and unsaved fields; every API response is an isolated read-only fixture. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'runtime/rd-navigation-history-browser';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
const pageErrors = [], unexpected = [], writes = [], checks = [], screenshots = [];
let checkpoint = 'fixture setup';
page.on('pageerror', error => pageErrors.push(error.message));
page.on('dialog', dialog => dialog.dismiss());

const stamp = '2026-11-05T02:00:00Z';
const actor = 'navigation-owner';
const workflow = { id: 'taskbook-generation', version: '1', template_id: 'taskbook-generation', template_version: '1', template_digest: 'navigation-fixed', digest: 'navigation-fixed', title: '研制任务书生成流程', category: 'project', status: 'published', publication_revision: 1,
  graph: { nodes: [{ id: 'input', title: '资料受理', role: '研发工程师', deliverables: [], position: { x: 0, y: 0 } }, { id: 'taskbook', title: '研制任务书生成', role: '研发工程师', deliverables: [], position: { x: 240, y: 0 }, workpackage_definition_id: 'taskbook' }], edges: [{ id: 'input-taskbook', source: 'input', target: 'taskbook' }] }, node_states: { input: 'pending', taskbook: 'pending' } };
const sources = ['tech', 'spec'].map(role => ({ id: role, role, name: role === 'tech' ? '隔离导航技术要求.docx' : '隔离导航产品规范.pdf', size: 2048, version: 1, sha256: role.repeat(16), created_at: stamp }));
const requirement = { id: 'requirement', title: '压力要求', content: '工作压力为 0.3 MPa。', source_ids: ['tech'], revision: 1, history: [], evidence: [{ source_id: 'tech', quote: '工作压力为 0.3 MPa。' }] };
const researchCase = { id: 'navigation-case', title: '导航隔离流程', scenario_id: 'taskbook', stage: 'input', status: 'active', input_revision: 3,
  context: { product_type: 'liquid_cooling_pipeline', product_domain: 'military', product_series: 'YLZJ', organization_scope: 'non_central_research' }, sources, source_selection: { tech: 'tech', spec: 'spec' }, requirements: [requirement], clarifications: [], comparisons: [], workpackages: [],
  decisions: [{ id: 'old-decision', stage: 'requirements', verdict: 'approved', rationale: '历史需求依据已失效，保留记录。', source_ids: ['tech'], created_at: stamp, invalidated_at: stamp, invalidated_reason: '输入版本已更新' }],
  product_route: null, composition_route: null, model_selection: { provider: '', name: '', id: '' },
  workflow_templates: { project: workflow }, project_workflow_status: { status: 'pending', terminal_node_id: 'taskbook' },
  business_lifecycle: { policy_version: 'v2', rd_activation_state: 'not_started', review_mode: 'local_review', local_review_enabled: true, can_record_decision: true, can_confirm_requirements: true } };
const packages = ['historical-package', 'target-package'].map((id, index) => ({ id, title: index ? '本次任务书执行' : '历史任务书执行', definition_id: 'taskbook', definition_version: '2', stage: 'planning', status: 'completed', plan_revision: 1, run_id: 'run-' + id,
  snapshot: { input_revision: index ? 3 : 2, submitted_at: stamp }, nodes: [{ id: 'generate', action_id: 'generate', action_version: '1', depends_on: [], required: true, status: 'completed', completed_at: stamp }],
  artifacts: [{ id: 'artifact-' + id, name: id + '.docx', kind: 'taskbook' }], obligations: [], blocked_reasons: [] }));
const executionCase = { ...researchCase, id: 'execution-case', title: '导航执行记录流程', stage: 'planning', decisions: [], workpackages: packages, business_lifecycle: { ...researchCase.business_lifecycle, rd_activation_state: 'active' } };
const completedCase = { ...executionCase, id: 'completed-case', title: '已完成的导航流程', project_workflow_status: { status: 'completed', terminal_node_id: 'taskbook' } };
const project = { id: 'navigation-project', title: '隔离导航项目', customer_name: '隔离客户', product_name: '液冷管路', owner_id: actor, members: [], events: [], version: 1, created_at: stamp, updated_at: stamp, cases: [researchCase, executionCase, completedCase] };
const listProjects = [...Array.from({ length: 5 }, (_, index) => ({ ...project, id: 'navigation-empty-' + index, title: '隔离导航空项目 ' + (index + 1), updated_at: '2026-11-04T02:00:00Z', cases: [] })), project];
const catalog = { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书', status: 'published' }], project_workflow_templates: [workflow], actions: [], workpackage_definitions: [] };
const caseUrl = '/?rd_view=projects&project=navigation-project&case=navigation-case';
const resumeKey = 'rd:case-resume:v1:navigation-owner:navigation-project:navigation-case';
const nav = () => page.getByRole('navigation', { name: '办理步骤', exact: true });
const step = name => nav().getByRole('button', { name, exact: true });
const sideView = name => page.getByRole('navigation', { name: '当前业务流程视图', exact: true }).getByRole('button', { name, exact: true });
const overview = () => page.getByRole('button', { name: '成果概览', exact: true });
const returnToEditor = () => page.getByRole('button', { name: '返回办理', exact: true });
const leaveDialog = () => page.getByRole('dialog', { name: '离开前保存填写', exact: true });
const params = () => new URL(page.url()).searchParams;
async function viewed(name) { await step(name).and(page.locator('[aria-current="step"]')).waitFor(); }
async function assertRoute(expected) {
  await page.waitForFunction(values => Object.entries(values).every(([key, value]) => {
    const actual = new URL(location.href).searchParams.get(key);
    return (key === 'case_view' ? actual || 'current' : actual) === value;
  }), expected);
  for (const [key, value] of Object.entries(expected)) assert.equal(key === 'case_view' ? params().get(key) || 'current' : params().get(key), value, `${key} identifies the visible page`);
}
async function capture(name) { await page.screenshot({ path: join(output, name + '.png') }); screenshots.push(name + '.png'); }
async function goHome() { await page.getByRole('button', { name: '我的工作', exact: true }).click(); await page.getByRole('heading', { name: '我的工作', level: 1, exact: true }).waitFor(); }
async function continueCase() { await page.getByRole('region', { name: '最近项目', exact: true }).getByRole('row').filter({ hasText: project.title }).getByRole('button', { name: '继续办理', exact: true }).click(); }

try {
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (!['GET', 'HEAD'].includes(request.method())) writes.push({ method: request.method(), path });
    if (request.method() === 'GET') {
      if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
      if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: actor, local_mode: true } });
      if (path === '/api/rd/projects') return route.fulfill({ json: { projects: listProjects } });
      if (path === '/api/rd/projects/' + project.id) return route.fulfill({ json: project });
      if (path === '/api/rd/catalog') return route.fulfill({ json: catalog });
      if (path === '/api/rd/catalog/items') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 5, total_pages: 1 } });
      if (path === '/api/models') return route.fulfill({ json: { success: true, models: [] } });
      if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: 'liquid_cooling_pipeline', label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }] }] } });
      if (path === '/api/rd/assistant/weather') return route.fulfill({ json: { status: 'unavailable', location: '隔离测试', notice: '导航测试不读取天气。' } });
      if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: 'input', project_version: 1, input_revision: 3 } } });
    }
    unexpected.push({ method: request.method(), path });
    return route.fulfill({ status: 500, json: { error: '导航夹具不允许此请求：' + path } });
  });

  checkpoint = 'internal browser back stays in the previous editing step';
  await page.goto(base + '/?rd_view=home');
  await continueCase(); await viewed('需求确认');
  await step('资料识别').click(); await viewed('资料识别');
  await step('需求确认').click(); await viewed('需求确认');
  await page.goBack();
  await page.waitForFunction(() => !document.querySelector('.rd-case-journey') || document.querySelector('.rd-case-journey [aria-current="step"]')?.getAttribute('aria-label') === '资料识别');
  assert.equal(await step('资料识别').and(page.locator('[aria-current="step"]')).count(), 1, 'Back after opening requirements returns to sources, not out of the case');
  await assertRoute({ case_view: 'current', step: 'sources' });
  await page.goForward(); await viewed('需求确认'); await assertRoute({ step: 'requirements' });
  checks.push('browser Back and Forward traverse actual editing steps');

  checkpoint = 'auxiliary views survive browser history, refresh and return-to-editor';
  await sideView('项目流程').click(); await assertRoute({ case_view: 'process' });
  await page.getByRole('region', { name: '项目固定流程', exact: true }).waitFor();
  await page.reload(); await page.getByRole('region', { name: '项目固定流程', exact: true }).waitFor();
  await assertRoute({ case_view: 'process' });
  await returnToEditor().click(); await viewed('需求确认');
  await sideView('资料与依据').click(); await assertRoute({ case_view: 'evidence' });
  await page.reload(); await page.locator('.rd-evidence-panel').waitFor(); await assertRoute({ case_view: 'evidence' });
  await returnToEditor().click(); await viewed('需求确认');
  await overview().click(); await page.getByRole('heading', { name: '当前成果', level: 1, exact: true }).waitFor();
  await assertRoute({ case_view: 'current', step: 'current' });
  await page.reload(); await page.getByRole('heading', { name: '当前成果', level: 1, exact: true }).waitFor();
  await returnToEditor().click(); await viewed('需求确认');
  await sideView('项目流程').click(); await sideView('资料与依据').click();
  await page.goBack(); await assertRoute({ case_view: 'process' });
  await page.getByRole('region', { name: '项目固定流程', exact: true }).waitFor();
  await page.goForward(); await assertRoute({ case_view: 'evidence' });
  assert.equal(await nav().locator('[aria-current="step"]').count(), 0, 'auxiliary views do not mark a business editor as visible');
  await capture('01-auxiliary-history');
  checks.push('process, evidence and overview keep explicit routes on reload and return to the previous editor');

  checkpoint = 'explicit URL takes precedence over personal continuation';
  await page.evaluate(key => localStorage.setItem(key, 'requirements'), resumeKey);
  await page.goto(base + caseUrl + '&case_view=current&step=sources'); await viewed('资料识别');
  await page.reload(); await viewed('资料识别');
  await step('需求确认').click(); await viewed('需求确认');
  await goHome(); await continueCase(); await viewed('需求确认');
  await page.goto(base + caseUrl + '&case_view=current&step=workpackages'); await viewed('需求确认');
  assert(await step('编排与生成').isDisabled(), 'an explicit unavailable step does not bypass business availability');
  checks.push('explicit available URLs win, ordinary continuation restores the personal editor, unavailable steps stay closed');

  checkpoint = 'overview reload restores a saved editing step distinct from the active business step';
  await page.evaluate(key => localStorage.setItem(key, 'sources'), resumeKey);
  await page.goto(base + caseUrl + '&case_view=current&step=current');
  await page.getByRole('heading', { name: '当前成果', level: 1, exact: true }).waitFor();
  const [overviewSession] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/api/rd/session'),
    page.reload(),
  ]);
  await overviewSession.finished();
  await page.getByRole('heading', { name: '当前成果', level: 1, exact: true }).waitFor();
  assert.equal(await page.evaluate(key => localStorage.getItem(key), resumeKey), 'sources', 'explicit overview does not overwrite the saved editor');
  await returnToEditor().click(); await viewed('资料识别'); await assertRoute({ step: 'sources' });
  assert((await step('需求确认').innerText()).includes('当前待办'), 'the returned personal editor remains distinct from the active business step');
  await step('需求确认').click(); await viewed('需求确认');
  checks.push('an explicit overview survives reload and returns to saved sources while requirements remain the current business task');

  checkpoint = 'same-case navigation keeps the live requirement draft';
  await page.getByText('补充或修订需求记录', { exact: true }).click();
  const draft = page.getByRole('textbox', { name: '需求标题', exact: true });
  await draft.fill('跨步骤保留但不提交的导航草稿');
  await step('资料识别').click(); await viewed('资料识别');
  await sideView('项目流程').click(); await sideView('资料与依据').click();
  await returnToEditor().click(); await viewed('资料识别');
  await step('需求确认').click(); await viewed('需求确认');
  assert.equal(await draft.inputValue(), '跨步骤保留但不提交的导航草稿');
  assert.equal(await leaveDialog().count(), 0, 'switching mounted work surfaces does not offer to discard retained fields');
  await page.goBack(); await viewed('资料识别');
  await page.goForward(); await viewed('需求确认');
  assert.equal(await draft.inputValue(), '跨步骤保留但不提交的导航草稿');
  await capture('02-live-draft-retained');
  await page.getByRole('button', { name: '取消填写', exact: true }).click();
  await page.getByRole('dialog', { name: '放弃未保存的需求填写', exact: true }).getByRole('button', { name: '放弃填写', exact: true }).click();
  checks.push('step, auxiliary and same-case history switches preserve unsaved fields without business writes');

  checkpoint = 'cross-module blocked Back preserves history and project list filters';
  await page.goto(base + '/?rd_view=projects&q=' + encodeURIComponent('隔离导航') + '&page=2');
  await page.getByRole('button', { name: project.title, exact: true }).click();
  await page.getByRole('article', { name: researchCase.title, exact: true }).getByRole('button', { name: '继续办理', exact: true }).click();
  await viewed('需求确认');
  const cleanCaseUrl = page.url();
  await page.getByText('补充或修订需求记录', { exact: true }).click();
  await draft.fill('后退取消后应完整保留');
  await page.goBack(); await leaveDialog().waitFor();
  await leaveDialog().getByRole('button', { name: '继续编辑', exact: true }).click();
  await viewed('需求确认'); assert.equal(page.url(), cleanCaseUrl);
  assert.equal(await draft.inputValue(), '后退取消后应完整保留');
  await page.goBack(); await leaveDialog().getByRole('button', { name: '放弃填写并切换', exact: true }).click();
  await page.getByRole('article', { name: researchCase.title, exact: true }).waitFor();
  await assertRoute({ project: project.id, case: null, q: '隔离导航', page: '2' });
  await page.goForward(); await viewed('需求确认');
  await page.getByText('补充或修订需求记录', { exact: true }).click();
  assert.equal(await draft.inputValue(), '', 'confirmed leave unmounts and discards only the unsaved local fields');
  await page.goBack(); await page.getByRole('article', { name: researchCase.title, exact: true }).waitFor();
  await page.goBack(); await page.getByRole('heading', { name: '项目空间', level: 1, exact: true }).waitFor();
  await assertRoute({ project: null, case: null, q: '隔离导航', page: '2' });
  assert.equal(await page.getByRole('textbox', { name: '搜索项目、客户、产品或业务流程', exact: true }).inputValue(), '隔离导航');
  await capture('03-filtered-list-return');
  checks.push('cancelled Back restores the same route; confirmed Back follows the original entry and Forward remains available; filters survive');

  checkpoint = 'returning from a case restores the scrolled filtered project list';
  await page.setViewportSize({ width: 1440, height: 500 });
  const listEntry = page.getByRole('article', { name: project.title, exact: true }).locator('.rd-project-continue').filter({ hasText: researchCase.title });
  await listEntry.evaluate(element => element.scrollIntoView({ block: 'center' }));
  const listScroll = await page.locator('.rd-application-shell').evaluate(element => element.scrollTop);
  assert(listScroll > 0, 'the filtered list is actually scrolled before opening the case');
  await listEntry.click(); await viewed('需求确认');
  await page.goBack(); await page.getByRole('heading', { name: '项目空间', level: 1, exact: true }).waitFor();
  await assertRoute({ project: null, case: null, q: '隔离导航', page: '2' });
  await page.waitForFunction(expected => Math.abs((document.querySelector('.rd-application-shell')?.scrollTop ?? 0) - expected) <= 2, listScroll);
  await page.setViewportSize({ width: 1440, height: 1000 });
  checks.push('returning directly from a case restores the filtered list page and its previous scroll position');

  checkpoint = 'repeated evidence requests reopen and focus the requested section';
  await page.goto(base + caseUrl + '&case_view=current&step=requirements'); await viewed('需求确认');
  for (let iteration = 0; iteration < 2; iteration++) {
    await page.getByRole('button', { name: '查看历史记录', exact: true }).click();
    await assertRoute({ case_view: 'evidence', evidence: 'history' });
    const history = page.locator('#rd-evidence-history');
    await page.waitForFunction(() => document.activeElement?.id === 'rd-evidence-history');
    assert(await history.evaluate(element => element.open), 'the explicitly requested history section is expanded');
    await history.locator(':scope > summary').click();
    await returnToEditor().click(); await viewed('需求确认');
  }
  await overview().click();
  await page.getByRole('button', { name: '查看全部成果与依据 →', exact: true }).click();
  await assertRoute({ case_view: 'evidence', evidence: 'artifacts' });
  await page.waitForFunction(() => document.activeElement?.id === 'rd-evidence-artifacts');
  await page.reload();
  await page.waitForFunction(() => document.activeElement?.id === 'rd-evidence-artifacts');
  checks.push('repeated history requests and refreshed artifact links expand and focus the correct evidence section');

  checkpoint = 'artifact navigation chooses the referenced workpackage and survives reload';
  await page.goto(base + '/?rd_view=projects&project=navigation-project&case=execution-case&case_view=evidence&evidence=artifacts');
  const artifact = page.locator('.rd-evidence-record').filter({ has: page.getByRole('link', { name: 'target-package.docx · 下载 ↗', exact: true }) });
  await artifact.getByRole('button', { name: '查看对应工作包与固定快照 →', exact: true }).click();
  await viewed('编排与生成'); await assertRoute({ case_view: 'current', step: 'workpackages', workpackage: 'target-package' });
  assert.equal(await page.locator('.rd-workpackage-summary > code').innerText(), 'target-package');
  await page.reload(); await viewed('编排与生成');
  assert.equal(await page.locator('.rd-workpackage-summary > code').innerText(), 'target-package');
  await page.goBack(); await assertRoute({ case_view: 'evidence', evidence: 'artifacts' });
  await artifact.waitFor();
  checks.push('artifact navigation selects its actual workpackage, survives refresh and returns to the evidence page');

  checkpoint = 'a completed overview returns to execution records instead of opening itself again';
  await page.goto(base + '/?rd_view=projects&project=navigation-project&case=completed-case&case_view=current&step=current');
  await page.getByRole('heading', { name: '当前成果', level: 1, exact: true }).waitFor();
  await returnToEditor().click(); await viewed('编排与生成'); await assertRoute({ step: 'workpackages' });
  await page.getByRole('heading', { name: '工作包计划与执行', exact: true }).waitFor();
  checks.push('completed workflows return from overview to execution records rather than looping on overview');

  await page.goto(base + caseUrl + '&case_view=current&step=requirements'); await viewed('需求确认');
  await sideView('资料与依据').click();

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await returnToEditor().click(); await viewed('需求确认');
    await sideView('项目流程').click();
    assert(await returnToEditor().isVisible());
    assert(await page.locator('.rd-application-shell').evaluate(element => element.scrollWidth <= element.clientWidth + 1));
    await capture('04-navigation-' + width);
  }
  checks.push('return navigation remains reachable at 1440px and 390px without horizontal shell overflow');
  assert.deepEqual(writes, [], 'navigation and local draft editing never submit business operations');
  assert.deepEqual(unexpected, []); assert.deepEqual(pageErrors, []);
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ status: 'passed', checks, screenshots, writes, unexpected, pageErrors, realApiRequests: 0, realModelCalls: 0, evidence_category: 'isolated_browser_api_fixture', notCovered: ['real project writes', 'model generation', 'OA authentication', 'other modules and full suite'] }, null, 2));
  console.log('PASS: ' + checks.join('; '));
} catch (error) {
  await capture('failure').catch(() => {});
  await writeFile(join(output, 'failure.json'), JSON.stringify({ checkpoint, message: error.message, url: page.url(), checks, writes, unexpected, pageErrors, body: await page.locator('body').innerText().catch(() => ''), realApiRequests: 0, realModelCalls: 0 }, null, 2));
  throw error;
} finally { await browser.close(); }
