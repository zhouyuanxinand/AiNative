/** Component browser fixtures: real forms and evidence rendering, isolated API responses. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'file:///C:/Users/周园鑫/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const errors = [], writes = [];
const source = { id: 'source-current', role: 'tech', name: '实际规范.docx', version: 2, sha256: 'fixed-hash' };
const project = { id: 'project', title: '模板验证项目', cases: [{ id: 'case', title: '目标案例', input_revision: 3, sources: [source], source_selection: { tech: source.id } }] };
const candidate = { candidate_id: 'candidate', status: 'blocked', target: { product_label: '目标高频模板' }, validation: { passed: false, blockers: ['缺少目标专业方法依据'] }, asset_manifest: { digest: 'manifest-fixed' }, asset_digest: 'asset-fixed' };
const session = { stop_reason: 'no_new_evidence', rounds: [1, 2].map(round => ({ round, obligations: [{ obligation_key: 'internal-field', query: { title: '耐压指标' }, accepted: [{ source_id: source.id, quote: '真实原文' }], rejected: [{ candidate: { value: '未核实值' }, reason: '缺少引用' }] }], remaining: ['internal-field'] })), remaining: ['internal-field'], usage: { queries: 0, candidates: 4, model_calls: 0, elapsed_seconds: 0 } };
async function setup(page, permissions = { can_prepare_templates: true, can_review_templates: true, can_publish_templates: true }) {
  page.setDefaultTimeout(8000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/__derivation-ux', route => route.fulfill({ contentType: 'text/html', body: '<html lang="zh-CN"><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body style="margin:0;padding:20px;width:auto;overflow:auto"><div id="fixture" class="rd-shell" style="display:block;min-height:0"></div></body></html>' }));
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    const json = data => route.fulfill({ json: data });
    if (route.request().method() === 'POST') { writes.push({ path, body: route.request().postData(), key: route.request().headers()['idempotency-key'] }); return route.fulfill({ status: 503, json: { error: '临时失败，请重试' } }); }
    if (path.endsWith('/governance/session')) return json(permissions);
    if (path.endsWith('/template-derivations')) return json({ items: [candidate], total: 1 });
    if (path.endsWith('/template-rules')) return json({ items: [{ id: 'rule', version: 1, status: 'published', digest: 'rule-fixed' }], total: 1 });
    if (path.endsWith('/candidate')) return json(candidate);
    return json({ items: [], total: 0 });
  });
  await page.goto(base + '/__derivation-ux');
  await page.evaluate(async ({ project, session }) => {
    const refresh = await import('/@react-refresh');
    refresh.default.injectIntoGlobalHook(window); window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => type => type; window.__vite_plugin_react_preamble_installed__ = true;
    const React = (await import('/node_modules/.vite/deps/react.js')).default;
    const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
    const { TemplateDerivationPanel } = await import('/src/features/rd/TemplateDerivationPanel.tsx');
    const { CompletionEvidence } = await import('/src/features/rd/CompletionEvidence.tsx');
    await import('/src/styles.css'); await import('/src/features/rd/rd.css');
    createRoot(document.getElementById('fixture')).render(React.createElement(React.Fragment, null, React.createElement(TemplateDerivationPanel, { projects: [project] }), React.createElement(CompletionEvidence, { session }), React.createElement(CompletionEvidence, { session: {}, title: '尚未记录的补缺' })));
  }, { project, session });
  await page.getByRole('button', { name: '目标高频模板 · 已阻塞', exact: true }).waitFor();
}
async function snap(page, name) { if (output) await page.screenshot({ path: join(output, name), fullPage: true }); }
async function focused(page, locator) { const id = await locator.getAttribute('id'); await page.waitForFunction(value => document.activeElement?.id === value, id); }
async function leaveState(page) { return page.evaluate(async () => (await import('/src/hooks/useApplicationLeaveGuard.ts')).applicationLeaveState()); }
async function settled(page) { await page.waitForFunction(async () => !(await import('/src/hooks/useApplicationLeaveGuard.ts')).applicationLeaveState().busyMessage); }
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 950 } });
  await setup(page);
  const prepare = page.getByText('准备新候选', { exact: true });
  await prepare.waitFor();
  assert.equal(await prepare.locator('xpath=ancestor::details[1]').getAttribute('open'), null, 'preparation starts collapsed');
  await page.getByRole('button', { name: '目标高频模板 · 已阻塞', exact: true }).click();
  await page.getByText('缺少目标专业方法依据', { exact: true }).waitFor();
  assert.equal(await page.getByText('适用目标、差异与验证结果', { exact: true }).locator('..').getAttribute('open'), null);
  await page.getByRole('button', { name: '填写办理依据', exact: true }).first().click();
  await focused(page, page.getByLabel('变更 / 核验 / 审核依据', { exact: true }));
  await page.getByLabel('变更 / 核验 / 审核依据', { exact: true }).fill('核对真实来源');
  await prepare.click();
  await page.getByLabel('目标产品名称', { exact: true }).fill('保留的名称');
  await prepare.click(); await prepare.click();
  assert.equal(await page.getByLabel('目标产品名称', { exact: true }).inputValue(), '保留的名称');
  await page.getByRole('button', { name: /^固定差异规则/ }).click();
  await page.getByRole('option', { name: 'rule · V1 · 已发布', exact: true }).click();
  await page.getByRole('button', { name: '派生完整目标候选', exact: true }).click();
  await focused(page, page.getByRole('button', { name: /^来源与实际回归案例/ }));
  assert.equal(await page.getByRole('button', { name: /^来源与实际回归案例/ }).getAttribute('aria-describedby'), 'rd-derivation-case-error');
  await page.getByRole('button', { name: /^来源与实际回归案例/ }).click();
  await page.getByRole('option', { name: '模板验证项目 / 目标案例', exact: true }).click();
  await page.getByRole('checkbox', { name: /实际规范/ }).check();
  for (const label of ['基线产品标识', '基线领域标识', '目标产品标识', '目标领域标识', '目标领域名称']) await page.getByLabel(label, { exact: true }).fill('fixed');
  await page.getByLabel('目标专业依据（指标 / 方法 / 判据）', { exact: true }).fill('{');
  await page.getByRole('button', { name: '派生完整目标候选', exact: true }).click();
  const evidence = page.getByLabel('目标专业依据（指标 / 方法 / 判据）', { exact: true });
  assert.equal(await evidence.getAttribute('aria-invalid'), 'true');
  await focused(page, evidence);
  await evidence.fill('{"indicators":[],"methods":[],"criteria":[]}');
  await page.getByRole('button', { name: '派生完整目标候选', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '临时失败' }).waitFor();
  await page.getByRole('button', { name: '派生完整目标候选', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '临时失败' }).waitFor();
  assert.equal(writes.length, 2); assert.equal(writes[0].key, writes[1].key);
  const completion = page.getByRole('region', { name: '有限补缺 · 证据与停止原因', exact: true });
  await completion.getByText('本次待补项：1 项', { exact: true }).waitFor();
  assert.equal(await completion.locator('dl[aria-label="补缺执行用量"] > div').filter({ hasText: '查询' }).locator('dd').textContent(), '0');
  assert.equal(await completion.locator('dl[aria-label="补缺执行用量"] > div').filter({ hasText: '耗时' }).locator('dd').textContent(), '0 秒');
  assert.equal(await completion.locator('.rd-completion-round[open]').count(), 0);
  await completion.getByText('第 2 轮 · 剩余 1 项待补', { exact: true }).click();
  await completion.getByRole('heading', { name: '耐压指标', exact: true }).waitFor();
  await completion.getByText('已拒绝候选 · 1 项', { exact: true }).last().click();
  await completion.getByText('拒绝原因：缺少引用', { exact: true }).last().waitFor();
  await page.getByRole('region', { name: '尚未记录的补缺', exact: true }).getByText('停止原因未记录', { exact: true }).waitFor();
  assert.equal(await page.getByRole('region', { name: '尚未记录的补缺', exact: true }).locator('dl[aria-label="补缺记录摘要"] > div').filter({ hasText: '已接受记录' }).locator('dd').textContent(), '未记录');
  await snap(page, 'derivation-desktop.png');
  await page.setViewportSize({ width: 390, height: 760 });
  await snap(page, 'derivation-narrow.png');
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2), JSON.stringify(await page.evaluate(() => [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth + 2).slice(0, 12).map(el => ({ tag: el.tagName, class: el.className, right: el.getBoundingClientRect().right })))));
  const reviewer = await browser.newPage({ viewport: { width: 1440, height: 950 } });
  await setup(reviewer, { can_prepare_templates: false, can_review_templates: true, can_publish_templates: false });
  assert.equal(await reviewer.getByText('准备新候选', { exact: true }).count(), 0);
  await reviewer.getByRole('button', { name: '目标高频模板 · 已阻塞', exact: true }).click();
  assert.equal(await reviewer.getByRole('button', { name: '独立审核候选', exact: true }).isDisabled(), true);
  await reviewer.getByText('填写办理依据后可审核、退回或回退。', { exact: true }).waitFor();
  await snap(reviewer, 'derivation-reviewer.png');
  const preparer = await browser.newPage({ viewport: { width: 1440, height: 700 } });
  await setup(preparer, { can_prepare_templates: true, can_review_templates: false, can_publish_templates: false });
  await preparer.getByRole('button', { name: '目标高频模板 · 已阻塞', exact: true }).click();
  assert.equal(await preparer.getByRole('button', { name: '独立审核候选', exact: true }).count(), 0);
  assert.equal(await preparer.getByLabel('真实版式检查页', { exact: true }).count(), 0);
  await preparer.getByRole('button', { name: '选择案例与来源', exact: true }).click();
  await focused(preparer, preparer.getByRole('button', { name: /^来源与实际回归案例/ }));
  await preparer.getByLabel('目标产品标识', { exact: true }).fill('target');
  await preparer.getByLabel('目标领域标识', { exact: true }).fill('domain');
  await preparer.getByText('维护差异规则', { exact: true }).click();
  await preparer.getByRole('button', { name: '保存差异规则草稿', exact: true }).click();
  const reason = preparer.getByLabel('变更 / 核验 / 审核依据', { exact: true });
  await focused(preparer, reason);
  await reason.fill('核对目标结构');
  await preparer.getByRole('button', { name: '保存差异规则草稿', exact: true }).click();
  const profile = preparer.getByLabel('目标 Profile（YAML）', { exact: true });
  await focused(preparer, profile);
  await profile.setInputFiles({ name: 'profile.yaml', mimeType: 'application/yaml', buffer: Buffer.from('target: fixed') });
  await preparer.getByLabel('目标 mapping（YAML）', { exact: true }).setInputFiles({ name: 'mapping.yaml', mimeType: 'application/yaml', buffer: Buffer.from('mapping: fixed') });
  const operations = preparer.getByLabel('结构差异操作（JSON 数组）', { exact: true });
  await operations.fill('{');
  await preparer.getByText('维护差异规则', { exact: true }).click();
  await preparer.getByText('维护差异规则', { exact: true }).click();
  assert.equal(await profile.evaluate(el => el.files[0].name), 'profile.yaml');
  await preparer.getByRole('button', { name: '保存差异规则草稿', exact: true }).click();
  await focused(preparer, operations);
  assert.equal(await operations.getAttribute('aria-invalid'), 'true');
  assert.equal(writes.length, 2, 'missing fields and malformed JSON never submit');
  await snap(preparer, 'derivation-rule-validation.png');
  const guarded = await browser.newPage({ viewport: { width: 1440, height: 950 } });
  await setup(guarded);
  await guarded.route('**/api/rd/template-derivations/candidate/review', route => route.fulfill({ json: { candidate_id: 'candidate', status: 'approved' } }));
  await guarded.getByRole('button', { name: '目标高频模板 · 已阻塞', exact: true }).click();
  await guarded.getByText('准备新候选', { exact: true }).click();
  await guarded.getByLabel('目标产品标识', { exact: true }).fill('尚未保存的目标');
  await guarded.getByLabel('变更 / 核验 / 审核依据', { exact: true }).fill('已有候选的审核依据');
  assert.equal((await leaveState(guarded)).dirty, true);
  await guarded.getByRole('button', { name: '独立审核候选', exact: true }).click();
  await guarded.getByRole('button', { name: '审核通过', exact: true }).click();
  await guarded.getByText(/已收到独立审核回执/).waitFor();
  await settled(guarded);
  assert.equal((await leaveState(guarded)).dirty, true, 'reviewing an existing candidate must not acknowledge a different preparation draft');
  assert.equal(await guarded.getByLabel('目标产品标识', { exact: true }).inputValue(), '尚未保存的目标');
  await guarded.route('**/api/rd/template-derivations/candidate/publish', route => route.fulfill({ json: { candidate_id: 'candidate', status: 'published' } }));
  await guarded.getByRole('button', { name: '发布目标固定版', exact: true }).click();
  await guarded.getByRole('button', { name: '发布目标模板', exact: true }).click();
  await guarded.getByText(/已收到目标发布回执/).waitFor();
  await settled(guarded);
  assert.equal((await leaveState(guarded)).dirty, true, 'publishing an existing candidate must preserve the preparation guard');
  await guarded.getByLabel('目标产品标识', { exact: true }).fill('');
  assert.equal((await leaveState(guarded)).dirty, false, 'acknowledged review reason does not leave a false warning after preparation is restored');

  const loaded = await browser.newPage({ viewport: { width: 1440, height: 950 } });
  await setup(loaded);
  const bound = { ...candidate, project_binding: { project_id: project.id, case_id: project.cases[0].id, input_revision: 3, source_ids: [source.id] } };
  await loaded.route('**/api/rd/template-derivations/candidate', route => route.fulfill({ json: bound }));
  assert.equal((await leaveState(loaded)).dirty, false, 'initial directory loading is clean');
  await loaded.getByRole('button', { name: '目标高频模板 · 已阻塞', exact: true }).click();
  await loaded.getByRole('button', { name: '选择案例与来源', exact: true }).click();
  assert.equal(await loaded.getByRole('checkbox', { name: /实际规范/ }).isChecked(), true);
  assert.equal((await leaveState(loaded)).dirty, false, 'reading a saved project binding is not an edit');
  await loaded.getByRole('checkbox', { name: /实际规范/ }).uncheck();
  assert.equal((await leaveState(loaded)).dirty, true, 'source-only edits are protected');
  await loaded.getByRole('button', { name: '目标高频模板 · 已阻塞', exact: true }).click();
  assert.equal(await loaded.getByRole('checkbox', { name: /实际规范/ }).isChecked(), false, 'rereading a candidate does not overwrite an edited source selection');
  await loaded.getByRole('checkbox', { name: /实际规范/ }).check();
  assert.equal((await leaveState(loaded)).dirty, false);
  for (const [label, changed, initial] of [
    ['变更 / 核验 / 审核依据', '待保存的依据', ''],
    ['目标专业依据（指标 / 方法 / 判据）', '{"indicators":[{"quote":"待保存原文"}]}', '{"indicators":[],"methods":[],"criteria":[]}'],
    ['目标产品名称', '只改名称', ''],
    ['基线领域标识', '只改基线领域', ''],
    ['目标资产版本', '2', '1'],
  ]) {
    const field = loaded.getByLabel(label, { exact: true });
    await field.fill(changed); assert.equal((await leaveState(loaded)).dirty, true, `${label} must be protected`);
    await loaded.getByRole('button', { name: '刷新治理记录', exact: true }).click();
    await loaded.getByRole('button', { name: '刷新治理记录', exact: true }).waitFor({ state: 'visible' });
    assert.equal((await leaveState(loaded)).dirty, true, 'directory refresh cannot acknowledge form edits');
    await field.fill(initial); assert.equal((await leaveState(loaded)).dirty, false, `${label} restores the saved baseline`);
  }
  await loaded.getByLabel('真实版式检查页', { exact: true }).setInputFiles({ name: 'page.png', mimeType: 'image/png', buffer: Buffer.from('page') });
  assert.equal((await leaveState(loaded)).dirty, true, 'selected visual-review files are protected');
  await loaded.getByLabel('真实版式检查页', { exact: true }).setInputFiles([]);
  assert.equal((await leaveState(loaded)).dirty, false);

  await preparer.route('**/api/rd/template-rules', route => route.fulfill({ json: { id: 'rule', applicability: { product_type: 'target', domain: 'domain' } } }));
  await operations.fill('[]');
  await preparer.getByRole('button', { name: '保存差异规则草稿', exact: true }).click();
  await preparer.getByText('差异规则草稿已保存。审核与发布需分别办理。', { exact: true }).waitFor();
  await settled(preparer);
  assert.equal((await leaveState(preparer)).dirty, false, 'successful rule save acknowledges its target, reason, JSON and files');
  await profile.setInputFiles({ name: 'profile.yaml', mimeType: 'application/yaml', buffer: Buffer.from('target: revised') });
  assert.equal((await leaveState(preparer)).dirty, true, 'replacing a saved file is a new unsaved edit');
  await preparer.getByRole('button', { name: '保存差异规则草稿', exact: true }).click();
  await settled(preparer);
  assert.equal((await leaveState(preparer)).dirty, false);
  const preparationEvidence = preparer.getByLabel('目标专业依据（指标 / 方法 / 判据）', { exact: true });
  await preparationEvidence.fill('{"indicators":[{"quote":"独立准备草稿"}]}');
  await preparer.getByRole('button', { name: '保存差异规则草稿', exact: true }).click();
  await preparer.getByText('差异规则草稿已保存。审核与发布需分别办理。', { exact: true }).waitFor();
  await settled(preparer);
  assert.equal((await leaveState(preparer)).dirty, true, 'rule save cannot acknowledge candidate evidence');

  await loaded.getByRole('button', { name: /^固定差异规则/ }).click();
  await loaded.getByRole('option', { name: 'rule · V1 · 已发布', exact: true }).click();
  for (const label of ['基线产品标识', '基线领域标识', '目标产品标识', '目标产品名称', '目标领域标识', '目标领域名称']) await loaded.getByLabel(label, { exact: true }).fill('fixed');
  await loaded.route('**/api/rd/template-derivations', route => route.fulfill({ json: { candidate_id: 'candidate' } }));
  await loaded.getByRole('button', { name: '派生完整目标候选', exact: true }).click();
  await loaded.getByText(/目标派生已返回/).waitFor();
  await settled(loaded);
  assert.equal((await leaveState(loaded)).dirty, false, 'successful derivation acknowledges the exact preparation fields');
  await loaded.getByText('维护差异规则', { exact: true }).click();
  await loaded.getByLabel('结构差异操作（JSON 数组）', { exact: true }).fill('[{"op":"pending-rule"}]');
  await loaded.getByRole('button', { name: '派生完整目标候选', exact: true }).click();
  await loaded.getByText(/目标派生已返回/).waitFor();
  await settled(loaded);
  assert.equal((await leaveState(loaded)).dirty, true, 'derivation cannot acknowledge a rule JSON draft');
  await loaded.route('**/api/rd/template-derivations', route => route.fulfill({ status: 403, json: { error: '治理权限已撤销' } }));
  await loaded.getByRole('button', { name: '派生完整目标候选', exact: true }).click();
  await loaded.getByRole('alert').filter({ hasText: '治理权限已撤销' }).waitFor();
  await settled(loaded);
  assert.equal((await leaveState(loaded)).dirty, false, 'permission denial clears the sensitive form and its saved snapshots together');
  assert.equal(await loaded.getByLabel('目标产品标识', { exact: true }).count(), 0);
  assert.deepEqual(errors, []);
  console.log('PASS: template task hierarchy, draft retention, field focus, retry identity, permission scope, evidence summaries, narrow layout');
} finally { await browser.close(); }
