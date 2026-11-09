/** Late analysis results: keep genuine failures, clear only a new current result. No real API writes. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const stamp = '2026-11-05T02:00:00Z';
const context = { product_type: '', product_domain: '', development_process: '', cover_phase: '', product_series: 'YLZJ', organization_scope: '' };
const makeAnalysis = (id, revision = 2, count = 48) => ({
  id, status: 'proposed', input_revision: revision, created_at: stamp, source_hashes: { tech: 'tech', spec: 'spec' },
  model_selection: { provider: 'fixture', name: 'test-default-model', id: '1' },
  context: Object.fromEntries(Object.keys(context).map(key => [key, { value: '', status: 'unresolved', reason: '资料未明确。', evidence: [] }])),
  requirements: Array.from({ length: count }, (_, index) => ({ title: `${id} 指标 ${index + 1}`, content: `工作温度 ${index + 1}℃。`, source_ids: ['tech'], evidence: [{ source_id: 'tech', quote: `工作温度 ${index + 1}℃。` }] })),
  warnings: [],
});
const project = { id: 'late-analysis-fixture', title: '资料分析延迟恢复验证', version: 1, owner_id: 'test', members: [], events: [], brief: '', cases: [{
  id: 'case-fixture', scenario_id: 'taskbook', title: '液冷任务书流程', stage: 'input', input_revision: 2, status: 'draft',
  context, model_selection: { provider: '', name: '', id: '' }, source_selection: { tech: 'tech', spec: 'spec' },
  sources: ['tech', 'spec'].map(role => ({ id: role, role, name: role === 'tech' ? 'YLZJ-BG-469液冷组件规格书.doc' : '液冷产品规范.doc', size: 2048, version: 1, sha256: role, created_at: stamp })),
  requirements: [], product_route: null, composition_route: null, decisions: [], workpackages: [], source_analysis: makeAnalysis('previous-result', 2, 61),
}] };
const errors = [], unexpected = [], checks = [];
let analysisRequests = 0;

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => errors.push(error.message));
  await page.clock.install();
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
    if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: 'liquid_cooling_pipeline', label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }] }] } });
    if (path === '/api/models') return route.fulfill({ json: { success: true, models: [{ provider: 'fixture', name: 'test-default-model', id: '1' }] } });
    if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'fixture-source-owner', local_mode: true } });
    if (path === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书' }], actions: [], workpackage_definitions: [] } });
    if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
    if (path === '/api/rd/projects/late-analysis-fixture') return route.fulfill({ json: project });
    if (path.endsWith('/evidence-locations')) return route.fulfill({ json: { items: [] } });
    if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: 'input', project_version: project.version, input_revision: 2 } } });
    if (path.endsWith('/analysis')) {
      assert.equal(request.method(), 'POST');
      analysisRequests += 1;
      // Keep the real fetch pending. The application aborts it at its unchanged 300-second timeout.
      return;
    }
    if (request.method() !== 'GET') unexpected.push({ method: request.method(), path });
    return route.fulfill({ json: {} });
  });
  const openSources = async () => {
    await page.goto(`${process.env.TEST_BASE_URL || 'http://127.0.0.1:18370'}/?project=late-analysis-fixture&case=case-fixture`);
    await page.getByRole('navigation', { name: '办理步骤', exact: true }).getByRole('button', { name: '资料识别', exact: true }).click().catch(async error => {
      console.error('Page errors:', errors, 'Body:', await page.locator('body').innerText());
      throw error;
    });
  };
  await openSources();
  const panel = page.getByRole('region', { name: '资料分析', exact: true });
  const warning = panel.getByText(/本次未取得新的分析结果/);
  const timeout = async () => {
    const count = analysisRequests;
    const posted = page.waitForRequest(request => new URL(request.url()).pathname.endsWith('/analysis') && request.method() === 'POST');
    await panel.getByRole('button', { name: project.cases[0].source_analysis ? '重新分析资料' : '分析上传资料', exact: true }).click();
    await posted;
    await page.clock.fastForward(300001);
    await page.getByRole('alert').filter({ hasText: '请求超时，操作结果尚未确认' }).waitFor();
    await warning.waitFor();
    assert.equal(analysisRequests, count + 1, 'a timeout does not automatically resend the analysis mutation');
  };
  const readLatest = async () => {
    await page.getByRole('button', { name: '读取最新版本', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '请求超时' }).waitFor({ state: 'hidden' });
  };

  await timeout();
  project.version += 1;
  await readLatest();
  assert.equal(await warning.isVisible(), true, 'refreshing the same old analysis cannot turn a failed run into success');
  await panel.getByText('previous-result 指标 1', { exact: true }).waitFor();
  checks.push('同一旧分析 ID：刷新保留黄色提示与旧数据');

  await timeout();
  project.version += 1;
  project.cases[0].source_analysis = makeAnalysis('late-stale-result', 1);
  await readLatest();
  assert.equal(await warning.isVisible(), true, 'a different analysis for an older input revision cannot resolve this failure');
  await panel.getByText(/这份识别结果已过期/).waitFor();
  checks.push('不同 ID 但输入已过期：保留失败与过期提示');

  await timeout();
  project.version += 1;
  project.cases[0].source_analysis = makeAnalysis('late-current-result');
  await readLatest();
  await panel.getByText('late-current-result 指标 1', { exact: true }).waitFor();
  await warning.waitFor({ state: 'hidden' });
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).isEnabled(), true);
  assert.equal(await panel.getByText(/这份识别结果已过期/).count(), 0);
  if (output) {
    await panel.getByRole('heading', { name: '资料分析', exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(output, 'late-current-analysis-recovered.png'), fullPage: true });
  }
  checks.push('300 秒实际请求超时后读取到新 ID / 当前输入版本：48 条结果可读，旧黄色提示清除');

  delete project.cases[0].source_analysis;
  project.version += 1;
  await openSources();
  await timeout();
  project.version += 1;
  project.cases[0].source_analysis = makeAnalysis('first-late-result');
  await readLatest();
  await panel.getByText('first-late-result 指标 1', { exact: true }).waitFor();
  await warning.waitFor({ state: 'hidden' });
  checks.push('首次分析无旧结果：晚到的新有效结果同样解除失败提示');
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpected, [], 'no unexpected API writes');
  const receipt = { passed: true, checks, fixtureAnalyses: analysisRequests, pageErrors: errors, realApiRequests: 0 };
  if (output) await writeFile(join(output, 'late-result-receipt.json'), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt));
} finally { await browser.close(); }
