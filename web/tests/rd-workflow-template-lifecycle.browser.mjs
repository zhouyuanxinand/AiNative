/** Isolated failure-path fixtures around the real FlowManagement component.
 * Every /api request is intercepted; this test cannot alter real templates or projects.
 */
import assert from 'node:assert/strict';
import { mkdir, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'docs/rd-platform/verification/screenshots/2026-11-03-workflow-templates/failure-paths';
await mkdir(output, { recursive: true });
const clone = value => JSON.parse(JSON.stringify(value));
const research = ['taskbook', 'taskbook_scope', 'scheme', 'detail', 'integration', 'verification', 'delivery'];
const selection = ['input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start'];
const names = { taskbook: '任务书编制', taskbook_scope: '任务书范围批准', scheme: '方案设计', detail: '详细设计', integration: '整合', verification: '验证', delivery: '交付', input: '资料受理', confirm_requirements: '需求确认', comparison: '产品比对', selection_decision: '选型决定', rd_start: '研发启动' };
const gates = { taskbook_scope: 'taskbook_scope', verification: 'verification', delivery: 'delivery', confirm_requirements: 'requirements', selection_decision: 'selection', rd_start: 'rd_start' };
const graph = ids => ({ nodes: ids.map((id, index) => ({ id, title: names[id], role: '研发工程师', deliverables: [names[id] + '记录'], position: { x: 24 + index % 3 * 250, y: 24 + Math.floor(index / 3) * 160 }, ...(gates[id] ? { gate: gates[id] } : {}), ...(id === 'taskbook' ? { action_resource: { resource_id: 'taskbook-authoring-team', resource_version: 1 }, workpackage_definition_id: 'taskbook' } : {}) })), edges: ids.slice(1).map((id, index) => ({ id: 'e-' + index, source: ids[index], target: id })) });
const fixed = (id, version, category, title, status) => ({ id, version, head_version: version, category, title, status, publication_revision: 1, product_route: category === 'research' ? 'modification' : null, graph: graph(category === 'research' ? research : selection), digest: id + '-digest-' + version, created_at: '2026-11-03T01:00:00Z', actor: 'fixture-maintainer', change_note: '浏览器隔离测试，非真实业务模板' });
const versions = {
  '1': fixed('fixture-research', '1', 'research', '隔离研发流程原版', 'published'),
  '2': fixed('fixture-research', '2', 'research', '隔离研发流程修订版', 'draft'),
};
versions['2'].graph.nodes[0].role = '质量工程师';
versions['2'].graph.nodes[0].position.x += 40;
const selectionTemplate = fixed('fixture-selection', '1', 'selection', '隔离选型流程', 'published');
const state = { manage: true, head: '2', failList: false, failHistory: false, saveFailure: '', failValidate: false };
const calls = [], errors = [], unexpected = [], checks = [];
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
page.setDefaultTimeout(15000);
page.on('pageerror', error => errors.push(error.message));
const versionDetail = (version, management = true) => ({ ...clone(versions[version]), head_version: state.head, available_versions: Object.keys(versions).filter(v => management || versions[v].status === 'published').sort((a, b) => Number(b) - Number(a)) });
const directory = items => ({ items, total: items.length, page: 1, page_size: 5, total_pages: 1 });
const validation = () => ({ valid: !state.failValidate, errors: state.failValidate ? [{ code: 'invalid_workflow', message: '请补齐任务书范围批准的前置依赖。', node_id: 'taskbook_scope' }] : [], warnings: [], graph_digest: 'fixture-graph-digest', checked_at: '2026-11-03T01:30:00Z' });
await page.route('**/__workflow-template-fixture**', route => route.fulfill({ contentType: 'text/html', body: '<html lang="zh-CN"><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>流程模板异常路径隔离验证</title></head><body><div id="fixture"></div></body></html>' }));
await page.route('**/api/**', async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname;
  if (!path.startsWith('/api/')) return route.continue();
  const json = data => route.fulfill({ json: data });
  const fail = (status, error) => route.fulfill({ status, json: { error } });
  const management = url.searchParams.get('management') === 'true';
  if (request.method() !== 'GET') calls.push({ path, method: request.method(), payload: request.postDataJSON() });
  if (path === '/api/rd/session') return json({ actor_id: 'local:fixture-client', local_mode: true });
  if (path === '/api/rd/governance/session') return json({ can_edit_workflows: state.manage, can_publish_workflows: state.manage, can_prepare_templates: false, can_publish_templates: false, can_review_templates: false, local_bootstrap: state.manage });
  if (path === '/api/rd/catalog/items') {
    const category = url.searchParams.get('category');
    if (category === 'actions') return json(directory([{ id: 'taskbook-authoring-team', version: 1, kind: 'team', title: '任务书编制专家团', name: '任务书编制专家团', status: 'published', executable: true, description: '浏览器隔离测试动作' }]));
    return json(directory([]));
  }
  if (path === '/api/rd/catalog/resources') return json(directory([]));
  if (path === '/api/rd/workflow-templates/validate') return state.manage ? json(validation()) : fail(403, '当前主体没有流程模板校验权限');
  if (path === '/api/rd/workflow-templates' && request.method() === 'POST') {
    if (!state.manage || state.saveFailure === 'permission') return fail(403, '当前主体没有流程模板治理权限');
    if (state.saveFailure === 'conflict') return fail(409, '业务流程模板内容版本已更新。');
    const payload = request.postDataJSON();
    if (payload.operation === 'validate') return json({ ...versionDetail(payload.version), validation: validation() });
    if (payload.operation === 'save') {
      const next = String(Number(state.head) + 1);
      versions[next] = { ...clone(versions[state.head]), ...payload, id: 'fixture-research', version: next, head_version: next, status: 'draft', publication_revision: 1, digest: 'fixture-digest-' + next, created_at: '2026-11-03T02:00:00Z' };
      state.head = next;
      return json(versionDetail(next));
    }
    return fail(422, '此隔离验证未模拟发布或停用');
  }
  if (path === '/api/rd/workflow-templates') {
    if (state.failList) return fail(503, '流程目录读取失败，请稍后重试。');
    if (url.searchParams.get('category') === 'selection') return json(directory([{ ...selectionTemplate, available_versions: ['1'] }]));
    const head = management ? state.head : Object.keys(versions).reverse().find(v => versions[v].status === 'published');
    return json(directory(head ? [versionDetail(head, management)] : []));
  }
  if (path.endsWith('/history')) {
    if (state.failHistory) return fail(503, '历史记录暂时无法读取');
    const items = Object.keys(versions).reverse().filter(v => management || versions[v].status === 'published').map(v => versionDetail(v, management));
    return json({ ...directory(items), events: items.map(v => ({ id: 'event-' + v.version, version: v.version, operation: 'save', actor: 'fixture-maintainer', created_at: v.created_at, change_note: v.change_note, status: v.status })), usages: [{ project_id: 'fixture-project', project_title: '隔离项目', case_id: 'fixture-case', case_title: '隔离工作', reference_type: 'adoption', template_version: '1', template_digest: versions['1'].digest, current: true, adopted_at: '2026-11-03T01:05:00Z' }] });
  }
  if (path.startsWith('/api/rd/workflow-templates/fixture-research/')) {
    const version = path.split('/').at(-1) === 'latest' ? state.head : path.split('/').at(-1);
    if (!versions[version]) return fail(404, '版本不存在');
    return json(versionDetail(version, management));
  }
  if (path.startsWith('/api/rd/workflow-templates/fixture-selection/')) return json({ ...selectionTemplate, available_versions: ['1'] });
  unexpected.push({ path, method: request.method() });
  return fail(500, '隔离验证不支持该请求，未访问真实 API');
});
const snap = async name => page.screenshot({ path: join(output, name + '.png'), animations: 'disabled' });
const select = async (label, option) => { await page.getByRole('combobox', { name: label, exact: true }).press('ArrowDown'); await page.getByRole('option', { name: option, exact: true }).click(); };
const open = async () => {
  await page.goto(`${base}/__workflow-template-fixture?flow_tab=flows&flow_kind=research`);
  await page.evaluate(async () => {
    const refresh = await import('/@react-refresh'); refresh.default.injectIntoGlobalHook(window);
    window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => type => type; window.__vite_plugin_react_preamble_installed__ = true;
    const React = (await import('/node_modules/.vite/deps/react.js')).default;
    const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
    const { FlowManagement } = await import('/src/features/rd/FlowManagement.tsx');
    const { PlatformTheme } = await import('/src/components/ui/PlatformTheme.tsx');
    for (const css of ['/src/styles.css', '/src/features/rd/rd.css', '/src/features/rd/rdApplicationShell.css']) await import(css);
    createRoot(document.getElementById('fixture')).render(React.createElement(PlatformTheme, null, React.createElement('div', { className: 'rd-shell rd-application-shell', style: { display: 'block' } }, React.createElement('main', { className: 'rd-page-content' }, React.createElement(FlowManagement, { catalog: { actions: [], workpackage_definitions: [], scenarios: [], stages: [] }, catalogLoading: false, catalogError: '', onRefreshCatalog: () => {}, projects: [], onOpenCase: () => {}, onOpenWorkspace: () => {} })))));
  });
  await select('流程用途', '研发阶段流程');
  await page.getByRole('button', { name: '编辑新版本', exact: true }).waitFor();
};
const edit = async text => { await page.getByRole('button', { name: '编辑新版本', exact: true }).click(); await page.getByLabel('流程名称', { exact: true }).fill(text); await page.locator('#workflow-change-note').fill('隔离验证：修改保留与权限检查'); };
try {
  await open();
  assert.equal(await page.getByRole('tab', { name: '选型与研发流程' }).count(), 0);
  assert.equal(await page.getByRole('tab', { name: '模板派生与发布' }).count(), 0);
  await edit('未保存修改应保留');
  await page.getByRole('tab', { name: '动作模板', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(await page.getByLabel('流程名称', { exact: true }).inputValue(), '未保存修改应保留');
  await page.getByRole('button', { name: '可调用工作包', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(await page.getByLabel('流程名称', { exact: true }).inputValue(), '未保存修改应保留');
  await select('流程用途', '选型阶段流程');
  await page.getByRole('dialog').getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(await page.getByLabel('流程名称', { exact: true }).inputValue(), '未保存修改应保留');
  await snap('01-dirty-switch-cancel-preserves-editor');
  await select('流程用途', '选型阶段流程');
  await page.getByRole('dialog').getByRole('button', { name: '放弃修改', exact: true }).click();
  await page.getByRole('heading', { name: '隔离选型流程', exact: true }).waitFor();
  assert.equal(calls.length, 0, 'cancelling/confirming navigation does not write templates');
  await select('流程用途', '研发阶段流程');
  await edit('顶级切换确认应放弃');
  await page.getByRole('tab', { name: '报告模板', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '放弃修改并切换', exact: true }).click();
  assert.equal(await page.getByLabel('流程名称', { exact: true }).count(), 0);
  await page.getByRole('tab', { name: '流程模板', exact: true }).click();
  await edit('工作包切换确认应放弃');
  await page.getByRole('button', { name: '可调用工作包', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '放弃修改并切换', exact: true }).click();
  assert.equal(await page.getByLabel('流程名称', { exact: true }).count(), 0);
  await page.getByRole('button', { name: '流程编排与版本', exact: true }).click();
  checks.push('unsaved top-level tab, workpackage view and category changes require confirmation; cancellation preserves edits');

  await edit('并发冲突后保留的内容');
  versions['3'] = fixed('fixture-research', '3', 'research', '另一位维护者保存的版本', 'draft');
  state.head = '3'; state.saveFailure = 'conflict';
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '内容版本已更新' }).waitFor();
  assert.equal(await page.getByLabel('流程名称', { exact: true }).inputValue(), '并发冲突后保留的内容');
  await page.getByRole('button', { name: '核对最新修订，保留当前编辑', exact: true }).click();
  await page.getByText(/最新内容已到 V3/).waitFor();
  assert.equal(await page.getByLabel('流程名称', { exact: true }).inputValue(), '并发冲突后保留的内容');
  await snap('02-conflict-preserves-local-fields');
  state.saveFailure = '';
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.getByText('草稿 V4 已保存。校验、发布后，项目才能采用。', { exact: true }).waitFor();
  const lastSave = calls.filter(call => call.payload.operation === 'save').at(-1).payload;
  assert.equal(lastSave.expected_version, 3);
  assert.equal(lastSave.title, '并发冲突后保留的内容');
  assert.equal(lastSave.based_on.version, '2', 'preserves original editing baseline while updating head CAS');
  checks.push('409 preserves fields; head refresh updates CAS without changing baseline; retry saves new revision');

  await edit('权限撤销后不应保留可编辑草稿');
  state.manage = false; state.saveFailure = 'permission';
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.getByText('当前可查看已获准的流程模板。编辑和发布由流程维护人员办理。', { exact: true }).waitFor();
  await page.getByRole('heading', { name: '隔离研发流程原版', exact: true }).waitFor();
  assert.equal(await page.getByLabel('流程名称', { exact: true }).count(), 0);
  assert.equal(await page.getByRole('button', { name: '编辑新版本', exact: true }).count(), 0);
  assert.equal(await page.getByRole('button', { name: '保存草稿', exact: true }).count(), 0);
  await snap('03-permission-revocation-clears-editor');
  checks.push('403 revocation clears management drafts and returns to published readonly catalog');

  state.manage = true; state.saveFailure = ''; await open();
  await select('查看固定版本', 'V1');
  versions['1'].status = 'retired'; versions['1'].publication_revision = 3;
  await page.getByRole('button', { name: '刷新模板', exact: true }).click();
  await page.locator('.rd-template-detail-head').getByText('V1 · 已停用', { exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: '发布版本', exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole('button', { name: '停用版本', exact: true }).isDisabled(), true);
  await snap('04-refresh-retains-selected-fixed-version-and-state');
  checks.push('refresh retains selected old version and updates its retirement state rather than switching to head');

  await select('查看固定版本', 'V4 · 最新修订');
  await page.getByRole('button', { name: '版本与回溯', exact: true }).click();
  await select('对比基准版本', 'V1');
  await page.locator('.rd-template-diff-list').waitFor();
  assert((await page.locator('.rd-template-diff-list').innerText()).includes('质量工程师'));
  assert((await page.locator('.rd-template-diff-list').innerText()).includes('仅布局'));
  await page.getByText('隔离项目 / 隔离工作', { exact: true }).waitFor();
  await snap('05-history-differences-and-visible-usage');
  checks.push('history displays fixed versions, human-readable attribute/layout differences and authorized usage');

  state.failList = true;
  await page.getByRole('button', { name: '刷新模板', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '流程目录读取失败' }).waitFor();
  state.failList = false;
  await page.getByRole('button', { name: '重试读取', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('.rd-template-manager>[role="alert"]'));
  await page.setViewportSize({ width: 390, height: 760 });
  await page.locator('.rd-template-diff-list').scrollIntoViewIfNeeded();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'no narrow-viewport document overflow');
  assert(await page.locator('.rd-application-shell').evaluate(el => el.scrollHeight > el.clientHeight), 'narrow viewport remains vertically scrollable');
  await snap('06-narrow-history-and-differences');
  checks.push('directory failure can retry; 390px history remains scrollable without horizontal page overflow');
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
  const receipt = { passed: true, mode: 'isolated API fixtures with real FlowManagement/WorkflowTemplateWorkbench components', actualBusinessWrites: 0, simulatedCommands: calls.map(call => ({ operation: call.payload.operation, title: call.payload.title })), checks, errors, unexpected };
  await writeFile(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  for (const stale of ['failure.png', 'failure.json']) await unlink(join(output, stale)).catch(error => { if (error.code !== 'ENOENT') throw error; });
  console.log(JSON.stringify(receipt));
} catch (error) {
  await snap('failure');
  await writeFile(join(output, 'failure.json'), JSON.stringify({ message: error.message, body: await page.locator('body').innerText(), errors, unexpected, calls }, null, 2));
  throw error;
} finally { await browser.close(); }
