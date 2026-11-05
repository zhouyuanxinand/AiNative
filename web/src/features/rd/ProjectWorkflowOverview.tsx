import { PlatformButton } from '../../components/ui/PlatformButton';
import { fixedBusinessTemplate } from './businessWorkflowFacts';
import { FlowGraphEditor } from './FlowGraphEditor';
import { statusTitle } from './presentation';
import type { ResearchCase } from './types';

export const projectWorkflowStatusTitle = (status?: string) => status === 'stale' ? '当前输入已变化' : status === 'pending_decision' ? '待业务确认' : statusTitle(status);

export function ProjectWorkflowOverview({ researchCase, onOpenWorkpackage }: { researchCase: ResearchCase; onOpenWorkpackage: (id: string) => void }) {
  const template = researchCase.workflow_templates?.project;
  if (!template) return null;
  const fixed = fixedBusinessTemplate(template);
  const flowState = researchCase.project_workflow_status;
  const nodeState = (id: string) => projectWorkflowStatusTitle(template.node_states?.[id]);
  const execution = (id: string) => {
    const reference = template.node_execution_refs?.[id];
    if (!reference) return <p className="rd-muted">尚无当前输入对应的执行记录。</p>;
    const workpackage = researchCase.workpackages.find(item => item.id === reference.workpackage_id);
    return <div><p className="rd-muted">{reference.step_instance_ids.length} 个执行步骤 · 运行 {reference.run_id}</p>{workpackage ? <PlatformButton type="button" className="rd-link-button" onClick={() => onOpenWorkpackage(workpackage.id)}>查看执行工作包 · {workpackage.title} →</PlatformButton> : <p className="rd-warning">执行工作包暂不可读取，请刷新项目后核对。</p>}</div>;
  };
  return <section className="rd-section" aria-label="项目固定流程">
    <div className="rd-section-head"><div><h3>{template.title}</h3><p>创建项目时固定的流程 · V{fixed.version}。双击节点或使用查看图标，检查当前办理状态与执行记录。</p></div><span className={`rd-badge ${flowState?.status ?? 'pending'}`}>{projectWorkflowStatusTitle(flowState?.status)}</span></div>
    {(template.stale || flowState?.status === 'stale') && <p className="rd-warning" role="status">输入已变化，原办理与执行记录继续保留；请按当前输入重新核对依据并固定任务书输入。</p>}
    {flowState?.reason && <p className="rd-warning" role="status">{flowState.reason}</p>}
    <FlowGraphEditor business businessCategory="project" readOnly allowRoutes={false} graph={template.graph} choices={template.graph.nodes.flatMap(node => node.action_resource ? [{ id: node.action_resource.resource_id, version: node.action_resource.resource_version, title: node.title || '已固定办理动作', kind: 'resource' as const }] : [])} onChange={() => {}} renderNodeDetails={node => <section aria-label="节点办理状态"><p><strong>当前状态：{nodeState(node.id)}</strong></p>{node.gate ? <p className="rd-muted">状态来自本项目当前有效的业务确认记录。</p> : execution(node.id)}</section>} />
    <details className="rd-disclosure" open><summary>节点办理状态</summary><ol className="rd-dependency-list">{template.graph.nodes.map(node => <li key={node.id} data-business-node-id={node.id}><div><strong>{node.title || node.id}</strong><span className={`rd-badge ${template.node_states?.[node.id] ?? 'pending'}`}>{nodeState(node.id)}</span></div>{template.node_execution_refs?.[node.id] && execution(node.id)}</li>)}</ol></details>
    <details className="rd-disclosure"><summary>固定流程版本与摘要</summary><dl><dt>流程版本</dt><dd>{fixed.id} · V{fixed.version}</dd><dt>固定摘要</dt><dd className="rd-prewrap" style={{ overflowWrap: 'anywhere' }}>{fixed.digest}</dd></dl></details>
  </section>;
}
