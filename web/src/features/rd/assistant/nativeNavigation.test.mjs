import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../../../../package.json', import.meta.url));
const ts = require('typescript');
function compile(path, imports = {}) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } });
  const module = { exports: {} };
  new Function('module', 'exports', 'require', outputText)(module, module.exports, name => { if (!(name in imports)) throw new Error('Unexpected import ' + name); return imports[name]; });
  return module.exports;
}
const navigation = compile('../platformNavigation.ts');
const { currentCasePageReference, assistantNavigationTarget } = compile('./nativeNavigation.ts', { '../platformNavigation': navigation });

test('assistant page context contains stable identity and excludes browser credentials or unrelated filters', () => {
  assert.deepEqual(currentCasePageReference('https://server:12345/projects/p1/flows/c1/requirements?token=secret&flow_q=old#row1', 'p1', 'c1'), { schema_version: 1, route_id: 'case.requirements', project_id: 'p1', case_id: 'c1' });
  assert.equal(currentCasePageReference('https://server/projects/p2/flows/c1/materials', 'p1', 'c1'), undefined);
  assert.equal(currentCasePageReference('https://server/work', 'p1', 'c1'), undefined);
});

test('structured navigation opens only recognized workfaces within the current case', () => {
  const ref = { schema_version: 1, route_id: 'case.requirements', project_id: 'p1', case_id: 'c1' };
  assert.equal(assistantNavigationTarget({ page_ref: ref, target: 'sources' }, 'p1', 'c1'), 'requirements');
  for (const patch of [{ project_id: 'p2' }, { case_id: 'c2' }, { route_id: 'https://outside.invalid' }, { schema_version: 2 }, { token: 'secret' }]) {
    assert.equal(assistantNavigationTarget({ page_ref: { ...ref, ...patch }, target: 'sources' }, 'p1', 'c1'), null);
  }
});

test('existing assistant responses retain validated target navigation', () => {
  assert.equal(assistantNavigationTarget({ target: 'sources' }, 'p1', 'c1'), 'sources');
  assert.equal(assistantNavigationTarget({ target: 'https://outside.invalid' }, 'p1', 'c1'), null);
  assert.equal(assistantNavigationTarget(null, 'p1', 'c1'), null);
});

test('structured workpackage navigation preserves its object identity without trusting legacy extras', () => {
  const ref = { schema_version: 1, route_id: 'case.execution', project_id: 'p1', case_id: 'c1', workpackage_id: 'w2' };
  assert.deepEqual(assistantNavigationTarget({ page_ref: ref, target: 'sources' }, 'p1', 'c1'), { target: 'workpackages', workpackageId: 'w2' });
  assert.equal(assistantNavigationTarget({ page_ref: { ...ref, case_id: 'c2' }, target: 'workpackages' }, 'p1', 'c1'), null);
  assert.equal(assistantNavigationTarget({ page_ref: { ...ref, route_id: 'case.materials' }, target: 'workpackages' }, 'p1', 'c1'), null);
  assert.equal(assistantNavigationTarget({ target: 'workpackages', workpackage_id: 'w2' }, 'p1', 'c1'), 'workpackages');
  const { workpackage_id, ...unfocused } = ref;
  assert.equal(assistantNavigationTarget({ page_ref: unfocused }, 'p1', 'c1'), 'workpackages');
});
