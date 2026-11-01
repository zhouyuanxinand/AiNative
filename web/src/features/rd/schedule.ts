import type { Workpackage } from './types';

export function scheduleTime(value?: string | null, dayOnly = false): number | null {
  if (!value) return null;
  const time = Date.parse(dayOnly ? `${value}T00:00:00+08:00` : value);
  return Number.isFinite(time) ? time : null;
}

/** Missing actuals remain missing. Only an ongoing run may extend to the reporting time. */
export function workpackageActualRange(workpackage: Workpackage, now = Date.now()) {
  const start = scheduleTime(workpackage.started_at);
  if (start === null) return null;
  const recordedEnd = scheduleTime(workpackage.completed_at ?? workpackage.ended_at);
  return { start, end: recordedEnd ?? (workpackage.status === 'running' ? now : start), recordedEnd };
}
