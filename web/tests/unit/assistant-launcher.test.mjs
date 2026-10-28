import assert from 'node:assert/strict';
import test from 'node:test';
import { clampLauncherPosition, launcherAnchorAt, launcherPosition, parseLauncherAnchor, crossedLauncherDragThreshold } from '../../src/features/assistant/model/assistantLauncher.ts';

const geometry = { viewport: { width: 1440, height: 1000 }, footprint: { width: 190, height: 130, offsetX: -5, offsetY: -70 } };

test('launcher edges account for the character extending above and beside its button', () => {
  assert.deepEqual(launcherPosition({ edge: 'left', y: 0 }, geometry), { x: 29, y: 94 });
  assert.deepEqual(launcherPosition({ edge: 'right', y: 1 }, geometry), { x: 1231, y: 916 });
  assert.deepEqual(clampLauncherPosition({ x: -100, y: -100 }, geometry), { x: 29, y: 94 });
  assert.deepEqual(clampLauncherPosition({ x: 9000, y: 9000 }, geometry), { x: 1231, y: 916 });
});

test('release snaps to the nearest visual edge and preserves proportional vertical placement', () => {
  assert.deepEqual(launcherAnchorAt({ x: 100, y: 505 }, geometry), { edge: 'left', y: 0.5 });
  assert.deepEqual(launcherAnchorAt({ x: 1100, y: 505 }, geometry), { edge: 'right', y: 0.5 });
  const small = { viewport: { width: 390, height: 844 }, footprint: geometry.footprint };
  const position = launcherPosition({ edge: 'right', y: 0.5 }, small);
  assert.equal(position.x + geometry.footprint.offsetX + geometry.footprint.width <= 378, true);
  assert.equal(position.y + geometry.footprint.offsetY >= 12, true);
  assert.equal(position.y + geometry.footprint.offsetY + geometry.footprint.height <= 832, true);
  assert.equal(launcherAnchorAt(position, small).y, 0.5);
});

test('a six pixel movement is a drag while a small hand movement remains a click', () => {
  assert.equal(crossedLauncherDragThreshold(3, 3), false);
  assert.equal(crossedLauncherDragThreshold(6, 0), true);
  assert.equal(crossedLauncherDragThreshold(0, -8), true);
});

test('stored UI position accepts only a valid edge and normalized finite height', () => {
  assert.deepEqual(parseLauncherAnchor('{"edge":"left","y":0.35}'), { edge: 'left', y: 0.35 });
  for (const value of [null, '', 'not-json', 'null', '{"edge":"top","y":0.5}', '{"edge":"right","y":-1}', '{"edge":"right","y":2}', '{"edge":"right","y":"0.5"}']) assert.equal(parseLauncherAnchor(value), null);
});
