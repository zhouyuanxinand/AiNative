import type { RdDetail } from '../api/rd';
import { projectTabFromUrl } from './projectNavigation.ts';

/** Open the same visible record order used by the owning project pagers. */
export function projectHref(detail: RdDetail, tab = 'overview', anchor = '') {
  if (anchor.startsWith('task-')) { const id = anchor.slice(5); if (detail.tasks.some(task => task.id === id && task.kind === 'taskbook')) return `/rd/${encodeURIComponent(detail.project.id)}/tasks/${encodeURIComponent(id)}`; }
  if (anchor.startsWith('review-')) { const review = detail.reviews.find(item => item.id === anchor.slice(7)); if (review && detail.tasks.some(task => task.id === review.task_id && task.kind === 'taskbook')) return `/rd/${encodeURIComponent(detail.project.id)}/tasks/${encodeURIComponent(review.task_id)}?view=review`; }
  const query = new URLSearchParams({ tab: projectTabFromUrl(`?tab=${encodeURIComponent(tab)}`) });
  if (['members', 'history', 'sources'].includes(tab)) { query.set('tab', 'materials'); query.set('section', tab); }
  const targets = [
    { prefix: 'requirement-', parameter: 'rd_requirements_page', items: detail.requirements },
    { prefix: 'task-', parameter: 'rd_tasks_page', items: detail.tasks },
    { prefix: 'artifact-', parameter: 'rd_artifacts_page', items: [...detail.artifacts].reverse() },
    { prefix: 'review-', parameter: 'rd_reviews_page', items: [...detail.reviews].reverse() },
  ];
  const target = targets.find(item => anchor.startsWith(item.prefix));
  if (target) {
    const id = anchor.slice(target.prefix.length);
    const index = target.items.findIndex(item => item.id === id);
    if (index >= 0) query.set(target.parameter, String(Math.floor(index / 10) + 1));
  }
  return `/rd/${encodeURIComponent(detail.project.id)}?${query}${anchor ? `#${encodeURIComponent(anchor)}` : ''}`;
}
