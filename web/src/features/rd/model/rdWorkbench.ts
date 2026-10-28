import type { RdDetail, RdRole } from '../api/rd';
import { projectHref } from './projectLinks.ts';

const labels: Record<RdRole, string> = { owner: '项目负责人', engineer: '工程师', reviewer: '独立评审', viewer: '只读成员' };
export function projectRole(detail: RdDetail): RdRole { return detail.project.role; }
export function roleLabel(role: RdRole) { return labels[role] || '只读成员'; }

/** Project phase is an explicit business projection, never a roll-up of task statuses. */
export function projectJourney(detail: RdDetail) {
  if (detail.journey) return detail.journey;
  const adoptions = detail.development_adoptions || [];
  const adoption = adoptions[adoptions.length - 1];
  const route = adoption?.route === 'modified' ? 'modification' : adoption?.route === 'new' || adoption?.route === 'modification' || adoption?.route === 'direct' ? adoption.route : 'undecided';
  return { route, route_label: route === 'new' ? '新研' : route === 'modification' ? '改型' : route === 'direct' ? '直接选用' : '路线待决定', stage: adoption ? 'route_recorded' : 'selection', stage_label: adoption ? '已有路线登记，阶段待核实' : detail.project.current_baseline_id ? '选型待办理' : '需求基线待确认', blockers: [] as string[] };
}
export interface WorkItem { id: string; title: string; description: string; href: string; projectId: string; projectName: string; kind: string; priority: 'high' | 'normal' }

/** Responsibility selects attention; the existing permission and assignment facts select commands. */
export function workItems(projects: RdDetail[], userId: string): WorkItem[] {
  const items: WorkItem[] = [];
  for (const detail of projects) {
    const permission = detail.project.role;
    const add = (kind: string, key: string, title: string, description: string, href: string, priority: WorkItem['priority'] = 'normal') => items.push({ id: `${detail.project.id}:${kind}:${key}`, title, description, href, projectId: detail.project.id, projectName: detail.project.name, kind, priority });
    const taskHref = (id: string, view?: string) => { const href = projectHref(detail, 'tasks', `task-${id}`); return view && detail.tasks.some(t => t.id === id && t.kind === 'taskbook') ? `${href}?view=${view}` : href; };
    const impacts = (detail.change_impacts || []).filter(impact => ['pending', 'open', 'unresolved'].includes(impact.status));
    if (permission === 'owner') {
      for (const impact of impacts) add('change_impact', impact.id, '复核上游变更影响', '保留原批准记录，明确新输入对任务与下游交接的影响。', taskHref(impact.task_id, 'handoff'), 'high');
      const releases = detail.taskbook_releases || [];
      for (const release of detail.project_plan?.pending_releases || []) {
        const task = detail.tasks.find(t => t.id === release.task_id);
        if (task) add('publish_plan', release.release_id, `发布已批准计划：${task.title}`, '工程批准已形成固定发布包；由负责人另行发布计划并发起交接。', taskHref(task.id, 'handoff'), 'high');
      }
      for (const task of detail.tasks.filter(t => t.kind === 'taskbook' && t.status === 'done')) {
        const currentId = detail.taskbook_work_units?.find(w => w.task_id === task.id)?.release_id;
        const release = currentId ? releases.find(r => r.id === currentId) : releases.filter(r => r.task_id === task.id).sort((a, b) => b.version - a.version)[0];
        if (detail.project_plan?.pending_releases === undefined && release && !impacts.some(i => i.task_id === task.id) && !detail.project_plan?.versions.some(v => v.release_id === release.id)) add('publish_plan', release.id, `发布已批准计划：${task.title}`, '工程批准已形成固定发布包；由负责人另行发布计划并发起交接。', taskHref(task.id, 'handoff'), 'high');
      }
      if (detail.requirements.length && !detail.project.current_baseline_id) add('baseline', 'current', '确认需求基线', '核对需求、来源与验收依据，固定后续选型输入。', projectHref(detail, 'requirements'));
      const journey = projectJourney(detail);
      if (detail.project.current_baseline_id && (journey.route === 'undecided' || ['selection_pending', 'needs_revalidation'].includes(journey.stage))) add('selection', 'route', journey.route === 'undecided' ? '办理产品选型与路线' : '核实并复核选型路线', '核对当前需求与选型依据；尚未核实的适用条件补齐后，由负责人记录当前采用决定。', projectHref(detail, 'flow', 'route-decision'), journey.stage === 'needs_revalidation' ? 'high' : 'normal');
      if (projectJourney(detail).route === 'direct' && projectJourney(detail).stage !== 'delivered') add('delivery', 'direct', '核对直接选用交接', '确认工程适用性、供应状态和接收记录；按实际情况记录交接结果。', projectHref(detail, 'flow', 'direct-delivery'));
      for (const requirement of detail.requirements.filter(r => r.required && r.clarification === 'open')) add('clarification', requirement.id, `澄清需求：${requirement.title}`, '必需需求尚未完成澄清，请补齐验收和来源依据。', projectHref(detail, 'requirements', `requirement-${requirement.id}`));
    }
    const canExecute = permission === 'owner' || permission === 'engineer';
    const pendingHandoffs = (detail.handoffs || []).filter(h => h.status === 'pending' && h.assignee_id === userId && detail.tasks.some(t => t.id === h.task_id && t.assignee_id === userId && t.required_handoff_id === h.id));
    if (canExecute) {
      for (const handoff of pendingHandoffs) add('accept_handoff', handoff.id, `接收交接：${detail.tasks.find(t => t.id === handoff.task_id)?.title || '下游任务'}`, '查看固定输入版本与责任安排，明确接收后才能开始执行。', projectHref(detail, 'tasks', `task-${handoff.task_id}`), 'high');
      for (const task of detail.tasks.filter(t => t.assignee_id === userId && ['todo', 'in_progress', 'changes_requested', 'needs_revalidation'].includes(t.status) && !pendingHandoffs.some(h => h.task_id === t.id))) {
        const blocked = impacts.some(i => i.task_id === task.id || i.downstream_task_ids?.includes(task.id));
        add('execute_task', task.id, `${blocked || task.status === 'needs_revalidation' ? '核对任务输入' : '办理任务'}：${task.title}`, blocked ? '上游变更尚未处置，请核对影响并联系负责人。' : task.status === 'changes_requested' ? '审签已退回，请按固定意见修订后重新送审。' : task.due_date ? `计划日期 ${task.due_date}；进入任务核对当前要求与成果。` : '进入任务核对固定输入、当前成果与下一步责任。', taskHref(task.id), blocked || task.status === 'changes_requested' ? 'high' : 'normal');
      }
    }
    if (permission !== 'viewer') for (const review of detail.reviews.filter(r => r.status === 'pending' && r.reviewer_id === userId && r.submitter_id !== userId)) add('review', review.id, `工程审签：${detail.tasks.find(t => t.id === review.task_id)?.title || '固定成果'}`, '核对本轮固定正文、输入与检查记录，独立作出工程决定。', projectHref(detail, 'artifacts', `review-${review.id}`), 'high');

  }
  return items.sort((a, b) => Number(b.priority === 'high') - Number(a.priority === 'high'));
}
