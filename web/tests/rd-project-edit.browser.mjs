/** Project editing acceptance. All /api/ requests use in-memory fixtures; no real data is written. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'runtime/rd-project-edit-browser';
await mkdir(output, { recursive: true });
const checks = [], errors = [], unexpected = [], writes = [];
const stamp = '2026-11-05T08:00:00Z', actor = 'project-edit-owner';
const workflow = { id: 'taskbook-generation', version: '1', template_id: 'taskbook-generation', template_version: '1', template_digest: 'edit-fixed', digest: 'edit-fixed', title: '研制任务书生成流程', category: 'project', status: 'published', publication_revision: 1,
  graph: { nodes: [{ id: 'input', title: '资料受理', role: '研发工程师', deliverables: [], position: { x: 0, y: 0 } }], edges: [] }, node_states: { input: 'pending' } };
const makeCase = title => ({ id: 'edit-case', title, scenario_id: 'taskbook', stage: 'input', status: 'active', input_revision: 1, context: {}, sources: [], source_selection: {}, requirements: [], workpackages: [], decisions: [], clarifications: [], comparisons: [], warnings: [], deliveries: [], reuse_candidates: [], product_route: null, composition_route: null, model_selection: { provider: '', name: '', id: '' },
  workflow_templates: { project: structuredClone(workflow) }, project_workflow_status: { status: 'pending', terminal_node_id: 'input' }, business_lifecycle: { policy_version: 'v2', rd_activation_state: 'not_started', local_review_enabled: true, can_record_decision: true, can_confirm_requirements: true } });
const makeProject = () => ({ id: 'edit-project', title: '隔离项目编辑验收', customer_name: '原客户', product_name: '原产品', brief: '原研发目标', version: 3, owner_id: actor, members: [], can_delete: true, delete_blocked_reason: '', created_at: stamp, updated_at: stamp, cases: [], events: [] });
const catalog = { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书', status: 'published' }], actions: [], workpackage_definitions: [], project_workflow_templates: [workflow] };
const projectPath = '/api/rd/projects/edit-project';
const clone = value => structuredClone(value);
const defer = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const labels = { title: '项目名称', customer_name: '客户名称', product_name: '产品名称', brief: '研发目标' };

async function fixture(name, viewport = { width: 1440, height: 1000 }) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage(); page.setDefaultTimeout(15000);
  page.on('pageerror', error => errors.push({ scenario: name, message: error.message }));
  const state = { project: makeProject(), listProject: null, readStatus: 200, mode: 'success', calls: [], reads: [], receipts: new Map(), listGate: null, readGate: null, writeGate: null };
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    if (!path.startsWith('/api/')) return route.continue();
    const respond = (json, status = 200) => route.fulfill({ status, json });
    if (method === 'GET') {
      state.reads.push(path);
      if (path === '/api/current-user') return respond({ auth_enabled: false, authenticated: false, user: null });
      if (path === '/api/rd/session') return respond({ actor_id: actor, local_mode: true });
      if (path === '/api/rd/catalog') return respond(catalog);
      if (path === '/api/rd/catalog/items') return respond({ items: [], total: 0, page: 1, page_size: 5, total_pages: 1 });
      if (path === '/api/rd/governance/session') return respond({ can_edit_workflows: false, can_publish_workflows: false, can_prepare_templates: false, can_publish_templates: false, can_review_templates: false, local_bootstrap: false });
      if (path === '/api/rd/workflow-templates') return respond({ items: [clone(workflow)], total: 1, page: 1, page_size: 5, total_pages: 1 });
      if (path === '/api/rd/projects') {
        const projects = [clone(state.listProject || state.project)];
        if (state.listGate) await state.listGate.promise;
        return respond({ projects });
      }
      if (path === projectPath) {
        if (state.readGate) await state.readGate.promise;
        return state.readStatus === 200 ? respond(clone(state.project)) : respond({ error: state.readStatus === 403 ? '当前账号无权编辑该项目' : state.readStatus === 404 ? '项目不存在或无权访问' : '项目读取暂不可用' }, state.readStatus);
      }
      if (path === '/api/rd/assistant/weather') return respond({ status: 'unavailable', location: '隔离测试', notice: '项目编辑测试不读取天气。' });
      if (path === '/api/product_catalog') return respond({ product_types: [] });
      if (path === '/api/models') return respond({ success: true, models: [] });
      if (path.endsWith('/assistant')) return respond({ messages: [], suggestions: [], context: { stage: 'input', project_version: state.project.version, input_revision: 1 } });
    }
    if (method === 'POST' && path === projectPath + '/commands') {
      const call = { key: request.headers()['idempotency-key'] || '', body: request.postDataJSON() };
      state.calls.push(clone(call)); writes.push({ scenario: name, path, ...clone(call) });
      assert(call.key.length > 0 && call.key.length <= 128, 'save includes the required idempotency key');
      assert.equal(call.body.command, 'save_project_profile');
      assert.deepEqual(Object.keys(call.body.data).sort(), Object.keys(labels).sort(), 'the editor submits exactly the four project fields');
      if (state.writeGate) await state.writeGate.promise;
      const receipt = state.receipts.get(call.key);
      if (receipt) {
        if (JSON.stringify(receipt.body) !== JSON.stringify(call.body)) return respond({ error: '同一幂等键不能用于不同请求' }, 409);
        return respond(clone(receipt.project));
      }
      if (state.mode === 'forbidden' || state.mode === 'missing') return respond({ error: state.mode === 'forbidden' ? '当前账号无权编辑该项目' : '项目不存在或无权访问' }, state.mode === 'forbidden' ? 403 : 404);
      if (state.mode === 'conflict' || call.body.expected_version !== state.project.version) return respond({ error: '项目已更新，请刷新后重试。' }, 409);
      state.project = { ...state.project, ...call.body.data, version: state.project.version + 1, updated_at: '2026-11-05T09:00:00Z' };
      state.listProject = null;
      state.receipts.set(call.key, { body: clone(call.body), project: clone(state.project) });
      if (state.mode === 'gateway-committed') return respond({ error: '网关暂不可用，请重试本次保存' }, 503);
      return respond(clone(state.project));
    }
    unexpected.push({ scenario: name, method, path });
    return respond({ error: 'Unmocked API is blocked by the project edit fixture' }, 503);
  });
  const dialog = page.getByRole('dialog', { name: '编辑项目', exact: true });
  const field = key => dialog.getByRole('textbox', { name: labels[key], exact: true });
  const save = () => dialog.getByRole('button', { name: /保存修改|重试保存|正在保存/ });
  const waitValue = async (key, value) => {
    await field(key).waitFor();
    await page.waitForFunction(({ element, value }) => element.value === value, { element: await field(key).elementHandle(), value });
  };
  const openList = async () => {
    await page.goto(base + '/?rd_view=projects');
    await page.getByRole('button', { name: '编辑项目：' + (state.listProject || state.project).title, exact: true }).waitFor();
  };
  const open = async () => {
    await page.getByRole('button', { name: '编辑项目：' + (state.listProject || state.project).title, exact: true }).click();
    await dialog.waitFor();
  };
  const ready = async () => { await open(); await waitValue('title', state.project.title); };
  const fill = async values => { for (const [key, value] of Object.entries(values)) await field(key).fill(value); };
  const snapshot = suffix => page.screenshot({ path: join(output, `${name}-${suffix}.png`), fullPage: true });
  const close = async () => { state.listGate?.resolve(); state.readGate?.resolve(); state.writeGate?.resolve(); await context.close(); };
  return { page, state, dialog, field, save, waitValue, openList, open, ready, fill, snapshot, close };
}

const scenarios = {
  async 'save-on-close'(f) {
    const { page, state, dialog, openList, ready, fill } = f;
    await openList(); await ready(); await fill({ title: '关闭时保存的项目' });
    await dialog.getByRole('button', { name: '取消', exact: true }).click();
    await page.getByRole('button', { name: '保存并关闭', exact: true }).click();
    await dialog.waitFor({ state: 'hidden' });
    await page.getByRole('article', { name: '关闭时保存的项目', exact: true }).waitFor();
    assert.equal(state.calls.length, 1);
    assert.equal(state.project.title, '关闭时保存的项目');
    checks.push('save-on-close: explicit save-and-close completes one versioned write before leaving');
  },
  async 'stale-list'(f) {
    const { page, state, dialog, openList, ready, fill, save } = f;
    state.project.version = 7;
    const oldTitle = state.project.title;
    await openList();
    state.listGate = defer();
    const pendingList = page.waitForRequest(request => request.method() === 'GET' && new URL(request.url()).pathname === '/api/rd/projects');
    await page.getByRole('button', { name: '刷新', exact: true }).click(); await pendingList;
    await ready();
    const updated = { title: '已保存的第八版项目', customer_name: '第八版客户', product_name: '第八版产品', brief: '第八版研发目标' };
    await fill(updated); await save().click(); await dialog.waitFor({ state: 'hidden' });
    assert.equal(state.calls[0].body.expected_version, 7); assert.equal(state.project.version, 8);
    const card = page.getByRole('article', { name: updated.title, exact: true });
    await card.waitFor();
    const delayedResponse = page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname === '/api/rd/projects');
    state.listGate.resolve(); state.listGate = null;
    const response = await delayedResponse;
    assert.equal((await response.json()).projects[0].version, 7, 'the released list genuinely contains the older version');
    await response.finished();
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve)))));
    assert.equal(await card.count(), 1, 'late version-7 list must not replace the saved version-8 card');
    const text = await card.innerText();
    assert(text.includes(updated.customer_name) && text.includes(updated.product_name) && text.includes(updated.brief), 'all displayed metadata remains from the saved version');
    assert.equal(await page.getByRole('article', { name: oldTitle, exact: true }).count(), 0, 'the older name does not reappear');
    assert.equal(state.calls.length, 1, 'late list reconciliation never resubmits the edit');
    await f.snapshot('latest-card');
    checks.push('stale-list: delayed version-7 list cannot roll back the name or metadata already saved and displayed at version 8');
  },
  async save(f) {
    const { page, state, dialog, save, openList, open, waitValue, fill, snapshot } = f;
    state.listProject = clone(state.project);
    state.project = { ...state.project, version: 7, title: '服务端最新项目', customer_name: '服务端客户', product_name: '服务端产品', brief: '服务端最新目标' };
    await openList(); state.readGate = defer();
    const read = page.waitForRequest(request => new URL(request.url()).pathname === projectPath);
    await open(); await read;
    assert.equal(state.calls.length, 0, 'opening the editor never writes');
    assert(await save().isDisabled(), 'saving is disabled until the latest project has loaded');
    state.readGate.resolve(); state.readGate = null;
    for (const key of Object.keys(labels)) await waitValue(key, state.project[key]);
    const values = { title: '修改后的项目', customer_name: '修改后的客户', product_name: '修改后的产品', brief: '修改后的研发目标\n保留第二行目标' };
    await fill(Object.fromEntries(Object.entries(values).map(([key, value]) => [key, '  ' + value + '  '])));
    state.writeGate = defer();
    const sent = page.waitForRequest(request => request.method() === 'POST' && new URL(request.url()).pathname === projectPath + '/commands');
    await save().click(); await sent;
    await save().evaluate(button => button.click()); await page.keyboard.press('Enter');
    assert.equal(state.calls.length, 1, 'repeated activation during the pending save sends only one request');
    assert.equal(state.calls[0].body.expected_version, 7, 'the save uses the freshly read version');
    assert.deepEqual(state.calls[0].body.data, values, 'all four fields are trimmed before saving');
    state.writeGate.resolve(); state.writeGate = null;
    await dialog.waitFor({ state: 'hidden' });
    const card = page.getByRole('article', { name: values.title, exact: true });
    await card.waitFor();
    assert((await card.innerText()).includes(values.customer_name)); assert((await card.innerText()).includes(values.product_name));
    await snapshot('saved-card');
    await page.reload(); await f.ready();
    for (const key of Object.keys(labels)) await waitValue(key, values[key]);
    assert.equal(state.project.version, 8); assert.equal(state.calls.length, 1);
    checks.push('save: latest detail overrides stale list data; four trimmed fields use latest version; pending duplicate is blocked; receipt updates card and reload rereads saved data');
  },
  async validation(f) {
    await f.openList(); await f.ready();
    await f.field('title').fill('   ');
    if (await f.save().isEnabled()) await f.save().click();
    assert.equal(f.state.calls.length, 0, 'blank names cannot reach the API');
    assert(await f.dialog.isVisible());
    await f.field('title').fill('保留必填项目名称');
    await f.fill({ customer_name: '', product_name: '', brief: '' });
    await f.save().click(); await f.dialog.waitFor({ state: 'hidden' });
    assert.deepEqual(f.state.calls[0].body.data, { title: '保留必填项目名称', customer_name: '', product_name: '', brief: '' });
    checks.push('validation: whitespace-only title never writes; optional customer, product and goal can be cleared');
  },
  async retry(f) {
    await f.openList(); await f.ready(); await f.fill({ title: '网关重试项目', brief: '网关丢失回执后的原始保存' });
    f.state.mode = 'gateway-committed';
    await f.save().click(); await f.dialog.getByRole('alert').filter({ hasText: '网关暂不可用' }).waitFor();
    const first = clone(f.state.calls[0]);
    await f.save().click(); await f.dialog.waitFor({ state: 'hidden' });
    assert.equal(f.state.calls.length, 2); assert.deepEqual(f.state.calls[1], first, '503 retries the original key, version and body');
    assert.equal(f.state.project.version, 4, 'a committed response lost at the gateway is not applied twice');
    checks.push('retry: 503 after commit retains draft and repeats the exact key/body once; response replay does not duplicate the edit');
  },
  async cancel(f) {
    await f.openList(); await f.ready();
    await f.dialog.getByRole('button', { name: '取消', exact: true }).click(); await f.dialog.waitFor({ state: 'hidden' });
    await f.ready(); await f.field('brief').fill('尚未保存的研发目标');
    await f.dialog.getByRole('button', { name: '取消', exact: true }).click();
    await f.page.getByRole('button', { name: '继续编辑', exact: true }).click();
    assert.equal(await f.field('brief').inputValue(), '尚未保存的研发目标');
    await f.dialog.getByRole('button', { name: '取消', exact: true }).click();
    await f.page.getByRole('button', { name: '放弃修改', exact: true }).click(); await f.dialog.waitFor({ state: 'hidden' });
    assert.equal(f.state.calls.length, 0); await f.ready(); await f.waitValue('brief', '原研发目标');
    checks.push('cancel: pristine cancel closes; continue editing retains dirty text; explicit discard closes without writing and reopen restores saved values');
  },
  async conflict(f) {
    await f.openList(); await f.ready(); await f.field('brief').fill('冲突前的未保存目标');
    f.state.project = { ...f.state.project, version: 6, title: '他人已更新的项目', brief: '他人已保存的目标' };
    await f.save().click(); await f.dialog.getByRole('alert').filter({ hasText: '项目已更新' }).waitFor();
    assert.equal(await f.field('brief').inputValue(), '冲突前的未保存目标'); assert(await f.save().isDisabled());
    assert.equal(f.state.calls.length, 1);
    const reads = f.state.reads.filter(path => path === projectPath).length;
    await f.dialog.getByRole('button', { name: '重新读取项目', exact: true }).click();
    await f.page.getByRole('button', { name: '继续编辑', exact: true }).click();
    assert.equal(f.state.reads.filter(path => path === projectPath).length, reads, 'declining reload preserves the draft without fetching over it');
    await f.dialog.getByRole('button', { name: '重新读取项目', exact: true }).click();
    await f.page.getByRole('button', { name: '放弃草稿并重新读取', exact: true }).click();
    await f.waitValue('brief', '他人已保存的目标'); await f.waitValue('title', '他人已更新的项目');
    assert.equal(f.state.calls.length, 1, 'explicit reload never automatically resubmits the old draft');
    await f.field('brief').fill('重新核对后的目标'); await f.save().click(); await f.dialog.waitFor({ state: 'hidden' });
    assert.equal(f.state.calls[1].body.expected_version, 6); assert.notEqual(f.state.calls[1].key, f.state.calls[0].key);
    checks.push('conflict: 409 keeps draft and blocks stale save; reload needs explicit discard confirmation, never autosaves, and next save uses new version/key');
  },
  async access(f) {
    await f.openList(); f.state.readStatus = 503; await f.open();
    await f.dialog.getByRole('alert').filter({ hasText: '项目读取暂不可用' }).waitFor();
    assert(await f.save().isDisabled()); f.state.readStatus = 200;
    await f.dialog.getByRole('button', { name: '重新读取项目', exact: true }).click(); await f.waitValue('title', f.state.project.title);
    for (const mode of ['forbidden', 'missing']) {
      f.state.mode = mode; await f.field('brief').fill('权限变化时尚未保存的目标');
      await f.save().click();
      await f.dialog.getByRole('alert').filter({ hasText: mode === 'forbidden' ? '当前账号无权编辑' : '项目不存在或无权访问' }).waitFor();
      assert.equal(f.state.project.brief, '原研发目标'); assert.equal(await f.field('brief').inputValue(), '权限变化时尚未保存的目标');
      assert(await f.save().isDisabled(), `${mode}: saving remains blocked until access is rechecked`);
      await f.dialog.getByRole('button', { name: '取消', exact: true }).click();
      await f.page.getByRole('button', { name: '放弃修改', exact: true }).click(); await f.dialog.waitFor({ state: 'hidden' });
      f.state.mode = 'success'; if (mode === 'forbidden') await f.ready();
    }
    checks.push('access: failed initial read retries explicitly; 403/404 never replace card data or claim success and preserve the unsaved draft');
  },
  async mobile(f) {
    await f.openList(); await f.ready(); await f.field('brief').fill('手机端项目编辑，确保输入和保存按钮可达。'.repeat(8));
    const geometry = await f.dialog.evaluate(element => { const box = element.getBoundingClientRect(); return { left: box.left, right: box.right, viewport: innerWidth, documentWidth: document.documentElement.scrollWidth }; });
    assert(geometry.left >= 0 && geometry.right <= geometry.viewport + 1 && geometry.documentWidth <= geometry.viewport + 1, 'mobile dialog fits without horizontal overflow');
    for (const key of Object.keys(labels)) assert(await f.field(key).isEditable());
    await f.save().scrollIntoViewIfNeeded(); await f.snapshot('dialog'); await f.save().click(); await f.dialog.waitFor({ state: 'hidden' });
    assert.equal(f.state.calls.length, 1);
    checks.push('mobile: 390px dialog and all four inputs fit; save stays reachable and completes');
  },
  async navigation(f) {
    await f.page.goto(base + '/?rd_view=home');
    await f.page.getByRole('navigation', { name: '研发平台导航', exact: true }).getByRole('button', { name: '项目空间', exact: true }).click();
    await f.ready(); await f.field('brief').fill('浏览器后退前保留的草稿');
    await f.page.goBack();
    await f.page.getByRole('button', { name: '继续编辑', exact: true }).click();
    assert.equal(new URL(f.page.url()).pathname === '/projects' ? 'projects' : new URL(f.page.url()).searchParams.get('rd_view'), 'projects');
    assert.equal(await f.field('brief').inputValue(), '浏览器后退前保留的草稿');
    await f.page.goBack();
    await f.page.getByRole('button', { name: '放弃填写并切换', exact: true }).click();
    await f.dialog.waitFor({ state: 'hidden' });
    await f.page.waitForURL(url => url.pathname === '/work' || url.searchParams.get('rd_view') === 'home');
    assert.equal(await f.page.getByRole('dialog').count(), 0, 'confirmed navigation unmounts the edit and discard dialogs');
    assert.equal(f.state.calls.length, 0);
    checks.push('navigation: browser Back asks before leaving a dirty editor; continue retains draft and route; discard returns to My Work with no residual dialog or write');
  },
  async sidebar(f) {
    f.state.project.cases = [makeCase(f.state.project.title)];
    const url = () => base + '/?rd_view=projects&project=edit-project&case=edit-case&case_view=evidence';
    const sidebar = f.page.locator('.rd-sidebar-case');
    await f.page.goto(url()); await sidebar.getByRole('navigation', { name: '当前业务流程视图', exact: true }).waitFor();
    let text = await sidebar.innerText();
    assert.equal(text.split(f.state.project.title).length - 1, 1, 'same project and workflow names are printed only once');
    assert.match(text, /项目/); assert.match(text, /流程/); assert(text.includes(workflow.title));
    f.state.project.cases[0].title = '独立液冷验证流程'; await f.page.reload(); await sidebar.getByText('独立液冷验证流程', { exact: false }).waitFor();
    text = await sidebar.innerText(); assert(text.includes(f.state.project.title)); assert(text.includes('独立液冷验证流程'));
    f.state.project.cases[0].title = f.state.project.title; delete f.state.project.cases[0].workflow_templates;
    await f.page.reload(); await sidebar.getByRole('navigation', { name: '当前业务流程视图', exact: true }).waitFor();
    text = await sidebar.innerText(); assert.equal(text.split(f.state.project.title).length - 1, 1); assert(text.includes('研制任务书'), 'missing template falls back to the scenario label');
    await f.snapshot('names');
    assert.equal(f.state.calls.length, 0);
    checks.push('sidebar: equal project/workflow names occur once with explicit roles; distinct names remain; absent template uses the scenario label');
  },
};

let passed = false;
try {
  const selected = process.env.TEST_CASE ? [process.env.TEST_CASE] : Object.keys(scenarios);
  for (const name of selected) {
    assert(name in scenarios, 'TEST_CASE must name an existing scenario');
    const f = await fixture(name, name === 'mobile' ? { width: 390, height: 844 } : undefined);
    try { await scenarios[name](f); }
    catch (error) { await f.snapshot('failure').catch(() => {}); throw error; }
    finally { await f.close(); }
  }
  assert.deepEqual(errors, [], 'no browser runtime errors'); assert.deepEqual(unexpected, [], 'all API calls are explicitly mocked'); passed = true;
} finally {
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ passed, checks, errors, unexpected, writes, realApiRequests: 0 }, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ passed, checks, realApiRequests: 0, output }));
