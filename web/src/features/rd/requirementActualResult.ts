import { isCurrentSource } from './presentation';
import type { Clarification, Requirement, ResearchCase, Source } from './types';

export type RequirementActualResult = { value: string; kind: 'accepted' | 'clarified' | 'specification' | 'baseline' };
const revision = (row: Requirement) => row.revision ?? row.version ?? 1;
const placeholder = /^(?:[^:：\n。.!！?？;；，,]{1,200}[:：]\s*)?(?:待澄清|待确认|待定|待补充|未明确|待填写|待采纳|待核对|【人工填写】)(?:\s*[（(][^()（）\n]*[)）])?[。．.!！?？;；,，\s]*$/u;
export const isUnresolvedRequirementValue = (value: string) => !value.trim() || value.trim() === '--' || placeholder.test(value.trim());
const snapshot = (source: Source) => ({ id: source.id, role: source.role, name: source.name, version: source.version, sha256: source.sha256 });
function equal(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object' || Array.isArray(left) !== Array.isArray(right)) return false;
  const a = Object.entries(left), b = Object.entries(right);
  return a.length === b.length && a.every(([key, value]) => Object.prototype.hasOwnProperty.call(right, key) && equal(value, (right as Record<string, unknown>)[key]));
}
export function currentRequirementSources(rc: ResearchCase): Source[] {
  const selection = { ...rc.source_selection };
  for (const role of ['tech', 'spec'] as const) {
    const candidates = rc.sources.filter(source => source.role === role);
    if (selection[role] === undefined && candidates.length === 1) selection[role] = candidates[0].id;
  }
  return rc.sources.filter(source => isCurrentSource(source, selection));
}
export function isCurrentSpecificationBatch(rc: ResearchCase): boolean {
  const batch = rc.requirement_recommendations;
  return !!batch && batch.status === 'current' && batch.input_revision === rc.input_revision
    && equal(batch.source_hashes, Object.fromEntries(currentRequirementSources(rc).map(source => [source.id, source.sha256])));
}
/** Applicability acceptance uses the adopted extraction, never the model proposal or a revised row. */
export function originalRequirementValue(rc: ResearchCase, row: Requirement): string | null {
  const analysis = rc.source_analysis;
  const sources = currentRequirementSources(rc);
  if (analysis?.status !== 'adopted' || analysis.adopted_input_revision !== rc.input_revision
    || !equal(analysis.source_hashes, Object.fromEntries(sources.map(source => [source.id, source.sha256])))) return null;
  const originals = analysis.requirements.filter(candidate => candidate.requirement_id === row.id && candidate.status !== 'rejected');
  if (originals.length !== 1) return null;
  const original = originals[0];
  const activeIds = new Set(sources.map(source => source.id));
  if (isUnresolvedRequirementValue(original.content) || !original.source_ids.length
    || !original.source_ids.every(id => activeIds.has(id))) return null;
  return original.content;
}
export function isAdoptedRequirementClarification(rc: ResearchCase, row: Requirement, record: Clarification): boolean {
  const batch = rc.requirement_recommendations, adoption = record.adoption;
  if (batch && !isCurrentSpecificationBatch(rc)) return false;
  if (record.status !== 'adopted' || record.requirement_id !== row.id || !adoption
    || adoption.requirement_revision !== revision(row) || adoption.requirement_content !== row.content
    || batch && adoption.recommendation_batch_id !== batch.id) return false;
  const recorded = (row.history ?? []).some(entry => !!entry && typeof entry === 'object'
    && 'revision' in entry && entry.revision === revision(row) && 'clarification_id' in entry && entry.clarification_id === record.id);
  const activeSources = currentRequirementSources(rc);
  const activeIds = new Set(activeSources.map(source => source.id));
  if (![...(row.source_ids ?? []), ...(record.answer_source_ids ?? [])].every(id => activeIds.has(id))) return false;
  const answerSources = rc.sources.filter(source => (record.answer_source_ids ?? []).includes(source.id));
  if (!recorded || !equal(record.answer_source_snapshots, answerSources.map(snapshot))) return false;
  return adoption.source_hashes == null || equal(adoption.source_hashes,
    Object.fromEntries(activeSources.map(source => [source.id, source.sha256])));
}
/** Current matched specifications supply a pending result; other suggestions require adoption. */
export function requirementActualResult(rc: ResearchCase, row: Requirement): RequirementActualResult | null {
  const resolvedContent = !isUnresolvedRequirementValue(row.content);
  const activeIds = new Set(currentRequirementSources(rc).map(source => source.id));
  if (!(row.source_ids ?? []).every(id => activeIds.has(id))) return null;
  const batch = rc.requirement_recommendations, review = row.review;
  if (batch && !isCurrentSpecificationBatch(rc)) return null;
  if (resolvedContent && (rc.clarifications ?? []).some(record => isAdoptedRequirementClarification(rc, row, record))) return { value: row.content, kind: 'clarified' };
  const items = batch?.items.filter(candidate => candidate.requirement_id === row.id) ?? [];
  const item = items.length === 1 ? items[0] : undefined;
  if (resolvedContent && batch && review?.decision === 'accept' && review.recommendation_batch_id === batch.id
    && review.requirement_revision === revision(row) && review.actual_value === row.content) {
    const matched = item?.status === 'matched' && item.proposed_value === row.content;
    const original = item?.status === 'needs_review' && review.actual_value_source === 'original'
      && review.analysis_id === rc.source_analysis?.id && originalRequirementValue(rc, row) === row.content;
    if (matched || original) return { value: row.content, kind: 'accepted' };
  }
  const proposal = item?.proposed_value ?? '';
  if (batch && item?.status === 'matched' && !isUnresolvedRequirementValue(proposal)) {
    const currentReview = review?.recommendation_batch_id === batch.id && review.requirement_revision === revision(row);
    if (currentReview && (review?.decision === 'reject' || review?.decision === 'manual')) return null;
    const saved = row.specification_result;
    const savedResult = saved?.actual_value_source === 'specification' && saved.actual_value === row.content
      && saved.actual_value === item.proposed_value && saved.recommendation_batch_id === batch.id
      && saved.requirement_revision === revision(row) && saved.source_requirement_revision === item.requirement_revision
      && equal(saved.source_hashes, batch.source_hashes);
    const specIds = new Set(currentRequirementSources(rc).filter(source => source.role === 'spec').map(source => source.id));
    const verifiedEvidence = !!item.evidence?.length && item.evidence.every(evidence => specIds.has(evidence.source_id) && !!evidence.quote?.trim());
    if ((item.requirement_revision === revision(row) || savedResult) && verifiedEvidence) return { value: proposal, kind: 'specification' };
  }
  return null;
}
/** Existing fixed baselines are read-only history, not permission to resolve new requirements implicitly. */
export function requirementDisplayResult(rc: ResearchCase, row: Requirement): RequirementActualResult | null {
  const result = requirementActualResult(rc, row);
  if (result) return result;
  const baseline = rc.requirement_baselines?.find(item => item.id === rc.business_lifecycle?.current_requirement_baseline_id);
  if (!baseline || baseline.invalidated_at || baseline.status !== 'current' || baseline.input_revision !== rc.input_revision
    || !equal(baseline.items, rc.requirements) || !Array.isArray(baseline.source_refs)) return null;
  const sourceRefs = baseline.source_refs as Array<{ id: string }>;
  const active = currentRequirementSources(rc);
  if (!sourceRefs.every(ref => active.some(source => source.id === ref.id && equal(ref, snapshot(source))))) return null;
  return { value: row.content, kind: 'baseline' };
}
