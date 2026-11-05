/** Product-series confirmation uses isolated API fixtures; no real model/project requests. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const output = process.env.SCREENSHOT_DIR || 'docs/rd-platform/verification/screenshots/2026-11-04-batch-sources-case-cards/series';
await mkdir(output, { recursive: true });
const stamp = '2026-11-04T00:00:00Z';
const nodeIds = ['input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start', 'taskbook'];
const projectTemplate = { id: 'adoption', template_id: 'taskbook-generation', template_version: '1', template_digest: 'series-flow', category: 'project', title: '研制任务书生成流程',
  graph: { nodes: nodeIds.map(id => ({ id, title: id })), edges: [] }, node_states: {} };
const base = (series = '') => ({ id: 'series-project', title: '系列补充验证', version: 12, owner_id: 'series-owner', members: [], events: [], cases: [{
  id: 'series-case', title: '系列补充流程', scenario_id: 'taskbook', stage: 'planning', status: 'active', input_revision: 3,
  context: { product_type: 'low_frequency_rectangular', product_domain: 'military', cover_phase: 'F', organization_scope: 'non_central_research', development_process: '改型II', product_series: series },
  context_provenance: {}, model_selection: { provider: '', name: '', id: '' },
  sources: ['tech', 'spec'].map(role => ({ id: role, role, name: role === 'tech' ? '需求.txt' : '规范.txt', sha256: role, size: 64, version: 1, created_at: stamp })),
  source_selection: { tech: 'tech', spec: 'spec' }, requirements: [{ id: 'req', title: '绝缘要求', content: '绝缘电阻不低于100MΩ。', source_ids: ['tech'] }], clarifications: [],
  product_route: { value: 'modification', rationale: '已记录改型', source_ids: ['tech'] }, composition_route: { value: 'direct', rationale: '沿用文档', source_ids: ['spec'] },
  decisions: [], workpackages: [], business_lifecycle: { policy_version: 'v2', rd_activation_state: 'active', current_activation_id: 'activation', current_requirement_baseline_id: 'baseline', can_confirm_requirements: true, can_record_decision: true, local_review_enabled: true },
  workflow_templates: { project: structuredClone(projectTemplate) }, project_workflow_status: { status: 'pending', template_id: 'taskbook-generation', template_version: '1', template_digest: 'series-flow', terminal_node_id: 'taskbook' },
  source_analysis: { id: 'adopted-analysis', status: 'adopted', input_revision: 2, adopted_input_revision: 3, created_at: stamp, source_hashes: { tech: 'tech', spec: 'spec' },
    model_selection: { provider: '', name: '', id: '' }, context: {}, requirements: [], warnings: [] },
}] });
let project = base(), failSave = true;
const calls = [], unexpected = [], errors = [], checks = [];

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
    if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [] } });
    if (path === '/api/models') return route.fulfill({ json: { success: true, models: [] } });
    if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'series-owner', local_mode: true } });
    if (path === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书' }], actions: [], workpackage_definitions: [] } });
    if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
    if (path === '/api/rd/projects/series-project') return route.fulfill({ json: project });
    if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: project.cases[0].stage, project_version: project.version, input_revision: project.cases[0].input_revision } } });
    if (path.endsWith('/commands')) {
      const body = request.postDataJSON();
      calls.push({ key: request.headers()['idempotency-key'], body: structuredClone(body) });
      assert.equal(body.command, 'save_context');
      assert.equal(body.expected_version, project.version);
      assert.deepEqual(Object.keys(body.data).sort(), ['case_id', 'context']);
      assert.equal(body.data.case_id, 'series-case');
      assert.deepEqual(body.data.context, { product_series: 'CY-200' }, 'series confirmation submits no other context fields or model changes');
      await new Promise(resolve => setTimeout(resolve, 120));
      if (failSave) { failSave = false; return route.fulfill({ status: 503, json: { error: '系列确认暂不可用，填写内容已保留。' } }); }
      project.version += 1;
      const current = project.cases[0];
      current.context.product_series = body.data.context.product_series;
      current.context_provenance.product_series = { kind: 'user', actor: 'series-owner', created_at: stamp, source_ids: [] };
      current.input_revision += 1; current.stage = 'input'; current.product_route = null; current.composition_route = null;
      current.source_analysis.status = 'stale';
      current.business_lifecycle.rd_activation_state = 'needs_review';
      current.business_lifecycle.current_activation_id = null; current.business_lifecycle.current_requirement_baseline_id = null;
      return route.fulfill({ json: project });
    }
    if (request.method() !== 'GET') unexpected.push({ method: request.method(), path });
    return route.fulfill({ json: {} });
  });
  const openCase = () => page.goto(`${process.env.TEST_BASE_URL || 'http://127.0.0.1:18370'}/?project=series-project&case=series-case`);
  const steps = page.getByRole('navigation', { name: '办理步骤', exact: true });
  const series = page.getByRole('region', { name: '确认产品系列', exact: true });
  const field = series.getByRole('textbox', { name: '产品系列', exact: true });
  await openCase();
  await steps.getByRole('button', { name: '编制准备', exact: true }).click();
  await page.getByRole('button', { name: /前往确认产品系列/ }).click();
  await series.waitFor();
  assert.equal(await field.inputValue(), '');
  assert.equal(project.cases[0].source_analysis.status, 'adopted');
  assert.equal(calls.length, 0, 'opening missing-series confirmation does not mutate the case');
  await series.getByRole('button', { name: '确认系列', exact: true }).click();
  await series.getByRole('alert').filter({ hasText: '请填写产品系列。' }).waitFor();
  assert.equal(calls.length, 0, 'empty series cannot submit a command');
  await page.screenshot({ path: join(output, '01-missing-validation-desktop.png'), fullPage: true });
  checks.push('preparation links to missing series after adopted recognition; empty values do not submit');

  await field.fill('  CY-200  ');
  await page.getByRole('navigation', { name: '研发平台导航', exact: true }).getByRole('button', { name: '我的工作', exact: true }).click();
  const leave = page.getByRole('dialog', { name: '离开前保存填写', exact: true });
  await leave.waitFor();
  assert.equal(new URL(page.url()).searchParams.get('case'), 'series-case');
  assert.equal(calls.length, 0);
  await leave.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(await field.inputValue(), '  CY-200  ');
  await page.setViewportSize({ width: 390, height: 844 });
  await field.scrollIntoViewIfNeeded();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'series form fits a 390px viewport');
  await page.screenshot({ path: join(output, '02-missing-draft-390.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  checks.push('unsaved series invokes leave protection and cancel preserves input at desktop and 390px');

  const beforeContext = structuredClone(project.cases[0].context);
  await series.getByRole('button', { name: '确认系列', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '系列确认暂不可用' }).waitFor();
  assert.equal(calls.length, 1);
  assert.equal(await field.inputValue(), '  CY-200  ');
  assert.equal(project.cases[0].context.product_series, '');
  assert.equal(await series.getByRole('button', { name: '确认系列', exact: true }).isEnabled(), true);
  await page.screenshot({ path: join(output, '03-save-failed-retained.png'), fullPage: true });
  checks.push('failed confirmation retains the complete draft and leaves the server case unchanged');

  await series.getByRole('button', { name: '确认系列', exact: true }).evaluate(element => { element.click(); element.click(); });
  await page.waitForFunction(() => document.querySelectorAll('.rd-series-confirm').length === 0);
  assert.equal(calls.length, 2, 'repeat clicks share the in-flight save');
  assert.equal(calls[1].key, calls[0].key, 'retry keeps the same successful-intent identity');
  assert.equal(project.cases[0].context.product_series, 'CY-200');
  assert.deepEqual(project.cases[0].context, { ...beforeContext, product_series: 'CY-200' });
  assert.equal(project.cases[0].stage, 'input', 'UI consumes the actual invalidated stage without faking approval');
  assert.equal(await page.getByRole('heading', { name: '需求与澄清', level: 1, exact: true }).isVisible(), true, 'a normal save keeps the requirements workface');
  await page.screenshot({ path: join(output, '04-confirmed-no-editor.png'), fullPage: true });
  await page.getByRole('navigation', { name: '研发平台导航', exact: true }).getByRole('button', { name: '我的工作', exact: true }).click();
  await page.waitForFunction(() => !new URL(location.href).searchParams.has('project'));
  assert.equal(await page.getByRole('dialog', { name: '离开前保存填写', exact: true }).count(), 0, 'successful confirmation clears the dirty guard');
  checks.push('success trims and saves only series, hides its editor, retains workface and clears dirty state');

  project = base('AUTO-88');
  project.cases[0].context_provenance.product_series = { kind: 'source_analysis', evidence: [{ source_id: 'tech', quote: '产品型号：AUTO-88' }] };
  const callsBeforeRead = calls.length;
  await openCase();
  await steps.getByRole('button', { name: '需求确认', exact: true }).click();
  assert.equal(await page.locator('.rd-series-confirm').count(), 0, 'an adopted series has no manual replacement editor');
  assert.equal(project.cases[0].context.product_series, 'AUTO-88');
  assert.equal(calls.length, callsBeforeRead);
  await page.screenshot({ path: join(output, '05-adopted-series-readonly.png'), fullPage: true });
  checks.push('already adopted automatic series is preserved without a manual editing form');
  assert.deepEqual(unexpected, []);
  assert.deepEqual(errors, []);
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ checks, fixtureCommands: calls.length, errors, unexpected, realApiRequests: 0 }, null, 2));
  console.log(JSON.stringify({ passed: true, checks, fixtureCommands: calls.length, errors, unexpected, screenshots: output }, null, 2));
} finally { await browser.close(); }
