/** Real project/workflow UI with isolated API reads and writes. No model or generation request. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || '../docs/rd-platform/verification/screenshots/2026-11-04-project-workflow-entry';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const errors = [], checks = [], mutations = [], unexpected = [], catalogReads = [];
const productCatalog = { product_types: [
  { value: 'liquid_cooling_pipeline', label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }, { value: 'civilian', label: '民品' }] },
  { value: 'electrical_connector', label: '电连接器', enabled: true, domains: [{ value: 'aviation', label: '航空质量体系' }] },
] };
let productCatalogFailure = true, productCatalogHold = null;
const page = await browser.newPage({ viewport: { width: 1520, height: 980 } });
page.setDefaultTimeout(15000);
page.on('pageerror', error => errors.push(error.message));
const snap = name => page.screenshot({ path: join(output, name + '.png') });
const catalogResponse = () => page.waitForResponse(response => new URL(response.url()).pathname === '/api/rd/catalog');
const focusWindow = () => page.evaluate(() => { window.dispatchEvent(new Event('focus')); });
const hideWindow = () => page.evaluate(() => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  document.dispatchEvent(new Event('visibilitychange'));
});
const returnVisible = () => page.evaluate(() => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  document.dispatchEvent(new Event('visibilitychange'));
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  document.dispatchEvent(new Event('visibilitychange'));
  window.dispatchEvent(new Event('focus'));
});
// Observe a settled activation event window before asserting that no read occurred.
const settleEvents = () => page.waitForTimeout(250);
const waitForCatalogIdle = target => target.getByText('正在读取已发布流程模板…', { exact: true }).waitFor({ state: 'hidden' });
const workflowControl = target => target.getByRole('combobox', { name: /^流程模板/ }).locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]');
const showWorkflowOptions = async target => { await workflowControl(target).click(); };
const classificationControl = (target, name) => target.getByRole('combobox', { name: new RegExp('^' + name) });
const chooseClassification = async (target, name, option) => {
  await classificationControl(target, name).locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').click();
  await page.getByRole('option', { name: option, exact: true }).click();
};
try {
  const ids = ['input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start', 'taskbook'];
  const titles = ['资料受理', '需求确认', '成熟产品比对', '选型决定', '研发启动依据', '研制任务书生成'];
  const template = { id: 'taskbook-generation', version: '1', head_version: '1', category: 'project', title: '研制任务书生成流程', status: 'published', publication_revision: 1, digest: 'fixture-version-one',
    graph: { nodes: ids.map((id, index) => ({ id, title: titles[index], role: '研发工程师', deliverables: [titles[index] + '记录'], position: { x: index * 240, y: 0 },
      ...({ confirm_requirements: 'requirements', selection_decision: 'selection', rd_start: 'rd_start' }[id] ? { gate: { confirm_requirements: 'requirements', selection_decision: 'selection', rd_start: 'rd_start' }[id] } : {}),
      ...(id === 'taskbook' ? { action_resource: { resource_id: 'taskbook-authoring-team', resource_version: 1 }, workpackage_definition_id: 'taskbook' } : {}),
    })), edges: ids.slice(1).map((id, index) => ({ id: 'edge-' + index, source: ids[index], target: id })) },
  };
  const catalog = { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书生成', status: 'published', initial_stage: 'input', context_fields: [] }], actions: [], workpackage_definitions: [], project_workflow_templates: [template] };
  const seed = catalog.project_workflow_templates.find(item => item.id === 'taskbook-generation');
  assert(seed && seed.status === 'published');
  assert.deepEqual(seed.graph.nodes.map(item => item.id), ['input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start', 'taskbook']);
  assert.equal(seed.graph.nodes.at(-1).title, '研制任务书生成');
  const directory = items => ({ items, total: items.length, page: 1, page_size: 5, total_pages: 1 });
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (request.method() === 'GET') {
      if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
      if (path === '/api/rd/assistant/weather') return route.fulfill({ json: { configured: false, available: false } });
      if (path === '/api/models') return route.fulfill({ json: { success: true, models: [] } });
      if (path === '/api/product_catalog') {
        const hold = productCatalogHold;
        if (hold) { hold.started(); await hold.wait; }
        return route.fulfill(productCatalogFailure ? { status: 503, json: { error: '隔离产品目录暂不可用' } } : { json: productCatalog });
      }
      if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'fixture-owner', local_mode: true } });
      if (path === '/api/rd/catalog') { catalogReads.push(path); return route.fulfill({ json: catalog }); }
      if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [] } });
      if (path === '/api/rd/governance/session') return route.fulfill({ json: { can_edit_workflows: false, can_publish_workflows: false, can_prepare_templates: false, can_review_templates: false, can_publish_templates: false, local_bootstrap: true } });
      if (path === '/api/rd/workflow-templates') return route.fulfill({ json: directory([seed]) });
      if (path === '/api/rd/catalog/items' || path === '/api/rd/catalog/resources') return route.fulfill({ json: directory([]) });
      if (path === '/api/rd/workflow-templates/' + seed.id + '/history') return route.fulfill({ json: { ...directory([seed]), events: [], usages: [] } });
      if (path.startsWith('/api/rd/workflow-templates/' + seed.id + '/')) return route.fulfill({ json: seed });
      if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: 'input', project_version: 2, input_revision: 1 } } });
    }
    unexpected.push({ method: request.method(), path });
    return route.fulfill({ status: 500, json: { detail: '未预期的隔离测试请求' } });
  });
  await page.goto(base + '/?rd_view=flows');
  await page.getByRole('heading', { name: seed.title, exact: true }).waitFor();
  assert.equal(await page.getByRole('combobox', { name: '流程用途', exact: true }).count(), 1);
  assert.equal(await page.locator('.rd-graph-node').count(), 6);
  assert.equal(await page.getByRole('tab', { name: '业务场景', exact: true }).count(), 0);
  await page.locator('.rd-management-data-state .rd-loading').waitFor({ state: 'hidden' });
  await page.locator('.rd-graph-editor').scrollIntoViewIfNeeded();
  await snap('01-隔离已发布流程模板');
  const firstOpenReads = catalogReads.length;
  await Promise.all([catalogResponse(), page.getByRole('button', { name: '使用此流程新建项目', exact: true }).click()]);
  const dialog = page.getByRole('dialog', { name: '新建项目', exact: true });
  await dialog.waitFor();
  await waitForCatalogIdle(dialog);
  await dialog.getByRole('alert').filter({ hasText: '产品分类读取失败' }).waitFor();
  assert(await classificationControl(dialog, '产品类型').isDisabled());
  assert(await classificationControl(dialog, '质量管理体系分类').isDisabled());
  assert((await workflowControl(dialog).innerText()).includes(seed.title), 'product catalog failure does not discard the workflow catalog selection');
  await snap('10-产品目录失败独立反馈');
  productCatalogFailure = false;
  let releaseProductCatalog, productCatalogStarted;
  const productCatalogWaiting = new Promise(resolve => { productCatalogStarted = resolve; });
  productCatalogHold = { started: productCatalogStarted, wait: new Promise(resolve => { releaseProductCatalog = resolve; }) };
  await Promise.all([productCatalogWaiting, dialog.getByRole('button', { name: '重新读取产品分类', exact: true }).click()]);
  await dialog.getByText('正在读取产品分类…', { exact: true }).waitFor();
  assert(await classificationControl(dialog, '产品类型').isDisabled());
  assert.equal(mutations.length, 0);
  productCatalogHold = null; releaseProductCatalog();
  await dialog.getByText('正在读取产品分类…', { exact: true }).waitFor({ state: 'hidden' });
  checks.push('产品目录失败与流程目录独立；重读期间两分类禁用，恢复不预选且无写入');
  assert.ok(catalogReads.length > firstOpenReads, 'opening from a workflow refreshes the project template catalog');
  assert.equal(await dialog.getByRole('button', { name: '刷新模板目录', exact: true }).count(), 0, 'creation refreshes the catalog automatically without a manual refresh button');
  assert((await workflowControl(dialog).locator('.ant-select-selection-item').innerText()).includes(seed.title));
  assert.equal(await dialog.getByText('业务场景', { exact: true }).count(), 0);
  await snap('02-流程模板发起项目');
  await chooseClassification(dialog, '产品类型', '液冷产品-液冷管路');
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  const discardClassification = page.getByRole('dialog', { name: '关闭当前创建', exact: true });
  await discardClassification.waitFor();
  await discardClassification.getByRole('button', { name: '继续填写', exact: true }).click();
  assert((await classificationControl(dialog, '产品类型').locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').innerText()).includes('液冷产品-液冷管路'), 'classification-only changes participate in the unsaved form guard');
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await discardClassification.getByRole('button', { name: '关闭创建', exact: true }).click();
  checks.push('隔离发布目录同源，模板画布六节点，点击发起不创建项目');

  // Rename and version the server fixture to prove the picker is registry-driven.
  const selected = { ...structuredClone(seed), version: '2', head_version: '2', title: '受控任务书流程修订测试', digest: 'fixture-version-two' };
  let catalogFailure = false, empty = false, createFailure = false;
  let offered = [selected], createHold = null, catalogHold = null;
  const createRequests = [];
  let expectedContext = { product_type: 'liquid_cooling_pipeline', product_domain: 'military', cover_phase: 'F', organization_scope: 'non_central_research' };
  const fixed = { ...selected, template_id: selected.id, template_version: selected.version, template_digest: selected.digest, node_states: {} };
  const researchCase = { id: 'fixture-case', title: '流程模板创建验收', scenario_id: 'taskbook', stage: 'input', status: 'active', input_revision: 1,
    context: {}, model_selection: { provider: '', name: '', id: '' }, product_route: null, composition_route: null,
    sources: [], source_selection: {}, requirements: [], workpackages: [], decisions: [], warnings: [], clarifications: [], comparisons: [], deliveries: [], reuse_candidates: [],
    workflow_templates: { project: fixed }, project_workflow_status: { status: 'pending', template_id: selected.id, template_version: '2', template_digest: selected.digest, terminal_node_id: 'taskbook' },
    business_lifecycle: { policy_version: 'v2', rd_activation_state: 'not_started', can_confirm_requirements: true, local_review_enabled: true },
  };
  let project = { id: 'fixture-project', title: researchCase.title, version: 1, owner_id: 'fixture-owner', members: [], cases: [], events: [] };
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (!path.startsWith('/api/')) return route.fallback();
    if (path === '/api/rd/catalog') {
      catalogReads.push(path);
      const response = catalogFailure ? { status: 503, json: { detail: '目录读取测试失败' } } : { json: structuredClone({ ...catalog, project_workflow_templates: empty ? [] : offered }) };
      const hold = catalogHold; catalogHold = null;
      if (hold) { hold.started(); await hold.wait; }
      return route.fulfill(response);
    }
    if (path === '/api/rd/projects' && request.method() === 'GET') return route.fulfill({ json: { projects: project.cases.length ? [project] : [] } });
    if (path === '/api/rd/projects' && request.method() === 'POST') {
      const body = request.postDataJSON(); mutations.push(body); createRequests.push({ body, key: request.headers()['idempotency-key'] || '' });
      assert.deepEqual(body.context, expectedContext, 'creation sends selected classifications and authoring options');
      project.context = structuredClone(body.context);
      if (createHold) await createHold;
      if (createFailure) return route.abort('failed'); return route.fulfill({ json: project });
    }
    if (path === '/api/rd/projects/fixture-project/commands') {
      const body = request.postDataJSON(); mutations.push(body);
      assert.equal(body.command, 'create_case');
      assert.deepEqual(body.data.workflow_template, { id: selected.id, version: selected.version, digest: selected.digest });
      assert.equal('scenario_id' in body.data, false);
      assert.equal('context' in body.data, false, 'case creation inherits project classifications without a separate competing context');
      researchCase.context = structuredClone(project.context);
      project = { ...project, version: 2, cases: [researchCase] };
      return route.fulfill({ json: project });
    }
    if (path === '/api/rd/projects/fixture-project') return route.fulfill({ json: project });
    return route.fallback();
  });
  await page.goto(base + '/?rd_view=projects');
  await page.getByRole('button', { name: '新建项目', exact: true }).waitFor();
  await page.getByRole('button', { name: '新建项目', exact: true }).click({ trial: true });
  const explicitChoice = { ...selected, id: 'fixture-explicit-workflow', version: '1', head_version: '1', title: '用户选择的固定流程', digest: 'fixture-explicit-one' };
  offered = [selected, explicitChoice];
  const newProjectReads = catalogReads.length;
  await Promise.all([catalogResponse(), page.getByRole('button', { name: '新建项目', exact: true }).click()]);
  await dialog.waitFor();
  await waitForCatalogIdle(dialog);
  assert.ok(catalogReads.length > newProjectReads, 'opening new project rereads a catalog changed after the page loaded');
  await showWorkflowOptions(dialog);
  await page.getByRole('option', { name: `${explicitChoice.title} · V1`, exact: true }).click();
  assert((await workflowControl(dialog).locator('.ant-select-selection-item').innerText()).includes(explicitChoice.title));
  const newerChoice = { ...explicitChoice, version: '2', head_version: '2', digest: 'fixture-explicit-two' };
  offered = [selected, newerChoice];
  const focusReads = catalogReads.length;
  await Promise.all([catalogResponse(), focusWindow()]);
  await waitForCatalogIdle(dialog);
  assert.ok(catalogReads.length > focusReads, 'focus return automatically refreshes an open dialog');
  assert((await workflowControl(dialog).locator('.ant-select-selection-item').innerText()).includes('V1'), 'focus refresh retains the explicitly selected historical version');
  await showWorkflowOptions(dialog);
  await page.getByRole('option', { name: `${newerChoice.title} · V2`, exact: true }).waitFor();
  await page.keyboard.press('Escape');
  const hiddenReads = catalogReads.length;
  await hideWindow(); await focusWindow(); await settleEvents();
  assert.equal(catalogReads.length, hiddenReads, 'a hidden tab does not refresh the catalog');
  const visibleReads = catalogReads.length;
  await Promise.all([catalogResponse(), returnVisible()]);
  await waitForCatalogIdle(dialog);
  await settleEvents();
  assert.equal(catalogReads.length, visibleReads + 1, 'visible and focus return coalesce into one automatic catalog refresh');
  assert((await workflowControl(dialog).locator('.ant-select-selection-item').innerText()).includes(`${explicitChoice.title} · V1`), 'visibility refresh does not silently replace a fixed choice');
  await showWorkflowOptions(dialog);
  await page.getByRole('option', { name: `${selected.title} · V2`, exact: true }).click();
  assert((await workflowControl(dialog).locator('.ant-select-selection-item').innerText()).includes(selected.title));
  assert((await workflowControl(dialog).locator('.ant-select-selection-item').innerText()).includes('V2'));
  checks.push('打开新建项目自动重读目录；focus和visible返回更新可选项，保留用户已选固定版本');

  const oldDirectoryChoice = { ...selected, id: 'fixture-slow-old-workflow', title: '过期慢响应中的流程', digest: 'fixture-slow-old' };
  const freshDirectoryChoice = { ...selected, id: 'fixture-return-fresh-workflow', title: '返回后发布的新流程', digest: 'fixture-return-fresh' };
  offered = [selected, oldDirectoryChoice];
  let releaseOldCatalog, oldCatalogStarted;
  const oldCatalogWaiting = new Promise(resolve => { oldCatalogStarted = resolve; });
  catalogHold = { started: oldCatalogStarted, wait: new Promise(resolve => { releaseOldCatalog = resolve; }) };
  await Promise.all([oldCatalogWaiting, focusWindow()]);
  const pendingCatalogReads = catalogReads.length;
  offered = [selected, freshDirectoryChoice];
  await Promise.all([
    catalogResponse(),
    page.waitForRequest(request => new URL(request.url()).pathname === '/api/rd/catalog'),
    focusWindow(),
  ]);
  assert.ok(catalogReads.length > pendingCatalogReads, 'returning while an older catalog read is pending starts a fresh read');
  await waitForCatalogIdle(dialog);
  await showWorkflowOptions(dialog);
  await page.getByRole('option', { name: `${freshDirectoryChoice.title} · V2`, exact: true }).waitFor();
  assert.equal(await page.getByRole('option', { name: `${oldDirectoryChoice.title} · V2`, exact: true }).count(), 0);
  await page.keyboard.press('Escape');
  releaseOldCatalog();
  await settleEvents();
  await showWorkflowOptions(dialog);
  await page.getByRole('option', { name: `${freshDirectoryChoice.title} · V2`, exact: true }).waitFor();
  assert.equal(await page.getByRole('option', { name: `${oldDirectoryChoice.title} · V2`, exact: true }).count(), 0, 'late old response does not overwrite the refreshed directory');
  await snap('07-并发重读保留新目录');
  await page.keyboard.press('Escape');
  assert((await workflowControl(dialog).locator('.ant-select-selection-item').innerText()).includes(`${selected.title} · V2`), 'overlapping reads also retain the chosen fixed workflow');
  offered = [selected, newerChoice];
  checks.push('旧目录慢请求未完成时返回仍发新GET；新目录生效后迟到旧响应不能覆盖，已选固定版本保留');

  await dialog.getByLabel('项目名称', { exact: false }).fill(researchCase.title);
  await dialog.getByRole('button', { name: '创建并开始', exact: true }).click();
  await dialog.getByRole('alert').filter({ hasText: /产品类型/ }).waitFor();
  assert.equal(mutations.length, 0, 'missing product type cannot create anything');
  for (const name of ['产品类型', '质量管理体系分类']) {
    const field = classificationControl(dialog, name);
    assert.equal(await field.getAttribute('aria-required'), 'true');
    assert.equal(await field.getAttribute('aria-invalid'), 'true');
    assert.equal(await field.getAttribute('aria-describedby'), 'rd-create-error');
  }
  assert(await classificationControl(dialog, '质量管理体系分类').isDisabled());
  await chooseClassification(dialog, '产品类型', '液冷产品-液冷管路');
  await dialog.getByRole('alert').filter({ hasText: '请选择产品类型和质量管理体系分类。' }).waitFor({ state: 'hidden' });
  await dialog.getByRole('button', { name: '创建并开始', exact: true }).click();
  await dialog.getByRole('alert').filter({ hasText: /质量管理体系/ }).waitFor();
  assert.equal(mutations.length, 0, 'missing quality classification cannot create anything');
  assert.equal(await classificationControl(dialog, '产品类型').getAttribute('aria-invalid'), 'false');
  assert.equal(await classificationControl(dialog, '质量管理体系分类').getAttribute('aria-invalid'), 'true');
  await chooseClassification(dialog, '质量管理体系分类', '军品');
  await dialog.getByRole('alert').filter({ hasText: '请选择产品类型和质量管理体系分类。' }).waitFor({ state: 'hidden' });
  await chooseClassification(dialog, '产品类型', '电连接器');
  await classificationControl(dialog, '质量管理体系分类').locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').click();
  await page.getByRole('option', { name: '航空质量体系', exact: true }).waitFor();
  assert.equal(await page.getByRole('option', { name: '军品', exact: true }).count(), 0, 'quality options follow the selected product type');
  await page.keyboard.press('Escape');
  await dialog.getByRole('button', { name: '创建并开始', exact: true }).click();
  await dialog.getByRole('alert').filter({ hasText: /质量管理体系/ }).waitFor();
  assert.equal(mutations.length, 0, 'changing product type clears the incompatible quality value');
  await chooseClassification(dialog, '产品类型', '液冷产品-液冷管路');
  await chooseClassification(dialog, '质量管理体系分类', '军品');
  assert.equal(await dialog.getByRole('alert').count(), 0, 'classification corrections clear their validation message before submission');
  assert.equal(await dialog.locator('.rd-create-options').getAttribute('open'), null, 'advanced authoring options are collapsed by default');
  assert((await dialog.locator('.rd-create-options summary').innerText()).includes('F · 非中央研究院产品'));
  await dialog.locator('.rd-create-options summary').click();
  await classificationControl(dialog, '封面研制阶段').waitFor();
  await chooseClassification(dialog, '封面研制阶段', 'S');
  await chooseClassification(dialog, '产品归属范围', '中央研究院产品');
  assert((await dialog.locator('.rd-create-options summary').innerText()).includes('S · 中央研究院产品'));
  await page.setViewportSize({ width: 390, height: 844 });
  await snap('10-窄屏更多编制选项');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  await page.setViewportSize({ width: 1520, height: 980 });
  await chooseClassification(dialog, '封面研制阶段', 'F');
  await chooseClassification(dialog, '产品归属范围', '非中央研究院产品');
  await snap('11-更多编制选项展开');
  await dialog.locator('.rd-create-options summary').click();
  checks.push('更多编制选项默认折叠，F与非中央研究院默认值；可切换阶段和归属，窄屏不溢出');
  await snap('08-项目分类必填与联动');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  await snap('09-窄屏项目分类');
  await page.setViewportSize({ width: 1520, height: 980 });
  checks.push('产品与质量体系均必填且关联字段错误；修改分类即时清除必填提示；质量选项随产品联动，失配值清空；空值不创建且390px无横溢出');
  await dialog.getByRole('button', { name: '创建并开始', exact: true }).evaluate(element => { element.click(); element.click(); });
  await page.getByRole('heading', { name: '资料识别与项目信息', exact: true }).waitFor();
  assert((await page.locator('.rd-case-heading .rd-case-kind').innerText()).includes(researchCase.title), 'created project title remains in the workspace context');
  assert.equal(mutations.length, 2);
  assert.deepEqual(researchCase.context, { product_type: 'liquid_cooling_pipeline', product_domain: 'military', cover_phase: 'F', organization_scope: 'non_central_research' });
  assert.equal(await page.locator('.rd-analysis-context-item').filter({ hasText: /封面阶段|组织范围/ }).count(), 0);
  checks.push('创建固定来自目录的 id/version/digest，保存四项建项参数且资料分析不重复展示，无业务场景入参');
  await page.getByRole('button', { name: '项目流程', exact: true }).click();
  const overview = page.getByRole('region', { name: '项目固定流程', exact: true });
  await overview.waitFor();
  assert.equal(await overview.locator('.rd-graph-node').count(), 6);
  assert.equal(await page.getByRole('list', { name: '案例八阶段业务流程', exact: true }).count(), 0);
  assert.equal(await overview.getByText('方案设计', { exact: true }).count(), 0);
  await snap('03-隔离项目固定六节点画布');
  await page.setViewportSize({ width: 390, height: 844 });
  await overview.scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  await snap('04-窄屏项目流程');
  checks.push('项目读取固定图，六节点终止；窄屏无页面横向溢出');
  researchCase.stage = 'planning';
  researchCase.product_route = { value: 'modification', rationale: 'fixture', source_ids: [] };
  researchCase.composition_route = { value: 'direct', rationale: 'fixture', source_ids: [] };
  await page.setViewportSize({ width: 1520, height: 980 });
  await page.goto(base + '/?rd_view=projects&project=fixture-project&case=fixture-case');
  await page.getByRole('navigation', { name: '办理步骤', exact: true }).getByRole('button', { name: '编制准备', exact: true }).click();
  await page.getByRole('region', { name: '编制依据', exact: true }).waitFor();
  assert.equal(await page.getByRole('combobox', { name: '研发流程模板', exact: true }).count(), 0);
  await page.getByLabel('本次任务书编制范围', { exact: true }).waitFor();
  await snap('06-沿用项目固定模板');
  researchCase.project_workflow_status.status = 'completed';
  await page.goto(base + '/?rd_view=projects&project=fixture-project&case=fixture-case');
  await page.getByRole('heading', { name: '研制任务书生成成果', exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: /批准任务书范围/ }).count(), 0);
  assert.equal(await page.getByRole('button', { name: '本阶段业务确认 →', exact: true }).count(), 0);
  checks.push('任务书准备沿用固定模板，完成后不要求范围批准或后续工程节点');
  await page.goto(base + '/?rd_view=projects');
  const completedRow = page.locator('.rd-project-continue').first();
  await completedRow.waitFor();
  assert((await completedRow.innerText()).includes('已完成'));
  assert((await completedRow.innerText()).includes('查看成果'));
  checks.push('项目空间按当前流程状态显示完成与查看成果');
  await page.getByRole('button', { name: '研发管理', exact: true }).click();
  await page.getByRole('combobox', { name: '工作范围', exact: true }).focus();
  await page.keyboard.press('ArrowDown');
  await page.getByRole('option', { name: '已完成案例', exact: true }).click();
  await page.locator('.rd-management-table tbody tr').first().waitFor();
  assert((await page.locator('.rd-management-table tbody').innerText()).includes(project.title));
  checks.push('研发管理已完成筛选与项目流程终态一致');

  await page.goto(base + '/?rd_view=projects&project=fixture-project');
  await page.getByRole('heading', { name: project.title, level: 1, exact: true }).waitFor();
  const addCaseReads = catalogReads.length;
  await Promise.all([catalogResponse(), page.getByRole('button', { name: '新增业务流程', exact: true }).click()]);
  const addCaseDialog = page.getByRole('dialog', { name: '新增业务流程', exact: true });
  await addCaseDialog.waitFor();
  await waitForCatalogIdle(addCaseDialog);
  assert.ok(catalogReads.length > addCaseReads, 'opening a new workflow also rereads the catalog');
  assert.equal(await addCaseDialog.getByRole('button', { name: '刷新模板目录', exact: true }).count(), 0);
  await addCaseDialog.getByRole('button', { name: '取消', exact: true }).click();
  await page.getByRole('button', { name: '流程管理', exact: true }).click();
  await page.getByRole('heading', { name: seed.title, exact: true }).waitFor();
  const returnedChoice = { ...selected, id: 'fixture-returned-workflow', title: '流程管理返回后新增的模板', digest: 'fixture-returned' };
  offered = [selected, returnedChoice];
  const returnReads = catalogReads.length;
  await Promise.all([catalogResponse(), page.getByRole('button', { name: '项目空间', exact: true }).click()]);
  assert.ok(catalogReads.length > returnReads, 'same-page return from workflow management refreshes the catalog');
  await Promise.all([catalogResponse(), page.getByRole('button', { name: '新建项目', exact: true }).click()]);
  await dialog.waitFor();
  await waitForCatalogIdle(dialog);
  await showWorkflowOptions(dialog);
  await page.getByRole('option', { name: `${returnedChoice.title} · V2`, exact: true }).waitFor();
  await page.keyboard.press('Escape');
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  checks.push('打开新增业务流程自动读目录；从流程管理同页返回后无需手动刷新即可使用新增模板');

  await page.goto(base + '/?rd_view=flows');
  await Promise.all([catalogResponse(), page.getByRole('button', { name: '使用此流程新建项目', exact: true }).click()]);
  await dialog.waitFor();
  await waitForCatalogIdle(dialog);
  assert((await workflowControl(dialog).locator('.ant-select-selection-item').innerText()).includes('V1'), 'published historical selection is retained even when the catalog offers V2');
  await dialog.getByLabel('项目名称', { exact: false }).fill('历史版本不确定请求验收');
  await chooseClassification(dialog, '产品类型', '液冷产品-液冷管路');
  await chooseClassification(dialog, '质量管理体系分类', '军品');
  await dialog.locator('.rd-create-options summary').click();
  await chooseClassification(dialog, '封面研制阶段', 'S');
  await chooseClassification(dialog, '产品归属范围', '中央研究院产品');
  expectedContext = { ...expectedContext, cover_phase: 'S', organization_scope: 'central_research' };
  createFailure = true;
  let releaseCreate;
  createHold = new Promise(resolve => { releaseCreate = resolve; });
  await Promise.all([page.waitForRequest(request => request.method() === 'POST' && new URL(request.url()).pathname === '/api/rd/projects'), dialog.getByRole('button', { name: '创建并开始', exact: true }).click()]);
  const pendingReads = catalogReads.length;
  assert(await classificationControl(dialog, '产品类型').isDisabled());
  assert(await classificationControl(dialog, '质量管理体系分类').isDisabled());
  assert(await classificationControl(dialog, '封面研制阶段').isDisabled());
  assert(await classificationControl(dialog, '产品归属范围').isDisabled());
  offered = [returnedChoice];
  await focusWindow(); await returnVisible(); await settleEvents();
  assert.equal(catalogReads.length, pendingReads, 'in-flight creation does not refresh the template catalog');
  assert((await workflowControl(dialog).locator('.ant-select-selection-item').innerText()).includes('V1'));
  createHold = null; releaseCreate();
  await dialog.getByRole('button', { name: '重试并核对', exact: true }).waitFor();
  assert(await classificationControl(dialog, '产品类型').isDisabled(), 'unknown creation locks the classified request snapshot');
  assert(await classificationControl(dialog, '质量管理体系分类').isDisabled());
  assert.equal(await dialog.getByRole('button', { name: '刷新模板目录', exact: true }).count(), 0, 'automatic refresh never exposes the removed manual button');
  const uncertainReads = catalogReads.length;
  await focusWindow(); await returnVisible(); await settleEvents();
  assert.equal(catalogReads.length, uncertainReads, 'an uncertain create does not refresh or replace its retry snapshot');
  assert((await workflowControl(dialog).locator('.ant-select-selection-item').innerText()).includes('V1'));
  await Promise.all([page.waitForEvent('requestfailed', { predicate: request => request.method() === 'POST' && new URL(request.url()).pathname === '/api/rd/projects' }), dialog.getByRole('button', { name: '重试并核对', exact: true }).click()]);
  await dialog.getByRole('button', { name: '重试并核对', exact: true }).waitFor();
  assert.deepEqual(createRequests.at(-1), createRequests.at(-2), 'retry retains the same request body and idempotency key');
  assert.ok(createRequests.at(-1).key);
  checks.push('创建中及网络结果未知时focus/visible不刷新；历史V1、请求正文和幂等重试键保持固定');
  createFailure = false;
  await page.setViewportSize({ width: 1520, height: 980 });
  empty = true;
  await page.goto(base + '/?rd_view=home');
  await Promise.all([catalogResponse(), page.getByRole('button', { name: '新建项目', exact: true }).click()]);
  await dialog.waitFor();
  await dialog.getByText('暂无可用于新建项目的已发布流程模板，请先在流程管理中校验并发布。', { exact: true }).waitFor();
  assert(await dialog.getByRole('button', { name: '创建并开始', exact: true }).isDisabled());
  await snap('05-无发布模板');
  catalogFailure = true;
  await Promise.all([catalogResponse(), focusWindow()]);
  await dialog.getByRole('alert').filter({ hasText: '流程模板读取失败' }).waitFor();
  assert(await dialog.getByRole('button', { name: '创建并开始', exact: true }).isDisabled());
  assert.equal(mutations.length, 4);
  catalogFailure = false; empty = false;
  offered = [selected];
  await Promise.all([catalogResponse(), returnVisible()]);
  await workflowControl(dialog).locator('.ant-select-selection-item').filter({ hasText: selected.title }).waitFor();
  assert(await dialog.getByRole('button', { name: '创建并开始', exact: true }).isEnabled());
  assert.equal(mutations.length, 4);
  checks.push('空目录和读取错误禁止创建，focus/visible自动恢复且无额外写入');
  assert.deepEqual(unexpected, [], 'every API request uses an explicit fixture');
  assert.deepEqual(errors, []);
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ checks, pageErrors: errors, unexpectedRequests: unexpected, fixtureMutations: mutations.length, catalogReads: catalogReads.length, realApiRequests: 0 }, null, 2));
  console.log(JSON.stringify({ passed: checks.length, checks, screenshots: output }));
} catch (error) {
  await snap('failure').catch(() => {});
  console.error(JSON.stringify({ completedChecks: checks, pageErrors: errors, unexpectedRequests: unexpected, fixtureMutations: mutations.length, catalogReads: catalogReads.length }));
  throw error;
} finally { await browser.close(); }
