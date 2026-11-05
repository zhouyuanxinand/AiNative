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
const { scenarioManifest, scenarioStage, nextCaseAction } = load('scenarioManifest');
const manifest = scenarioManifest('taskbook');
const projectNodes = ['input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start', 'taskbook'];
const projectTemplate = {
  id: 'taskbook-generation', version: '1', title: '研制任务书生成流程', category: 'project', status: 'published', digest: 'fixed-project-digest',
  graph: { nodes: projectNodes.map(id => ({ id, title: id })), edges: projectNodes.slice(1).map((target, index) => ({ id: `edge-${index}`, source: projectNodes[index], target })) },
};
const binding = overrides => ({ id: 'binding', status: 'current', input_revision: 3, workflow: { ...projectTemplate, nodes: projectNodes }, ...overrides });
const researchCase = overrides => ({
  id: 'project-case', scenario_id: 'taskbook', stage: 'planning', status: 'active', input_revision: 3,
  sources: [], requirements: [], decisions: [], workpackages: [], context: {},
  product_route: { value: 'modification' }, composition_route: { value: 'adapt' },
  business_lifecycle: { policy_version: 'v2', rd_activation_state: 'active' },
  workflow_templates: { project: projectTemplate },
  project_workflow_status: { status: 'pending', template_id: projectTemplate.id, template_version: '1', template_digest: projectTemplate.digest, terminal_node_id: 'taskbook' },
  ...overrides,
});
const completedPackage = overrides => ({
  id: 'current-taskbook', definition_id: 'taskbook', definition_version: '2', stage: 'planning', status: 'completed',
  nodes: [{ id: 'verified', action_id: 'verify', status: 'completed', result: { delivery_approved: true } }],
  artifacts: [{ id: 'generated-docx', name: '任务书.docx', kind: 'docx' }], snapshot: { input_revision: 3 },
  obligations: [], blocked_reasons: [], ...overrides,
});

test('project planning describes taskbook generation within its fixed terminal boundary', () => {
  const stage = scenarioStage(researchCase({}), manifest);
  assert.equal(stage.edit, 'preparation');
  assert.equal(stage.outcome, 'artifacts');
  assert.doesNotMatch([stage.title, stage.guidance, stage.outcomeTitle, stage.editLabel].join(' '), /范围批准|工程设计|方案设计|详细设计|整合|交付/);
});

test('server-confirmed project completion has no further case action even while the legacy stage remains planning', () => {
  const data = researchCase({ project_workflow_status: { status: 'completed', terminal_node_id: 'taskbook' }, taskbook_binding: binding({}), workpackages: [completedPackage({})] });
  assert.equal(nextCaseAction(data, manifest), null);
});

test('current blocked project execution continues to its workpackage evidence', () => {
  const data = researchCase({ project_workflow_status: { status: 'blocked', terminal_node_id: 'taskbook' }, taskbook_binding: binding({}), workpackages: [completedPackage({ status: 'blocked', artifacts: [], blocked_reasons: ['缺少当前来源依据'] })] });
  const action = nextCaseAction(data, manifest);
  assert.equal(action.target, 'workpackages');
  assert.match(action.label, /阻塞|缺口/);
});

test('changed input with stale server projection returns to preparation instead of presenting historical completion', () => {
  const data = researchCase({ input_revision: 4, project_workflow_status: { status: 'stale', terminal_node_id: 'taskbook' }, taskbook_binding: binding({ status: 'stale', invalidated_at: '2026-11-04T01:00:00Z' }), workpackages: [completedPackage({})] });
  const stage = scenarioStage(data, manifest);
  assert.doesNotMatch(stage.title, /已完成|流程完成/);
  assert.equal(nextCaseAction(data, manifest).target, 'preparation');
});

test('a generated project deliverable with passed verification never creates a taskbook-scope approval action', () => {
  const data = researchCase({ taskbook_binding: binding({}), workpackages: [completedPackage({})] });
  const action = nextCaseAction(data, manifest);
  assert.equal(action.target, 'workpackages');
  assert.doesNotMatch(action.label, /范围批准|批准任务书范围|工程设计/);
});

test('legacy planning retains its existing taskbook-scope approval after verified generation', () => {
  const legacyWorkflow = { id: 'legacy-research', version: '1', title: '改型研发流程', status: 'published', product_route: 'modification', nodes: ['taskbook', 'taskbook_scope', 'scheme', 'detail', 'integration', 'verification', 'delivery'] };
  const data = researchCase({ workflow_templates: undefined, project_workflow_status: undefined, taskbook_binding: binding({ workflow: legacyWorkflow }), workpackages: [completedPackage({})] });
  assert.match(scenarioStage(data, manifest).guidance, /范围批准/);
  assert.deepEqual(nextCaseAction(data, manifest), { target: 'decision', label: '核对并批准任务书范围' });
});
