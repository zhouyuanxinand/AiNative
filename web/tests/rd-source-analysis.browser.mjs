/** Source recognition/adoption UI. All API calls are isolated fixtures; no model or platform writes. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
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
proposal.context.development_process = { value: '改型II', status: 'proposed', reason: '来源明确研制流程。', evidence: [{ source_id: 'tech', quote: '研制流程：改型II。' }] };
proposal.context.product_series = { value: 'YLZJ', status: 'already_confirmed', reason: '保留现有系列。', evidence: [] };
proposal.requirements[0].recommendation = { text: '补充验收工况', proposed_value: '额定工况下核验工作温度。',
  evidence: [{ source_id: 'spec', quote: '额定工况下核验工作温度。' }] };
let failAnalysis = true, failAdopt = true, failSave = false, failDelete = false;
let holdAnalysis = true, holdSave = false, releaseAnalysis, releaseSave;
const modelChoices = [
  { provider: 'smartvision', name: 'azure/gpt-5.4', id: 'fixture-azure', vendor: '微软 Azure', configured: true },
  { provider: 'smartvision', name: 'dashscope/qwen3.5-plus', id: 'fixture-dashscope', vendor: '阿里云 DashScope', configured: true },
];
const analysisRequests = [], commands = [], errors = [], writeOrder = [], checks = [], unexpected = [];

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
    if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: 'liquid_cooling_pipeline', label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }] }] } });
    if (path === '/api/models') return route.fulfill({ json: { success: true, models: [{ provider: 'fixture', name: 'test-default-model', id: '1' }, ...modelChoices] } });
    if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'fixture-source-owner', local_mode: true } });
    if (path === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书' }], actions: [], workpackage_definitions: [] } });
    if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
    if (path === '/api/rd/projects/analysis-fixture') return route.fulfill({ json: project });
    if (path.endsWith('/evidence-locations') && request.method() === 'GET') return route.fulfill({ json: { items: [] } });
    if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: 'input', project_version: project.version, input_revision: project.cases[0].input_revision } } });
    if (path.endsWith('/sources/classify')) {
      const body = request.postDataJSON();
      assert.equal(body.use_model, true);
      return route.fulfill({ json: { items: body.files.map(item => ({ id: item.id, role: 'unknown', reason: '浏览器夹具待手动分类', method: 'unknown' })), warnings: [] } });
    }
    if (path.endsWith('/analysis')) {
      assert.equal(request.method(), 'POST');
      const call = { key: request.headers()['idempotency-key'], body: request.postDataJSON(), projectVersion: project.version, model: structuredClone(project.cases[0].model_selection) };
      analysisRequests.push(call); writeOrder.push({ kind: 'analysis', ...call });
      if (holdAnalysis) { holdAnalysis = false; await new Promise(resolve => { releaseAnalysis = resolve; }); }
      await new Promise(resolve => setTimeout(resolve, 150));
      if (failAnalysis) { failAnalysis = false; return route.fulfill({ status: 502, json: { error: '模型服务暂不可用，资料已保留。' } }); }
      project.version += 1;
      project.cases[0].source_analysis = structuredClone(proposal);
      project.cases[0].source_analysis.input_revision = project.cases[0].input_revision;
      if (call.model.provider) project.cases[0].source_analysis.model_selection = structuredClone(call.model);
      return route.fulfill({ json: project });
    }
    if (path.endsWith('/commands')) {
      const body = request.postDataJSON(); commands.push({ key: request.headers()['idempotency-key'], body });
      writeOrder.push({ kind: body.command, key: request.headers()['idempotency-key'], body: structuredClone(body) });
      if (body.command === 'delete_source') {
        assert.equal(request.method(), 'POST');
        assert.equal(body.expected_version, project.version, 'source deletion uses the current project version');
        assert.deepEqual(Object.keys(body.data).sort(), ['case_id', 'source_id']);
        assert.equal(body.data.case_id, 'case-fixture');
        const current = project.cases[0], source = current.sources.find(item => item.id === body.data.source_id);
        assert(source, 'only an existing fixture source can be deleted');
        await new Promise(resolve => setTimeout(resolve, 150));
        if (failDelete) { failDelete = false; return route.fulfill({ status: 503, json: { error: '删除资料服务暂不可用，请重试。' } }); }
        project.version += 1;
        current.sources = current.sources.filter(item => item.id !== source.id);
        current.deleted_sources = [...(current.deleted_sources ?? []), { ...structuredClone(source), deleted_at: stamp }];
        const selected = Object.values(current.source_selection).includes(source.id);
        current.source_selection = Object.fromEntries(Object.entries(current.source_selection).filter(([, id]) => id !== source.id));
        if (selected) {
          current.input_revision += 1;
          if (current.source_analysis) current.source_analysis.status = 'stale';
        }
        return route.fulfill({ json: project });
      }
      if (body.command === 'save_context') {
        if (holdSave) { holdSave = false; await new Promise(resolve => { releaseSave = resolve; }); }
        assert.equal(body.expected_version, project.version, 'model save uses the current project version');
        assert.equal(body.data.case_id, 'case-fixture');
        assert.deepEqual(Object.keys(body.data.model_selection).sort(), ['id', 'name', 'provider']);
        assert.equal(body.data.model_selection.provider, 'smartvision');
        if (failSave) { failSave = false; return route.fulfill({ status: 503, json: { error: '模型设置保存暂不可用，请重试。' } }); }
        project.version += 1; project.cases[0].input_revision += 1;
        project.cases[0].model_selection = structuredClone(body.data.model_selection);
        if (project.cases[0].source_analysis) project.cases[0].source_analysis.status = 'stale';
        return route.fulfill({ json: project });
      }
      assert.equal(body.command, 'adopt_source_analysis');
      assert.equal(body.data.accept_recommendations, undefined, 'adopting extraction never adopts specification suggestions');
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
      if (analysis.requirements.length) project.cases[0].requirements = analysis.requirements.map((item, index) => {
        item.requirement_id = `requirement-${index}`;
        return { ...item, id: item.requirement_id, revision: 1 };
      });
      return route.fulfill({ json: project });
    }
    if (request.method() !== 'GET') unexpected.push({ method: request.method(), path });
    return route.fulfill({ json: path.endsWith('/session') ? { ok: true } : {} });
  });
  await page.goto(`${process.env.TEST_BASE_URL || 'http://127.0.0.1:18370'}/?project=analysis-fixture&case=case-fixture`);
  const sourceStep = () => page.getByRole('navigation', { name: '办理步骤', exact: true }).getByRole('button', { name: '资料识别', exact: true });
  const openSourceStep = async () => {
    await sourceStep().waitFor();
    const viewed = page.getByRole('navigation', { name: '办理步骤', exact: true }).locator('[aria-current="step"]');
    const returning = await viewed.count() > 0 && await viewed.getAttribute('aria-label') !== '资料识别';
    const beforeUrl = page.url();
    await sourceStep().click();
    if (returning) {
      const confirmation = page.getByRole('dialog', { name: '返回资料识别', exact: true });
      await confirmation.waitFor();
      assert.equal(page.url(), beforeUrl, 'backward navigation waits for explicit confirmation');
      await confirmation.getByRole('button', { name: '继续返回', exact: true }).click();
      await confirmation.waitFor({ state: 'hidden' });
    }
    await sourceStep().and(page.locator('[aria-current="step"]')).waitFor();
  };
  await openSourceStep().catch(async error => { console.error('Page errors:', errors, 'Body:', await page.locator('body').innerText()); throw error; });
  const panel = page.getByRole('region', { name: '资料分析', exact: true });
  await panel.waitFor();
  const materials = page.getByRole('region', { name: '编制资料', exact: true });
  const materialsToggle = () => materials.getByRole('button', { name: /^(展开|收起)编制资料$/ });
  const checkMaterialsExpanded = async expanded => {
    assert.equal(await materialsToggle().getAttribute('aria-expanded'), String(expanded));
    assert.equal(await materials.getByRole('button', { name: '选择资料文件', exact: true }).and(materials.locator('button')).isVisible(), expanded);
  };
  await checkMaterialsExpanded(true);
  assert.equal(await page.locator('input[id^="rd-context-"]').count(), 0, 'business context is not a manual input form');
  assert.equal(await panel.locator('dt').count(), 2, 'development process and product series remain on the source-analysis page');
  assert.equal(await panel.getByText('资料未明确', { exact: true }).count(), 1);
  assert.equal(await panel.locator('dt').filter({ hasText: /^(产品类型|质量管理体系分类|封面阶段|组织范围)$/ }).count(), 0, 'project creation parameters are not repeated as source-analysis cards');
  const analyze = panel.getByRole('button', { name: '分析上传资料', exact: true });
  await analyze.evaluate(element => { element.click(); element.click(); });
  await panel.getByText('已提交分析，正在等待分析结果。服务尚未返回可细分的处理阶段，可能需要数分钟。', { exact:true }).waitFor();
  await panel.getByRole('timer', { name:'本次等待时长', exact:true }).getByText('已等待 0 分 1 秒', { exact:true }).waitFor();
  assert.equal(await panel.getByRole('progressbar').count(),0, 'analysis does not invent measurable progress');
  if (output) await page.screenshot({ path:join(output,'analysis-waiting-elapsed.png') });
  releaseAnalysis();
  checks.push('真实等待计时、无伪造百分比、分析失败保留资料并明确重试');
  await page.getByRole('alert').filter({ hasText: '模型服务暂不可用' }).first().waitFor();
  assert.equal(await page.getByRole('alert').filter({ hasText: '模型服务暂不可用' }).count(), 1, 'analysis failure is shown once in the page error area');
  assert.equal(analysisRequests.length, 1, 'duplicate click is locked');
  await panel.getByText(/本次未取得新的分析结果/).waitFor();
  await checkMaterialsExpanded(true);
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).count(), 0);
  await analyze.focus(); await page.keyboard.press('Enter');
  await panel.getByRole('button', { name: '确认采用', exact: true, disabled: false }).waitFor();
  assert.equal(analysisRequests.length, 2);
  await checkMaterialsExpanded(false);
  assert.equal(await materials.locator('input[type="file"]').count(), 1, 'collapsed upload content remains mounted');
  const topActions = panel.locator('.rd-analysis-controls');
  const topReanalyze = topActions.getByRole('button', { name: '重新分析资料', exact: true });
  const topAdopt = topActions.getByRole('button', { name: '确认采用', exact: true });
  const topReview = topActions.getByRole('button', { name: '核对需求', exact: true });
  assert.equal(await topReview.count(), 0, 'proposed analysis requires adoption before continuing');
  const [reanalyzeBox, adoptBox] = await Promise.all([topReanalyze.boundingBox(), topAdopt.boundingBox()]);
  assert(reanalyzeBox && adoptBox && adoptBox.x >= reanalyzeBox.x + reanalyzeBox.width && Math.abs(adoptBox.y - reanalyzeBox.y) <= 1, 'adopt follows reanalyze on the same top action row');
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).count(), 1, 'no duplicate adoption action below the result');
  await materialsToggle().focus(); await page.keyboard.press('Enter');
  await checkMaterialsExpanded(true);
  await materialsToggle().click();
  await checkMaterialsExpanded(false);
  if (output) await page.screenshot({ path: join(output, 'analysis-collapsed-actions-desktop.png') });
  checks.push('分析失败保持展开，成功收起且上传组件保持挂载；键盘展开；采用紧邻重新分析右侧且无底部重复按钮');
  assert.equal(analysisRequests[0].key, analysisRequests[1].key, 'analysis retry keeps its idempotency key');
  assert.deepEqual(analysisRequests[1].body, { expected_version: 1 });
  assert.equal(commands.length, 0, 'preview must not silently adopt');
  assert.equal(await panel.getByText('液冷产品-液冷管路', { exact: true }).count(), 0);
  assert.equal(await panel.getByText('军品', { exact: true }).count(), 0);
  await panel.getByText('改型II', { exact: true }).waitFor();
  assert(!((await panel.innerText()).includes('liquid_cooling_pipeline')), 'internal enum is not exposed as a field value');
  // Ignore the single colspan cell that describes an empty table.
  const previewRows = panel.locator('tbody tr').filter({ has: page.getByRole('cell').nth(3) });
  assert.equal(await previewRows.count(), proposal.requirements.length);
  for (const name of ['指标', '原文指标', '公司自有组件指标', 'AI 推荐', '证据来源', '需求澄清']) {
    assert.equal(await panel.getByRole('columnheader', { name, exact: true }).count(), 1, `preview column: ${name}`);
  }
  const reviewButton = panel.getByRole('button', { name: '全屏审阅', exact: true });
  const previewSearch = panel.getByRole('textbox', { name: '搜索需求', exact: true });
  await previewSearch.fill('原文要求 6');
  assert.equal(await previewRows.count(),1, 'ordinary preview supports local search');
  assert.equal(await previewRows.locator('.rd-req-metric > span').innerText(),'06', 'preview search retains the source row number');
  await panel.getByRole('button', {name:'清除搜索',exact:true}).click();
  assert.equal(await previewSearch.evaluate(el=>el===document.activeElement),true, 'search clear returns focus to input');
  const review = page.getByRole('dialog', { name: '需求清单审阅', exact: true });
  const searchReview = review.getByLabel('搜索需求', { exact: true });
  assert.equal(await panel.getByRole('checkbox', { name: '选用此建议' }).count(), 0, 'extraction has no specification adoption controls');
  assert.equal(await previewRows.first().getByRole('cell').nth(3).innerText(), '待需求确认时核对规范');
  assert.equal(await previewRows.first().getByRole('cell').nth(4).innerText(), '—', 'legacy hints never populate specification evidence');
  assert.equal(commands.length, 0, 'preview does not write a business decision');
  assert.equal(await page.locator('.rd-case-page > .rd-project-header').count(), 0, 'case workface removes the redundant project toolbar');
  assert.equal(await page.locator('.rd-case-page > .rd-project-business-context').count(), 0, 'case workface starts with workflow navigation instead of repeated background');
  await panel.getByRole('button', { name: '客户画像', exact: true }).click();
  const customerProfile = page.getByRole('dialog', { name: '客户画像', exact: true });
  await customerProfile.waitFor();
  assert.equal(await customerProfile.locator('input, textarea').count(), 0, 'project portrait lookup is a read-only projection');
  if (output) await page.screenshot({ path: join(output, 'customer-profile-inspector.png') });
  await customerProfile.getByRole('button', { name: '返回办理', exact: true }).click();
  await customerProfile.waitFor({ state: 'hidden' });
  assert.equal(await previewRows.count(), 8, 'closing a portrait preserves the source list');
  await panel.getByRole('button', { name: '产品画像', exact: true }).click();
  const productProfile = page.getByRole('dialog', { name: '产品画像', exact: true });
  await productProfile.waitFor();
  await page.keyboard.press('Escape');
  await productProfile.waitFor({ state: 'hidden' });
  assert.equal(commands.length, 0, 'portrait lookup does not adopt a requirement or write a profile');
  const sixthSource = panel.getByText('核对来源原文', { exact: true }).nth(5);
  await sixthSource.click();
  await panel.getByRole('blockquote').filter({ hasText: '第 6 条' }).waitFor();
  await reviewButton.click();
  await review.waitFor();
  await searchReview.fill('原文要求 1');
  await review.locator('tbody tr').filter({ hasText: '原文要求 1' }).waitFor();
  assert.equal(await review.locator('tbody tr').count(), 1, 'full review searches the entire source list');
  assert.equal(await review.getByRole('checkbox', { name: '选用此建议' }).count(), 0, 'fullscreen follows the same extraction-only contract');
  await searchReview.fill('');
  assert.equal(await review.getByRole('button', {name:/已选建议/}).count(), 0, 'obsolete suggestion selection is not offered');
  await review.getByRole('button', {name:'待处理（8）',exact:true}).click();
  assert.equal(await review.locator('tbody tr[data-row-key]').count(),8, 'fullscreen pending filter retains all original requirements');
  await review.getByRole('button', {name:'下一项待处理',exact:true}).click();
  assert.equal(await review.locator('tr[data-row-key="1"]').evaluate(el=>el===document.activeElement),true);
  await review.getByRole('button', {name:'全部（8）',exact:true}).click();
  await searchReview.fill('原文要求 1');
  await review.getByText('筛选仅影响显示；确认采用将采用全部 8 项原文需求和可采用的识别信息。', { exact:true }).waitFor();
  assert.equal(await review.getByText('建议依据', { exact: true }).count(), 0);
  assert.equal(await review.locator('tbody tr').getByRole('cell').nth(4).innerText(), '—');
  assert(!/5℃|70℃/.test(await review.locator('tbody tr').getByRole('cell').nth(2).innerText()), 'the company indicator cannot copy an unverified source value');
  await searchReview.fill('无匹配指标的搜索词');
  await review.getByText(/没有匹配的需求/).waitFor();
  await searchReview.fill('');
  await review.getByText('核对来源原文', { exact: true }).first().click();
  if (output) {
    await page.getByText('资料分析已完成，请核对识别依据与原文需求后确认采用。', { exact: true }).waitFor({ state: 'hidden' });
    await page.screenshot({ path: join(output, 'requirement-review-desktop.png') });
  }
  await page.keyboard.press('Escape'); await review.waitFor({ state: 'hidden' });
  assert.equal(await previewRows.count(), 8, 'returning from full review retains the entire list');
  await panel.getByRole('blockquote').filter({ hasText: '第 6 条' }).waitFor();
  assert.equal(await previewRows.first().getByRole('cell').nth(4).innerText(), '—', 'returning cannot expose legacy suggestion evidence');
  assert(await sixthSource.evaluate(el => el.parentElement.open), 'returning keeps the open original quote');
  checks.push('需求清单全量纵览、原文出处核对、屏蔽旧增强建议、全屏检索和原位返回');
  if (output) {
    await panel.evaluate(element => { const shell = document.querySelector('.rd-application-shell'); shell.scrollTop += element.getBoundingClientRect().top - 110; });
    await page.screenshot({ path: join(output, 'source-analysis-proposal.png') });
  }
  await reviewButton.click(); await review.waitFor();
  await searchReview.fill('原文要求 1');
  await review.getByRole('button', { name: '确认采用', exact: true }).evaluate(element=>{ element.click(); element.click(); });
  await review.getByRole('status').filter({ hasText:'采用服务暂不可用' }).waitFor();
  await page.getByRole('alert', { includeHidden:true }).filter({ hasText: '采用服务暂不可用' }).first().waitFor({state:'attached'});
  assert.equal(project.cases[0].requirements.length, 0, 'failed adoption does not update UI business records');
  assert.equal(await searchReview.inputValue(), '原文要求 1', 'fullscreen adoption failure preserves the current search');
  assert.equal(await review.locator('tbody tr[data-row-key]').count(), 1, 'fullscreen adoption failure preserves the reviewed row');
  await review.getByRole('button', { name: '确认采用', exact: true }).click();
  await review.waitFor({state:'hidden'});
  await page.getByRole('navigation', { name: '办理步骤', exact: true }).getByRole('button', { name: '需求确认', exact: true }).and(page.locator('[aria-current="step"]')).waitFor();
  await page.waitForFunction(() => document.activeElement?.id === 'rd-case-workarea');
  await openSourceStep();
  await panel.getByText('识别结果已采用，可继续核对并确认需求。', { exact: true }).waitFor();
  await topReview.and(page.locator(':enabled')).waitFor();
  assert.equal(await page.getByRole('button', { name: '核对需求', exact: true }).count(), 1, 'adopted analysis has one continuation at the top');
  assert.equal(await topReview.evaluate(element => element.classList.contains('ant-btn-primary')), true, 'continuing is the primary action');
  assert.equal(await topReanalyze.evaluate(element => element.classList.contains('ant-btn-primary')), false, 'reanalyzing an adopted result is secondary');
  const [reviewReanalyzeBox, reviewBox] = await Promise.all([topReanalyze.boundingBox(), topReview.boundingBox()]);
  assert(reviewReanalyzeBox && reviewBox && reviewBox.x >= reviewReanalyzeBox.x + reviewReanalyzeBox.width && Math.abs(reviewBox.y - reviewReanalyzeBox.y) <= 1, 'review follows reanalysis on the same desktop action row');
  if (output) await page.screenshot({ path: join(output, 'adopted-analysis-continuation-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await topReview.scrollIntoViewIfNeeded();
  const [mobileReanalyze, mobileReview] = await Promise.all([topReanalyze.boundingBox(), topReview.boundingBox()]);
  assert(mobileReanalyze && mobileReview && mobileReview.x >= mobileReanalyze.x + mobileReanalyze.width && Math.abs(mobileReview.y - mobileReanalyze.y) <= 1, '390px adopted controls keep review to the right');
  assert(await page.locator('.rd-application-shell').evaluate(element => element.scrollWidth <= element.clientWidth + 1), 'adopted controls do not overflow the narrow page');
  if (output) await page.screenshot({ path: join(output, 'adopted-analysis-continuation-narrow.png') });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const adoptedPicker = panel.getByRole('combobox', { name: '编制模型', exact: true });
  await adoptedPicker.locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').click();
  await page.getByRole('option', { name: `${modelChoices[0].vendor} · ${modelChoices[0].name}`, exact: true }).click();
  assert.equal(await topReview.isDisabled(), true, 'an unsaved model selection cannot continue using the old analysis');
  await adoptedPicker.locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').click();
  await page.getByRole('option', { name: '使用平台默认模型', exact: true }).click();
  assert.equal(await topReview.isEnabled(), true, 'restoring the adopted model restores continuation');
  await materialsToggle().click();
  await page.getByLabel('选择资料文件', { exact: true }).setInputFiles({ name: '待上传继续核对验收.txt', mimeType: 'text/plain', buffer: Buffer.from('浏览器隔离夹具') });
  assert.equal(await topReview.isDisabled(), true, 'pending uploads block continuing with adopted analysis');
  const pendingContinuationUrl = page.url(), pendingContinuationWrites = writeOrder.length;
  await topReview.evaluate(element => element.click());
  assert.equal(page.url(), pendingContinuationUrl);
  assert.equal(writeOrder.length, pendingContinuationWrites);
  await page.getByRole('button', { name: '清空待上传', exact: true }).click();
  await topReview.and(page.locator(':enabled')).waitFor();
  assert.equal(await topReview.isEnabled(), true);
  holdAnalysis = true; failAnalysis = true;
  await topReanalyze.click();
  await panel.getByText('已提交分析，正在等待分析结果。服务尚未返回可细分的处理阶段，可能需要数分钟。', { exact: true }).waitFor();
  assert.equal(await topReview.isDisabled(), true, 'in-flight reanalysis cannot continue');
  releaseAnalysis();
  await panel.getByText(/本次未取得新的分析结果/).waitFor();
  assert.equal(await topReview.isEnabled(), true, 'a failed retry keeps the previously adopted current result available');
  checks.push('普通预览搜索及清除焦点、全屏筛选、明确仅采用原文范围、全屏失败保留搜索并同键重试');
  assert.equal(commands[0].key, commands[1].key, 'adoption retry keeps its key');
  assert.equal(project.cases[0].stage, 'input', 'adoption does not invent stage approval');
  assert.equal(project.cases[0].context.cover_phase, '', 'missing information stays unresolved');
  assert.equal(project.cases[0].decisions.length, 0);
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).count(), 0);
  const beforeContinue = writeOrder.length;
  await topReview.click();
  await page.getByRole('navigation', { name: '办理步骤', exact: true }).getByRole('button', { name: '需求确认', exact: true }).and(page.locator('[aria-current="step"]')).waitFor();
  assert.equal(writeOrder.length, beforeContinue, 'reviewing adopted requirements only navigates and never repeats analysis or adoption');
  assert.equal(await page.getByLabel('需求标题', { exact: true }).isVisible(), false, 'manual entry is a secondary collapsed action');
  assert.equal(await page.locator('.rd-requirement-list tbody tr[data-row-key]').count(), 8, 'adopted source requirements populate the next workflow');
  await openSourceStep();

  // Reorder the working list and have two questions share a title: only the adopted ID identifies the row.
  const currentCase = project.cases[0], originalRequirements = structuredClone(currentCase.requirements);
  const ids = originalRequirements.map(item => item.id), inputRevision = currentCase.input_revision;
  const adoptedValue = '采用工况为 12℃～40℃', companyReply = '客户回复：以现场验收数据为依据';
  const clarification = (requirement_id, question, status) => ({ id: `c-${requirement_id}`, requirement_id, requirement_revision: 1, input_revision: inputRevision,
    revision: status === 'open' ? 1 : status === 'answered' ? 2 : 3, status, required: true, question, answer: null, source_ids: ['tech'],
    answer_source_ids: [], adoption: null, actor: 'test', created_at: stamp });
  currentCase.requirements[2] = { ...currentCase.requirements[2], content: adoptedValue, revision: 2 };
  currentCase.requirements.reverse();
  currentCase.clarifications = [
    { ...clarification(ids[2], '确认环境温度适用条件', 'adopted'), input_revision: inputRevision - 1, answer: companyReply, answer_source_ids: ['spec'],
      adoption: { requirement_revision: 2, input_revision: inputRevision, requirement_content: adoptedValue, actor: 'test', created_at: stamp } },
    clarification(ids[0], '确认环境温度适用条件', 'open'),
    { ...clarification(ids[1], '请核实运输温度', 'answered'), answer: '运输条件尚待采用', answer_source_ids: ['tech'] },
    { ...clarification(ids[3], '旧版工况问题', 'answered'), input_revision: inputRevision - 1, answer: '旧版工况回复', answer_source_ids: ['tech'] },
  ];
  project.version++;
  await page.reload(); await openSourceStep();
  const metricRow = index => previewRows.filter({ hasText: `原文要求 ${index}` });
  const detail = index => metricRow(index).getByRole('cell').nth(5);
  await detail(1).getByText('待答复', { exact: true }).waitFor();
  await detail(1).getByText('确认环境温度适用条件', { exact: true }).waitFor();
  assert(!(await detail(1).innerText()).includes(companyReply), 'another requirement with the same question must not leak its answer');
  await detail(2).getByText('待采用', { exact: true }).waitFor();
  assert((await detail(2).innerText()).includes('运输条件尚待采用'));
  await detail(3).getByText('已采用', { exact: true }).waitFor();
  assert((await detail(3).innerText()).includes(companyReply));
  assert((await detail(3).innerText()).includes(adoptedValue));
  const originalMetric = await metricRow(3).getByRole('cell').nth(1).innerText();
  assert(originalMetric.includes('第 3 条') && !originalMetric.includes(adoptedValue), 'clarification never overwrites the displayed original requirement');
  assert.equal((await metricRow(3).getByRole('cell').nth(2).innerText()).trim(), '—', 'no adopted reply becomes a company capability claim');
  await detail(4).getByText('当前版本无澄清', { exact: true }).waitFor();
  await detail(4).getByText(/历史澄清/).click();
  assert((await detail(4).innerText()).includes('旧版工况回复'), 'older replies are explicitly available as history');
  await panel.getByRole('button', {name:'待澄清（2）',exact:true}).click();
  assert.equal(await previewRows.count(),2, 'clarification filter excludes adopted and stale records');
  await panel.getByRole('button', {name:'全部（8）',exact:true}).click();
  await reviewButton.click(); await review.waitFor();
  await searchReview.fill(companyReply);
  await review.locator('tbody tr').filter({ hasText: '原文要求 3' }).waitFor();
  assert.equal(await review.locator('tbody tr').count(), 1);
  if (output) await page.screenshot({ path: join(output, 'requirement-review-clarified.png') });
  await review.getByRole('button', { name: '退出全屏', exact: true }).click();
  await review.waitFor({ state: 'hidden' });
  const beforeReview = writeOrder.length;
  await reviewButton.click(); await review.waitFor();
  await searchReview.fill('运输条件尚待采用');
  await review.getByRole('row').filter({ hasText: '原文要求 2' }).getByRole('button', { name: '办理澄清', exact: true }).click();
  await review.waitFor({ state: 'hidden' });
  await page.waitForFunction(id => document.activeElement?.id === `rd-clar-adopt-c-${id}`, ids[1]);
  await openSourceStep();
  await detail(1).getByRole('button', { name: '办理澄清', exact: true }).click();
  await page.waitForFunction(id => document.activeElement?.id === `rd-clar-answer-c-${id}`, ids[0]);
  await openSourceStep();
  await detail(5).getByRole('button', { name: '办理澄清', exact: true }).click();
  await page.waitForFunction(() => document.activeElement?.id === 'rd-clar-question');
  const targetForm = page.locator('form').filter({ has: page.getByLabel('需要澄清的问题', { exact: true }) });
  assert((await targetForm.innerText()).includes('原文要求 5'), 'new clarification is targeted to the chosen requirement');
  await page.locator('#rd-clar-question').fill('草稿 A');
  await page.locator('.rd-requirement-list tbody tr').filter({ hasText: '原文要求 2' }).getByRole('button', { name: '办理澄清', exact: true }).click();
  await page.getByText(/已有未保存的澄清草稿/).waitFor();
  assert.equal(await page.locator('#rd-clar-question').inputValue(), '草稿 A', 'moving to another requirement preserves an unfinished question');
  assert((await targetForm.innerText()).includes('原文要求 5'), 'preserving a question draft must also preserve its original target');
  await page.waitForFunction(() => document.activeElement?.id === 'rd-clar-question');
  await page.locator('#rd-clar-question').fill('');
  await page.reload(); await openSourceStep();
  assert.equal(writeOrder.length, beforeReview, 'exiting, opening clarification and refreshing must not write');
  assert.equal(commands.length, 2, 'review actions never submit or adopt changes');
  currentCase.requirements = originalRequirements; currentCase.clarifications = [];
  checks.push('按已采用需求 ID 关联澄清；区分原文、待答复、已答复、采用结果和版本历史');

  project.version += 1; project.cases[0].input_revision += 1;
  project.cases[0].source_analysis.status = 'proposed';
  await page.reload();
  await openSourceStep();
  await panel.getByText('这份识别结果已过期。资料或项目信息已变化，请重新分析后再采用。', { exact: true }).waitFor();
  assert.equal(await topReview.count(), 0, 'stale analysis does not offer continuation to requirement review');
  await checkMaterialsExpanded(true);
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).isDisabled(), true);
  await reviewButton.click(); await review.waitFor();
  assert.equal(await review.getByRole('button', {name:'确认采用',exact:true}).isDisabled(),true, 'fullscreen keeps stale analysis locked');
  assert.equal(await review.getByRole('checkbox', {name:'选用此建议'}).count(),0, 'stale extraction still has no suggestion adoption controls');
  await review.getByRole('button', {name:'来源待复核（8）',exact:true}).click();
  assert.equal(await review.locator('tbody tr[data-row-key]').count(),8);
  await review.getByRole('button', {name:'退出全屏',exact:true}).click(); await review.waitFor({state:'hidden'});
  checks.push('当前澄清筛选排除历史和已采用记录；全屏过期分析与建议保持禁用');
  await panel.getByRole('button', { name: '重新分析资料', exact: true }).click();
  await panel.getByRole('button', { name: '确认采用', exact: true, disabled: false }).waitFor();
  await checkMaterialsExpanded(false);
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).isEnabled(), true);
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.evaluate(element => { const shell = document.querySelector('.rd-application-shell'); shell.scrollTop += element.getBoundingClientRect().top - 16; });
  assert(await page.locator('.rd-application-shell').evaluate(element => element.scrollWidth <= element.clientWidth + 1), 'narrow layout has no horizontal page overflow');
  const [narrowReanalyze, narrowAdopt] = await Promise.all([topReanalyze.boundingBox(), topAdopt.boundingBox()]);
  assert(narrowReanalyze && narrowAdopt && narrowAdopt.x >= narrowReanalyze.x + narrowReanalyze.width && Math.abs(narrowAdopt.y - narrowReanalyze.y) <= 1, '390px action row keeps adoption to the right of reanalysis');
  if (output) await page.screenshot({ path: join(output, 'source-analysis-narrow.png') });
  await reviewButton.click(); await review.waitFor();
  assert(await review.evaluate(element => {
    const box = element.getBoundingClientRect();
    return box.width >= innerWidth - 8 && box.left >= -1 && box.right <= innerWidth + 1;
  }), 'narrow full-screen review fits viewport');
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'narrow review has no horizontal page overflow');
  if (output) {
    await page.getByText('资料分析已完成，请核对识别依据与原文需求后确认采用。', { exact: true }).waitFor({ state: 'hidden' });
    await page.screenshot({ path: join(output, 'requirement-review-narrow.png') });
  }
  await page.keyboard.press('Escape'); await review.waitFor({ state: 'hidden' });

  const researchCase = project.cases[0];
  const previousEvidence = structuredClone(researchCase.context_provenance.development_process);
  const replacementSource = { ...sources[0], id: 'tech-replacement', version: 2, sha256: 'replacement-tech-sha' };
  const replacementQuote = '研制流程：改型II。新版资料明确沿用原研制流程。';
  const replacementRefs = [{ source_id: replacementSource.id, version: replacementSource.version, sha256: replacementSource.sha256, location: { line: 1 } }];
  researchCase.sources.push(replacementSource); researchCase.source_selection.tech = replacementSource.id;
  researchCase.input_revision++; project.version++;
  researchCase.parameter_facts = { development_process: { field: 'development_process', value: researchCase.context.development_process, status: 'unresolved', evidence_status: 'stale', source_refs: [], decision_ref: null, rule_refs: [], reason: '旧来源已失效，等待核对。', candidates: [] } };
  researchCase.source_analysis = { ...structuredClone(proposal), id: 'analysis-refresh', input_revision: researchCase.input_revision,
    source_hashes: { 'tech-replacement': replacementSource.sha256, spec: 'spec' }, requirements: [], warnings: [],
    context: Object.fromEntries(Object.entries(researchCase.context).map(([key, value]) => [key, { value, status: value ? 'already_confirmed' : 'unresolved', reason: '保留原采用值。', evidence: [] }])) };
  researchCase.source_analysis.context.development_process = { value: researchCase.context.development_process, status: 'proposed', adoption_kind: 'refresh_source_refs',
    reason: '新版明确支持原参数值，等待明确采用新的来源依据。', evidence: [{ source_id: replacementSource.id, quote: replacementQuote }], source_refs: replacementRefs };
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload();
  await openSourceStep();
  const refreshedField = panel.locator('.rd-analysis-context-item').filter({ hasText: '同值新来源，待确认采用' });
  await refreshedField.waitFor();
  await refreshedField.getByText('查看原文依据', { exact: true }).click();
  await refreshedField.getByRole('blockquote').filter({ hasText: replacementQuote }).waitFor();
  assert.equal(await refreshedField.getByText('研制流程：改型II。', { exact: true }).count(), 0, 'refresh preview quotes the new source, not old provenance');
  assert.equal(await previewRows.count(), 0);
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).isEnabled(), true, 'supported parameter refresh is adoptable without requirement rows');
  assert.deepEqual(researchCase.context_provenance.development_process, previousEvidence, 'preview preserves the previously adopted evidence');
  if (output) await page.screenshot({ path: join(output, 'source-analysis-same-value-refresh.png') });
  await panel.getByRole('button', { name: '确认采用', exact: true }).click();
  await page.getByRole('navigation', { name: '办理步骤', exact: true }).getByRole('button', { name: '需求确认', exact: true }).and(page.locator('[aria-current="step"]')).waitFor();
  await openSourceStep();
  await panel.getByText('识别结果已采用，可继续核对并确认需求。', { exact: true }).waitFor();
  assert.equal(commands.at(-1).body.data.analysis_id, 'analysis-refresh');
  assert.equal(researchCase.context.product_type, 'liquid_cooling_pipeline');
  assert.equal(researchCase.context.development_process, '改型II');
  assert.deepEqual(researchCase.context_provenance.development_process.source_refs, replacementRefs);
  assert.equal(researchCase.requirements.length, 8, 'parameter-only adoption preserves prior requirements');
  assert.equal(await panel.getByText('同值新来源，待确认采用', { exact: true }).count(), 0, 'successful adoption no longer claims the new source is pending');

  // The original default-model lifecycle above stays intact; model changes now save as part of analysis.
  researchCase.source_analysis = { ...structuredClone(proposal), status: 'proposed', input_revision: researchCase.input_revision };
  await page.reload();
  await openSourceStep();
  const picker = panel.getByRole('combobox', { name: '编制模型', exact: true });
  const analyzeSelected = () => panel.getByRole('button', { name: /^(分析上传资料|重新分析资料)$/ });
  const saveCalls = () => commands.filter(item => item.body.command === 'save_context');
  const selectModel = async model => {
    await picker.locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').click();
    await page.getByRole('option', { name: `${model.vendor} · ${model.name}`, exact: true }).click();
  };
  const selection = model => ({ provider: model.provider, name: model.name, id: model.id });
  await selectModel(modelChoices[0]);
  assert.equal(await page.getByRole('button', { name: '保存模型设置', exact: true }).count(), 0, 'model selection has no separate save action');
  assert.equal(await analyzeSelected().isEnabled(), true, 'a changed model can be analyzed directly');
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).isDisabled(), true, 'a model draft cannot adopt an old analysis result');

  const pendingWrites = writeOrder.length;
  await checkMaterialsExpanded(false);
  await materialsToggle().click();
  await page.getByLabel('选择资料文件', { exact: true }).setInputFiles({ name: '待上传模型联动验收.txt', mimeType: 'text/plain', buffer: Buffer.from('仅用于浏览器夹具，不上传真实资料。') });
  await checkMaterialsExpanded(true);
  assert.equal(await materialsToggle().isDisabled(), true, 'pending uploads stay visible until handled');
  assert.equal(await analyzeSelected().isDisabled(), true, 'a pending file still blocks analysis with a changed model');
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).isDisabled(), true);
  await analyzeSelected().evaluate(element => element.click());
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(writeOrder.length, pendingWrites, 'a pending file cannot trigger a save or analysis request');
  if (output) await page.screenshot({ path: join(output, 'model-change-pending-upload.png') });
  await page.getByRole('button', { name: '清空待上传', exact: true }).click();
  await analyzeSelected().click({ trial: true });
  checks.push('模型改值可直接分析、无独立保存；旧结果采用及待上传文件保护保留');

  failSave = true; holdSave = true;
  const modelSaveStart = saveCalls().length, modelAnalysisStart = analysisRequests.length;
  const versionBeforeModelSave = project.version;
  const firstWrite = page.waitForRequest(request => request.method() === 'POST' && /\/(?:commands|analysis)$/.test(new URL(request.url()).pathname));
  await analyzeSelected().evaluate(element => { element.click(); element.click(); });
  assert.equal(new URL((await firstWrite).url()).pathname.endsWith('/commands'), true, 'a changed model is saved before any analysis request');
  await panel.getByText('正在保存模型设置，尚未开始分析。', {exact:true}).waitFor();
  if (output) await page.screenshot({path:join(output,'analysis-saving-model.png')});
  releaseSave();
  await page.getByRole('alert').filter({ hasText: '模型设置保存暂不可用' }).first().waitFor();
  assert.equal(saveCalls().length, modelSaveStart + 1, 'duplicate clicks submit a single model save');
  assert.equal(analysisRequests.length, modelAnalysisStart, 'save failure does not invoke analysis');
  assert.equal(project.version, versionBeforeModelSave, 'failed save does not advance the project');
  assert((await panel.locator('.ant-select-selection-item').innerText()).includes(modelChoices[0].name), 'save failure preserves the chosen model');
  assert.equal(await analyzeSelected().isEnabled(), true);
  if (output) await page.screenshot({ path: join(output, 'model-save-failure.png') });

  failAnalysis = true; holdAnalysis = true;
  const retryOrder = writeOrder.length;
  await analyzeSelected().evaluate(element => { element.click(); element.click(); });
  await panel.getByText('已提交分析，正在等待分析结果。服务尚未返回可细分的处理阶段，可能需要数分钟。', { exact:true }).waitFor();
  assert.equal(await panel.getByText('正在保存模型设置，尚未开始分析。', {exact:true}).count(),0, 'confirmed model save advances the known waiting phase');
  releaseAnalysis();
  await page.getByRole('alert').filter({ hasText: '模型服务暂不可用' }).first().waitFor();
  assert.equal(saveCalls().length, modelSaveStart + 2, 'retry saves once before the first analysis');
  assert.equal(saveCalls().at(-1).key, saveCalls().at(-2).key, 'model-save retry keeps its idempotency key');
  assert.equal(analysisRequests.length, modelAnalysisStart + 1);
  assert.deepEqual(writeOrder.slice(retryOrder).map(item => item.kind), ['save_context', 'analysis'], 'one locked chain saves then analyzes');
  const analysisAfterSave = analysisRequests.at(-1);
  assert.deepEqual(saveCalls().at(-1).body.data.model_selection, selection(modelChoices[0]));
  assert.equal(analysisAfterSave.body.expected_version, versionBeforeModelSave + 1, 'analysis uses the project version returned by saving');
  assert.equal(analysisAfterSave.body.expected_version, analysisAfterSave.projectVersion);
  assert.deepEqual(analysisAfterSave.model, selection(modelChoices[0]), 'analysis sees the persisted provider/name/id');
  if (output) await page.screenshot({ path: join(output, 'model-saved-analysis-failed.png') });

  const analysisRetryOrder = writeOrder.length;
  await Promise.all([
    page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/analysis')),
    analyzeSelected().evaluate(element => { element.click(); element.click(); }),
  ]);
  await panel.getByRole('button', { name: '确认采用', exact: true, disabled: false }).waitFor();
  assert.equal(saveCalls().length, modelSaveStart + 2, 'analysis failure retry does not save the unchanged model again');
  assert.equal(analysisRequests.length, modelAnalysisStart + 2, 'duplicate retry clicks start one analysis');
  assert.equal(analysisRequests.at(-1).key, analysisAfterSave.key, 'analysis retry keeps its original idempotency key');
  assert.deepEqual(analysisRequests.at(-1).body, analysisAfterSave.body);
  assert.deepEqual(writeOrder.slice(analysisRetryOrder).map(item => item.kind), ['analysis']);
  checks.push('保存失败不分析且同键重试；保存成功用新版本分析，分析失败仅重试原分析键，重复点击不重复提交');

  await selectModel(modelChoices[1]);
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).isDisabled(), true);
  const directVersion = project.version, directSaveStart = saveCalls().length, directAnalysisStart = analysisRequests.length, directOrder = writeOrder.length;
  await Promise.all([
    page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/analysis')),
    analyzeSelected().evaluate(element => { element.click(); element.click(); }),
  ]);
  await panel.getByRole('button', { name: '确认采用', exact: true, disabled: false }).waitFor();
  assert.equal(saveCalls().length, directSaveStart + 1);
  assert.equal(analysisRequests.length, directAnalysisStart + 1);
  assert.deepEqual(writeOrder.slice(directOrder).map(item => item.kind), ['save_context', 'analysis']);
  assert.equal(analysisRequests.at(-1).body.expected_version, directVersion + 1);
  assert.deepEqual(analysisRequests.at(-1).model, selection(modelChoices[1]));
  assert.equal(await panel.getByRole('button', { name: '确认采用', exact: true }).isEnabled(), true);
  if (output) await page.screenshot({ path: join(output, 'model-change-save-and-analyze-success.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.evaluate(element => { const shell = document.querySelector('.rd-application-shell'); shell.scrollTop += element.getBoundingClientRect().top - 16; });
  assert(await page.locator('.rd-application-shell').evaluate(element => element.scrollWidth <= element.clientWidth + 1), 'narrow model-and-analysis controls have no horizontal page overflow');
  if (output) await page.screenshot({ path: join(output, 'model-change-save-and-analyze-narrow.png') });
  await page.setViewportSize({ width: 1440, height: 1000 });
  checks.push('一次点击完成新模型保存和成功分析，返回结果才允许采用');

  // File-card behavior shares the real page coordinator and the same isolated command transport.
  const longSourceName = '液冷🚀组件技术要求及环境适应性验证规范与中文长文件名称最终受控版本2026.docx';
  const boundarySourceName = '规'.repeat(26) + '.pdf';
  const cardSources = [
    { ...sources[0], id: 'card-tech', role: 'tech', name: longSourceName, sha256: 'card-tech-sha' },
    { ...sources[1], id: 'card-spec', role: 'spec', name: boundarySourceName, sha256: 'card-spec-sha' },
    { ...sources[0], id: 'card-reference', role: 'reference', name: '参考连接结构示意图.png', sha256: 'card-reference-sha' },
    { ...sources[0], id: 'card-history-tech', role: 'tech', name: '上一版技术资料.doc', sha256: 'card-history-sha' },
  ];
  Object.assign(researchCase, {
    sources: structuredClone(cardSources), source_selection: { tech: 'card-tech', spec: 'card-spec' }, status: 'draft', workpackages: [],
    workflow_templates: { project: { id: 'fixture-adoption', template_id: 'taskbook-generation', template_version: '1', template_digest: 'fixture-project-digest', title: '已固定的研制任务书生成', category: 'project', graph: { nodes: [], edges: [] } } },
    project_workflow_status: { status: 'pending', template_id: 'taskbook-generation', template_version: '1', template_digest: 'fixture-project-digest', terminal_node_id: 'taskbook' },
  });
  delete researchCase.source_analysis;
  project.version += 1;
  const openSourceCards = async () => {
    await page.reload();
    await openSourceStep();
    await panel.waitFor();
    await page.getByRole('heading', { name: '资料识别与项目信息', level: 1, exact: true }).waitFor();
  };
  await openSourceCards();
  const sourceSection = page.getByRole('region', { name: '编制资料', exact: true });
  const currentCards = sourceSection.locator('.rd-current-files .rd-source-card');
  const sourceLink = name => sourceSection.getByRole('link', { name, exact: true });
  const deleteButton = name => sourceSection.getByRole('button', { name: `删除资料“${name}”`, exact: true });
  const deleteCalls = () => commands.filter(item => item.body.command === 'delete_source');
  assert.equal(await currentCards.count(), 3, 'three current files are presented as cards');
  assert.equal(await sourceSection.getByText('资料记录', { exact: true }).count(), 0, 'the old source-record block is removed');
  const locationNav = page.getByRole('navigation', { name: '当前位置', exact: true });
  assert.equal(await locationNav.count(), 1, 'the page has one current-location navigation');
  assert.equal(await locationNav.evaluate(element => !!element.closest('.rd-topbar')), true, 'current location belongs to the top bar');
  const heading = page.locator('.rd-case-heading');
  assert((await heading.innerText()).includes('已固定的研制任务书生成 · V1'), 'the heading reads the real adoption template_version');
  assert.equal((await page.locator('body').innerText()).includes('Vundefined'), false);
  // Project management actions remain on the overview, not on each case workface.
  const sourceCardsUrl = page.url();
  await locationNav.getByRole('button', { name: project.title, exact: true }).click();
  await page.locator('.rd-project-header').getByRole('button', { name: '刷新', exact: true }).click();
  const refreshNotice = page.getByText('已刷新。未保存的填写继续保留。', { exact: true });
  await refreshNotice.waitFor();
  assert.equal(await page.locator('.rd-notice.rd-banner').filter({ hasText: '已刷新。未保存的填写继续保留。' }).count(), 0, 'refresh success uses a transient message instead of a page banner');
  await refreshNotice.waitFor({ state: 'hidden' });
  await page.goto(sourceCardsUrl);
  await panel.waitFor();
  const longLink = sourceLink(longSourceName);
  const nameCharacters = Array.from(longSourceName);
  assert(nameCharacters.length > 30);
  assert.equal(await longLink.innerText(), nameCharacters.slice(0, 21).join('') + '…' + nameCharacters.slice(-8).join(''), 'long Unicode names keep the first 21 and final 8 characters');
  assert.equal(Array.from(boundarySourceName).length, 30);
  assert.equal(await sourceLink(boundarySourceName).innerText(), boundarySourceName, 'a 30-character name remains complete');
  await longLink.hover();
  const nameTooltip = page.getByRole('tooltip').filter({ hasText: longSourceName });
  await nameTooltip.waitFor();
  assert.equal(await nameTooltip.innerText(), longSourceName, 'hover reveals the complete filename');
  await page.mouse.move(0, 0);
  assert.equal(await currentCards.nth(0).locator('.rd-source-file-icon svg[data-icon="file-word"]').count(), 1);
  assert.equal(await currentCards.nth(1).locator('.rd-source-file-icon svg[data-icon="file-pdf"]').count(), 1);
  assert.equal(await currentCards.nth(2).locator('.rd-source-file-icon svg[data-icon="file-image"]').count(), 1);
  const desktopCards = await currentCards.evaluateAll(elements => elements.map(element => { const box = element.getBoundingClientRect(); return { x: box.x, y: box.y, width: box.width, height: box.height }; }));
  assert(Math.abs(desktopCards[0].y - desktopCards[1].y) <= 1 && desktopCards[1].x > desktopCards[0].x, 'desktop cards use two columns');
  assert(Math.abs(desktopCards[0].x - desktopCards[2].x) <= 1 && desktopCards[2].y >= desktopCards[0].y + desktopCards[0].height, 'a third desktop card starts the next row');
  const desktopGrid = await sourceSection.locator('.rd-current-files .rd-source-file-grid').boundingBox();
  assert(desktopCards[2].width < desktopGrid.width / 2 - 1, 'a short filename keeps its card narrower than half the file grid');
  const cardBackground = await currentCards.nth(2).evaluate(element => getComputedStyle(element).backgroundColor);
  assert(!['transparent', 'rgba(0, 0, 0, 0)', 'rgb(255, 255, 255)'].includes(cardBackground), 'source cards have a visible tinted background');
  if (output) await page.screenshot({ path: join(output, 'source-file-cards-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  const narrowCards = await currentCards.evaluateAll(elements => elements.map(element => { const box = element.getBoundingClientRect(); return { x: box.x, y: box.y, width: box.width, height: box.height }; }));
  const narrowGrid = await sourceSection.locator('.rd-current-files .rd-source-file-grid').boundingBox();
  assert(narrowCards.every(box => Math.abs(box.x - narrowCards[0].x) <= 1 && box.width <= narrowGrid.width + 1), 'narrow cards share a single column without requiring equal widths');
  assert(narrowCards.slice(1).every((box, index) => box.y >= narrowCards[index].y + narrowCards[index].height), 'narrow cards wrap into separate rows');
  assert(await page.locator('.rd-application-shell').evaluate(element => element.scrollWidth <= element.clientWidth + 1), 'file cards do not overflow at 390px');
  if (output) await page.screenshot({ path: join(output, 'source-file-cards-narrow.png') });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const assistantLauncher = page.getByRole('button', { name: '打开小航助手', exact: true });
  assert.equal(await assistantLauncher.evaluate(element => !!element.closest('.rd-journey-heading-actions')), false, 'the source page has no assistant button in the heading');
  assert.equal(await assistantLauncher.count(), 1, 'the character is the single assistant entry');
  assert.equal(await page.locator('.rd-floating-launcher .rd-floating-figure').isVisible(), true, 'the source page displays the floating character');
  const sourceAnalyze = panel.getByRole('button', { name: '分析上传资料', exact: true });
  await sourceAnalyze.click({ trial: true });
  assert.equal(await sourceAnalyze.evaluate(element => { const box = element.getBoundingClientRect(), hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2); return hit === element || element.contains(hit); }), true, 'the closed assistant does not cover the analysis action');
  await assistantLauncher.click();
  const assistantDialog = page.getByRole('dialog', { name: `${researchCase.title} · 小航助手`, exact: true });
  await assistantDialog.waitFor();
  await assistantDialog.getByRole('textbox', { name: '询问当前案例', exact: true }).fill('布局验收草稿，仅保留，不发送。');
  await assistantDialog.getByRole('button', { name: '收起小航助手', exact: true }).click();
  await assistantDialog.waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: '成果概览', exact: true }).click();
  assert.equal(await page.locator('.rd-floating-launcher').isVisible(), true, 'other workspaces retain the floating assistant launcher');
  await assistantLauncher.click();
  await assistantDialog.waitFor();
  assert.equal(await assistantDialog.getByRole('textbox', { name: '询问当前案例', exact: true }).inputValue(), '布局验收草稿，仅保留，不发送。', 'switching workspaces preserves the character assistant conversation draft');
  await assistantDialog.getByRole('textbox', { name: '询问当前案例', exact: true }).fill('');
  await assistantDialog.getByRole('button', { name: '收起小航助手', exact: true }).click();
  await assistantDialog.waitFor({ state: 'hidden' });
  await openSourceStep();
  await panel.waitFor();
  checks.push('真实模板版本、唯一顶栏位置导航、Unicode文件卡与类型图标、桌面两列和390px单列；小航统一由悬浮小人触发，标题无助手按钮，跨工作面保留草稿');

  const deleteDialog = page.getByRole('dialog', { name: '删除资料', exact: true });
  const referenceName = cardSources[2].name;
  const deletionsBeforeCancel = deleteCalls().length;
  await deleteButton(referenceName).click();
  await deleteDialog.waitFor();
  await deleteDialog.getByText(`删除“${referenceName}”？`, { exact: true }).waitFor();
  assert.equal(await deleteDialog.getByRole('button', { name: '删除资料', exact: true }).evaluate(element => element.classList.contains('ant-btn-dangerous')), true, 'destructive confirmation uses the danger style');
  await deleteDialog.getByRole('button', { name: '取消', exact: true }).click();
  await deleteDialog.waitFor({ state: 'hidden' });
  assert.equal(deleteCalls().length, deletionsBeforeCancel, 'cancelling deletion sends no command');
  assert.equal(await sourceLink(referenceName).count(), 1);

  failDelete = true;
  await deleteButton(referenceName).click();
  const deletionVersion = project.version;
  await deleteDialog.getByRole('button', { name: '删除资料', exact: true }).evaluate(element => { element.click(); element.click(); });
  await deleteDialog.getByRole('alert').filter({ hasText: '删除资料服务暂不可用' }).waitFor();
  assert.equal(deleteCalls().length, deletionsBeforeCancel + 1, 'repeated confirmation submits one deletion');
  assert.equal(project.version, deletionVersion, 'a failed deletion leaves the project version unchanged');
  assert.equal(await sourceLink(referenceName).count(), 1, 'a failed deletion keeps the source card');
  assert.equal(await deleteDialog.getByRole('button', { name: '删除资料', exact: true }).isEnabled(), true, 'failed deletion is retryable in place');
  if (output) await page.screenshot({ path: join(output, 'source-delete-failure.png') });
  await deleteDialog.getByRole('button', { name: '删除资料', exact: true }).evaluate(element => { element.click(); element.click(); });
  await deleteDialog.waitFor({ state: 'hidden' });
  assert.equal(deleteCalls().length, deletionsBeforeCancel + 2, 'repeated retry submits one deletion');
  assert.equal(deleteCalls().at(-1).key, deleteCalls().at(-2).key, 'the failed command retry preserves its idempotency key');
  assert.equal(await sourceLink(referenceName).count(), 0, 'successful deletion removes the source card');
  assert.equal(project.cases[0].sources.some(item => item.id === 'card-reference'), false);
  checks.push('删除取消不提交、失败保留资料并就地重试、危险确认和连点去重');

  const beforeBlockedDelete = deleteCalls().length;
  researchCase.workpackages = [{ id: 'fixture-running', definition_id: 'taskbook', title: '运行中工作包夹具', stage: 'input', status: 'running', plan_revision: 1, nodes: [], artifacts: [], obligations: [], blocked_reasons: [] }];
  project.version += 1;
  await openSourceCards();
  assert.equal(await deleteButton(longSourceName).isDisabled(), true, 'running workpackages prevent source deletion');
  await deleteButton(longSourceName).evaluate(element => element.click());
  assert.equal(await deleteDialog.count(), 0);
  assert.equal(deleteCalls().length, beforeBlockedDelete);
  researchCase.workpackages = []; researchCase.status = 'completed'; project.version += 1;
  await openSourceCards();
  assert.equal(await deleteButton(longSourceName).isDisabled(), true, 'a completed case prevents source deletion');
  await deleteButton(longSourceName).evaluate(element => element.click());
  assert.equal(await deleteDialog.count(), 0);
  assert.equal(deleteCalls().length, beforeBlockedDelete);
  researchCase.status = 'draft'; project.version += 1;
  await openSourceCards();
  assert.equal(await panel.getByRole('button', { name: '分析上传资料', exact: true }).isEnabled(), true);
  await deleteButton(longSourceName).click();
  await deleteDialog.getByText('该文件将不再用于本次分析，需重新分析并确认资料。', { exact: false }).waitFor();
  await deleteDialog.getByRole('button', { name: '删除资料', exact: true }).click();
  await deleteDialog.waitFor({ state: 'hidden' });
  assert.equal(await sourceLink(longSourceName).count(), 0);
  assert.equal(project.cases[0].source_selection.tech, undefined, 'deleting the current technical source clears the selection');
  assert.equal(project.cases[0].source_selection.spec, 'card-spec', 'other current source selections are retained');
  assert.equal(project.cases[0].sources.some(item => item.id === 'card-history-tech'), true, 'historical technical input remains available without being selected');
  assert.equal(await panel.getByRole('button', { name: '分析上传资料', exact: true }).isDisabled(), true, 'history does not silently replace a deleted current technical input');
  const analysesAfterDelete = analysisRequests.length;
  await panel.getByRole('button', { name: '分析上传资料', exact: true }).evaluate(element => element.click());
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(analysisRequests.length, analysesAfterDelete, 'a deleted current technical source cannot invoke analysis');
  await sourceSection.locator('.rd-source-history > summary').click();
  await sourceLink('上一版技术资料.doc').waitFor();
  assert.equal(await sourceSection.getByRole('button', { name: '采用此版本', exact: true }).isEnabled(), true, 'choosing a historical input remains an explicit action');
  checks.push('运行中与完成态禁止删除；删除当前技术资料清选择，历史不自动回退且分析禁用');

  project.cases[0].sources = []; project.cases[0].source_selection = {}; project.cases[0].requirements = []; delete project.cases[0].source_analysis;
  await page.reload();
  await openSourceStep();
  assert.equal(await panel.getByRole('button', { name: '分析上传资料', exact: true }).isDisabled(), true, 'empty sources cannot invoke the model');
  researchCase.parameter_facts = {
    product_type: { field: 'product_type', value: researchCase.context.product_type, status: 'conflict', evidence_status: 'current', source_refs: [], decision_ref: null, rule_refs: [], reason: '隔离冲突：资料产品类型与创建项目时的分类不一致。', candidates: [] },
    product_domain: { field: 'product_domain', value: researchCase.context.product_domain, status: 'conflict', evidence_status: 'current', source_refs: [], decision_ref: null, rule_refs: [], reason: '隔离冲突：资料质量体系与项目预置值不一致。', candidates: [] },
  };
  const commandsBeforeConflict = commands.length;
  await page.reload(); await openSourceStep();
  await panel.getByText(/隔离冲突：资料产品类型与创建项目时的分类不一致。/).waitFor();
  await panel.getByText(/隔离冲突：资料质量体系与项目预置值不一致。/).waitFor();
  assert.equal(await panel.locator('dt').count(), 2);
  assert.equal(await panel.locator('dt').filter({ hasText: /^(产品类型|质量管理体系分类|封面阶段|组织范围)$/ }).count(), 0);
  assert.equal(commands.length, commandsBeforeConflict, 'displaying classification conflicts never changes project context');
  if (output) await page.screenshot({ path: join(output, 'project-classification-conflicts.png') });
  checks.push('项目四项预置参数不重复展示，保留研制流程、系列与来源刷新；项目分类冲突仍明确提示且不自动改值');
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpected, [], 'all API mutations use explicit fixtures');
  if (output) await writeFile(join(output, 'receipt.json'), JSON.stringify({ legacySourceAnalysis: 'passed', checks, pageErrors: errors, unexpectedRequests: unexpected, fixtureCommands: commands.length, fixtureSourceDeletes: deleteCalls().length, fixtureAnalyses: analysisRequests.length, realApiRequests: 0 }, null, 2));
  console.log(JSON.stringify({ passed: true, legacySourceAnalysis: 'passed', checks, fixtureCommands: commands.length, fixtureSourceDeletes: deleteCalls().length, fixtureAnalyses: analysisRequests.length, pageErrors: errors, realApiRequests: 0, screenshots: output }));
} finally { await browser.close(); }
