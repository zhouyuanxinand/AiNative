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
const { readCaseResume, writeCaseResume, browserCaseResumeStorage } = load('caseResume');
const { scenarioManifest } = load('scenarioManifest');
const manifest = scenarioManifest('taskbook');
const projectTemplate = {
  id: 'taskbook-generation', version: '1', title: '任务书流程', category: 'project', status: 'published',
  digest: 'fixed-project', graph: { nodes: [], edges: [] }, publication_revision: 1,
};
const researchCase = overrides => ({
  id: 'case', title: '测试项目', scenario_id: 'taskbook', stage: 'input', status: 'active', input_revision: 3,
  sources: [], source_selection: {}, requirements: [], clarifications: [], comparisons: [],
  product_route: null, composition_route: null, context: {}, decisions: [], workpackages: [],
  business_lifecycle: { policy_version: 'v2', rd_activation_state: 'not_started' },
  workflow_templates: { project: projectTemplate }, project_workflow_status: { status: 'pending' },
  ...overrides,
});
const memoryStorage = () => {
  const values = new Map();
  return { values, getItem: key => values.get(key) ?? null, setItem: (key, value) => { values.set(key, value); } };
};
const read = (data, storage, actor = 'local:user', projectId = 'project', caseId = 'case') =>
  readCaseResume(actor, projectId, caseId, data, manifest, storage);
const write = (surface, data, storage, actor = 'local:user', projectId = 'project', caseId = 'case') =>
  writeCaseResume(actor, projectId, caseId, surface, data, storage);

test('without a saved step, opens the current business step, including adopted input review', () => {
  const storage = memoryStorage();
  assert.equal(read(researchCase({}), storage), 'sources');
  assert.equal(read(researchCase({ source_analysis: { status: 'adopted', adopted_input_revision: 3 } }), storage), 'requirements');
  assert.equal(read(researchCase({ stage: 'selection' }), storage), 'routes');
});

test('reopens an available previous editing step without changing the current business stage', () => {
  const storage = memoryStorage();
  const data = researchCase({ stage: 'planning' });
  write('requirements', data, storage);
  assert.equal(read(data, storage), 'requirements');
  assert.equal(data.stage, 'planning');
});

test('current submitted or running execution takes precedence over a saved earlier step', () => {
  const storage = memoryStorage();
  const data = researchCase({ stage: 'planning' });
  write('sources', data, storage);
  for (const status of ['submitted', 'running']) {
    const executing = { ...data, workpackages: [{ id: 'package', stage: 'planning', status, snapshot: { input_revision: 3 }, nodes: [], artifacts: [] }] };
    assert.equal(read(executing, storage), 'workpackages');
    assert.deepEqual([...storage.values.values()], ['sources']);
    assert.equal(read({ ...executing, project_workflow_status: { status: 'completed' } }, storage), 'current');
  }
});

test('historical or other-stage running records do not override the saved current editing step', () => {
  const storage = memoryStorage();
  const data = researchCase({ stage: 'planning' });
  write('sources', data, storage);
  for (const workpackage of [
    { stage: 'planning', status: 'running', snapshot: { input_revision: 2 } },
    { stage: 'design', status: 'running', snapshot: { input_revision: 3 } },
    { stage: 'planning', status: 'blocked', snapshot: { input_revision: 3 } },
  ]) {
    assert.equal(read({ ...data, workpackages: [{ ...workpackage, id: 'package', nodes: [], artifacts: [] }] }, storage), 'sources');
  }
});

test('saved steps are isolated by actor, project and case', () => {
  const storage = memoryStorage();
  const data = researchCase({ stage: 'planning' });
  write('requirements', data, storage);
  assert.equal(read(data, storage), 'requirements');
  assert.equal(read(data, storage, 'oa:user'), 'preparation');
  assert.equal(read(data, storage, 'local:user', 'other-project'), 'preparation');
  assert.equal(read(data, storage, 'local:user', 'project', 'other-case'), 'preparation');
});

test('identity segments cannot collide through separators or encoded characters', () => {
  const storage = memoryStorage();
  const data = researchCase({ stage: 'planning' });
  write('sources', data, storage, 'user:a', 'b', 'c');
  write('requirements', data, storage, 'user', 'a:b', 'c');
  write('routes', data, storage, 'user%3Aa', 'b', 'c');
  assert.equal(storage.values.size, 3);
  assert.equal(read(data, storage, 'user:a', 'b', 'c'), 'sources');
  assert.equal(read(data, storage, 'user', 'a:b', 'c'), 'requirements');
  assert.equal(read(data, storage, 'user%3Aa', 'b', 'c'), 'routes');
});

test('overview, process and evidence visits do not overwrite the last editing step', () => {
  const storage = memoryStorage();
  const data = researchCase({ stage: 'planning' });
  write('requirements', data, storage);
  for (const surface of ['current', 'process', 'evidence', 'unknown']) write(surface, data, storage);
  assert.equal(read(data, storage), 'requirements');
  assert.deepEqual([...storage.values.values()], ['requirements']);
});

test('business decision pages persist their owning step rather than a generic decision destination', () => {
  const storage = memoryStorage();
  for (const [stage, expected] of [['requirements', 'requirements'], ['selection', 'routes'], ['design', 'workpackages']]) {
    const data = researchCase({ stage });
    write('decision', data, storage);
    assert.equal(read(data, storage), expected);
    assert.deepEqual([...storage.values.values()], [expected]);
  }
});

test('legacy planning decisions restore preparation and later legacy steps remain reachable', () => {
  const storage = memoryStorage();
  const legacy = researchCase({
    stage: 'planning', workflow_templates: undefined, project_workflow_status: undefined,
    business_lifecycle: { policy_version: 'legacy_v1' },
  });
  write('decision', legacy, storage);
  assert.equal(read(legacy, storage), 'preparation');
  for (const [stage, surface] of [['delivery', 'delivery'], ['knowledge', 'reuse']]) {
    const later = { ...legacy, stage };
    write(surface, later, storage);
    assert.equal(read(later, storage), surface);
  }
});

test('v2 planning decisions restore execution only after current inputs make that step available', () => {
  const storage = memoryStorage();
  const data = researchCase({ stage: 'planning' });
  write('preparation', data, storage);
  write('decision', data, storage);
  assert.deepEqual([...storage.values.values()], ['preparation']);
  const bound = { ...data, taskbook_binding: { status: 'current', input_revision: 3 } };
  write('decision', bound, storage);
  assert.equal(read(bound, storage), 'workpackages');
  assert.deepEqual([...storage.values.values()], ['workpackages']);
});

test('unavailable future steps cannot be written or restored after case state changes', () => {
  const storage = memoryStorage();
  const initial = researchCase({});
  write('sources', initial, storage);
  write('workpackages', initial, storage);
  assert.equal(read(initial, storage), 'sources');
  const later = researchCase({ stage: 'design' });
  write('workpackages', later, storage);
  assert.equal(read(later, storage), 'workpackages');
  assert.equal(read(initial, storage), 'sources');
});

test('a removed step from a different workflow version falls back to the active step', () => {
  const storage = memoryStorage();
  const legacy = researchCase({ stage: 'delivery', workflow_templates: undefined, project_workflow_status: undefined });
  write('delivery', legacy, storage);
  assert.equal(read(researchCase({ stage: 'planning' }), storage), 'preparation');
});

test('completed fixed and legacy workflows open the outcome and preserve the saved editing step', () => {
  const storage = memoryStorage();
  const data = researchCase({ stage: 'planning' });
  write('requirements', data, storage);
  const completed = [
    { ...data, project_workflow_status: { status: 'completed' } },
    { ...data, status: 'completed', workflow_templates: undefined, project_workflow_status: undefined },
  ];
  for (const item of completed) {
    assert.equal(read(item, storage), 'current');
    write('sources', item, storage);
    assert.deepEqual([...storage.values.values()], ['requirements']);
  }
});

test('empty, malformed, non-step and generic decision values fall back safely', () => {
  const data = researchCase({ stage: 'planning' });
  for (const value of ['', 'decision', 'current', 'process', 'evidence', 'null', '{"surface":"sources"}', ' sources ']) {
    assert.equal(read(data, { getItem: () => value, setItem: () => {} }), 'preparation');
  }
});

test('missing identity never reads or writes another account or case navigation', () => {
  const data = researchCase({ stage: 'planning' });
  const storage = { getItem: () => assert.fail('must not read'), setItem: () => assert.fail('must not write') };
  for (const [actor, projectId, caseId] of [[null, 'p', 'c'], [undefined, 'p', 'c'], ['', 'p', 'c'], ['a', '', 'c'], ['a', 'p', '']]) {
    assert.equal(readCaseResume(actor, projectId, caseId, data, manifest, storage), 'preparation');
    writeCaseResume(actor, projectId, caseId, 'sources', data, storage);
  }
});

test('disabled or failing storage leaves navigation usable without throwing', () => {
  const data = researchCase({ stage: 'selection' });
  assert.equal(read(data, null), 'routes');
  write('sources', data, null);
  const inaccessible = {
    getItem: () => { throw new Error('storage blocked'); },
    setItem: () => { throw new Error('quota exceeded'); },
  };
  assert.equal(read(data, inaccessible), 'routes');
  assert.doesNotThrow(() => write('sources', data, inaccessible));
  assert.equal(browserCaseResumeStorage(), null);
});

test('persists only the navigation identifier, never source names, model settings or business data', () => {
  const storage = memoryStorage();
  const data = researchCase({ title: 'Private product', context: { api_key: 'secret' }, stage: 'planning' });
  write('sources', data, storage);
  assert.deepEqual([...storage.values.entries()], [['rd:case-resume:v1:local%3Auser:project:case', 'sources']]);
});
