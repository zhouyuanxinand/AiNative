/** Real requirement-confirmation UI with isolated APIs; no model calls or user-project writes. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const output = process.env.SCREENSHOT_DIR || path.resolve('runtime/requirement-spec-review/ui');
await mkdir(output, { recursive: true });
const stamp = '2026-11-05T02:00:00Z';
const titles = ['工作温度', '工作压力', '耐盐雾', '贮存条件'];
const originals = ['5℃～70℃', '0.3 MPa', '48 h', '室内贮存'];
const rows = titles.map((title, index) => ({ id: `req-${index}`, title, content: originals[index], source_ids: ['tech'], revision: 1 }));
const sources = ['tech', 'spec'].map(role => ({ id: role, role, name: role === 'tech' ? '客户技术要求.docx' : '液冷产品规范.docx', version: 1, sha256: role, size: 128, created_at: stamp }));
const rc = { id: 'spec-case', scenario_id: 'taskbook', title: '规范逐项核对', stage: 'requirements', status: 'draft', input_revision: 2,
  context: { product_series: 'YLZJ' }, model_selection: { provider: 'fixture', id: 'model', name: 'isolated-spec-model' },
  sources, requirements: rows, source_selection: { tech: 'tech', spec: 'spec' }, decisions: [], workpackages: [], clarifications: [],
  product_route: null, composition_route: null,
  source_analysis: { id: 'original-analysis', status: 'adopted', input_revision: 1, adopted_input_revision: 2, created_at: stamp,
    model_selection: { provider: 'fixture', id: 'model', name: 'isolated-spec-model' }, context: {}, source_hashes: { tech: 'tech', spec: 'spec' }, warnings: [],
    requirements: rows.map(row => ({ title: row.title, content: row.content, source_ids: ['tech'], evidence: [{ source_id: 'tech', quote: row.content }], requirement_id: row.id })) } };
const project = { id: 'spec-project', title: '规范建议浏览器验证', owner_id: 'spec-owner', members: [], version: 1, cases: [rc], events: [] };
// Old extraction results can contain a self-cited hint. It must not become a specification proposal.
rc.source_analysis.requirements[0].recommendation = { text: '请核对所引条款的适用条件', proposed_value: originals[0],
  evidence: [{ source_id: 'tech', quote: originals[0] }] };
const definitions = [
  { status: 'matched', text: '规范明确工作温度及适用工况。', proposed_value: '额定工况下工作温度 5℃～70℃', evidence: [{ source_id: 'spec', quote: '额定工况下工作温度 5℃～70℃' }] },
  { status: 'difference', text: '客户要求 0.3 MPa，规范规定 0.2 MPa，需澄清适用型号。', evidence: [{ source_id: 'spec', quote: '工作压力 0.2 MPa' }] },
  { status: 'not_found', text: '规范未检索到盐雾时间，请补充依据。', evidence: [] },
  { status: 'needs_review', text: '规范贮存条件需要核对适用范围。', proposed_value: '室外低温贮存（适用型号待核对）', evidence: [{ source_id: 'spec', quote: '贮存条件按产品型号确认' }] },
];
const commands = [], pageErrors = [], fixtureErrors = [], unexpectedWrites = [], checks = [];
let nextBatch = 0, failRecommend = false, holdRecommend = true, releaseRecommend;
const batchForCurrent = () => ({ id: `spec-batch-${++nextBatch}`, status: 'current', input_revision: rc.input_revision, created_at: stamp,
  model_selection: rc.model_selection, source_hashes: { tech: 'tech', spec: 'spec' }, warnings: ['规范中的不同型号指标不能混用。'],
  items: definitions.map((item, index) => ({ ...structuredClone(item), requirement_id: rows[index].id, requirement_revision: rows[index].revision })) });
let page;
try {
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('dialog', async dialog => { if (dialog.type() === 'beforeunload') await dialog.accept(); else await dialog.dismiss(); });
  await page.route('**/api/**', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname;
    if (!pathname.startsWith('/api/')) return route.continue();
    try {
      if (pathname === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
      if (pathname === '/api/rd/session') return route.fulfill({ json: { actor_id: 'spec-owner', local_mode: true } });
      if (pathname === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书' }], actions: [], workpackage_definitions: [] } });
      if (pathname === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
      if (pathname === '/api/rd/projects/spec-project') return route.fulfill({ json: project });
      if (pathname === '/api/models') return route.fulfill({ json: { success: true, models: [rc.model_selection] } });
      if (pathname === '/api/product_catalog') return route.fulfill({ json: { product_types: [] } });
      if (pathname.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: rc.stage, project_version: project.version, input_revision: rc.input_revision } } });
      if (pathname.endsWith('/evidence-locations') && request.method() === 'GET') {
        const batches = [rc.source_analysis, rc.requirement_recommendations].filter(Boolean);
        const items = batches.flatMap(batch => (batch.items || batch.requirements).flatMap((row, index) => row.evidence.map(evidence => ({ ...evidence, analysis_id: batch.id,
          status: 'located', source_name: evidence.source_id === 'tech' ? sources[0].name : sources[1].name, source_version: 1,
          locations: [{ id: `B${String(index + 1).padStart(4, '0')}`, label: `第 ${index + 1} 段` }] }))));
        return route.fulfill({ json: { items } });
      }
      if (pathname.endsWith('/commands') && request.method() === 'POST') {
        const body = request.postDataJSON();
        assert.equal(body.expected_version, project.version);
        assert.equal(body.data.case_id, rc.id);
        assert(request.headers()['idempotency-key'], 'commands carry the existing idempotency key');
        commands.push(body);
        if (body.command === 'recommend_requirements') {
          assert.deepEqual(Object.keys(body.data).sort(), ['case_id']);
          if (holdRecommend) { holdRecommend = false; await new Promise(resolve => { releaseRecommend = resolve; }); }
          if (failRecommend) { failRecommend = false; return route.fulfill({ status: 503, json: { error: '规范服务暂不可用' } }); }
          rc.requirement_recommendations = batchForCurrent(); project.version++;
          return route.fulfill({ json: project });
        }
        if (body.command === 'review_requirement') {
          const { requirement_id, requirement_revision, recommendation_batch_id, analysis_id, decision, reason, actual_value } = body.data;
          const row = rows.find(item => item.id === requirement_id);
          assert(row); assert.equal(requirement_revision, row.revision);
          assert.equal(analysis_id, rc.source_analysis.id);
          assert.equal(recommendation_batch_id, rc.requirement_recommendations.id);
          const recommendation = rc.requirement_recommendations.items.find(item => item.requirement_id === row.id);
          assert.equal(rc.requirement_recommendations.status, 'current');
          if (decision === 'accept') {
            assert.equal(recommendation.status, 'needs_review'); assert.equal(actual_value, undefined);
            const original = rc.source_analysis.requirements.find(item => item.requirement_id === row.id);
            assert(original); row.content = original.content; row.source_ids = [...original.source_ids];
          }
          else if (decision === 'reject') { assert(reason?.trim()); assert.equal(actual_value, undefined); }
          else assert.fail('actual results cannot be entered manually');
          row.revision++; project.version++; rc.input_revision++;
          rc.source_analysis.adopted_input_revision = rc.input_revision;
          rc.requirement_recommendations.input_revision = rc.input_revision;
          row.review = { decision, actual_value: decision === 'reject' ? null : row.content, reason: reason || '', requirement_revision: row.revision, input_revision: rc.input_revision,
            analysis_id, recommendation_batch_id, recommendation, actor: 'spec-owner', created_at: stamp };
          if (decision === 'accept' && recommendation.status === 'needs_review') row.review.actual_value_source = 'original';
          return route.fulfill({ json: project });
        }
        unexpectedWrites.push(body.command); throw new Error(`Unexpected fixture command: ${body.command}`);
      }
      if (!['GET', 'HEAD'].includes(request.method())) { unexpectedWrites.push(pathname); return route.fulfill({ status: 501, json: { error: 'Unexpected isolated write' } }); }
      return route.fulfill({ json: {} });
    } catch (error) {
      fixtureErrors.push(error.message);
      return route.fulfill({ status: 500, json: { error: error.message } });
    }
  });
  const url = (process.env.TEST_BASE_URL || 'http://127.0.0.1:18370') + '/?project=spec-project&case=spec-case&step=requirements';
  const table = page.locator('.rd-decision-table');
  const row = index => table.locator(`tbody tr[data-row-key="req-${index}"]`);
  const actual = index => row(index).getByLabel(titles[index] + ' 实际结果', { exact: true });
  const recommend = () => page.getByRole('button', { name: '重新核对规范', exact: true });
  const screenshot = async name => page.screenshot({ path: path.join(output, name), fullPage: false });
  await page.goto(url); await table.waitFor();
  const beforeContents = rows.map(item => item.content);
  for (let index = 0; index < rows.length; index++) {
    await row(index).getByText('尚未核对规范', { exact: true }).waitFor();
    assert.equal(await row(index).getByRole('cell').nth(3).innerText(), '—', 'no specification evidence exists before its batch');
    assert.equal(await row(index).getByRole('button', { name: '采纳', exact: true }).count(), 0);
    assert.equal(await row(index).getByRole('button', { name: '不采纳', exact: true }).count(), 0);
    assert.equal(await actual(index).innerText(), '--');
    assert.equal(await actual(index).evaluate(element => element.tagName), 'P', 'actual result is read-only');
  }
  assert.equal(await page.getByText(/增强建议尚未处理/).count(), 0, 'legacy self-citations do not block confirmation');
  await row(0).getByText('查看原文', { exact: true }).click();
  const originalEvidence = row(0).getByRole('cell').nth(1).getByRole('button', { name: '预览原文，定位 B0001', exact: true });
  await originalEvidence.waitFor();
  assert.equal(await originalEvidence.getAttribute('title'), '客户技术要求.docx · V1 · 第 1 段');
  await screenshot('00-before-spec-review.png');
  await row(0).getByText('查看原文', { exact: true }).click();
  checks.push('legacy extraction hints never display as specification evidence or decisions; original quotes remain traceable');
  await page.getByRole('button', { name: '按规范生成建议', exact: true }).click();
  await page.locator('.rd-spec-review-toolbar').getByRole('button', { name: /正在逐项核对/ }).waitFor();
  await page.waitForFunction(() => document.querySelector('.rd-spec-review-toolbar .ant-btn-loading') !== null);
  assert.deepEqual(rows.map(item => item.content), beforeContents, 'starting a recommendation never adopts values');
  assert.equal(commands.filter(item => item.command === 'recommend_requirements').length, 1);
  assert.equal(await row(0).getByRole('textbox').count(), 0, 'running analysis does not expose result edits');
  assert(releaseRecommend, 'the fixture request reached the generation boundary'); releaseRecommend();
  await row(0).getByText('已找到规范依据', { exact: true }).waitFor();
  await row(1).getByText('指标存在差异', { exact: true }).waitFor();
  await row(2).getByText('规范未找到对应指标', { exact: true }).waitFor();
  await row(3).getByText('适用性待核对', { exact: true }).waitFor();
  assert.equal(await actual(0).innerText(), definitions[0].proposed_value, 'a current matched specification supplies the pending-confirmation result');
  await row(0).getByText('规范建议 · 待确认', { exact: true }).waitFor();
  for (const index of [1, 2, 3]) assert.equal(await actual(index).innerText(), '--');
  const evidence = row(0).getByRole('button', { name: '预览原文，定位 B0001', exact: true });
  await evidence.waitFor(); assert.equal(await evidence.getAttribute('title'), '液冷产品规范.docx · V1 · 第 1 段');
  assert.deepEqual((await row(0).getByRole('cell').nth(4).getByRole('button').allTextContents()).map(text => text.trim()), ['办理澄清'], 'matched rows expose only clarification and are confirmed together');
  for (const index of [1, 2]) assert.equal(await row(index).getByRole('button', { name: '采纳', exact: true }).count(), 0);
  assert.equal(await row(3).getByRole('button', { name: '采纳', exact: true }).isEnabled(), true);
  assert.deepEqual((await row(3).getByRole('cell').nth(4).getByRole('button').allTextContents()).map(text => text.trim()), ['采纳', '不采纳', '办理澄清'], 'needs-review rows expose only the three decision actions');
  assert.equal(await row(2).getByRole('button', { name: '不采纳', exact: true }).count(), 0);
  await screenshot('01-generated-proposals.png');
  checks.push('four specification states retain evidence; only matched results automatically display their pending-confirmation value');

  await row(1).getByRole('button', { name: '不采纳', exact: true }).click();
  await row(1).getByLabel(titles[1] + ' 不采纳原因', { exact: true }).fill('待提交的型号适用性核对原因');
  assert.equal(await recommend().isDisabled(), true, 'new generation cannot invalidate a live draft');
  await page.reload(); await table.waitFor();
  assert.equal(await row(1).getByLabel(titles[1] + ' 不采纳原因', { exact: true }).inputValue(), '待提交的型号适用性核对原因');
  assert.equal(await recommend().isDisabled(), true);
  await row(1).getByRole('button', { name: '放弃草稿', exact: true }).click();
  assert.equal(await recommend().isEnabled(), true);
  assert.equal(await actual(2).innerText(), '--');
  checks.push('live drafts survive refresh and block regenerated suggestions until explicitly discarded');

  failRecommend = true;
  const batchBeforeFailure = structuredClone(rc.requirement_recommendations);
  await recommend().click();
  await page.getByText('本次规范核对未完成，原有结果已保留。请检查页面错误提示后重试。', { exact: true }).waitFor();
  await page.getByRole('alert').filter({ hasText: '规范服务暂不可用' }).first().waitFor();
  assert.deepEqual(rc.requirement_recommendations, batchBeforeFailure);
  assert.deepEqual(rows.map(item => item.content), beforeContents);
  assert.equal(await actual(0).innerText(), definitions[0].proposed_value);
  assert.equal(await row(0).getByRole('button', { name: '采纳', exact: true }).count(), 0);
  await screenshot('02-failure-preserves-results.png');
  await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/commands') && response.status() === 200),
    recommend().click(),
  ]);
  await recommend().waitFor();
  assert.notEqual(rc.requirement_recommendations.id, batchBeforeFailure.id);
  assert.equal(await page.getByText('本次规范核对未完成，原有结果已保留。请检查页面错误提示后重试。', { exact: true }).count(), 0);
  checks.push('failed recheck preserves previous results; retry replaces only the suggestion batch');

  await row(0).getByText('规范建议 · 待确认', { exact: true }).waitFor();
  assert.equal(await actual(0).innerText(), definitions[0].proposed_value);
  assert.equal((await row(0).getByRole('cell').nth(1).innerText()).startsWith(originals[0]), true, 'source requirement remains unchanged');
  assert.equal(rows[0].content, originals[0], 'displaying a matched result does not rewrite the source requirement');
  assert.equal(rows[0].review, undefined, 'matched results are not fabricated per-row acceptances');
  assert.deepEqual(rows.slice(1).map(item => item.content), originals.slice(1));
  await row(1).getByRole('button', { name: '不采纳', exact: true }).click();
  assert.equal(await row(1).getByRole('button', { name: '确认不采纳', exact: true }).isDisabled(), true);
  await row(1).getByLabel(titles[1] + ' 不采纳原因', { exact: true }).fill('该规范适用型号不同，保留客户压力要求。');
  await row(1).getByRole('button', { name: '确认不采纳', exact: true }).click();
  await row(1).getByText('不采纳 · 待澄清', { exact: true }).waitFor();
  assert.equal(await actual(1).innerText(), '--');
  await row(1).getByRole('button', { name: '办理澄清', exact: true }).click();
  await page.locator('.rd-record-new').getByLabel('需要澄清的问题', { exact: true }).waitFor();
  await page.locator('.rd-record-new .ant-select-selection-item').filter({ hasText: '工作压力 · v2' }).waitFor();
  assert.deepEqual(commands.filter(item => item.command === 'review_requirement').map(item => [item.data.requirement_id, item.data.decision, item.data.recommendation_batch_id]),
    [['req-1', 'reject', rc.requirement_recommendations.id]]);
  await screenshot('03-explicit-decisions.png');
  checks.push('matched results need no per-row writes; difference rejection requires a reason and batch identity');

  const reviewedBatchId = rc.requirement_recommendations.id;
  rc.source_analysis.id = 'repeated-source-analysis'; project.version++;
  await page.reload(); await table.waitFor();
  await row(0).getByText('规范建议 · 待确认', { exact: true }).waitFor();
  await row(1).getByText('不采纳 · 待澄清', { exact: true }).waitFor();
  assert.equal(rc.requirement_recommendations.id, reviewedBatchId);
  assert.equal(await actual(0).innerText(), definitions[0].proposed_value);
  assert.equal(await row(0).getByRole('button', { name: '采纳', exact: true }).count(), 0);
  await page.getByRole('button', { name: '待决定（3）', exact: true }).waitFor();
  checks.push('re-adopting unchanged sources preserves decisions on the still-current batch and requirement revision');

  await row(3).getByRole('button', { name: '采纳', exact: true }).click();
  await row(3).getByText('已采纳', { exact: true }).waitFor();
  assert.equal(await actual(3).innerText(), originals[3], 'needs-review adoption uses the adopted original requirement');
  assert.notEqual(await actual(3).innerText(), definitions[3].proposed_value, 'an unverified proposed value cannot replace the original');
  assert.equal(rows[3].review.actual_value_source, 'original');
  assert.deepEqual(rows[3].source_ids, ['tech'], 'original adoption preserves the original source identity');
  await page.reload(); await table.waitFor();
  assert.equal(await actual(3).innerText(), originals[3], 'explicit original adoption survives reload');
  assert.equal(await row(3).getByRole('button', { name: '采纳', exact: true }).isDisabled(), true);
  await row(3).getByRole('button', { name: '不采纳', exact: true }).click();
  await row(3).getByLabel(titles[3] + ' 不采纳原因', { exact: true }).fill('需再核对贮存适用型号。');
  await row(3).getByRole('button', { name: '确认不采纳', exact: true }).click();
  await row(3).getByText('不采纳 · 待澄清', { exact: true }).waitFor();
  assert.equal(await actual(3).innerText(), '--', 'rejecting an adopted original clears the actual result');
  await row(3).getByRole('button', { name: '采纳', exact: true }).click();
  await row(3).getByText('已采纳', { exact: true }).waitFor();
  assert.equal(await actual(3).innerText(), originals[3], 're-adoption still uses the immutable original');
  assert.equal(rows[3].review.actual_value_source, 'original');
  assert.equal(await actual(0).innerText(), definitions[0].proposed_value, 'needs-review decisions do not overwrite another row');
  assert.equal(await actual(2).innerText(), '--');
  checks.push('needs-review accept adopts only the original, persists on reload, clears on rejection and can be re-adopted');

  const commandCount = commands.length;
  await row(3).getByRole('button', { name: '办理澄清', exact: true }).click();
  const clarification = page.locator('.rd-record-new').filter({ hasText: '提出澄清问题' });
  await clarification.getByLabel('需要澄清的问题', { exact: true }).waitFor();
  await clarification.locator('.ant-select-selection-item').filter({ hasText: `贮存条件 · v${rows[3].revision}` }).waitFor();
  assert.equal(commands.length, commandCount, 'opening clarification does not adopt or save a requirement');
  assert.equal(rows[3].content, originals[3]);
  await screenshot('04-clarification-target.png');
  checks.push('needs-review item opens the corresponding clarification form without mutating the requirement');

  rows[3].content = '室内干燥贮存，按客户确认型号执行'; rows[3].revision++;
  rows[3].history = [{ revision: rows[3].revision, clarification_id: 'clarification-adopted' }];
  rc.input_revision++; rc.source_analysis.adopted_input_revision = rc.input_revision;
  rc.requirement_recommendations.input_revision = rc.input_revision; project.version++;
  rc.clarifications.push({ id: 'clarification-adopted', requirement_id: rows[3].id, question: '请确认贮存适用型号。',
    required: true, status: 'adopted', revision: 1, requirement_revision: 1, input_revision: rc.input_revision - 1,
    source_ids: ['tech'], actor: 'spec-owner', created_at: stamp, answer: rows[3].content, answer_source_ids: ['spec'], history: [],
    answer_source_snapshots: sources.filter(source => source.id === 'spec').map(({ id, role, name, version, sha256 }) => ({ id, role, name, version, sha256 })),
    adoption: { requirement_revision: rows[3].revision, input_revision: rc.input_revision, requirement_content: rows[3].content,
      recommendation_batch_id: rc.requirement_recommendations.id, actor: 'spec-owner', created_at: stamp } });
  await page.reload(); await table.waitFor();
  await row(3).getByText('澄清已采用', { exact: true }).waitFor();
  assert.equal(await actual(3).innerText(), rows[3].content);
  assert.equal(await row(3).getByRole('textbox').count(), 0, 'adopted clarification cannot be overwritten by a second actual-value edit');
  assert.equal(await row(3).getByRole('button', { name: '不采纳', exact: true }).isDisabled(), true);
  assert.equal(await row(3).getByText('建议已过期，请重新核对规范', { exact: true }).count(), 0);
  assert.equal(await row(3).getByRole('button', { name: '编辑需求', exact: true }).count(), 0, 'a needs-review row keeps its decision-only actions after clarification');
  assert.equal(await recommend().isEnabled(), true);
  await page.getByRole('button', { name: '待决定（2）', exact: true }).waitFor();
  assert.equal(commands.length, commandCount, 'loading an adopted clarification never writes another decision');
  await screenshot('05-adopted-clarification.png');
  checks.push('adopted clarification at the batch revision counts as handled and locks duplicate decisions without becoming stale');

  assert.equal(await row(0).getByRole('button', { name: '不采纳', exact: true }).count(), 0);
  rc.requirement_recommendations.status = 'stale'; rc.input_revision++;
  rc.source_analysis.adopted_input_revision = rc.input_revision; project.version++;
  await page.reload(); await table.waitFor();
  await page.getByText('需求或来源已变更，请重新核对规范。', { exact: true }).waitFor();
  assert.equal(await actual(0).innerText(), '--', 'stale specification values stop appearing as current results');
  assert.equal(await row(0).getByRole('button', { name: '采纳', exact: true }).count(), 0);
  assert.equal(await row(0).getByRole('button', { name: '不采纳', exact: true }).count(), 0);
  assert.equal(await row(3).getByRole('button', { name: '不采纳', exact: true }).isDisabled(), true);
  assert.equal(await recommend().isEnabled(), true);
  checks.push('stale batches disable suggestion decisions while offering a current recheck');
  await screenshot('06-stale-batch.png');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.rd-spec-review-toolbar').scrollIntoViewIfNeeded();
  assert.equal(await page.locator('.rd-spec-review-toolbar').evaluate(element => element.scrollWidth <= element.clientWidth + 1), true, 'mobile generation controls fit');
  assert.equal(await table.evaluate(element => element.scrollWidth <= element.clientWidth + 1), true, 'mobile review rows fit');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1), true, 'mobile page has no horizontal overflow');
  await screenshot('07-narrow-layout.png');
  rc.source_selection.spec = 'missing-primary-spec'; project.version++;
  await page.reload(); await table.waitFor();
  await page.getByText('请先在资料识别中上传并选择主产品规范。', { exact: true }).waitFor();
  assert.equal(await recommend().isDisabled(), true);
  rc.source_selection.spec = 'spec'; rc.stage = 'selection'; project.version++;
  await page.reload(); await row(0).getByText('只读', { exact: true }).waitFor();
  assert.equal(await recommend().count(), 0, 'completed confirmation stage cannot generate another batch');
  checks.push('390px layout, missing main specification, and completed-stage read-only guards');
  assert.deepEqual(fixtureErrors, []); assert.deepEqual(unexpectedWrites, []); assert.deepEqual(pageErrors, []);
  await writeFile(path.join(output, 'receipt.json'), JSON.stringify({ passed: true, checks, fixtureCommands: commands.map(item => ({ command: item.command, data: item.data })),
    realApiRequests: 0, unexpectedWrites, fixtureErrors, pageErrors }, null, 2));
  console.log('PASS: specification generation, evidence, draft protection, failed recheck/retry, accept/reject, clarification, stale decisions, mobile and read-only');
} catch (error) {
  if (page) await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: false }).catch(() => {});
  await writeFile(path.join(output, 'failure.json'), JSON.stringify({ passed: false, checks, message: error.message, fixtureErrors, unexpectedWrites, pageErrors }, null, 2));
  throw error;
} finally { if (releaseRecommend) releaseRecommend(); await browser.close(); }
