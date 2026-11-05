/** Real project list/detail UI with isolated API fixtures.
 * Every /api request is intercepted; no real project, source, artifact or model is changed.
 */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'docs/rd-platform/verification/screenshots/2026-11-04-project-deletion';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const page = await browser.newPage({ viewport: { width: 1520, height: 980 } });
page.setDefaultTimeout(15000);
const checks = [], errors = [], deletes = [], unexpected = [], reads = [];
page.on('pageerror', error => errors.push(error.message));
const clone = value => structuredClone(value);
const makeCase = id => ({ id, title: id.endsWith('-one') ? '隔离需求受理流程' : '隔离任务书编制流程', scenario_id: 'taskbook', stage: 'input', status: 'active', input_revision: 1,
  context: {}, model_selection: { provider: '', name: '', id: '' }, product_route: null, composition_route: null,
  sources: [], source_selection: {}, requirements: [], workpackages: [], decisions: [], warnings: [], clarifications: [], comparisons: [], deliveries: [], reuse_candidates: [],
});
const makeProject = (id = 'fixture-delete-project', title = '隔离项目删除验收', version = 3) => ({ id, title, version, owner_id: 'fixture-owner', can_delete: true, delete_blocked_reason: '',
  members: [], cases: [makeCase(id + '-one'), makeCase(id + '-two')], events: [], brief: '项目删除浏览器隔离夹具', customer_name: '测试客户', product_name: '测试产品',
  created_at: '2026-11-04T00:00:00Z', updated_at: '2026-11-04T00:00:00Z',
});
const fixture = makeProject();
const state = { projects: [clone(fixture)], mode: 'success', attempts: 0, hold: null };
const dialog = page.getByRole('dialog', { name: '删除项目', exact: true });
const icon = title => page.getByRole('button', { name: `删除项目“${title}”`, exact: true });
const confirm = () => dialog.getByRole('button', { name: /^(删除项目|重试.*)$/ });
const snap = name => page.screenshot({ path: join(output, name + '.png'), fullPage: true });
const reset = (projects = [clone(fixture)], mode = 'success') => { state.projects = clone(projects); state.mode = mode; state.attempts = 0; state.hold = null; };
const openList = async (query = '') => {
  await page.goto(base + '/?rd_view=projects' + query);
  await page.getByRole('heading', { name: '项目空间', exact: true }).waitFor();
  await page.getByRole('status').filter({ hasText: '正在读取项目' }).waitFor({ state: 'hidden' });
};
const openDetail = async (project = fixture) => {
  await page.goto(base + '/?rd_view=projects&project=' + encodeURIComponent(project.id));
  await page.getByRole('heading', { name: project.title, exact: true }).waitFor();
};
const openDelete = async project => {
  await icon(project.title).click();
  await dialog.waitFor();
};
const waitForDelete = () => page.waitForRequest(request => request.method() === 'DELETE' && new URL(request.url()).pathname.startsWith('/api/rd/projects/'));
const assertRequest = (call, project) => {
  assert.equal(call.path, '/api/rd/projects/' + encodeURIComponent(project.id));
  assert.equal(call.version, String(project.version));
  assert.ok(call.key, 'delete carries an Idempotency-Key');
  assert.equal(call.body, null, 'delete version is sent in the query');
};

await page.route('**/api/**', async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
  if (!path.startsWith('/api/')) return route.continue();
  const json = value => route.fulfill({ json: value });
  if (method === 'GET') {
    reads.push(path);
    if (path === '/api/current-user') return json({ auth_enabled: false, authenticated: false, user: null });
    if (path === '/api/rd/session') return json({ actor_id: 'fixture-owner', local_mode: true });
    if (path === '/api/rd/catalog') return json({ stages: [], scenarios: [{ id: 'taskbook', title: '隔离项目流程' }], actions: [], workpackage_definitions: [], project_workflow_templates: [] });
    if (path === '/api/rd/projects') return json({ projects: clone(state.projects) });
    if (path === '/api/rd/assistant/weather') return route.fulfill({ status: 503, json: { error: '隔离删除测试不加载天气服务' } });
    if (path.startsWith('/api/rd/projects/')) {
      const id = decodeURIComponent(path.slice('/api/rd/projects/'.length));
      const project = state.projects.find(item => item.id === id);
      return project ? json(clone(project)) : route.fulfill({ status: 404, json: { detail: '项目不存在' } });
    }
  }
  if (method === 'DELETE' && path.startsWith('/api/rd/projects/')) {
    const call = { path, version: url.searchParams.get('expected_version'), key: request.headers()['idempotency-key'] || '', body: request.postData() };
    deletes.push(call); state.attempts += 1;
    if (state.mode === 'forbidden') return route.fulfill({ status: 403, json: { detail: '只有项目负责人可以删除项目' } });
    if (state.mode === 'conflict') return route.fulfill({ status: 409, json: { detail: '项目版本已变化，请重新读取项目后再次确认' } });
    if (state.mode === 'network-first' && state.attempts === 1) return route.abort('failed');
    if (state.hold) await state.hold;
    const id = decodeURIComponent(path.slice('/api/rd/projects/'.length));
    state.projects = state.projects.filter(item => item.id !== id);
    if (state.mode === 'gateway-committed') return route.fulfill({ status: 503, json: { detail: '网关返回失败' } });
    return json({ ok: true, project_id: id, version: Number(call.version) + 1, deleted_at: '2026-11-04T02:00:00Z' });
  }
  unexpected.push({ method, path });
  return route.fulfill({ status: 500, json: { detail: '未预期的隔离测试请求' } });
});

try {
  await openList();
  await icon(fixture.title).focus();
  assert.equal(await icon(fixture.title).evaluate(element => document.activeElement === element), true, 'list delete icon is keyboard focusable');
  await page.keyboard.press('Enter');
  await dialog.waitFor();
  const message = await dialog.innerText();
  assert.ok(message.includes(fixture.title), 'confirmation identifies the project');
  assert.match(message, /2\s*个.*流程/, 'confirmation counts the contained workflows');
  assert.match(message, /来源|资料/, 'confirmation explains source access');
  assert.match(message, /成果/, 'confirmation explains result access');
  assert.match(message, /逻辑删除|追溯|保留/, 'confirmation explains retained trace records');
  assert.equal(deletes.length, 0, 'opening confirmation does not send DELETE');
  await snap('01-列表删除确认');
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await dialog.waitFor({ state: 'hidden' });
  assert.equal(deletes.length, 0, 'cancel sends no DELETE');
  assert.equal(await icon(fixture.title).evaluate(element => document.activeElement === element), true, 'cancel restores focus to the delete icon');
  checks.push('列表角标键盘可用；确认显示项目、流程数量和资料成果影响；取消零写入并归还焦点');

  const foreign = { ...makeProject('fixture-foreign', '非负责人项目'), owner_id: 'another-owner', can_delete: false };
  const active = { ...makeProject('fixture-active', '执行中的项目'), delete_blocked_reason: '项目存在提交中或运行中的任务，暂时不能删除' };
  active.cases[0].workpackages = [{ id: 'fixture-running', title: '正在执行的任务', status: 'running', nodes: [], artifacts: [], obligations: [], blocked_reasons: [] }];
  reset([fixture, foreign, active]);
  await openList();
  assert.equal(await icon(foreign.title).count(), 0, 'non-owner delete entry is absent');
  assert.equal(await icon(active.title).isDisabled(), true, 'active runtime disables the owner icon');
  await icon(active.title).locator('..').hover();
  await page.getByRole('tooltip').filter({ hasText: active.delete_blocked_reason }).waitFor();
  assert.equal(deletes.length, 0);
  await snap('02-负责人及执行限制');
  await openDetail(foreign);
  assert.equal(await icon(foreign.title).count(), 0, 'detail also hides non-owner entry');
  await openDetail(active);
  assert.equal(await icon(active.title).isDisabled(), true, 'detail also blocks active runtime');
  checks.push('列表和详情均隐藏非负责人入口；运行中负责人入口禁用并提示原因');

  reset();
  await openDetail();
  await openDelete(fixture);
  const start = deletes.length;
  let release;
  state.hold = new Promise(resolve => { release = resolve; });
  await Promise.all([waitForDelete(), confirm().click()]);
  assert.equal(await dialog.getByRole('button', { name: '取消', exact: true }).isDisabled(), true, 'in-flight cancellation is disabled');
  await page.keyboard.press('Escape');
  await page.locator('.ant-modal-wrap').click({ position: { x: 5, y: 5 } });
  assert.equal(await dialog.isVisible(), true, 'Escape and mask retain the pending request');
  assert.equal(deletes.length, start + 1, 'pending confirmation submits once');
  assertRequest(deletes.at(-1), fixture);
  release();
  await dialog.waitFor({ state: 'hidden' });
  await page.getByRole('heading', { name: '项目空间', exact: true }).waitFor();
  await page.getByRole('heading', { name: '还没有项目', exact: true }).waitFor();
  const returned = new URL(page.url());
  assert.equal(returned.searchParams.get('rd_view'), 'projects');
  assert.equal(returned.searchParams.has('project'), false, 'deleting the current project clears its URL');
  assert.equal(returned.searchParams.has('case'), false);
  assert.equal(await icon(fixture.title).count(), 0, 'success removes the deleted project');
  await snap('03-详情删除后返回项目空间');
  checks.push('详情确认发送版本与幂等键；处理中遮罩/Escape不取消；成功移除项目并返回项目空间');

  reset([fixture], 'forbidden');
  await openList();
  await openDelete(fixture);
  await confirm().click();
  await dialog.getByRole('alert').filter({ hasText: '只有项目负责人' }).waitFor();
  assert.equal(await dialog.isVisible(), true, '403 retains confirmation and its error');
  assert.equal(await icon(fixture.title).count(), 1, '403 does not remove project');
  assert.equal(state.projects.length, 1);
  await snap('04-权限失败保留项目');
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  checks.push('403错误留在确认框，项目仍可见，不冒充删除成功');

  reset([fixture], 'conflict');
  await openList();
  await openDelete(fixture);
  const conflictStart = deletes.length;
  await confirm().click();
  await dialog.getByRole('alert').filter({ hasText: '版本已变化' }).waitFor();
  assert.equal(await dialog.isVisible(), true);
  assert.equal(await confirm().isDisabled(), true, 'conflict requires explicit read before confirming');
  assert.equal(deletes.length, conflictStart + 1);
  const conflictCall = deletes.at(-1);
  state.projects[0] = { ...state.projects[0], version: fixture.version + 1, title: '已重读的隔离项目' };
  const latest = clone(state.projects[0]);
  const projectReads = reads.filter(path => path === '/api/rd/projects/' + fixture.id).length;
  await dialog.getByRole('button', { name: '重新读取项目', exact: true }).click();
  await dialog.getByText(latest.title, { exact: false }).first().waitFor();
  assert.ok(reads.filter(path => path === '/api/rd/projects/' + fixture.id).length > projectReads, 'conflict recovery reads the targeted project');
  assert.equal(deletes.length, conflictStart + 1, 'reading a new version does not auto-delete it');
  assert.equal(await confirm().isEnabled(), true);
  await snap('05-冲突重读后再次确认');
  state.mode = 'success';
  await confirm().click();
  await dialog.waitFor({ state: 'hidden' });
  assertRequest(deletes.at(-1), latest);
  assert.notEqual(deletes.at(-1).key, conflictCall.key, 'newly confirmed version starts a new idempotency key');
  assert.equal(deletes.length, conflictStart + 2);
  checks.push('409保留弹窗并禁止旧版确认；显式重读目标后再次确认，用新版本和新幂等键删除');

  reset([fixture], 'network-first');
  await openList();
  await openDelete(fixture);
  const retryStart = deletes.length;
  await confirm().click();
  await dialog.getByRole('alert').waitFor();
  assert.equal(await icon(fixture.title).count(), 1, 'network failure retains project');
  const unknownCall = deletes.at(-1);
  assertRequest(unknownCall, fixture);
  await snap('06-网络失败同次重试');
  await confirm().click();
  await dialog.waitFor({ state: 'hidden' });
  await page.getByRole('heading', { name: '还没有项目', exact: true }).waitFor();
  assert.equal(deletes.length, retryStart + 2);
  assert.deepEqual(deletes.at(-1), unknownCall, 'uncertain retry preserves project, expected version and idempotency key');
  checks.push('网络失败保留项目；重试固定同一个项目、版本和幂等键');

  reset([fixture], 'gateway-committed');
  await openDetail();
  await openDelete(fixture);
  const gatewayStart = deletes.length;
  await confirm().click();
  await dialog.getByRole('alert').filter({ hasText: '网关返回失败' }).waitFor();
  await dialog.getByRole('status').filter({ hasText: '请求结果尚未确认' }).waitFor();
  assert.equal(state.projects.length, 0, 'gateway fixture committed deletion before returning 503');
  assert.equal(deletes.length, gatewayStart + 1);
  assertRequest(deletes.at(-1), fixture);
  const gatewayReads = reads.filter(path => path === '/api/rd/projects').length;
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await dialog.waitFor({ state: 'hidden' });
  await page.getByRole('heading', { name: '项目空间', exact: true }).waitFor();
  await page.getByRole('heading', { name: '还没有项目', exact: true }).waitFor();
  assert.ok(reads.filter(path => path === '/api/rd/projects').length > gatewayReads, 'closing uncertain gateway result rereads the project list');
  const gatewayReturn = new URL(page.url());
  assert.equal(gatewayReturn.searchParams.get('rd_view'), 'projects');
  assert.equal(gatewayReturn.searchParams.has('project'), false, 'gateway reconciliation clears the stale detail URL');
  assert.equal(gatewayReturn.searchParams.has('case'), false);
  assert.equal(await page.getByRole('status').filter({ hasText: '项目已删除' }).count(), 0, 'uncertain response does not claim confirmed deletion');
  assert.equal(deletes.length, gatewayStart + 1, 'cancel reconciles without another delete request');
  await snap('09-网关异常后核对项目');
  checks.push('删除已提交但网关503时提示结果未确认；取消后重读项目列表、清除详情URL，不伪造成功通知');

  const others = Array.from({ length: 5 }, (_, index) => makeProject('fixture-page-' + index, '分页保留项目 ' + index));
  reset([...others, fixture]);
  await openList('&page=2');
  await icon(fixture.title).waitFor();
  await openDelete(fixture);
  await confirm().click();
  await dialog.waitFor({ state: 'hidden' });
  await page.getByText('第 1 / 1 页', { exact: true }).waitFor();
  assert.equal(await page.locator('.rd-project-entry').count(), 5, 'deleting the last card repairs the displayed pagination');
  assert.equal(await icon(fixture.title).count(), 0);
  checks.push('删除末页唯一项目后修正分页并显示剩余项目');

  reset();
  await page.setViewportSize({ width: 390, height: 844 });
  await openList();
  const bounds = await icon(fixture.title).boundingBox();
  assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 391, '390px delete icon stays in the viewport');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, '390px list has no page overflow');
  await snap('07-390px项目角标');
  await openDelete(fixture);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, '390px confirmation has no page overflow');
  const mobileConfirm = await confirm().boundingBox();
  assert.ok(mobileConfirm && mobileConfirm.x >= 0 && mobileConfirm.x + mobileConfirm.width <= 391, '390px confirmation action remains reachable');
  await snap('08-390px删除确认');
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await openDetail();
  assert.equal(await icon(fixture.title).isVisible(), true);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, '390px detail has no page overflow');
  checks.push('390px列表角标、确认按钮与详情入口可见可达，无页面横向溢出');

  assert.deepEqual(unexpected, [], 'all API requests use explicit isolated fixtures');
  assert.deepEqual(errors, [], 'project deletion renders without browser errors');
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ checks, pageErrors: errors, unexpectedRequests: unexpected, fixtureDeletes: deletes.length, realApiRequests: 0 }, null, 2));
  console.log(JSON.stringify({ passed: checks.length, checks, fixtureDeletes: deletes.length, realApiRequests: 0, screenshots: output }));
} catch (error) {
  await snap('failure').catch(() => {});
  console.error(JSON.stringify({ completedChecks: checks, pageErrors: errors, unexpectedRequests: unexpected, reads, fixtureDeletes: deletes }));
  throw error;
} finally {
  await browser.close();
}
