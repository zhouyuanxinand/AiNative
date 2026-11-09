/** Isolated APIs exercise the real review table without changing any user project. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const output = process.env.SCREENSHOT_DIR || path.resolve('runtime/requirement-decision-scroll/ui');
await mkdir(output, { recursive: true });
const sources = ['tech', 'spec'].map(role => ({ id: role, role, name: role === 'tech' ? '客户技术要求.docx' : '产品规范.docx', version: 1, sha256: role, size: 100 }));
const requirements = Array.from({ length: 40 }, (_, index) => ({ id: `req-${index}`, title: `指标 ${index + 1}`, content: `原始指标 ${index + 1}`, source_ids: ['tech'], revision: 1 }));
const rc = { id: 'scroll-case', scenario_id: 'taskbook', title: '长表逐项办理', stage: 'requirements', status: 'draft', input_revision: 2,
  context: { product_series: 'YLZJ' }, sources, source_selection: { tech: 'tech', spec: 'spec' }, requirements,
  decisions: [], workpackages: [], clarifications: [], product_route: null, composition_route: null,
  source_analysis: { id: 'analysis', status: 'adopted', input_revision: 1, adopted_input_revision: 2, context: {}, warnings: [],
    model_selection: { provider: 'fixture', id: '1', name: 'isolated-model' }, source_hashes: { tech: 'tech', spec: 'spec' },
    requirements: requirements.map(row => ({ requirement_id: row.id, title: row.title, content: row.content, source_ids: ['tech'], evidence: [{ source_id: 'tech', quote: row.content }] })) },
  requirement_recommendations: { id: 'batch', status: 'current', input_revision: 2, created_at: '2026-11-06T01:00:00Z', warnings: [],
    model_selection: { provider: 'fixture', id: '1', name: 'isolated-model' }, source_hashes: { tech: 'tech', spec: 'spec' },
    items: requirements.map(row => ({ requirement_id: row.id, requirement_revision: 1, status: 'needs_review', text: '核对适用范围', proposed_value: '未确认建议', evidence: [{ source_id: 'spec', quote: '核对适用范围' }] })) } };
const project = { id: 'scroll-project', title: '需求操作位置验证', owner_id: 'scroll-owner', members: [], version: 1, cases: [rc], events: [] };
const errors = [], commands = [], positions = [];
let release, page, failNext = true;
try {
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname;
    if (!pathname.startsWith('/api/')) return route.continue();
    try {
      if (pathname === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
      if (pathname === '/api/rd/session') return route.fulfill({ json: { actor_id: 'scroll-owner', local_mode: true } });
      if (pathname === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书' }], actions: [], workpackage_definitions: [] } });
      if (pathname === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
      if (pathname === '/api/rd/projects/scroll-project') return route.fulfill({ json: project });
      if (pathname === '/api/models') return route.fulfill({ json: { success: true, models: [] } });
      if (pathname === '/api/product_catalog') return route.fulfill({ json: { product_types: [] } });
      if (pathname.endsWith('/evidence-locations')) return route.fulfill({ json: { items: [] } });
      if (pathname.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: rc.stage, project_version: project.version, input_revision: rc.input_revision } } });
      if (pathname.endsWith('/commands') && request.method() === 'POST') {
        const body = request.postDataJSON();
        assert.equal(body.command, 'review_requirement'); assert.equal(body.expected_version, project.version);
        const row = requirements.find(item => item.id === body.data.requirement_id);
        assert(row); assert.equal(body.data.requirement_revision, row.revision);
        commands.push(body);
        await new Promise(resolve => { release = resolve; });
        if (failNext) { failNext = false; release = undefined; return route.fulfill({ status: 503, json: { error: '暂时无法保存需求决定，请重试。' } }); }
        row.revision++; project.version++; rc.input_revision++;
        rc.source_analysis.adopted_input_revision = rc.input_revision;
        rc.requirement_recommendations.input_revision = rc.input_revision;
        row.review = { decision: body.data.decision, actual_value: body.data.decision === 'accept' ? row.content : null,
          actual_value_source: body.data.decision === 'accept' ? 'original' : undefined, requirement_revision: row.revision,
          recommendation_batch_id: 'batch', analysis_id: 'analysis', recommendation: rc.requirement_recommendations.items.find(item => item.requirement_id === row.id), actor: 'scroll-owner', created_at: '2026-11-06T01:00:00Z' };
        release = undefined;
        return route.fulfill({ json: project });
      }
      assert(['GET', 'HEAD'].includes(request.method()), 'no unplanned writes');
      return route.fulfill({ json: {} });
    } catch (error) { errors.push(error.message); return route.fulfill({ status: 500, json: { error: error.message } }); }
  });
  await page.goto((process.env.TEST_BASE_URL || 'http://127.0.0.1:18375') + '/?project=scroll-project&case=scroll-case&step=requirements');
  const table = page.locator('.rd-decision-table');
  let row = table.locator('tr[data-row-key="req-20"]');
  await row.getByRole('button', { name: '采纳', exact: true }).waitFor();
  await row.evaluate(element => element.scrollIntoView({ block: 'center' }));
  const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const position = async name => {
    await settle();
    const value = await row.evaluate(element => ({ y: element.getBoundingClientRect().y, top: element.closest('.rd-application-shell').scrollTop,
      height: element.getBoundingClientRect().height, clarificationActions: Array.from(document.querySelectorAll('.rd-decision-table button')).filter(button => button.textContent === '办理澄清').length }));
    positions.push({ name, ...value }); return value;
  };
  const before = await position('before accept');
  await row.getByRole('button', { name: '采纳', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.rd-decision-table tr[data-row-key="req-20"] button').disabled);
  const busy = await position('accept pending');
  assert(release, 'the isolated request is pending'); release();
  await page.getByRole('alert').filter({ hasText: '暂时无法保存需求决定，请重试。' }).first().waitFor();
  const failed = await position('after failed accept');
  assert(Math.abs(busy.y - before.y) < 40 && Math.abs(failed.y - before.y) < 40, 'a failed decision stays at its row rather than scrolling to the page error');
  assert.equal(await row.getByLabel('指标 21 实际结果', { exact: true }).innerText(), '--');
  await row.getByRole('button', { name: '采纳', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.rd-decision-table tr[data-row-key="req-20"] button').disabled);
  await position('accept retry pending'); assert(release); release();
  await row.getByText('已采纳', { exact: true }).waitFor();
  const accepted = await position('after accept');
  assert(Math.abs(busy.y - before.y) < 40 && Math.abs(accepted.y - before.y) < 40, 'accept keeps the current row in position while saving and after completion');
  assert.equal(busy.clarificationActions, requirements.length, 'busy state disables rather than removes clarification actions');
  await row.getByRole('button', { name: '不采纳', exact: true }).click();
  await row.getByLabel('指标 21 不采纳原因', { exact: true }).fill('该型号适用范围需再澄清。');
  const beforeReject = await position('before reject');
  await row.getByRole('button', { name: '确认不采纳', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.rd-decision-table tr[data-row-key="req-20"] textarea').disabled);
  const rejecting = await position('reject pending');
  assert(release); release();
  await row.getByText('不采纳 · 待澄清', { exact: true }).waitFor();
  const rejected = await position('after reject');
  assert(Math.abs(rejecting.y - beforeReject.y) < 40 && Math.abs(rejected.y - beforeReject.y) < 40, 'reject keeps the current row instead of jumping to the clarification form');
  assert.equal(await row.getByLabel('指标 21 实际结果', { exact: true }).innerText(), '--');
  await page.screenshot({ path: path.join(output, 'after-row-decisions.png') });
  const side = name => page.getByRole('navigation', { name: '当前业务流程视图', exact: true }).getByRole('button', { name, exact: true });
  await side('项目流程').click();
  await page.locator('.rd-case-heading h1').filter({ hasText: /^项目流程$/ }).waitFor();
  await side('当前成果').click(); await row.waitFor();
  const returned = await position('after process return');
  assert(Math.abs(returned.y - rejected.y) < 40, 'returning from the process view preserves the reviewed row');
  await row.getByRole('button', { name: '办理澄清', exact: true }).click();
  const question = page.locator('.rd-record-new').getByLabel('需要澄清的问题', { exact: true });
  await question.waitFor(); await question.fill('核对型号后再回复，保留此澄清草稿。');
  await page.getByRole('button', { name: '返回对应需求 ↑', exact: true }).click();
  const clarificationReturned = await position('after clarification return');
  assert(Math.abs(clarificationReturned.y - returned.y) < 40, 'explicit clarification provides a return to the same requirement row');
  assert.equal(await question.inputValue(), '核对型号后再回复，保留此澄清草稿。', 'returning does not discard the clarification draft');
  await question.fill('');

  row = table.locator('tr[data-row-key="req-36"]');
  await row.evaluate(element => element.scrollIntoView({ block: 'center' }));
  const bottom = await position('bottom before accept');
  await row.getByRole('button', { name: '采纳', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.rd-decision-table tr[data-row-key="req-36"] button').disabled);
  assert(release); release(); await row.getByText('已采纳', { exact: true }).waitFor();
  const bottomAccepted = await position('bottom after accept');
  assert(Math.abs(bottomAccepted.y - bottom.y) < 40, 'adoption near the end of a long table retains position');
  await row.getByRole('button', { name: '不采纳', exact: true }).click();
  await row.getByLabel('指标 37 不采纳原因', { exact: true }).fill('需要核对产品适用条件。');
  const bottomReject = await position('bottom before reject');
  failNext = true;
  await row.getByRole('button', { name: '确认不采纳', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.rd-decision-table tr[data-row-key="req-36"] textarea').disabled);
  assert(release); release();
  await row.getByRole('button', { name: '确认不采纳', exact: true }).waitFor({ state: 'visible' });
  await page.waitForFunction(() => !document.querySelector('.rd-decision-table tr[data-row-key="req-36"] textarea').disabled);
  const bottomFailed = await position('bottom after failed reject');
  assert(Math.abs(bottomFailed.y - bottomReject.y) < 40, 'failed rejection near the end keeps the current row');
  assert.equal(await row.getByLabel('指标 37 不采纳原因', { exact: true }).inputValue(), '需要核对产品适用条件。');
  await row.getByRole('button', { name: '确认不采纳', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.rd-decision-table tr[data-row-key="req-36"] textarea').disabled);
  assert(release); release(); await row.getByText('不采纳 · 待澄清', { exact: true }).waitFor();
  const bottomRejected = await position('bottom after reject retry');
  assert(Math.abs(bottomRejected.y - bottomReject.y) < 40, 'rejection retry preserves the position');
  assert.equal(commands.length, 6);
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, 'receipt.json'), JSON.stringify({ passed: true, positions, fixtureCommands: commands.length, realApiRequests: 0, errors }, null, 2));
  console.log('PASS: accept/reject retain the long-table position during saving and on return from process');
} catch (error) {
  if (page) await page.screenshot({ path: path.join(output, 'failure.png') }).catch(() => {});
  await writeFile(path.join(output, 'failure.json'), JSON.stringify({ passed: false, message: error.message, positions, errors }, null, 2));
  throw error;
} finally { release?.(); await browser.close(); }
