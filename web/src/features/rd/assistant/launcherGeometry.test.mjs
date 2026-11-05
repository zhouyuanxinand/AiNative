import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
const require = createRequire(new URL('../../../../package.json', import.meta.url));
const ts = require('typescript');
const source = await readFile(new URL('./launcherGeometry.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const geometry = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
test('only a pointer in the edge strip requests hiding', () => {
  assert.equal(geometry.launcherDockEdge(20, 1440), 'left');
  assert.equal(geometry.launcherDockEdge(1420, 1440), 'right');
  assert.equal(geometry.launcherDockEdge(1380, 1440), null);
  assert.equal(geometry.launcherDockEdge(180, 390), null);
});
test('saved hidden state is restored without breaking existing anchors', () => {
  assert.deepEqual(geometry.parseLauncherAnchor('{"edge":"left","y":0.5,"hidden":true}'), { edge:'left', y:0.5, hidden:true });
  assert.deepEqual(geometry.parseLauncherAnchor('{"edge":"right","y":1}'), { edge:'right', y:1 });
  assert.equal(geometry.parseLauncherAnchor('{"edge":"left","y":2}'), null);
});
test('launcher stays inside short and narrow viewports', () => {
  const area = { viewport:{width:390,height:424}, footprint:{width:48,height:48,offsetX:0,offsetY:0} };
  assert.deepEqual(geometry.launcherPosition({edge:'right', y:1}, area), {x:318, y:352});
  assert.deepEqual(geometry.clampLauncherPosition({x:-100,y:900}, area), {x:24,y:352});
});
