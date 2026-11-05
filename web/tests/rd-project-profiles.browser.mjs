/** Project-scoped profile views: isolated read responses, no enterprise master-data assumptions. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'runtime/project-profiles';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
const pageErrors = [], writes = [], checks = [];
page.on('pageerror', error => pageErrors.push(error.message));
let mode = 'ready', release;
const stamp = '2026-11-05T04:00:00Z';
const projects = Array.from({ length: 6 }, (_, index) => {
  const old = { id: 'old', role: 'tech', name: '技术要求-旧版.docx', sha256: 'old-hash', version: 1, size: 12, created_at: stamp };
  const current = { id: 'current', role: 'tech', name: '技术要求-现版.docx', sha256: 'new-hash', version: 2, size: 15, created_at: stamp };
  const spec = { id: 'spec', role: 'spec', name: '产品规范.docx', sha256: 'spec-hash', version: 1, size: 15, created_at: stamp };
  const researchCase = { id: 'case-' + index, title: '液冷办理 ' + index, scenario_id: 'taskbook', stage: 'requirements', status: 'active', input_revision: 3,
    context: { product_type: 'liquid_cooling_pipeline', product_domain: 'military', product_series: 'YLZJ' }, context_provenance: { product_series: { evidence: [{ source_id: 'project_product_name', quote: '项目登记 YLZJ' }] } }, source_selection: { tech: 'current', spec: 'spec' }, sources: [old, current, spec], workpackages: [], decisions: [], product_route: null, composition_route: null,
    requirements: [{ id: 'req-' + index, title: '环境温度', content: '确认值 5℃～42℃', source_ids: ['old'], revision: 2, review: { decision: 'manual', actual_value: '确认值 5℃～42℃', reason: '已核对需求答复', analysis_id: 'superseded-analysis', requirement_revision: 2, actor: 'owner', created_at: stamp } }],
    source_analysis: { id: 'analysis-' + index, status: 'stale', input_revision: 1, created_at: stamp, source_hashes: { old: 'old-hash' }, context: {}, model_selection: { name: 'test-model', id: '1', provider: 'test' }, warnings: [], requirements: [{ requirement_id: 'req-' + index, title: '环境温度', content: '原文温度 10℃～40℃', source_ids: ['old'], evidence: [{ source_id: 'old', quote: '原文温度 10℃～40℃' }] }] },
  };
  researchCase.requirements.push({ id: 'accepted-' + index, title: '防护等级', content: 'IP68', source_ids: ['old', 'spec'], revision: 2,
    review: { decision: 'accept', actual_value: 'IP68', requirement_revision: 2, analysis_id: researchCase.source_analysis.id, actor: 'owner', created_at: stamp,
      recommendation: { text: '按适用产品规范', proposed_value: 'IP68', evidence: [{ source_id: 'spec', quote: '防护等级 IP68' }] } } });
  researchCase.source_analysis.requirements.push({ requirement_id: 'accepted-' + index, title: '防护等级', content: '原文防护等级待澄清', source_ids: ['old'], evidence: [{ source_id: 'old', quote: '原文防护等级待澄清' }] });
  return { id: 'profile-project-' + index, title: '画像范围项目 ' + index, customer_name: '同名客户', product_name: '同名产品', brief: '项目范围 ' + index, version: 1, owner_id: 'owner', members: [], events: [], updated_at: stamp, cases: [researchCase] };
});
try {
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (!['GET', 'HEAD'].includes(req.method())) writes.push(path);
    if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
    if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'owner', local_mode: true } });
    if (path === '/api/rd/projects') {
      if (mode === 'loading') await new Promise(resolve => { release = resolve; });
      if (mode === 'error') return route.fulfill({ status: 503, json: { detail: '画像读取失败测试' } });
      return route.fulfill({ json: { projects: mode === 'empty' ? [] : projects } });
    }
    if (path.startsWith('/api/rd/projects/')) return route.fulfill({ json: projects.find(project => path.endsWith(project.id)) || {} });
    if (path === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [], actions: [], workpackage_definitions: [] } });
    if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: 'liquid_cooling_pipeline', label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }] }] } });
    if (path === '/api/rd/assistant/weather') return route.fulfill({ json: { status: 'unavailable' } });
    return route.fulfill({ json: {} });
  });
  await page.goto(base + '/?rd_view=management');
  await page.getByRole('heading', { name: '项目与工作', exact: true }).waitFor();
  await page.getByRole('tab', { name: '客户画像', exact: true }).click();
  const directory = page.getByRole('region', { name: '客户画像目录', exact: true });
  await directory.getByRole('textbox', { name: '搜索客户画像', exact: true }).fill('同名客户');
  await directory.getByRole('textbox', { name: '搜索客户画像', exact: true }).press('Enter');
  await directory.getByText('1–5 / 6 条', { exact: true }).waitFor();
  await directory.getByRole('button', { name: '下一页', exact: true }).click();
  await directory.getByText('6–6 / 6 条', { exact: true }).waitFor();
  await page.screenshot({ path: join(output, '00-customer-directory.png') });
  await directory.getByRole('button', { name: '查看画像', exact: true }).click();
  const detail = page.getByRole('region', { name: '客户画像详情', exact: true });
  await detail.waitFor();
  assert.equal(await directory.count(), 0, 'profile detail replaces rather than stacks beneath its directory');
  await detail.getByText('画像范围项目 5', { exact: true }).first().waitFor();
  assert(await detail.getByText('画像主档尚未接入', { exact: true }).isVisible());
  assert(await detail.getByText('原文温度 10℃～40℃', { exact: true }).first().isVisible());
  assert(await detail.getByText('确认值 5℃～42℃', { exact: true }).first().isVisible());
  assert.equal(await detail.getByText('历史分析 · 待复核', { exact: true }).count(), 2);
  assert(await detail.getByText('决定待复核', { exact: true }).isVisible(), 'superseded analysis does not validate an old row decision');
  await detail.getByText('来源与原文', { exact: true }).first().click();
  const citation = detail.getByRole('link', { name: /技术要求-旧版.docx/ }).first();
  assert((await citation.getAttribute('href')).includes('/profile-project-5/cases/case-5/sources/old'));
  assert(await detail.getByText('历史版本', { exact: true }).first().isVisible());
  const acceptedRow = detail.getByRole('row').filter({ hasText: '防护等级' });
  await acceptedRow.getByText('当前记录依据', { exact: true }).click();
  assert(await acceptedRow.getByRole('link', { name: /产品规范.docx/ }).isVisible());
  assert(await acceptedRow.getByText('防护等级 IP68', { exact: true }).isVisible());
  assert.equal(await acceptedRow.locator('td').nth(1).getByRole('link', { name: /产品规范.docx/ }).count(), 0, 'accepted recommendation proof must not replace original source proof');
  await page.screenshot({ path: join(output, '01-customer-detail-desktop.png') });
  await page.getByRole('button', { name: '返回客户画像目录', exact: true }).click();
  await directory.getByText('6–6 / 6 条', { exact: true }).waitFor();
  assert.equal(await directory.getByRole('textbox', { name: '搜索客户画像' }).inputValue(), '同名客户');
  checks.push('同名客户按项目分成六条，详情互斥，返回保留查询与第2页，原文与实际值分离且历史来源有标注');
  await page.getByRole('tab', { name: '产品画像', exact: true }).click();
  await page.getByRole('region', { name: '产品画像目录' }).getByRole('button', { name: '查看画像', exact: true }).first().click();
  const product = page.getByRole('region', { name: '产品画像详情', exact: true });
  await product.getByText('液冷产品-液冷管路', { exact: true }).waitFor();
  await product.getByText('企业已验证能力尚未接入', { exact: true }).waitFor();
  await product.getByText('参数依据', { exact: true }).click();
  assert(await product.getByText('项目登记 · 产品名称', { exact: true }).isVisible());
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await page.locator('.rd-application-shell').evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'profile does not widen entire narrow page');
  await page.screenshot({ path: join(output, '02-product-detail-mobile.png') });
  await page.reload();
  await product.waitFor();
  checks.push('产品目录与客户目录互相隔离；产品画像不将技术要求冒称已验证能力，刷新保留详情');
  mode = 'empty';
  await page.goto(base + '/?rd_view=management&management_tab=customer');
  await page.getByText('暂无可查看的客户画像。', { exact: true }).waitFor();
  mode = 'error'; await page.reload();
  await page.getByRole('alert').filter({ hasText: '项目状态读取失败' }).waitFor();
  assert.equal(await page.getByText('暂无可查看的客户画像。', { exact: true }).count(), 0);
  mode = 'loading';
  await page.reload();
  await page.getByRole('status').filter({ hasText: '正在读取项目状态' }).waitFor();
  assert.equal(await page.getByText('暂无可查看的客户画像。', { exact: true }).count(), 0);
  mode = 'ready'; release();
  await page.getByRole('region', { name: '客户画像目录' }).getByText('1–5 / 6 条', { exact: true }).waitFor();
  checks.push('空数据、读取失败、请求中分别展示，加载失败不伪装为空目录');
  assert.deepEqual(pageErrors, []); assert.deepEqual(writes, []);
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ passed: true, checks, pageErrors, writes, mocked: true }, null, 2));
  console.log(JSON.stringify({ passed: true, checks, mocked: true }));
} catch (error) {
  await page.screenshot({ path: join(output, 'failure.png') });
  await writeFile(join(output, 'failure.json'), JSON.stringify({ error: String(error), url: page.url(), pageErrors, body: await page.locator('body').innerText() }, null, 2));
  throw error;
} finally { release?.(); await browser.close(); }
