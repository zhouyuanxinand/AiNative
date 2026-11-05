import { fixedBusinessTemplate } from './businessWorkflowFacts';
import { caseJourney } from './caseJourney';
import { packageUsesCurrentInput } from './caseOutcomeModel';
import { operationTimestamp } from './operationsProjection';
import { isCurrentSource, statusTitle } from './presentation';
import { scenarioManifest } from './scenarioManifest';
import type { Project, ResearchCase, Workpackage } from './types';

interface CardProgress { completed: number | null; total: number; percent: number | null; label: string }
function progress(states: Array<string | undefined>, unit: string): CardProgress {
  const total = states.length, completed = states.filter(state => state === 'completed').length;
  const missing = states.filter(state => !state).length;
  return { completed: total ? completed : null, total, percent: total && !missing ? completed * 100 / total : null,
    label: !total ? `${unit}进度未记录` : missing === total ? `${unit}进度未记录（${total} 个${unit}）`
      : `已完成 ${completed} / ${total} 个${unit}${missing ? ` · ${missing} 个未记录` : ''}` };
}
function validDay(value?: string | null): string | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const time = Date.parse(value + 'T00:00:00Z');
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value ? value : null;
}
function deadline(packages: Workpackage[]): string | null {
  const dates = packages.filter(item => !['completed', 'cancelled'].includes(item.status)).flatMap(item => {
    const end = validDay(item.planned_end), start = validDay(item.planned_start);
    return end && (!item.planned_start || start && start <= end) ? [end] : [];
  });
  return dates.sort()[0] ?? null;
}
function reason(value: unknown): string {
  if (typeof value === 'string') return value.trim();
  if (!value || typeof value !== 'object') return '';
  const record = value as Record<string, unknown>;
  return typeof record.message === 'string' ? record.message.trim() : typeof record.reason === 'string' ? record.reason.trim() : '';
}

/** Read-only card facts; fixed-flow execution is selected by the server's current run references. */
export function projectCaseCardModel(project: Project, researchCase: ResearchCase) {
  const template = researchCase.workflow_templates?.project, flow = researchCase.project_workflow_status;
  const fixed = template && fixedBusinessTemplate(template);
  const completed = template ? flow?.status === 'completed' : researchCase.status === 'completed';
  const stale = !!template && (template.stale || flow?.status === 'stale');
  const references = template ? [...Object.values(template.node_execution_refs ?? {}), ...(flow?.execution_ref ? [flow.execution_ref] : [])] : [];
  const currentRuns = researchCase.workpackages.filter(item => item.status !== 'cancelled' && packageUsesCurrentInput(item, researchCase)
    && (!template || references.some(ref => ref.workpackage_id === item.id && ref.run_id === item.run_id)));
  const activeRuns = currentRuns.filter(item => item.stage === researchCase.stage);
  const drafts = researchCase.workpackages.filter(item => item.status === 'draft' && item.stage === researchCase.stage);
  const blocked = activeRuns.filter(item => ['blocked', 'failed'].includes(item.status));
  const status = template ? flow?.status ?? (stale ? 'stale' : 'pending') : completed ? 'completed'
    : activeRuns.some(item => ['running', 'submitted'].includes(item.status)) ? 'running'
      : activeRuns.some(item => item.status === 'failed') ? 'failed' : blocked.length ? 'blocked' : 'pending';
  const attention = completed ? null : flow?.reason?.trim() || (stale ? '当前输入已变化，请重新核对并固定任务书输入。' : '')
    || (['blocked', 'failed'].includes(status) || !template && blocked.length ? blocked.flatMap(item => item.blocked_reasons.map(reason)).filter(Boolean).join('；') || '当前执行需处理，请进入办理页核对阻塞与证据。' : '') || null;
  const manifest = scenarioManifest(researchCase.scenario_id);
  const journey = caseJourney(template ? { ...researchCase, workpackages: [...currentRuns, ...drafts] } : researchCase, manifest);
  const active = journey.steps.find(item => item.id === journey.active);
  const sources = researchCase.sources.filter(item => isCurrentSource(item, researchCase.source_selection));
  const sourceIds = new Set(sources.map(item => item.id));
  const requirements = researchCase.requirements.filter(item => item.source_ids.length > 0 && item.source_ids.every(id => sourceIds.has(id)));
  let completion: CardProgress;
  if (template) {
    const ids = [...new Set(template.graph.nodes.map(node => node.id))];
    completion = stale ? { completed: null, total: ids.length, percent: null, label: '当前输入变化，节点进度待重新核对' }
      : progress(ids.map(id => template.node_states?.[id]), '节点');
  } else completion = progress(activeRuns.flatMap(item => item.nodes.map(node => node.status)), '执行步骤');
  const deliveries = (researchCase.deliveries ?? []).filter(item => item.input_revision === researchCase.input_revision);
  const latestDelivery = deliveries.reduce<(typeof deliveries)[number] | undefined>((latest, item) => {
    if (!latest) return item;
    const previous = operationTimestamp(latest.created_at), next = operationTimestamp(item.created_at);
    return previous && next && previous > next ? latest : item;
  }, undefined);
  return {
    completed, status, statusLabel: stale ? '当前输入已变化' : status === 'pending' ? '待办理' : statusTitle(status),
    templateTitle: template?.title || manifest?.title || '业务流程', templateVersion: fixed?.version || null,
    stepTitle: completed ? '流程已完成' : active?.title ?? '待核对当前流程',
    nextLabel: completed ? '查看当前成果与依据' : journey.next?.label ?? '核对当前记录并继续办理', attention,
    progress: completion, sourceCount: sources.length, requirementCount: requirements.length,
    owner: project.owner_id?.trim() || '未设置', deadline: deadline([...activeRuns, ...drafts]),
    artifactCount: new Set(currentRuns.flatMap(item => item.artifacts.map(artifact => artifact.id))).size,
    delivery: latestDelivery ? latestDelivery.outcome === 'accepted' ? '已登记接收' : '需修订' : '未登记',
    actionLabel: completed ? '查看成果' : '继续办理',
  };
}
