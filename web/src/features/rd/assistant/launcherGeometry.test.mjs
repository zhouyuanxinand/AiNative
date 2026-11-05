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

test('a free placement survives persistence and viewport resize in both axes', () => {
  const area = { viewport:{width:1440,height:1000}, footprint:{width:100,height:100,offsetX:0,offsetY:0} };
  const point = { x:550, y:370 };
  const saved = geometry.parseLauncherAnchor(JSON.stringify(geometry.launcherAnchorAt(point, area)));
  assert.deepEqual(geometry.launcherPosition(saved, area), point);
  const resized = geometry.launcherPosition(saved, { ...area, viewport:{width:390,height:700} });
  assert(resized.x > 24 && resized.x < 266 && resized.y > 24 && resized.y < 576);
  assert.deepEqual(geometry.launcherPosition(saved, area), point);
});

test('free horizontal coordinates are validated while legacy anchors remain compatible', () => {
  assert.deepEqual(geometry.parseLauncherAnchor('{"edge":"left","x":0.4,"y":0.5}'), { edge:'left', x:0.4, y:0.5 });
  for (const x of [-0.01, 1.01, '0.5', null]) {
    assert.equal(geometry.parseLauncherAnchor(JSON.stringify({ edge:'right', x, y:0.5 })), null);
  }
});
