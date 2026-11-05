import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript');
const source = await readFile(new URL('./flowEdgeGeometry.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const { routeFlowEdge } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const rect = (x, y, width = 210, height = 108) => ({ x, y, width, height });
const normal = { top: { x: 0, y: -1 }, right: { x: 1, y: 0 }, bottom: { x: 0, y: 1 }, left: { x: -1, y: 0 } };
const delta = (a, b) => ({ x: b.x - a.x, y: b.y - a.y });
const dot = (a, b) => a.x * b.x + a.y * b.y;
function intersectsInterior(a, b, box) {
  return a.x === b.x ? a.x > box.x && a.x < box.x + box.width && Math.max(a.y, b.y) > box.y && Math.min(a.y, b.y) < box.y + box.height
    : a.y > box.y && a.y < box.y + box.height && Math.max(a.x, b.x) > box.x && Math.min(a.x, b.x) < box.x + box.width;
}
function assertSafe(route, from, to, obstacles = []) {
  assert.equal(route.clear, true);
  assert.match(route.path, /^M[\d\s.,-]+(?:L[\d\s.,-]+)+$/);
  assert(route.points.length >= 2);
  assert.deepEqual(route.points[0], route.sourcePoint);
  assert.deepEqual(route.points.at(-1), route.targetPoint);
  for (const [point, side, box] of [[route.sourcePoint, route.sourceSide, from], [route.targetPoint, route.targetSide, to]]) {
    if (side === 'left' || side === 'right') {
      assert.equal(point.x, side === 'left' ? box.x : box.x + box.width);
      assert(point.y >= box.y && point.y <= box.y + box.height);
    } else {
      assert.equal(point.y, side === 'top' ? box.y : box.y + box.height);
      assert(point.x >= box.x && point.x <= box.x + box.width);
    }
  }
  assert(dot(delta(route.points[0], route.points[1]), normal[route.sourceSide]) > 0, 'first segment leaves source outward');
  assert(dot(delta(route.points.at(-2), route.points.at(-1)), normal[route.targetSide]) < 0, 'arrow enters target inward');
  for (let i = 1; i < route.points.length; i++) {
    const a = route.points[i - 1], b = route.points[i];
    assert(a.x === b.x || a.y === b.y, 'every segment is orthogonal');
    assert.notDeepEqual(a, b, 'no zero-length segments');
    for (const box of [from, to, ...obstacles]) assert(!intersectsInterior(a, b, box), `segment crosses node ${JSON.stringify({ a, b, box })}`);
  }
  assert(route.points.every(point => Number.isFinite(point.x) && Number.isFinite(point.y)));
  assert(route.points.every(point => point.x >= route.bounds.x && point.x <= route.bounds.x + route.bounds.width && point.y >= route.bounds.y && point.y <= route.bounds.y + route.bounds.height));
  assert(route.points.some((end, i) => i && (end.x === route.points[i - 1].x && route.labelPoint.x === end.x && route.labelPoint.y >= Math.min(end.y, route.points[i - 1].y) && route.labelPoint.y <= Math.max(end.y, route.points[i - 1].y) || end.y === route.points[i - 1].y && route.labelPoint.y === end.y && route.labelPoint.x >= Math.min(end.x, route.points[i - 1].x) && route.labelPoint.x <= Math.max(end.x, route.points[i - 1].x))), 'label remains on routed path');
}
test('horizontal and reverse dragging choose facing edges with inward arrows', () => {
  for (const [from, to, sides] of [[rect(24,24), rect(400,24), ['right','left']], [rect(400,24),rect(24,24),['left','right']]]) {
    const route = routeFlowEdge(from,to); assertSafe(route,from,to);
    assert.deepEqual([route.sourceSide,route.targetSide],sides);
    assert.equal(route.points.length,2);
  }
});
test('vertical dragging switches from right-left ports to bottom-top or top-bottom', () => {
  for (const [from,to,sides] of [[rect(300,24),rect(300,320),['bottom','top']],[rect(300,320),rect(300,24),['top','bottom']]]) {
    const route=routeFlowEdge(from,to);assertSafe(route,from,to);assert.deepEqual([route.sourceSide,route.targetSide],sides);
  }
});
test('aligned nodes separated by only 30px connect directly without outward-stub detours', () => {
  for (const [from,to,sides] of [[rect(0,0),rect(240,0),['right','left']],[rect(240,0),rect(0,0),['left','right']],[rect(0,0),rect(0,138),['bottom','top']],[rect(0,138),rect(0,0),['top','bottom']]]) {
    const route=routeFlowEdge(from,to);assertSafe(route,from,to);
    assert.deepEqual([route.sourceSide,route.targetSide],sides);
    assert.equal(route.points.length,2,'available straight gap must not route around a node');
    assert.equal(Math.abs(route.sourcePoint.x-route.targetPoint.x)+Math.abs(route.sourcePoint.y-route.targetPoint.y),30);
  }
});
test('sub-stub gaps remain direct while touching nodes use a nonzero clear path', () => {
  const from=rect(0,0);
  for (const gap of [1,9,18]) {
    const to=rect(210+gap,0),route=routeFlowEdge(from,to);assertSafe(route,from,to);assert.equal(route.points.length,2);
  }
  const touching=rect(210,0);assertSafe(routeFlowEdge(from,touching),from,touching);
});
test('close diagonal and crossed axes keep every segment outside both node interiors', () => {
  const from=rect(300,300);
  for(const to of [rect(512,350),rect(85,350),rect(380,410),rect(380,190),rect(512,410),rect(85,190),rect(510,408)]) assertSafe(routeFlowEdge(from,to),from,to);
});
test('obstacles and staggered lanes route around node bodies without depending on node size constants', () => {
  const from=rect(100,200),to=rect(800,250),walls=[rect(40,100,270,50),rect(40,350,270,50),rect(320,150,30,150),rect(440,280,30,160),rect(560,150,30,150)];
  assertSafe(routeFlowEdge(from,to,walls),from,to,walls);
  const a=rect(20,20,100,44),b=rect(500,20,180,70),middle=rect(220,0,100,140);
  assertSafe(routeFlowEdge(a,b,[a,b,middle]),a,b,[middle]);
});
test('repeated positions across all quadrants recompute exact endpoints deterministically', () => {
  const from=rect(320,320),before=structuredClone(from);let previousPath='';
  for(const [x,y] of [[24,24],[320,24],[620,24],[620,320],[620,620],[320,620],[24,620],[24,320]]) {
    const to=rect(x,y),route=routeFlowEdge(from,to);assertSafe(route,from,to);
    assert.deepEqual(route,routeFlowEdge(from,to));assert.notEqual(route.path,previousPath);previousPath=route.path;
  }
  assert.deepEqual(from,before);
});
test('overlapping rectangles are reported honestly and never yield NaN geometry', () => {
  const from=rect(300,300),to=rect(350,320);
  const partial=routeFlowEdge(from,to);assert.equal(partial.overlapping,true);assertSafe(partial,from,to);
  const contained=routeFlowEdge(rect(320,320,20,20),from);assert.equal(contained.overlapping,true);assert.equal(contained.clear,false);
  assert(!contained.path.includes('NaN'));assert(contained.points.every(point=>Number.isFinite(point.x)&&Number.isFinite(point.y)));
});
test('fractional dimensions and translating the canvas preserve route attachment', () => {
  const from=rect(0.25,0.5,133.5,71.5),to=rect(320.75,230.5,187.5,91.5),obstacle=rect(180.25,130.25,60.5,120.5);
  const route=routeFlowEdge(from,to,[obstacle]);assertSafe(route,from,to,[obstacle]);
  const translate=box=>({...box,x:box.x+107.5,y:box.y+62.25});
  const moved=routeFlowEdge(translate(from),translate(to),[translate(obstacle)]);
  assertSafe(moved,translate(from),translate(to),[translate(obstacle)]);
  assert.deepEqual(moved.points,route.points.map(translate));
});
