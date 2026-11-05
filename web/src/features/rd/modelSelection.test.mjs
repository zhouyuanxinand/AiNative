import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript');
const modules = new Map();
function load(url) {
  if (modules.has(url.href)) return modules.get(url.href).exports;
  const module = { exports: {} }; modules.set(url.href, module);
  const { outputText } = ts.transpileModule(readFileSync(url, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } });
  new Function('require', 'module', 'exports', outputText)(path => path.startsWith('.') ? load(new URL(path + '.ts', url)) : require(path), module, module.exports);
  return module.exports;
}
const { modelSelectionKey } = load(new URL('../../lib/model.ts', import.meta.url));
const { normalizeModelSelection, normalizeModelCatalog, modelDisplayLabel, buildModelOptions, readRecentModels, rememberRecentModel, recentModelsKey } = load(new URL('./modelSelection.ts', import.meta.url));
const azure = { provider: 'smartvision', name: 'azure/gpt-5.4', id: '7' };
const dash = { provider: 'smartvision', name: 'dashscope/deepseek-v4-pro', id: '8' };
const flatten = items => items.flatMap(item => item.options ?? [item]);
const storage = () => { const entries = new Map(); return { getItem: key => entries.get(key) ?? null, setItem: (key, value) => entries.set(key, value) }; };

test('object order never changes selection, and the default has a readable label', () => {
  const reversed = { id: '', name: '', provider: '' };
  assert.equal(modelSelectionKey(normalizeModelSelection(reversed)), modelSelectionKey({ provider: '', name: '', id: '' }));
  const options = flatten(buildModelOptions([], reversed, []));
  assert.equal(options.find(item => item.value === modelSelectionKey(reversed)).label, '使用平台默认模型');
});
test('catalog keeps vendor and execution identity, deduplicates, and respects availability', () => {
  const catalog = normalizeModelCatalog([{ ...azure, vendor: '微软 Azure', configured: true }, { ...azure }, { ...dash, vendor: '阿里云 DashScope', configured: false }]);
  assert.equal(catalog.length, 2); assert.equal(catalog[0].provider, 'smartvision');
  assert.equal(modelDisplayLabel(catalog[0]), '微软 Azure · azure/gpt-5.4');
  assert.equal(flatten(buildModelOptions(catalog, azure, [dash])).find(item => item.value === modelSelectionKey(dash)).disabled, true);
  assert.equal(buildModelOptions(catalog, azure, [dash]).some(group => group.label === '最近使用'), false);
});
test('recents are first, unique, and limited to models in the current catalog', () => {
  const catalog = normalizeModelCatalog([{ ...azure, vendor: '微软 Azure' }, { ...dash, vendor: '阿里云 DashScope' }]);
  const options = buildModelOptions(catalog, azure, [dash, dash, { ...azure, id: 'removed' }]);
  const group = options.find(item => item.label === '最近使用');
  assert.deepEqual(group.options.map(item => item.value), [modelSelectionKey(dash)]);
  assert.equal(flatten(options).filter(item => item.value === modelSelectionKey(dash)).length, 1);
});
test('a saved model missing from catalog remains readable without becoming a new available option', () => {
  const options = flatten(buildModelOptions([], azure, [azure]));
  const saved = options.find(item => item.value === modelSelectionKey(azure));
  assert.match(saved.label, /微软 Azure.*azure\/gpt-5.4/); assert.equal(saved.disabled, true);
  assert.equal(modelDisplayLabel(azure), '微软 Azure · azure/gpt-5.4');
});
test('recent history persists per actor, newest first, deduplicates and caps at five', () => {
  const cache = storage();
  for (let i = 0; i < 7; i++) rememberRecentModel(cache, 'actor-a', { ...azure, id: String(i), name: `azure/model-${i}` });
  assert.equal(readRecentModels(cache, 'actor-a').length, 5);
  assert.equal(readRecentModels(cache, 'actor-a')[0].id, '6');
  rememberRecentModel(cache, 'actor-a', { ...azure, id: '3', name: 'azure/model-3' });
  assert.equal(readRecentModels(cache, 'actor-a')[0].id, '3');
  assert.equal(readRecentModels(cache, 'actor-a').length, 5);
  assert.deepEqual(readRecentModels(cache, 'actor-b'), []);
  assert.deepEqual(readRecentModels(cache, ''), []);
  assert.notEqual(recentModelsKey('actor:a'), recentModelsKey('actor/a'));
  rememberRecentModel(cache, 'actor-a', { provider: '', name: '', id: '' });
  assert.equal(readRecentModels(cache, 'actor-a').length, 5);
});
test('unavailable storage or corrupt history cannot break model selection or saving', () => {
  const cache = storage(); cache.setItem(recentModelsKey('actor'), '{bad');
  assert.deepEqual(readRecentModels(cache, 'actor'), []);
  cache.setItem(recentModelsKey('actor'), JSON.stringify([null, 5, {}, azure]));
  assert.deepEqual(readRecentModels(cache, 'actor'), [azure]);
  const denied = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  assert.deepEqual(readRecentModels(denied, 'actor'), []);
  assert.deepEqual(rememberRecentModel(denied, 'actor', azure), [azure]);
});
