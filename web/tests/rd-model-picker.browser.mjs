/** Real CaseInputForm, CurrentUserProvider and StyledSelect with isolated API fixtures.
 * No real model invocation, source upload or project mutation is possible.
 */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'docs/rd-platform/verification/screenshots/2026-11-04-model-picker';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const errors = [], unexpected = [], saves = [], analyses = [], checks = [], sessionReplies = [], controlRows = [];
let observed = {};
context.on('page', target => { target.setDefaultTimeout(15000); target.on('pageerror', error => errors.push(error.message)); });
page.on('pageerror', error => errors.push(error.message));
const models = [
  { provider: 'smartvision', name: 'azure/gpt-5.4', id: 'azure-gpt54', vendor: '微软 Azure', configured: true },
  { provider: 'smartvision', name: 'dashscope/qwen3.5-plus', id: 'dashscope-qwen35', vendor: '阿里云 DashScope', configured: true },
  ...Array.from({ length: 4 }, (_, index) => ({ provider: 'smartvision', name: 'azure/engineering-' + (index + 1), id: 'azure-engineering-' + (index + 1), vendor: '微软 Azure', configured: true })),
];
const transportModels = models.map(({ name, ...model }) => ({ ...model, model: name }));
const emptySelection = () => ({ id: '', name: '', provider: '' });
const researchCase = { id: 'fixture-model-case', title: '模型选择隔离验收', scenario_id: 'taskbook', stage: 'input', status: 'active', input_revision: 1,
  context: {}, model_selection: emptySelection(), product_route: null, composition_route: null,
  sources: [{ id: 'fixture-model-source', role: 'tech', name: '模型选择隔离资料.txt', size: 64, version: 1, sha256: 'fixture-model-source-sha', created_at: '2026-11-04T00:00:00Z' }], source_selection: { tech: 'fixture-model-source' },
  requirements: [], workpackages: [], decisions: [], warnings: [], clarifications: [], comparisons: [], deliveries: [], reuse_candidates: [],
};
const state = { actor: 'fixture-model-owner-a', actorAfterSave: '', sessionHold: null, failModels: false, failSession: false, failSave: false, models: structuredClone(transportModels),
  project: { id: 'fixture-model-project', title: researchCase.title, version: 1, owner_id: 'fixture-owner', members: [], cases: [researchCase], events: [] },
};
const label = model => `${model.vendor} · ${model.name}`;
const combo = target => target.getByRole('combobox', { name: '编制模型', exact: true });
const selectedText = target => target.locator('.rd-context-form .ant-select-selection-item').innerText();
const popup = target => target.locator('.ant-select-dropdown:visible');
const snap = name => page.screenshot({ path: join(output, name + '.png'), animations: 'disabled', fullPage: true });
const storage = target => target.evaluate(() => Object.fromEntries(Object.entries(localStorage)));
const measureAnalysisRow = async () => {
  await page.evaluate(() => document.fonts.ready);
  const [selector, analyzeButton] = await Promise.all([
    combo(page).locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').boundingBox(),
    page.getByRole('button', { name: '分析上传资料', exact: true }).boundingBox(),
  ]);
  controlRows.push({ viewport: page.viewportSize(), selector, analyzeButton,
    bottomDelta: analyzeButton.y + analyzeButton.height - selector.y - selector.height,
    heightDelta: analyzeButton.height - selector.height,
  });
};
const focusIdentity = () => page.evaluate(() => { window.dispatchEvent(new Event('focus')); });
const visibleIdentity = () => page.evaluate(() => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  document.dispatchEvent(new Event('visibilitychange'));
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  document.dispatchEvent(new Event('visibilitychange'));
});
const waitForSessionSettled = async target => {
  await target.waitForFunction(() => {
    const session = window.__modelFixtureSession;
    return session?.completed > 0 && session.pending === 0 && performance.now() - session.lastActivity >= 100;
  });
  await target.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
};

await context.route('**/__rd-model-picker-fixture', route => route.fulfill({ contentType: 'text/html', body: '<html lang="zh-CN"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>研发模型选择隔离验收</title></head><body><div id="fixture"></div></body></html>' }));
await context.route('**/api/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname;
  if (!path.startsWith('/api/')) return route.continue();
  if (request.method() === 'GET') {
    if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
    if (path === '/api/rd/session') {
      const response = state.failSession ? { status: 503, json: { detail: '会话读取测试失败' } } : { json: { actor_id: state.actor, local_mode: true } };
      const hold = state.sessionHold; state.sessionHold = null;
      if (hold) { hold.started(); await hold.wait; }
      await route.fulfill(response);
      sessionReplies.push({ actor: response.json.actor_id || '', delayed: !!hold });
      return;
    }
    if (path === '/api/models') return route.fulfill(state.failModels ? { status: 503, json: { error: '模型目录读取测试失败' } } : { json: { success: true, models: state.models } });
    if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [] } });
  }
  if (request.method() === 'POST' && path === '/api/rd/projects/fixture-model-project/commands') {
    const body = request.postDataJSON(); saves.push(body);
    assert.equal(body.command, 'save_context');
    assert.equal(body.expected_version, state.project.version);
    assert.equal(body.data.case_id, 'fixture-model-case');
    assert.deepEqual(Object.keys(body.data.model_selection).sort(), ['id', 'name', 'provider'], 'display metadata is never persisted as model selection');
    if (body.data.model_selection.name) assert.equal(body.data.model_selection.provider, 'smartvision', 'vendor labels do not replace the invocation provider');
    if (state.failSave) return route.fulfill({ status: 422, json: { detail: '模型设置保存测试失败' } });
    state.project = { ...state.project, version: state.project.version + 1,
      cases: [{ ...state.project.cases[0], input_revision: state.project.cases[0].input_revision + 1, model_selection: structuredClone(body.data.model_selection) }],
    };
    if (state.actorAfterSave) { state.actor = state.actorAfterSave; state.actorAfterSave = ''; }
    return route.fulfill({ json: state.project });
  }
  if (request.method() === 'POST' && path === '/api/rd/projects/fixture-model-project/cases/fixture-model-case/analysis') {
    const body = request.postDataJSON();
    assert.equal(body.expected_version, state.project.version, 'analysis uses the project returned by the model save');
    analyses.push({ body, key: request.headers()['idempotency-key'] });
    state.project = { ...state.project, version: state.project.version + 1 };
    return route.fulfill({ json: state.project });
  }
  unexpected.push({ method: request.method(), path });
  return route.fulfill({ status: 500, json: { detail: '未预期的隔离测试请求' } });
});

async function mount(target = page, { origin = base, reload = false, waitForSession = true } = {}) {
  if (reload) await target.reload(); else await target.goto(origin + '/__rd-model-picker-fixture');
  const catalogResponse = target.waitForResponse(response => new URL(response.url()).pathname === '/api/models');
  const hydrated = target.evaluate(async fixtureProject => {
    const fetchOriginal = window.fetch.bind(window);
    const session = window.__modelFixtureSession = { pending: 0, completed: 0, lastActivity: performance.now() };
    window.fetch = async (input, init) => {
      const path = new URL(input instanceof Request ? input.url : String(input), location.href).pathname;
      if (path !== '/api/rd/session') return fetchOriginal(input, init);
      session.pending += 1; session.lastActivity = performance.now();
      try {
        const response = await fetchOriginal(input, init);
        await response.clone().arrayBuffer();
        session.completed += 1;
        return response;
      } finally { session.pending -= 1; session.lastActivity = performance.now(); }
    };
    const refresh = await import('/@react-refresh'); refresh.default.injectIntoGlobalHook(window);
    window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => type => type; window.__vite_plugin_react_preamble_installed__ = true;
    const React = (await import('/node_modules/.vite/deps/react.js')).default;
    const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
    const { PlatformTheme } = await import('/src/components/ui/PlatformTheme.tsx');
    const { CurrentUserProvider } = await import('/src/hooks/useCurrentUser.tsx');
    const { CaseInputForm } = await import('/src/features/rd/CaseInputForm.tsx');
    const { rdCommand, rdAnalyzeSources, makeRequestKey } = await import('/src/features/rd/api.ts');
    for (const file of ['/src/styles.css', '/src/features/rd/rd.css', '/src/features/rd/caseWorkspace.css', '/src/features/rd/rdExperience.css', '/src/features/rd/rdApplicationShell.css']) await import(file);
    const h = React.createElement;
    function Fixture() {
      const [project, setProject] = React.useState(fixtureProject), [busy, setBusy] = React.useState(false), [error, setError] = React.useState('');
      const currentProject = React.useRef(project); currentProject.current = project;
      const analyzing = React.useRef(false);
      const modelRetry = React.useRef({ fingerprint: '', key: '' });
      const analysisRetry = React.useRef({ fingerprint: '', key: '' });
      async function command(name, data, onSuccess) {
        setBusy(true); setError('');
        try {
          const saved = await rdCommand(project, name, { ...data, case_id: project.cases[0].id }, makeRequestKey());
          setProject(saved); onSuccess?.(); return true;
        } catch (reason) { setError(reason.message); return false; }
        finally { setBusy(false); }
      }
      // Exercise the component's new analyze boundary using isolated API receipts.
      // The full-page source-analysis file separately verifies the real project coordinator.
      async function analyze(caseId, modelChange) {
        if (analyzing.current) return false;
        analyzing.current = true; setBusy(true); setError('');
        let target = currentProject.current;
        try {
          if (modelChange) {
            const data = { case_id: caseId, context: target.cases[0].context, model_selection: modelChange.selection };
            const fingerprint = JSON.stringify([target.id, target.version, data]);
            if (modelRetry.current.fingerprint !== fingerprint) modelRetry.current = { fingerprint, key: makeRequestKey() };
            target = await rdCommand(target, 'save_context', data, modelRetry.current.key);
            currentProject.current = target; setProject(target); modelChange.onSaved();
            modelRetry.current = { fingerprint: '', key: '' };
          }
          const fingerprint = JSON.stringify([target.id, target.version, caseId]);
          if (analysisRetry.current.fingerprint !== fingerprint) analysisRetry.current = { fingerprint, key: makeRequestKey() };
          target = await rdAnalyzeSources(target, caseId, analysisRetry.current.key);
          currentProject.current = target; setProject(target);
          analysisRetry.current = { fingerprint: '', key: '' }; return true;
        } catch (reason) { setError(reason.message); return false; }
        finally { analyzing.current = false; setBusy(false); }
      }
      return h('div', { className: 'rd-shell rd-application-shell', style: { display: 'block', minHeight: '100vh' } },
        h('main', { className: 'rd-page-content rd-focused-case', style: { maxWidth: 1000 } },
          h('h1', null, '研发模型选择验收'), h('p', null, '隔离夹具，不调用真实模型或修改实际项目。'),
          error && h('p', { role: 'alert' }, error),
          h(CaseInputForm, { project, researchCase: project.cases[0], busy, error, command, onAnalyze: analyze, onUpload: async () => { throw new Error('Fixture forbids uploads'); }, onDirtyChange: () => {} })));
    }
    createRoot(document.getElementById('fixture')).render(h(PlatformTheme, null, h(CurrentUserProvider, null, h(Fixture))));
  }, structuredClone(state.project));
  await Promise.all([hydrated, catalogResponse]);
  if (waitForSession) await waitForSessionSettled(target);
  await combo(target).waitFor();
}

async function openPicker(target = page) {
  await combo(target).locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').click();
  await target.getByRole('listbox').waitFor();
}

async function choose(model, target = page) {
  await openPicker(target);
  await target.getByRole('option', { name: model ? label(model) : '使用平台默认模型', exact: true }).click();
}

async function analyzeSelection(target = page) {
  await Promise.all([
    target.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/analysis')),
    target.getByRole('button', { name: '分析上传资料', exact: true }).click(),
  ]);
  await target.getByRole('button', { name: '分析上传资料', exact: true }).click({ trial: true });
  await waitForSessionSettled(target);
}

async function analyzeBeforeIdentitySettles() {
  await Promise.all([
    page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/analysis')),
    page.getByRole('button', { name: '分析上传资料', exact: true }).click(),
  ]);
  await page.getByRole('button', { name: '分析上传资料', exact: true }).click({ trial: true });
}

function holdNextSession() {
  let started, release;
  const waiting = Promise.all([
    new Promise(resolve => { started = resolve; }),
    page.waitForRequest(request => new URL(request.url()).pathname === '/api/rd/session'),
  ]);
  state.sessionHold = { started, wait: new Promise(resolve => { release = resolve; }) };
  return { waiting, release };
}

async function recentLabels(target = page) {
  return popup(target).locator('.ant-select-item-group,.ant-select-item-option').evaluateAll(nodes => {
    let recent = false;
    const labels = [];
    for (const node of nodes) {
      if (node.classList.contains('ant-select-item-group')) recent = node.textContent.trim() === '最近使用';
      else if (recent) labels.push((node.querySelector('.ant-select-item-option-content')?.textContent || node.textContent).trim());
    }
    return labels;
  });
}

async function assertRecents(expected, target = page) {
  await openPicker(target);
  if (expected.length) {
    await popup(target).getByText('最近使用', { exact: true }).waitFor();
    const groups = await popup(target).locator('.ant-select-item-group').allTextContents();
    assert.equal(groups[0], '最近使用', 'recent models are the first group');
  } else assert.equal(await popup(target).getByText('最近使用', { exact: true }).count(), 0);
  assert.deepEqual(await recentLabels(target), expected.map(label));
}

try {
  await mount(page, { waitForSession: false });
  const defaultLabel = await selectedText(page);
  await openPicker();
  observed = { defaultLabel, optionLabels: await page.getByRole('option').allTextContents() };
  assert.equal(defaultLabel, '使用平台默认模型', 'empty model selection stays readable regardless of server field order');
  await page.getByRole('option', { name: label(models[0]), exact: true }).waitFor();
  await page.getByRole('option', { name: label(models[1]), exact: true }).waitFor();
  await waitForSessionSettled(page);
  assert.equal(await popup(page).getByText('最近使用', { exact: true }).count(), 0, 'new actor has no recent models');
  await snap('01-可读默认模型与厂商名称');
  await page.keyboard.press('Escape');
  await measureAnalysisRow();
  await snap('09-默认编制模型仅下拉框');
  checks.push('空模型字段顺序不显示JSON；微软Azure/阿里云DashScope厂商和模型名称可读');

  const emptyHistory = await storage(page);
  await choose(models[1]);
  assert.equal(await page.getByRole('button', { name: '保存模型设置', exact: true }).count(), 0, 'model choice is saved by analysis without a separate save button');
  assert.equal(await page.getByText('请先上传已选文件或保存模型设置，再分析与采用。', { exact: true }).count(), 0, 'model changes no longer ask for a separate save');
  assert.equal(await page.getByRole('button', { name: '分析上传资料', exact: true }).isEnabled(), true, 'a model change can be analyzed directly');
  assert.equal(saves.length, 0, 'selecting a model alone does not save the project');
  assert.deepEqual(await storage(page), emptyHistory, 'selecting alone does not record a recent model');
  await mount(page, { reload: true });
  await assertRecents([]);
  await page.keyboard.press('Escape');
  await choose(models[1]);
  state.failSave = true;
  const analysesBeforeFailedSave = analyses.length;
  await page.getByRole('button', { name: '分析上传资料', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '模型设置保存测试失败' }).waitFor();
  assert.equal(analyses.length, analysesBeforeFailedSave, 'failed model save does not start analysis');
  assert.deepEqual(await storage(page), emptyHistory, 'failed save does not record a recent model');
  assert((await selectedText(page)).includes(models[1].name), 'save failure preserves the selected input');
  state.failSave = false;
  await mount(page, { reload: true });
  await assertRecents([]);
  await page.keyboard.press('Escape');
  await choose(models[0]);
  await analyzeSelection();
  const savedHistory = await storage(page);
  assert.notDeepEqual(savedHistory, emptyHistory, 'successful non-default save records recent usage');
  await mount(page, { reload: true });
  await assertRecents([models[0]]);
  assert.equal(await page.getByRole('option', { name: label(models[0]), exact: true }).count(), 1, 'recent model is not duplicated in the remaining choices');
  await snap('02-保存后刷新保留最近使用');
  await page.keyboard.press('Escape');
  await choose(null);
  await analyzeSelection();
  assert.deepEqual(await storage(page), savedHistory, 'saving platform default does not change non-default recent usage');
  assert.equal(await selectedText(page), '使用平台默认模型');
  checks.push('仅选择、保存失败及保存默认模型不写最近记录；成功保存后刷新保留并去重');

  for (const model of models.slice(1)) { await choose(model); await analyzeSelection(); }
  const latestFive = models.slice(1).reverse();
  await assertRecents(latestFive);
  assert.equal((await recentLabels(page)).length, 5, 'recent group holds at most five models');
  assert.equal(await page.getByRole('option', { name: label(models[0]), exact: true }).count(), 1, 'evicted model remains available in the ordinary directory');
  await page.keyboard.press('Escape');
  await choose(models[2]);
  await analyzeSelection();
  const reordered = [models[2], models[5], models[4], models[3], models[1]];
  await assertRecents(reordered);
  for (const model of reordered) assert.equal(await page.getByRole('option', { name: label(model), exact: true }).count(), 1);
  await snap('03-最近五条按成功使用排序');
  await page.keyboard.press('Escape');
  checks.push('最近使用最多五条，成功复用移到首位，整个下拉中同一模型不重复');

  state.actor = 'fixture-model-owner-b';
  await mount(page, { reload: true });
  await assertRecents([]);
  assert((await selectedText(page)).includes(models[2].name), 'a different actor can still read the server-saved model');
  await page.keyboard.press('Escape');
  state.actor = 'fixture-model-owner-a';
  await mount(page, { reload: true });
  await assertRecents(reordered);
  await page.keyboard.press('Escape');
  const alternate = new URL(base); alternate.hostname = alternate.hostname === 'localhost' ? '127.0.0.1' : 'localhost';
  const otherOrigin = await context.newPage();
  await mount(otherOrigin, { origin: alternate.origin });
  assert.notEqual(new URL(otherOrigin.url()).origin, new URL(page.url()).origin);
  await assertRecents([], otherOrigin);
  await otherOrigin.close();
  await assertRecents(reordered);
  await page.keyboard.press('Escape');
  checks.push('同一浏览器中不同actor及不同origin不共享最近记录，原账号历史继续保留');

  state.models = models.filter(model => model.id !== models[2].id).map(model => model.id === models[5].id ? { ...model, configured: false } : model);
  await mount(page, { reload: true });
  const historicalLabel = await selectedText(page);
  assert(historicalLabel.includes(models[2].name), 'saved model missing from the directory remains readable');
  assert.doesNotMatch(historicalLabel, /^\s*\{/);
  await assertRecents([models[4], models[3], models[1]]);
  assert.equal(await page.getByRole('option', { name: label(models[2]), exact: true }).count(), 0, 'missing saved model is not offered as a normal available choice');
  await snap('04-目录缺失时仍可读历史模型');
  await page.keyboard.press('Escape');
  checks.push('最近分组过滤目录缺失及未就绪模型，当前已保存历史值保持可读且不自动换模型');

  state.failModels = true;
  await mount(page, { reload: true });
  await page.getByRole('alert').filter({ hasText: '模型目录读取测试失败' }).waitFor();
  assert((await selectedText(page)).includes(models[2].name));
  assert.doesNotMatch(await selectedText(page), /^\s*\{/);
  await assertRecents([]);
  await page.keyboard.press('Escape');
  state.failModels = false; state.models = structuredClone(transportModels);
  await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/api/models'),
    page.getByRole('button', { name: '重新获取', exact: true }).click(),
  ]);
  await page.locator('.rd-context-form .ant-select-selection-item').filter({ hasText: label(models[2]) }).waitFor();
  await assertRecents(reordered);
  await page.keyboard.press('Escape');
  state.failSession = true;
  await mount(page, { reload: true });
  await assertRecents([]);
  assert((await selectedText(page)).includes(models[2].name), 'session failure does not hide the saved model');
  await page.keyboard.press('Escape');
  state.failSession = false;
  checks.push('模型目录失败可读已保存值并重试恢复；会话读取失败不显示缓存中的其他历史');

  await page.setViewportSize({ width: 390, height: 844 });
  await mount(page, { reload: true });
  await combo(page).scrollIntoViewIfNeeded();
  await measureAnalysisRow();
  await snap('10-390px仅下拉框');
  await combo(page).focus();
  await page.keyboard.press('ArrowDown');
  await popup(page).getByText('最近使用', { exact: true }).waitFor();
  await combo(page).focus();
  await page.keyboard.press('Home');
  let selectedByKeyboard = false;
  for (let index = 0; index < models.length + 2; index += 1) {
    const active = await combo(page).getAttribute('aria-activedescendant');
    const text = active ? await page.locator('[id="' + active + '"]').innerText() : '';
    if (text.includes(models[1].name)) { await page.keyboard.press('Enter'); selectedByKeyboard = true; break; }
    await page.keyboard.press('ArrowDown');
  }
  assert.equal(selectedByKeyboard, true, 'keyboard navigation can select a recent model');
  assert((await selectedText(page)).includes(models[1].name));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, '390px picker does not overflow the page');
  await analyzeSelection();
  assert.deepEqual(saves.at(-1).data.model_selection, { provider: models[1].provider, name: models[1].name, id: models[1].id });
  await openPicker();
  const mobilePopup = await popup(page).boundingBox();
  assert(mobilePopup && mobilePopup.x >= 0 && mobilePopup.x + mobilePopup.width <= 391, '390px dropdown remains within the viewport');
  await snap('05-390px键盘选择与最近分组');
  await page.keyboard.press('Escape');
  checks.push('390px键盘可选择并保存最近模型，下拉无横向溢出，实际调用provider保持smartvision');

  await page.setViewportSize({ width: 1440, height: 1000 });
  const actorARecent = [models[1], models[2], models[5], models[4], models[3]];
  await assertRecents(actorARecent);
  await page.keyboard.press('Escape');
  const sameDocument = await page.evaluate(() => performance.timeOrigin);
  const historyBeforeActorChange = await storage(page);
  const sessionsBeforeSave = await page.evaluate(() => window.__modelFixtureSession.completed);
  await choose(models[0]);
  state.actorAfterSave = 'fixture-model-owner-b';
  await analyzeSelection();
  await waitForSessionSettled(page);
  assert.equal(state.actor, 'fixture-model-owner-b', 'fixture switches the shared server identity while the save is in flight');
  assert.deepEqual(await storage(page), historyBeforeActorChange, 'a save completed under a changed actor must not be recorded against either uncertain identity');
  assert.ok(await page.evaluate(() => window.__modelFixtureSession.completed) > sessionsBeforeSave, 'successful save reconfirms the current server actor');
  await assertRecents([]);
  await page.keyboard.press('Escape');
  assert((await selectedText(page)).includes(models[0].name), 'confirmed project save remains readable after an actor switch');

  const refreshIdentity = async activate => {
    await Promise.all([
      page.waitForResponse(response => new URL(response.url()).pathname === '/api/rd/session'),
      activate(),
    ]);
    await waitForSessionSettled(page);
  };
  state.actor = 'fixture-model-owner-a';
  await refreshIdentity(focusIdentity);
  await assertRecents(actorARecent);
  await page.keyboard.press('Escape');
  state.actor = 'fixture-model-owner-b';
  await refreshIdentity(visibleIdentity);
  await assertRecents([]);
  await page.keyboard.press('Escape');
  state.actor = 'fixture-model-owner-a';
  await refreshIdentity(focusIdentity);
  await assertRecents(actorARecent);
  await page.keyboard.press('Escape');
  state.failSession = true;
  await refreshIdentity(focusIdentity);
  await assertRecents([]);
  await page.keyboard.press('Escape');
  state.failSession = false;
  await refreshIdentity(visibleIdentity);
  await assertRecents(actorARecent);
  assert.equal(await page.evaluate(() => performance.timeOrigin), sameDocument, 'identity refresh and recovery happen without reloading the page');
  await snap('06-同页切换账号后历史重新确认');
  await page.keyboard.press('Escape');
  checks.push('同页保存期间actor变化不串写历史；focus/visible重读身份，失败清历史并可恢复，全程不reload');

  const delayedFailures = [];
  const checkDelayed = (name, actual, expected) => {
    try { assert.deepEqual(actual, expected); return true; }
    catch (error) { delayedFailures.push({ name, error: error.message }); return false; }
  };
  const delayedSavesStart = saves.length;
  await choose(models[4]);
  const firstCheck = holdNextSession();
  await Promise.all([analyzeBeforeIdentitySettles(), firstCheck.waiting]);
  assert.equal(await combo(page).isDisabled(), false, 'a pending personal-history check does not block choosing the next model');
  await choose(models[5]);
  await analyzeBeforeIdentitySettles();
  assert.deepEqual(saves.slice(delayedSavesStart).map(save => save.data.model_selection), [models[4], models[5]].map(({ provider, name, id }) => ({ provider, name, id })), 'the project confirms saving M1 then M2 before their identity checks settle');
  // Let an independently completed newer verification return before releasing the old one.
  // A serialized implementation may start that newer check after release instead.
  await page.waitForTimeout(250);
  firstCheck.release();
  await waitForSessionSettled(page);
  assert((await selectedText(page)).includes(models[5].name), 'late verification does not replace the latest selected model');
  await openPicker();
  const orderedAfterDelayedCheck = await recentLabels(page);
  const expectedSaveOrder = [models[5], models[4], models[1], models[2], models[3]].map(label);
  if (checkDelayed('save verifications preserve successful save order', orderedAfterDelayedCheck, expectedSaveOrder)) {
    checks.push('两次连续成功保存可继续选模型；旧身份校验迟到不把较早模型移到最近使用首位');
  }
  await snap('07-延迟校验仍按保存顺序排列');
  await page.keyboard.press('Escape');

  await openPicker();
  const actorALabelsBeforeLateReply = await recentLabels(page);
  await page.keyboard.press('Escape');
  const historyBeforeLateReply = await storage(page);
  await choose(models[2]);
  const oldActorCheck = holdNextSession();
  state.actorAfterSave = 'fixture-model-owner-b';
  await Promise.all([analyzeBeforeIdentitySettles(), oldActorCheck.waiting]);
  assert.deepEqual(saves.at(-1).data.model_selection, { provider: models[2].provider, name: models[2].name, id: models[2].id });
  const refreshDuringPendingCheck = async () => {
    const completedBefore = await page.evaluate(() => window.__modelFixtureSession.completed);
    await Promise.all([
      page.waitForResponse(response => new URL(response.url()).pathname === '/api/rd/session'),
      focusIdentity(),
    ]);
    await page.waitForFunction(before => window.__modelFixtureSession.completed > before, completedBefore);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  };
  await refreshDuringPendingCheck();
  await assertRecents([]);
  await page.keyboard.press('Escape');
  state.actor = 'fixture-model-owner-a';
  await refreshDuringPendingCheck();
  await openPicker();
  assert.deepEqual(await recentLabels(page), actorALabelsBeforeLateReply, 'returning to A reads the current A history before the stale response');
  await page.keyboard.press('Escape');
  oldActorCheck.release();
  await waitForSessionSettled(page);
  await openPicker();
  const actorAfterLateReply = await recentLabels(page);
  const actorStayedCurrent = checkDelayed('old B verification cannot replace newer A history', actorAfterLateReply, actorALabelsBeforeLateReply);
  const historyStayedCurrent = checkDelayed('old actor verification cannot write any history after identity changes', await storage(page), historyBeforeLateReply);
  if (actorStayedCurrent && historyStayedCurrent) checks.push('A→B→A重新确认身份后，迟到的旧B校验不能覆盖新A历史或写入缓存');
  await snap('08-身份往返后丢弃迟到旧校验');
  await page.keyboard.press('Escape');
  assert.deepEqual(delayedFailures, [], 'delayed session responses preserve recent order and current identity');

  assert.deepEqual(errors, []);
  assert.deepEqual(unexpected, []);
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ checks, pageErrors: errors, unexpectedRequests: unexpected, fixtureSaves: saves.length, fixtureAnalyses: analyses.length, delayedSessionResponses: sessionReplies.filter(reply => reply.delayed).length, controlRows, realApiRequests: 0 }, null, 2));
  console.log(JSON.stringify({ passed: checks.length, checks, fixtureSaves: saves.length, fixtureAnalyses: analyses.length, realApiRequests: 0, screenshots: output }));
} catch (error) {
  await snap('failure').catch(() => {});
  console.error(JSON.stringify({ completedChecks: checks, pageErrors: errors, unexpectedRequests: unexpected, fixtureSaves: saves.length, sessionReplies, observed }));
  throw error;
} finally { await browser.close(); }
