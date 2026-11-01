import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type MouseEvent } from 'react';
import { FeedbackConfirmDialog, FeedbackDialog } from '../../components/feedback/FeedbackDialog';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { useApplicationLeaveGuard } from '../../hooks/useApplicationLeaveGuard';
import { useCurrentUser } from '../../hooks/useCurrentUser';
import { RdAccountDock } from './RdAccountDock';
import { RdNavigationIcon } from './RdNavigationIcon';
import { CaseWorkspace } from './CaseWorkspace';
import { FloatingAssistant } from './FloatingAssistant';
import { PlatformHome } from './PlatformHome';
import { PlatformManagement } from './PlatformManagement';
import { RD_AUTH_REQUIRED_EVENT, RdApiError, makeRequestKey, rdAnalyzeSources, rdCatalog, rdCommand, rdCreate, rdProject, rdProjects, rdUpload } from './api';
import { messageOf, stageTitle } from './presentation';
import type { CaseWorkspaceView, Catalog, Project } from './types';
import { WorkspacePanel } from './WorkspacePanel';
import type { CommandRunner } from './WorkpackagePanel';
import '../../feedback.css';
import './rd.css';
import './caseWorkspace.css';
import './rdExperience.css';
import './platformHome.css';
import './rdApplicationShell.css';

type View = 'home' | 'projects' | 'workspace' | 'management' | 'flows' | 'knowledge' | 'operations' | 'system';
const VIEW_TITLES: Record<View, string> = { home: '我的工作', projects: '项目空间', workspace: '资源工作台', management: '研发管理', flows: '流程管理', knowledge: '知识管理', operations: '运营管理', system: '系统管理' };
const MANAGEMENT_VIEWS: View[] = ['management', 'flows', 'knowledge', 'operations', 'system'];
const PROJECT_PAGE_SIZE = 5;
function readLocation() {
  const query = new URLSearchParams(window.location.search);
  const path = window.location.pathname.match(/^\/rd\/projects\/([^/]+)(?:\/cases\/([^/]+))?\/?$/);
  const decode = (value?: string) => { try { return value ? decodeURIComponent(value) : ''; } catch { return ''; } };
  const projectId = query.get('project') ?? decode(path?.[1]);
  const requested = query.get('rd_view');
  const view: View = requested === 'contracts' ? 'workspace' : requested && Object.prototype.hasOwnProperty.call(VIEW_TITLES, requested) ? requested as View : projectId ? 'projects' : 'home';
  const page = Number(query.get('page'));
  return { view, projectId, caseId: query.get('case') ?? decode(path?.[2]), q: query.get('q') ?? '', page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1 };
}

export function RdPlatformPage() {
  const { requireLogin } = useCurrentUser();
  useEffect(() => {
    window.addEventListener(RD_AUTH_REQUIRED_EVENT, requireLogin);
    return () => window.removeEventListener(RD_AUTH_REQUIRED_EVENT, requireLogin);
  }, [requireLogin]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [location, setLocation] = useState(readLocation);
  const [caseView, setCaseView] = useState<CaseWorkspaceView>('current');
  const [surfaceRequest, setSurfaceRequest] = useState<{ target: 'current' | 'sources'; serial: number; caseId: string }>();
  const surfaceSerial = useRef(0);
  const [projects, setProjects] = useState<Project[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [projectLoading, setProjectLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [catalogError, setCatalogError] = useState('');
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [revision, setRevision] = useState(0);
  const [catalogRevision, setCatalogRevision] = useState(0);
  const [newDialog, setNewDialog] = useState<'project' | 'case' | null>(null);
  const [title, setTitle] = useState('');
  const [scenario, setScenario] = useState('');
  const [homeGoal, setHomeGoal] = useState('');
  const [goal, setGoal] = useState('');
  const [customerName, setCustomerName] = useState('');
  const [productName, setProductName] = useState('');
  const [createProgress, setCreateProgress] = useState<Project | null>(null);
  const [createError, setCreateError] = useState('');
  const [createUncertain, setCreateUncertain] = useState(false);
  const [createConflict, setCreateConflict] = useState(false);
  const [discardCreate, setDiscardCreate] = useState(false);
  const [pendingNavigation, setPendingNavigation] = useState<(() => void) | null>(null);
  const [query, setQuery] = useState(location.q);
  const [updatedAt, setUpdatedAt] = useState('');
  const mutationLock = useRef(false);
  const mutationRetry = useRef({ fingerprint: '', key: '' });
  const createRetry = useRef({ fingerprint: '', projectKey: '', caseKey: '', project: null as Project | null });
  const projectRequest = useRef<AbortController>();
  const queryRef = useRef<HTMLInputElement>(null);
  const composition = useRef(false);
  const focusUpload = useRef(false);
  const setChildDirty = useCallback((value: boolean) => setDirty(value), []);
  const selectedCase = location.view === 'projects' && project?.id === location.projectId ? project.cases.find(item => item.id === location.caseId) : undefined;
  const hasActiveRun = project?.cases.some(item => item.workpackages.some(workpackage => ['submitted', 'running'].includes(workpackage.status)));
  function beginCreate(kind: 'project' | 'case', fromUpload = false) {
    focusUpload.current = fromUpload;
    setTitle(''); setGoal(kind === 'project' ? homeGoal : ''); setCustomerName(''); setProductName('');
    setScenario(catalog?.scenarios[0]?.id ?? ''); setCreateError(''); setCreateUncertain(false); setCreateConflict(false); setCreateProgress(null);
    createRetry.current = { fingerprint: '', projectKey: '', caseKey: '', project: null };
    setNewDialog(kind);
  }
  function startFromUpload() { requestNavigation(() => beginCreate('project', true)); }
  useEffect(() => {
    if (!focusUpload.current || !selectedCase) return;
    focusUpload.current = false;
    setSurfaceRequest({ target: 'sources', serial: ++surfaceSerial.current, caseId: selectedCase.id });
  }, [selectedCase]);
  const createDirty = !!newDialog && !!(title || goal || customerName || productName || createProgress);
  useApplicationLeaveGuard({ dirty: createDirty || !!homeGoal.trim(), busyMessage: busy ? '研发操作尚未完成，请等待结果后再离开。' : undefined });
  useEffect(() => {
    document.title = `${selectedCase?.title ?? (location.view === 'projects' ? project?.title ?? VIEW_TITLES.projects : VIEW_TITLES[location.view])} · 研发管理平台`;
  }, [selectedCase?.title, project?.title, location.view]);

  const navigate = useCallback((next: Partial<ReturnType<typeof readLocation>>, replace = false) => {
    const previous = readLocation();
    const merged = { ...previous, ...next };
    if (previous.projectId !== merged.projectId || previous.caseId !== merged.caseId) { setCaseView('current'); setSurfaceRequest(undefined); }
    const url = new URL(window.location.href);
    if (url.pathname.startsWith('/rd/projects/')) url.pathname = '/rd';
    if (merged.view === 'home') url.searchParams.delete('rd_view'); else url.searchParams.set('rd_view', merged.view);
    for (const [key, value] of [['project', merged.projectId], ['case', merged.caseId], ['q', merged.q], ['page', merged.page > 1 ? String(merged.page) : '']] as const) {
      if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
    }
    window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
    setLocation(merged); setDirty(false); setError(''); setNotice(''); setConflict(false);
  }, []);
  const requestNavigation = (action: () => void) => {
    if (document.querySelector('.credentials-dialog[open]')) { setNotice('请先关闭设置窗口，再切换页面。'); return; }
    if (busy || workspaceBusy || mutationLock.current) { setNotice('当前操作尚未完成，请等待结果后再切换。'); return; }
    if (dirty || createDirty) setPendingNavigation(() => action); else action();
  };
  useEffect(() => {
    const onPop = () => {
      const next = readLocation();
      const settingsDialogOpen = !!document.querySelector('.credentials-dialog[open]');
      if (settingsDialogOpen || dirty || createDirty || busy || workspaceBusy) {
        const currentUrl = new URL(window.location.href);
        if (currentUrl.pathname.startsWith('/rd/projects/')) currentUrl.pathname = '/rd';
        if (location.projectId) currentUrl.searchParams.set('project', location.projectId); else currentUrl.searchParams.delete('project');
        if (location.caseId) currentUrl.searchParams.set('case', location.caseId); else currentUrl.searchParams.delete('case');
        if (location.view !== 'home') currentUrl.searchParams.set('rd_view', location.view); else currentUrl.searchParams.delete('rd_view');
        window.history.pushState({}, '', currentUrl);
        if (settingsDialogOpen) setNotice('请先关闭设置窗口，再切换页面。');
        else if (busy || workspaceBusy) setNotice('操作尚未完成，请等待结果后再切换。');
        else setPendingNavigation(() => () => navigate(next));
      } else { if (next.projectId !== location.projectId || next.caseId !== location.caseId) { setCaseView('current'); setSurfaceRequest(undefined); } setLocation(next); setQuery(next.q); setError(''); }
    };
    window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop);
  }, [dirty, createDirty, busy, workspaceBusy, location, navigate]);
  useEffect(() => {
    const controller = new AbortController();
    setListLoading(true); setListError('');
    void rdProjects(controller.signal).then(response => { if (!controller.signal.aborted) { setProjects(response.projects); setListLoading(false); } }).catch(reason => { if (!controller.signal.aborted) { setListError(messageOf(reason)); setListLoading(false); } });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    const controller = new AbortController();
    setCatalogLoading(true); setCatalogError('');
    void rdCatalog(controller.signal).then(response => { if (!controller.signal.aborted) { setCatalog(response); setCatalogLoading(false); } }).catch(reason => { if (!controller.signal.aborted) { setCatalogError(messageOf(reason)); setCatalogLoading(false); } });
    return () => controller.abort();
  }, [catalogRevision]);
  useEffect(() => {
    projectRequest.current?.abort();
    if (!location.projectId) { setProject(null); setProjectLoading(false); return; }
    const controller = new AbortController(); projectRequest.current = controller; setProjectLoading(true); setProject(null);
    void rdProject(location.projectId, controller.signal).then(value => { if (!controller.signal.aborted) { setProject(value); setProjectLoading(false); setUpdatedAt(new Date().toLocaleTimeString('zh-CN')); } }).catch(reason => { if (!controller.signal.aborted) { setProjectLoading(false); setError(messageOf(reason)); } });
    return () => controller.abort();
  }, [location.projectId]);
  const applyProject = useCallback((value: Project) => {
    setProject(current => !current || current.id === value.id && current.version <= value.version ? value : current);
    setProjects(current => current.some(item => item.id === value.id) ? current.map(item => item.id === value.id ? value : item) : [value, ...current]);
    setUpdatedAt(new Date().toLocaleTimeString('zh-CN'));
  }, []);
  const refreshProject = useCallback(async (background = false) => {
    if (!location.projectId || mutationLock.current) return;
    projectRequest.current?.abort(); const controller = new AbortController(); projectRequest.current = controller;
    if (!background) setRefreshing(true);
    try {
      const value = await rdProject(location.projectId, controller.signal);
      if (!controller.signal.aborted) { applyProject(value); setError(''); setConflict(false); if (!background) setNotice('已刷新。未保存的填写继续保留。'); }
    } catch (reason) { if (!controller.signal.aborted) setError(`状态读取失败，当前显示上次结果。${messageOf(reason)}`); }
    finally { if (!controller.signal.aborted) setRefreshing(false); }
  }, [location.projectId, applyProject]);
  useEffect(() => {
    if (!hasActiveRun || dirty || busy || newDialog || location.view !== 'projects') return;
    const timer = window.setInterval(() => { void refreshProject(true); }, 2500);
    return () => window.clearInterval(timer);
  }, [hasActiveRun, dirty, busy, newDialog, location.view, refreshProject]);
  useEffect(() => () => projectRequest.current?.abort(), []);
  const runCommand = useCallback<CommandRunner>(async (command, data, success) => {
    if (!project || mutationLock.current) return false;
    const fingerprint = JSON.stringify([project.id, project.version, command, data]);
    if (mutationRetry.current.fingerprint !== fingerprint) mutationRetry.current = { fingerprint, key: makeRequestKey() };
    mutationLock.current = true; projectRequest.current?.abort(); setRefreshing(false); setBusy(true); setError(''); setConflict(false); setNotice('');
    try {
      const value = await rdCommand(project, command, data, mutationRetry.current.key);
      mutationRetry.current = { fingerprint: '', key: '' }; applyProject(value); success?.();
      if (command === 'create_case') {
        const createdCase = value.cases.find(item => !project.cases.some(previous => previous.id === item.id));
        if (createdCase) navigate({ view: 'projects', projectId: value.id, caseId: createdCase.id });
      }
      setNotice('已保存。'); return true;
    } catch (reason) {
      setError(messageOf(reason)); setConflict(reason instanceof RdApiError && reason.status === 409);
      if (command === 'create_case') { setCreateUncertain(reason instanceof RdApiError && [0, 408].includes(reason.status)); setCreateConflict(reason instanceof RdApiError && reason.status === 409); }
      return false;
    }
    finally { mutationLock.current = false; setBusy(false); }
  }, [project, applyProject, navigate]);
  const upload = useCallback(async (caseId: string, file: File, role: string, success: () => void) => {
    if (!project || mutationLock.current) return;
    const fingerprint = JSON.stringify([project.id, caseId, project.version, file.name, file.size, file.lastModified, role]);
    if (mutationRetry.current.fingerprint !== fingerprint) mutationRetry.current = { fingerprint, key: makeRequestKey() };
    mutationLock.current = true; projectRequest.current?.abort(); setRefreshing(false); setBusy(true); setError(''); setNotice('');
    try { const value = await rdUpload(project, caseId, file, role, mutationRetry.current.key); applyProject(value); mutationRetry.current = { fingerprint: '', key: '' }; success(); setNotice('资料已上传并保存。'); }
    catch (reason) { setError(messageOf(reason)); setConflict(reason instanceof RdApiError && reason.status === 409); }
    finally { mutationLock.current = false; setBusy(false); }
  }, [project, applyProject]);
  const analyzeSources = useCallback(async (caseId: string) => {
    if (!project || mutationLock.current) return false;
    const fingerprint = JSON.stringify([project.id, caseId, project.version, 'analyze_sources']);
    if (mutationRetry.current.fingerprint !== fingerprint) mutationRetry.current = { fingerprint, key: makeRequestKey() };
    mutationLock.current = true; projectRequest.current?.abort(); setRefreshing(false); setBusy(true); setError(''); setConflict(false); setNotice('');
    try {
      const value = await rdAnalyzeSources(project, caseId, mutationRetry.current.key);
      mutationRetry.current = { fingerprint: '', key: '' }; applyProject(value);
      setNotice('资料分析已完成，请核对识别依据与原文需求后确认采用。'); return true;
    } catch (reason) {
      setError(messageOf(reason)); setConflict(reason instanceof RdApiError && reason.status === 409); return false;
    } finally { mutationLock.current = false; setBusy(false); }
  }, [project, applyProject]);
  async function create(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) { setCreateError('请填写名称。'); document.getElementById('rd-create-title')?.focus(); return; }
    if (!scenario || !catalog?.scenarios.some(item => item.id === scenario)) { setCreateError('请选择当前可用的业务场景。'); document.getElementById('rd-scenario-label')?.scrollIntoView({ block: 'center' }); return; }
    setCreateError('');
    if (newDialog === 'case') {
      const ok = await runCommand('create_case', { scenario_id: scenario, title: title.trim() }, () => { setNewDialog(null); setTitle(''); });
      if (!ok) setCreateError('业务流程尚未确认保存。填写内容已保留，请检查返回信息后重试。');
      return;
    }
    if (mutationLock.current) return;
    const profile = { brief: goal.trim(), customer_name: customerName.trim(), product_name: productName.trim() };
    const fingerprint = JSON.stringify([title.trim(), profile, scenario]);
    if (createRetry.current.fingerprint !== fingerprint) createRetry.current = { fingerprint, projectKey: makeRequestKey(), caseKey: makeRequestKey(), project: null };
    mutationLock.current = true; projectRequest.current?.abort(); setRefreshing(false); setBusy(true); setCreateError(''); setCreateConflict(false);
    try {
      let createdProject = createRetry.current.project;
      if (!createdProject) {
        createdProject = await rdCreate(title.trim(), {}, createRetry.current.projectKey, profile);
        createRetry.current.project = createdProject; setCreateProgress(createdProject); applyProject(createdProject);
      }
      const value = await rdCommand(createdProject, 'create_case', { scenario_id: scenario, title: title.trim() }, createRetry.current.caseKey);
      const createdCase = value.cases.find(item => !createdProject.cases.some(previous => previous.id === item.id));
      applyProject(value);
      if (!createdCase) throw new Error('项目已保存，尚未取得新业务流程的回执。请重试核对。');
      createRetry.current = { fingerprint: '', projectKey: '', caseKey: '', project: null };
      setCreateProgress(null); setNewDialog(null); setTitle(''); setHomeGoal(''); setGoal('');
      navigate({ view: 'projects', projectId: value.id, caseId: createdCase.id }); setNotice('项目与业务流程已建立，可以开始办理。');
    }
    catch (reason) { setCreateError(messageOf(reason)); setCreateUncertain(reason instanceof RdApiError && [0, 408].includes(reason.status)); setCreateConflict(reason instanceof RdApiError && reason.status === 409 && !!createRetry.current.project); }
    finally { mutationLock.current = false; setBusy(false); }
  }
  async function reconcileCreation() {
    const saved = newDialog === 'case' ? project : createRetry.current.project;
    if (!saved || mutationLock.current) return;
    mutationLock.current = true; setBusy(true);
    try {
      const value = await rdProject(saved.id);
      if (newDialog === 'case') mutationRetry.current = { fingerprint: '', key: '' };
      else { createRetry.current.project = value; createRetry.current.caseKey = makeRequestKey(); setCreateProgress(value); }
      applyProject(value); setCreateError(''); setError(''); setConflict(false); setCreateConflict(false); setCreateUncertain(false);
    } catch (reason) { setCreateError(messageOf(reason)); }
    finally { mutationLock.current = false; setBusy(false); }
  }
  function closeCreate() { if (busy) return; if (createDirty || createUncertain) setDiscardCreate(true); else setNewDialog(null); }
  function discardCreation() {
    const saved = createRetry.current.project;
    const unknownCase = newDialog === 'case' && createUncertain;
    focusUpload.current = false; setTitle(''); setGoal(''); setCustomerName(''); setProductName('');
    setNewDialog(null); setDiscardCreate(false); setCreateProgress(null);
    if (saved) navigate({ view: 'projects', projectId: saved.id, caseId: '' });
    else if (unknownCase) void refreshProject();
    else if (createUncertain) setRevision(value => value + 1);
  }
  const filtered = useMemo(() => projects.filter(item => `${item.title} ${item.customer_name ?? ''} ${item.product_name ?? ''} ${item.brief ?? ''} ${item.cases.map(researchCase => researchCase.title).join(' ')}`.toLocaleLowerCase().includes(location.q.toLocaleLowerCase())), [projects, location.q]);
  const page = Math.min(location.page, Math.max(1, Math.ceil(filtered.length / PROJECT_PAGE_SIZE)));
  const pageItems = filtered.slice((page - 1) * PROJECT_PAGE_SIZE, page * PROJECT_PAGE_SIZE);
  const commitQuery = (value: string) => navigate({ q: value, page: 1 }, true);
  const legacyNavigation = (event: MouseEvent<HTMLAnchorElement>, href: string) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || !dirty && !createDirty && !busy && !workspaceBusy) return;
    event.preventDefault(); requestNavigation(() => { setDirty(false); setProject(null); setLocation(current => ({ ...current, view: 'projects', projectId: '', caseId: '' })); window.setTimeout(() => window.location.assign(href), 0); });
  };
  const openProject = (projectId: string, caseId = '', target: CaseWorkspaceView = 'current') => requestNavigation(() => { navigate({ view: 'projects', projectId, caseId }); setCaseView(target); });
  const openView = (view: View) => requestNavigation(() => navigate({ view, projectId: '', caseId: '' }));
  const startCaseCreation = () => requestNavigation(() => { if (project) navigate({ view: 'projects', projectId: project.id, caseId: '' }); beginCreate('case'); });
  const scenarioTitle = (id: string) => { const item = catalog?.scenarios.find(entry => entry.id === id); return item?.title ?? item?.name ?? '业务流程'; };
  const creationLocked = busy || !!createProgress || createUncertain;

  return <div className={`rd-shell rd-platform-shell rd-application-shell${sidebarCollapsed ? ' is-sidebar-collapsed' : ''}`}><aside className="rd-sidebar">
    <div className="rd-brand-row"><a className="rd-brand" href="/rd" aria-label="研发管理平台首页" onClick={event => { event.preventDefault(); openView('home'); }}><img src="/assets/jonhon-logo.png" alt="JONHON" /></a><button type="button" className="rd-sidebar-toggle" onClick={() => setSidebarCollapsed(value => !value)} aria-label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'} title={sidebarCollapsed ? '展开侧栏' : '收起侧栏'} aria-expanded={!sidebarCollapsed}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d={sidebarCollapsed ? 'm9 6 6 6-6 6' : 'm15 6-6 6 6 6'} /></svg></button></div>
    <div className="rd-sidebar-navigation">
    <nav aria-label="研发平台导航">
      {(['home', 'projects', ...MANAGEMENT_VIEWS.filter(view => view !== 'system'), 'workspace'] as View[]).map(view => <button key={view} type="button" disabled={busy || workspaceBusy} title={VIEW_TITLES[view]} aria-label={VIEW_TITLES[view]} className={location.view === view ? 'active' : ''} aria-current={location.view === view ? 'page' : undefined} onClick={() => openView(view)}><RdNavigationIcon name={view} /><span className="rd-nav-label">{VIEW_TITLES[view]}</span></button>)}
    </nav>
    {location.view === 'projects' && <section className="rd-sidebar-case" aria-labelledby="rd-sidebar-case-label">
      <p id="rd-sidebar-case-label" className="rd-sidebar-case-label">{project?.title ?? '项目工作面'}</p>
      {selectedCase ? <><strong className="rd-sidebar-case-name">{selectedCase.title}</strong><nav aria-label="当前业务流程视图">
        {([{ id: 'current', title: '当前成果' }, { id: 'process', title: '项目流程' }, { id: 'evidence', title: '资料与画像' }] as const).map(item => <button key={item.id} type="button" className={caseView === item.id ? 'active' : ''} aria-current={caseView === item.id ? 'page' : undefined} aria-controls="rd-case-workarea" onClick={() => { setCaseView(item.id); if (item.id === 'current') setSurfaceRequest({ target: 'current', serial: ++surfaceSerial.current, caseId: selectedCase.id }); }}>{item.title}</button>)}
      </nav></> : <p className="rd-sidebar-case-hint">先选择项目和业务流程</p>}
    </section>}
    </div>
    <RdAccountDock onExpand={() => setSidebarCollapsed(false)} onOpenSettings={() => openView('system')} settingsActive={location.view === 'system'} settingsDisabled={busy || workspaceBusy} />
  </aside>
    <div className="rd-main"><header className="rd-topbar"><div className="rd-platform-heading"><strong>研发管理平台</strong><span>{location.view === 'projects' ? project?.title ?? VIEW_TITLES.projects : VIEW_TITLES[location.view]}</span></div><div className="rd-topbar-help"><a href="/help/manual" onClick={event => legacyNavigation(event, '/help/manual')} title="操作手册" aria-label="操作手册"><RdNavigationIcon name="knowledge" /></a><a href="/help/video" onClick={event => legacyNavigation(event, '/help/video')} title="操作视频" aria-label="操作视频"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9 5 3-5 3V9Z"/></svg></a></div></header>
      {location.view === 'workspace' ? <WorkspacePanel catalog={catalog} onDirtyChange={setChildDirty} onBusyChange={setWorkspaceBusy} /> : <main className="rd-page-content">
        {catalogError && location.view !== 'flows' && <p className="rd-warning rd-banner" role="alert">业务目录读取失败：{catalogError} <button className="rd-link-button" onClick={() => setCatalogRevision(value => value + 1)}>重新读取</button></p>}
        {error && <div className="rd-error rd-banner" role="alert"><p>{error}</p>{conflict && <p>项目版本已变化。当前填写保留；读取最新版本并核对后再保存。</p>}{location.projectId && <button className="rd-button" disabled={busy || refreshing} onClick={() => void refreshProject()}>读取最新版本</button>}</div>}
        {notice && <p className="rd-notice rd-banner" role="status">{notice}</p>}
        {location.view === 'home' ? <PlatformHome goal={homeGoal} onGoalChange={setHomeGoal} onStart={() => beginCreate('project')} projects={projects} catalog={catalog} loading={listLoading} error={listError} onRefresh={() => setRevision(value => value + 1)} onOpenProject={id => openProject(id)} onOpenCase={(pid, cid) => openProject(pid, cid)} onOpenProjects={() => openView('projects')} /> : MANAGEMENT_VIEWS.includes(location.view) ? <PlatformManagement view={location.view} projects={projects} catalog={catalog} loading={listLoading} error={listError} onRefresh={() => setRevision(value => value + 1)} catalogLoading={catalogLoading} catalogError={catalogError} onRefreshCatalog={() => setCatalogRevision(value => value + 1)} onOpenCase={(pid, cid, target) => openProject(pid, cid, target)} onOpenWorkspace={() => openView('workspace')} /> : !location.projectId ? <>
          <div className="rd-page-title"><div><h1>项目空间</h1><p>按项目查看目标、业务流程与当前成果。</p></div><button type="button" className="rd-button primary" disabled={busy || !catalog?.scenarios.length} onClick={() => beginCreate('project')}>新建项目</button></div>
          <div className="rd-list-toolbar"><form noValidate role="search" onSubmit={event => { event.preventDefault(); if (!composition.current) commitQuery(query); }}><label className="rd-visually-hidden" htmlFor="rd-project-search">搜索项目、客户、产品或业务流程</label><div className="rd-search"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg><input ref={queryRef} id="rd-project-search" value={query} placeholder="查找项目、客户或产品" onCompositionStart={() => { composition.current = true; }} onCompositionEnd={event => { composition.current = false; commitQuery(event.currentTarget.value); }} onChange={event => { setQuery(event.target.value); if (!composition.current) commitQuery(event.target.value); }} />{query && <button type="button" aria-label="清空项目搜索" onClick={() => { setQuery(''); commitQuery(''); queryRef.current?.focus(); }}>×</button>}</div></form><span className="rd-muted">{filtered.length} 个项目</span><button type="button" className="rd-link-button" disabled={listLoading} onClick={() => setRevision(value => value + 1)}>{listLoading ? '读取中…' : '刷新'}</button></div>
          {listError && <p className="rd-error rd-banner" role="alert">{listError} <button className="rd-link-button" onClick={() => setRevision(value => value + 1)}>重新读取</button></p>}{listLoading && <p className="rd-loading" role="status">正在读取项目…</p>}
          {!listLoading && !listError && !filtered.length && <div className="rd-platform-empty"><h2>{location.q ? '没有找到匹配的项目' : '还没有项目'}</h2><p>{location.q ? '试试其他名称，或清空搜索查看全部项目。' : '发起项目工作，选择业务场景后开始办理。'}</p>{location.q && <button type="button" className="rd-link-button" onClick={() => { setQuery(''); commitQuery(''); }}>清空搜索</button>}</div>}
          <div className="rd-project-entries">{pageItems.map(item => <article className="rd-project-entry rd-platform-project" key={item.id}>
            <header><div><h3><button type="button" onClick={() => openProject(item.id)}>{item.title}</button></h3>{(item.customer_name || item.product_name) && <p className="rd-project-profile-line">{[item.customer_name, item.product_name].filter(Boolean).join(' · ')}</p>}{item.brief && <p className="rd-project-goal-preview">{item.brief}</p>}</div><button type="button" className="rd-link-button" onClick={() => openProject(item.id)}>查看项目 <span aria-hidden="true">↗</span></button></header>
            {item.cases.length ? <div className="rd-project-cases">{item.cases.slice(0, 2).map(researchCase => {
              const needsAttention = researchCase.workpackages.some(workpackage => ['blocked', 'failed'].includes(workpackage.status));
              return <button type="button" className="rd-project-continue" key={researchCase.id} onClick={() => openProject(item.id, researchCase.id)}><div><strong>{researchCase.title}</strong><small>{scenarioTitle(researchCase.scenario_id)} · {researchCase.status === 'completed' ? '已完成' : stageTitle(researchCase.stage)}{needsAttention && <span className="rd-attention-text"> · 执行需处理</span>}</small></div><span>{researchCase.status === 'completed' ? '查看成果' : '继续办理'} <span aria-hidden="true">→</span></span></button>;
            })}</div> : <div className="rd-project-no-cases"><p>尚未建立业务流程</p><button type="button" className="rd-link-button" onClick={() => openProject(item.id)}>进入项目选择场景</button></div>}
            {item.cases.length > 2 && <button type="button" className="rd-link-button rd-project-show-all" onClick={() => openProject(item.id)}>查看全部 {item.cases.length} 个流程</button>}
          </article>)}</div>
          {!!filtered.length && <div className="rd-pagination"><span>显示 {(page - 1) * PROJECT_PAGE_SIZE + 1}–{Math.min(page * PROJECT_PAGE_SIZE, filtered.length)} / {filtered.length} 个项目</span><div><button className="rd-button" disabled={page <= 1} onClick={() => navigate({ page: page - 1 })}>上一页</button><span>第 {page} / {Math.max(1, Math.ceil(filtered.length / PROJECT_PAGE_SIZE))} 页</span><button className="rd-button" disabled={page * PROJECT_PAGE_SIZE >= filtered.length} onClick={() => navigate({ page: page + 1 })}>下一页</button></div></div>}
        </> : projectLoading ? <p className="rd-loading" role="status">正在打开项目…</p> : project ? <>
          <div className="rd-project-header"><div><nav className="rd-breadcrumb" aria-label="当前位置"><button type="button" className="rd-link-button" onClick={() => openView('projects')}>项目空间</button><span>/</span>{selectedCase ? <button type="button" className="rd-link-button" onClick={() => openProject(project.id)}>{project.title}</button> : <span>{project.title}</span>}</nav>{!selectedCase && <h1>{project.title}</h1>}{dirty && <p className="rd-unsaved-state">有未保存的填写{hasActiveRun ? ' · 自动刷新已暂停' : ''}</p>}</div><div className="rd-project-tools"><button type="button" className="rd-link-button" disabled={busy || refreshing} onClick={() => void refreshProject()}>{refreshing ? '刷新中…' : '刷新'}</button>{!selectedCase && <button type="button" className="rd-button primary" disabled={busy || !catalog?.scenarios.length} onClick={startCaseCreation}>新增业务流程</button>}<details className="rd-project-options"><summary>项目记录</summary><div><dl><dt>项目编号</dt><dd><code>{project.id}</code></dd><dt>项目负责人</dt><dd>{project.owner_id}</dd><dt>记录版本</dt><dd>{project.version}</dd><dt>最近刷新</dt><dd>{updatedAt || '—'}</dd></dl>{selectedCase && <button type="button" className="rd-button" disabled={busy || !catalog?.scenarios.length} onClick={startCaseCreation}>新增业务流程</button>}</div></details></div></div>
          <div className="rd-project-business-context"><dl><div><dt>客户</dt><dd>{project.customer_name || '未填写'}</dd></div><div><dt>产品</dt><dd>{project.product_name || '未填写'}</dd></div><div className="rd-project-goal"><dt>研发目标</dt><dd>{project.brief || '未填写'}</dd></div></dl>{selectedCase && <span className="rd-scenario-label">{scenarioTitle(selectedCase.scenario_id)}</span>}</div>
          {selectedCase ? <CaseWorkspace key={selectedCase.id} project={project} researchCase={selectedCase} catalog={catalog} busy={busy} error={error} view={caseView} surfaceRequest={surfaceRequest?.caseId === selectedCase.id ? surfaceRequest : undefined} onViewChange={setCaseView} onCommand={runCommand} onAnalyze={analyzeSources} onUpload={upload} onDirtyChange={setChildDirty} onBusyChange={setWorkspaceBusy} /> : <><div className="rd-project-cases-heading"><h2>业务流程</h2><p>选择流程实例，查看当前成果与办理进展。</p></div>{location.caseId && <p className="rd-warning">未找到指定流程。请选择下方可访问的流程实例。</p>}{!project.cases.length && <div className="rd-platform-empty"><h3>选择业务场景开始</h3><p>新增业务流程后，将在项目中保留输入、成果与过程记录。</p></div>}<div className="rd-case-grid">{project.cases.map(researchCase => <article key={researchCase.id} className="rd-case-card"><p className="rd-scenario-label">{scenarioTitle(researchCase.scenario_id)}</p><h2>{researchCase.title}</h2><span className={`rd-badge ${researchCase.status === 'completed' ? 'completed' : 'running'}`}>{researchCase.status === 'completed' ? '已完成' : stageTitle(researchCase.stage)}</span><div className="rd-case-counts"><span>{researchCase.sources.length} 份资料</span><span>{researchCase.requirements.length} 条需求</span></div><button type="button" className="rd-button" onClick={() => openProject(project.id, researchCase.id)}>{researchCase.status === 'completed' ? '查看成果' : '继续办理'} <span aria-hidden="true">→</span></button></article>)}</div></>}
        </> : !error && <div className="rd-empty"><h2>项目尚未读取</h2><button className="rd-button" onClick={() => void refreshProject()}>重新读取</button></div>}
      </main>}
    </div>
    {!selectedCase && <FloatingAssistant project={location.view === 'projects' ? project ?? undefined : undefined} onStartTask={startFromUpload} onOpenProjects={() => openView('projects')} />}
    {newDialog && <FeedbackDialog title={newDialog === 'project' ? '新建项目' : '新增业务流程'} className="rd-create-dialog rd-platform-create" onCancel={closeCreate}><form noValidate onSubmit={event => void create(event)}>
      <p className="rd-muted">{newDialog === 'project' ? '明确项目目标，选择本次要开展的业务场景。' : '为当前项目建立一个独立办理的流程实例。'}</p>
      <div className="rd-field"><label htmlFor="rd-create-title">{newDialog === 'project' ? '项目名称' : '流程名称'} <span className="rd-required">必填</span></label><input id="rd-create-title" maxLength={200} value={title} onChange={event => setTitle(event.target.value)} disabled={creationLocked} aria-invalid={!!createError && !title.trim()} aria-describedby={createError ? 'rd-create-error' : undefined} placeholder={newDialog === 'project' ? '填写项目名称' : '填写本次工作的名称'} /></div>
      {newDialog === 'project' && <><div className="rd-field"><label htmlFor="rd-create-goal">研发目标 <span className="rd-optional">选填</span></label><textarea id="rd-create-goal" className="resize-none" rows={3} maxLength={4000} value={goal} onChange={event => setGoal(event.target.value)} disabled={creationLocked} placeholder="希望解决什么问题，交付什么成果" /></div><div className="rd-create-profile-grid"><div className="rd-field"><label htmlFor="rd-create-customer">客户名称 <span className="rd-optional">选填</span></label><input id="rd-create-customer" maxLength={200} value={customerName} onChange={event => setCustomerName(event.target.value)} disabled={creationLocked} /></div><div className="rd-field"><label htmlFor="rd-create-product">产品名称 <span className="rd-optional">选填</span></label><input id="rd-create-product" maxLength={200} value={productName} onChange={event => setProductName(event.target.value)} disabled={creationLocked} /></div></div></>}
      <div className="rd-field"><label id="rd-scenario-label">业务场景 <span className="rd-required">必填</span></label><StyledSelect aria-labelledby="rd-scenario-label" value={scenario} onChange={setScenario} disabled={creationLocked} placeholder="选择可用场景" options={(catalog?.scenarios ?? []).map(item => ({ value: item.id, label: item.title ?? item.name ?? item.id }))} />{!catalog?.scenarios.length && <p className="rd-warning">尚未取得可用场景，请关闭后重新读取业务目录。</p>}</div>
      {createProgress && <p className="rd-notice" role="status">项目“{createProgress.title}”已保存，正在建立业务流程。重试会继续此项目。</p>}
      {createError && <p id="rd-create-error" className="rd-error" role="alert">{newDialog === 'case' && error ? error : createError}</p>}{createConflict && <p className="rd-warning">项目记录已变化。<button type="button" className="rd-link-button" disabled={busy} onClick={() => void reconcileCreation()}>读取项目后继续</button></p>}{createUncertain && <p className="rd-warning">服务端结果尚未确认。可用下方按钮重试同一次请求；请勿重复创建。</p>}
      <div className="rd-actions"><button type="button" className="rd-button" disabled={busy} onClick={closeCreate}>{createProgress ? '稍后继续' : '取消'}</button><button type="submit" className="rd-button primary" disabled={busy || createConflict || !catalog?.scenarios.length}>{busy ? createProgress ? '正在建立流程…' : '正在创建…' : createProgress ? '继续建立流程' : createUncertain ? '重试并核对' : '创建并开始'}</button></div>
    </form></FeedbackDialog>}
    {pendingNavigation && <FeedbackConfirmDialog title="离开前保存填写" confirm="放弃填写并切换" cancel="继续编辑" onCancel={() => setPendingNavigation(null)} onConfirm={() => { const next = pendingNavigation; setPendingNavigation(null); setDirty(false); setNewDialog(null); next(); }}><p>当前有未保存的输入、文件选择或计划修改。切换后这些填写会丢失，已保存的项目记录继续保留。</p></FeedbackConfirmDialog>}
    {discardCreate && <FeedbackConfirmDialog title={createProgress ? '稍后建立业务流程' : '关闭当前创建'} confirm={createProgress ? '进入已保存项目' : '关闭创建'} cancel="继续填写" onCancel={() => setDiscardCreate(false)} onConfirm={discardCreation}><p>{createProgress ? '项目已保存。尚未确认建立的业务流程可在项目空间继续添加，项目记录会保留。' : createUncertain ? '请求结果尚未确认。关闭后将重新读取项目核对；首页目标草稿会保留。' : '当前填写尚未保存。首页目标草稿会保留，已保存记录不受影响。'}</p></FeedbackConfirmDialog>}
  </div>;
}

export default RdPlatformPage;
