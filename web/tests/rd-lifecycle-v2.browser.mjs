/** Isolated API fixtures: exercises UI lifecycle contracts, never a real model or engineering signature. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const output = process.env.SCREENSHOT_DIR || 'runtime/rd-lifecycle-v2-browser';
await mkdir(output, { recursive: true });
const stamp = '2026-11-01T02:00:00Z';
const context = { product_type: 'liquid_cooling_pipeline', product_domain: 'military', development_process: '改型II', cover_phase: 'S', product_series: 'YLZJ', organization_scope: 'non_central_research' };
const sourceRows = ['tech', 'spec'].map(role => ({ id: role, role, name: role === 'tech' ? '隔离测试技术要求.txt' : '隔离测试产品规范.txt', size: 80, version: 1, sha256: role.repeat(16), created_at: stamp }));
const requirements = [{ id: 'r1', title: '工作压力', content: '工作压力：0.3 MPa。', source_ids: ['tech'], revision: 1, history: [], evidence: [{ source_id: 'tech', quote: '工作压力：0.3 MPa。' }] }];
const statistics = { total: 1, matches: 1, partial: 0, gap: 0, unknown: 0, match_ratio: 1 };
const comparisonRows = [{ requirement_id: 'r1', assessment: 'match', candidate_value: '0.3 MPa', reason: '隔离比对夹具', source_ids: ['spec'] }];
const routeDecision = value => ({ value, rationale: '隔离夹具已登记的逐项比对决定', source_ids: ['tech', 'spec'], actor: 'fixture-owner', created_at: stamp, comparison_id: 'comparison-product', comparison_revision: 1 });
const workflow = { id: 'taskbook-modification-v1', version: '1', title: '改型研发流程', status: 'published', product_route: 'modification', nodes: ['taskbook', 'scheme', 'detail', 'integration', 'verification', 'delivery'] };
const actionNames = { resolve_context: '解析与核对参数', template_plan: '模板路由与装配计划', content_completion: '内容补齐与证据核对', generate: '生成研制任务书', verify: '质量验证' };
const nodes = Object.keys(actionNames).map((id, index, ids) => ({ id, action_id: id, action_version: '1', depends_on: index ? [ids[index - 1]] : [], required: true, status: 'draft', result: null, attempt: 0 }));
const catalog = { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书', status: 'published' }], research_workflow_templates: [workflow],
  actions: Object.entries(actionNames).map(([id, title]) => ({ id, title, version: '1' })),
  workpackage_definitions: [{ id: 'taskbook', version: '2', title: '任务书装配与校验', stages: ['planning'], business_node_id: 'taskbook_planning', required_actions: Object.keys(actionNames), optional_actions: [], nodes }] };
let project = { id: 'lifecycle-fixture', title: '隔离测试数据 · v2 首链', version: 1, owner_id: 'fixture-owner', members: [], events: [], brief: '', cases: [{
  id: 'case-fixture', scenario_id: 'taskbook', title: '隔离测试数据 · 液冷首链', stage: 'input', input_revision: 1, status: 'draft', context: {}, sources: [], source_selection: {},
  requirements: [], clarifications: [], comparisons: [], decisions: [], workpackages: [], review_bundles: [], requirement_baselines: [], rd_activations: [],
  product_route: null, composition_route: null, model_selection: { provider: 'fixture', name: 'isolated-test-model', id: '1' },
  business_lifecycle: { policy_version: 'v2', selection_order_id: 'SEL-fixture', rd_activation_state: 'not_started', rd_project_code: null, review_mode: 'local_review', required_policy_ref: 'local-project-owner-v1', local_review_enabled: true, can_record_decision: true, can_confirm_requirements: true,
    current_requirement_baseline_id: null, current_selection_bundle_id: null, current_selection_decision_id: null, current_activation_id: null, current_taskbook_scope_decision_id: null },
}] };
const current = () => project.cases[0];
const requests = [], errors = [], routeErrors = [], screenshots = [];
let failConfirmation = true, failDecision = true;
function bundle(kind) {
  return { id: kind + '-bundle-' + project.version, kind, status: 'submitted', digest: kind + '-fixed-digest-' + project.version, input_revision: current().input_revision,
    review_mode: 'local_review', required_policy_ref: 'local-project-owner-v1', actor: 'fixture-owner', created_at: stamp,
    fixed_objects: kind === 'selection' ? { requirements } : { workpackage_id: 'wp-fixture', run_id: 'run-fixture', input_revision: current().input_revision, binding_id: 'binding-fixture', artifacts: current().workpackages[0].artifacts, quality_result: { delivery_approved: true } },
    report: kind === 'selection' ? { id: 'report-fixture', title: '固定选型报告', format: 'structured_selection_report', rows: comparisonRows, statistics, requirements, product_route: current().product_route, composition_route: current().composition_route } : undefined };
}
function completePackage(passed) {
  const wp = current().workpackages[0];
  wp.status = passed ? 'completed' : 'blocked';
  wp.nodes = wp.nodes.map(node => ({ ...node, status: node.id === 'verify' && !passed ? 'blocked' : 'completed', result: node.id === 'verify' ? { delivery_approved: passed, blockers: passed ? [] : ['隔离测试：质量门禁未通过'] } : {}, completed_at: stamp }));
  wp.artifacts = [{ id: 'doc-fixture', kind: 'taskbook', name: '隔离测试任务书复核稿.docx', sha256: 'fixture-output' }];
  wp.blocked_reasons = passed ? [] : ['隔离测试：质量门禁未通过'];
}

const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
page.on('pageerror', error => errors.push(error.message));
page.on('requestfailed', request => { if (request.failure()?.errorText !== 'net::ERR_ABORTED') errors.push(request.url() + ': ' + request.failure()?.errorText); });
page.on('dialog', dialog => dialog.type() === 'beforeunload' ? dialog.accept() : dialog.dismiss());
async function capture(name) {
  await page.screenshot({ path: join(output, name + '.png') });
  screenshots.push(name + '.png');
}
async function openNext() { await page.locator('.rd-outcome-heading').getByRole('button').click(); }
async function returnToOutcome() { await page.getByRole('button', { name: '← 返回当前成果', exact: true }).click(); }
async function choose(label, option) {
  await page.getByRole('button', { name: typeof label === 'string' ? new RegExp('^' + label) : label }).click();
  await page.getByRole('option', { name: option, exact: true }).click();
}
async function confirmDialog() { await page.getByRole('dialog').getByRole('button', { name: '保存本地决定', exact: true }).click(); }
async function reloadFixture() { await page.reload(); await page.locator('.rd-case-heading h1').waitFor(); }

try {
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    try {
      if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
      if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: context.product_type, label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }] }] } });
      if (path === '/api/models') return route.fulfill({ json: { success: true, models: [{ provider: 'fixture', name: 'isolated-test-model', id: '1' }] } });
      if (path === '/api/rd/catalog') return route.fulfill({ json: catalog });
      if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
      if (path === '/api/rd/projects/lifecycle-fixture') return route.fulfill({ json: project });
      if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: current().stage, project_version: project.version, input_revision: current().input_revision } } });
      if (path.endsWith('/sources') && request.method() === 'POST') {
        const source = sourceRows[current().sources.length];
        assert(source, 'only the two isolated source uploads are expected');
        assert(request.postDataBuffer().toString().includes(source.name));
        current().sources.push(structuredClone(source)); current().source_selection[source.role] = source.id;
        project.version++; current().input_revision++;
        return route.fulfill({ json: project });
      }
      if (path.endsWith('/analysis')) {
        assert.equal(request.method(), 'POST');
        current().source_analysis = { id: 'analysis-fixture', status: 'proposed', input_revision: current().input_revision, created_at: stamp,
          source_hashes: Object.fromEntries(sourceRows.map(source => [source.id, source.sha256])), model_selection: current().model_selection,
          context: Object.fromEntries(Object.entries(context).map(([field, value]) => [field, { value, status: 'proposed', reason: '隔离夹具明确声明的参数', evidence: [{ source_id: 'tech', quote: '隔离测试参数依据' }] }])), requirements, warnings: ['本页为隔离 API 测试夹具，不是实际模型生成或工程批准。'] };
        project.version++; return route.fulfill({ json: project });
      }
      if (path.endsWith('/commands')) {
        const body = request.postDataJSON(), data = body.data, name = body.command;
        requests.push({ key: request.headers()['idempotency-key'], body: structuredClone(body) });
        assert.equal(body.expected_version, project.version);
        assert.equal(data.case_id, current().id);
        assert(request.headers()['idempotency-key'], 'writes need an idempotency key');
        await new Promise(resolve => setTimeout(resolve, 80));
        if (name === 'confirm_requirements' && failConfirmation) { failConfirmation = false; return route.fulfill({ status: 503, json: { error: '隔离测试：需求确认暂不可用，草稿已保留。' } }); }
        if (name === 'record_selection_decision' && failDecision) { failDecision = false; return route.fulfill({ status: 503, json: { error: '隔离测试：决定保存暂不可用，请重试。' } }); }
        const c = current(), life = c.business_lifecycle;
        if (name === 'adopt_source_analysis') {
          assert.equal(data.analysis_id, 'analysis-fixture');
          c.context = structuredClone(context); c.requirements = structuredClone(requirements); c.input_revision++;
          c.source_analysis.status = 'adopted'; c.source_analysis.adopted_input_revision = c.input_revision;
        } else if (name === 'confirm_requirements') {
          assert.equal(data.expected_input_revision, c.input_revision); assert(data.scope.trim()); assert(data.source_ids.includes('tech'));
          c.requirement_baselines.push({ id: 'requirements-baseline', digest: 'requirements-digest', revision: 1, input_revision: c.input_revision, status: 'current', requirements, source_refs: sourceRows, scope: data.scope, actor: 'fixture-owner', created_at: stamp });
          life.current_requirement_baseline_id = 'requirements-baseline'; c.stage = 'selection';
          // The existing comparison/route editor is outside this lifecycle test; its inputs are explicit fixtures.
          c.product_route = routeDecision('modification'); c.composition_route = routeDecision('direct');
          c.comparisons = ['product', 'document'].map(kind => ({ id: 'comparison-' + kind, kind, title: '隔离逐项比对', revision: 1, input_revision: c.input_revision, sha256: kind, source_ids: ['spec'], rows: comparisonRows, statistics, status: 'manual_record' }));
        } else if (name === 'prepare_selection_review') {
          assert.equal(data.expected_input_revision, c.input_revision);
          const fixed = bundle('selection'); c.review_bundles.push(fixed); life.current_selection_bundle_id = fixed.id;
        } else if (name === 'record_selection_decision' || name === 'record_taskbook_scope_decision') {
          assert.equal(life.can_record_decision, true, 'non-owner UI must never send a decision');
          const fixed = c.review_bundles.find(item => item.id === data.bundle_id);
          assert(fixed); assert.equal(data.bundle_digest, fixed.digest); assert(data.scope.trim()); assert(data.rationale.trim());
          const decision = { id: name + '-' + project.version, kind: fixed.kind, bundle_id: fixed.id, bundle_digest: fixed.digest, verdict: data.verdict,
            scope: data.scope, rationale: data.rationale, actor: 'fixture-owner', input_revision: c.input_revision, created_at: stamp, review_mode: 'local_review',
            policy_ref: 'local-project-owner-v1', qualification: { role: 'project_owner', project_id: project.id, actor: 'fixture-owner' }, electronic_signature: false };
          c.decisions.push(decision); fixed.status = data.verdict;
          if (fixed.kind === 'selection') life.current_selection_decision_id = decision.id;
          else { life.current_taskbook_scope_decision_id = decision.id; c.stage = 'design'; }
        } else if (name === 'authorize_rd_start') {
          assert.equal(data.selection_decision_id, life.current_selection_decision_id); assert(data.scope.trim()); assert(data.rationale.trim());
          life.rd_activation_state = 'active'; life.rd_project_code = 'RD-ISOLATED'; life.current_activation_id = 'activation-fixture';
          c.rd_activations.push({ id: 'activation-fixture', selection_decision_id: data.selection_decision_id, scope: data.scope, rationale: data.rationale, status: 'active' }); c.stage = 'planning';
        } else if (name === 'adopt_taskbook_flow') {
          assert.equal(c.stage, 'planning'); assert.equal(life.rd_activation_state, 'active'); assert.equal(data.workflow_id, workflow.id); assert.equal(data.workflow_version, '1');
          c.taskbook_binding = { id: 'binding-fixture', revision: 1, input_revision: c.input_revision, status: 'current', workflow, scope: data.scope, rationale: data.rationale, source_ids: ['tech', 'spec'], fingerprint: 'fixed-binding-digest', adopted_at: stamp,
            document_template: { title: '液冷管路受控任务书', product_type: context.product_type, product_domain: 'military' } };
        } else if (name === 'pull_workpackage') {
          assert.equal(c.stage, 'planning'); assert.equal(data.definition_id, 'taskbook'); assert.equal(data.definition_version, '2');
          c.workpackages.push({ id: 'wp-fixture', definition_id: 'taskbook', definition_version: '2', business_node_id: 'taskbook_planning', title: '任务书装配与校验', stage: 'planning', status: 'draft', plan_revision: 1, nodes: structuredClone(nodes), artifacts: [], obligations: [], blocked_reasons: [] });
        } else if (name === 'submit_workpackage') {
          assert.equal(data.workpackage_id, 'wp-fixture'); const wp = c.workpackages[0]; wp.run_id = 'run-fixture'; wp.snapshot = { input_revision: c.input_revision, submitted_at: stamp }; completePackage(false);
        } else if (name === 'prepare_taskbook_scope_review') {
          assert.equal(data.workpackage_id, 'wp-fixture'); assert.equal(c.workpackages[0].status, 'completed');
          c.review_bundles.push(bundle('taskbook_scope'));
        } else assert.fail('Unexpected fixture command: ' + name);
        project.version++; return route.fulfill({ json: project });
      }
      assert.equal(request.method(), 'GET', 'No unhandled mutation may reach the real server');
      return route.fulfill({ json: {} });
    } catch (error) { routeErrors.push(error.message); return route.fulfill({ status: 500, json: { error: error.message } }); }
  });
  await page.goto((process.env.TEST_BASE_URL || 'http://127.0.0.1:18370') + '/?project=lifecycle-fixture&case=case-fixture');
  await openNext();
  for (const source of sourceRows) {
    if (source.role === 'spec') await choose('资料用途', '规范标准');
    await page.getByLabel('选择资料文件', { exact: true }).setInputFiles({ name: source.name, mimeType: 'text/plain', buffer: Buffer.from('隔离测试数据：工作压力：0.3 MPa。') });
    await page.getByRole('button', { name: '上传并采用', exact: true }).click();
    await page.locator('.rd-current-files').getByRole('link', { name: source.name + ' ↗', exact: true }).waitFor();
  }
  await page.getByRole('button', { name: '分析上传资料', exact: true }).click();
  await page.getByRole('button', { name: '确认采用', exact: true }).click();
  await page.getByText('已采用', { exact: true }).first().waitFor();
  await capture('01-source-adoption-isolated');
  assert.equal(current().stage, 'input'); assert.equal(current().decisions.length, 0);
  await returnToOutcome(); await openNext();
  const requirementScope = page.getByLabel('确认范围', { exact: true });
  await requirementScope.fill('隔离测试：确认液冷工作压力及其原文来源');
  const confirmRequirements = page.getByRole('button', { name: '确认需求并进入选型', exact: true });
  await confirmRequirements.click();
  await page.getByRole('dialog').getByRole('button', { name: '保存本地决定', exact: true }).evaluate(element => { element.click(); element.click(); });
  await page.getByRole('alert').filter({ hasText: '需求确认暂不可用' }).first().waitFor();
  assert.equal(requests.filter(item => item.body.command === 'confirm_requirements').length, 1, 'duplicate confirmation clicks send one command');
  assert.equal(await requirementScope.inputValue(), '隔离测试：确认液冷工作压力及其原文来源');
  await capture('02-requirement-confirmation-retry-isolated');
  await confirmDialog();
  await page.waitForFunction(() => document.querySelector('.rd-case-heading')?.textContent?.includes('选型'));
  const confirmationRequests = requests.filter(item => item.body.command === 'confirm_requirements');
  assert.equal(confirmationRequests.length, 2); assert.equal(confirmationRequests[0].key, confirmationRequests[1].key);
  assert.equal(current().decisions.length, 0, 'requirements confirmation creates no engineering approval');
  await openNext();
  await page.getByText('本地负责人确认 · 非正式电子审签', { exact: false }).waitFor();
  await page.getByRole('button', { name: '生成固定选型报告', exact: true }).click();
  await page.getByRole('button', { name: '批准选型报告', exact: true }).waitFor();
  const decisionScope = '隔离测试范围：液冷改型策划\n' + Array.from({ length: 24 }, (_, i) => `核对条目 ${i + 1}：仅使用已固定的需求、来源、产品配置与选型差异。`).join('\n');
  await page.getByLabel('决定范围', { exact: true }).fill(decisionScope);
  await page.getByLabel('决定说明', { exact: true }).fill('隔离测试：按固定报告核对，非正式电子签署。');
  await capture('03-selection-report-isolated');
  await page.getByRole('button', { name: '批准选型报告', exact: true }).click();
  await page.getByRole('dialog').waitFor();
  await page.mouse.click(3, 3);
  await page.getByRole('dialog').waitFor({ state: 'hidden' });
  assert.equal(await page.getByLabel('决定范围', { exact: true }).inputValue(), decisionScope);
  await page.getByRole('button', { name: '批准选型报告', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('dialog').evaluate(element => { element.scrollTop = element.scrollHeight; });
  const modal = await page.getByRole('dialog').boundingBox();
  assert(modal.y >= -1 && modal.y + modal.height <= 845, 'decision dialog fits a narrow viewport');
  await capture('03-selection-dialog-narrow-isolated');
  await confirmDialog();
  await page.getByRole('dialog').getByRole('alert').filter({ hasText: '决定保存暂不可用' }).waitFor();
  assert.equal(await page.getByLabel('决定范围', { exact: true }).inputValue(), decisionScope);
  await confirmDialog();
  await page.getByRole('dialog').waitFor({ state: 'hidden' });
  const decisionRequests = requests.filter(item => item.body.command === 'record_selection_decision');
  assert.equal(decisionRequests.length, 2); assert.equal(decisionRequests[0].key, decisionRequests[1].key);
  assert.equal(current().stage, 'selection'); assert.equal(current().business_lifecycle.rd_activation_state, 'not_started');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByLabel('决定范围', { exact: true }).fill('隔离测试：启动当前液冷改型策划');
  await page.getByLabel('决定说明', { exact: true }).fill('按已批准的固定选型报告单独办理研发启动。');
  await page.getByRole('button', { name: '确认研发启动', exact: true }).click(); await confirmDialog();
  await page.waitForFunction(() => document.querySelector('.rd-case-heading')?.textContent?.includes('策划'));
  assert.equal(current().rd_activations.length, 1); assert.equal(current().workpackages.length, 0);
  await openNext();
  await choose('研发流程模板', '改型研发流程 · V1');
  await page.getByLabel('本次研发工作范围', { exact: true }).fill('隔离测试：按选型差异形成任务书');
  await page.getByLabel('采用依据与差异处理边界', { exact: true }).fill('使用已固定六参数、来源及本地启动记录');
  await page.getByRole('button', { name: '采用流程并固定任务书输入', exact: true }).click();
  await page.getByText('已采用固定版本', { exact: false }).first().waitFor();
  await returnToOutcome(); await openNext();
  await choose(/当前阶段可拉取的工作包/, '任务书装配与校验 · V2');
  await page.getByRole('button', { name: '拉取工作包', exact: true }).click();
  const canvas = page.getByRole('region', { name: '编排执行计划', exact: true });
  await canvas.getByRole('button', { name: '列表', exact: true }).click();
  assert.equal(await canvas.locator('ol li').count(), nodes.length);
  await canvas.getByRole('button', { name: '画布', exact: true }).click();
  await capture('04-planning-workpackage-isolated');
  const sidebarBefore = await page.locator('.rd-sidebar').boundingBox();
  await page.locator('.rd-application-shell').evaluate(element => { element.scrollTop = element.scrollHeight; });
  const sidebarAfter = await page.locator('.rd-sidebar').boundingBox();
  assert(Math.abs(sidebarAfter.y - sidebarBefore.y) <= 1, 'main sidebar remains visible while the working area scrolls');
  await page.getByRole('button', { name: '确认提交', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '固定快照并提交', exact: true }).click();
  await page.getByText('隔离测试：质量门禁未通过', { exact: true }).first().waitFor();
  await returnToOutcome();
  assert.equal(current().stage, 'planning');
  await page.getByText('其他办理入口', { exact: true }).click();
  await page.getByRole('button', { name: '本阶段业务确认', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: '批准任务书范围', exact: true }).count(), 0, 'QA failure cannot show range approval');
  assert.equal(await page.getByRole('button', { name: '形成任务书范围核对包', exact: true }).isEnabled().catch(() => false), false);
  await capture('04-quality-blocked-isolated');
  completePackage(true); project.version++;
  // Creation/list order differs from submission order; the newer submitted result owns the scope review.
  current().workpackages.push({ ...structuredClone(current().workpackages[0]), id: 'wp-older-submission-fixture',
    run_id: 'run-older-fixture', snapshot: { input_revision: current().input_revision, submitted_at: '2026-11-01T01:00:00Z' } });
  await reloadFixture(); await openNext();
  await page.getByRole('button', { name: '形成任务书范围核对包', exact: true }).click();
  await page.getByRole('button', { name: '批准任务书范围', exact: true }).waitFor();
  const ownerSnapshot = structuredClone(project);
  current().business_lifecycle.can_record_decision = false;
  current().business_lifecycle.decision_unavailable_reason = '本地业务确认仅由项目负责人办理；成员和管理员不自动取得工程决定资格。';
  await reloadFixture(); await openNext();
  assert.equal(await page.getByRole('button', { name: '批准任务书范围', exact: true }).isDisabled(), true);
  await page.getByText(/没有项目负责人决定资格/).first().waitFor();
  await capture('04-owner-restriction-isolated');
  project = ownerSnapshot; await reloadFixture(); await openNext();
  await page.getByLabel('决定范围', { exact: true }).fill('隔离测试：批准当前任务书范围进入工程设计');
  await page.getByLabel('决定说明', { exact: true }).fill('仅绑定已完成工作包及通过的质量结果');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.rd-application-shell').evaluate(element => { element.scrollTop = element.scrollHeight; });
  assert(await page.locator('.rd-application-shell').evaluate(element => element.scrollWidth <= element.clientWidth + 1), 'narrow working area has no page-level horizontal overflow');
  await capture('04-scope-review-narrow-isolated');
  await page.getByRole('button', { name: '批准任务书范围', exact: true }).click(); await confirmDialog();
  await page.waitForFunction(() => document.querySelector('.rd-case-heading')?.textContent?.includes('工程设计'));
  assert.equal(current().stage, 'design');
  assert.equal(requests.filter(item => item.body.command === 'authorize_rd_start').length, 1);
  assert.equal(requests.filter(item => item.body.command === 'submit_workpackage').length, 1);
  assert(requests.every(item => item.body.command !== 'advance_stage'), 'v2 UI never sends the legacy stage bypass');
  current().business_lifecycle.rd_activation_state = 'historical_unverified';
  current().business_lifecycle.current_taskbook_scope_decision_id = null;
  current().decisions = [];
  project.version++;
  await page.setViewportSize({ width: 1440, height: 1000 });
  await reloadFixture();
  await page.getByText('历史记录待核对', { exact: true }).first().waitFor();
  assert.equal(current().stage, 'design');
  assert.equal(current().business_lifecycle.policy_version, 'v2');
  assert.equal(await page.getByText(/任务书范围已批准/).count(), 0, 'historical design stage cannot imply scope approval');
  await capture('05-historical-unverified-isolated');
  assert.deepEqual(errors, []); assert.deepEqual(routeErrors, []);
  await writeFile(join(output, 'verification.json'), JSON.stringify({ status: 'passed', evidence_category: 'isolated_browser_api_fixture', real_model_generation: false, formal_engineering_signature: false, screenshots, commands: requests.map(item => item.body.command), checks: ['source upload/adoption', 'requirement retry/draft/idempotency', 'fixed report approval', 'separate RD activation', 'planning v2 workpackage', 'canvas/list', 'QA block', 'owner restriction', 'scope approval', 'latest submission scope selection', 'narrow scroll', 'modal dismissal/retry', 'historical design does not imply approval'] }, null, 2));
  console.log('Lifecycle v2 isolated browser checks passed; screenshots and verification.json: ' + output);
} catch (error) {
  await capture('failure-isolated').catch(() => {});
  await writeFile(join(output, 'failure.json'), JSON.stringify({ message: error.message, pageErrors: errors, routeErrors, commands: requests, body: await page.locator('body').innerText().catch(() => '') }, null, 2));
  throw error;
} finally { await browser.close(); }
