import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript'), loaded = new Map();
function load(name) {
  if (loaded.has(name)) return loaded.get(name).exports;
  const source = readFileSync(new URL(`./${name}.ts`, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } });
  const module = { exports: {} }; loaded.set(name, module);
  new Function('require', 'module', 'exports', outputText)(path => path.startsWith('./') ? load(path.slice(2)) : require(path), module, module.exports);
  return module.exports;
}
const { projectCaseCardModel } = load('projectCaseCardModel');
const template = states => ({ id: 'fixed-flow', version: '2', title: '固定任务书流程', graph: { nodes: ['input', 'requirements', 'taskbook'].map(id => ({ id, title: id })), edges: [] }, node_states: states });
const researchCase = extra => ({ id: 'c', title: '流程甲', scenario_id: 'taskbook', stage: 'input', status: 'active', input_revision: 3, context: {}, sources: [], requirements: [], decisions: [], workpackages: [], product_route: null, composition_route: null, ...extra });
const project = { id: 'p', title: '项目', owner_id: '真实负责人账号' };
const wp = (id, status, extra = {}) => ({ id, title: id, status, stage: 'planning', nodes: [], artifacts: [], blocked_reasons: [], snapshot: { input_revision: 3 }, ...extra });
const view = value => projectCaseCardModel(project, researchCase(value));

test('fixed node progress uses actual completed states, while current source and requirement counts exclude history', () => {
  const result = view({ workflow_templates: { project: template({ input: 'completed', requirements: 'pending_decision', taskbook: 'running' }) }, project_workflow_status: { status: 'running' },
    source_selection: { tech: 'new' }, sources: [{ id: 'old', role: 'tech' }, { id: 'new', role: 'tech' }, { id: 'ref', role: 'reference' }],
    requirements: [{ id: 'current', source_ids: ['new'] }, { id: 'old', source_ids: ['old'] }, { id: 'unknown', source_ids: [] }] });
  assert.equal(result.progress.completed, 1); assert.equal(result.progress.total, 3);
  assert.equal(result.progress.percent, 100 / 3); assert.equal(result.sourceCount, 2); assert.equal(result.requirementCount, 1);
  assert.equal(result.owner, project.owner_id); assert.equal(result.completed, false);
});

test('missing node states and zero-node templates never manufacture a progress percentage', () => {
  const absent = view({ workflow_templates: { project: template(undefined) } });
  assert.equal(absent.progress.percent, null); assert.match(absent.progress.label, /未记录/);
  const partial = view({ workflow_templates: { project: template({ input: 'completed' }) } });
  assert.equal(partial.progress.percent, null); assert.equal(partial.progress.completed, 1); assert.match(partial.progress.label, /未记录/);
  const empty = template({}); empty.graph.nodes = [];
  assert.equal(view({ workflow_templates: { project: empty } }).progress.percent, null);
});

test('stale fixed workflow never inherits historical completed progress or a legacy completed case flag', () => {
  const result = view({ status: 'completed', workflow_templates: { project: { ...template({ input: 'completed', requirements: 'completed', taskbook: 'completed' }), stale: true } }, project_workflow_status: { status: 'stale', reason: '当前输入已变更，请重新固定' } });
  assert.equal(result.completed, false); assert.equal(result.progress.percent, null);
  assert.equal(result.status, 'stale'); assert.equal(result.attention, '当前输入已变更，请重新固定');
  assert.equal(result.actionLabel, '继续办理');
});

test('fixed terminal state controls outcome navigation; a completed package alone does not complete the flow', () => {
  const incomplete = view({ workflow_templates: { project: template({}) }, project_workflow_status: { status: 'pending' }, workpackages: [wp('done', 'completed')] });
  assert.equal(incomplete.completed, false);
  const done = view({ workflow_templates: { project: template({ input: 'completed', requirements: 'completed', taskbook: 'completed' }) }, project_workflow_status: { status: 'completed' } });
  assert.equal(done.actionLabel, '查看成果'); assert.equal(done.progress.percent, 100); assert.equal(done.stepTitle, '流程已完成');
});

test('attention and artifacts use current input records, excluding old failed runs and cancelled output', () => {
  const result = view({ stage: 'planning', workpackages: [
    wp('old', 'failed', { snapshot: { input_revision: 2 }, blocked_reasons: ['历史失败'], artifacts: [{ id: 'old' }] }),
    wp('cancel', 'cancelled', { artifacts: [{ id: 'cancel' }] }),
    wp('now', 'blocked', { blocked_reasons: [{ message: '缺少当前证据' }], artifacts: [{ id: 'current' }] }),
  ] });
  assert.equal(result.status, 'blocked'); assert.equal(result.attention, '缺少当前证据'); assert.equal(result.artifactCount, 1);
});

test('fixed flow execution references exclude same-revision old bindings and superseded failures', () => {
  const result = view({ stage: 'planning', workflow_templates: { project: { ...template({ input: 'completed', requirements: 'completed', taskbook: 'completed' }), node_execution_refs: { taskbook: { workpackage_id: 'current', run_id: 'run-current', step_instance_ids: ['generate'] } } } }, project_workflow_status: { status: 'completed' }, workpackages: [
    wp('old', 'failed', { run_id: 'run-old', artifacts: [{ id: 'old-document' }], blocked_reasons: ['旧绑定失败'], planned_end: '2026-01-01' }),
    wp('current', 'completed', { run_id: 'run-current', artifacts: [{ id: 'current-document' }] }),
  ] });
  assert.equal(result.status, 'completed'); assert.equal(result.attention, null); assert.equal(result.artifactCount, 1); assert.equal(result.deadline, null);
  const unreferenced = view({ stage: 'planning', workflow_templates: { project: template({}) }, project_workflow_status: { status: 'pending' }, workpackages: [wp('old', 'failed', { artifacts: [{ id: 'old' }], blocked_reasons: ['旧失败'] })] });
  assert.equal(unreferenced.status, 'pending'); assert.equal(unreferenced.attention, null); assert.equal(unreferenced.artifactCount, 0);
});

test('deadline uses the earliest valid current open workpackage date; illegal, reverse and historical dates stay unknown', () => {
  const result = view({ stage: 'planning', workpackages: [wp('old', 'running', { snapshot: { input_revision: 2 }, planned_end: '2026-01-01' }), wp('done', 'completed', { planned_end: '2026-01-02' }), wp('later', 'running', { planned_end: '2026-12-10' }), wp('near', 'draft', { snapshot: null, planned_start: '2026-11-01', planned_end: '2026-11-20' })] });
  assert.equal(result.deadline, '2026-11-20');
  for (const dates of [{ planned_end: '2026-02-30' }, { planned_start: '2026-12-01', planned_end: '2026-11-20' }, { planned_end: 'not-a-date' }]) {
    assert.equal(view({ stage: 'planning', workpackages: [wp('invalid', 'draft', dates)] }).deadline, null);
  }
});

test('delivery is independent of generation and only the latest current-input receipt is shown', () => {
  assert.equal(view({ workpackages: [wp('done', 'completed', { artifacts: [{ id: 'doc' }] })] }).delivery, '未登记');
  const result = view({ deliveries: [{ id: 'old', input_revision: 2, outcome: 'accepted', created_at: '2026-11-04T05:00:00Z' }, { id: 'accepted', input_revision: 3, outcome: 'accepted', created_at: '2026-11-04T03:00:00Z' }, { id: 'revise', input_revision: 3, outcome: 'revision_required', created_at: '2026-11-04T04:00:00Z' }] });
  assert.equal(result.delivery, '需修订');
});

test('legacy and empty cases retain honest unknowns and never infer a responsible person from actors or node roles', () => {
  const empty = projectCaseCardModel({ ...project, owner_id: '' }, researchCase({ decisions: [{ actor: '审批人' }] }));
  assert.equal(empty.owner, '未设置'); assert.equal(empty.deadline, null); assert.equal(empty.progress.percent, null); assert.equal(empty.delivery, '未登记');
  const legacy = view({ stage: 'planning', workpackages: [wp('now', 'running', { nodes: [{ status: 'completed' }, { status: 'running' }] }), wp('old', 'completed', { snapshot: { input_revision: 2 }, nodes: [{ status: 'completed' }] })] });
  assert.equal(legacy.progress.completed, 1); assert.equal(legacy.progress.total, 2); assert.match(legacy.progress.label, /执行步骤/);
});

test('legacy parallel execution keeps the shared running state and separately exposes a blocked package', () => {
  const result = view({ stage: 'planning', workpackages: [wp('failed', 'failed', { blocked_reasons: ['一份工作包缺证据'] }), wp('running', 'running')] });
  assert.equal(result.status, 'running'); assert.equal(result.attention, '一份工作包缺证据');
});
