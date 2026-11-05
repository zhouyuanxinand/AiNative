import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../package.json', import.meta.url));
const ts = require('typescript');
const source = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } });
const module = { exports: {} };
// Route resolution does not mount screens or initialize their network effects.
new Function('require', 'module', 'exports', outputText)(name => name.startsWith('react') ? require(name) : {}, module, module.exports);
const { resolveAppRoute } = module.exports;

test('retired taskbook and former fallback entries resolve to the research platform', () => {
  for (const path of ['/taskbook', '/taskbook/', '/taskbook/legacy', '/old-workspace']) {
    assert.deepEqual(resolveAppRoute(path, ''), { page: 'rd', replaceUrl: '/rd' });
  }
});

test('legacy redirects keep only research navigation and drop callback credentials and fragments', () => {
  assert.deepEqual(resolveAppRoute('/taskbook', '?project=p1&case=c1&rd_view=projects&q=%E9%9C%80%E6%B1%82&page=2&userid=fixture-user&token=fixture-token&_jtb_auth_state=fixture-state&appid=9086&access_token=fixture-access&redirect_uri=https%3A%2F%2Fexample.invalid', '#fixture-token'),
    { page: 'rd', replaceUrl: '/rd?project=p1&case=c1&rd_view=projects&q=%E9%9C%80%E6%B1%82&page=2' });
});

test('existing research deep links keep their object identity while sensitive query fields are removed', () => {
  assert.deepEqual(resolveAppRoute('/rd/projects/p1/cases/c1', '?q=CY&page=2'), { page: 'rd' });
  assert.deepEqual(resolveAppRoute('/rd', '?rd_view=projects&token=fixture-token'), { page: 'rd', replaceUrl: '/rd?rd_view=projects' });
  assert.deepEqual(resolveAppRoute('/', ''), { page: 'rd' });
});

test('admin, help, logs and genuine review routes retain their existing screens', () => {
  assert.deepEqual(resolveAppRoute('/admin/', '?view=resources'), { page: 'admin' });
  assert.deepEqual(resolveAppRoute('/feedback', ''), { page: 'admin' });
  assert.deepEqual(resolveAppRoute('/help/manual', ''), { page: 'help', kind: 'manual' });
  assert.deepEqual(resolveAppRoute('/help/video', ''), { page: 'help', kind: 'video' });
  assert.deepEqual(resolveAppRoute('/log', ''), { page: 'logs' });
  assert.deepEqual(resolveAppRoute('/logs', ''), { page: 'logs' });
  assert.deepEqual(resolveAppRoute('/review/job%20one/', '?revision=revision-2'), { page: 'review', jid: 'job one' });
});

test('malformed review identifiers do not throw or become generated job identities', () => {
  assert.deepEqual(resolveAppRoute('/review/%E0%A4%A', ''), { page: 'rd', replaceUrl: '/rd' });
});

test('directory URLs preserve independent state while unknown keys and credentials are removed', () => {
  const search = '?rd_view=workspace&workspace_q=Skill&workspace_kind=skill&workspace_page=2&workspace_item=s1&workspace_version=1&flow_tab=actions&flow_kind=research&flow_item=f1%401&flow_version=1&flow_detail=canvas&flow_q=test&flow_page=3&management_q=CY&management_kind=completed&management_page=2&knowledge_q=YLZJ&knowledge_kind=all&knowledge_page=3';
  assert.deepEqual(resolveAppRoute('/', search), { page: 'rd' });
  assert.deepEqual(resolveAppRoute('/', search + '&workspace_token=secret&flow_appid=evil&token=secret'), { page: 'rd', replaceUrl: '/' + search });
});

test('case work surfaces and evidence deep links survive reload without retaining credentials', () => {
  for (const detail of ['case_view=process', 'case_view=evidence&evidence=history', 'step=workpackages&workpackage=package-2']) {
    const search = `?rd_view=projects&project=p1&case=c1&${detail}&q=CY&page=2`;
    assert.deepEqual(resolveAppRoute('/rd', search), { page: 'rd' });
    assert.deepEqual(resolveAppRoute('/rd', search + '&token=secret'), { page: 'rd', replaceUrl: '/rd' + search });
  }
});
