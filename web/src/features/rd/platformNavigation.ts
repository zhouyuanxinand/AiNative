import type { CaseSurface } from './scenarioManifest';
import type { CaseWorkspaceView } from './types';

export const VIEW_TITLES = { home: '我的工作', projects: '项目空间', workspace: '资源工作台', management: '研发管理', flows: '流程管理', knowledge: '知识管理', operations: '运营管理', system: '系统管理' } as const;
export type PlatformView = keyof typeof VIEW_TITLES;
export interface CasePage { caseView: CaseWorkspaceView; surface?: CaseSurface; evidence?: 'artifacts' | 'history'; workpackageId?: string }
export interface PlatformLocation extends CasePage { view: PlatformView; projectId: string; caseId: string; q: string; page: number; researchTab?: 'customer' | 'product'; projectStatus?: 'active' | 'attention' | 'completed' | 'empty'; projectSort?: 'oldest' | 'name'; projectLayout?: 'list' }
const paths: Record<PlatformView, string> = { home: '/work', projects: '/projects', management: '/research', flows: '/flows', knowledge: '/knowledge', operations: '/operations', workspace: '/workspace', system: '/settings' };
const surfacePaths: Record<CaseSurface, string> = { current: 'overview', sources: 'materials', requirements: 'requirements', routes: 'selection', preparation: 'preparation', workpackages: 'execution', delivery: 'delivery', reuse: 'reuse', decision: 'decision' };
const decode = (value?: string) => { try { return value ? decodeURIComponent(value) : ''; } catch { return ''; } };
const positivePage = (value: unknown) => { const page = Number(value); return Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1; };
const emptyLocation = (): PlatformLocation => ({ view: 'home', projectId: '', caseId: '', q: '', page: 1, caseView: 'current', surface: undefined, evidence: undefined, workpackageId: undefined });

export function readPlatformLocation(href: string): PlatformLocation {
  const url = new URL(href), query = url.searchParams, pathname = url.pathname.replace(/\/+$/, '') || '/';
  const result = emptyLocation();
  const projectPath = pathname.match(/^\/projects\/([^/]+)(?:\/flows\/([^/]+)(?:\/([^/]+))?)?$/);
  const main = Object.entries(paths).find(([, path]) => path === pathname), profile = pathname.match(/^\/research\/(customers|products)$/);
  if (projectPath) {
    result.view = 'projects'; result.projectId = decode(projectPath[1]); result.caseId = result.projectId ? decode(projectPath[2]) : '';
    const page = projectPath[3];
    if (result.caseId) {
      if (page === 'process') result.caseView = 'process';
      else if (page === 'evidence' || page === 'history') { result.caseView = 'evidence'; result.evidence = page === 'history' ? 'history' : 'artifacts'; }
      else result.surface = (Object.keys(surfacePaths) as CaseSurface[]).find(key => surfacePaths[key] === page);
    }
  } else if (main || profile) {
    result.view = profile ? 'management' : main![0] as PlatformView;
    if (profile) result.researchTab = profile[1] === 'customers' ? 'customer' : 'product';
  } else {
    // Read existing bookmarks; a semantic path takes precedence over old query IDs.
    const oldPath = pathname.match(/^\/rd\/projects\/([^/]+)(?:\/cases\/([^/]+))?$/);
    result.projectId = query.get('project') ?? decode(oldPath?.[1]);
    result.caseId = result.projectId ? query.get('case') ?? decode(oldPath?.[2]) : '';
    const requested = query.get('rd_view');
    result.view = requested === 'contracts' ? 'workspace' : requested && Object.prototype.hasOwnProperty.call(VIEW_TITLES, requested) ? requested as PlatformView : result.projectId ? 'projects' : 'home';
    const panel = query.get('case_view'), step = query.get('step'), evidence = query.get('evidence');
    result.caseView = result.caseId && (panel === 'process' || panel === 'evidence') ? panel : 'current';
    result.surface = result.caseId && result.caseView === 'current' && Object.prototype.hasOwnProperty.call(surfacePaths, step ?? '') ? step as CaseSurface : undefined;
    result.evidence = result.caseId && result.caseView === 'evidence' && (evidence === 'artifacts' || evidence === 'history') ? evidence : undefined;
    const tab = query.get('management_tab');
    if (result.view === 'management' && (tab === 'customer' || tab === 'product')) result.researchTab = tab;
  }
  if (result.view !== 'projects') { result.projectId = ''; result.caseId = ''; }
  if (result.view === 'projects' && !result.projectId) {
    result.q = query.get('q') ?? ''; result.page = positivePage(query.get('page'));
    const status = query.get('status'), sort = query.get('sort');
    if (status === 'active' || status === 'attention' || status === 'completed' || status === 'empty') result.projectStatus = status;
    if (sort === 'oldest' || sort === 'name') result.projectSort = sort;
    if (query.get('layout') === 'list') result.projectLayout = 'list';
  }
  if (result.caseId && result.caseView === 'current' && result.surface === 'workpackages') result.workpackageId = query.get('workpackage') || undefined;
  return result;
}

/** The defaults also restrict which navigation fields can be retained in URLs/history. */
export const DIRECTORY_DEFAULTS: Record<string, Record<string, string>> = {
  projects: { q: '', page: '1', status: 'all', sort: 'recent', layout: 'cards' },
  management: { q: '', kind: 'all', page: '1', tab: 'tasks' },
  management_customer: { q: '', page: '1', item: '' }, management_product: { q: '', page: '1', item: '' },
  flow: { tab: 'flows', kind: 'research', item: '', version: '', detail: '', q: '', page: '1' },
  workflow: { category: 'project', q: '', page: '1', item: '', version: '', detail: 'canvas', history_page: '1', compare: '' },
  knowledge: { q: '', kind: 'all', page: '1', tab: 'tasks', item: '' },
  workspace: { q: '', kind: '', item: '', version: '', page: '1' },
  operations: { query: '', owner: 'all', stage: 'all', status: 'all', tab: 'delivery', package_page: '1', project_page: '1', risk_page: '1', quality_page: '1' },
};
export type DirectorySnapshots = Record<string, Record<string, string>>;
export const DIRECTORY_HISTORY = 'rdDirectoryStates';
const queryKey = (prefix: string, key: string) => prefix === 'projects' ? key : `${prefix}_${key}`;
export function readDirectoryLocation(href: string, prefix: string, defaults: Record<string, string>, snapshots: DirectorySnapshots = {}): Record<string, string> {
  const query = new URL(href).searchParams, value = { ...defaults };
  for (const key of Object.keys(defaults)) value[key] = query.get(queryKey(prefix, key)) ?? snapshots[prefix]?.[key] ?? defaults[key];
  if ('page' in value) value.page = String(positivePage(value.page));
  if (prefix === 'management') { const location = readPlatformLocation(href); value.tab = location.researchTab ?? (location.view === 'management' ? 'tasks' : value.tab); }
  return value;
}
export function captureDirectoryHistory(href: string, state: Record<string, unknown> | null): Record<string, unknown> {
  const snapshots: DirectorySnapshots = { ...(state?.[DIRECTORY_HISTORY] as DirectorySnapshots ?? {}) }, query = new URL(href).searchParams;
  for (const [prefix, defaults] of Object.entries(DIRECTORY_DEFAULTS)) {
    if (Object.keys(defaults).some(key => query.has(queryKey(prefix, key)))) snapshots[prefix] = readDirectoryLocation(href, prefix, defaults, snapshots);
  }
  const location = readPlatformLocation(href);
  if (location.view === 'management') snapshots.management = { ...snapshots.management, tab: location.researchTab ?? 'tasks' };
  return { ...state, [DIRECTORY_HISTORY]: snapshots };
}
function directoryPrefixes(location: PlatformLocation, href: string, snapshots: DirectorySnapshots): string[] {
  if (location.view === 'projects') return location.projectId ? [] : ['projects'];
  if (location.view === 'management') return [location.researchTab ? `management_${location.researchTab}` : 'management'];
  if (location.view === 'flows') { const flow = readDirectoryLocation(href, 'flow', DIRECTORY_DEFAULTS.flow, snapshots); return flow.tab === 'flows' && flow.kind === 'research' ? ['flow', 'workflow'] : ['flow']; }
  return ['workspace', 'knowledge', 'operations'].includes(location.view) ? [location.view] : [];
}
export function platformLocationUrl(href: string, location: PlatformLocation, snapshots: DirectorySnapshots = {}): URL {
  const url = new URL(href), previous = readPlatformLocation(href);
  url.search = ''; url.hash = ''; url.pathname = paths[location.view];
  if (location.view === 'management' && location.researchTab) url.pathname += location.researchTab === 'customer' ? '/customers' : '/products';
  if (location.view === 'projects' && location.projectId) {
    url.pathname += '/' + encodeURIComponent(location.projectId);
    if (location.caseId) {
      url.pathname += '/flows/' + encodeURIComponent(location.caseId);
      const part = location.caseView === 'process' ? 'process' : location.caseView === 'evidence' ? location.evidence === 'history' ? 'history' : 'evidence' : location.surface ? surfacePaths[location.surface] : '';
      if (part) url.pathname += '/' + part;
      if (part === 'execution' && location.workpackageId) url.searchParams.set('workpackage', location.workpackageId);
    }
  }
  for (const prefix of directoryPrefixes(location, href, snapshots)) {
    const defaults = DIRECTORY_DEFAULTS[prefix], value = readDirectoryLocation(href, prefix, defaults, snapshots);
    if (prefix === 'projects' && previous.view === 'projects' && !previous.projectId) {
      value.q = location.q; value.page = String(location.page);
      value.status = location.projectStatus ?? 'all'; value.sort = location.projectSort ?? 'recent'; value.layout = location.projectLayout ?? 'cards';
    }
    for (const [key, content] of Object.entries(value)) {
      if (prefix === 'management' && key === 'tab') continue;
      if (content && content !== defaults[key]) url.searchParams.set(queryKey(prefix, key), content);
    }
  }
  return url;
}
export function updateDirectoryLocation(href: string, prefix: string, value: Record<string, string>, state: Record<string, unknown> | null): { url: URL; state: Record<string, unknown> } {
  const nextState = captureDirectoryHistory(href, state), snapshots = nextState[DIRECTORY_HISTORY] as DirectorySnapshots;
  snapshots[prefix] = { ...value };
  const source = new URL(href);
  for (const key of Object.keys(DIRECTORY_DEFAULTS[prefix] ?? value)) source.searchParams.delete(queryKey(prefix, key));
  const location = readPlatformLocation(source.href);
  if (prefix === 'management') location.researchTab = value.tab === 'customer' || value.tab === 'product' ? value.tab : undefined;
  return { url: platformLocationUrl(source.href, location, snapshots), state: nextState };
}

export type PageRouteId = 'work' | 'projects' | 'project' | 'research' | 'research.customers' | 'research.products' | 'flows' | 'knowledge' | 'operations' | 'workspace' | 'settings' | 'case.resume' | 'case.overview' | 'case.materials' | 'case.requirements' | 'case.selection' | 'case.preparation' | 'case.execution' | 'case.delivery' | 'case.reuse' | 'case.decision' | 'case.process' | 'case.evidence' | 'case.history';
export interface PageReference { schema_version: 1; route_id: PageRouteId; project_id?: string; case_id?: string; workpackage_id?: string }
export function pageReference(location: PlatformLocation): PageReference {
  const ref: PageReference = { schema_version: 1, route_id: paths[location.view].slice(1) as PageRouteId };
  if (location.view === 'management' && location.researchTab) ref.route_id = location.researchTab === 'customer' ? 'research.customers' : 'research.products';
  if (location.view === 'projects' && location.projectId) {
    ref.route_id = 'project'; ref.project_id = location.projectId;
    if (location.caseId) {
      ref.case_id = location.caseId;
      const page = location.caseView === 'process' ? 'process' : location.caseView === 'evidence' ? location.evidence === 'history' ? 'history' : 'evidence' : location.surface ? surfacePaths[location.surface] : 'resume';
      ref.route_id = `case.${page}` as PageRouteId;
      if (page === 'execution' && location.workpackageId) ref.workpackage_id = location.workpackageId;
    }
  }
  return ref;
}
export function locationFromPageReference(value: unknown): PlatformLocation | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const ref = value as Record<string, unknown>;
  if (ref.schema_version !== 1 || typeof ref.route_id !== 'string' || Object.keys(ref).some(key => !['schema_version', 'route_id', 'project_id', 'case_id', 'workpackage_id'].includes(key))) return null;
  const id = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value);
  const isCase = ref.route_id.startsWith('case.'), isProject = ref.route_id === 'project' || isCase;
  if (isProject ? !id(ref.project_id) : ref.project_id !== undefined) return null;
  if (isCase ? !id(ref.case_id) : ref.case_id !== undefined) return null;
  if (ref.workpackage_id !== undefined && (ref.route_id !== 'case.execution' || !id(ref.workpackage_id))) return null;
  let path: string;
  if (isCase) {
    const part = ref.route_id.slice(5);
    if (!['resume', ...Object.values(surfacePaths), 'process', 'evidence', 'history'].includes(part)) return null;
    path = `/projects/${encodeURIComponent(ref.project_id as string)}/flows/${encodeURIComponent(ref.case_id as string)}` + (part === 'resume' ? '' : '/' + part);
  } else if (ref.route_id === 'project') path = '/projects/' + encodeURIComponent(ref.project_id as string);
  else if (ref.route_id === 'research.customers' || ref.route_id === 'research.products') path = '/' + ref.route_id.replace('.', '/');
  else { path = '/' + ref.route_id; if (!Object.values(paths).includes(path)) return null; }
  const url = new URL(path, 'https://page-reference.invalid');
  if (ref.workpackage_id) url.searchParams.set('workpackage', ref.workpackage_id as string);
  return readPlatformLocation(url.href);
}
export function sameCaseWorkspace(left: PlatformLocation, right: PlatformLocation): boolean { return left.view === 'projects' && right.view === 'projects' && !!left.caseId && left.projectId === right.projectId && left.caseId === right.caseId; }
export const HISTORY_INDEX = 'rdNavigationIndex';
export function ensureHistoryIndex(history: History): number {
  const index = history.state?.[HISTORY_INDEX];
  if (Number.isInteger(index) && index >= 0) return index;
  history.replaceState({ ...history.state, [HISTORY_INDEX]: 0 }, ''); return 0;
}
