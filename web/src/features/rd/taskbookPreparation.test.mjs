import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript');
const loaded = {};
async function load(name) {
  const source = await readFile(new URL(`./${name}.ts`, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(path => loaded[path.slice(2)], module, module.exports);
  return loaded[name] = module.exports;
}
loaded.presentation = { CONTEXT_FIELDS: [], STAGES: [], isCurrentSource: () => true };
await load('caseOutcomeModel');
const { engineeringState } = await load('engineeringState');
const { nextCaseAction, scenarioManifest } = await load('scenarioManifest');
const manifest = scenarioManifest('taskbook');
const data = binding => ({ stage: 'planning', status: 'active', input_revision: 3, workpackages: [], decisions: [], sources: [], requirements: [], product_route: { value: 'modification' }, composition_route: { value: 'adapt' }, taskbook_binding: binding });
test('planning keeps the user at embedded preparation until a current frozen binding exists', () => {
  for (const binding of [null, { status: 'stale', input_revision: 3 }, { status: 'current', input_revision: 2 }, { status: 'current', input_revision: 3, invalidated_at: 'changed' }]) {
    assert.equal(nextCaseAction(data(binding), manifest).target, 'preparation');
  }
  assert.equal(nextCaseAction(data({ status: 'current', input_revision: 3 }), manifest).target, 'decision');
});
test('taskbook execution remains an embedded design node and completed generation is not business approval', () => {
  const current = { ...data(null), stage: 'design', workpackages: [{ id: 'w', stage: 'design', status: 'completed', nodes: [], artifacts: [{ id: 'a', kind: 'docx' }], snapshot: { input_revision: 3 } }] };
  assert.equal(nextCaseAction(current, manifest).target, 'workpackages');
});
test('mature product planning goes to a real supply decision without a taskbook binding', () => {
  assert.equal(nextCaseAction({ ...data(null), product_route: { value: 'direct' } }, manifest).target, 'decision');
});
test('professional design requires all current adopted-flow nodes and ignores historical conclusions', () => {
  const current = { ...data({ id: 'binding', status: 'current', input_revision: 3, workflow: { nodes: ['taskbook', 'scheme', 'detail', 'integration'] } }), stage: 'design', workpackages: [{ id: 'w', stage: 'design', status: 'completed', nodes: [{ action_id: 'verify', status: 'completed', result: { delivery_approved: true } }], artifacts: [{ id: 'a', kind: 'docx' }], snapshot: { input_revision: 3 } }] };
  const records = ['scheme', 'detail', 'integration'].map((node_id, i) => ({ id: node_id, node_id, prerequisite_record_ids: ['scheme', 'detail'].slice(0, i), input_revision: 3, binding_id: 'binding', verdict: 'approved' }));
  assert.equal(nextCaseAction({ ...current, engineering_records: records.slice(0, 2) }, manifest).target, 'workpackages');
  assert.equal(nextCaseAction({ ...current, engineering_records: records.map(record => ({ ...record, binding_id: 'old' })) }, manifest).target, 'workpackages');
  assert.equal(nextCaseAction({ ...current, engineering_records: records }, manifest).target, 'decision');
  assert.equal(nextCaseAction({ ...current, engineering_records: [...records, { ...records[0], verdict: 'rejected' }] }, manifest).target, 'workpackages');
});


test('a newly approved predecessor invalidates old downstream approvals until their evidence is reviewed again', () => {
  const current = { ...data({ id: 'binding', status: 'current', input_revision: 3, workflow: { nodes: ['taskbook', 'scheme', 'detail', 'integration'] } }), engineering_records: [
    { id: 's1', node_id: 'scheme', binding_id: 'binding', input_revision: 3, verdict: 'approved', prerequisite_record_ids: [] },
    { id: 'd1', node_id: 'detail', binding_id: 'binding', input_revision: 3, verdict: 'approved', prerequisite_record_ids: ['s1'] },
    { id: 'i1', node_id: 'integration', binding_id: 'binding', input_revision: 3, verdict: 'approved', prerequisite_record_ids: ['s1', 'd1'] },
  ] };
  assert.equal(engineeringState(current).complete, true);
  current.engineering_records.push({ ...current.engineering_records[0], id: 's2' });
  assert.equal(engineeringState(current).records[0].id, 's2');
  assert.equal(engineeringState(current).records[1], undefined);
  assert.equal(engineeringState(current).records[2], undefined);
  assert.equal(engineeringState(current).complete, false);
  current.engineering_records.push({ ...current.engineering_records[1], id: 'd2', prerequisite_record_ids: ['s2'] });
  assert.equal(engineeringState(current).records[1].id, 'd2');
  assert.equal(engineeringState(current).complete, false);
  current.engineering_records.push({ ...current.engineering_records[2], id: 'i2', prerequisite_record_ids: ['s2', 'd2'] });
  assert.equal(engineeringState(current).complete, true);
  current.taskbook_binding.invalidated_at = 'changed';
  assert.equal(engineeringState(current).bindingCurrent, false);
  assert.equal(engineeringState(current).complete, false);
});
