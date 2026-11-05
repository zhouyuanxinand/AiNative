import { locationFromPageReference, pageReference, readPlatformLocation, type PageReference } from '../platformNavigation';
import type { AssistantTarget } from '../types';

export type AssistantNavigation = AssistantTarget | { target: 'workpackages'; workpackageId: string };

/** Only stable object references cross the assistant boundary, never a browser URL. */
export function currentCasePageReference(href: string, projectId: string, caseId: string): PageReference | undefined {
  const reference = pageReference(readPlatformLocation(href));
  return reference.project_id === projectId && reference.case_id === caseId ? reference : undefined;
}

const targetByRoute: Partial<Record<PageReference['route_id'], AssistantTarget>> = {
  'case.overview': 'current', 'case.materials': 'sources', 'case.requirements': 'requirements',
  'case.selection': 'routes', 'case.execution': 'workpackages', 'case.process': 'process',
  'case.evidence': 'artifacts', 'case.history': 'history',
};
const legacyTargets = new Set<AssistantTarget>(['current', 'sources', 'requirements', 'routes', 'workpackages', 'process', 'artifacts', 'history']);

/** The existing workface navigation still owns drafts, focus and leave protection. */
export function assistantNavigationTarget(navigation: unknown, projectId: string, caseId: string): AssistantNavigation | null {
  if (!navigation || typeof navigation !== 'object') return null;
  const value = navigation as { page_ref?: unknown; target?: unknown };
  if (value.page_ref !== undefined) {
    const location = locationFromPageReference(value.page_ref);
    if (!location || location.projectId !== projectId || location.caseId !== caseId) return null;
    const reference = pageReference(location);
    if (reference.route_id === 'case.execution' && reference.workpackage_id) return { target: 'workpackages', workpackageId: reference.workpackage_id };
    return targetByRoute[reference.route_id] ?? null;
  }
  return typeof value.target === 'string' && legacyTargets.has(value.target as AssistantTarget) ? value.target as AssistantTarget : null;
}
