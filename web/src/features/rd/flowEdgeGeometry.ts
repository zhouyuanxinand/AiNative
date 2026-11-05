export interface FlowEdgePoint { x: number; y: number }
export interface FlowEdgeRect extends FlowEdgePoint { width: number; height: number }
export type FlowEdgeSide = 'top' | 'right' | 'bottom' | 'left';
export interface FlowEdgeRoute {
  path: string;
  points: FlowEdgePoint[];
  sourcePoint: FlowEdgePoint;
  targetPoint: FlowEdgePoint;
  sourceSide: FlowEdgeSide;
  targetSide: FlowEdgeSide;
  labelPoint: FlowEdgePoint;
  bounds: FlowEdgeRect;
  clear: boolean;
  overlapping: boolean;
}
type Port = { side: FlowEdgeSide; point: FlowEdgePoint; outside: FlowEdgePoint; direction: number };
type Candidate = { points: FlowEdgePoint[]; source: Port; target: Port; score: number };
const SPACE = 18, LANE = 12, TURN_COST = 12;
const vectors = [{ x: 1, y: 0 }, { x: 0, y: 1 }, { x: -1, y: 0 }, { x: 0, y: -1 }];
const equal = (a: FlowEdgePoint, b: FlowEdgePoint) => a.x === b.x && a.y === b.y;
const distance = (a: FlowEdgePoint, b: FlowEdgePoint) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
const sameRect = (a: FlowEdgeRect, b: FlowEdgeRect) => equal(a, b) && a.width === b.width && a.height === b.height;
const contains = (rect: FlowEdgeRect, point: FlowEdgePoint) => point.x > rect.x && point.x < rect.x + rect.width && point.y > rect.y && point.y < rect.y + rect.height;
const overlaps = (a: FlowEdgeRect, b: FlowEdgeRect) => Math.max(a.x, b.x) < Math.min(a.x + a.width, b.x + b.width) && Math.max(a.y, b.y) < Math.min(a.y + a.height, b.y + b.height);

function ports(rect: FlowEdgeRect): Port[] {
  return [
    { side: 'right' as const, point: { x: rect.x + rect.width, y: rect.y + rect.height / 2 }, direction: 0 },
    { side: 'bottom' as const, point: { x: rect.x + rect.width / 2, y: rect.y + rect.height }, direction: 1 },
    { side: 'left' as const, point: { x: rect.x, y: rect.y + rect.height / 2 }, direction: 2 },
    { side: 'top' as const, point: { x: rect.x + rect.width / 2, y: rect.y }, direction: 3 },
  ].map(port => ({ ...port, outside: { x: port.point.x + vectors[port.direction].x * SPACE, y: port.point.y + vectors[port.direction].y * SPACE } }));
}
function blocked(a: FlowEdgePoint, b: FlowEdgePoint, rects: FlowEdgeRect[]): boolean {
  return rects.some(rect => a.x === b.x
    ? a.x > rect.x && a.x < rect.x + rect.width && Math.max(a.y, b.y) > rect.y && Math.min(a.y, b.y) < rect.y + rect.height
    : a.y > rect.y && a.y < rect.y + rect.height && Math.max(a.x, b.x) > rect.x && Math.min(a.x, b.x) < rect.x + rect.width);
}
function direction(a: FlowEdgePoint, b: FlowEdgePoint) { return a.x === b.x ? b.y > a.y ? 1 : 3 : b.x > a.x ? 0 : 2; }
function simplify(points: FlowEdgePoint[]) {
  const result: FlowEdgePoint[] = [];
  for (const point of points) {
    if (result.length && equal(result[result.length - 1], point)) continue;
    while (result.length > 1 && direction(result[result.length - 2], result[result.length - 1]) === direction(result[result.length - 1], point)) result.pop();
    result.push(point);
  }
  return result;
}
function candidate(source: Port, target: Port, middle: FlowEdgePoint[], rects: FlowEdgeRect[]): Candidate | undefined {
  const points = simplify([source.point, ...middle, target.point]);
  if (points.length < 2) return;
  let previous = source.direction, score = 0;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i], current = direction(a, b);
    if ((a.x !== b.x && a.y !== b.y) || current === (previous + 2) % 4 || blocked(a, b, rects)) return;
    score += distance(a, b) + (current === previous ? 0 : TURN_COST); previous = current;
  }
  if (direction(points[0], points[1]) !== source.direction || previous !== (target.direction + 2) % 4) return;
  return { points, source, target, score };
}

/** Tiny priority queue used only when a route requires several obstacle detours. */
class Queue {
  private values: Array<{ state: number; cost: number }> = [];
  push(value: { state: number; cost: number }) {
    let index = this.values.push(value) - 1;
    while (index) { const parent = (index - 1) >> 1; if (this.values[parent].cost <= value.cost) break; this.values[index] = this.values[parent]; index = parent; }
    this.values[index] = value;
  }
  pop() {
    const first = this.values[0], last = this.values.pop();
    if (last && this.values.length) {
      let index = 0;
      while (index * 2 + 1 < this.values.length) {
        let child = index * 2 + 1;
        if (child + 1 < this.values.length && this.values[child + 1].cost < this.values[child].cost) child++;
        if (this.values[child].cost >= last.cost) break;
        this.values[index] = this.values[child]; index = child;
      }
      this.values[index] = last;
    }
    return first;
  }
}

function obstacleRoute(sources: Port[], targets: Port[], rects: FlowEdgeRect[], xs: number[], ys: number[]): Candidate | undefined {
  const width = xs.length, count = width * ys.length;
  const point = (index: number) => ({ x: xs[index % width], y: ys[Math.floor(index / width)] });
  const indexOf = (p: FlowEdgePoint) => ys.indexOf(p.y) * width + xs.indexOf(p.x);
  const valid = Array.from({ length: count }, (_, index) => !rects.some(rect => contains(rect, point(index))));
  const costs = new Float64Array(count * 4).fill(Infinity), previous = new Int32Array(count * 4).fill(-1), origins = new Int8Array(count * 4).fill(-1);
  const queue = new Queue();
  sources.forEach((source, index) => {
    const position = indexOf(source.outside), state = position * 4 + source.direction;
    if (valid[position]) { costs[state] = SPACE; origins[state] = index; queue.push({ state, cost: SPACE }); }
  });
  const endings = new Map<number, Port[]>();
  for (const target of targets) { const index = indexOf(target.outside); endings.set(index, [...endings.get(index) ?? [], target]); }
  let best: Candidate | undefined, next: ReturnType<Queue['pop']>;
  while ((next = queue.pop())) {
    if (next.cost !== costs[next.state]) continue;
    if (best && next.cost >= best.score) break;
    const index = Math.floor(next.state / 4), incoming = next.state % 4, here = point(index), origin = sources[origins[next.state]];
    for (const target of endings.get(index) ?? []) {
      if (incoming === target.direction) continue;
      const middle: FlowEdgePoint[] = [];
      for (let cursor = next.state; cursor >= 0; cursor = previous[cursor]) middle.push(point(Math.floor(cursor / 4)));
      const route = candidate(origin, target, middle.reverse(), rects);
      if (route && (!best || route.score < best.score)) best = route;
    }
    for (let dir = 0; dir < 4; dir++) {
      if (dir === (incoming + 2) % 4) continue;
      const x = index % width + vectors[dir].x, y = Math.floor(index / width) + vectors[dir].y;
      if (x < 0 || x >= width || y < 0 || y >= ys.length) continue;
      const neighbor = y * width + x, state = neighbor * 4 + dir;
      if (!valid[neighbor] || blocked(here, point(neighbor), rects)) continue;
      const cost = next.cost + distance(here, point(neighbor)) + (dir === incoming ? 0 : TURN_COST);
      if (cost >= costs[state]) continue;
      costs[state] = cost; previous[state] = next.state; origins[state] = origins[next.state]; queue.push({ state, cost });
    }
  }
  return best;
}
function result(route: Candidate, clear: boolean, overlapping: boolean): FlowEdgeRoute {
  const { points, source, target } = route;
  let remaining = points.slice(1).reduce((length, point, i) => length + distance(points[i], point), 0) / 2;
  let labelPoint = points[0];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i], length = distance(a, b);
    if (remaining <= length) { labelPoint = { x: a.x + (b.x - a.x) * remaining / length, y: a.y + (b.y - a.y) * remaining / length }; break; }
    remaining -= length;
  }
  const x = Math.min(...points.map(p => p.x)), y = Math.min(...points.map(p => p.y));
  return { path: points.map((point, i) => `${i ? 'L' : 'M'}${point.x},${point.y}`).join(' '), points, sourcePoint: source.point, targetPoint: target.point, sourceSide: source.side, targetSide: target.side, labelPoint, bounds: { x, y, width: Math.max(...points.map(p => p.x)) - x, height: Math.max(...points.map(p => p.y)) - y }, clear, overlapping };
}

/** Routes in unscaled canvas coordinates. Rectangles must have positive dimensions.
 * The final segment always points into the target border; use an SVG marker with
 * orient="auto" and its tip at refX. Pass current drag-preview rectangles, not
 * saved positions. Overlapping/contained nodes may have no visible clear route.
 */
export function routeFlowEdge(sourceRect: FlowEdgeRect, targetRect: FlowEdgeRect, allObstacleRects: FlowEdgeRect[] = []): FlowEdgeRoute {
  const others = allObstacleRects.filter(rect => !sameRect(rect, sourceRect) && !sameRect(rect, targetRect));
  const rects = [sourceRect, targetRect, ...others], overlapping = overlaps(sourceRect, targetRect);
  const sources = ports(sourceRect).filter(port => !blocked(port.point, port.outside, [targetRect, ...others]));
  const targets = ports(targetRect).filter(port => !blocked(port.point, port.outside, [sourceRect, ...others]));
  let best: Candidate | undefined;
  const tryPath = (s: Port, t: Port, middle: FlowEdgePoint[]) => {
    const route = candidate(s, t, middle, rects);
    if (route && (!best || route.score < best.score)) best = route;
  };
  // A free straight gap needs no outward stubs, even when narrower than SPACE.
  for (const s of ports(sourceRect)) for (const t of ports(targetRect)) tryPath(s, t, []);
  if (best) return result(best, true, overlapping);
  // The common one/two-turn paths avoid grid-search work during pointer moves.
  for (const s of sources) for (const t of targets) {
    const a = s.outside, b = t.outside;
    tryPath(s, t, [a, { x: b.x, y: a.y }, b]);
    tryPath(s, t, [a, { x: a.x, y: b.y }, b]);
  }
  if (best) return result(best, true, overlapping);
  const xs = [...new Set([...rects.flatMap(rect => [rect.x - LANE, rect.x + rect.width + LANE]), ...sources.map(port => port.outside.x), ...targets.map(port => port.outside.x)])].sort((a, b) => a - b);
  const ys = [...new Set([...rects.flatMap(rect => [rect.y - LANE, rect.y + rect.height + LANE]), ...sources.map(port => port.outside.y), ...targets.map(port => port.outside.y)])].sort((a, b) => a - b);
  for (const s of sources) for (const t of targets) {
    const a = s.outside, b = t.outside;
    for (const x of xs) tryPath(s, t, [a, { x, y: a.y }, { x, y: b.y }, b]);
    for (const y of ys) tryPath(s, t, [a, { x: a.x, y }, { x: b.x, y }, b]);
  }
  if (!best && sources.length && targets.length) best = obstacleRoute(sources, targets, rects, xs, ys);
  if (best) return result(best, true, overlapping);
  // A fully covered port cannot be made visible by edge routing alone.
  const source = ports(sourceRect)[0], target = ports(targetRect)[2];
  const points = simplify([source.point, source.outside, { x: source.outside.x, y: target.outside.y }, target.outside, target.point]);
  return result({ source, target, points, score: Infinity }, false, overlapping);
}
