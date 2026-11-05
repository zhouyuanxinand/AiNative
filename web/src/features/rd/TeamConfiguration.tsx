import { PlatformButton } from '../../components/ui/PlatformButton';
import { useId, useState } from 'react';
import { FlowGraphEditor } from './FlowGraphEditor';
import { applyOperations } from './flowDraftReducer';
import type { FlowGraph, ResourceSummary } from './types';

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
// Raw JSON is editable; incomplete structures must remain repairable in that editor.
// These checks protect visualization only. Publication and executability stay server-owned.
export function teamConfigurationIssue(configuration: Record<string, unknown>): string {
  if (configuration.members !== undefined && (!Array.isArray(configuration.members) || configuration.members.some(member => !record(member) || typeof member.resource_id !== 'string' || !['string', 'number'].includes(typeof member.resource_version)))) return 'members 应为包含 resource_id 和 resource_version 的成员数组。';
  for (const key of ['inputs', 'outputs']) if (configuration[key] !== undefined && !Array.isArray(configuration[key])) return `${key} 应为数组。`;
  if (configuration.execution_graph !== undefined) {
    const graph = configuration.execution_graph;
    if (!record(graph) || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) return 'execution_graph 应包含 nodes 和 edges 数组。';
    for (const node of graph.nodes) {
      if (!record(node) || typeof node.id !== 'string') return '每个节点应包含字符串 id。';
      for (const key of ['title', 'role', 'action_id', 'resource_id']) if (node[key] !== undefined && typeof node[key] !== 'string') return `节点 ${node.id} 的 ${key} 应为文字。`;
      for (const key of ['action_version', 'resource_version']) if (node[key] !== undefined && !['string', 'number'].includes(typeof node[key])) return `节点 ${node.id} 的 ${key} 应为文字或数字版本号。`;
      if (node.deliverables !== undefined && (!Array.isArray(node.deliverables) || node.deliverables.some(item => typeof item !== 'string'))) return `节点 ${node.id} 的 deliverables 应为文字数组。`;
      if (node.position !== undefined && (!record(node.position) || !Number.isFinite(node.position.x) || !Number.isFinite(node.position.y))) return `节点 ${node.id} 的 position 应包含数字 x 和 y。`;
    }
    if (graph.edges.some(edge => !record(edge) || ['id', 'source', 'target'].some(key => typeof edge[key] !== 'string'))) return '每条连线应包含字符串 id、source 和 target。';
  }
  return '';
}

export function TeamConfiguration({ configuration, onChange, disabled = false, resources = [] }: { configuration: Record<string, unknown>; onChange?: (value: Record<string, unknown>) => void; disabled?: boolean; resources?: ResourceSummary[] }) {
  const fieldId = useId();
  const [resourceId, setResourceId] = useState(''), [version, setVersion] = useState('1');
  const issue = teamConfigurationIssue(configuration);
  if (issue) return <p className="rd-notice" role="status">团队配置暂时无法显示：{issue} 请在高级配置中修正，当前填写已保留。</p>;
  const members = (configuration.members ?? []) as Array<{ resource_id: string; resource_version: number | string }>;
  const graph = (configuration.execution_graph ?? { nodes: [], edges: [] }) as FlowGraph;
  const set = (patch: Record<string, unknown>) => onChange?.({ ...configuration, ...patch });
  const editable = !!onChange;
  return <section className="rd-designer-review" aria-label="专家团固定组成与内部执行图"><h4>专家团固定组成</h4><p className="rd-muted">专家团是共享 Workspace 资源；固定成员、输入输出与内部依赖图共同发布。项目采用后只读，执行能力仍由已注册执行器核验。</p><ul>{members.map((member, index) => <li key={`${member.resource_id}@${member.resource_version}-${index}`}><code>{member.resource_id} · V{member.resource_version}</code>{editable && <PlatformButton type="button" className="rd-link-button" disabled={disabled} onClick={() => set({ members: members.filter((_, i) => i !== index) })}>移除成员</PlatformButton>}</li>)}</ul>{!members.length && <p className="rd-empty-inline">尚无固定成员。</p>}{editable && <div className="rd-graph-add"><label>成员资源标识<input aria-label="成员资源标识" value={resourceId} onChange={event => setResourceId(event.target.value)} disabled={disabled} /></label><label>固定版本<input aria-label="成员固定版本" type="number" min="1" value={version} onChange={event => setVersion(event.target.value)} disabled={disabled} /></label><PlatformButton type="button" className="rd-button" disabled={disabled || !resourceId.trim() || Number(version) < 1 || members.some(item => item.resource_id === resourceId.trim() && String(item.resource_version) === version)} onClick={() => { set({ members: [...members, { resource_id: resourceId.trim(), resource_version: Number(version) }] }); setResourceId(''); }}>添加固定成员</PlatformButton></div>}
    <div className="rd-derivation-grid">{(['inputs','outputs'] as const).map(key => <div className="rd-field" key={key}><label htmlFor={`${fieldId}-${key}`}>{key === 'inputs' ? '输入合同' : '输出合同'}（每行一项）</label><textarea id={`${fieldId}-${key}`} className="resize-none" rows={3} disabled={!editable || disabled} value={((configuration[key] ?? []) as unknown[]).map(item => typeof item === 'string' ? item : JSON.stringify(item)).join('\n')} onChange={event => set({ [key]: event.target.value.split('\n').filter(Boolean) })} /></div>)}</div>
    <FlowGraphEditor allowRoutes={false} graph={graph} readOnly={!editable} disabled={disabled} choices={members.map(member => ({ id: member.resource_id, version: member.resource_version, title: resources.find(item => item.id === member.resource_id)?.name ?? member.resource_id, kind: 'resource' as const }))} onChange={operations => set({ execution_graph: applyOperations(graph, operations) })} />
  </section>;
}
