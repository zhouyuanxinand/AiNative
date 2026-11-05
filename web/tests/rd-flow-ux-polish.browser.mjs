/** Isolated UI fixtures: no production project writes, execution, or approvals. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'file:///C:/Users/周园鑫/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const browser = await chromium.launch({ headless: true });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const failures = [], errors = [];
let passed = 0;
const team = { id: 'authoring-team', kind: 'team', version: 1, name: '编制专家团', executable: true, status: 'published' };
function fixtures() {
  const nodes = Array.from({ length: 12 }, (_, index) => ({ id: 'node-' + index, title: index > 9 ? '同名复核' : '办理节点 ' + (index + 1), role: '工程师', action_id: 'resolve_context', action_version: '1', deliverables: [], position: { x: index % 3 * 240 + 24, y: Math.floor(index / 3) * 180 + 24 } }));
  const graph = { nodes, edges: [] };
  const template = { id: 'workflow-1', version: '1', head_version: '1', category: 'selection', title: '标准选型流程', digest: 'fixed', publication_revision: 1, status: 'published', graph: { nodes: [{ ...nodes[0], id: 'input', title: '资料受理' }, { ...nodes[1], id: 'selection_decision', title: '选型决定', gate: 'selection' }], edges: [{ id: 'edge', source: 'input', target: 'selection_decision' }] } };
  const draft = { id: 'draft-1', workpackage_id: 'wp-1', revision: 1, input_revision: 2, graph, digest: 'draft-digest', history: [], confirmed_fields: [] };
  const workpackage = { id: 'wp-1', title: '任务书工作包', definition_id: 'taskbook', definition_version: '1', stage: 'design', status: 'draft', plan_revision: 1, nodes: [{ id: 'n1', action_id: 'resolve_context', action_version: '1', depends_on: [], required: true }], artifacts: [], obligations: [], blocked_reasons: [] };
  const researchCase = { id: 'case', title: '流程体验验证', scenario_id: 'taskbook', stage: 'design', status: 'active', input_revision: 2, context: {}, sources: [], requirements: [], decisions: [], workpackages: [workpackage], flow_drafts: [draft] };
  const project = { id: 'project', title: '流程体验验证', version: 1, owner_id: 'user', members: [], events: [], cases: [researchCase] };
  return { project, researchCase, draft, workpackage, template, writes: [], teamsFail: false, teamsEmpty: false, teamReads: 0, saveFail: false };
}
async function setup(page, data) {
  page.setDefaultTimeout(6000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    const json = value => route.fulfill({ json: value });
    if (path === '/api/current-user') return json({ auth_enabled: false, authenticated: false, user: null });
    if (path === '/api/rd/session') return json({ ok: true });
    if (path === '/api/rd/governance/session') return data.governanceDenied ? route.fulfill({ status: 403, json: { error: '模板维护权限已撤销' } }) : json({ can_edit_workflows: true, can_publish_workflows: true });
    if (path === '/api/rd/catalog') return json({ stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书' }], actions: [{ id: 'resolve_context', title: '参数核对', version: '1' }], workpackage_definitions: [] });
    if (path === '/api/rd/catalog/items') { data.teamReads++; const failed = data.teamsFail, empty = data.teamsEmpty; if (data.teamDelay) await data.teamDelay; return failed ? route.fulfill({ status: 503, json: { error: '目录暂时不可用' } }) : json({ items: empty ? [] : [team], total: empty ? 0 : 1, total_pages: 1, page: 1, page_size: 5 }); }
    if (path.startsWith('/api/rd/catalog/resources/')) return json({ ...team, configuration: { members: [], inputs: [], outputs: [], execution_graph: { nodes: [], edges: [] } } });
    if (path === '/api/rd/workflow-templates') { if (request.method() === 'POST') { data.writes.push(request.postDataJSON()); return data.saveFail ? route.fulfill({ status: 409, json: { error: '模板版本已更新' } }) : json(data.template); } return json({ items: [data.template], total: 1, total_pages: 1, page: 1, page_size: 5 }); }
    if (path.startsWith('/api/rd/workflow-templates/')) return json(data.template);
    if (path === '/api/rd/projects') return json({ projects: [data.project] });
    if (path === '/api/rd/projects/project') return json(data.project);
    if (path.endsWith('/assistant')) return json({ messages: [], suggestions: [], context: { stage: 'design', project_version: 1 } });
    if (path.endsWith('/commands')) { data.writes.push(request.postDataJSON()); return json(data.project); }
    if (path === '/api/models') return json({ success: true, models: [] });
    if (path === '/api/product_catalog') return json({ product_types: [] });
    return json({});
  });
}
async function choose(page, label, option) { await page.getByRole('button', { name: label, exact: true }).click(); await page.getByRole('option', { name: option, exact: true }).click(); }
async function openProject(page) { await page.goto(base + '/?project=project&case=case'); await page.getByRole('button', { name: '检查计划并确认提交', exact: true }).click(); await page.locator('.rd-flow-designer').waitFor(); }
async function snap(page, name) { if (output) await page.screenshot({ path: join(output, name), fullPage: false }); }
async function check(name, action) { const page = await browser.newPage({ viewport: { width: 1440, height: 950 } }); const data = fixtures(); try { await setup(page, data); await action(page, data); passed++; console.log('PASS', name); } catch (error) { failures.push({ name, error: error.message }); console.error('FAIL', name, error.message, (await page.locator('body').innerText()).slice(0, 3000)); } finally { await page.close(); } }
try {
  await check('cancel preserves or discards template edits without writing', async (page, data) => {
    await page.goto(base + '/?rd_view=flows&flow_tab=business');
    await page.getByRole('button', { name: '编辑业务模板新修订', exact: true }).click();
    await page.getByRole('button', { name: '取消编辑', exact: true }).click();
    assert.equal(await page.getByLabel('业务模板名称', { exact: true }).count(), 0);
    await page.getByRole('button', { name: '另存为新业务模板', exact: true }).click();
    await page.getByLabel('业务模板名称', { exact: true }).fill('保留的新模板');
    await page.getByRole('button', { name: '取消编辑', exact: true }).click();
    await page.getByRole('button', { name: '继续编辑', exact: true }).click();
    assert.equal(await page.getByLabel('业务模板名称', { exact: true }).inputValue(), '保留的新模板');
    await page.getByRole('button', { name: '取消编辑', exact: true }).click();
    await page.keyboard.press('Escape');
    assert.equal(await page.getByLabel('业务模板名称', { exact: true }).inputValue(), '保留的新模板');
    data.saveFail = true;
    await page.getByRole('button', { name: '保存业务模板草稿', exact: true }).click();
    await page.getByText('模板版本已更新', { exact: true }).waitFor();
    await page.getByRole('button', { name: '取消编辑', exact: true }).click();
    await snap(page, 'flow-cancel-dialog.png');
    await page.getByRole('button', { name: '放弃修改', exact: true }).click();
    assert.equal(await page.getByLabel('业务模板名称', { exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: '研发流程模板', exact: true }).isEnabled(), true);
    assert.equal(data.writes.length, 1);
  });
  await check('directory retry preserves unsaved graph and empty differs from error', async (page, data) => {
    data.teamsFail = true; await openProject(page);
    const editor = page.locator('.rd-flow-designer');
    await editor.getByLabel('节点标题', { exact: true }).fill('保留的节点标题');
    await editor.getByText(/获准专家团目录读取失败/).waitFor();
    data.teamsFail = false; data.teamsEmpty = true;
    await editor.getByRole('button', { name: '重新读取专家团', exact: true }).click();
    await editor.getByText('当前没有获准的可执行专家团。已有节点与修改仍保留。', { exact: true }).waitFor();
    assert.equal(await editor.getByLabel('节点标题', { exact: true }).inputValue(), '保留的节点标题');
    data.teamsEmpty = false;
    await editor.getByRole('button', { name: '重新读取专家团', exact: true }).click();
    await choose(editor, '新增节点的固定能力', '编制专家团 · V1');
    assert.equal(await editor.getByRole('button', { name: '添加节点', exact: true }).isEnabled(), true);
    assert.equal(data.writes.length, 0);
  });
  await check('node navigation reveals offscreen nodes and preserves coordinates', async (page, data) => {
    await openProject(page); const editor = page.locator('.rd-flow-designer > .rd-graph-editor');
    await choose(editor, '选择流程节点', '同名复核 · 12 / 12');
    await editor.getByRole('button', { name: '定位所选节点', exact: true }).click();
    assert(await editor.locator('.rd-graph-scroll').evaluate(element => element.scrollTop > 0));
    assert.equal(await editor.getByLabel('Y 坐标', { exact: true }).inputValue(), '564');
    await editor.getByRole('button', { name: '复制节点', exact: true }).click();
    await page.waitForFunction(() => { const root = document.querySelector('.rd-flow-designer > .rd-graph-editor'); const selected = root?.querySelector('.rd-graph-node.is-selected'); const viewport = root?.querySelector('.rd-graph-scroll'); if (!selected || !viewport) return false; const a = selected.getBoundingClientRect(), b = viewport.getBoundingClientRect(); return a.top >= b.top && a.bottom <= b.bottom + 2; });
    await editor.getByRole('button', { name: '编辑所选属性', exact: true }).click();
    assert.equal(await page.evaluate(() => document.activeElement?.textContent), '节点属性 · 同名复核（副本）');
    await page.setViewportSize({ width: 390, height: 760 });
    await editor.evaluate(element => element.scrollIntoView({ block: 'start', inline: 'nearest' }));
    await editor.getByRole('button', { name: '选择流程节点', exact: true }).focus();
    await page.keyboard.press('ArrowDown');
    await page.waitForFunction(() => { const menu = document.querySelector('.rd-flow-designer > .rd-graph-editor .select-control.open .select-menu'); return menu && getComputedStyle(menu).opacity === '1'; });
    await snap(page, 'flow-node-menu-narrow.png');
    await page.keyboard.press('ArrowDown');
    assert.equal(await editor.getByLabel('节点标题', { exact: true }).inputValue(), '办理节点 1');
    await page.keyboard.press('ArrowUp'); await page.keyboard.press('ArrowUp');
    assert.equal(await editor.getByLabel('节点标题', { exact: true }).inputValue(), '同名复核');
    await editor.getByRole('button', { name: '定位所选节点', exact: true }).click();
    await editor.evaluate(element => element.scrollIntoView({ block: 'start', inline: 'nearest' }));
    await snap(page, 'flow-graph-narrow.png');
    assert(await page.locator('.rd-application-shell').evaluate(element => element.scrollWidth <= element.clientWidth + 2));
    assert.equal(data.writes.length, 0);
  });
  await check('next action explains dirty and stage restriction; waste wording matches', async (page, data) => {
    await openProject(page); const designer = page.locator('.rd-flow-designer');
    await designer.getByRole('region', { name: '当前状态与下一步', exact: true }).getByText(/校验草稿/).waitFor();
    await designer.getByLabel('节点标题', { exact: true }).fill('待保存标题');
    await designer.getByRole('region', { name: '当前状态与下一步', exact: true }).getByText(/先保存草稿/).waitFor();
    await page.getByRole('button', { name: '废止此工作包', exact: true }).click();
    await page.getByRole('dialog', { name: '废止此工作包', exact: true }).waitFor();
    assert.equal(await page.getByRole('dialog').getByRole('button', { name: '废止此工作包', exact: true }).count(), 1);
    await page.getByRole('button', { name: '取消', exact: true }).click();
    await designer.evaluate(element => element.scrollIntoView({ block: 'start', inline: 'nearest' }));
    await snap(page, 'flow-next-action.png');
    assert.equal(data.writes.length, 0);
    data.workpackage.stage = 'planning';
    await page.reload(); await page.getByRole('button', { name: '项目流程', exact: true }).click();
    await page.locator('.rd-schedule-row').getByRole('button', { name: '任务书工作包', exact: true }).click();
    await designer.getByRole('region', { name: '当前状态与下一步', exact: true }).getByText(/所属阶段/).waitFor();
  });
  await check('business directory can retry while a template has unsaved input', async (page, data) => {
    data.teamsFail = true;
    await page.goto(base + '/?rd_view=flows&flow_tab=business');
    await page.getByRole('button', { name: '编辑业务模板新修订', exact: true }).click();
    await page.getByLabel('业务模板名称', { exact: true }).fill('保留的业务模板');
    await page.getByText(/获准专家团目录读取失败/).waitFor();
    assert.equal(await page.getByRole('button', { name: '刷新业务模板', exact: true }).isDisabled(), true);
    data.teamsFail = false;
    await page.getByRole('button', { name: '重新读取专家团', exact: true }).click();
    await choose(page, '新增节点的固定能力', '编制专家团 · V1');
    assert.equal(await page.getByLabel('业务模板名称', { exact: true }).inputValue(), '保留的业务模板');
    assert.equal(data.writes.length, 0);
  });
  await check('late directory response cannot restore restricted editing or choices after access is revoked', async (page, data) => {
    let releaseTeams;
    data.teamDelay = new Promise(resolve => { releaseTeams = resolve; });
    await page.goto(base + '/?rd_view=flows&flow_tab=business');
    await page.getByRole('button', { name: '编辑业务模板新修订', exact: true }).waitFor();
    data.governanceDenied = true;
    await page.getByRole('button', { name: '刷新业务模板', exact: true }).click();
    await page.getByRole('button', { name: '编辑业务模板新修订', exact: true }).waitFor({ state: 'hidden' });
    releaseTeams();
    await page.waitForLoadState('networkidle');
    assert.equal(await page.getByRole('button', { name: '编辑业务模板新修订', exact: true }).count(), 0);
    assert.equal(await page.getByLabel('节点标题', { exact: true }).isDisabled(), true);
    assert.equal((await page.locator('.rd-graph-editor').innerText()).includes('编制专家团'), false);
    assert.equal(await page.getByText('正在读取获准专家团…', { exact: true }).count(), 0);
    assert.equal(data.writes.length, 0);
  });
  for (const state of ['no-draft', 'stale', 'ready-to-adopt', 'adopted', 'running']) {
    await check('next action follows server state: ' + state, async (page, data) => {
      const candidate = { id: 'candidate', digest: 'candidate-digest', draft_id: 'draft-1', draft_revision: state === 'stale' ? 0 : 1, input_revision: 2, graph: data.draft.graph, validation: { valid: true, errors: [], warnings: [] }, diff: {}, mapping: [], compiled_plan: [], resource_locks: [] };
      if (state === 'no-draft') data.researchCase.flow_drafts = [];
      else data.researchCase.execution_candidates = [candidate];
      if (state === 'adopted' || state === 'running') { data.workpackage.execution_adoption_id = 'adoption'; data.researchCase.execution_adoptions = [{ id: 'adoption', candidate_id: 'candidate', candidate_digest: 'candidate-digest', actor: '工程师' }]; }
      if (state === 'running') data.workpackage.status = 'running';
      await page.goto(base + '/?project=project&case=case');
      await page.getByRole('button', { name: '项目流程', exact: true }).click();
      await page.locator('.rd-schedule-row').getByRole('button', { name: '任务书工作包', exact: true }).click();
      const designer = page.locator('.rd-flow-designer'), summary = designer.getByRole('region', { name: '当前状态与下一步', exact: true });
      const descriptions = { 'no-draft': /先建立流程草稿/, stale: /准备新的执行候选/, 'ready-to-adopt': /先采用此执行候选/, adopted: /单独确认提交执行/, running: /请查看实际执行步骤/ };
      await summary.getByText(descriptions[state]).waitFor();
      if (state === 'stale') assert.equal(await designer.getByRole('button', { name: '确认提交执行', exact: true }).isDisabled(), true);
      if (state === 'adopted') assert.equal(await designer.getByRole('button', { name: '确认提交执行', exact: true }).isEnabled(), true);
      if (state === 'running') assert.equal(await designer.getByLabel('节点标题', { exact: true }).isDisabled(), true);
      assert.equal(data.writes.length, 0);
    });
  }
  assert.deepEqual(errors, []);
  assert.deepEqual(failures, []);
  console.log(JSON.stringify({ passed: true, scenarios: passed, screenshots: output }));
} finally { await browser.close(); }

