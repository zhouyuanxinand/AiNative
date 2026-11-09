import { caseJourney, caseStepForSurface } from './caseJourney';
import type { CasePage } from './platformNavigation';
import type { ResearchCase } from './types';

/** Only an explicit move to an earlier, available editor needs a warning. */
export function backwardCaseStep(before: CasePage, after: CasePage, researchCase: ResearchCase) {
  if (before.caseView !== 'current' || after.caseView !== 'current'
    || !before.surface || before.surface === 'current' || !after.surface || after.surface === 'current') return null;
  const steps = caseJourney(researchCase).steps;
  const from = steps.findIndex(step => step.id === caseStepForSurface(before.surface!, researchCase));
  const to = steps.findIndex(step => step.id === caseStepForSurface(after.surface!, researchCase));
  return from > to && to >= 0 && steps[to].available ? steps[to] : null;
}
