/** Continuous journey with API fixtures only. Every business transition starts with a UI action. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'runtime/rd-case-journey-browser';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
const stamp = '2026-11-04T02:00:00Z';
const context = { product_type: 'liquid_cooling_pipeline', product_domain: 'military', development_process: '改型II', cover_phase: 'S', product_series: 'YLZJ', organization_scope: 'non_central_research' };
const sources = ['tech', 'spec'].map(role => ({ id: role, role, name: role === 'tech' ? '连续办理隔离资料—液冷管路原文技术要求及来源版本核对记录.docx' : '连续办理隔离产品规范.pdf', size: 2048, version: 1, sha256: role.repeat(16), created_at: stamp }));
const requirement = { id: 'r1', title: '工作压力', content: '工作压力：0.3 MPa。', source_ids: ['tech'], revision: 1, history: [], evidence: [{ source_id: 'tech', quote: '工作压力：0.3 MPa。' }] };
const workflowIds = ['input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start', 'taskbook'];
const workflowTitles = ['资料受理', '需求确认', '成熟产品比对', '选型决定', '研发启动依据', '研制任务书生成'];
const workflow = { id: 'taskbook-generation', version: '1', template_id: 'taskbook-generation', template_version: '1', template_digest: 'journey-fixed', title: '固定研制任务书流程', status: 'published', node_states: {},
  graph: { nodes: workflowIds.map((id, index) => ({ id, title: workflowTitles[index], role: '研发工程师', deliverables: [], position: { x: index * 240, y: 0 },
    ...(['confirm_requirements', 'selection_decision', 'rd_start'].includes(id) ? { gate: { confirm_requirements: 'requirements', selection_decision: 'selection', rd_start: 'rd_start' }[id] } : {}),
    ...(id === 'taskbook' ? { workpackage_definition_id: 'taskbook' } : {}) })), edges: workflowIds.slice(1).map((id, index) => ({ id: 'e-' + id, source: workflowIds[index], target: id })) } };
const actionNames = { resolve_context: '解析与核对参数', template_plan: '模板路由与装配计划', content_completion: '内容补齐与证据核对', generate: '生成研制任务书', verify: '质量验证' };
const nodes = Object.keys(actionNames).map((id, index, ids) => ({ id, action_id: id, action_version: '1', depends_on: index ? [ids[index - 1]] : [], required: true, status: 'draft', result: null, attempt: 0 }));
const catalog = { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书', status: 'published' }], project_workflow_templates: [workflow], actions: Object.entries(actionNames).map(([id, title]) => ({ id, title, version: '1' })),
  workpackage_definitions: [{ id: 'taskbook', version: '2', title: '任务书装配与校验', stages: ['planning'], business_node_id: 'taskbook_planning', required_actions: Object.keys(actionNames), optional_actions: [], nodes }] };
const project = { id: 'journey-fixture', title: '隔离测试 · 连续办理导航', version: 1, owner_id: 'fixture-owner', members: [], events: [], cases: [{
  id: 'case-fixture', title: '隔离测试 · 连续办理导航', scenario_id: 'taskbook', stage: 'input', status: 'active', input_revision: 1,
  context: {}, sources: structuredClone(sources), source_selection: { tech: 'tech', spec: 'spec' }, model_selection: { provider: 'fixture', name: 'isolated-model', id: '1' },
  requirements: [], clarifications: [], comparisons: [], decisions: [], review_bundles: [], requirement_baselines: [], rd_activations: [], workpackages: [], product_route: null, composition_route: null,
  workflow_templates: { project: workflow }, project_workflow_status: { status: 'pending', terminal_node_id: 'taskbook' },
  business_lifecycle: { policy_version: 'v2', rd_activation_state: 'not_started', review_mode: 'local_review', local_review_enabled: true, can_record_decision: true, can_confirm_requirements: true },
}] };
const current = () => project.cases[0];
const commands = [], checks = [], screenshots = [], pageErrors = [], routeErrors = [], unexpected = [], apiWrites = [];
const failures = new Set(['adopt_source_analysis', 'confirm_requirements', 'record_selection_decision', 'authorize_rd_start', 'adopt_taskbook_flow']);
let submittedAt = 0, pollReads = 0;
let actorId = 'fixture-owner';
let sessionHold = null;
let checkpoint = 'initial';
page.on('pageerror', error => pageErrors.push(error.message));
page.on('dialog', dialog => dialog.type() === 'beforeunload' ? dialog.accept() : dialog.dismiss());
const nav = () => page.getByRole('navigation', { name: '办理步骤', exact: true });
const step = name => nav().getByRole('button', { name, exact: true });
const visibleHeading = () => page.locator('.rd-case-heading h1');
async function viewed(name) { await step(name).and(page.locator('[aria-current="step"]')).waitFor(); }
async function capture(name) { await page.screenshot({ path: join(output, name + '.png') }); screenshots.push(name + '.png'); }
async function choose(label, option, within = page) {
  await within.getByRole('combobox', { name: label, exact: true }).locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').click();
  await page.getByRole('option', { name: option, exact: true }).click();
}
async function next() { const button = page.locator('.rd-case-continuation').getByRole('button'); await button.click(); }
async function confirm() { await page.getByRole('dialog').getByRole('button', { name: '保存本地决定', exact: true }).click(); }
async function assertNoOverflow() {
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'document does not overflow horizontally');
  assert(await page.locator('.rd-application-shell').evaluate(element => element.scrollWidth <= element.clientWidth + 1), 'application does not overflow horizontally');
}
async function layouts(label, overview = false) {
  for (const width of [1440, 1920, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.locator(width === 390 ? '.rd-case-journey' : '#rd-case-workarea').evaluate(element => element.scrollIntoView({ block: 'start' }));
    await assertNoOverflow();
    assert.equal(await nav().locator('[aria-current="step"]').count(), overview ? 0 : 1, 'only an open editor is marked as the viewed step');
    assert.equal(await visibleHeading().count(), 1, 'each work surface has one main title');
    assert(await visibleHeading().isVisible());
    await capture(`${label}-${width}`);
    if (width === 390) {
      await page.locator('#rd-case-workarea').evaluate(element => element.scrollIntoView({ block: 'start' }));
      await capture(`${label}-${width}-workface`);
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
}
async function failure(name) {
  await page.getByRole('alert').filter({ hasText: `隔离失败：${name}` }).first().waitFor();
}
async function saved(label) {
  checkpoint = label;
  await page.locator('.rd-unsaved-state').waitFor({ state: 'hidden' });
}
async function goHome() {
  await page.getByRole('button', { name: '我的工作', exact: true }).click();
  await page.getByRole('heading', { name: '我的工作', level: 1, exact: true }).waitFor();
}
async function continueFromHome(completed = false) {
  await page.getByRole('table', { name: '最近项目与当前工作', exact: true }).getByRole('button', { name: completed ? '查看成果' : '继续办理', exact: true }).click();
}

try {
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (!['GET', 'HEAD'].includes(request.method())) apiWrites.push({ method: request.method(), path });
    try {
      if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
      if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: context.product_type, label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }] }] } });
      if (path === '/api/models') return route.fulfill({ json: { success: true, models: [current().model_selection] } });
      if (path === '/api/rd/session') {
        const hold = sessionHold;
        if (hold) { hold.started(); await hold.wait; }
        return route.fulfill({ json: { actor_id: actorId, local_mode: true } });
      }
      if (path === '/api/rd/catalog') return route.fulfill({ json: catalog });
      if (path === '/api/rd/catalog/items') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 5, total_pages: 1 } });
      if (path === '/api/rd/governance/session') return route.fulfill({ json: { can_edit_workflows: false, can_publish_workflows: false, can_prepare_templates: false, can_review_templates: false, can_publish_templates: false, local_bootstrap: true } });
      if (path === '/api/rd/workflow-templates') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 5, total_pages: 1 } });
      if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
      if (path === '/api/rd/projects/journey-fixture') {
        if (submittedAt) {
          pollReads++;
          if (Date.now() - submittedAt > 3500 && current().workpackages[0].status === 'running') {
            const wp = current().workpackages[0];
            wp.status = 'completed';
            wp.nodes = wp.nodes.map(node => ({ ...node, status: 'completed', completed_at: stamp, result: node.id === 'verify' ? { delivery_approved: true, blockers: [] } : {} }));
            wp.artifacts = [{ id: 'doc-fixture', kind: 'taskbook', name: '连续办理隔离复核稿.docx', sha256: 'fixture-output' }];
            current().project_workflow_status.status = 'completed'; project.version++;
          }
        }
        return route.fulfill({ json: project });
      }
      if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: current().stage, project_version: project.version, input_revision: current().input_revision } } });
      if (path.endsWith('/analysis')) {
        assert.equal(request.method(), 'POST'); assert.equal(request.postDataJSON().expected_version, project.version);
        current().source_analysis = { id: 'analysis-fixture', status: 'proposed', input_revision: current().input_revision, created_at: stamp, source_hashes: Object.fromEntries(sources.map(source => [source.id, source.sha256])), model_selection: current().model_selection,
          context: Object.fromEntries(Object.entries(context).map(([field, value]) => [field, { value, status: 'proposed', reason: '隔离资料明确记载', evidence: [{ source_id: 'tech', quote: '隔离参数依据' }] }])), requirements: [requirement], warnings: [] };
        project.version++; return route.fulfill({ json: project });
      }
      if (path.endsWith('/commands')) {
        assert.equal(request.method(), 'POST');
        const body = request.postDataJSON(), { command: name, data } = body, c = current(), life = c.business_lifecycle;
        commands.push({ key: request.headers()['idempotency-key'], body: structuredClone(body) });
        assert.equal(body.expected_version, project.version); assert.equal(data.case_id, c.id); assert(request.headers()['idempotency-key']);
        if (failures.delete(name)) return route.fulfill({ status: 503, json: { error: `隔离失败：${name}，原填写保留。` } });
        if (name === 'adopt_source_analysis') {
          assert.equal(data.analysis_id, c.source_analysis.id); c.context = structuredClone(context); c.requirements = [structuredClone(requirement)]; c.input_revision++;
          c.source_analysis.status = 'adopted'; c.source_analysis.adopted_input_revision = c.input_revision;
        } else if (name === 'save_requirement') {
          assert(data.title && data.content && data.source_ids.includes('tech'));
          Object.assign(c.requirements.find(item => item.id === data.id), { title: data.title, content: data.content, source_ids: data.source_ids });
          c.input_revision++; c.stage = 'input';
        } else if (name === 'confirm_requirements') {
          assert.equal(data.expected_input_revision, c.input_revision); assert(data.scope); assert(data.source_ids.includes('tech'));
          c.requirement_baselines.push({ id: 'baseline-fixture', input_revision: c.input_revision, requirements: structuredClone(c.requirements), status: 'current', scope: data.scope });
          life.current_requirement_baseline_id = 'baseline-fixture'; c.stage = 'selection';
        } else if (name === 'save_comparison') {
          assert.equal(data.rows.length, 1); assert.equal(data.rows[0].assessment, 'match'); assert(data.rows[0].reason); assert(data.rows[0].source_ids.includes('spec'));
          c.comparisons.push({ ...structuredClone(data), id: 'comparison-' + data.kind, revision: 1, input_revision: c.input_revision, status: 'manual_record', statistics: { total: 1, matches: 1, partial: 0, gap: 0, unknown: 0 }, sha256: data.kind });
        } else if (name === 'record_route_decision') {
          assert.equal(data.comparison_id, 'comparison-' + (data.axis === 'product' ? 'product' : 'document'));
          c[data.axis === 'product' ? 'product_route' : 'composition_route'] = { ...structuredClone(data), actor: 'fixture-owner', created_at: stamp, comparison_revision: 1 };
        } else if (name === 'prepare_selection_review') {
          assert(c.product_route && c.composition_route);
          const bundle = { id: 'selection-bundle', kind: 'selection', status: 'submitted', digest: 'fixed-report-digest', input_revision: c.input_revision, created_at: stamp, fixed_objects: { requirements: c.requirements },
            report: { title: '固定选型报告', rows: c.comparisons[0].rows, statistics: c.comparisons[0].statistics, product_route: c.product_route, composition_route: c.composition_route } };
          c.review_bundles.push(bundle); life.current_selection_bundle_id = bundle.id;
        } else if (name === 'record_selection_decision') {
          assert.equal(data.bundle_digest, 'fixed-report-digest'); assert(data.scope && data.rationale);
          const decision = { ...structuredClone(data), id: 'decision-' + project.version, kind: 'selection', actor: 'fixture-owner', created_at: stamp, input_revision: c.input_revision };
          c.decisions.push(decision); c.review_bundles[0].status = data.verdict;
          life.current_selection_decision_id = decision.id;
        } else if (name === 'authorize_rd_start') {
          assert.equal(data.selection_decision_id, life.current_selection_decision_id); assert(data.scope && data.rationale);
          life.rd_activation_state = 'active'; life.current_activation_id = 'activation-fixture'; life.rd_project_code = 'RD-FIXTURE';
          c.rd_activations.push({ id: life.current_activation_id, status: 'active', ...structuredClone(data) }); c.stage = 'planning';
        } else if (name === 'adopt_taskbook_flow') {
          if (life) assert.equal(life.rd_activation_state, 'active');
          assert.equal(data.workflow_id, workflow.id); assert.equal(data.workflow_version, '1'); assert(data.scope && data.rationale);
          c.taskbook_binding = { id: 'binding-fixture', revision: 1, input_revision: c.input_revision, status: 'current', workflow: c.workflow_templates?.project ? workflow : catalog.research_workflow_templates[0], scope: data.scope, rationale: data.rationale, source_ids: ['tech', 'spec'], fingerprint: 'binding-digest', adopted_at: stamp, document_template: { title: '隔离受控任务书模板' } };
        } else if (name === 'pull_workpackage') {
          assert.equal(data.definition_id, 'taskbook'); assert.equal(data.definition_version, '2'); assert.equal(c.taskbook_binding.input_revision, c.input_revision);
          c.workpackages.push({ id: 'wp-fixture', definition_id: 'taskbook', definition_version: '2', business_node_id: 'taskbook_planning', title: '任务书装配与校验', stage: 'planning', status: 'draft', plan_revision: 1, nodes: structuredClone(nodes), artifacts: [], obligations: [], blocked_reasons: [] });
        } else if (name === 'create_flow_draft') {
          assert.equal(data.workpackage_id, 'wp-fixture');
          c.flow_drafts = [{ id: 'draft-fixture', workpackage_id: 'wp-fixture', definition_id: 'taskbook', definition_version: '2', revision: 1, input_revision: c.input_revision, digest: 'draft-digest', semantic_digest: 'semantic-digest', layout_digest: 'layout-digest', history: [], confirmed_fields: [], conflicts: [],
            graph: { nodes: nodes.map((node, index) => ({ ...structuredClone(node), title: actionNames[node.id], role: '研发工程师', deliverables: [], position: { x: 24 + index % 3 * 240, y: 24 + Math.floor(index / 3) * 130 } })), edges: nodes.flatMap(node => node.depends_on.map(id => ({ id: id + '-' + node.id, source: id, target: node.id }))) } }];
        } else if (name === 'validate_flow_draft') {
          assert.equal(data.draft_id, 'draft-fixture'); c.flow_drafts[0].validation = { valid: true, errors: [], warnings: [] };
        } else if (name === 'prepare_execution_bundle') {
          const draft = c.flow_drafts[0]; assert.equal(data.draft_id, draft.id); assert(draft.validation.valid);
          c.execution_candidates = [{ id: 'candidate-fixture', digest: 'candidate-digest', draft_id: draft.id, draft_revision: draft.revision, workpackage_id: 'wp-fixture', input_revision: c.input_revision, graph: structuredClone(draft.graph), compiled_plan: structuredClone(nodes), resource_locks: [], mapping: [], validation: { valid: true, errors: [], warnings: [] }, diff: { added: [], removed: [], changed: [] } }];
        } else if (name === 'adopt_execution_bundle') {
          assert.equal(data.candidate_id, 'candidate-fixture'); assert.equal(data.candidate_digest, 'candidate-digest');
          c.execution_adoptions = [{ id: 'adoption-fixture', candidate_id: data.candidate_id, candidate_digest: data.candidate_digest, workpackage_id: 'wp-fixture', actor: 'fixture-owner', adopted_at: stamp }];
          c.workpackages[0].execution_adoption_id = 'adoption-fixture';
        } else if (name === 'submit_workpackage') {
          assert.equal(data.workpackage_id, 'wp-fixture');
          assert.equal(c.workpackages[0].execution_adoption_id, 'adoption-fixture');
          const wp = c.workpackages[0]; wp.status = 'running'; wp.run_id = 'run-fixture'; wp.snapshot = { input_revision: c.input_revision, binding_id: c.taskbook_binding.id, submitted_at: stamp }; submittedAt = Date.now();
          wp.nodes[0].status = 'running'; c.project_workflow_status.status = 'running';
        } else assert.fail('Unhandled command ' + name);
        project.version++; return route.fulfill({ json: project });
      }
      unexpected.push({ method: request.method(), path });
      return route.fulfill({ status: 500, json: { error: 'Unlisted fixture request ' + path } });
    } catch (error) { routeErrors.push(error.message); return route.fulfill({ status: 500, json: { error: error.message } }); }
  });
  await page.goto(base + '/?rd_view=home');
  await continueFromHome(); await viewed('资料识别');
  assert.equal(commands.length, 0, 'first continue opens pending sources without mutating the project');
  assert.equal(await page.getByRole('region', { name: '资料分析', exact: true }).locator('dt').count(), 4);
  await capture('resume-01-first-continue-sources');
  await page.getByRole('button', { name: '成果概览', exact: true }).click();
  await nav().waitFor();
  assert.equal(await nav().getByRole('button').count(), 5, 'fixed workflow stops at taskbook generation');
  assert.equal(await nav().locator('[aria-current], .is-viewed').count(), 0, 'overview shows the pending business step without claiming an editor is open');
  assert.equal(await page.locator('.rd-outcome-heading').getByRole('button').count(), 1, 'overview has one main continuation');
  await layouts('00-initial-overview', true);
  await page.getByRole('button', { name: '项目流程', exact: true }).click();
  await page.getByRole('region', { name: '项目固定流程', exact: true }).waitFor();
  assert.equal(await nav().locator('[aria-current], .is-viewed').count(), 0, 'project process does not claim a business editor is open');
  await page.getByRole('navigation', { name: '当前业务流程视图', exact: true }).getByRole('button', { name: '当前成果', exact: true }).click();
  await page.getByRole('button', { name: '查看全部成果与依据 →', exact: true }).click();
  await page.getByRole('heading', { name: '资料与依据', level: 1, exact: true }).waitFor();
  assert.equal(await nav().locator('[aria-current], .is-viewed').count(), 0, 'evidence does not claim a business editor is open');
  await page.getByRole('navigation', { name: '当前业务流程视图', exact: true }).getByRole('button', { name: '当前成果', exact: true }).click();
  for (const title of ['需求确认', '选型与启动', '编制准备', '编排与生成']) { assert(await step(title).isDisabled()); assert(await step(title).getAttribute('title')); }
  const requirementReason = await step('需求确认').getAttribute('title');
  const requirementHint = nav().locator('.rd-journey-step-hint[tabindex]').filter({ has: page.getByRole('button', { name: '需求确认', exact: true }) });
  assert.equal(await requirementHint.getAttribute('aria-label'), `需求确认：${requirementReason}`);
  assert.equal(await nav().locator('.rd-journey-step-hint[tabindex]').count(), 4, 'only unavailable steps add a keyboard focus target for their reason');
  const writesBeforeHint = apiWrites.length;
  await step('资料识别').focus(); await page.keyboard.press('Tab');
  assert(await requirementHint.evaluate(element => element === document.activeElement), 'Tab reaches the unavailable requirement step reason');
  const reasonTooltip = page.getByRole('tooltip').filter({ hasText: requirementReason });
  await reasonTooltip.waitFor();
  assert.equal(await reasonTooltip.innerText(), requirementReason);
  assert.equal(apiWrites.length, writesBeforeHint, 'keyboard focus on an unavailable step sends no API writes');
  await step('资料识别').focus(); await page.mouse.move(0, 0);
  await reasonTooltip.waitFor({ state: 'hidden' });
  await requirementHint.click(); await reasonTooltip.waitFor();
  assert.equal(await reasonTooltip.innerText(), requirementReason);
  assert(await step('需求确认').isDisabled());
  assert.equal(await nav().locator('[aria-current], .is-viewed').count(), 0, 'opening a reason does not navigate away from overview');
  assert.equal(apiWrites.length, writesBeforeHint, 'clicking an unavailable step sends no API writes');
  assert.equal(apiWrites.length, 0);
  await page.waitForFunction(reason => [...document.querySelectorAll('.ant-tooltip:not(.ant-tooltip-hidden)')].some(element => element.textContent === reason && getComputedStyle(element).opacity === '1'), requirementReason);
  await capture('00-disabled-step-reason');
  await step('资料识别').focus(); await page.mouse.move(0, 0);
  checks.push('unavailable requirement step reason is reachable by Tab and click, with its button still disabled and zero API writes');
  await step('资料识别').focus(); await page.keyboard.press('Enter'); await viewed('资料识别');
  assert.equal(commands.length, 0, 'step navigation sends no business command');
  await layouts('01-sources');
  await page.getByRole('button', { name: '分析上传资料', exact: true }).click();
  const adopt = page.getByRole('button', { name: '确认采用', exact: true });
  await adopt.click(); await failure('adopt_source_analysis'); await viewed('资料识别');
  assert.equal(current().requirements.length, 0);
  await capture('02-adoption-error');
  await adopt.click(); await viewed('需求确认');
  await saved('source adoption');
  assert.equal(current().stage, 'input'); assert.equal(current().decisions.length, 0);
  await layouts('03-requirements');
  checks.push('future steps disabled with reason; keyboard navigation is read-only; adoption failure stays and success opens requirements');

  const writesBeforeResume = apiWrites.length;
  await goHome(); await continueFromHome(); await viewed('需求确认');
  assert.equal(current().stage, 'input', 'the last editor is restored even when adoption has not advanced the server stage');
  await capture('resume-02-requirements-before-stage-advance');
  await page.getByRole('button', { name: '成果概览', exact: true }).click();
  await page.getByRole('heading', { name: '当前成果', level: 1, exact: true }).waitFor();
  assert.equal(await nav().locator('[aria-current], .is-viewed').count(), 0, 'explicit overview stays open');
  await goHome(); await continueFromHome(); await viewed('需求确认');
  await page.reload(); await viewed('需求确认');
  assert.equal(apiWrites.length, writesBeforeResume, 'returning home, continuing and reloading only restore navigation');
  actorId = 'fixture-other-account';
  await page.reload(); await viewed('需求确认');
  await step('资料识别').click(); await page.reload(); await viewed('资料识别');
  actorId = 'fixture-owner';
  await page.reload(); await viewed('需求确认');
  assert.equal(apiWrites.length, writesBeforeResume, 'account-specific navigation does not alter project data');
  await capture('resume-03-account-isolation-and-refresh');
  checks.push('first continue opens sources; same-stage requirements editor survives home/overview/reload; different account positions are isolated and navigation sends no writes');

  await page.getByRole('button', { name: '编辑需求', exact: true }).click();
  await page.getByLabel('需求内容', { exact: true }).fill('工作压力：0.3 MPa。保留原文来源并补充核对说明。');
  const assistantLauncher = page.getByRole('button', { name: '打开小航助手', exact: true });
  assert(await assistantLauncher.evaluate(element => !!element.closest('.rd-journey-heading-actions')));
  await assistantLauncher.click();
  const assistantDialog = page.getByRole('dialog', { name: `${current().title} · 小航助手`, exact: true });
  await assistantDialog.getByRole('textbox', { name: '询问当前案例', exact: true }).fill('跨步骤保留的助手草稿，不发送。');
  await assistantDialog.getByRole('button', { name: '收起小航助手', exact: true }).click();
  await step('资料识别').click();
  await assistantLauncher.click();
  assert.equal(await assistantDialog.getByRole('textbox', { name: '询问当前案例', exact: true }).inputValue(), '跨步骤保留的助手草稿，不发送。');
  await assistantDialog.getByRole('textbox', { name: '询问当前案例', exact: true }).fill('');
  await assistantDialog.getByRole('button', { name: '收起小航助手', exact: true }).click();
  const beforeRevisit = commands.length;
  await next(); await viewed('需求确认');
  assert.equal(commands.length, beforeRevisit, 'source continuation returns to requirements without any write');
  assert.equal(await page.getByLabel('需求内容', { exact: true }).inputValue(), '工作压力：0.3 MPa。保留原文来源并补充核对说明。');
  await page.getByRole('button', { name: '保存需求记录', exact: true }).click(); await viewed('需求确认');
  await saved('requirement save');
  assert.equal(current().stage, 'input');
  const mutationsBeforeNext = commands.length;
  await next(); await page.getByLabel('确认范围', { exact: true }).fill('确认当前液冷工作压力及来源');
  assert.equal(commands.length, mutationsBeforeNext, 'continue navigation does not confirm requirements');
  await page.getByRole('button', { name: '确认需求并进入选型', exact: true }).click(); await confirm();
  await failure('confirm_requirements'); await viewed('需求确认');
  assert.equal(await page.getByLabel('确认范围', { exact: true }).inputValue(), '确认当前液冷工作压力及来源');
  await confirm(); await viewed('选型与启动');
  await saved('requirements confirmation');
  assert.equal(current().product_route, null); assert.equal(current().composition_route, null);
  checks.push('requirement draft survives step changes; ordinary save stays; explicit confirmation failure preserves scope and retry opens comparison');

  // The pending server step and previous remembered page both differ from requirements,
  // so falling back after losing the pending personal write cannot pass this assertion.
  await step('资料识别').click();
  await goHome();
  const writesBeforeSlowIdentity = apiWrites.length;
  let releaseSession, sessionStarted;
  const sessionWaiting = new Promise(resolve => { sessionStarted = resolve; });
  sessionHold = { started: sessionStarted, wait: new Promise(resolve => { releaseSession = resolve; }) };
  await continueFromHome(); await sessionWaiting; await viewed('选型与启动');
  await step('需求确认').click(); await viewed('需求确认');
  await page.getByRole('button', { name: '成果概览', exact: true }).click();
  await page.getByRole('heading', { name: '当前成果', level: 1, exact: true }).waitFor();
  const identityResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/rd/session');
  sessionHold = null; releaseSession();
  await (await identityResponse).finished();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert(await page.getByRole('heading', { name: '当前成果', level: 1, exact: true }).isVisible(), 'a late identity response does not replace the explicitly opened overview');
  assert.equal(await nav().locator('[aria-current], .is-viewed').count(), 0);
  await capture('resume-05-delayed-identity-keeps-overview');
  await goHome(); await continueFromHome(); await viewed('需求确认');
  assert.equal(current().stage, 'selection', 'the restored requirement editor is distinct from the current selection task');
  assert.equal(apiWrites.length, writesBeforeSlowIdentity, 'late identity only persists the pending navigation choice');
  checks.push('delayed identity preserves the requirement editor selected before overview without replacing overview or issuing writes; next continue restores requirements instead of the active selection task');

  await goHome();
  let releaseInUseSession, inUseSessionStarted;
  const inUseSessionWaiting = new Promise(resolve => { inUseSessionStarted = resolve; });
  sessionHold = { started: inUseSessionStarted, wait: new Promise(resolve => { releaseInUseSession = resolve; }) };
  await continueFromHome(); await inUseSessionWaiting; await viewed('选型与启动');
  const unsavedReason = page.locator('.rd-route-editor').filter({ has: page.getByRole('heading', { name: '产品研制分类', exact: true }) }).getByLabel('决定理由', { exact: true });
  await unsavedReason.fill('身份返回前填写的决定理由，仅保留草稿，不提交。');
  await page.locator('.rd-unsaved-state').waitFor();
  const inUseIdentityResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/rd/session');
  sessionHold = null; releaseInUseSession();
  await (await inUseIdentityResponse).finished();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await viewed('选型与启动');
  assert.equal(await unsavedReason.inputValue(), '身份返回前填写的决定理由，仅保留草稿，不提交。');
  assert(await page.locator('.rd-unsaved-state').isVisible(), 'late identity leaves the active unsaved editor intact');
  assert.equal(apiWrites.length, writesBeforeSlowIdentity, 'editing during delayed identity sends no backend mutation');
  await capture('resume-06-delayed-identity-keeps-dirty-editor');
  await unsavedReason.fill(''); await saved('late identity draft cleanup');
  checks.push('late identity does not replace an edited default selection page with the saved requirement page; unsaved reason stays intact and clearing it leaves no writes');
  await step('选型与启动').click(); await viewed('选型与启动');

  await page.getByText('登记一份逐项比对', { exact: true }).click();
  for (const [kind, label] of [['product', '产品比对 · 产品研制分类依据'], ['document', '文档比对 · 任务书编制策略依据']]) {
    await choose('比对对象', label);
    await page.getByLabel('比对名称', { exact: true }).fill(kind === 'product' ? '连续链产品比对' : '连续链文档比对');
    await page.getByRole('group', { name: '比对总体依据', exact: true }).getByRole('checkbox').nth(1).check();
    const row = page.locator('.rd-record-new .rd-record-item').filter({ hasText: '工作压力' });
    if ((await row.getAttribute('open')) === null) await row.locator('summary').click();
    await choose('核对结果', '满足', row);
    await row.getByLabel('候选值或描述', { exact: true }).fill('0.3 MPa');
    await row.getByLabel('依据说明', { exact: true }).fill('按当前产品规范逐条核对');
    await row.getByRole('group', { name: '本项来源', exact: true }).getByRole('checkbox').nth(1).check();
    await page.getByRole('button', { name: '保存逐项比对', exact: true }).click();
    await page.locator('.rd-comparison-summary').filter({ hasText: kind === 'product' ? '连续链产品比对' : '连续链文档比对' }).waitFor();
    await saved(kind + ' comparison');
    await viewed('选型与启动');
  }
  for (const [axis, title, option, comparison, button] of [['product', '产品研制分类', '改型', '连续链产品比对', '保存产品分类决定'], ['composition', '任务书编制策略', '直接使用现有模板', '连续链文档比对', '保存编制策略决定']]) {
    const editor = page.locator('.rd-route-editor').filter({ has: page.getByRole('heading', { name: title, exact: true }) });
    await choose(title, option, editor);
    await editor.getByLabel('决定理由', { exact: true }).fill('按固定需求及逐项证据记录实际决定');
    await editor.getByRole('checkbox').first().check();
    await choose('采用的当前逐项比对（必选）', `${comparison} · v1 · 满足 1/1`, editor);
    await editor.getByRole('button', { name: button, exact: true }).click();
    await editor.getByText('已记录决定', { exact: true }).waitFor(); await viewed('选型与启动');
    await saved(axis + ' route');
    assert.equal(current().rd_activations.length, 0);
  }
  await layouts('04-comparisons-routes');
  await next();
  await page.getByRole('button', { name: '生成固定选型报告', exact: true }).click();
  await page.getByLabel('决定范围', { exact: true }).fill('核对当前固定选型报告');
  await page.getByLabel('决定说明', { exact: true }).fill('依据固定需求、两类比对及两个决定；非正式电子审签');
  await page.getByRole('button', { name: '退回选型报告', exact: true }).click(); await confirm();
  await failure('record_selection_decision'); await viewed('选型与启动'); assert.equal(current().decisions.length, 0);
  await confirm();
  await page.getByRole('dialog').waitFor({ state: 'hidden' });
  await viewed('选型与启动'); assert.equal(current().decisions.at(-1).verdict, 'rejected');
  assert.equal(current().stage, 'selection'); assert.equal(current().rd_activations.length, 0);
  await page.getByLabel('决定范围', { exact: true }).fill('再次核对当前固定选型报告');
  await page.getByLabel('决定说明', { exact: true }).fill('已完成退回事项复核，独立批准选型');
  await page.getByRole('button', { name: '批准选型报告', exact: true }).click(); await confirm();
  await page.getByRole('button', { name: '确认研发启动', exact: true }).waitFor();
  assert.equal(current().stage, 'selection'); assert.equal(current().rd_activations.length, 0); assert.equal(current().workpackages.length, 0);
  await capture('05-selection-approved-separate-activation');
  await page.getByLabel('决定范围', { exact: true }).fill('按选型结论启动任务书编制');
  await page.getByLabel('决定说明', { exact: true }).fill('独立确认研发启动');
  await page.getByRole('button', { name: '确认研发启动', exact: true }).click(); await confirm();
  await failure('authorize_rd_start'); await viewed('选型与启动'); assert.equal(current().stage, 'selection');
  await confirm(); await viewed('编制准备'); assert.equal(current().rd_activations.length, 1); assert.equal(current().workpackages.length, 0);
  await saved('RD activation');
  checks.push('both comparisons and route decisions entered through UI; fixed report approval and RD activation remain separate explicit actions; failures remain in place');

  await page.getByLabel('本次任务书编制范围', { exact: true }).fill('按当前工作压力形成任务书复核稿');
  await page.getByLabel('采用依据与差异处理边界', { exact: true }).fill('固定需求、比对、路线与六参数来源');
  await layouts('06-preparation');
  const bind = page.getByRole('button', { name: '固定任务书输入', exact: true });
  await bind.click(); await failure('adopt_taskbook_flow'); await viewed('编制准备');
  assert.equal(await page.getByLabel('本次任务书编制范围', { exact: true }).inputValue(), '按当前工作压力形成任务书复核稿');
  await bind.click(); await viewed('编排与生成'); assert.equal(current().workpackages.length, 0);
  await saved('taskbook binding');
  await layouts('07-workpackage-empty');
  await choose('当前阶段可拉取的工作包', '任务书装配与校验 · V2');
  await page.getByRole('button', { name: '拉取工作包', exact: true }).click();
  await page.getByRole('button', { name: '建立流程草稿', exact: true }).click();
  await page.locator('.rd-flow-designer .rd-graph-node').first().waitFor();
  assert.equal(await page.locator('.rd-flow-designer .rd-graph-node').count(), nodes.length);
  await page.getByRole('button', { name: '校验草稿', exact: true }).click();
  await page.getByRole('region', { name: '草稿校验结果', exact: true }).waitFor();
  await page.getByRole('button', { name: '准备执行候选', exact: true }).click();
  await page.getByRole('button', { name: '采用此执行候选', exact: true }).click();
  assert.equal(commands.filter(item => item.body.command === 'adopt_execution_bundle').length, 0);
  await page.getByRole('dialog').getByRole('button', { name: '采用固定候选', exact: true }).click();
  await saved('execution adoption');
  assert.equal(current().workpackages[0].status, 'draft', 'adopting the execution candidate does not submit');
  await capture('08-workpackage-plan');
  await page.getByRole('button', { name: '确认提交执行', exact: true }).click();
  assert.equal(commands.filter(item => item.body.command === 'submit_workpackage').length, 0, 'opening confirmation does not submit');
  await page.getByRole('dialog').getByRole('button', { name: '固定快照并执行', exact: true }).click();
  await page.locator('.rd-workpackage-summary .running').waitFor(); await viewed('编排与生成');
  await capture('09-executing');
  await step('资料识别').click();
  await page.reload(); await viewed('编排与生成');
  assert.equal(commands.filter(item => item.body.command === 'submit_workpackage').length, 1, 'running execution takes priority over a saved source page without resubmission');
  await page.locator('.rd-workpackage-summary .completed').waitFor(); await viewed('编排与生成');
  assert(pollReads >= 1, 'completion comes through the normal project polling after user submission');
  await page.getByRole('button', { name: '成果概览', exact: true }).click();
  await page.getByRole('heading', { name: '研制任务书生成成果', exact: true }).waitFor();
  await page.getByRole('link', { name: /连续办理隔离复核稿/ }).first().waitFor();
  assert.equal(await page.getByRole('button', { name: /批准任务书范围/ }).count(), 0);
  await layouts('10-completed-outcome', true);
  await goHome(); await continueFromHome(true);
  await page.getByRole('heading', { name: '当前成果', level: 1, exact: true }).waitFor();
  assert.equal(await nav().locator('[aria-current], .is-viewed').count(), 0, 'completed workflow opens overview regardless of its previous execution editor');
  await page.reload();
  await page.getByRole('heading', { name: '当前成果', level: 1, exact: true }).waitFor();
  await capture('resume-04-completed-overview');
  checks.push('binding failure keeps draft and retry opens workpackages; pull/create draft/validate/prepare candidate/adopt/explicit submit execute in place; normal polling completes fixed workflow and outcome keeps artifact link');
  for (const name of ['adopt_source_analysis', 'confirm_requirements', 'record_selection_decision', 'authorize_rd_start', 'adopt_taskbook_flow']) {
    const calls = commands.filter(item => item.body.command === name); assert.equal(calls.length, name === 'record_selection_decision' ? 3 : 2); assert.equal(calls[0].key, calls[1].key, name + ' retry preserves idempotency');
  }
  assert.equal(commands.filter(item => item.body.command === 'submit_workpackage').length, 1);
  assert(commands.every(item => item.body.command !== 'advance_stage'));

  // A separate legacy starting fixture checks only the navigation branch affected by this change.
  // It does not replace any segment of the continuous fixed-workflow chain above.
  submittedAt = 0;
  delete current().workflow_templates; delete current().project_workflow_status; delete current().business_lifecycle;
  delete current().taskbook_binding; delete current().flow_drafts; delete current().execution_candidates; delete current().execution_adoptions;
  current().workpackages = []; current().stage = 'planning'; project.version++;
  catalog.research_workflow_templates = [{ ...workflow, product_route: 'modification', nodes: ['taskbook', 'scheme', 'detail', 'integration', 'verification', 'delivery'] }];
  await page.reload();
  await nav().waitFor();
  await viewed('编制准备');
  assert.equal(await nav().getByRole('button').count(), 7, 'legacy retains delivery and reuse steps');
  await step('编制准备').click();
  await choose('研发流程模板', '固定研制任务书流程 · V1');
  await page.getByLabel('本次研发工作范围', { exact: true }).fill('旧案例范围与后续工程节点保持独立');
  await page.getByLabel('采用依据与差异处理边界', { exact: true }).fill('旧生命周期采用只固定当前输入');
  await page.getByRole('button', { name: '采用流程并固定任务书输入', exact: true }).click();
  await page.getByText('已采用固定版本', { exact: false }).first().waitFor();
  await viewed('编制准备'); assert(await step('编排与生成').isDisabled());
  await next();
  await page.getByRole('button', { name: '记录阶段决定', exact: true }).waitFor();
  assert.equal(current().stage, 'planning'); assert.equal(current().workpackages.length, 0);
  await capture('11-legacy-preparation-stage-gate');
  checks.push('legacy branch retains seven steps; binding stays in preparation and requires its original explicit stage decision before execution');
  assert.deepEqual(pageErrors, []); assert.deepEqual(routeErrors, []); assert.deepEqual(unexpected, []);
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ status: 'passed', checks, screenshots, commands: commands.map(item => item.body.command), fixtureApiWrites: apiWrites.length, pollReads, pageErrors, routeErrors, unexpected, realApiRequests: 0, realModelCalls: 0, evidence_category: 'isolated_browser_api_fixture', notCovered: ['real model generation', 'formal engineering signature', 'legacy engineering/delivery lifecycle'] }, null, 2));
  console.log(JSON.stringify({ status: 'passed', checks, screenshots: output, commands: commands.length }));
} catch (error) {
  await capture('failure').catch(() => {});
  await writeFile(join(output, 'failure.json'), JSON.stringify({ message: error.message, checkpoint, pollReads, checks, pageErrors, routeErrors, unexpected, commands, body: await page.locator('body').innerText().catch(() => ''), formState: await page.locator('form').evaluateAll(forms => forms.map(form => ({ text: form.textContent, fields: [...form.querySelectorAll('input,textarea')].map(field => ({ id: field.id, value: field.value, checked: field.checked })), buttons: [...form.querySelectorAll('button')].map(button => ({ text: button.textContent, disabled: button.disabled })) }))).catch(() => []) }, null, 2));
  throw error;
} finally { await browser.close(); }
