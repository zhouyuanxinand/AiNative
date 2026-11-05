import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript');
const loaded = new Map();
function load(name) {
  if (loaded.has(name)) return loaded.get(name).exports;
  const source = readFileSync(new URL(`./${name}.ts`, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } });
  const module = { exports: {} };
  loaded.set(name, module);
  new Function('require', 'module', 'exports', outputText)(path => path.startsWith('./') ? load(path.slice(2)) : require(path), module, module.exports);
  return module.exports;
}
const { scenarioManifest } = load('scenarioManifest');
const { caseJourney, caseStepForSurface, successfulCaseDestination } = load('caseJourney');
const manifest = scenarioManifest('taskbook');
const projectTemplate = {
  id: 'taskbook-generation', version: '1', title: '研制任务书生成流程', category: 'project', status: 'published',
  digest: 'fixed-project', graph: { nodes: [], edges: [] }, publication_revision: 1,
};
const sources = [
  { id: 'tech', role: 'tech', name: '需求.pdf', sha256: 'tech-hash', size: 12, version: 1, created_at: '2026-11-04T00:00:00Z' },
  { id: 'spec', role: 'spec', name: '规范.pdf', sha256: 'spec-hash', size: 12, version: 1, created_at: '2026-11-04T00:00:00Z' },
];
const requirement = { id: 'req', title: '绝缘要求', content: '按规范检验', source_ids: ['tech', 'spec'], revision: 1, history: [] };
const analysis = overrides => ({
  id: 'analysis', status: 'adopted', input_revision: 2, adopted_input_revision: 3, created_at: '2026-11-04T00:00:00Z',
  source_hashes: { tech: 'tech-hash', spec: 'spec-hash' }, model_selection: { provider: '', name: '', id: '' },
  context: {}, requirements: [{ title: requirement.title, content: requirement.content, source_ids: ['tech', 'spec'], evidence: [] }], warnings: [], ...overrides,
});
const lifecycle = overrides => ({
  policy_version: 'v2', selection_order_id: null, rd_activation_state: 'not_started', rd_project_code: null,
  current_requirement_baseline_id: null, current_selection_bundle_id: null, current_selection_decision_id: null,
  current_activation_id: null, current_taskbook_scope_decision_id: null, review_mode: 'local_owner', required_policy_ref: '',
  local_review_enabled: true, can_record_decision: true, can_confirm_requirements: true, ...overrides,
});
const binding = overrides => ({
  id: 'binding', revision: 1, status: 'current', input_revision: 3, workflow: { ...projectTemplate, nodes: ['taskbook'], product_route: 'modification' },
  source_ids: ['tech', 'spec'], document_template: {}, scope: '编制任务书', rationale: '依照已确认需求', fingerprint: 'binding-digest',
  adopted_at: '2026-11-04T00:00:00Z', ...overrides,
});
const researchCase = overrides => ({
  id: 'case', title: '研制项目', scenario_id: 'taskbook', stage: 'input', status: 'active', input_revision: 3,
  sources, source_selection: { tech: 'tech', spec: 'spec' }, requirements: [], clarifications: [], comparisons: [],
  product_route: null, composition_route: null, context: {}, decisions: [], workpackages: [],
  business_lifecycle: lifecycle({}), workflow_templates: { project: projectTemplate },
  project_workflow_status: { status: 'pending', template_id: projectTemplate.id, template_version: '1', template_digest: projectTemplate.digest, terminal_node_id: 'taskbook' },
  ...overrides,
});
const selectionCase = overrides => researchCase({
  stage: 'selection', requirements: [requirement], source_analysis: analysis({}),
  business_lifecycle: lifecycle({ current_requirement_baseline_id: 'baseline' }),
  requirement_baselines: [{ id: 'baseline', input_revision: 3, status: 'current', items: [requirement] }], ...overrides,
});
const planningCase = overrides => selectionCase({
  stage: 'planning', product_route: { value: 'modification' }, composition_route: { value: 'adapt' },
  business_lifecycle: lifecycle({ current_requirement_baseline_id: 'baseline', current_selection_decision_id: 'approved-selection', current_activation_id: 'activation', rd_activation_state: 'active' }),
  ...overrides,
});
const legacyCase = overrides => researchCase({
  workflow_templates: undefined, project_workflow_status: undefined, business_lifecycle: lifecycle({ policy_version: 'legacy_v1' }), ...overrides,
});
const workpackage = overrides => ({
  id: 'package', title: '任务书', definition_id: 'taskbook', definition_version: '2', stage: 'planning', status: 'completed', plan_revision: 1,
  snapshot: { input_revision: 3 }, nodes: [{ id: 'verify', action_id: 'verify', status: 'completed', result: { delivery_approved: true } }],
  artifacts: [{ id: 'docx', name: '任务书.docx', kind: 'docx' }], blocked_reasons: [], obligations: [], ...overrides,
});
const step = (journey, id) => journey.steps.find(item => item.id === id);

test('an unadopted input exposes only the source page, not future pages from the frozen project template', () => {
  const journey = caseJourney(researchCase({ source_analysis: analysis({ status: 'proposed', adopted_input_revision: undefined }) }), manifest);
  assert.equal(journey.active, 'sources');
  assert.equal(journey.completed, false);
  assert.deepEqual(journey.steps.filter(item => item.available).map(item => item.id), ['sources']);
  assert.equal(journey.next.target, 'sources');
  assert.ok(step(journey, 'requirements').reason);
  assert.ok(step(journey, 'preparation').reason);
  assert.equal(step(journey, 'delivery'), undefined);
});

test('adopted analysis at input opens requirement review without unlocking selection', () => {
  const data = researchCase({ source_analysis: analysis({}), requirements: [requirement] });
  const journey = caseJourney(data, manifest);
  assert.equal(journey.active, 'requirements');
  assert.equal(step(journey, 'requirements').available, true);
  assert.equal(step(journey, 'routes').available, false);
  assert.deepEqual(journey.next, { target: 'decision', label: '确认需求并进入选型' });
  assert.equal(caseStepForSurface(journey.next.target, data), 'requirements');
});

test('adopted analysis without extracted requirements opens review and preserves the existing analysis action', () => {
  const data = researchCase({ source_analysis: analysis({ requirements: [] }) });
  const journey = caseJourney(data, manifest);
  assert.equal(journey.active, 'requirements');
  assert.equal(step(journey, 'requirements').available, true);
  assert.equal(journey.next.target, 'sources');
});

test('a requirement revision can be reviewed at input even when it made the old analysis stale', () => {
  const data = researchCase({ requirements: [{ ...requirement, revision: 2 }], source_analysis: analysis({ status: 'stale' }) });
  const journey = caseJourney(data, manifest);
  assert.equal(journey.active, 'requirements');
  assert.equal(step(journey, 'requirements').available, true);
  assert.equal(step(journey, 'routes').available, false);
  assert.equal(journey.next.target, 'decision');
});

test('removed current inputs return to sources while old requirements remain available for review', () => {
  const data = researchCase({
    sources: [sources[1]], source_selection: { tech: '', spec: 'spec' }, requirements: [requirement],
    source_analysis: analysis({ status: 'stale' }),
  });
  const journey = caseJourney(data, manifest);
  assert.equal(journey.active, 'sources');
  assert.equal(journey.next.target, 'sources');
  assert.equal(step(journey, 'requirements').available, true);
});

test('required unanswered clarification keeps the next action in requirements', () => {
  const data = researchCase({ requirements: [requirement], clarifications: [{ id: 'clarification', required: true, status: 'answered', input_revision: 3 }] });
  const journey = caseJourney(data, manifest);
  assert.equal(journey.active, 'requirements');
  assert.equal(journey.next.target, 'requirements');
  assert.equal(step(journey, 'routes').available, false);
});

test('a fixed requirement baseline opens selection while startup and preparation still wait', () => {
  const journey = caseJourney(selectionCase({}), manifest);
  assert.equal(journey.active, 'routes');
  assert.deepEqual(journey.steps.filter(item => item.available).map(item => item.id), ['sources', 'requirements', 'routes']);
  assert.equal(journey.next.target, 'routes');
  const approved = caseJourney(selectionCase({ product_route: { value: 'modification' }, composition_route: { value: 'adapt' }, business_lifecycle: lifecycle({ current_selection_decision_id: 'decision' }) }), manifest);
  assert.equal(approved.active, 'routes');
  assert.equal(approved.next.target, 'decision');
  assert.equal(step(approved, 'preparation').available, false);
});

test('current input binding opens project execution only after preparation', () => {
  const preparing = caseJourney(planningCase({}), manifest);
  assert.equal(preparing.active, 'preparation');
  assert.equal(step(preparing, 'preparation').available, true);
  assert.equal(step(preparing, 'workpackages').available, false);
  const bound = caseJourney(planningCase({ taskbook_binding: binding({}) }), manifest);
  assert.equal(bound.active, 'workpackages');
  assert.equal(bound.next.target, 'workpackages');
  assert.equal(step(bound, 'workpackages').available, true);
});

test('historical downstream records stay viewable after input invalidation without advancing the current step', () => {
  const data = researchCase({
    requirements: [requirement], source_analysis: analysis({ status: 'stale' }),
    comparisons: [{ id: 'comparison', input_revision: 2, invalidated_at: '2026-11-04T00:00:00Z' }],
    taskbook_binding: binding({ status: 'stale', input_revision: 2 }),
    workpackages: [workpackage({ status: 'blocked', snapshot: { input_revision: 2 } })],
  });
  const journey = caseJourney(data, manifest);
  assert.equal(journey.active, 'requirements');
  assert.equal(journey.next.target, 'decision');
  assert.equal(step(journey, 'routes').available, true);
  assert.equal(step(journey, 'preparation').available, true);
  assert.equal(step(journey, 'workpackages').available, true);
  assert.equal(journey.completed, false);
});

for (const status of ['submitted', 'running', 'blocked', 'failed']) test(`current ${status} execution stays at workpackages`, () => {
  const data = planningCase({ taskbook_binding: binding({}), workpackages: [workpackage({ status, artifacts: [] })] });
  assert.equal(caseJourney(data, manifest).active, 'workpackages');
  assert.equal(caseJourney(data, manifest).next.target, 'workpackages');
});

test('old input or other-stage blocked packages do not replace current preparation', () => {
  const journey = caseJourney(planningCase({ workpackages: [workpackage({ status: 'failed', snapshot: { input_revision: 2 } }), workpackage({ id: 'selection-package', stage: 'selection', status: 'blocked' })] }), manifest);
  assert.equal(journey.active, 'preparation');
  assert.equal(journey.next.target, 'preparation');
  assert.equal(step(journey, 'workpackages').available, true);
});

test('project completion is taken from the server status, never from artifacts or passed verification', () => {
  const data = planningCase({ taskbook_binding: binding({}), workpackages: [workpackage({})] });
  assert.equal(caseJourney(data, manifest).completed, false);
  const completed = caseJourney({ ...data, project_workflow_status: { ...data.project_workflow_status, status: 'completed' } }, manifest);
  assert.equal(completed.completed, true);
  assert.equal(completed.active, 'workpackages');
  assert.equal(completed.next, null);
  const stale = caseJourney({ ...data, status: 'completed', project_workflow_status: { ...data.project_workflow_status, status: 'stale' }, taskbook_binding: binding({ status: 'stale' }) }, manifest);
  assert.equal(stale.completed, false);
});

test('missing decision qualification does not hide viewable steps or claim completion', () => {
  const data = researchCase({ requirements: [requirement], source_analysis: analysis({}), business_lifecycle: lifecycle({ can_record_decision: false, can_confirm_requirements: false }) });
  assert.equal(caseJourney(data, manifest).active, 'requirements');
  assert.equal(step(caseJourney(data, manifest), 'requirements').available, true);
  const historical = caseJourney(legacyCase({ stage: 'planning', business_lifecycle: lifecycle({ rd_activation_state: 'historical_unverified' }) }), manifest);
  assert.equal(historical.next, null);
  assert.equal(historical.completed, false);
});

test('legacy steps preserve requirement review, preparation decisions, delivery and reuse', () => {
  const reviewing = caseJourney(legacyCase({ stage: 'requirements', requirements: [requirement] }), manifest);
  assert.equal(reviewing.active, 'requirements');
  assert.equal(step(reviewing, 'routes').available, false);
  assert.equal(step(reviewing, 'delivery').available, false);
  assert.equal(step(reviewing, 'reuse').available, false);
  const preparing = caseJourney(legacyCase({ stage: 'planning', product_route: { value: 'modification' }, taskbook_binding: binding({}) }), manifest);
  assert.equal(preparing.active, 'preparation');
  assert.equal(preparing.next.target, 'decision');
  assert.equal(step(preparing, 'workpackages').available, false);
  assert.equal(caseJourney(legacyCase({ stage: 'delivery' }), manifest).active, 'delivery');
  const completed = caseJourney(legacyCase({ stage: 'knowledge', status: 'completed' }), manifest);
  assert.equal(completed.active, 'reuse');
  assert.equal(completed.completed, true);
  assert.equal(completed.next, null);
});

test('decision surfaces belong to their real lifecycle step, including legacy planning', () => {
  const rows = [
    [researchCase({}), 'requirements'], [legacyCase({ stage: 'requirements' }), 'requirements'],
    [selectionCase({}), 'routes'], [planningCase({}), 'workpackages'],
    [legacyCase({ stage: 'planning' }), 'preparation'], [legacyCase({ stage: 'design' }), 'workpackages'],
    [legacyCase({ stage: 'delivery' }), 'delivery'], [legacyCase({ stage: 'knowledge' }), 'reuse'],
  ];
  for (const [data, expected] of rows) assert.equal(caseStepForSurface('decision', data), expected);
  assert.equal(caseStepForSurface('sources', planningCase({})), 'sources');
  assert.equal(caseStepForSurface('current', researchCase({ requirements: [requirement] })), 'requirements');
});

test('successful adoption enters requirement review only for the returned current adopted analysis', () => {
  const before = researchCase({ source_analysis: analysis({ status: 'proposed', adopted_input_revision: undefined }) });
  const after = researchCase({ source_analysis: analysis({}), requirements: [requirement] });
  assert.equal(successfulCaseDestination('adopt_source_analysis', { analysis_id: 'analysis' }, before, after), 'requirements');
  assert.equal(successfulCaseDestination('adopt_source_analysis', { analysis_id: 'other' }, before, after), null);
  assert.equal(successfulCaseDestination('adopt_source_analysis', { analysis_id: 'analysis' }, before, { ...after, source_analysis: analysis({ status: 'stale' }) }), null);
});

test('successful requirement confirmation and independent startup follow their returned stages', () => {
  assert.equal(successfulCaseDestination('confirm_requirements', { expected_input_revision: 3 }, researchCase({ requirements: [requirement] }), selectionCase({})), 'routes');
  assert.equal(successfulCaseDestination('confirm_requirements', {}, researchCase({}), researchCase({})), null);
  assert.equal(successfulCaseDestination('authorize_rd_start', { selection_decision_id: 'approved-selection' }, selectionCase({}), planningCase({})), 'preparation');
  assert.equal(successfulCaseDestination('authorize_rd_start', {}, selectionCase({}), selectionCase({})), null);
});

test('binding adoption goes to execution for v2 and keeps the separate legacy planning approval', () => {
  assert.equal(successfulCaseDestination('adopt_taskbook_flow', { workflow_id: projectTemplate.id, workflow_version: '1' }, planningCase({}), planningCase({ taskbook_binding: binding({}) })), 'workpackages');
  assert.equal(successfulCaseDestination('adopt_taskbook_flow', {}, planningCase({}), planningCase({ taskbook_binding: binding({ status: 'stale' }) })), null);
  assert.equal(successfulCaseDestination('adopt_taskbook_flow', {}, legacyCase({ stage: 'planning' }), legacyCase({ stage: 'planning', taskbook_binding: binding({}) })), null);
});

test('ordinary saves, rejected decisions and unchanged transitions never advance the page', () => {
  const before = selectionCase({});
  const after = planningCase({});
  for (const command of ['save_requirement', 'adopt_clarification', 'answer_clarification', 'record_route_decision', 'save_comparison', 'prepare_selection_review', 'pull_workpackage', 'submit_workpackage']) {
    assert.equal(successfulCaseDestination(command, {}, before, after), null, command);
  }
  assert.equal(successfulCaseDestination('advance_stage', { stage: 'selection', verdict: 'rejected' }, before, after), null);
  assert.equal(successfulCaseDestination('advance_stage', { stage: 'selection', verdict: 'approved' }, before, before), null);
  assert.equal(successfulCaseDestination('confirm_requirements', {}, researchCase({}), { ...selectionCase({}), id: 'another-case' }), null);
});

test('legacy and engineering approvals retain the actual next stage, including direct supply and terminal completion', () => {
  const rows = [
    ['advance_stage', 'input', 'requirements', 'requirements'],
    ['advance_stage', 'requirements', 'selection', 'routes'],
    ['advance_stage', 'selection', 'planning', 'preparation'],
    ['advance_stage', 'planning', 'design', 'workpackages'],
    ['confirm_engineering_stage', 'design', 'verification', 'workpackages'],
    ['confirm_engineering_stage', 'verification', 'delivery', 'delivery'],
    ['confirm_engineering_stage', 'delivery', 'knowledge', 'reuse'],
  ];
  for (const [command, from, to, expected] of rows) assert.equal(successfulCaseDestination(command, { stage: from, verdict: 'approved' }, legacyCase({ stage: from }), legacyCase({ stage: to })), expected);
  assert.equal(successfulCaseDestination('record_selection_decision', { verdict: 'approved' }, selectionCase({}), legacyCase({ stage: 'delivery', product_route: { value: 'direct' } })), 'delivery');
  assert.equal(successfulCaseDestination('record_taskbook_scope_decision', { verdict: 'approved' }, planningCase({}), legacyCase({ stage: 'design' })), 'workpackages');
  assert.equal(successfulCaseDestination('advance_stage', { stage: 'knowledge', verdict: 'approved' }, legacyCase({ stage: 'knowledge' }), legacyCase({ stage: 'knowledge', status: 'completed' })), 'current');
});
