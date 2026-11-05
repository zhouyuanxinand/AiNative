import type { FlowGraph, FlowOperation } from './types';
export interface DraftEdit { graph: FlowGraph; operations: FlowOperation[] }
export interface DraftState extends DraftEdit { past: DraftEdit[]; future: DraftEdit[] }
export type DraftAction = { type: 'reset'; graph: FlowGraph } | { type: 'apply'; operations: FlowOperation[] } | { type: 'undo' } | { type: 'redo' };
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
export function applyOperations(graph: FlowGraph, operations: FlowOperation[]): FlowGraph {
  const next = clone(graph);
  for (const operation of operations) {
    const node = next.nodes.find(item => item.id === operation.node_id);
    if (operation.op === 'add_node' && operation.node) next.nodes.push(clone(operation.node));
    if (operation.op === 'remove_node') { next.nodes = next.nodes.filter(item => item.id !== operation.node_id); next.edges = next.edges.filter(edge => edge.source !== operation.node_id && edge.target !== operation.node_id); }
    if (operation.op === 'copy_node' && node) next.nodes.push({ ...clone(node), id: operation.node?.id ?? `${node.id}-copy`, position: { x: (node.position?.x ?? 30) + 40, y: (node.position?.y ?? 30) + 100 } });
    if (operation.op === 'add_edge' && operation.edge) next.edges.push(clone(operation.edge));
    if (operation.op === 'remove_edge') next.edges = next.edges.filter(edge => edge.id !== operation.edge_id);
    if (operation.op === 'set_node' && node) {
      const properties = clone(operation.properties ?? {});
      // These optional business references use null as an explicit clear command.
      // Remove them from the final graph; omission in a patch means keep the value.
      for (const key of ['action_resource', 'workpackage_definition_id'] as const) {
        if (properties[key] === null) { delete node[key]; delete properties[key]; }
      }
      Object.assign(node, properties);
    }
    if (operation.op === 'move_node' && node) node.position = clone(operation.position!);
  }
  return next;
}
/** Layout is a single undoable edit; it never changes dependencies or business fields. */
export function autoLayoutOperations(graph: FlowGraph): FlowOperation[] {
  const ids = new Set(graph.nodes.map(node => node.id));
  const incoming = new Map(graph.nodes.map(node => [node.id, 0]));
  const outgoing = new Map(graph.nodes.map(node => [node.id, [] as string[]]));
  for (const edge of graph.edges) if (ids.has(edge.source) && ids.has(edge.target)) {
    incoming.set(edge.target, incoming.get(edge.target)! + 1);
    outgoing.get(edge.source)!.push(edge.target);
  }
  const levels = new Map<string, number>();
  const queue = graph.nodes.filter(node => incoming.get(node.id) === 0).map(node => node.id);
  for (const id of queue) levels.set(id, 0);
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index];
    for (const target of outgoing.get(id) ?? []) {
      levels.set(target, Math.max(levels.get(target) ?? 0, levels.get(id)! + 1));
      incoming.set(target, incoming.get(target)! - 1);
      if (incoming.get(target) === 0) queue.push(target);
    }
  }
  // Incomplete/cyclic drafts can still be arranged and then corrected by the user.
  const ordered = new Set(queue);
  const finalLevel = levels.size ? Math.max(...levels.values()) + 1 : 0;
  const rows = new Map<number, number>();
  return graph.nodes.flatMap(node => {
    const level = ordered.has(node.id) ? levels.get(node.id)! : finalLevel;
    const row = rows.get(level) ?? 0;
    rows.set(level, row + 1);
    const position = { x: 24 + level * 270, y: 24 + row * 160 };
    return node.position?.x === position.x && node.position?.y === position.y ? [] : [{ op: 'move_node', node_id: node.id, position } as FlowOperation];
  });
}
export function draftReducer(state: DraftState, action: DraftAction): DraftState {
  if (action.type === 'reset') return { graph: clone(action.graph), operations: [], past: [], future: [] };
  if (action.type === 'undo') { const previous = state.past[state.past.length - 1]; return previous ? { ...previous, past: state.past.slice(0, -1), future: [{ graph: state.graph, operations: state.operations }, ...state.future] } : state; }
  if (action.type === 'redo') { const next = state.future[0]; return next ? { ...next, past: [...state.past, { graph: state.graph, operations: state.operations }], future: state.future.slice(1) } : state; }
  return { graph: applyOperations(state.graph, action.operations), operations: [...state.operations, ...action.operations], past: [...state.past, { graph: state.graph, operations: state.operations }], future: [] };
}
/** Assistant changes to confirmed fields require explicit conflict resolution at the service. */
export function confirmedConflicts(operations: FlowOperation[], confirmed: Array<{ node_id: string; field: string }>): string[] {
  return operations.flatMap(operation => confirmed.filter(item => item.node_id === operation.node_id && (operation.op === 'remove_node' || operation.op === 'copy_node' || operation.op === 'move_node' && item.field === 'position' || operation.op === 'set_node' && Object.prototype.hasOwnProperty.call(operation.properties, item.field))).map(item => `${item.node_id}.${item.field}`));
}


