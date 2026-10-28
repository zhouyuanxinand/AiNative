interface TaskInputs { id: string; kind?: string; baseline_id: string; status: string; source_task_id?: string }
interface TaskImpact { task_id: string; status: string; downstream_task_ids?: string[] }

/** Native applicability follows explicit impact review, while generic tasks keep the baseline rule. */
export function taskInputApplicability(task: TaskInputs, currentBaselineId: string | null, impacts: TaskImpact[] = []) {
  const native = task.kind === 'taskbook' || task.kind === 'plan_item';
  const pending = native && impacts.some(impact => impact.status === 'pending' && (impact.task_id === task.id || impact.downstream_task_ids?.includes(task.id)));
  const current = task.status !== 'needs_revalidation' && !pending && (native || task.baseline_id === currentBaselineId);
  return { native, current, reviewTaskId: native ? task.kind === 'plan_item' ? task.source_task_id : task.id : undefined };
}
