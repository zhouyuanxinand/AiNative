/** Flow directory + canvas behavior. Draft mutations are fixtures; never run a generation. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const errors = [];
const snap = async (page, name) => { if (output) await page.screenshot({ path: join(output, name) }); };
const isUnfilteredActions = response => {
  const url = new URL(response.url());
  return url.pathname === '/api/rd/catalog/items' && url.searchParams.get('category') === 'actions' && !url.searchParams.get('q');
};
async function verifyTeamActionCards(page, directory) {
  assert(Array.isArray(directory.items) && directory.items.length > 0, 'the action directory contains granted fixed expert teams');
  assert(directory.items.every(item => item.kind === 'team'), 'P2 action entries are expert teams, not internal execution steps');
  await page.locator('.rd-flow-resource-card').first().waitFor();
  assert.equal(await page.locator('.rd-flow-resource-card').count(), directory.items.length, 'render the actual server page without assuming a fixed team count');
  assert.deepEqual(await page.locator('.rd-flow-resource-card > details:last-child > code').allTextContents(), directory.items.map(item => item.id), 'render the IDs returned for the granted team versions');
}
async function choose(page, label, option) {
  await page.getByRole('button', { name: label, exact: true }).click();
  await page.getByRole('option', { name: option, exact: true }).click();
}
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
  page.setDefaultTimeout(15000); page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', route => route.request().method() === 'GET' ? route.continue() : route.abort());
  await page.goto(`${base}/?rd_view=flows`);
  const canvas = page.getByRole('region', { name: '工作包节点预览', exact: true });
  await canvas.locator('.rd-canvas-node').first().waitFor();
  assert.equal(await canvas.locator('.rd-canvas-node').count(), 5);
  assert.equal(await canvas.locator('.rd-canvas-edges > path').count(), 4);
  await canvas.getByRole('button', { name: '生成研制任务书，模板节点', exact: true }).click();
  assert.equal(await page.locator('.rd-flow-node-inspector h4').innerText(), '生成研制任务书');
  const beforeZoom = await canvas.locator('.rd-canvas-scale').innerText();
  await canvas.getByRole('button', { name: '放大画布', exact: true }).click();
  assert.notEqual(await canvas.locator('.rd-canvas-scale').innerText(), beforeZoom);
  const beforePan = await canvas.locator('.rd-canvas-plane').getAttribute('style');
  await canvas.locator('.rd-canvas-viewport').focus(); await page.keyboard.press('ArrowLeft');
  assert.notEqual(await canvas.locator('.rd-canvas-plane').getAttribute('style'), beforePan);
  const bounds = await canvas.locator('.rd-canvas-viewport').boundingBox();
  const beforeDrag = await canvas.locator('.rd-canvas-plane').getAttribute('style');
  await page.mouse.move(bounds.x + 15, bounds.y + 15); await page.mouse.down(); await page.mouse.move(bounds.x + 70, bounds.y + 55, { steps: 4 }); await page.mouse.up();
  assert.notEqual(await canvas.locator('.rd-canvas-plane').getAttribute('style'), beforeDrag);
  await canvas.getByRole('button', { name: '适应画布', exact: true }).click();
  await canvas.getByRole('button', { name: '列表', exact: true }).click();
  assert.equal(await canvas.locator('.rd-canvas-list li').count(), 5);
  await canvas.getByRole('button', { name: '画布', exact: true }).click();
  await snap(page, '01-流程模板画布.png');
  await page.getByRole('button', { name: '研发流程', exact: true }).click();
  await page.getByRole('region', { name: '研发路径预览', exact: true }).waitFor();
  assert.equal(await page.locator('.rd-canvas-node').count(), 6);
  await snap(page, '02-研发路径画布.png');
  const resourcesTab = page.getByRole('tab', { name: '智能体与 Skill', exact: true });
  await resourcesTab.focus(); await page.keyboard.press('ArrowRight');
  assert.equal(await page.evaluate(() => document.activeElement.textContent), '动作模板');
  const initialActions = page.waitForResponse(isUnfilteredActions);
  await page.keyboard.press('Enter');
  await verifyTeamActionCards(page, await (await initialActions).json());
  await page.getByLabel('搜索动作模板', { exact: true }).fill('不存在的动作');
  await page.getByText('没有匹配的记录，请调整关键词。', { exact: true }).waitFor();
  const restoredActions = page.waitForResponse(isUnfilteredActions);
  await page.getByRole('button', { name: '清空搜索', exact: true }).click();
  const restoredDirectory = await (await restoredActions).json();
  await verifyTeamActionCards(page, restoredDirectory);
  const firstTeam = restoredDirectory.items[0];
  await page.getByText(`查看固定专家团组成 · ${firstTeam.id} V${firstTeam.version}`, { exact: true }).click();
  const teamDetail = page.getByRole('region', { name: '专家团固定组成与内部执行图', exact: true });
  await teamDetail.waitFor();
  const cardGraph = await teamDetail.locator('.rd-graph-structure').boundingBox();
  const cardInspector = await teamDetail.locator('.rd-graph-inspector').boundingBox();
  assert(cardInspector.y >= cardGraph.y + cardGraph.height - 1, 'a narrow directory card stacks its graph and inspector without overlap at desktop viewport widths');
  await snap(page, '03-动作模板目录.png');
  await resourcesTab.click();
  await page.locator('.rd-flow-resource-card').first().waitFor();
  await snap(page, '04-智能体与Skill目录.png');
  await page.getByRole('tab', { name: '报告模板', exact: true }).click();
  await page.locator('.rd-flow-resource-card').first().waitFor();
  const templateLink = await page.getByRole('link', { name: '下载当前模板 ↗' }).first().getAttribute('href');
  assert(templateLink.startsWith('/api/templates/'));
  await snap(page, '05-报告模板目录.png');
  if (await page.getByRole('button', { name: '下一页', exact: true }).isEnabled()) {
    await page.getByRole('button', { name: '下一页', exact: true }).click();
    assert(await page.locator('.rd-flow-resource-card').count() > 0);
  }
  await page.getByRole('tab', { name: '流程模板', exact: true }).click();
  await page.getByRole('button', { name: '工作包模板', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await canvas.scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  const scroll = page.locator('.rd-application-shell');
  await scroll.evaluate(element => { element.scrollTop = element.scrollHeight; });
  await page.getByRole('button', { name: '进入项目编排 →' }).scrollIntoViewIfNeeded();
  await snap(page, '06-窄屏底部可浏览.png');
  await canvas.getByRole('button', { name: '列表', exact: true }).click();
  await canvas.scrollIntoViewIfNeeded(); await snap(page, '07-窄屏节点列表.png');
  const catalog = await (await page.request.get(`${base}/api/rd/catalog`)).json();
  await page.close();

  // A v1 package without a flow draft enters the unified P2 designer; mutations remain isolated.
  const definition = catalog.workpackage_definitions.find(item => item.id === 'taskbook' && String(item.version) === '1');
  assert(definition, 'the compatibility fixture uses the v1 taskbook definition');
  const workpackage = { id: 'canvas-package', definition_id: 'taskbook', definition_version: '1', title: '画布交互验证工作包', stage: 'design', status: 'draft', plan_revision: 1, nodes: structuredClone(definition.nodes), artifacts: [], obligations: [], blocked_reasons: [] };
  const researchCase = { id: 'canvas-case', title: '液冷管路编排验证', scenario_id: 'taskbook', stage: 'design', status: 'active', input_revision: 1, context: {}, product_route: null, composition_route: null, sources: [], requirements: [], decisions: [], workpackages: [workpackage] };
  const project = { id: 'canvas-project', title: '画布交互验证（测试数据）', version: 1, owner_id: 'test', members: [], events: [], cases: [researchCase] };
  const teams = [{ id: 'taskbook-authoring-team', name: '任务书编制专家团（测试数据）' }, { id: 'consistency-team', name: '资料一致性专家团（测试数据）' }].map(item => ({ ...item, kind: 'team', version: 1, status: 'published', executable: true }));
  const authoringId = 'authoring-action';
  const fixture = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
  fixture.setDefaultTimeout(15000); fixture.on('pageerror', error => errors.push(error.message));
  let failSave = true, failResources = true; const commands = [];
  await fixture.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
    if (path === '/api/rd/catalog') return route.fulfill({ json: catalog });
    if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
    if (path === '/api/rd/projects/canvas-project') return route.fulfill({ json: project });
    if (path === '/api/models') return route.fulfill({ json: { success: true, models: [] } });
    if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: 'design', project_version: project.version } } });
    if (path.endsWith('/catalog/items')) return route.fulfill({ json: { items: teams, total: teams.length, total_pages: 1, page: 1, page_size: 5 } });
    if (path.endsWith('/workflow-templates')) return route.fulfill({ json: { items: [], total: 0, total_pages: 1, page: 1, page_size: 5 } });
    if (path.endsWith('/catalog/resources')) {
      if (failResources) { failResources = false; return route.fulfill({ status: 503, json: { error: '测试资源目录暂不可用' } }); }
      return route.fulfill({ json: { total: 1, page: 1, page_size: 5, total_pages: 1, items: [{ id: 'unbound', kind: 'agent', name: '未绑定智能体（测试数据）', description: '只验证目录状态。', version: 1, status: 'published', executable: false, available_versions: [1] }] } });
    }
    if (path.endsWith('/commands')) {
      const body = request.postDataJSON(); commands.push({ ...body, key: request.headers()['idempotency-key'] });
      assert.equal(body.data.case_id, 'canvas-case'); assert.equal(body.expected_version, project.version);
      assert.equal(body.data.workpackage_id, workpackage.id);
      assert(request.headers()['idempotency-key']);
      if (body.command === 'create_flow_draft') {
        // designer.default_graph collapses an untouched v1 required plan into its fixed authoring team.
        researchCase.flow_drafts = [{ id: 'canvas-draft', workpackage_id: workpackage.id, definition_id: 'taskbook', definition_version: '1', revision: 1, input_revision: 1, digest: 'draft-1', semantic_digest: 'semantic-1', layout_digest: 'layout-1', graph: { nodes: [{ id: authoringId, resource_id: 'taskbook-authoring-team', resource_version: 1, title: workpackage.title, role: '研发专家团', deliverables: [workpackage.title], position: { x: 24, y: 24 } }], edges: [] }, history: [], confirmed_fields: [], conflicts: [] }];
        workpackage.execution_schema_version = 3;
      } else if (body.command === 'apply_flow_patch') {
        const draft = researchCase.flow_drafts[0];
        assert.equal(body.data.expected_draft_revision, draft.revision);
        assert.equal(body.data.base_digest, draft.digest);
        assert.equal(body.data.origin, 'manual');
        if (failSave) { failSave = false; return route.fulfill({ status: 503, json: { error: '测试草稿保存失败，修改仍保留' } }); }
        for (const operation of body.data.operations) {
          const node = draft.graph.nodes.find(item => item.id === operation.node_id);
          if (operation.op === 'add_node') draft.graph.nodes.push(structuredClone(operation.node));
          else if (operation.op === 'remove_node') { draft.graph.nodes = draft.graph.nodes.filter(item => item.id !== operation.node_id); draft.graph.edges = draft.graph.edges.filter(edge => edge.source !== operation.node_id && edge.target !== operation.node_id); }
          else if (operation.op === 'set_node') Object.assign(node, operation.properties);
          else if (operation.op === 'move_node') node.position = structuredClone(operation.position);
          else if (operation.op === 'add_edge') draft.graph.edges.push(structuredClone(operation.edge));
          else throw new Error(`Unexpected fixture patch ${operation.op}`);
        }
        draft.revision++; draft.digest = 'draft-' + draft.revision;
      } else if (body.command === 'validate_flow_draft') {
        researchCase.flow_drafts[0].validation = { valid: true, errors: [], warnings: [] };
      } else if (body.command === 'prepare_execution_bundle') {
        const draft = researchCase.flow_drafts[0];
        const optional = draft.graph.nodes.find(node => node.resource_id === 'consistency-team');
        assert.deepEqual(draft.graph.edges.map(({ source, target }) => ({ source, target })), [{ source: optional.id, target: authoringId }]);
        const compiled = [{ id: 'check__consistency', action_id: 'consistency', action_version: '1', depends_on: [], required: false }, ...definition.nodes.map(node => ({ id: 'authoring__' + node.id, action_id: node.action_id, action_version: node.action_version, required: node.required, depends_on: node.depends_on.length ? node.depends_on.map(id => 'authoring__' + id) : ['check__consistency'] }))];
        researchCase.execution_candidates = [{ id: 'canvas-candidate', digest: 'candidate-fixed', draft_id: draft.id, draft_revision: draft.revision, workpackage_id: workpackage.id, input_revision: 1, graph: structuredClone(draft.graph), semantic_digest: 'semantic-fixed', layout_digest: 'layout-fixed', compiled_plan: compiled, mapping: compiled.map(node => ({ action_instance_id: node.id.startsWith('authoring__') ? authoringId : optional.id, step_instance_id: node.id, action_id: node.action_id })), resource_locks: teams.map(item => ({ resource_id: item.id, resource_version: item.version })), validation: { valid: true, errors: [], warnings: [] }, diff: { added: [optional.id], removed: [], changed: [authoringId], impact: '影响下次采用' } }];
      } else if (body.command === 'adopt_execution_bundle') {
        assert.equal(body.data.candidate_id, 'canvas-candidate'); assert.equal(body.data.candidate_digest, 'candidate-fixed');
        researchCase.execution_adoptions = [{ id: 'canvas-adoption', candidate_id: 'canvas-candidate', candidate_digest: 'candidate-fixed', workpackage_id: workpackage.id, actor: 'test' }];
        workpackage.execution_adoption_id = 'canvas-adoption';
        workpackage.nodes = structuredClone(researchCase.execution_candidates[0].compiled_plan);
        workpackage.plan_revision++;
      } else if (body.command === 'submit_workpackage') {
        assert.equal(workpackage.execution_adoption_id, 'canvas-adoption');
        workpackage.status = 'submitted';
      } else throw new Error(`Unexpected mutation ${body.command}`);
      project.version++; return route.fulfill({ json: project });
    }
    return route.fulfill({ json: path.endsWith('/session') ? { ok: true } : {} });
  });
  await fixture.goto(`${base}/?project=canvas-project&case=canvas-case`);
  await fixture.getByRole('button', { name: '检查计划并确认提交', exact: true }).click();
  const panel = fixture.getByRole('region', { name: '工作包计划与执行', exact: true });
  await panel.getByRole('button', { name: '建立流程草稿', exact: true }).click();
  const editor = panel.locator('.rd-flow-designer > .rd-graph-editor');
  await editor.locator('.rd-graph-node').first().waitFor();
  assert.equal(await editor.locator('.rd-graph-node').count(), 1, 'v1 default plan is represented by its fixed authoring team');
  const canvasArea = await editor.locator('.rd-graph-structure').boundingBox();
  const detailsArea = await editor.locator('.rd-graph-inspector').boundingBox();
  assert(canvasArea.width > detailsArea.width, 'full-width project editor keeps the canvas as the larger column');
  await choose(fixture, '新增节点的固定能力', '资料一致性专家团（测试数据） · V1');
  await panel.getByRole('button', { name: '添加节点', exact: true }).click();
  assert.equal(await editor.locator('.rd-graph-node').count(), 2);
  assert.equal(await panel.getByRole('button', { name: '准备执行候选', exact: true }).isDisabled(), true);
  await editor.getByRole('button', { name: '移除节点', exact: true }).click();
  assert.equal(await editor.locator('.rd-graph-node').count(), 1);
  await panel.getByRole('button', { name: '添加节点', exact: true }).click();
  await editor.getByLabel('X 坐标', { exact: true }).fill('80');
  await choose(fixture, '连线起点', '资料一致性专家团（测试数据）');
  await choose(fixture, '连线终点', workpackage.title);
  await editor.getByRole('button', { name: '添加连线', exact: true }).click();
  await panel.getByRole('button', { name: '保存草稿', exact: true }).click();
  await fixture.getByRole('alert').filter({ hasText: '测试草稿保存失败' }).first().waitFor();
  assert.equal(await editor.locator('.rd-graph-node').count(), 2);
  assert.equal(await editor.getByLabel('X 坐标', { exact: true }).inputValue(), '80');
  await panel.getByRole('button', { name: '保存草稿', exact: true }).click();
  await fixture.waitForFunction(() => document.querySelector('.rd-flow-designer')?.innerText.includes('草稿修订 2'));
  const saves = commands.filter(item => item.command === 'apply_flow_patch');
  assert.equal(saves.length, 2); assert.equal(saves[0].key, saves[1].key, 'retry keeps the same idempotency key');
  assert.deepEqual(saves[0].data, saves[1].data, 'retry preserves the complete patch and CAS base');
  const savedGraph = researchCase.flow_drafts[0].graph;
  const optionalNode = savedGraph.nodes.find(node => node.resource_id === 'consistency-team');
  assert.equal(optionalNode.position.x, 80);
  assert.deepEqual(savedGraph.edges.map(({ source, target }) => ({ source, target })), [{ source: optionalNode.id, target: authoringId }]);
  await editor.scrollIntoViewIfNeeded(); await snap(fixture, '08-v1工作包迁移流程草稿-测试数据.png');
  await fixture.setViewportSize({ width: 390, height: 844 });
  await editor.locator('.rd-graph-add').first().scrollIntoViewIfNeeded();
  assert.equal(await fixture.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  await snap(fixture, '09-窄屏编排操作-测试数据.png');
  await fixture.setViewportSize({ width: 1600, height: 1100 });
  await panel.getByRole('button', { name: '校验草稿', exact: true }).click();
  await panel.getByRole('heading', { name: '校验结果 · 通过', exact: true }).waitFor();
  await panel.getByRole('button', { name: '准备执行候选', exact: true }).click();
  await panel.getByRole('heading', { name: '固定执行候选', exact: true }).waitFor();
  assert.equal(await panel.getByRole('button', { name: '确认提交执行', exact: true }).isDisabled(), true);
  await panel.getByRole('button', { name: '采用此执行候选', exact: true }).click();
  assert.equal(commands.filter(item => item.command === 'adopt_execution_bundle').length, 0, 'adoption waits for its own confirmation');
  await fixture.getByRole('dialog').getByRole('button', { name: '采用固定候选', exact: true }).click();
  await panel.getByRole('button', { name: '已采用此候选', exact: true }).waitFor();
  assert.equal(commands.filter(item => item.command === 'submit_workpackage').length, 0, 'adoption does not submit execution');
  assert.equal(workpackage.status, 'draft');
  await fixture.getByRole('button', { name: '项目流程', exact: true }).click();
  const preview = fixture.getByRole('region', { name: '工作包执行图', exact: true });
  await preview.waitFor();
  assert.equal(await preview.locator('.rd-canvas-node').count(), definition.nodes.length + 1, 'execution preview uses the adopted compiled steps');
  await fixture.getByRole('button', { name: '编辑工作包计划 →', exact: true }).click();
  await panel.getByRole('button', { name: '确认提交执行', exact: true }).click();
  assert.equal(commands.filter(item => item.command === 'submit_workpackage').length, 0, 'submission waits for a separate confirmation');
  await fixture.getByRole('dialog').getByRole('button', { name: '固定快照并执行', exact: true }).click();
  await panel.getByText('固定执行图 · 只读', { exact: true }).waitFor();
  assert.equal(await editor.getByLabel('节点标题', { exact: true }).isDisabled(), true);
  assert.equal(await panel.getByRole('button', { name: '保存草稿', exact: true }).count(), 0);
  assert.equal(await panel.getByRole('button', { name: '添加节点', exact: true }).count(), 0);
  assert.equal(commands.filter(item => item.command === 'submit_workpackage').length, 1);
  for (const item of commands.filter(item => ['prepare_execution_bundle', 'adopt_execution_bundle', 'submit_workpackage'].includes(item.command))) {
    assert(!Object.hasOwn(item.data, 'nodes') && !Object.hasOwn(item.data, 'graph'), 'execution commands refer to fixed server drafts/candidates instead of resubmitting display geometry');
  }
  assert(commands.find(item => item.command === 'apply_flow_patch').data.operations.some(operation => operation.op === 'move_node'), 'layout edits remain explicit draft operations');
  assert.equal(commands.some(item => item.command === 'save_plan'), false, 'v1 migration never falls back to the retired plan editor');
  await fixture.goto(`${base}/?rd_view=flows&flow_tab=resources`);
  await fixture.getByRole('alert').filter({ hasText: '测试资源目录暂不可用' }).waitFor();
  await fixture.getByRole('button', { name: '重试读取', exact: true }).click();
  await fixture.getByText('仅定义 · 未绑定执行能力', { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log('PASS: live expert-team directory IDs/counts, non-overlapping card graph, graph navigation, search/paging/narrow scroll; isolated v1-to-P2 draft migration, optional add/remove, dependency/layout patch, failed-save same-key retry, separate candidate adoption/submission and submitted read-only state. No real generation or project mutations.');
} finally { await browser.close(); }
