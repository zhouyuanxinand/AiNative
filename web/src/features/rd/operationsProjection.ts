import type { Project, ResearchCase, Workpackage } from './types';

/** Read-only projection of the current identity's already-authorized projects. */
export type OperationsFilters = { query: string; status: string; stage: string; owner: string };
export const EMPTY_OPERATIONS_FILTERS: OperationsFilters = { query: '', status: 'all', stage: 'all', owner: 'all' };
export interface OperationsPackageRow {
  key: string; project: Project; researchCase: ResearchCase; workpackage: Workpackage;
  overdue: boolean; dueSoon: boolean; missingDue: boolean; attention: boolean;
  reasons: string[]; durationMs: number | null;
}
export interface OperationsProjectRow {
  project: Project; cases: ResearchCase[]; packages: OperationsPackageRow[];
  openCount: number; attentionCount: number; overdueCount: number; completedCount: number; adopted: boolean;
}
export interface OperationsSnapshot {
  metrics: {
    projectCount: number; caseCount: number; packageCount: number; openCount: number; runningCount: number;
    completedCount: number; blockedCount: number; failedCount: number; cancelledCount: number; draftCount: number;
    overdueCount: number; dueSoonCount: number; missingDueCount: number; attentionCount: number;
    completionRate: number | null; requirementsCount: number; sourceCount: number; artifactCount: number;
    reuseCandidateCount: number; obligationCount: number; adoptedCaseCount: number; adoptedProjectCount: number;
    adoptionRate: number | null; nodeCount: number; completedNodeCount: number;
  };
  packages: OperationsPackageRow[]; projects: OperationsProjectRow[]; issues: OperationsPackageRow[];
  statusCounts: Array<{ id: string; count: number }>; stageCounts: Array<{ id: string; count: number }>;
  trend: Array<{ day: string; planned: number; completed: number }>;
  trendSamples: { planned: number; completed: number; missingCompletedDate: number };
}

const STATUSES = ['draft', 'submitted', 'running', 'blocked', 'failed', 'completed', 'cancelled'];
const STAGES = ['input', 'requirements', 'selection', 'planning', 'design', 'verification', 'delivery', 'knowledge'];
const EXECUTED = new Set(['submitted', 'running', 'blocked', 'failed', 'completed']);
const CLOSED = new Set(['completed', 'cancelled']);
const DAY_MS = 86_400_000;
const text = (value: unknown) => typeof value === 'string' ? value : '';
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const matches = (query: string, ...values: unknown[]) => values.some(value => text(value).toLocaleLowerCase('zh-CN').includes(query));

function validDay(value: unknown): string | null {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(value + 'T00:00:00Z');
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value ? value : null;
}
function instant(value: unknown): number | null {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !validDay(value.slice(0, 10))) return null;
  const clock = value.slice(11, 19).split(':').map(Number);
  if (clock[0] > 23 || clock[1] > 59 || (clock[2] ?? 0) > 59) return null;
  const result = Date.parse(value); return Number.isFinite(result) ? result : null;
}
const shanghaiDay = (time: number) => new Date(time + 8 * 3_600_000).toISOString().slice(0, 10);
function endInstant(packageValue: Workpackage): number | null { return instant(packageValue.completed_at) ?? instant(packageValue.ended_at); }
export function operationTimestamp(value: unknown): string | undefined {
  const timestamp = instant(value); return timestamp === null ? undefined : new Date(timestamp).toISOString();
}
export function operationEndTimestamp(packageValue: Workpackage): string | undefined {
  const timestamp = endInstant(packageValue); return timestamp === null ? undefined : new Date(timestamp).toISOString();
}
function dueDay(packageValue: Workpackage): string | null {
  const end = validDay(packageValue.planned_end), start = validDay(packageValue.planned_start);
  return end && (!start || start <= end) ? end : null;
}
function adoptedCase(researchCase: ResearchCase): boolean {
  const revision = researchCase.input_revision;
  if (!Number.isInteger(revision)) return false;
  const current = (row: Record<string, unknown>) => row.input_revision === revision && !row.invalidated_at;
  // These entries are adoption receipts, not the global template directory.
  const adoption = Object.values(researchCase.workflow_templates ?? {}).some(value => {
    if (!isRecord(value)) return false;
    return current(value) && !!text(value.template_id) && !!text(value.template_version) && !!text(value.template_digest);
  });
  const binding = researchCase.taskbook_binding;
  return adoption || !!(binding && binding.status === 'current' && binding.input_revision === revision
    && !binding.invalidated_at && binding.id && binding.workflow?.id && binding.workflow?.version);
}
function reasonText(value: unknown): string {
  if (typeof value === 'string') return value.trim();
  if (isRecord(value)) return text(value.message).trim() || text(value.reason).trim();
  return '';
}
function packageRow(project: Project, researchCase: ResearchCase, workpackage: Workpackage, today: string, soon: string): OperationsPackageRow {
  const deadline = dueDay(workpackage), open = !CLOSED.has(workpackage.status);
  const overdue = !!(open && deadline && deadline < today);
  const dueSoon = !!(open && deadline && deadline >= today && deadline <= soon);
  const reasons = (workpackage.blocked_reasons ?? []).map(reasonText).filter(Boolean);
  const start = instant(workpackage.started_at), end = endInstant(workpackage);
  return {
    key: `${project.id}/${researchCase.id}/${workpackage.id}`, project, researchCase, workpackage,
    overdue, dueSoon, missingDue: !deadline,
    attention: open && (overdue || ['failed', 'blocked'].includes(workpackage.status) || reasons.length > 0),
    reasons, durationMs: start !== null && end !== null && end >= start ? end - start : null,
  };
}
function counts(ids: string[], values: string[]) {
  const result = new Map(ids.map(id => [id, 0]));
  for (const id of values) result.set(id, (result.get(id) ?? 0) + 1);
  return [...result].map(([id, count]) => ({ id, count }));
}

export function projectOperations(projects: Project[], filters: OperationsFilters = EMPTY_OPERATIONS_FILTERS, now: Date = new Date()): OperationsSnapshot {
  const today = shanghaiDay(now.getTime());
  const todayStart = Date.parse(today + 'T00:00:00Z');
  const soon = new Date(todayStart + 6 * DAY_MS).toISOString().slice(0, 10);
  const query = filters.query.trim().toLocaleLowerCase('zh-CN');
  const projected: OperationsProjectRow[] = [];
  for (const project of projects) {
    if (filters.owner !== 'all' && project.owner_id !== filters.owner) continue;
    const parentMatch = !query || matches(query, project.title, project.customer_name, project.product_name, project.brief);
    const cases: ResearchCase[] = [], packages: OperationsPackageRow[] = [];
    for (const researchCase of project.cases ?? []) {
      if (filters.stage !== 'all' && researchCase.stage !== filters.stage) continue;
      const caseMatch = parentMatch || matches(query, researchCase.title);
      const eligible = (researchCase.workpackages ?? []).filter(workpackage => (filters.status === 'all' || workpackage.status === filters.status)
        && (caseMatch || matches(query, workpackage.title)));
      if ((filters.status !== 'all' && eligible.length === 0) || (!caseMatch && eligible.length === 0)) continue;
      cases.push(researchCase);
      packages.push(...eligible.map(workpackage => packageRow(project, researchCase, workpackage, today, soon)));
    }
    if (!cases.length && !(filters.stage === 'all' && filters.status === 'all' && parentMatch)) continue;
    projected.push({ project, cases, packages, openCount: packages.filter(row => !CLOSED.has(row.workpackage.status)).length,
      attentionCount: packages.filter(row => row.attention).length, overdueCount: packages.filter(row => row.overdue).length,
      completedCount: packages.filter(row => row.workpackage.status === 'completed').length, adopted: cases.some(adoptedCase) });
  }
  projected.sort((a, b) => b.attentionCount - a.attentionCount || b.overdueCount - a.overdueCount || a.project.id.localeCompare(b.project.id));
  const packages = projected.flatMap(row => row.packages), cases = projected.flatMap(row => row.cases);
  const statusCounts = counts(STATUSES, packages.map(row => row.workpackage.status || 'unknown'));
  const statusCount = (id: string) => statusCounts.find(row => row.id === id)?.count ?? 0;
  const denominator = packages.filter(row => EXECUTED.has(row.workpackage.status)).length;
  const completedCount = statusCount('completed'), adoptedProjectCount = projected.filter(row => row.adopted).length;
  const trend = Array.from({ length: 14 }, (_unused, index) => ({ day: new Date(todayStart - (13 - index) * DAY_MS).toISOString().slice(0, 10), planned: 0, completed: 0 }));
  const days = new Map(trend.map(row => [row.day, row]));
  const trendSamples = { planned: 0, completed: 0, missingCompletedDate: 0 };
  for (const { workpackage } of packages) {
    const plannedDay = dueDay(workpackage), planned = plannedDay ? days.get(plannedDay) : undefined;
    if (planned) { planned.planned++; trendSamples.planned++; }
    if (workpackage.status !== 'completed') continue;
    const finish = endInstant(workpackage);
    if (finish === null) { trendSamples.missingCompletedDate++; continue; }
    const completed = days.get(shanghaiDay(finish));
    if (completed) { completed.completed++; trendSamples.completed++; }
  }
  const issues = packages.filter(row => row.attention).sort((a, b) => {
    const priority = (row: OperationsPackageRow) => row.workpackage.status === 'failed' ? 0 : row.workpackage.status === 'blocked' ? 1 : row.overdue ? 2 : 3;
    return priority(a) - priority(b) || (dueDay(a.workpackage) ?? '9999').localeCompare(dueDay(b.workpackage) ?? '9999') || a.key.localeCompare(b.key);
  });
  return { projects: projected, packages, issues, statusCounts, stageCounts: counts(STAGES, cases.map(row => row.stage || 'unknown')), trend, trendSamples,
    metrics: { projectCount: projected.length, caseCount: cases.length, packageCount: packages.length,
      openCount: packages.filter(row => !CLOSED.has(row.workpackage.status)).length,
      runningCount: statusCount('running'), completedCount, blockedCount: statusCount('blocked'), failedCount: statusCount('failed'),
      cancelledCount: statusCount('cancelled'), draftCount: statusCount('draft'),
      overdueCount: packages.filter(row => row.overdue).length, dueSoonCount: packages.filter(row => row.dueSoon).length,
      missingDueCount: packages.filter(row => row.missingDue).length, attentionCount: issues.length,
      completionRate: denominator ? completedCount / denominator * 100 : null,
      requirementsCount: cases.reduce((sum, row) => sum + (row.requirements?.length ?? 0), 0),
      sourceCount: cases.reduce((sum, row) => sum + (row.sources?.length ?? 0), 0),
      artifactCount: packages.reduce((sum, row) => sum + (row.workpackage.artifacts?.length ?? 0), 0),
      reuseCandidateCount: cases.reduce((sum, row) => sum + (row.reuse_candidates?.length ?? 0), 0),
      obligationCount: packages.reduce((sum, row) => sum + (row.workpackage.obligations?.length ?? 0), 0),
      adoptedCaseCount: cases.filter(adoptedCase).length, adoptedProjectCount,
      adoptionRate: projected.length ? adoptedProjectCount / projected.length * 100 : null,
      nodeCount: packages.reduce((sum, row) => sum + (row.workpackage.nodes?.length ?? 0), 0),
      completedNodeCount: packages.reduce((sum, row) => sum + (row.workpackage.nodes ?? []).filter(node => node.status === 'completed').length, 0) } };
}
