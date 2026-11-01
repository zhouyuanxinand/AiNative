import type { PlanNode } from './types';

export const NODE_WIDTH = 228;
export const NODE_HEIGHT = 88;
export interface PositionedNode { node: PlanNode; x: number; y: number }

/** Derive layout from the dependency graph, never from display order. */
export function layoutWorkflow(nodes: PlanNode[]) {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const errors: string[] = [];
  if (byId.size !== nodes.length) errors.push('节点标识重复，请核对计划。');
  const levels = new Map<string, number>();
  const visiting = new Set<string>();
  function visit(id: string): number {
    if (levels.has(id)) return levels.get(id)!;
    if (visiting.has(id)) { errors.push('节点依赖形成环路，请调整前置依赖。'); return 0; }
    visiting.add(id);
    const node = byId.get(id)!;
    let level = 0;
    for (const dependency of node.depends_on) {
      if (!byId.has(dependency)) { errors.push('计划包含缺失的前置节点，请核对依赖。'); continue; }
      level = Math.max(level, visit(dependency) + 1);
    }
    visiting.delete(id); levels.set(id, level); return level;
  }
  nodes.forEach(node => visit(node.id));
  const ordered = [...nodes].sort((a, b) => levels.get(a.id)! - levels.get(b.id)!);
  const chain = !errors.length && ordered.every((node, index) => index === 0 ? !node.depends_on.length : node.depends_on.length === 1 && node.depends_on[0] === ordered[index - 1].id);
  const rows = new Map<number, number>();
  const positions: PositionedNode[] = ordered.map((node, index) => {
    const level = levels.get(node.id)!;
    const row = rows.get(level) ?? 0; rows.set(level, row + 1);
    const chainRow = Math.floor(index / 3);
    return { node, x: 38 + (chain ? (chainRow % 2 ? 2 - index % 3 : index % 3) : level) * 280, y: 40 + (chain ? chainRow : row) * 176 };
  });
  return { positions, errors: [...new Set(errors)], width: Math.max(320, ...positions.map(p => p.x + NODE_WIDTH + 38)), height: Math.max(260, ...positions.map(p => p.y + NODE_HEIGHT + 40)) };
}
