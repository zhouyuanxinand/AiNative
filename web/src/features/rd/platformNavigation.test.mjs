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

test('case and evidence links round-trip with project-list filters', () => {
  for (const detail of ['step=sources', 'case_view=process', 'case_view=evidence&evidence=history', 'step=workpackages&workpackage=w2']) {
    const location = read(base + '&' + detail);
    assert.deepEqual(read(url(base, location).href), location);
    assert.equal(location.q, 'CY');
    assert.equal(location.page, 2);
  }
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
