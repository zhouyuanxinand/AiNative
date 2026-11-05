import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript');
const { outputText } = ts.transpileModule(readFileSync(new URL('./platformNavigation.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 },
});
const module = { exports: {} };
new Function('module', 'exports', outputText)(module, module.exports);
const { readPlatformLocation: read, platformLocationUrl: url, sameCaseWorkspace } = module.exports;
const base = 'https://platform.example/rd?rd_view=projects&project=p1&case=c1&q=CY&page=2';

test('project directory status, sort and layout survive detail navigation and reject unknown values', () => {
  const href = 'https://platform.example/projects?q=冷却&page=2&status=attention&sort=name&layout=list';
  const location = read(href);
  assert.equal(location.projectStatus, 'attention');
  assert.equal(location.projectSort, 'name');
  assert.equal(location.projectLayout, 'list');
  assert.deepEqual(read(url(href, location).href), location);
  const snapshots = module.exports.captureDirectoryHistory(href, {}).rdDirectoryStates;
  const detail = url(href, { ...location, projectId: 'p1' }, snapshots);
  assert.equal(detail.search, '');
  const returned = read(url(detail.href, { ...read(detail.href), projectId: '' }, snapshots).href);
  assert.equal(returned.projectStatus, 'attention');
  assert.equal(returned.projectSort, 'name');
  assert.equal(returned.projectLayout, 'list');
  assert.equal(returned.q, '冷却');
  assert.equal(returned.page, 2);
  const unknown = read('https://platform.example/projects?status=wrong&sort=wrong&layout=wrong');
  assert.equal(unknown.projectStatus, undefined);
  assert.equal(unknown.projectSort, undefined);
  assert.equal(unknown.projectLayout, undefined);
});

test('semantic routes locate work surfaces and distinguish resume from overview', () => {
  const prefix = 'https://platform.example/projects/p1/flows/c1';
  assert.equal(read(prefix).caseId, 'c1');
  assert.equal(read(prefix).surface, undefined);
  assert.equal(read(prefix + '/overview').surface, 'current');
  assert.equal(read(prefix + '/materials').surface, 'sources');
  assert.equal(read(prefix + '/selection').surface, 'routes');
  assert.equal(read(prefix + '/execution?workpackage=w2').workpackageId, 'w2');
  assert.equal(read(prefix + '/history').evidence, 'history');
  assert.equal(url(base, read(base + '&step=requirements')).pathname, '/projects/p1/flows/c1/requirements');
});

test('page references are host-independent and reject incomplete or foreign identities', () => {
  const { pageReference, locationFromPageReference } = module.exports;
  const ref = { schema_version: 1, route_id: 'case.execution', project_id: 'p1', case_id: 'c1', workpackage_id: 'w2' };
  assert.deepEqual(pageReference(locationFromPageReference(ref)), ref);
  for (const invalid of [{ ...ref, schema_version: 2 }, { route_id: 'work', schema_version: 1, project_id: 'p1' }, { schema_version: 1, route_id: 'case.materials', case_id: 'c1' }, { schema_version: 1, route_id: 'https://evil.invalid' }]) assert.equal(locationFromPageReference(invalid), null);
});

test('page references use the same bounded ASCII identifiers as the backend', () => {
  const { locationFromPageReference } = module.exports;
  const ref = { schema_version: 1, route_id: 'case.execution', project_id: 'p1', case_id: 'c1', workpackage_id: 'w2' };
  for (const key of ['project_id', 'case_id', 'workpackage_id']) {
    for (const invalid of ['', ' project', 'project one', '项目', '.hidden', '-prefix', '_prefix', 'p%20one', 'p/one', 'p\\one', 'x'.repeat(129)]) {
      assert.equal(locationFromPageReference({ ...ref, [key]: invalid }), null, `${key}: ${invalid}`);
    }
    assert.equal(locationFromPageReference({ ...ref, [key]: 'A_1.2-3' }) !== null, true);
    assert.equal(locationFromPageReference({ ...ref, [key]: 'x'.repeat(128) }) !== null, true);
  }
});

test('case and evidence links round-trip while project filters stay in history', () => {
  for (const detail of ['step=sources', 'case_view=process', 'case_view=evidence&evidence=history', 'step=workpackages&workpackage=w2']) {
    const location = read(base + '&' + detail);
    assert.deepEqual(read(url(base, location).href), location);
    assert.equal(location.q, '');
    assert.equal(location.page, 1);
    assert.equal(url(base, location).searchParams.has('q'), false);
    const snapshot = module.exports.captureDirectoryHistory(base, { rdNavigationIndex: 4 });
    assert.equal(snapshot.rdNavigationIndex, 4);
    const list = url(url(base, location).href, { ...location, projectId: '', caseId: '' }, snapshot.rdDirectoryStates);
    assert.equal(list.searchParams.get('q'), 'CY');
    assert.equal(list.searchParams.get('page'), '2');
  }
});

test('only active nondefault directory values appear in canonical addresses', () => {
  const old = 'https://platform.example/?rd_view=flows&flow_tab=actions&flow_q=生成&flow_page=2&flow_kind=research&management_q=CY&management_kind=all&token=secret';
  const state = module.exports.captureDirectoryHistory(old, { rdNavigationIndex: 7 });
  const flow = url(old, read(old), state.rdDirectoryStates);
  assert.equal(flow.pathname, '/flows');
  assert.deepEqual([...flow.searchParams.keys()], ['flow_tab', 'flow_q', 'flow_page']);
  const research = url(flow.href, { ...read(flow.href), view: 'management' }, state.rdDirectoryStates);
  assert.equal(research.href, 'https://platform.example/research?management_q=CY');
  const updated = module.exports.updateDirectoryLocation(research.href, 'management', { q: '', kind: 'all', page: '1', tab: 'product' }, state);
  assert.equal(updated.url.href, 'https://platform.example/research/products');
  assert.equal(updated.state.rdNavigationIndex, 7);
});

test('unknown panels and steps cannot become a view, and unrelated focus is not reused', () => {
  assert.equal(read(base + '&step=unknown&case_view=unknown').surface, undefined);
  assert.equal(read(base + '&step=sources&workpackage=w2').workpackageId, undefined);
  assert.equal(read(base + '&case_view=process&evidence=history').evidence, undefined);
  const current = read(base + '&case_view=evidence&evidence=history');
  const projectList = url(base, { ...current, projectId: '', caseId: '' });
  assert.equal(projectList.searchParams.has('case_view'), false);
  assert.equal(projectList.searchParams.has('evidence'), false);
  assert.equal(projectList.searchParams.get('q'), 'CY');
});

test('path-based case links normalize without losing object identity', () => {
  const source = 'https://platform.example/rd/projects/project%20one/cases/case%202?step=requirements';
  const location = read(source);
  assert.equal(location.projectId, 'project one');
  assert.equal(location.caseId, 'case 2');
  assert.deepEqual(read(url(source, location).href), location);
  assert.doesNotThrow(() => read('https://platform.example/rd/projects/%E0%A4%A'));
});

test('retained forms are only shared within the same case workspace', () => {
  const current = read(base);
  assert.equal(sameCaseWorkspace(current, { ...current, caseView: 'evidence' }), true);
  for (const change of [{ caseId: 'c2' }, { projectId: 'p2' }, { view: 'home' }, { caseId: '' }]) {
    assert.equal(sameCaseWorkspace(current, { ...current, ...change }), false);
  }
});
