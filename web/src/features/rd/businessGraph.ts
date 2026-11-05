import type { BusinessWorkflowTemplate, FlowGraph, FlowNode, FlowOperation } from './types';
type BusinessWorkflowCategory = BusinessWorkflowTemplate['category'];
/** Existing stage flows end at approval; project flows execute through the taskbook terminal. */
export function businessApprovalGate(category: BusinessWorkflowCategory) { return category === 'project' ? 'taskbook' : category === 'research' ? 'taskbook_scope' : 'selection_decision'; }
/** Reachability follows dependencies, never the node array or canvas coordinates. */
export function businessExecutableNodes(graph: FlowGraph, category: BusinessWorkflowCategory): Set<string> {
  const result = new Set<string>(), visiting = new Set<string>();
  function visit(id: string) { if (visiting.has(id)) return; visiting.add(id); for (const edge of graph.edges.filter(item => item.target === id)) { result.add(edge.source); visit(edge.source); } }
  const gate = businessApprovalGate(category);
  if (!graph.nodes.some(node => node.id === gate)) return result;
  visit(gate);
  if (category === 'project') result.add(gate); else result.delete(gate);
  return result;
}
/** Insert an action immediately before the approval or terminal step, retaining prior dependencies. */
export function insertBusinessAction(graph: FlowGraph, category: BusinessWorkflowCategory, node: FlowNode): FlowOperation[] {
  const gate = businessApprovalGate(category);
  if (!graph.nodes.some(item => item.id === gate)) return [];
  const incoming = graph.edges.filter(edge => edge.target === gate);
  return [{ op: 'add_node', node }, ...incoming.flatMap(edge => [{ op: 'remove_edge', edge_id: edge.id } as FlowOperation, { op: 'add_edge', edge: { ...edge, target: node.id } } as FlowOperation]), { op: 'add_edge', edge: { id: `edge-${node.id}-${gate}`, source: node.id, target: gate } }];
}
