import { caseJourney, caseStepForSurface } from './caseJourney';
import { summarizeCaseOutcome } from './caseOutcomeModel';
import type { CaseSurface, ScenarioManifest } from './scenarioManifest';
import type { ResearchCase } from './types';

export type CaseResumeStorage = Pick<Storage, 'getItem' | 'setItem'> | null;

export function browserCaseResumeStorage(): CaseResumeStorage {
  try { return typeof window === 'undefined' ? null : window.localStorage; }
  catch { return null; }
}

function resumeKey(actor: string | null | undefined, projectId: string, caseId: string): string | null {
  if (!actor || !projectId || !caseId) return null;
  return `rd:case-resume:v1:${encodeURIComponent(actor)}:${encodeURIComponent(projectId)}:${encodeURIComponent(caseId)}`;
}

/** Resume navigation only; availability and completion always come from current server data. */
export function readCaseResume(
  actor: string | null | undefined,
  projectId: string,
  caseId: string,
  researchCase: ResearchCase,
  manifest?: ScenarioManifest,
  storage: CaseResumeStorage = browserCaseResumeStorage(),
): CaseSurface {
  const journey = caseJourney(researchCase, manifest);
  if (journey.completed) return 'current';
  if (summarizeCaseOutcome(researchCase).execution.kind === 'running') return journey.active;
  const key = resumeKey(actor, projectId, caseId);
  if (key && storage) {
    try {
      const saved = storage.getItem(key);
      const step = journey.steps.find(item => item.id === saved && item.available);
      if (step) return step.target;
    } catch { /* Browser storage may be disabled; the current business step remains usable. */ }
  }
  return journey.active;
}

export function writeCaseResume(
  actor: string | null | undefined,
  projectId: string,
  caseId: string,
  surface: CaseSurface,
  researchCase: ResearchCase,
  storage: CaseResumeStorage = browserCaseResumeStorage(),
): void {
  const key = resumeKey(actor, projectId, caseId);
  if (!key || !storage || surface === 'current') return;
  const journey = caseJourney(researchCase);
  if (journey.completed) return;
  const step = caseStepForSurface(surface, researchCase);
  if (!journey.steps.some(item => item.id === step && item.available)) return;
  try { storage.setItem(key, step); }
  catch { /* Saving navigation must not block business actions. */ }
}
