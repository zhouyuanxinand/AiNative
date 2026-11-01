import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript');
const source = await readFile(new URL('./workflowLayout.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const { layoutWorkflow } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const node = (id, depends_on = []) => ({ id, action_id: id, action_version: '1', depends_on, required: true });

test('dependency order wins over the array order; chain folds without node overlap', () => {
  const graph = layoutWorkflow([node('e', ['d']), node('c', ['b']), node('a'), node('b', ['a']), node('d', ['c'])]);
  assert.deepEqual(graph.errors, []);
  assert.deepEqual(graph.positions.map(item => item.node.id), ['a', 'b', 'c', 'd', 'e']);
  assert.equal(new Set(graph.positions.map(item => `${item.x},${item.y}`)).size, 5);
  assert(graph.positions[3].y > graph.positions[2].y);
});
test('parallel dependencies get distinct rows and join at the later level', () => {
  const graph = layoutWorkflow([node('a'), node('b', ['a']), node('c', ['a']), node('d', ['b', 'c'])]);
  const [a, b, c, d] = graph.positions;
  assert.equal(b.x, c.x); assert.notEqual(b.y, c.y); assert(d.x > b.x); assert(b.x > a.x);
});
test('cycle, missing dependency and duplicate IDs produce actionable errors', () => {
  assert.match(layoutWorkflow([node('a', ['b']), node('b', ['a'])]).errors.join(), /环路/);
  assert.match(layoutWorkflow([node('a', ['gone'])]).errors.join(), /缺失/);
  assert.match(layoutWorkflow([node('a'), node('a')]).errors.join(), /重复/);
});
test('empty plans and node statuses do not invent graph edges or positions', () => {
  assert.deepEqual(layoutWorkflow([]).positions, []);
  const original = [node('a'), node('b', ['a'])];
  assert.deepEqual(layoutWorkflow(original).positions.map(({x,y})=>[x,y]), layoutWorkflow(original.map(n=>({...n,status:'running'}))).positions.map(({x,y})=>[x,y]));
});
