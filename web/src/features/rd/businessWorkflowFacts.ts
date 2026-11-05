import type { ResearchCase } from './types';
export interface FixedBusinessTemplate { id?: string; version?: string | number; digest?: string; template_id?: string; template_version?: string | number; template_digest?: string }
export interface BusinessExecutionFact { status: 'completed' | 'running' | 'blocked' | 'failed' | 'cancelled' | 'pending'; workpackageId: string; runId: string; completed: number; total: number }
const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' ? value as Record<string, unknown> : {};
export function fixedBusinessTemplate(value: FixedBusinessTemplate) {
  return { id: value.template_id ?? value.id, version: String(value.template_version ?? value.version ?? ''), digest: value.template_digest ?? value.digest };
}
function sameTemplate(left: FixedBusinessTemplate, right: FixedBusinessTemplate) {
  const a = fixedBusinessTemplate(left), b = fixedBusinessTemplate(right);
  return !!a.id && !!a.version && a.id === b.id && a.version === b.version && (!a.digest || !b.digest || a.digest === b.digest);
}
/** Project adopted business actions from their fixed candidate and actual run, never from catalog or old template runs. */
export function businessNodeExecution(researchCase: ResearchCase, template: FixedBusinessTemplate, businessNodeId: string): BusinessExecutionFact | null {
  let fact: BusinessExecutionFact | null = null;
  const ordered = researchCase.workpackages.map((workpackage, index) => ({ workpackage, index, submittedAt: Date.parse(String(workpackage.snapshot?.submitted_at ?? '')) }));
  ordered.sort((a, b) => { const aTime = Number.isFinite(a.submittedAt) ? a.submittedAt : 0, bTime = Number.isFinite(b.submittedAt) ? b.submittedAt : 0; return aTime - bTime || (aTime && bTime ? String(a.workpackage.run_id ?? '').localeCompare(String(b.workpackage.run_id ?? '')) : 0) || a.index - b.index; });
  for (const { workpackage } of ordered) {
    if (researchCase.input_revision === undefined || workpackage.snapshot?.input_revision !== researchCase.input_revision || !workpackage.run_id) continue;
    const reference = record(workpackage.snapshot.execution_candidate);
    const candidate = (researchCase.execution_candidates ?? []).find(item => item.id === reference.id && item.digest === reference.digest);
    if (!candidate || candidate.input_revision !== researchCase.input_revision || !candidate.business_template || !sameTemplate(candidate.business_template, template)) continue;
    const fixedMapping = workpackage.snapshot.execution_mapping ?? workpackage.execution_mapping;
    const sourceMapping = Array.isArray(fixedMapping) ? fixedMapping : candidate.mapping;
    const mappings = sourceMapping.map(record).filter(item => !item.run_id || item.run_id === workpackage.run_id);
    const stepIds = new Set(mappings.filter(item => item.business_node_id === businessNodeId).map(item => item.step_instance_id));
    const nodes = workpackage.nodes.filter(node => stepIds.has(node.id) || sourceMapping.length === 0 && node.business_node_id === businessNodeId);
    if (!nodes.length) continue;
    const completed = nodes.filter(node => node.status === 'completed').length;
    const status: BusinessExecutionFact['status'] = workpackage.status === 'cancelled' ? 'cancelled'
      : nodes.some(node => node.status === 'blocked') ? 'blocked'
        : nodes.some(node => node.status === 'failed') ? 'failed'
          : nodes.some(node => node.status === 'cancelled') ? 'cancelled'
            : completed === nodes.length ? 'completed'
              : nodes.some(node => node.status === 'running') || completed > 0 ? 'running' : 'pending';
    fact = { status, workpackageId: workpackage.id, runId: workpackage.run_id, completed, total: nodes.length };
  }
  return fact;
}
export const BUSINESS_EXECUTION_LABELS: Record<BusinessExecutionFact['status'], string> = { completed: '执行已完成', running: '执行中', blocked: '执行已阻塞', failed: '执行失败', cancelled: '执行已取消', pending: '待执行' };

