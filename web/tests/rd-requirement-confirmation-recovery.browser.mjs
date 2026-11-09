/** Confirmation readiness and return-to-clarification flow, using isolated API fixtures. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const output = process.env.SCREENSHOT_DIR || path.resolve('runtime/requirement-confirmation-recovery');
await mkdir(output, { recursive: true });
const stamp = '2026-11-05T02:00:00Z';
const sources = ['tech', 'spec'].map(role => ({ id: role, role, name: role === 'tech' ? '技术要求.docx' : '产品规范.docx', version: 1, sha256: role, size: 128, created_at: stamp }));
const requirement = { id: 'r1', title: '环境温度', content: '5℃～42℃', source_ids: ['tech'], revision: 1 };
const unmatched = { id: 'r2', title: '连接规格', content: '按客户接口图', source_ids: ['tech'], revision: 1 };
const ids = ['input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start', 'taskbook'];
const workflow = { id: 'taskbook-generation', version: '1', template_id: 'taskbook-generation', template_version: '1', template_digest: 'recovery-fixed', title: '研制任务书生成流程', status: 'published', node_states: {},
  graph: { nodes: ids.map((id, index) => ({ id, title: id, role: '研发工程师', deliverables: [], position: { x: index * 240, y: 0 },
    ...({ confirm_requirements: 'requirements', selection_decision: 'selection', rd_start: 'rd_start' }[id] ? { gate: { confirm_requirements: 'requirements', selection_decision: 'selection', rd_start: 'rd_start' }[id] } : {}),
    ...(id === 'taskbook' ? { workpackage_definition_id: 'taskbook' } : {}) })), edges: ids.slice(1).map((id, index) => ({ id: 'e-' + id, source: ids[index], target: id })) } };
const rc = { id: 'recovery-case', scenario_id: 'taskbook', title: '需求确认恢复', stage: 'requirements', status: 'active', input_revision: 2,
  context: { product_series: 'YLZJ' }, model_selection: { provider: 'fixture', id: 'model', name: 'isolated-model' },
  sources, requirements: [requirement, unmatched], source_selection: { tech: 'tech', spec: 'spec' }, decisions: [], workpackages: [], clarifications: [], comparisons: [], review_bundles: [], requirement_baselines: [],
  workflow_templates: { project: workflow }, project_workflow_status: { status: 'pending', terminal_node_id: 'taskbook' },
  business_lifecycle: { policy_version: 'v2', rd_activation_state: 'not_started', review_mode: 'local_review', local_review_enabled: true, can_record_decision: true, can_confirm_requirements: true },
  product_route: null, composition_route: null,
  source_analysis: { id: 'analysis', status: 'adopted', input_revision: 1, adopted_input_revision: 2, created_at: stamp,
    model_selection: { provider: 'fixture', id: 'model', name: 'isolated-model' }, context: {}, source_hashes: { tech: 'tech', spec: 'spec' }, warnings: [],
    requirements: [requirement, unmatched].map(row => ({ ...row, requirement_id: row.id, evidence: [{ source_id: 'tech', quote: row.content }] })) },
  requirement_recommendations: { id: 'batch', status: 'current', input_revision: 2, created_at: stamp, model_selection: { provider: 'fixture', id: 'model', name: 'isolated-model' }, source_hashes: { tech: 'tech', spec: 'spec' }, warnings: [],
    items: [{ requirement_id: 'r1', requirement_revision: 1, status: 'difference', text: '规范与客户环境温度不同，需要核对。', evidence: [{ source_id: 'spec', quote: '环境温度 -20℃～55℃' }] },
      { requirement_id: 'r2', requirement_revision: 1, status: 'not_found', text: '规范未找到对应接口，保留客户要求。', evidence: [] }] } };
const project = { id: 'recovery-project', title: '需求确认恢复隔离验证', owner_id: 'recovery-owner', members: [], version: 1, cases: [rc], events: [] };
const commands = [], pageErrors = [], fixtureErrors = [], checks = [];
let rejectNextConfirmation = true;
let successfulConfirmations = 0;
const errorText = '「环境温度」的规范建议尚未处理，请填写决定或采用澄清结果。';
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
page.on('pageerror', error => pageErrors.push(error.message));
page.on('dialog', dialog => dialog.type() === 'beforeunload' ? dialog.accept() : dialog.dismiss());
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const url = step => `${base}/?project=${project.id}&case=${rc.id}&step=${step}`;
const table = page.locator('.rd-decision-table');
const heading = page.locator('.rd-case-heading h1');
const save = () => page.getByRole('dialog').getByRole('button', { name: '保存本地决定', exact: true });
const continueButton = () => page.locator('.rd-case-continuation').getByRole('button', { name: /确认需求并进入选型/ });
const confirmButton = () => page.locator('.rd-business-decision').getByRole('button', { name: '确认需求并进入选型', exact: true });
const returnButton = () => page.getByRole('button', { name: '返回需求与澄清', exact: true });
const scope = () => page.getByLabel('确认范围', { exact: true });
const confirmScope = '确认当前需求，作为后续选型依据。';
async function capture(name) { await page.screenshot({ path: path.join(output, name + '.png') }); }
const sourceSnapshot = source => Object.fromEntries(['id', 'role', 'name', 'version', 'sha256'].map(key => [key, source[key]]));
async function clarify(row, value) {
  const tableRow = table.locator(`tbody tr[data-row-key="${row.id}"]`);
  await tableRow.getByRole('button', { name: '办理澄清', exact: true }).click();
  const create = page.locator('.rd-record-new');
  await create.getByLabel('需要澄清的问题', { exact: true }).fill(`请确认${row.title}适用值`);
  await create.getByRole('checkbox', { name: /技术要求.docx/ }).check();
  await create.getByRole('button', { name: '保存澄清问题', exact: true }).click();
  const record = page.locator(`[data-clarification-id="clar-${row.id}"]`);
  await record.locator('summary').click();
  await record.getByLabel('澄清答复', { exact: true }).fill(value);
  await record.getByRole('checkbox', { name: /技术要求.docx/ }).check();
  await record.getByRole('button', { name: '保存澄清答复', exact: true }).click();
  await record.getByLabel('采用后的完整需求正文', { exact: true }).waitFor();
  assert.equal((await tableRow.getByRole('cell').nth(5).innerText()).split('\n')[0], '--', 'saved answer alone cannot assign an actual result');
  await record.getByLabel('采用后的完整需求正文', { exact: true }).fill(value);
  await record.getByRole('button', { name: '核对并采用答复', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '采用并重新确认', exact: true }).click();
  await page.getByRole('dialog').waitFor({ state: 'hidden' });
  await tableRow.getByRole('cell').nth(5).getByText(value, { exact: true }).waitFor();
}
try {
  await page.route('**/api/**', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname;
    if (!pathname.startsWith('/api/')) return route.continue();
    try {
      if (pathname === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
      if (pathname === '/api/rd/session') return route.fulfill({ json: { actor_id: project.owner_id, local_mode: true } });
      if (pathname === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书' }], actions: [], workpackage_definitions: [], project_workflow_templates: [workflow] } });
      if (pathname === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
      if (pathname === `/api/rd/projects/${project.id}`) return route.fulfill({ json: project });
      if (pathname === '/api/models') return route.fulfill({ json: { success: true, models: [rc.model_selection] } });
      if (pathname === '/api/product_catalog') return route.fulfill({ json: { product_types: [] } });
      if (pathname.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: rc.stage, project_version: project.version, input_revision: rc.input_revision } } });
      if (pathname.endsWith('/evidence-locations')) return route.fulfill({ json: { items: [] } });
      if (pathname.endsWith('/commands') && request.method() === 'POST') {
        const body = request.postDataJSON(); commands.push(body);
        assert.equal(body.expected_version, project.version);
        assert.equal(body.data.case_id, rc.id);
        if (body.command === 'review_requirement') {
          assert.equal(body.data.requirement_id, requirement.id);
          assert.equal(body.data.requirement_revision, requirement.revision);
          assert.equal(body.data.recommendation_batch_id, rc.requirement_recommendations.id);
          assert.equal(body.data.decision, 'reject');
          assert(body.data.reason?.trim());
          requirement.revision++; rc.input_revision++; project.version++;
          rc.source_analysis.adopted_input_revision = rc.input_revision;
          rc.requirement_recommendations.input_revision = rc.input_revision;
          requirement.review = { decision: 'reject', actual_value: null, reason: body.data.reason,
            requirement_revision: requirement.revision, input_revision: rc.input_revision, analysis_id: rc.source_analysis.id,
            recommendation_batch_id: rc.requirement_recommendations.id, recommendation: structuredClone(rc.requirement_recommendations.items[0]), actor: project.owner_id, created_at: stamp };
          return route.fulfill({ json: project });
        }
        if (body.command === 'open_clarification') {
          const target = rc.requirements.find(row => row.id === body.data.requirement_id);
          assert(target && body.data.question && body.data.source_ids.length);
          rc.clarifications.push({ id: `clar-${target.id}`, requirement_id: target.id, question: body.data.question,
            source_ids: body.data.source_ids, input_revision: rc.input_revision, requirement_revision: target.revision,
            status: 'open', revision: 1, required: true, created_at: stamp });
          project.version++;
          return route.fulfill({ json: project });
        }
        if (body.command === 'answer_clarification') {
          const record = rc.clarifications.find(item => item.id === body.data.clarification_id);
          assert(record && body.data.answer && body.data.source_ids.length);
          Object.assign(record, { answer: body.data.answer, answer_source_ids: body.data.source_ids,
            answer_source_snapshots: sources.filter(source => body.data.source_ids.includes(source.id)).map(sourceSnapshot),
            status: 'answered', answered_by: project.owner_id, answered_at: stamp });
          record.revision++; project.version++;
          return route.fulfill({ json: project });
        }
        if (body.command === 'adopt_clarification') {
          const record = rc.clarifications.find(item => item.id === body.data.clarification_id);
          assert.equal(record?.status, 'answered');
          const target = rc.requirements.find(row => row.id === record.requirement_id);
          target.revision++; rc.input_revision++; project.version++;
          target.content = body.data.requirement_content;
          delete target.review;
          target.history = [...(target.history ?? []), { revision: target.revision, clarification_id: record.id, content: target.content }];
          Object.assign(record, { status: 'adopted', adoption: { requirement_revision: target.revision, requirement_content: target.content,
            input_revision: rc.input_revision, recommendation_batch_id: rc.requirement_recommendations.id,
            source_hashes: { tech: 'tech', spec: 'spec' } } });
          record.revision++; rc.stage = 'input';
          rc.source_analysis.adopted_input_revision = rc.input_revision;
          rc.requirement_recommendations.input_revision = rc.input_revision;
          return route.fulfill({ json: project });
        }
        if (body.command === 'confirm_requirements') {
          assert.equal(body.data.expected_input_revision, rc.input_revision);
          assert.equal(body.data.scope, confirmScope);
          assert(rc.requirements.every(row => rc.clarifications.some(record => record.requirement_id === row.id
            && record.status === 'adopted' && record.adoption.requirement_revision === row.revision)), 'each requirement needs an explicit actual result');
          if (rejectNextConfirmation) { rejectNextConfirmation = false; return route.fulfill({ status: 422, json: { error: errorText } }); }
          successfulConfirmations++; project.version++; rc.stage = 'selection';
          rc.requirement_baselines.push({ id: 'baseline', input_revision: rc.input_revision, items: structuredClone(rc.requirements),
            source_refs: sources.map(sourceSnapshot), scope: body.data.scope, status: 'current' });
          rc.business_lifecycle.current_requirement_baseline_id = 'baseline';
          return route.fulfill({ json: project });
        }
        throw new Error(`Unexpected fixture command: ${body.command}`);
      }
      if (!['GET', 'HEAD'].includes(request.method())) throw new Error(`Unexpected fixture write: ${pathname}`);
      return route.fulfill({ json: {} });
    } catch (error) { fixtureErrors.push(error.message); return route.fulfill({ status: 500, json: { error: error.message } }); }
  });

  await page.goto(url('requirements')); await table.waitFor();
  await table.getByText('指标存在差异', { exact: true }).waitFor();
  assert.equal(await continueButton().isDisabled(), true, 'unhandled specification advice must block entry into confirmation');
  assert.equal(commands.length, 0, 'reading readiness cannot write a business decision');
  await capture('01-pending-gate');
  checks.push('pending specification decision blocks the confirmation entry');

  await page.goto(url('decision')); await scope().waitFor();
  assert.equal(await confirmButton().isDisabled(), true, 'direct links cannot bypass readiness');
  await scope().fill(confirmScope);
  await returnButton().click(); await table.waitFor();
  assert.equal(await heading.innerText(), '需求与澄清');
  assert.equal(await scope().inputValue(), confirmScope, 'returning to clarification preserves confirmation scope');
  assert.equal(commands.length, 0, 'returning to clarification is navigation, not a business rollback');
  await capture('02-return-preserves-scope');
  checks.push('blocked direct entry can return to requirements while preserving scope');

  const row = table.locator('tbody tr[data-row-key="r1"]');
  await row.getByRole('button', { name: '不采纳', exact: true }).click();
  await row.getByLabel('环境温度 不采纳原因', { exact: true }).fill('规范适用型号不同，保留客户环境温度要求。');
  await row.getByRole('button', { name: '确认不采纳', exact: true }).click();
  await row.getByText('不采纳 · 待澄清', { exact: true }).waitFor();
  assert.equal(await continueButton().isDisabled(), true, 'rejection and not_found both require explicit clarification');
  assert.equal(requirement.review.decision, 'reject');
  assert.equal(requirement.review.actual_value, null);
  assert.equal(successfulConfirmations, 0);
  await clarify(requirement, '5℃～42℃');
  assert.equal(await continueButton().isDisabled(), true, 'the unmatched requirement is still unresolved');
  await clarify(unmatched, '采用客户接口图 V1');
  assert.equal(await continueButton().isEnabled(), true, 'only explicit adoption of both answers resolves readiness');
  checks.push('rejection leaves --; each row needs an adopted clarification; answer-only does not resolve it');

  const unmatchedRow = table.locator('tbody tr[data-row-key="r2"]');
  await unmatchedRow.getByRole('button', { name: '编辑需求', exact: true }).click();
  await unmatchedRow.getByLabel('需求内容', { exact: true }).fill('尚未保存的接口说明');
  assert.equal(await continueButton().isDisabled(), true, 'unsaved requirement drafts cannot enter confirmation');
  await unmatchedRow.getByRole('button', { name: '取消', exact: true }).click();
  assert.equal(await continueButton().isEnabled(), true);
  assert.equal(await unmatchedRow.getByRole('cell').nth(5).getByText(unmatched.content, { exact: true }).count(), 1);
  checks.push('unsaved requirement edits block confirmation; discard preserves adopted actual result');

  await continueButton().click(); await scope().waitFor();
  assert.equal(await scope().inputValue(), confirmScope);
  await confirmButton().click();
  await save().click();
  await page.getByRole('dialog').getByText(errorText, { exact: true }).waitFor();
  assert.equal(rc.stage, 'input');
  assert.equal(commands.filter(item => item.command === 'confirm_requirements').length, 1);
  await capture('03-server-rejection-recovery');
  await page.getByRole('dialog').getByRole('button', { name: '返回需求与澄清', exact: true }).click();
  await page.getByRole('dialog').waitFor({ state: 'hidden' });
  await table.waitFor();
  assert.equal(await scope().inputValue(), confirmScope);
  assert.equal(rc.stage, 'input');
  assert.equal(successfulConfirmations, 0);
  checks.push('late server rejection offers an in-dialog return and preserves scope without advancing');

  await page.setViewportSize({ width: 390, height: 844 });
  await continueButton().scrollIntoViewIfNeeded();
  assert(await page.locator('.rd-application-shell').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
  await continueButton().click(); await scope().waitFor();
  assert.equal(await scope().inputValue(), confirmScope);
  await returnButton().scrollIntoViewIfNeeded();
  assert(await returnButton().isVisible());
  await capture('04-mobile-ready-confirmation');
  await confirmButton().click(); await save().click();
  await page.getByRole('dialog').waitFor({ state: 'hidden' });
  assert.equal(successfulConfirmations, 1);
  assert.equal(rc.requirement_baselines.length, 1);
  assert.equal(rc.stage, 'selection');
  assert.equal(commands.filter(item => item.command === 'confirm_requirements').length, 2, 'one rejected request followed by one successful explicit confirmation');
  checks.push('resolved requirements can be confirmed once on mobile after recovery');
} catch (error) {
  pageErrors.push(error.stack || String(error));
  await capture('failure').catch(() => {});
} finally {
  const receipt = { passed: checks.length > 0 && !pageErrors.length && !fixtureErrors.length, checks, pageErrors, fixtureErrors, commands };
  await writeFile(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt, null, 2));
  await browser.close();
  if (!receipt.passed) process.exitCode = 1;
}
