import type { CaseSurface } from './scenarioManifest';
import type { CaseWorkspaceView } from './types';

export const VIEW_TITLES = { home: '我的工作', projects: '项目空间', workspace: '资源工作台', management: '研发管理', flows: '流程管理', knowledge: '知识管理', operations: '运营管理', system: '系统管理' } as const;
export type PlatformView = keyof typeof VIEW_TITLES;
export interface CasePage { caseView: CaseWorkspaceView; surface?: CaseSurface; evidence?: 'artifacts' | 'history'; workpackageId?: string }
export interface PlatformLocation extends CasePage { view: PlatformView; projectId: string; caseId: string; q: string; page: number }
const surfaces: CaseSurface[] = ['current', 'sources', 'requirements', 'routes', 'preparation', 'workpackages', 'delivery', 'reuse', 'decision'];
export function readPlatformLocation(href: string): PlatformLocation {
  const url = new URL(href), query = url.searchParams;
  const path = url.pathname.match(/^\/rd\/projects\/([^/]+)(?:\/cases\/([^/]+))?\/?$/);
  const decode = (value?: string) => { try { return value ? decodeURIComponent(value) : ''; } catch { return ''; } };
  const projectId = query.get('project') ?? decode(path?.[1]);
  const caseId = projectId ? query.get('case') ?? decode(path?.[2]) : '';
  const requested = query.get('rd_view'), panel = query.get('case_view'), step = query.get('step');
  const view = requested === 'contracts' ? 'workspace' : requested && Object.prototype.hasOwnProperty.call(VIEW_TITLES, requested) ? requested as PlatformView : projectId ? 'projects' : 'home';
  const caseView = panel === 'process' || panel === 'evidence' ? panel : 'current';
  const page = Number(query.get('page'));
  const evidence = query.get('evidence');
  return { view, projectId, caseId, q: query.get('q') ?? '', page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
    caseView: caseId ? caseView : 'current',
    surface: caseId && caseView === 'current' && surfaces.includes(step as CaseSurface) ? step as CaseSurface : undefined,
    evidence: caseId && caseView === 'evidence' && (evidence === 'artifacts' || evidence === 'history') ? evidence : undefined,
    workpackageId: caseId && step === 'workpackages' && caseView === 'current' ? query.get('workpackage') || undefined : undefined };
}

export function platformLocationUrl(href: string, location: PlatformLocation): URL {
  const url = new URL(href);
  if (url.pathname.startsWith('/rd/projects/')) url.pathname = '/rd';
  const inCase = location.view === 'projects' && !!location.projectId && !!location.caseId;
  for (const [key, value] of Object.entries({ rd_view: location.view === 'home' ? '' : location.view,
    project: location.projectId, case: location.caseId, q: location.q, page: location.page > 1 ? String(location.page) : '',
    case_view: inCase && location.caseView !== 'current' ? location.caseView : '',
    step: inCase && location.caseView === 'current' ? location.surface : '',
    evidence: inCase && location.caseView === 'evidence' ? location.evidence : '',
    workpackage: inCase && location.caseView === 'current' && location.surface === 'workpackages' ? location.workpackageId : '',
  })) { if (value) url.searchParams.set(key, value); else url.searchParams.delete(key); }
  return url;
}

export function sameCaseWorkspace(left: PlatformLocation, right: PlatformLocation): boolean {
  return left.view === 'projects' && right.view === 'projects' && !!left.caseId && left.projectId === right.projectId && left.caseId === right.caseId;
}

export const HISTORY_INDEX = 'rdNavigationIndex';
export function ensureHistoryIndex(history: History): number {
  const index = history.state?.[HISTORY_INDEX];
  if (Number.isInteger(index) && index >= 0) return index;
  history.replaceState({ ...history.state, [HISTORY_INDEX]: 0 }, '');
  return 0;
}
