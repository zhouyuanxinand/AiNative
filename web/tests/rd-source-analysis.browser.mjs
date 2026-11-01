/** Source recognition/adoption UI. All API calls are isolated fixtures; no model or platform writes. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const stamp = '2026-11-01T02:00:00Z';
const sources = ['tech', 'spec'].map(role => ({ id: role, role, name: role === 'tech' ? '液冷组件规格书.doc' : '液冷产品规范.doc', size: 2048, version: 1, sha256: role, created_at: stamp }));
const empty = { product_type: '', product_domain: '', development_process: '', cover_phase: '', product_series: 'YLZJ', organization_scope: '' };
let project = { id: 'analysis-fixture', title: '资料识别行为验证', version: 1, owner_id: 'test', members: [], events: [], brief: '', cases: [{
  id: 'case-fixture', scenario_id: 'taskbook', title: '液冷任务书流程', stage: 'input', input_revision: 2, status: 'draft',
  context: empty, model_selection: { provider: '', name: '', id: '' }, source_selection: { tech: 'tech', spec: 'spec' },
  sources, requirements: [], product_route: null, composition_route: null, decisions: [], workpackages: [],
}] };
const proposal = {
  id: 'analysis-1', status: 'proposed', input_revision: 2, created_at: stamp, source_hashes: { tech: 'tech', spec: 'spec' },
  model_selection: { provider: 'fixture', name: 'test-default-model', id: '1' },
  context: Object.fromEntries(Object.keys(empty).map(key => [key, { value: '', status: 'unresolved', reason: '资料未明确，后续流程继续形成。', evidence: [] }])),
  requirements: Array.from({ length: 8 }, (_, index) => ({ title: `原文要求 ${index + 1}`, content: `引用原文第 ${index + 1} 条：工作温度 5℃～70℃。`, source_ids: ['tech'], evidence: [{ source_id: 'tech', quote: `引用原文第 ${index + 1} 条：工作温度 5℃～70℃。` }] })),
  warnings: ['旧版 DOC 已转换，请核对原文表格。'],
};
proposal.context.product_type = { value: 'liquid_cooling_pipeline', status: 'proposed', reason: '来源文件描述液冷管路。', evidence: [{ source_id: 'tech', quote: '本组件为液冷管路。' }] };
proposal.context.product_domain = { value: 'military', status: 'proposed', reason: '规范明确军品质量体系。', evidence: [{ source_id: 'spec', quote: '适用于军品。' }] };
proposal.context.product_series = { value: 'YLZJ', status: 'already_confirmed', reason: '保留现有系列。', evidence: [] };
let failAnalysis = true, failAdopt = true;
const analysisRequests = [], commands = [], errors = [];

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
    if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: 'liquid_cooling_pipeline', label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }] }] } });
    if (path === '/api/models') return route.fulfill({ json: { success: true, models: [{ provider: 'fixture', name: 'test-default-model', id: '1' }] } });
    if (path === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书' }], actions: [], workpackage_definitions: [] } });
    if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
    if (path === '/api/rd/projects/analysis-fixture') return route.fulfill({ json: project });
    if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: 'input', project_version: project.version, input_revision: project.cases[0].input_revision } } });
    if (path.endsWith('/analysis')) {
      assert.equal(request.method(), 'POST');
      analysisRequests.push({ key: request.headers()['idempotency-key'], body: request.postDataJSON() });
      await new Promise(resolve => setTimeout(resolve, 150));
      if (failAnalysis) { failAnalysis = false; return route.fulfill({ status: 502, json: { error: '模型服务暂不可用，资料已保留。' } }); }
      project.version += 1;
      project.cases[0].source_analysis = structuredClone(proposal);
      project.cases[0].source_analysis.input_revision = project.cases[0].input_revision;
      return route.fulfill({ json: project });
    }
    if (path.endsWith('/commands')) {
      const body = request.postDataJSON(); commands.push({ key: request.headers()['idempotency-key'], body });
      assert.equal(body.command, 'adopt_source_analysis');
      assert.equal(body.data.analysis_id, project.cases[0].source_analysis.id);
      assert.equal(body.data.case_id, 'case-fixture');
      if (failAdopt) { failAdopt = false; return route.fulfill({ status: 503, json: { error: '采用服务暂不可用，请重试。' } }); }
      project.version += 1; project.cases[0].input_revision += 1;
      const analysis = project.cases[0].source_analysis;
      analysis.status = 'adopted'; analysis.adopted_input_revision = project.cases[0].input_revision;
      for (const [key, item] of Object.entries(analysis.context)) if (item.status === 'proposed' && item.value) {
        project.cases[0].context[key] = item.value;
        project.cases[0].context_provenance ??= {};
        project.cases[0].context_provenance[key] = { kind: 'source_analysis', evidence: structuredClone(item.evidence), reason: item.reason, source_refs: item.source_refs ?? [] };
        if (project.cases[0].parameter_facts?.[key]) Object.assign(project.cases[0].parameter_facts[key], { status: 'adopted', evidence_status: 'current', source_refs: item.source_refs ?? [] });
      }
      if (analysis.requirements.length) project.cases[0].requirements = analysis.requirements.map((item, index) => ({ ...item, id: `requirement-${index}` }));
      return route.fulfill({ json: project });
    }
    return route.fulfill({ json: path.endsWith('/session') ? { ok: true } : {} });
  });
  await page.goto(`${process.env.TEST_BASE_URL || 'http://127.0.0.1:18370'}/?project=analysis-fixture&case=case-fixture`);
  await page.getByRole('button', { name: '分析资料并确认采用 →', exact: true }).first().click().catch(async error => { console.error('Page errors:', errors, 'Body:', await page.locator('body').innerText()); throw error; });
  const panel = page.getByRole('region', { name: '从资料形成项目信息与需求' });
  await panel.waitFor();
  assert.equal(await page.locator('input[id^="rd-context-"]').count(), 0, 'business context is not a manual input form');
  assert.equal(await panel.locator('dt').count(), 6);
  assert.equal(await panel.getByText('资料未明确', { exact: true }).count(), 5);
  const analyze = panel.getByRole('button', { name: '分析上传资料', exact: true });
  await analyze.evaluate(element => { element.click(); element.click(); });
  await page.getByRole('alert').filter({ hasText: '模型服务暂不可用' }).first().waitFor();
  assert.equal(analysisRequests.length, 1, 'duplicate click is locked');
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).count(), 0);
  await analyze.focus(); await page.keyboard.press('Enter');
  await panel.getByText('待核对采用', { exact: true }).waitFor();
  assert.equal(analysisRequests.length, 2);
  assert.equal(analysisRequests[0].key, analysisRequests[1].key, 'analysis retry keeps its idempotency key');
  assert.deepEqual(analysisRequests[1].body, { expected_version: 1 });
  assert.equal(commands.length, 0, 'preview must not silently adopt');
  await panel.getByText('液冷产品-液冷管路', { exact: true }).waitFor();
  await panel.getByText('军品', { exact: true }).waitFor();
  assert(!((await panel.innerText()).includes('liquid_cooling_pipeline')), 'internal enum is not exposed as a field value');
  assert.equal(await panel.locator('.rd-analysis-requirements article').count(), 5);
  await panel.getByRole('button', { name: '下一页', exact: true }).click();
  assert.equal(await panel.locator('.rd-analysis-requirements article').count(), 3);
  await panel.getByText('核对来源原文', { exact: true }).first().click();
  await panel.getByRole('blockquote').filter({ hasText: '第 6 条' }).waitFor();
  await panel.getByRole('button', { name: '上一页', exact: true }).click();
  if (output) {
    await panel.evaluate(element => { const shell = document.querySelector('.rd-application-shell'); shell.scrollTop += element.getBoundingClientRect().top - 110; });
    await page.screenshot({ path: join(output, 'source-analysis-proposal.png') });
  }
  await panel.getByRole('button', { name: '确认采用', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '采用服务暂不可用' }).first().waitFor();
  assert.equal(project.cases[0].requirements.length, 0, 'failed adoption does not update UI business records');
  await panel.getByRole('button', { name: '确认采用', exact: true }).click();
  await panel.getByText('已采用', { exact: true }).waitFor();
  await page.waitForFunction(() => document.activeElement?.textContent?.startsWith('识别结果已采用。'));
  assert.equal(commands[0].key, commands[1].key, 'adoption retry keeps its key');
  assert.equal(project.cases[0].stage, 'input', 'adoption does not invent stage approval');
  assert.equal(project.cases[0].context.cover_phase, '', 'missing information stays unresolved');
  assert.equal(project.cases[0].decisions.length, 0);
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).count(), 0);
  await page.getByRole('button', { name: '← 返回当前成果', exact: true }).click();
  await page.getByRole('button', { name: '澄清、采纳与需求确认 →', exact: true }).click();
  assert.equal(await page.getByLabel('需求标题', { exact: true }).isVisible(), false, 'manual entry is a secondary collapsed action');
  assert.equal(await page.locator('.rd-requirement-list article').count(), 8, 'adopted source requirements populate the next workflow');
  await page.getByRole('button', { name: '查看资料识别与采用', exact: true }).click();

  project.version += 1; project.cases[0].input_revision += 1;
  project.cases[0].source_analysis.status = 'proposed';
  await page.reload();
  await page.getByRole('button', { name: '分析资料并确认采用 →', exact: true }).first().click();
  await panel.getByText('待重新分析', { exact: true }).waitFor();
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).isDisabled(), true);
  await panel.getByRole('button', { name: '重新分析资料', exact: true }).click();
  await panel.getByText('待核对采用', { exact: true }).waitFor();
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).isEnabled(), true);
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.evaluate(element => { const shell = document.querySelector('.rd-application-shell'); shell.scrollTop += element.getBoundingClientRect().top - 16; });
  assert(await page.locator('.rd-application-shell').evaluate(element => element.scrollWidth <= element.clientWidth + 1), 'narrow layout has no horizontal page overflow');
  if (output) await page.screenshot({ path: join(output, 'source-analysis-narrow.png') });

  const researchCase = project.cases[0];
  const previousEvidence = structuredClone(researchCase.context_provenance.product_type);
  const replacementSource = { ...sources[0], id: 'tech-replacement', version: 2, sha256: 'replacement-tech-sha' };
  const replacementQuote = '产品类型：液冷管路。新版资料明确沿用原产品类型。';
  const replacementRefs = [{ source_id: replacementSource.id, version: replacementSource.version, sha256: replacementSource.sha256, location: { line: 1 } }];
  researchCase.sources.push(replacementSource); researchCase.source_selection.tech = replacementSource.id;
  researchCase.input_revision++; project.version++;
  researchCase.parameter_facts = { product_type: { field: 'product_type', value: researchCase.context.product_type, status: 'unresolved', evidence_status: 'stale', source_refs: [], decision_ref: null, rule_refs: [], reason: '旧来源已失效，等待核对。', candidates: [] } };
  researchCase.source_analysis = { ...structuredClone(proposal), id: 'analysis-refresh', input_revision: researchCase.input_revision,
    source_hashes: { 'tech-replacement': replacementSource.sha256, spec: 'spec' }, requirements: [], warnings: [],
    context: Object.fromEntries(Object.entries(researchCase.context).map(([key, value]) => [key, { value, status: value ? 'already_confirmed' : 'unresolved', reason: '保留原采用值。', evidence: [] }])) };
  researchCase.source_analysis.context.product_type = { value: researchCase.context.product_type, status: 'proposed', adoption_kind: 'refresh_source_refs',
    reason: '新版明确支持原参数值，等待明确采用新的来源依据。', evidence: [{ source_id: replacementSource.id, quote: replacementQuote }], source_refs: replacementRefs };
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload();
  await page.getByRole('button', { name: '分析资料并确认采用 →', exact: true }).first().click();
  const refreshedField = panel.locator('.rd-analysis-context-item').filter({ hasText: '同值新来源，待确认采用' });
  await refreshedField.waitFor();
  await refreshedField.getByText('查看原文依据', { exact: true }).click();
  await refreshedField.getByRole('blockquote').filter({ hasText: replacementQuote }).waitFor();
  assert.equal(await refreshedField.getByText('本组件为液冷管路。', { exact: true }).count(), 0, 'refresh preview quotes the new source, not old provenance');
  assert.equal(await panel.locator('.rd-analysis-requirements article').count(), 0);
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).isEnabled(), true, 'supported parameter refresh is adoptable without requirement rows');
  assert.deepEqual(researchCase.context_provenance.product_type, previousEvidence, 'preview preserves the previously adopted evidence');
  if (output) await page.screenshot({ path: join(output, 'source-analysis-same-value-refresh.png') });
  await panel.getByRole('button', { name: '确认采用', exact: true }).click();
  await panel.getByText('已采用', { exact: true }).waitFor();
  assert.equal(commands.at(-1).body.data.analysis_id, 'analysis-refresh');
  assert.equal(researchCase.context.product_type, 'liquid_cooling_pipeline');
  assert.deepEqual(researchCase.context_provenance.product_type.source_refs, replacementRefs);
  assert.equal(researchCase.requirements.length, 8, 'parameter-only adoption preserves prior requirements');
  assert.equal(await panel.getByText('同值新来源，待确认采用', { exact: true }).count(), 0, 'successful adoption no longer claims the new source is pending');
  project.cases[0].sources = []; project.cases[0].source_selection = {}; project.cases[0].requirements = []; delete project.cases[0].source_analysis;
  await page.reload();
  await page.getByRole('button', { name: '分析资料并确认采用 →', exact: true }).first().click();
  assert.equal(await panel.getByRole('button', { name: '分析上传资料', exact: true }).isDisabled(), true, 'empty sources cannot invoke the model');
  assert.deepEqual(errors, []);
  console.log('Source analysis browser checks passed: readonly context, preview, provenance, paging, failure/retry, adoption, stale input, same-value source refresh without requirements, narrow layout.');
} finally { await browser.close(); }
