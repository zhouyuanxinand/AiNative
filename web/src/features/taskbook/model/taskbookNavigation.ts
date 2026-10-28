import type { NativeWorkspace } from '../api/workspace';

export type TaskbookView = 'inputs' | 'document' | 'planning' | 'review' | 'handoff';
export function validTaskbookView(view: string | null): TaskbookView | null {
  return view === 'inputs' || view === 'document' || view === 'planning' || view === 'review' || view === 'handoff' ? view : null;
}

/** Resolve only when entering a workspace; subsequent refreshes retain the selected view. */
export function taskbookView(requested: string | null, w: NativeWorkspace): TaskbookView {
  const explicit = validTaskbookView(requested);
  if (explicit) return explicit;
  if (w.reviews.some(review => review.status === 'pending' && review.reviewer_id === w.current_user_id && review.submitter_id !== w.current_user_id)) return 'review';
  if (w.handoffs.some(handoff => handoff.status === 'pending' && handoff.assignee_id === w.current_user_id)
    || w.project.owner_id === w.current_user_id && w.change_impacts.some(impact => impact.status === 'pending')) return 'handoff';
  if (w.task.status === 'done' && w.releases.some(release => release.id === w.work_unit.release_id)) return 'handoff';
  if (w.task.status === 'changes_requested') return 'document';
  if (w.task.status === 'in_review') return 'review';
  if (w.work_unit.selected_revision_id) {
    if (w.work_unit.current_stage === 'ND14') return 'planning';
    if (w.work_unit.current_stage === 'ND15') return w.wbs?.source_revision_id === w.work_unit.selected_revision_id && w.wbs.status === 'verified' ? 'review' : 'planning';
    return 'document';
  }
  return 'inputs';
}

export const taskbookProjectHref = (pid: string, tid: string) => `/rd/${encodeURIComponent(pid)}?tab=flow#task-${encodeURIComponent(tid)}`;
export const taskbookReviewHref = (pid: string, tid: string, reviewId?: string) => `/rd/${encodeURIComponent(pid)}/tasks/${encodeURIComponent(tid)}?view=review${reviewId ? `#review-${encodeURIComponent(reviewId)}` : ''}`;
