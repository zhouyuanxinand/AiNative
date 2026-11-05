/** Read-only evidence locations: real UI, isolated API data, no platform/model writes. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'runtime/rd-evidence-locations-browser';
await mkdir(output, { recursive: true });
const stamp = '2026-11-05T02:00:00Z', actor = 'evidence-reader';
const sources = [
  { id: 'tech', role: 'tech', name: '液冷组件需求.doc', version: 3 },
  { id: 'spec', role: 'spec', name: '公司组件规范.docx', version: 2 },
  { id: 'text', role: 'reference', name: '补充要求.txt', version: 1 },
  { id: 'unreadable', role: 'reference', name: '暂不可读资料.docx', version: 1 },
].map(source => ({ ...source, sha256: 'sha-' + source.id, size: 2048, created_at: stamp }));
const candidates = [
  ['工作温度', 'tech', '工作温度 5℃～70℃。'],
  ['工作压力', 'spec', '工作压力不得小于 0.3 MPa。'],
  ['运输要求', 'text', '运输中保持干燥。'],
  ['重复原文', 'tech', '产品表面无裂纹。'],
  ['未匹配原文', 'tech', '本次摘录未在原文件中找到。'],
  ['读取受限', 'unreadable', '待核实的原始要求。'],
  ['同文不同来源', 'spec', '工作温度 5℃～70℃。'],
  ['同源不同原文', 'tech', '贮存温度 -40℃～85℃。'],
].map(([title, sourceId, content]) => ({ title, content, source_ids: [sourceId], evidence: [{ source_id: sourceId, quote: content }] }));
candidates[0].recommendation = { text: '明确验收工况', proposed_value: '额定工况下核验工作温度。', evidence: [{ source_id: 'spec', quote: '额定工况下核验工作温度。' }] };
const contextFields = { product_type: 'liquid_cooling_pipeline', product_domain: 'military', development_process: '', cover_phase: 'F', product_series: 'YLZJ', organization_scope: 'non_central_research' };
const analysis = { id: 'location-analysis', status: 'proposed', input_revision: 2, created_at: stamp, context: {}, source_hashes: Object.fromEntries(sources.map(source => [source.id, source.sha256])), model_selection: { provider: 'fixture', name: 'fixture-model', id: '1' }, warnings: [], requirements: candidates };
const researchCase = { id: 'location-case', title: '定位审阅流程', scenario_id: 'taskbook', stage: 'input', status: 'draft', input_revision: 2, context: contextFields, model_selection: { provider: '', name: '', id: '' }, source_selection: { tech: 'tech', spec: 'spec' }, sources, requirements: [], source_analysis: analysis, product_route: null, composition_route: null, decisions: [], workpackages: [] };
// Deliberately reuse source IDs and quote text. They must still resolve within the selected case.
const otherCase = { ...structuredClone(researchCase), id: 'other-location-case', title: '另一条定位流程', sources: sources.map(source => ({ ...source, name: '另一流程-' + source.name, version: source.version + 1 })), source_analysis: { ...structuredClone(analysis), id: 'other-analysis' } };
const project = { id: 'location-project', title: '原文定位验证项目', owner_id: actor, members: [], events: [], version: 1, created_at: stamp, updated_at: stamp, customer_name: '隔离测试客户', product_name: '液冷管路', brief: '只读定位验证', cases: [researchCase, otherCase] };
const catalog = { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书' }], actions: [], workpackage_definitions: [] };
const ids = [['B0007'], ['B0012-R002'], ['L0001'], ['B0020', 'B0031'], [], [], ['B0042'], ['B0021']];
const labels = [['第 7 段'], ['第 12 块 · 表格第 2 行'], ['第 1 行'], ['第 20 段', '第 31 段'], [], [], ['第 42 段'], ['第 21 段']];
function locationsFor(rc) {
  const entries = rc.source_analysis.requirements.map((candidate, index) => {
    const source = [...rc.sources, ...(rc.deleted_sources ?? [])].find(source => source.id === candidate.source_ids[0]);
    return { source_id: source.id, quote: candidate.content, source_name: source.name, source_version: source.version, source_sha256: source.sha256, analysis_id: rc.source_analysis.id,
      source_state: source.deleted_at ? 'deleted' : 'current', normalized_sha256: 'current-conversion',
      status: index === 3 ? 'ambiguous' : index === 4 ? 'not_found' : index === 5 ? 'unavailable' : 'located',
      locations: (rc.id === otherCase.id && index === 0 ? ['B0999'] : ids[index] ?? ['B0088']).map((id, i) => ({ id, label: labels[index]?.[i] ?? '第 88 段' })),
      coordinate_space: source.id === 'tech' ? 'normalized' : source.id === 'text' ? 'text' : 'original',
      reason: index === 4 ? '当前来源没有精确匹配的原文。' : index === 5 ? '来源文件暂时无法读取。' : undefined };
  });
  entries.push({ source_id: 'spec', quote: candidates[0].recommendation.evidence[0].quote, analysis_id: rc.source_analysis.id, source_name: rc.sources[1].name, source_version: rc.sources[1].version, status: 'located', locations: [{ id: 'B0050', label: '第 50 段' }] });
  for (const [field, provenance] of Object.entries(rc.context_provenance ?? {})) {
    entries.push({ source_id: 'tech', quote: candidates[0].content, analysis_id: provenance.analysis_id ?? null,
      source_name: rc.sources[0].name, source_version: rc.sources[0].version, source_sha256: rc.sources[0].sha256,
      source_state: 'current', coordinate_space: 'normalized', normalized_sha256: 'old-conversion',
      status: 'located', locations: [{ id: field === 'product_series' ? 'B0090' : 'B0091', label: field === 'product_series' ? '第 90 段' : '第 91 段' }] });
  }
  // Responses need not have the same order as displayed evidence.
  return entries.reverse();
}
const checks = [], requests = [], unexpected = [], faults = [];
const cases = ['main-and-fullscreen', 'retry', 'case-isolation', 'analysis-isolation-and-deleted-source', 'preview-retry', 'preview-stale', 'preview-unavailable', 'preview-mobile', 'preview-cancel', 'preview-history-navigation'];
const selected = process.env.TEST_CASE ? [process.env.TEST_CASE] : cases;
assert(selected.every(name => cases.includes(name)), 'TEST_CASE must identify a test in this file');

async function openOriginal(page, link, sourceId, caseId = researchCase.id) {
  const expected = `/api/rd/projects/${project.id}/cases/${caseId}/sources/${sourceId}`;
  assert.equal(await link.getAttribute('href'), expected);
  assert.equal(await link.getAttribute('target'), '_blank');
  const popupEvent = page.waitForEvent('popup');
  await link.click();
  const popup = await popupEvent;
  await popup.waitForLoadState('domcontentloaded');
  assert.equal(new URL(popup.url()).pathname, expected, 'original-file access stays within the selected project and case');
  await popup.getByText('只读原件夹具', { exact: true }).waitFor();
  await popup.close();
}
async function openPreview(page, trigger, sourceId, caseId = researchCase.id) {
  await trigger.scrollIntoViewIfNeeded();
  const ancestorScroll = () => trigger.evaluate(element => {
    const values = [];
    for (let parent = element.parentElement; parent; parent = parent.parentElement) values.push(parent.scrollTop);
    return values;
  });
  const before = await ancestorScroll();
  const anchor = (await trigger.innerText()).replace('↗', '').trim();
  await trigger.click();
  const preview = page.getByRole('dialog', { name: '原文预览', exact: true });
  await preview.waitFor();
  const body = preview.getByRole('region', { name: '原文件正文', exact: true });
  await body.waitFor();
  const selected = body.locator(`[data-evidence-anchor="${anchor}"]`);
  assert(await selected.locator('mark').count() > 0, 'the requested original quote is highlighted');
  assert.equal(await selected.getAttribute('class'), 'rd-evidence-preview-block is-selected');
  const bounds = await selected.boundingBox(), viewport = await body.boundingBox();
  assert(bounds.y >= viewport.y && bounds.y < viewport.y + viewport.height, 'chosen location is scrolled into the preview viewport');
  assert.deepEqual(await ancestorScroll(), before, 'opening and anchoring the preview preserves source-page scrolling');
  const choices = preview.getByRole('navigation', { name: '原文匹配位置', exact: true }).getByRole('button');
  if (await choices.count() > 1) {
    const next = choices.first();
    await next.click();
    const nextAnchor = await next.innerText();
    assert.equal(await body.locator(`[data-evidence-anchor="${nextAnchor}"]`).getAttribute('class'), 'rd-evidence-preview-block is-selected');
    assert.equal(await next.getAttribute('aria-current'), 'location');
  }
  await page.screenshot({ path: join(output, `preview-${caseId}-${anchor}-${page.viewportSize().width}.png`) });
  await openOriginal(page, preview.getByRole('link', { name: '下载原文件 ↗', exact: true }), sourceId, caseId);
  await preview.getByRole('button', { name: '关闭预览', exact: true }).click();
  await preview.waitFor({ state: 'hidden' });
  await page.waitForFunction(label => document.activeElement?.getAttribute('aria-label') === label, await trigger.getAttribute('aria-label'));
  assert.deepEqual(await ancestorScroll(), before, 'closing restores source-page scroll and focus');
}
async function openProof(row) {
  const proof = row.locator('details.rd-req-source').filter({ has: row.page().getByText('核对来源原文', { exact: true }) });
  if (!(await proof.getAttribute('open'))) {
    if (!(await proof.evaluate(element => element.open))) await proof.locator('summary').click();
  }
  return proof;
}

try {
  for (const testCase of selected) {
    const fixtureProject = structuredClone(project);
    if (testCase === 'analysis-isolation-and-deleted-source') {
      const current = fixtureProject.cases[0];
      current.context.development_process = '改型II';
      current.context_provenance = {
        product_series: { kind: 'source_analysis', analysis_id: 'context-analysis-old', evidence: structuredClone(candidates[0].evidence) },
        development_process: { kind: 'source_analysis', analysis_id: null, evidence: structuredClone(candidates[0].evidence) },
      };
      current.deleted_sources = [{ id: 'deleted', role: 'reference', name: '已移除的旧版资料.docx', version: 1, sha256: 'deleted-source', deleted_at: stamp }];
      current.source_analysis.requirements.push({ title: '已删除来源追溯', content: '保留已采用的旧版要求。', source_ids: ['deleted'], evidence: [{ source_id: 'deleted', quote: '保留已采用的旧版要求。' }] });
    }
    const context = await browser.newContext({ viewport: testCase === 'preview-mobile' ? { width: 390, height: 844 } : { width: 1500, height: 1000 } });
    const page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on('pageerror', error => faults.push(error.message));
    let failLocations = testCase === 'retry';
    let failPreview = testCase === 'preview-retry' || testCase === 'preview-stale';
    let releasePreview;
    const holdPreview = testCase === 'preview-cancel' ? new Promise(resolve => { releasePreview = resolve; }) : Promise.resolve();
    let releaseLocations;
    const holdLocations = testCase === 'main-and-fullscreen' ? new Promise(resolve => { releaseLocations = resolve; }) : Promise.resolve();
    await context.route('**/api/**', async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      if (!path.startsWith('/api/')) return route.continue();
      requests.push({ testCase, method: request.method(), path });
      if (request.method() === 'GET') {
        if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
        if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: actor, local_mode: true } });
        if (path === '/api/rd/governance/session') return route.fulfill({ json: { can_edit_workflows: false, can_publish_workflows: false, can_prepare_templates: false, can_review_templates: false, can_publish_templates: false } });
        if (path === '/api/rd/workflow-templates') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 5, total_pages: 1 } });
        if (path === '/api/rd/catalog') return route.fulfill({ json: catalog });
        if (path === '/api/rd/catalog/items') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 5, total_pages: 1 } });
        if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [fixtureProject] } });
        if (path === '/api/rd/projects/' + project.id) return route.fulfill({ json: fixtureProject });
        if (path === '/api/models') return route.fulfill({ json: { success: true, models: [{ provider: 'fixture', name: 'fixture-model', id: '1' }] } });
        if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: 'liquid_cooling_pipeline', label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }] }] } });
        if (path === '/api/rd/assistant/weather') return route.fulfill({ json: { status: 'unavailable', notice: '定位测试不读取天气。' } });
        if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: 'input', project_version: 1, input_revision: 2 } } });
        for (const rc of fixtureProject.cases) {
          const prefix = `/api/rd/projects/${project.id}/cases/${rc.id}`;
          if (path === prefix + '/evidence-locations') {
            await holdLocations;
            return failLocations ? route.fulfill({ status: 503, json: { error: '定位服务暂不可用，请重试。' } }) : route.fulfill({ json: { items: locationsFor(rc) } });
          }
          if (path === prefix + '/evidence-preview') {
            await holdPreview;
            if (failPreview) return route.fulfill({ status: testCase === 'preview-stale' ? 409 : 503, json: { error: testCase === 'preview-stale' ? '资料版本已变化，请刷新定位后重新打开。' : '预览暂时不可用，请重试。' } });
            const item = locationsFor(rc).find(item => item.source_id === url.searchParams.get('source_id') && item.quote === url.searchParams.get('quote') && (item.analysis_id ?? null) === url.searchParams.get('analysis_id'));
            assert(item, 'preview requires an exact persisted fixture reference');
            assert.equal(url.searchParams.get('source_sha256'), item.source_sha256 || '');
            assert.equal(url.searchParams.get('normalized_sha256'), item.normalized_sha256 ?? null);
            const filler = Array.from({ length: 35 }, (_, index) => ({ id: `PRE${index}`, label: `前文 ${index}`, text: `前文说明 ${index}`, segments: [{ text: `前文说明 ${index}`, highlighted: false }] }));
            const blocks = item.locations.map(point => ({ ...point, text: item.quote, segments: [{ text: item.quote, highlighted: true }] }));
            if (testCase === 'preview-unavailable') return route.fulfill({ json: { ...item, status: 'unavailable', selected_location_id: null, blocks: [], reason: '此分析未保留可定位的转换副本' } });
            return route.fulfill({ json: { ...item, selected_location_id: url.searchParams.get('location_id'), blocks: [...filler, ...blocks] } });
          }
          if (path.startsWith(prefix + '/sources/') && rc.sources.some(source => path === prefix + '/sources/' + source.id)) return route.fulfill({ contentType: 'text/html; charset=utf-8', body: '<!doctype html><meta charset="utf-8"><p>只读原件夹具</p>' });
        }
      }
      unexpected.push({ method: request.method(), path });
      return route.fulfill({ status: 500, json: { error: '只读定位测试不允许此请求：' + path } });
    });
    await page.goto(`${base}/?rd_view=projects&project=${project.id}&case=${researchCase.id}&case_view=current&step=sources`);
    const panel = page.getByRole('region', { name: '原文需求对照', exact: true });
    await panel.waitFor();
    const row = index => panel.locator(`tr[data-row-key="${index + 1}"]`);
    const first = await openProof(row(0));
    if (testCase === 'main-and-fullscreen') {
      await first.getByText('正在定位…', { exact: true }).waitFor();
      assert.equal(await first.getByRole('button', { name: /定位 B/ }).count(), 0, 'loading never invents a document position');
      releaseLocations();
      for (let i = 0; i < candidates.length; i++) {
        const proof = await openProof(row(i));
        for (const id of ids[i]) {
          const link = proof.getByRole('button', { name: `预览原文，定位 ${id}`, exact: true });
          await link.waitFor();
          assert.equal((await link.innerText()).replace('↗', '').trim(), id);
          assert((await link.getAttribute('title')).startsWith(`${sources.find(source => source.id === candidates[i].source_ids[0]).name} · V${sources.find(source => source.id === candidates[i].source_ids[0]).version} · `), 'file and source version remain in the tooltip');
        }
        assert.equal(await proof.locator('blockquote').innerText(), candidates[i].content, 'the quoted original remains unchanged');
      }
      assert.match(await first.getByRole('button', { name: '预览原文，定位 B0007', exact: true }).getAttribute('title'), /转换文档定位$/);
      await row(3).getByText('多处匹配', { exact: true }).waitFor();
      assert.equal(await row(3).getByRole('button', { name: /预览原文，定位/ }).count(), 2, 'all ambiguous matching locations remain visible');
      await row(4).getByText('未找到原文位置', { exact: true }).waitFor();
      await row(5).getByText('暂无法定位', { exact: true }).waitFor();
      for (const index of [4, 5]) assert.equal(await row(index).getByRole('button', { name: /预览原文，定位/ }).count(), 0, 'unmatched or unavailable references do not display fake IDs');
      await row(0).getByText('建议依据', { exact: true }).click();
      await row(0).getByRole('button', { name: '预览原文，定位 B0050', exact: true }).waitFor();
      await openPreview(page, first.getByRole('button', { name: '预览原文，定位 B0007', exact: true }), 'tech');
      await openPreview(page, row(3).getByRole('button', { name: '预览原文，定位 B0031', exact: true }), 'tech');
      await openOriginal(page, row(4).getByRole('link', { name: '下载原文件 ↗', exact: true }), 'tech');
      await page.screenshot({ path: join(output, 'main-table-locations.png') });
      checks.push('Main table: paragraph/table-row/text-line IDs, source+quote exact mapping, filename/version tooltip, converted-document label, ambiguous/unmatched/unavailable states and original-file access');
      const callsBeforeReview = requests.filter(request => request.testCase === testCase && request.path.endsWith('/evidence-locations')).length;
      await page.getByRole('button', { name: '全屏审阅', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: '需求清单审阅', exact: true });
      await dialog.waitFor();
      for (const index of [0, 1, 2, 3, 4, 5]) {
        const fullRow = dialog.locator(`tr[data-row-key="${index + 1}"]`), proof = await openProof(fullRow);
        for (const id of ids[index]) await proof.getByRole('button', { name: `预览原文，定位 ${id}`, exact: true }).waitFor();
        if (index === 4) await proof.getByText('未找到原文位置', { exact: true }).waitFor();
        if (index === 5) await proof.getByText('暂无法定位', { exact: true }).waitFor();
      }
      assert.equal(requests.filter(request => request.testCase === testCase && request.path.endsWith('/evidence-locations')).length, callsBeforeReview, 'fullscreen shares the authorized read without fetching per cell');
      await openPreview(page, dialog.getByRole('button', { name: '预览原文，定位 B0007', exact: true }), 'tech');
      await dialog.getByLabel('搜索需求').fill('工作温度');
      await dialog.getByRole('button', { name: '预览原文，定位 B0007', exact: true }).waitFor();
      await page.screenshot({ path: join(output, 'fullscreen-locations.png') });
      await dialog.getByRole('button', { name: '退出全屏', exact: true }).click();
      await dialog.waitFor({ state: 'hidden' });
      await first.getByRole('button', { name: '预览原文，定位 B0007', exact: true }).waitFor();
      checks.push('Fullscreen: same source IDs/statuses, searchable review, shared read and return to main table');
    } else if (testCase === 'retry') {
      await first.getByText('定位读取失败', { exact: true }).waitFor();
      await openOriginal(page, first.getByRole('link', { name: '下载原文件 ↗', exact: true }), 'tech');
      assert.equal(await first.getByRole('button', { name: /定位 B/ }).count(), 0);
      await page.screenshot({ path: join(output, 'locations-read-failure.png') });
      const before = requests.filter(request => request.testCase === testCase && request.path.endsWith('/evidence-locations')).length;
      failLocations = false;
      await first.getByRole('button', { name: '重试定位', exact: true }).click();
      await first.getByRole('button', { name: '预览原文，定位 B0007', exact: true }).waitFor();
      assert.equal(await first.getByRole('button', { name: '重试定位', exact: true }).count(), 0);
      assert.equal(requests.filter(request => request.testCase === testCase && request.path.endsWith('/evidence-locations')).length, before + 1);
      assert.equal(await first.locator('blockquote').innerText(), candidates[0].content);
      checks.push('503 failure: explicit feedback, original still opens, one read-only retry restores IDs without altering source text');
    } else if (testCase === 'case-isolation') {
      await first.getByRole('button', { name: '预览原文，定位 B0007', exact: true }).waitFor();
      await page.getByRole('navigation', { name: '当前位置', exact: true }).getByRole('button', { name: project.title, exact: true }).click();
      await page.getByRole('article', { name: otherCase.title, exact: true }).getByRole('button', { name: '继续办理', exact: true }).click();
      await page.waitForURL(url => url.searchParams.get('case') === otherCase.id || url.pathname === `/projects/${project.id}/flows/${otherCase.id}/materials`);
      await panel.waitFor();
      const otherProof = await openProof(row(0));
      const otherLink = otherProof.getByRole('button', { name: '预览原文，定位 B0999', exact: true });
      await otherLink.waitFor();
      assert.equal(await otherProof.getByRole('button', { name: '预览原文，定位 B0007', exact: true }).count(), 0);
      assert((await otherLink.getAttribute('title')).startsWith('另一流程-液冷组件需求.doc · V4 · '));
      await openPreview(page, otherLink, 'tech', otherCase.id);
      const caseRequests = requests.filter(request => request.testCase === testCase && request.path.endsWith('/evidence-locations'));
      assert(caseRequests.some(request => request.path.includes('/cases/' + researchCase.id + '/')));
      assert(caseRequests.some(request => request.path.includes('/cases/' + otherCase.id + '/')));
      checks.push('Real project navigation: reused source ID/quote resolves against the other case only, including tooltip version and original-file path');
    } else if (testCase === 'analysis-isolation-and-deleted-source') {
      await first.getByRole('button', { name: '预览原文，定位 B0007', exact: true }).waitFor();
      const provenance = label => page.locator('.rd-analysis-context-item').filter({ has: page.locator('dt').filter({ hasText: label }) });
      for (const [label, id] of [['产品系列', 'B0090'], ['研制流程', 'B0091']]) {
        const entry = provenance(label);
        await entry.getByText('查看原文依据', { exact: true }).click();
        await entry.getByRole('button', { name: `预览原文，定位 ${id}`, exact: true }).waitFor();
        assert.equal(await entry.getByRole('button', { name: '预览原文，定位 B0007', exact: true }).count(), 0, 'old context evidence must not inherit the current analysis conversion coordinates');
        assert.equal(await entry.locator('blockquote').innerText(), candidates[0].content, 'identical quote text can belong to a distinct analysis');
      }
      assert.equal(await first.getByRole('button', { name: /定位 B009[01]/ }).count(), 0, 'current requirements must not inherit old/null analysis coordinates');
      const deleted = await openProof(row(8));
      const deletedLink = deleted.getByRole('button', { name: '预览原文，定位 B0088', exact: true });
      await deletedLink.waitFor();
      await deleted.getByText('已删除来源 · 仅供追溯', { exact: true }).waitFor();
      assert.equal(await deletedLink.getAttribute('title'), '已移除的旧版资料.docx · V1 · 第 88 段');
      assert.equal(await page.locator('.rd-current-files').getByText('已移除的旧版资料.docx', { exact: true }).count(), 0, 'a deleted evidence source does not become a current input');
      assert.equal(await deleted.locator('blockquote').innerText(), '保留已采用的旧版要求。');
      await page.screenshot({ path: join(output, 'analysis-isolation-and-deleted-source.png') });
      await page.getByRole('button', { name: '全屏审阅', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: '需求清单审阅', exact: true });
      await dialog.waitFor();
      const currentProof = await openProof(dialog.locator('tr[data-row-key="1"]'));
      await currentProof.getByRole('button', { name: '预览原文，定位 B0007', exact: true }).waitFor();
      assert.equal(await dialog.getByRole('button', { name: /定位 B009[01]/ }).count(), 0, 'fullscreen does not borrow coordinates from context evidence');
      const deletedProof = await openProof(dialog.locator('tr[data-row-key="9"]'));
      await deletedProof.getByText('已删除来源 · 仅供追溯', { exact: true }).waitFor();
      await deletedProof.getByRole('button', { name: '预览原文，定位 B0088', exact: true }).waitFor();
      checks.push('Analysis isolation: current, old and null analysis IDs resolve identical source/quote to separate coordinates; deleted source stays traceable with explicit state in main and fullscreen review');
    } else if (testCase === 'preview-history-navigation') {
      await page.getByRole('button', { name: '成果概览', exact: true }).click();
      await page.getByRole('heading', { name: '当前成果', exact: true }).waitFor();
      const destination = page.url();
      await page.getByRole('button', { name: '返回办理', exact: true }).click();
      await panel.waitFor();
      const proof = await openProof(row(0));
      const trigger = proof.getByRole('button', { name: '预览原文，定位 B0007', exact: true });
      await trigger.click();
      const preview = page.getByRole('dialog', { name: '原文预览', exact: true });
      await preview.getByRole('region', { name: '原文件正文', exact: true }).waitFor();
      await trigger.evaluate(element => {
        window.evidenceTriggerFocusAttempts = [];
        const original = element.focus;
        element.focus = function(options) {
          window.evidenceTriggerFocusAttempts.push({ hidden: Boolean(this.closest('[hidden], [inert]')), hasRect: this.getClientRects().length > 0 });
          original.call(this, options);
        };
      });
      await page.goBack();
      await page.waitForURL(destination);
      await page.getByRole('heading', { name: '当前成果', exact: true }).waitFor();
      await preview.waitFor({ state: 'hidden' });
      assert.deepEqual(await page.evaluate(() => window.evidenceTriggerFocusAttempts), [], 'history navigation never restores focus to a source-page trigger');
      assert.equal(await page.evaluate(() => Boolean(document.activeElement?.closest('[hidden], [inert]'))), false, 'focus remains on the destination surface');
      await page.goForward();
      await panel.waitFor();
      assert.equal(await preview.count(), 0, 'returning to sources never revives a closed preview or old selected anchor');
      await openPreview(page, trigger, 'tech');
      checks.push('Browser Back closes the body-portal preview without restoring source focus; Forward retains evidence and opens a fresh anchored preview');
    } else {
      const trigger = first.getByRole('button', { name: '预览原文，定位 B0007', exact: true });
      await trigger.waitFor();
      if (testCase === 'preview-mobile') {
        await openPreview(page, trigger, 'tech');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false, 'narrow page never overflows horizontally');
        checks.push('390px preview: original anchor and highlight, usable own scroll, download, close and focus recovery');
      } else {
        await trigger.click();
        const preview = page.getByRole('dialog', { name: '原文预览', exact: true });
        await preview.waitFor();
        if (testCase === 'preview-cancel') {
          await preview.getByRole('status').getByText('正在读取原文预览…', { exact: true }).waitFor();
          await page.keyboard.press('Escape');
          await preview.waitFor({ state: 'hidden' });
          releasePreview();
          assert.equal(await page.getByRole('region', { name: '原文件正文', exact: true }).count(), 0, 'cancelled reads cannot reopen preview or expose stale blocks');
        } else if (testCase === 'preview-retry') {
          await preview.getByRole('alert').getByText('预览暂时不可用，请重试。', { exact: true }).waitFor();
          await openOriginal(page, preview.getByRole('link', { name: '下载原文件 ↗', exact: true }), 'tech');
          failPreview = false;
          await preview.getByRole('button', { name: '重试预览', exact: true }).click();
          await preview.getByRole('region', { name: '原文件正文', exact: true }).locator('[data-evidence-anchor="B0007"] mark').waitFor();
          await preview.getByRole('button', { name: '关闭预览', exact: true }).click();
          await preview.waitFor({ state: 'hidden' });
        } else if (testCase === 'preview-stale') {
          await preview.getByRole('alert').getByText('资料版本已变化，请刷新定位后重新打开。', { exact: true }).waitFor();
          const before = requests.filter(request => request.testCase === testCase && request.path.endsWith('/evidence-locations')).length;
          failPreview = false;
          await preview.getByRole('button', { name: '刷新定位', exact: true }).click();
          await preview.waitFor({ state: 'hidden' });
          await trigger.waitFor();
          assert.equal(requests.filter(request => request.testCase === testCase && request.path.endsWith('/evidence-locations')).length, before + 1);
          await openPreview(page, trigger, 'tech');
        } else {
          await preview.getByRole('status').getByText(/此分析未保留可定位的转换副本/).waitFor();
          await preview.getByText(/B0007（第 7 段）/).waitFor();
          assert.equal(await preview.getByRole('region', { name: '原文件正文', exact: true }).count(), 0);
          await openOriginal(page, preview.getByRole('link', { name: '下载原文件 ↗', exact: true }), 'tech');
          await preview.getByRole('button', { name: '关闭预览', exact: true }).click();
          await preview.waitFor({ state: 'hidden' });
        }
        assert.equal(await first.locator('blockquote').innerText(), candidates[0].content, 'preview and recovery never modify the saved quote');
        checks.push(`${testCase}: explicit state, read-only recovery and unchanged evidence`);
      }
    }
    await context.close();
  }
  assert.deepEqual(unexpected, [], 'no undeclared API requests or writes may reach the real platform');
  assert.deepEqual(faults, [], 'no page runtime errors');
  assert(requests.every(request => request.method === 'GET'), 'viewing/retrying locations never mutates a project or calls a model');
  const receipt = { passed: true, checks, pageErrors: faults, requests, realApiRequests: 0, screenshots: output };
  await writeFile(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify({ passed: true, checks, apiReads: requests.length, realApiRequests: 0, screenshots: output }));
} finally { await browser.close(); }
