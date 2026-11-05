/** Operating dashboard acceptance with isolated records. No production API writes. */
import assert from 'node:assert/strict';
import { mkdir, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'file:///C:/Users/周园鑫/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'docs/rd-platform/verification/screenshots/2026-11-03-operations-dashboard';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1050 }, timezoneId: 'Asia/Shanghai' });
page.setDefaultTimeout(8000);
const errors = [], apiRequests = [], checks = [], callbacks = [];
page.on('pageerror', error => errors.push(error.message));
await page.clock.setFixedTime(new Date('2026-11-03T04:00:00Z'));
await page.route('**/api/**', route => {
  apiRequests.push({ method: route.request().method(), path: new URL(route.request().url()).pathname });
  return route.fulfill({ status: 500, json: { error: 'Isolated operating dashboard must not call business APIs' } });
});
await page.route('**/__operations-fixture', route => route.fulfill({ contentType: 'text/html', body: '<html lang="zh-CN"><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>运营看板隔离验收</title></head><body><div id="fixture"></div></body></html>' }));

function workpackage(id, title, status, extra = {}) {
  return { id, title, definition_id: 'taskbook', definition_version: '2', stage: 'design', status, plan_revision: 1, nodes: [], artifacts: [], obligations: [], blocked_reasons: [], planned_start: null, planned_end: null, started_at: null, ended_at: null, completed_at: null, ...extra };
}
function researchCase(id, title, stage, workpackages, extra = {}) {
  return { id, title, scenario_id: 'taskbook', stage, status: 'active', input_revision: 1, context: { product_type: 'liquid_cooling_pipeline', product_series: 'YLZJ' }, sources: [], requirements: [], decisions: [], workpackages, product_route: null, composition_route: null, ...extra };
}
const projects = [
  { id: 'project-alpha', title: '液冷管路研制项目', owner_id: 'li-ming', customer_name: '研究所甲', product_name: 'YLZJ管路', version: 4, members: [], created_at: '2026-10-01T00:00:00Z', updated_at: '2026-11-03T00:00:00Z', events: [], cases: [
    researchCase('case-design', '液冷设计流程', 'design', [
      workpackage('wp-done', '需求归集已完成', 'completed', { started_at: '2026-10-31T00:00:00Z', ended_at: '2026-10-31T00:05:00Z', completed_at: '2026-10-31T00:05:00Z', planned_end: '2026-11-01', artifacts: [{ id: 'a1', name: '任务书.docx', kind: 'taskbook' }], nodes: [{ id: 'done-node', action_id: 'generate', action_version: '1', depends_on: [], required: true, status: 'completed' }] }),
      workpackage('wp-blocked', '密封验证准备', 'blocked', { planned_end: '2026-11-01', started_at: '2026-11-02T00:00:00Z', ended_at: '2026-11-02T00:03:00Z', blocked_reasons: [{ code: 'missing_evidence', message: '需要核对密封试验依据' }] }),
      workpackage('wp-running', '总成技术装配', 'running', { planned_end: '2026-11-06', started_at: '2026-11-03T03:00:00Z' }),
    ], { requirements: [{ id: 'req-1', title: '压力要求', content: '工作压力0.3MPa', source_ids: [] }, { id: 'req-2', title: '盐雾要求', content: '满足输入规格', source_ids: [] }], sources: [{ id: 's1', name: '液冷组件需求.docx', role: 'tech', version: 1, sha256: 'a'.repeat(64), size: 1024, created_at: '2026-10-31T00:00:00Z' }] }),
    researchCase('case-planning', '任务书策划流程', 'planning', [workpackage('wp-draft', '技术编制规划', 'draft')]),
  ] },
  { id: 'project-beta', title: '连接器验证项目', owner_id: 'wang-xue', customer_name: '研究所乙', product_name: 'CY连接器', version: 2, members: [], created_at: '2026-10-10T00:00:00Z', updated_at: '2026-11-02T00:00:00Z', events: [], cases: [
    researchCase('case-verification', '连接器验证流程', 'verification', [
      workpackage('wp-failed', '第三方检查', 'failed', { planned_end: '2026-11-10', started_at: '2026-11-02T00:00:00Z', ended_at: '2026-11-02T00:02:00Z', blocked_reasons: ['来源服务暂不可用'] }),
      workpackage('wp-cancelled', '原始取消记录', 'cancelled', { planned_end: '2026-10-01', ended_at: '2026-10-02T00:00:00Z' }),
    ]),
  ] },
];
const snap = async name => { await page.evaluate(() => document.fonts.ready); await page.screenshot({ path: join(output, name + '.png'), fullPage: true, animations: 'disabled' }); };
async function setProps(props) {
  await page.evaluate(props => window.operationsFixture.setProps(props), props);
  await page.waitForFunction(patch => Object.entries(patch).every(([key, value]) => JSON.stringify(window.operationsFixture.currentProps?.[key]) === JSON.stringify(value)), props);
}
async function projectCount() {
  const card = page.locator('.ops-kpi').filter({ has: page.getByText('可见项目', { exact: true }) });
  return await card.locator('.ant-statistic-content-value').count() ? await card.locator('.ant-statistic-content-value').innerText() : null;
}
async function select(label, name) {
  const combo = page.getByRole('combobox', { name: label, exact: true });
  await combo.focus(); await page.keyboard.press('ArrowDown');
  await page.getByRole('option', { name, exact: true }).click();
}
async function check(name, run) { await run(); checks.push(name); }
try {
  await page.goto(base + '/__operations-fixture');
  await page.evaluate(async () => {
    const refresh = await import('/@react-refresh'); refresh.default.injectIntoGlobalHook(window); window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => type => type; window.__vite_plugin_react_preamble_installed__ = true;
    const React = (await import('/node_modules/.vite/deps/react.js')).default;
    const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
    const { PlatformTheme } = await import('/src/components/ui/PlatformTheme.tsx');
    const { OperationsDashboard } = await import('/src/features/rd/OperationsDashboard.tsx');
    for (const css of ['/src/styles.css', '/src/features/rd/rd.css', '/src/features/rd/rdApplicationShell.css', '/src/features/rd/platformManagement.css']) await import(css);
    window.operationsFixture = { calls: [], refreshes: 0 };
    function Fixture() {
      const [props, setProps] = React.useState({ projects: [], loading: false, error: '' });
      React.useLayoutEffect(() => { window.operationsFixture.currentProps = props; }, [props]);
      window.operationsFixture.setProps = patch => setProps(current => ({ ...current, ...patch }));
      return React.createElement(PlatformTheme, null, React.createElement('div', { className: 'rd-shell rd-application-shell', style: { display: 'block' } }, React.createElement(OperationsDashboard, { ...props, onRefresh: () => { window.operationsFixture.refreshes++; }, onOpenCase: (...args) => window.operationsFixture.calls.push(args) })));
    }
    createRoot(document.getElementById('fixture')).render(React.createElement(Fixture));
  });
  await page.getByRole('heading', { name: '运营管理', exact: true }).waitFor();

  // The following semantic selectors follow the dashboard's data-display regions.
  await check('empty dashboard retains the complete operating structure and honest unknown values', async () => {
    assert.equal(await page.locator('.ops-kpi').count(), 4);
    assert.equal(await page.locator('.ops-chart-grid>.ops-panel').count(), 4);
    assert.equal(await page.locator('.ops-metric-group').count(), 4);
    assert.equal(await projectCount(), '0');
    const rate = page.locator('.ops-kpi').filter({ has: page.getByText('执行完成率', { exact: true }) });
    assert.equal(await rate.locator('.ant-statistic-content-value').innerText(), '—', 'an empty denominator is unknown, not a fabricated zero percent');
    await page.getByRole('heading', { name: '项目交付与协调', exact: true }).waitFor();
    assert(await page.locator('body').innerText().then(text => text.includes('尚未接入') && !text.includes('2026年10月配套批次')));
    assert.equal(await page.locator('.ops-chart-grid path[data-series]').count(), 0, 'empty datasets must not draw fabricated trend lines');
    await snap('01-empty-dashboard');
  });

  await check('real records replace empty values and project/workpackage backlinks preserve scope', async () => {
    await setProps({ projects });
    await page.getByText('液冷管路研制项目', { exact: true }).first().waitFor();
    assert.equal(await projectCount(), '2');
    await snap('02-populated-dashboard');
    await page.getByRole('button', { name: '查看液冷管路研制项目项目', exact: true }).click();
    assert.deepEqual(await page.evaluate(() => window.operationsFixture.calls.at(-1)), ['project-alpha', 'case-design', 'process']);
    await page.getByRole('button', { name: '查看密封验证准备执行', exact: true }).click();
    assert.deepEqual(await page.evaluate(() => window.operationsFixture.calls.at(-1)), ['project-alpha', 'case-design', 'process']);
    await snap('02b-projects-and-ledger');
  });

  await check('keyword, status, stage and owner filtering share a single record scope', async () => {
    await page.locator('#rd-management-search').fill('密封');
    await page.getByText('密封验证准备', { exact: true }).first().waitFor();
    assert.equal(await page.getByText('第三方检查', { exact: true }).count(), 0);
    await page.getByRole('button', { name: '清空搜索', exact: true }).click();
    assert(await page.locator('#rd-management-search').evaluate(el => el === document.activeElement));
    await select('运行状态', '已阻塞');
    assert.equal(await page.getByText('第三方检查', { exact: true }).count(), 0);
    await select('运行状态', '全部状态');
    await select('研发阶段', '方案设计');
    assert.equal(await page.getByText('第三方检查', { exact: true }).count(), 0);
    assert.equal(await page.getByText('技术编制规划', { exact: true }).count(), 0);
    await select('项目负责人', 'wang-xue');
    await page.getByText('没有符合条件的记录', { exact: true }).first().waitFor();
    await page.getByRole('button', { name: '重置筛选', exact: true }).first().click();
    await page.getByText('第三方检查', { exact: true }).first().waitFor();
    await snap('03-filter-reset');
  });

  await check('loading and failure retain uncertainty and stale records, refresh can recover', async () => {
    await setProps({ projects: [], loading: true });
    assert.equal(await page.locator('.ops-kpi').count(), 4);
    await page.locator('.ops-kpi .ant-skeleton').first().waitFor();
    assert.notEqual(await projectCount(), '0');
    await setProps({ loading: false, error: '模拟读取失败' });
    await page.getByRole('alert').waitFor();
    assert.equal(await projectCount(), '—');
    assert.equal(await page.locator('.ops-chart-grid path[data-series]').count(), 0);
    await setProps({ projects, error: '模拟读取失败' });
    await page.getByText('液冷管路研制项目', { exact: true }).first().waitFor();
    assert(await page.locator('body').innerText().then(text => /上次|旧记录|缓存/.test(text)));
    await snap('04-stale-error');
    const before = await page.evaluate(() => window.operationsFixture.refreshes);
    await page.getByRole('button', { name: '刷新项目', exact: true }).click();
    assert.equal(await page.evaluate(() => window.operationsFixture.refreshes), before + 1);
    await setProps({ projects: [projects[1]], loading: false, error: '' });
    assert.equal(await projectCount(), '1');
    assert.equal(await page.getByText('液冷管路研制项目', { exact: true }).count(), 0, 'refresh must replace removed records');
    await setProps({ projects, error: '', loading: false });
  });

  await check('390px layout remains readable and its tables own horizontal scrolling', async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => document.fonts.ready);
    assert(await page.locator('.rd-application-shell').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
    await snap('05-populated-390');
    await page.locator('.ops-ledgers').scrollIntoViewIfNeeded();
    assert(await page.locator('.ops-ledgers').isVisible());
    const tableScroll = page.locator('.ops-ledgers .ant-table-content').first();
    assert(await tableScroll.evaluate(el => el.scrollWidth > el.clientWidth));
    assert(await tableScroll.evaluate(el => { el.scrollLeft = el.scrollWidth - el.clientWidth; return el.scrollLeft > 0; }), 'mobile table can actually scroll to its later columns');
    await snap('06-ledger-390');
  });

  assert.deepEqual(errors, []); assert.deepEqual(apiRequests, []);
  callbacks.push(...await page.evaluate(() => window.operationsFixture.calls));
  const receipt = { passed: true, mode: 'isolated real React dashboard; no production record mutation', checks, errors, apiRequests, callbacks };
  await writeFile(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  for (const name of ['failure.png', 'failure.json']) await unlink(join(output, name)).catch(error => { if (error.code !== 'ENOENT') throw error; });
  console.log(JSON.stringify(receipt));
} catch (error) {
  await snap('failure');
  await writeFile(join(output, 'failure.json'), JSON.stringify({ error: error.message, checks, errors, apiRequests, body: await page.locator('body').innerText() }, null, 2));
  throw error;
} finally { await browser.close(); }
