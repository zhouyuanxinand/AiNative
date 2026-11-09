import { Button, message } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type MouseEvent } from 'react';
import { FeedbackConfirmDialog, FeedbackDialog } from '../../components/feedback/FeedbackDialog';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { loadProductCatalog } from '../../api/catalog';
import type { ProductCatalog } from '../../types';
import { useApplicationLeaveGuard, applicationLeaveState } from '../../hooks/useApplicationLeaveGuard';
import { useCurrentUser } from '../../hooks/useCurrentUser';
import { RdAccountDock } from './RdAccountDock';
import { useSidebarResize } from './useSidebarResize';
import { RdNavigationIcon } from './RdNavigationIcon';
import { CaseWorkspace } from './CaseWorkspace';
import { backwardCaseStep } from './backwardCaseStep';
import { ProjectCaseCard } from './ProjectCaseCard';
import { ProjectOverviewCard } from './ProjectOverviewCard';
import { ProjectDirectoryTable, selectDirectoryProjects } from './ProjectDirectory';
import { VIEW_TITLES, HISTORY_INDEX, DIRECTORY_HISTORY, captureDirectoryHistory, ensureHistoryIndex, platformLocationUrl, readPlatformLocation, sameCaseWorkspace, type PlatformView, type CasePage, type DirectorySnapshots } from './platformNavigation';
import type { CaseSurface } from './scenarioManifest';
import { ProjectDeleteButton } from './ProjectDeleteButton';
import { ProjectDeleteDialog } from './ProjectDeleteDialog';
import { ProjectEditDialog } from './ProjectEditDialog';
import { FloatingAssistant } from './FloatingAssistant';
import { PlatformHome } from './PlatformHome';
import { PlatformManagement } from './PlatformManagement';
import { RD_AUTH_REQUIRED_EVENT, RdApiError, makeRequestKey, rdAnalyzeSources, rdCatalog, rdCommand, rdCreate, rdProject, rdProjects, rdUpload, rdUploadBatch } from './api';
import { messageOf } from './presentation';
import type { BusinessWorkflowTemplate, CaseWorkspaceView, Catalog, Project, SourceAnalysisRunner, SourceBatchRunner } from './types';
import { WorkspacePanel } from './WorkspacePanel';
import type { CommandRunner } from './WorkpackagePanel';
import '../../feedback.css';
import './rd.css';
import './caseWorkspace.css';
import './rdExperience.css';
import './platformHome.css';
import './rdApplicationShell.css';
import './sourcePageLayout.css';
import './projectCreateDialog.css';

type View = PlatformView;
const MANAGEMENT_VIEWS: View[] = ['management', 'flows', 'knowledge', 'operations', 'system'];
const PROJECT_PAGE_SIZE = 5;
const CLASSIFICATION_REQUIRED = '请选择产品类型和质量管理体系分类。';
function readLocation() {
  return readPlatformLocation(window.location.href);
}

export function RdPlatformPage() {
  const { requireLogin } = useCurrentUser();
  useEffect(() => {
    window.addEventListener(RD_AUTH_REQUIRED_EVENT, requireLogin);
    return () => window.removeEventListener(RD_AUTH_REQUIRED_EVENT, requireLogin);
  }, [requireLogin]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const sidebarResize = useSidebarResize(sidebarCollapsed);
  const pageTopRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const [canScrollToTop, setCanScrollToTop] = useState(false);
  const [location, setLocation] = useState(readLocation);
  useEffect(() => {
    const shell = sidebarResize.shellRef.current;
    const main = mainRef.current;
    if (!shell || !main) return;
    const measure = () => setCanScrollToTop(shell.scrollHeight > shell.clientHeight + 1);
    const observer = new ResizeObserver(measure);
    observer.observe(shell);
    observer.observe(main);
    // The grid can keep main at viewport height while its children overflow.
    for (const child of main.children) observer.observe(child);
    // On mobile, the navigation is in normal flow above the main content.
    const sidebar = shell.querySelector(':scope > .rd-sidebar');
    if (sidebar) observer.observe(sidebar);
    measure();
    return () => observer.disconnect();
  }, [sidebarResize.shellRef, location.view]);
  function scrollToTop() {
    pageTopRef.current?.focus({ preventScroll: true });
    sidebarResize.shellRef.current?.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  }
  const caseView = location.caseView;
  const historyIndex = useRef(ensureHistoryIndex(window.history));
  const restoringHistory = useRef<(() => void) | null>(null);
  const approvedHistory = useRef<number | null>(null);
  const scrollPositions = useRef(new Map<number, number>());
  const pendingScroll = useRef<number | null>(null);
  const [surfaceRequest, setSurfaceRequest] = useState<{ target: 'current' | 'sources' | 'resume'; serial: number; caseId: string }>();
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
  const [messageApi, messageContextHolder] = message.useMessage();
  const setNotice = useCallback((value: string) => {
    if (value) void messageApi.open({ key: 'rd-operation-notice', type: 'info', content: <span role="status">{value}</span>, duration: 3 });
    else messageApi.destroy('rd-operation-notice');
  }, [messageApi]);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [revision, setRevision] = useState(0);
  const [catalogRevision, setCatalogRevision] = useState(0);
  const [newDialog, setNewDialog] = useState<'project' | 'case' | null>(null);
  const [title, setTitle] = useState('');
  const [workflowKey, setWorkflowKey] = useState('');
  const [preferredWorkflow, setPreferredWorkflow] = useState<BusinessWorkflowTemplate | null>(null);
  const [goal, setGoal] = useState('');
  const [customerName, setCustomerName] = useState('');
  const [productName, setProductName] = useState('');
  const [productType, setProductType] = useState('');
  const [productDomain, setProductDomain] = useState('');
  const [coverPhase, setCoverPhase] = useState('F');
  const [organizationScope, setOrganizationScope] = useState('non_central_research');
  const [productCatalog, setProductCatalog] = useState<ProductCatalog | null>(null);
  const [productCatalogLoading, setProductCatalogLoading] = useState(false);
  const [productCatalogError, setProductCatalogError] = useState('');
  const [productCatalogRevision, setProductCatalogRevision] = useState(0);
  const [createProgress, setCreateProgress] = useState<Project | null>(null);
  const [createError, setCreateError] = useState('');
  const [createUncertain, setCreateUncertain] = useState(false);
  const [createConflict, setCreateConflict] = useState(false);
  const [discardCreate, setDiscardCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);
  const [editTarget, setEditTarget] = useState<Project | null>(null);
  const [pendingNavigation, setPendingNavigation] = useState<(() => void) | null>(null);
  const [pendingStepNavigation, setPendingStepNavigation] = useState<{ title: string; proceed: () => void } | null>(null);
  const [query, setQuery] = useState(location.q);
  const [updatedAt, setUpdatedAt] = useState('');
  const mutationLock = useRef(false);
  const mutationRetry = useRef({ fingerprint: '', key: '' });
  const createRetry = useRef({ fingerprint: '', projectKey: '', caseKey: '', project: null as Project | null });
  const projectRequest = useRef<AbortController>();
  const previousView = useRef(location.view);
  const queryRef = useRef<HTMLInputElement>(null);
  const composition = useRef(false);
  const focusUpload = useRef(false);
  const setChildDirty = useCallback((value: boolean) => setDirty(value), []);
  const selectedCase = location.view === 'projects' && project?.id === location.projectId ? project.cases.find(item => item.id === location.caseId) : undefined;
  const navigationContext = useRef({ selectedCase, busy, workspaceBusy });
  navigationContext.current = { selectedCase, busy, workspaceBusy };
  const lastCaseEditor = useRef<{ caseId: string; page: CasePage }>();
  useEffect(() => {
    if (!selectedCase) lastCaseEditor.current = undefined;
    else if (location.caseView === 'current' && location.surface && location.surface !== 'current') {
      lastCaseEditor.current = { caseId: selectedCase.id, page: location };
    }
    setPendingStepNavigation(null);
    setPendingNavigation(null);
  }, [location, selectedCase?.id]);
  const earlierStep = useCallback((before: ReturnType<typeof readLocation>, after: ReturnType<typeof readLocation>) => {
    const value = navigationContext.current.selectedCase;
    if (!value || value.id !== before.caseId || !sameCaseWorkspace(before, after)) return null;
    const previousEditor = before.caseView === 'current' && before.surface && before.surface !== 'current'
      ? before : lastCaseEditor.current?.caseId === value.id ? lastCaseEditor.current.page : before;
    return backwardCaseStep(previousEditor, after, value);
  }, []);
  const sidebarFlowTitle = selectedCase?.title.trim() === project?.title.trim()
    ? [selectedCase?.workflow_templates?.project?.title, catalog?.scenarios.find(item => item.id === selectedCase?.scenario_id)?.title, '当前业务流程'].find(title => title?.trim() && title.trim() !== project?.title.trim())
    : selectedCase?.title;
  const hasActiveRun = project?.cases.some(item => item.workpackages.some(workpackage => ['submitted', 'running'].includes(workpackage.status)));
  const creationLocked = busy || !!createProgress || createUncertain;
  const selectedProduct = productCatalog?.product_types.find(item => item.value === productType);
  const productDomains = selectedProduct?.domains ?? [];
  const workflowChoices = (catalog?.project_workflow_templates ?? []).filter(item => item.status === 'published');
  const creationWorkflows = preferredWorkflow
    ? [preferredWorkflow, ...workflowChoices.filter(item => item.id !== preferredWorkflow.id || item.version !== preferredWorkflow.version)] : workflowChoices;
  const creationWorkflow = creationWorkflows.find(item => `${item.id}@${item.version}` === workflowKey);
  const canChooseWorkflow = !catalogLoading && !catalogError && creationWorkflows.length > 0;
  const refreshCatalog = useCallback(() => {
    if (mutationLock.current || newDialog && (creationLocked || createConflict)) return;
    setCatalogLoading(true); setCatalogRevision(value => value + 1);
  }, [newDialog, creationLocked, createConflict]);
  function chooseWorkflow(key: string) {
    setWorkflowKey(key);
    setPreferredWorkflow(creationWorkflows.find(item => `${item.id}@${item.version}` === key) ?? null);
  }
  function beginCreate(kind: 'project' | 'case', fromUpload = false, workflow?: BusinessWorkflowTemplate) {
    focusUpload.current = fromUpload;
    setTitle(''); setGoal(''); setCustomerName(''); setProductName('');
    setProductType(''); setProductDomain('');
    setCoverPhase('F'); setOrganizationScope('non_central_research');
    setPreferredWorkflow(workflow ?? null);
    setWorkflowKey(workflow ? `${workflow.id}@${workflow.version}` : ''); setCreateError(''); setCreateUncertain(false); setCreateConflict(false); setCreateProgress(null);
    createRetry.current = { fingerprint: '', projectKey: '', caseKey: '', project: null };
    setCatalogLoading(true); setCatalogRevision(value => value + 1);
    setNewDialog(kind);
  }
  useEffect(() => {
    if (newDialog !== 'project') return;
    let active = true;
    setProductCatalogLoading(true); setProductCatalogError('');
    void loadProductCatalog().then(value => {
      if (active) setProductCatalog(value);
    }).catch(reason => {
      if (active) { setProductCatalog(null); setProductCatalogError(messageOf(reason)); }
    }).finally(() => { if (active) setProductCatalogLoading(false); });
    return () => { active = false; };
  }, [newDialog, productCatalogRevision]);
  function chooseProductType(value: string) {
    setProductType(value);
    if (createError === CLASSIFICATION_REQUIRED) setCreateError('');
    const domains = productCatalog?.product_types.find(item => item.value === value)?.domains ?? [];
    if (!domains.some(item => item.value === productDomain)) setProductDomain('');
  }
  function chooseProductDomain(value: string) {
    setProductDomain(value);
    if (createError === CLASSIFICATION_REQUIRED) setCreateError('');
  }
  useEffect(() => {
    if (newDialog && !creationLocked && !catalogLoading && !catalogError && !workflowKey && workflowChoices[0]) {
      setWorkflowKey(`${workflowChoices[0].id}@${workflowChoices[0].version}`);
      setPreferredWorkflow(workflowChoices[0]);
    }
  }, [newDialog, workflowKey, catalog, catalogLoading, catalogError, creationLocked]);
  useEffect(() => {
    const returnedFromFlows = previousView.current === 'flows' && location.view !== 'flows';
    previousView.current = location.view;
    if (returnedFromFlows) refreshCatalog();
  }, [location.view, refreshCatalog]);
  useEffect(() => {
    if (!newDialog || creationLocked || createConflict) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refreshOnReturn = () => {
      if (document.visibilityState !== 'visible') return;
      if (timer) clearTimeout(timer);
      // Returning from a template tab can emit both events. Read the directory once.
      timer = setTimeout(() => { if (document.visibilityState === 'visible') refreshCatalog(); }, 100);
    };
    window.addEventListener('focus', refreshOnReturn);
    document.addEventListener('visibilitychange', refreshOnReturn);
    return () => { if (timer) clearTimeout(timer); window.removeEventListener('focus', refreshOnReturn); document.removeEventListener('visibilitychange', refreshOnReturn); };
  }, [newDialog, creationLocked, createConflict, refreshCatalog]);
  function startFromUpload() { requestNavigation(() => beginCreate('project', true)); }
  useEffect(() => {
    if (!focusUpload.current || !selectedCase) return;
    focusUpload.current = false;
    setSurfaceRequest({ target: 'sources', serial: ++surfaceSerial.current, caseId: selectedCase.id });
  }, [selectedCase]);
  const createDirty = !!newDialog && !!(title || goal || customerName || productName || productType || productDomain || coverPhase !== 'F' || organizationScope !== 'non_central_research' || createProgress);
  useApplicationLeaveGuard({ dirty: createDirty, busyMessage: busy ? '研发操作尚未完成，请等待结果后再离开。' : undefined });
  useEffect(() => {
    document.title = `${selectedCase?.title ?? (location.view === 'projects' ? project?.title ?? VIEW_TITLES.projects : VIEW_TITLES[location.view])} · AI Native研发管理平台`;
  }, [selectedCase?.title, project?.title, location.view]);

  const navigate = useCallback((next: Partial<ReturnType<typeof readLocation>>, replace = false, stepApproved = false): void => {
    const previous = readLocation();
    let merged = { ...previous, ...next };
    const internal = sameCaseWorkspace(previous, merged);
    const backward = !replace && !stepApproved ? earlierStep(previous, merged) : null;
    if (backward) {
      const current = navigationContext.current;
      if (current.busy || current.workspaceBusy || mutationLock.current || applicationLeaveState().busyMessage) {
        setNotice('当前操作尚未完成，请等待结果后再切换。'); return;
      }
      setPendingNavigation(null);
      setPendingStepNavigation({ title: backward.title, proceed: () => navigate(next, false, true) });
      return;
    }
    if (!internal) {
      merged = { ...merged, caseView: 'current', surface: undefined, evidence: undefined, workpackageId: undefined, ...next };
      setSurfaceRequest(undefined);
    }
    if (merged.view !== 'management') merged.researchTab = undefined;
    const navigationState = captureDirectoryHistory(window.location.href, window.history.state);
    const url = platformLocationUrl(window.location.href, merged, navigationState[DIRECTORY_HISTORY] as DirectorySnapshots);
    if (url.href === window.location.href) return;
    setEditTarget(null);
    scrollPositions.current.set(historyIndex.current, document.querySelector('.rd-application-shell')?.scrollTop ?? 0);
    if (!internal && !replace) pendingScroll.current = 0;
    if (!replace) historyIndex.current += 1;
    // Keep committed directory filters on both the entry being left and the next one.
    window.history.replaceState(navigationState, '');
    window.history[replace ? 'replaceState' : 'pushState']({ ...navigationState, [HISTORY_INDEX]: historyIndex.current }, '', url);
    const resolved = readLocation(); setLocation(resolved); setQuery(resolved.q);
    if (!internal) { setDirty(false); setError(''); setNotice(''); setConflict(false); }
  }, [setNotice, earlierStep]);
  useEffect(() => {
    const sync = () => setLocation(readLocation());
    window.addEventListener('rd:directory-location', sync);
    return () => window.removeEventListener('rd:directory-location', sync);
  }, []);
  const navigateCase = useCallback((page: CasePage, replace = false) => {
    navigate({ surface: undefined, evidence: undefined, workpackageId: undefined, ...page }, replace);
  }, [navigate]);
  const requestNavigation = (action: () => void) => {
    if (document.querySelector('.credentials-dialog[open]')) { setNotice('请先关闭设置窗口，再切换页面。'); return; }
    if (busy || workspaceBusy || mutationLock.current || applicationLeaveState().busyMessage) { setNotice('当前操作尚未完成，请等待结果后再切换。'); return; }
    setPendingStepNavigation(null);
    if (dirty || createDirty || applicationLeaveState().dirty) setPendingNavigation(() => action); else action();
  };
  useEffect(() => {
    const onPop = () => {
      if (restoringHistory.current) {
        const restored = restoringHistory.current;
        restoringHistory.current = null; restored(); return;
      }
      const next = readLocation();
      scrollPositions.current.set(historyIndex.current, document.querySelector('.rd-application-shell')?.scrollTop ?? 0);
      const targetIndex = window.history.state?.[HISTORY_INDEX];
      const approved = approvedHistory.current !== null && approvedHistory.current === targetIndex;
      approvedHistory.current = null;
      const settingsDialogOpen = !!document.querySelector('.credentials-dialog[open]');
      const locked = busy || workspaceBusy || mutationLock.current || !!applicationLeaveState().busyMessage;
      const internal = sameCaseWorkspace(location, next);
      const leavingDraft = createDirty || !internal && (dirty || applicationLeaveState().dirty);
      const backward = earlierStep(location, next);
      if (!approved && (settingsDialogOpen || locked || leavingDraft || backward)) {
        const delta = Number.isInteger(targetIndex) ? targetIndex - historyIndex.current : 0;
        const offerNavigation = () => {
          // A new browser intent supersedes an open in-page navigation question.
          setPendingStepNavigation(null); setPendingNavigation(null);
          if (settingsDialogOpen) setNotice('请先关闭设置窗口，再切换页面。');
          else if (locked) setNotice('操作尚未完成，请等待结果后再切换。');
          else {
            const proceed = () => {
              if (delta) { approvedHistory.current = targetIndex; window.history.go(delta); }
              else navigate(next, true);
            };
            if (backward && !leavingDraft) setPendingStepNavigation({ title: backward.title, proceed });
            else setPendingNavigation(() => proceed);
          }
        };
        if (delta) {
          // Restore the existing entry. Pushing here would erase the Forward branch.
          restoringHistory.current = offerNavigation;
          window.history.go(-delta);
        } else {
          window.history.replaceState({ ...window.history.state, [HISTORY_INDEX]: historyIndex.current }, '', platformLocationUrl(window.location.href, location));
          offerNavigation();
        }
        return;
      }
      historyIndex.current = ensureHistoryIndex(window.history);
      setEditTarget(null);
      if (!internal) { pendingScroll.current = scrollPositions.current.get(historyIndex.current) ?? 0; setSurfaceRequest(undefined); setDirty(false); setError(''); }
      setLocation(next); setQuery(next.q);
    };
    window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop);
  }, [dirty, createDirty, busy, workspaceBusy, location, navigate, setNotice, earlierStep]);
  useEffect(() => {
    if (pendingScroll.current === null || projectLoading || listLoading || location.projectId && project?.id !== location.projectId) return;
    // Editors focus their own work area; list/detail returns restore the saved scroll.
    if (location.caseId) { pendingScroll.current = null; return; }
    const top = pendingScroll.current;
    const frame = requestAnimationFrame(() => {
      document.querySelector('.rd-application-shell')?.scrollTo({ top, behavior: 'auto' });
      pendingScroll.current = null;
    });
    return () => cancelAnimationFrame(frame);
  }, [location, projectLoading, listLoading, project?.id]);
  useEffect(() => {
    const controller = new AbortController();
    setListLoading(true); setListError('');
    void rdProjects(controller.signal).then(response => {
      if (controller.signal.aborted) return;
      setProjects(current => {
        const known = new Map(current.map(item => [item.id, item]));
        // A list read started before an edit must not replace its newer save receipt.
        return response.projects.map(item => {
          const latest = known.get(item.id);
          return latest && latest.version > item.version ? latest : item;
        });
      });
      setListLoading(false);
    }).catch(reason => { if (!controller.signal.aborted) { setListError(messageOf(reason)); setListLoading(false); } });
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
    if (!hasActiveRun || dirty || busy || newDialog || editTarget || location.view !== 'projects') return;
    const timer = window.setInterval(() => { void refreshProject(true); }, 2500);
    return () => window.clearInterval(timer);
  }, [hasActiveRun, dirty, busy, newDialog, editTarget, location.view, refreshProject]);
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
      setNotice(command === 'recommend_requirements' ? '规范核对已完成，请逐项查看建议与证据。' : '已保存。'); return true;
    } catch (reason) {
      setError(messageOf(reason)); setConflict(reason instanceof RdApiError && reason.status === 409);
      if (reason instanceof RdApiError && [401,403].includes(reason.status)) { setProject(null); setProjects(current => current.filter(item => item.id !== project.id)); setDirty(false); mutationRetry.current = { fingerprint: '', key: '' }; }
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
  const uploadBatch = useCallback<SourceBatchRunner>(async (caseId, items, key, expectedVersion) => {
    if (!project || mutationLock.current) return { ok: false, message: '当前操作尚未完成，请稍后重试。' };
    mutationLock.current = true; projectRequest.current?.abort(); setRefreshing(false); setBusy(true); setError(''); setConflict(false); setNotice('');
    try {
      const value = await rdUploadBatch(project, caseId, items, key, expectedVersion);
      applyProject(value); setNotice(`${items.length} 份资料已上传。`);
      return { ok: true };
    } catch (reason) {
      const message = messageOf(reason);
      setConflict(reason instanceof RdApiError && reason.status === 409);
      if (reason instanceof RdApiError && [401, 403].includes(reason.status)) { setProject(null); setProjects(current => current.filter(item => item.id !== project.id)); setDirty(false); }
      return { ok: false, message, uncertain: reason instanceof RdApiError && (reason.status === 0 || reason.status === 408 || reason.status >= 500) };
    } finally { mutationLock.current = false; setBusy(false); }
  }, [project, applyProject]);
  const analyzeSources = useCallback<SourceAnalysisRunner>(async (caseId, modelChange) => {
    if (!project || mutationLock.current) return false;
    const researchCase = project.cases.find(item => item.id === caseId);
    if (!researchCase) return false;
    let analysisProject = project;
    let savingModel = !!modelChange;
    mutationLock.current = true; projectRequest.current?.abort(); setRefreshing(false); setBusy(true); setError(''); setConflict(false); setNotice('');
    try {
      if (modelChange) {
        const data = { case_id: caseId, context: researchCase.context, model_selection: modelChange.selection };
        const fingerprint = JSON.stringify([project.id, project.version, 'save_context', data]);
        if (mutationRetry.current.fingerprint !== fingerprint) mutationRetry.current = { fingerprint, key: makeRequestKey() };
        analysisProject = await rdCommand(project, 'save_context', data, mutationRetry.current.key);
        mutationRetry.current = { fingerprint: '', key: '' };
        applyProject(analysisProject);
        modelChange.onSaved();
        savingModel = false;
      }
      // Use the save response directly: this callback still closes over the pre-save project.
      const fingerprint = JSON.stringify([analysisProject.id, caseId, analysisProject.version, 'analyze_sources']);
      if (mutationRetry.current.fingerprint !== fingerprint) mutationRetry.current = { fingerprint, key: makeRequestKey() };
      const value = await rdAnalyzeSources(analysisProject, caseId, mutationRetry.current.key);
      mutationRetry.current = { fingerprint: '', key: '' }; applyProject(value);
      setNotice('资料分析已完成，请核对识别依据与原文需求后确认采用。'); return true;
    } catch (reason) {
      setError(savingModel ? '模型设置保存失败，尚未开始分析。' + messageOf(reason) : messageOf(reason));
      setConflict(reason instanceof RdApiError && reason.status === 409);
      if (reason instanceof RdApiError && [401, 403].includes(reason.status)) { setProject(null); setProjects(current => current.filter(item => item.id !== project.id)); setDirty(false); mutationRetry.current = { fingerprint: '', key: '' }; }
      return false;
    } finally { mutationLock.current = false; setBusy(false); }
  }, [project, applyProject]);
  async function create(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) { setCreateError('请填写名称。'); document.getElementById('rd-create-title')?.focus(); return; }
    if (!canChooseWorkflow || !creationWorkflow) { setCreateError('请选择当前可用的已发布流程模板。'); document.getElementById('rd-project-workflow-label')?.scrollIntoView({ block: 'center' }); return; }
    const workflowTemplate = { id: creationWorkflow.id, version: creationWorkflow.version, digest: creationWorkflow.digest };
    setCreateError('');
    if (newDialog === 'case') {
      const ok = await runCommand('create_case', { workflow_template: workflowTemplate, title: title.trim() }, () => { setNewDialog(null); setTitle(''); });
      if (!ok) setCreateError('业务流程尚未确认保存。填写内容已保留，请检查返回信息后重试。');
      return;
    }
    if (!createProgress && !createUncertain && (productCatalogLoading || productCatalogError || !selectedProduct?.enabled || !productDomains.some(item => item.value === productDomain))) {
      setCreateError(CLASSIFICATION_REQUIRED);
      document.getElementById(!selectedProduct?.enabled ? 'rd-create-product-type' : 'rd-create-product-domain')?.focus();
      return;
    }
    if (mutationLock.current) return;
    const profile = { brief: goal.trim(), customer_name: customerName.trim(), product_name: productName.trim() };
    const context = { product_type: productType, product_domain: productDomain, cover_phase: coverPhase, organization_scope: organizationScope };
    const fingerprint = JSON.stringify([title.trim(), profile, context, workflowTemplate]);
    if (createRetry.current.fingerprint !== fingerprint) createRetry.current = { fingerprint, projectKey: makeRequestKey(), caseKey: makeRequestKey(), project: null };
    mutationLock.current = true; projectRequest.current?.abort(); setRefreshing(false); setBusy(true); setCreateError(''); setCreateConflict(false);
    try {
      let createdProject = createRetry.current.project;
      if (!createdProject) {
        createdProject = await rdCreate(title.trim(), context, createRetry.current.projectKey, profile);
        createRetry.current.project = createdProject; setCreateProgress(createdProject); applyProject(createdProject);
      }
      const value = await rdCommand(createdProject, 'create_case', { workflow_template: workflowTemplate, title: title.trim() }, createRetry.current.caseKey);
      const createdCase = value.cases.find(item => !createdProject.cases.some(previous => previous.id === item.id));
      applyProject(value);
      if (!createdCase) throw new Error('项目已保存，尚未取得新业务流程的回执。请重试核对。');
      createRetry.current = { fingerprint: '', projectKey: '', caseKey: '', project: null };
      setCreateProgress(null); setNewDialog(null); setTitle(''); setGoal('');
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
    setProductType(''); setProductDomain('');
    setNewDialog(null); setDiscardCreate(false); setCreateProgress(null);
    if (saved) navigate({ view: 'projects', projectId: saved.id, caseId: '' });
    else if (unknownCase) void refreshProject();
    else if (createUncertain) setRevision(value => value + 1);
  }
  const filtered = useMemo(() => selectDirectoryProjects(projects, location), [projects, location.q, location.projectStatus, location.projectSort]);
  const page = Math.min(location.page, Math.max(1, Math.ceil(filtered.length / PROJECT_PAGE_SIZE)));
  const pageItems = filtered.slice((page - 1) * PROJECT_PAGE_SIZE, page * PROJECT_PAGE_SIZE);
  useEffect(() => {
    if (location.view === 'projects' && !location.projectId && !listLoading && !listError && location.page !== page) navigate({ page }, true);
  }, [location.view, location.projectId, location.page, listLoading, listError, page, navigate]);
  const commitQuery = (value: string) => navigate({ q: value, page: 1 }, true);
  const legacyNavigation = (event: MouseEvent<HTMLAnchorElement>, href: string) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || !dirty && !createDirty && !busy && !workspaceBusy) return;
    event.preventDefault(); requestNavigation(() => { setDirty(false); setProject(null); setLocation(current => ({ ...current, view: 'projects', projectId: '', caseId: '' })); window.setTimeout(() => window.location.assign(href), 0); });
  };
  const openProject = (projectId: string, caseId = '', target: CaseWorkspaceView = 'current', surface?: CaseSurface) => requestNavigation(() => navigate({ view: 'projects', projectId, caseId, caseView: target, surface, evidence: undefined, workpackageId: undefined }));
  const openView = (view: View) => requestNavigation(() => {
    const tab = window.history.state?.[DIRECTORY_HISTORY]?.management?.tab;
    navigate({ view, projectId: '', caseId: '', researchTab: view === 'management' && (tab === 'customer' || tab === 'product') ? tab : undefined });
  });
  const startCaseCreation = () => requestNavigation(() => { if (project) navigate({ view: 'projects', projectId: project.id, caseId: '' }); beginCreate('case'); });
  const setProjectMutationPending = useCallback((pending: boolean) => {
    mutationLock.current = pending;
    if (pending) { projectRequest.current?.abort(); setRefreshing(false); }
    setBusy(pending);
  }, []);
  function projectDeleted(projectId: string) {
    setProjects(current => current.filter(item => item.id !== projectId));
    setDeleteTarget(null); setNotice('项目已删除。');
    if (location.projectId === projectId) {
      projectRequest.current?.abort(); setProject(null); setDirty(false);
      navigate({ view: 'projects', projectId: '', caseId: '' });
    }
    setRevision(value => value + 1);
  }
  function closeDeletion(uncertain = false) {
    if (uncertain) {
      setRevision(value => value + 1);
      if (location.projectId === deleteTarget?.id) { setProject(null); setDirty(false); navigate({ view: 'projects', projectId: '', caseId: '' }); }
    }
    setDeleteTarget(null);
  }
  function applyEditedProject(value: Project) {
    setProjects(current => current.map(item => item.id === value.id && item.version <= value.version ? value : item));
    setProject(current => current?.id === value.id && current.version <= value.version ? value : current);
  }
  function closeProjectEdit(uncertain = false) {
    setEditTarget(null);
    if (uncertain) setRevision(value => value + 1);
  }

  return <div ref={sidebarResize.shellRef} style={sidebarResize.style} className={`rd-shell rd-platform-shell rd-application-shell${sidebarCollapsed ? ' is-sidebar-collapsed' : ''}${sidebarResize.resizing ? ' is-sidebar-resizing' : ''}`}><aside id="rd-platform-sidebar" className="rd-sidebar">
    <div className="rd-brand-row"><a className="rd-brand" href="/rd" aria-label="AI Native研发管理平台首页" onClick={event => { event.preventDefault(); openView('home'); }}><img src="/assets/jonhon-logo.png" alt="JONHON" /></a><Button type="default" htmlType="button" className="rd-sidebar-toggle" onClick={() => setSidebarCollapsed(value => !value)} aria-label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'} title={sidebarCollapsed ? '展开侧栏' : '收起侧栏'} aria-expanded={!sidebarCollapsed}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d={sidebarCollapsed ? 'm9 6 6 6-6 6' : 'm15 6-6 6 6 6'} /></svg></Button></div>
    <div className="rd-sidebar-navigation">
    <nav aria-label="研发平台导航">
      {(['home', 'projects', ...MANAGEMENT_VIEWS.filter(view => view !== 'system'), 'workspace'] as View[]).map(view => <Button type="text" key={view} htmlType="button" disabled={busy || workspaceBusy} title={VIEW_TITLES[view]} aria-label={VIEW_TITLES[view]} className={location.view === view ? 'active' : ''} aria-current={location.view === view ? 'page' : undefined} onClick={() => openView(view)}><RdNavigationIcon name={view} /><span className="rd-nav-label">{VIEW_TITLES[view]}</span></Button>)}
    </nav>
    {location.view === 'projects' && project && location.projectId === project.id && <section className="rd-sidebar-case" aria-labelledby="rd-sidebar-case-label">
      <p id="rd-sidebar-case-label" className="rd-sidebar-case-label">{project ? <><span className="rd-sidebar-context-kind">项目</span>{project.title}</> : '项目工作面'}</p>
      {selectedCase ? <><strong className="rd-sidebar-case-name"><span className="rd-sidebar-context-kind">流程</span>{sidebarFlowTitle}</strong><nav aria-label="当前业务流程视图">
        {([{ id: 'current', title: '当前成果' }, { id: 'process', title: '项目流程' }, { id: 'evidence', title: '资料与依据' }] as const).map(item => <button key={item.id} type="button" className={caseView === item.id ? 'active' : ''} aria-current={caseView === item.id ? 'page' : undefined} aria-controls="rd-case-workarea" disabled={busy || workspaceBusy} onClick={() => item.id === 'current' ? setSurfaceRequest({ target: 'resume', serial: ++surfaceSerial.current, caseId: selectedCase.id }) : navigateCase({ caseView: item.id })}>{item.title}</button>)}
      </nav></> : <p className="rd-sidebar-case-hint">先选择项目和业务流程</p>}
    </section>}
    </div>
    <RdAccountDock onExpand={() => setSidebarCollapsed(false)} onOpenSettings={() => openView('system')} settingsActive={location.view === 'system'} settingsDisabled={busy || workspaceBusy} />
    {sidebarResize.enabled && <div className="rd-sidebar-resizer" {...sidebarResize.separatorProps} />}
  </aside>
    <div ref={mainRef} className="rd-main"><header className="rd-topbar"><div ref={pageTopRef} className="rd-platform-heading" tabIndex={-1}><strong>AI Native研发管理平台</strong>{location.view === 'projects' && project ? <nav className="rd-breadcrumb rd-header-breadcrumb" aria-label="当前位置"><Button type="link" htmlType="button" className="rd-link-button" onClick={() => openView('projects')}>项目空间</Button><span aria-hidden="true">/</span>{selectedCase ? <Button type="link" htmlType="button" className="rd-link-button" onClick={() => openProject(project.id)}>{project.title}</Button> : <span aria-current="page">{project.title}</span>}</nav> : <span>{VIEW_TITLES[location.view]}</span>}</div><div className="rd-topbar-help"><a href="/help/manual" onClick={event => legacyNavigation(event, '/help/manual')} title="操作手册" aria-label="操作手册"><RdNavigationIcon name="knowledge" /></a><a href="/help/video" onClick={event => legacyNavigation(event, '/help/video')} title="操作视频" aria-label="操作视频"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9 5 3-5 3V9Z"/></svg></a></div></header>
      {location.view === 'workspace' ? <WorkspacePanel catalog={catalog} onDirtyChange={setChildDirty} onBusyChange={setWorkspaceBusy} onCatalogChange={() => setCatalogRevision(value => value + 1)} /> : <main className={`rd-page-content${location.view === 'projects' && selectedCase ? ' rd-case-page' : ''}`}>
        {catalogError && location.view !== 'flows' && <p className="rd-warning rd-banner" role="alert">业务目录读取失败：{catalogError} <Button type="link" className="rd-link-button" onClick={() => setCatalogRevision(value => value + 1)}>重新读取</Button></p>}
        {messageContextHolder}
        {error && <div id="rd-project-error" className="rd-error rd-banner" role="alert" tabIndex={-1}><p>{error}</p>{conflict && <p>项目版本已变化。当前填写保留；读取最新版本并核对后再保存。</p>}{location.projectId && <Button type="default" className="rd-button" disabled={busy || refreshing} onClick={() => void refreshProject()}>读取最新版本</Button>}</div>}
        {location.view === 'home' ? <PlatformHome canCreate={canChooseWorkflow} catalogLoading={catalogLoading} catalogError={catalogError} onStart={() => beginCreate('project')} projects={projects} catalog={catalog} loading={listLoading} error={listError} onRefresh={() => setRevision(value => value + 1)} onOpenProject={id => openProject(id)} onOpenCase={(pid, cid, target) => openProject(pid, cid, 'current', target)} onOpenProjects={() => openView('projects')} /> : MANAGEMENT_VIEWS.includes(location.view) ? <PlatformManagement key={location.view} view={location.view} projects={projects} catalog={catalog} loading={listLoading} error={listError} onRefresh={() => setRevision(value => value + 1)} catalogLoading={catalogLoading} catalogError={catalogError} onRefreshCatalog={() => setCatalogRevision(value => value + 1)} onOpenCase={(pid, cid, target) => openProject(pid, cid, target)} onOpenWorkspace={() => openView('workspace')} onStartWorkflow={workflow => requestNavigation(() => beginCreate('project', false, workflow))} /> : !location.projectId ? <>
          <div className="rd-page-title"><div><h1>项目空间</h1><p>按项目查看目标、业务流程与当前成果。</p></div><Button type="primary" htmlType="button" className="rd-button primary" disabled={busy || !canChooseWorkflow} onClick={() => beginCreate('project')}>新建项目</Button></div>
          <div className="rd-list-toolbar"><form noValidate role="search" onSubmit={event => { event.preventDefault(); if (!composition.current) commitQuery(query); }}><label className="rd-visually-hidden" htmlFor="rd-project-search">搜索项目、客户、产品或业务流程</label><div className="rd-search"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg><input ref={queryRef} id="rd-project-search" value={query} placeholder="查找项目、客户或产品" onCompositionStart={() => { composition.current = true; }} onCompositionEnd={event => { composition.current = false; commitQuery(event.currentTarget.value); }} onChange={event => { setQuery(event.target.value); if (!composition.current) commitQuery(event.target.value); }} />{query && <button type="button" aria-label="清空项目搜索" onClick={() => { setQuery(''); commitQuery(''); queryRef.current?.focus(); }}>×</button>}</div></form><span className="rd-muted">{filtered.length} 个项目</span><Button type="link" htmlType="button" className="rd-link-button" disabled={listLoading} onClick={() => setRevision(value => value + 1)}>{listLoading ? '读取中…' : '刷新'}</Button></div>
          <div className="rd-project-directory-tools">
            <label><span id="rd-project-status-label">状态</span><StyledSelect aria-labelledby="rd-project-status-label" value={location.projectStatus ?? 'all'} onChange={value => navigate({ projectStatus: value === 'all' ? undefined : value as typeof location.projectStatus, page: 1 })} options={[{ value: 'all', label: '全部项目' }, { value: 'active', label: '办理中' }, { value: 'attention', label: '需关注' }, { value: 'completed', label: '已完成' }, { value: 'empty', label: '待建立流程' }]} /></label>
            <label><span id="rd-project-sort-label">排序</span><StyledSelect aria-labelledby="rd-project-sort-label" value={location.projectSort ?? 'recent'} onChange={value => navigate({ projectSort: value === 'recent' ? undefined : value as typeof location.projectSort, page: 1 })} options={[{ value: 'recent', label: '最近更新优先' }, { value: 'oldest', label: '较早更新优先' }, { value: 'name', label: '按项目名称' }]} /></label>
            <div className="rd-project-view-switch" role="group" aria-label="项目展示方式"><Button aria-pressed={!location.projectLayout} onClick={() => navigate({ projectLayout: undefined }, true)}>卡片</Button><Button aria-pressed={location.projectLayout === 'list'} onClick={() => navigate({ projectLayout: 'list' }, true)}>紧凑列表</Button></div>
          </div>
          {listError && <p className="rd-error rd-banner" role="alert">{listError} <Button type="link" className="rd-link-button" onClick={() => setRevision(value => value + 1)}>重新读取</Button></p>}{listLoading && <p className="rd-loading" role="status">正在读取项目…</p>}
          {!listLoading && !listError && !filtered.length && <div className="rd-platform-empty"><h2>{location.q || location.projectStatus ? '没有找到匹配的项目' : '还没有项目'}</h2><p>{location.projectStatus ? '当前状态下没有匹配项目，可调整筛选条件。' : location.q ? '试试其他名称，或清空搜索查看全部项目。' : '发起项目工作，选择已发布流程模板后开始办理。'}</p>{location.projectStatus ? <Button type="link" onClick={() => navigate({ q: '', projectStatus: undefined, page: 1 })}>清除筛选</Button> : location.q && <Button type="link" htmlType="button" className="rd-link-button" onClick={() => { setQuery(''); commitQuery(''); }}>清空搜索</Button>}</div>}
          {location.projectLayout === 'list' ? <ProjectDirectoryTable projects={pageItems} disabled={busy || workspaceBusy} onOpen={id => openProject(id)} onContinue={(id, caseId) => openProject(id, caseId)} onEdit={value => requestNavigation(() => setEditTarget(value))} onDelete={setDeleteTarget} /> : <div className="rd-project-entries">{pageItems.map(item => <ProjectOverviewCard key={item.id} project={item} disabled={busy || workspaceBusy} onOpen={() => openProject(item.id)} onContinue={caseId => openProject(item.id, caseId)} onEdit={value => requestNavigation(() => setEditTarget(value))} onDelete={setDeleteTarget} />)}</div>}
          {!!filtered.length && <div className="rd-pagination"><span>显示 {(page - 1) * PROJECT_PAGE_SIZE + 1}–{Math.min(page * PROJECT_PAGE_SIZE, filtered.length)} / {filtered.length} 个项目</span><div><Button type="default" className="rd-button" disabled={page <= 1} onClick={() => navigate({ page: page - 1 })}>上一页</Button><span>第 {page} / {Math.max(1, Math.ceil(filtered.length / PROJECT_PAGE_SIZE))} 页</span><Button type="default" className="rd-button" disabled={page * PROJECT_PAGE_SIZE >= filtered.length} onClick={() => navigate({ page: page + 1 })}>下一页</Button></div></div>}
        </> : projectLoading ? <p className="rd-loading" role="status">正在打开项目…</p> : project ? <>
          {!selectedCase && <><div className="rd-project-header"><div>{!selectedCase && <h1>{project.title}</h1>}{dirty && <p className="rd-unsaved-state">有未保存的填写{hasActiveRun ? ' · 自动刷新已暂停' : ''}</p>}</div><div className="rd-project-tools"><ProjectDeleteButton project={project} disabled={busy || workspaceBusy || refreshing} onRequest={setDeleteTarget} /><Button type="link" htmlType="button" className="rd-link-button" disabled={busy || refreshing} onClick={() => void refreshProject()}>{refreshing ? '刷新中…' : '刷新'}</Button>{!selectedCase && <Button type="primary" htmlType="button" className="rd-button primary" disabled={busy || !canChooseWorkflow} onClick={startCaseCreation}>新增业务流程</Button>}<details className="rd-project-options"><summary>项目记录</summary><div><dl><dt>项目编号</dt><dd><code>{project.id}</code></dd><dt>项目负责人</dt><dd>{project.owner_id}</dd><dt>记录版本</dt><dd>{project.version}</dd><dt>最近刷新</dt><dd>{updatedAt || '—'}</dd></dl>{selectedCase && <Button type="default" htmlType="button" className="rd-button" disabled={busy || !canChooseWorkflow} onClick={startCaseCreation}>新增业务流程</Button>}</div></details></div></div>
          <div className="rd-project-business-context"><dl><div><dt>客户</dt><dd>{project.customer_name || '未填写'}</dd></div><div><dt>产品</dt><dd>{project.product_name || '未填写'}</dd></div><div className="rd-project-goal"><dt>研发目标</dt><dd>{project.brief || '未填写'}</dd></div></dl></div></>}
          {selectedCase ? <CaseWorkspace key={selectedCase.id} project={project} researchCase={selectedCase} catalog={catalog} busy={busy} error={error} view={caseView} route={location} surfaceRequest={surfaceRequest?.caseId === selectedCase.id ? surfaceRequest : undefined} onNavigate={navigateCase} onCommand={runCommand} onAnalyze={analyzeSources} onUpload={upload} onBatchUpload={uploadBatch} onDirtyChange={setChildDirty} onBusyChange={setWorkspaceBusy} /> : <><div className="rd-project-cases-heading"><h2>业务流程</h2><p>选择流程实例，查看当前成果与办理进展。</p></div>{location.caseId && <p className="rd-warning">未找到指定流程。请选择下方可访问的流程实例。</p>}{!project.cases.length && <div className="rd-platform-empty"><h3>选择流程模板开始</h3><p>新增业务流程后，将在项目中保留输入、成果与过程记录。</p></div>}<div className="rd-case-grid">{project.cases.map(researchCase => <ProjectCaseCard key={researchCase.id} project={project} researchCase={researchCase} onContinue={() => openProject(project.id, researchCase.id)} onOpenProcess={() => openProject(project.id, researchCase.id, 'process')} onOpenEvidence={() => openProject(project.id, researchCase.id, 'evidence')} />)}</div></>}
        </> : !error && <div className="rd-empty"><h2>项目尚未读取</h2><Button type="default" className="rd-button" onClick={() => void refreshProject()}>重新读取</Button></div>}
      </main>}
      <footer className="rd-platform-footer" aria-label="平台愿景">
        <div className="rd-platform-footer-inner">
          <div className="rd-platform-footer-brand">
            <img src="/assets/jonhon-logo.png" alt="中航光电 JONHON" />
            <p className="rd-platform-vision">让知识贯通研发，让智能驱动创新</p>
          </div>
          <Button type="text" htmlType="button" className="rd-back-to-top" aria-hidden={!canScrollToTop} tabIndex={canScrollToTop ? undefined : -1} onClick={scrollToTop} icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M5 4h14M12 20V8m-6 6 6-6 6 6" /></svg>}>回到顶部</Button>
        </div>
      </footer>
    </div>
    {!selectedCase && <FloatingAssistant project={location.view === 'projects' ? project ?? undefined : undefined} onStartTask={startFromUpload} onOpenProjects={() => openView('projects')} />}
    {newDialog && <FeedbackDialog title={newDialog === 'project' ? '新建项目' : '新增业务流程'} className="rd-create-dialog rd-platform-create" onCancel={closeCreate}><form className="rd-create-form" noValidate onSubmit={event => void create(event)}>
      <div className="rd-create-body">
      <p className="rd-muted">{newDialog === 'project' ? '明确项目目标，选择本次采用的已发布流程模板。' : '为当前项目建立一个独立办理的流程实例。'}</p>
      <div className="rd-field"><label htmlFor="rd-create-title">{newDialog === 'project' ? '项目名称' : '流程名称'} <span className="rd-required">必填</span></label><input id="rd-create-title" maxLength={200} value={title} onChange={event => setTitle(event.target.value)} disabled={creationLocked} aria-invalid={!!createError && !title.trim()} aria-describedby={createError ? 'rd-create-error' : undefined} placeholder={newDialog === 'project' ? '填写项目名称' : '填写本次工作的名称'} /></div>
      {newDialog === 'project' && <>
        <div className="rd-create-profile-grid">
          <div className="rd-field"><label id="rd-create-product-type-label" htmlFor="rd-create-product-type">产品类型 <span className="rd-required">必填</span></label><StyledSelect id="rd-create-product-type" required invalid={createError === CLASSIFICATION_REQUIRED && !selectedProduct?.enabled} aria-labelledby="rd-create-product-type-label" aria-describedby={createError === CLASSIFICATION_REQUIRED ? 'rd-create-error' : undefined} value={productType} onChange={chooseProductType} disabled={creationLocked || productCatalogLoading || !!productCatalogError} placeholder="选择产品类型" options={(productCatalog?.product_types ?? []).map(item => ({ value: item.value, label: item.label, disabled: !item.enabled }))} /></div>
          <div className="rd-field"><label id="rd-create-product-domain-label" htmlFor="rd-create-product-domain">质量管理体系分类 <span className="rd-required">必填</span></label><StyledSelect id="rd-create-product-domain" required invalid={createError === CLASSIFICATION_REQUIRED && !productDomains.some(item => item.value === productDomain)} aria-labelledby="rd-create-product-domain-label" aria-describedby={createError === CLASSIFICATION_REQUIRED ? 'rd-create-error' : undefined} value={productDomain} onChange={chooseProductDomain} disabled={creationLocked || productCatalogLoading || !!productCatalogError || !selectedProduct?.enabled} placeholder="选择质量管理体系" options={productDomains.map(item => ({ value: item.value, label: item.label }))} /></div>
        </div>
        {productCatalogLoading ? <p className="rd-loading" role="status">正在读取产品分类…</p> : productCatalogError ? <p className="rd-error" role="alert">产品分类读取失败：{productCatalogError} <Button type="link" htmlType="button" disabled={creationLocked} onClick={() => setProductCatalogRevision(value => value + 1)}>重新读取产品分类</Button></p> : !productCatalog?.product_types.some(item => item.enabled) && <p className="rd-warning">暂无可用产品分类，请核对产品目录配置。</p>}
      </>}
      {newDialog === 'project' && <><div className="rd-field"><label htmlFor="rd-create-goal">研发目标 <span className="rd-optional">选填</span></label><textarea id="rd-create-goal" className="resize-none" rows={3} maxLength={4000} value={goal} onChange={event => setGoal(event.target.value)} disabled={creationLocked} placeholder="希望解决什么问题，交付什么成果" /></div><div className="rd-create-profile-grid"><div className="rd-field"><label htmlFor="rd-create-customer">客户名称 <span className="rd-optional">选填</span></label><input id="rd-create-customer" maxLength={200} value={customerName} onChange={event => setCustomerName(event.target.value)} disabled={creationLocked} /></div><div className="rd-field"><label htmlFor="rd-create-product">产品名称 <span className="rd-optional">选填</span></label><input id="rd-create-product" maxLength={200} value={productName} onChange={event => setProductName(event.target.value)} disabled={creationLocked} /></div></div></>}
      <div className="rd-field">
        <label id="rd-project-workflow-label">流程模板 <span className="rd-required">必填</span></label>
        <StyledSelect aria-labelledby="rd-project-workflow-label" value={workflowKey} onChange={chooseWorkflow} disabled={creationLocked || catalogLoading || !!catalogError} placeholder="选择已发布流程模板" options={creationWorkflows.map(item => ({ value: `${item.id}@${item.version}`, label: `${item.title} · V${item.version}` }))} />
        {creationWorkflow && <p className="rd-muted">已发布 V{creationWorkflow.version} · {creationWorkflow.graph.nodes.length} 个节点 · 终点：{creationWorkflow.graph.nodes.filter(node => !creationWorkflow.graph.edges.some(edge => edge.source === node.id)).map(node => node.title).join('、')}。创建后保留此次采用的固定版本。</p>}
        {catalogLoading ? <p className="rd-loading" role="status">正在读取已发布流程模板…</p> : catalogError ? <p className="rd-error" role="alert">流程模板读取失败：{catalogError} <Button type="link" htmlType="button" disabled={creationLocked || createConflict} onClick={refreshCatalog}>重新读取</Button></p> : !creationWorkflows.length && <p className="rd-warning">暂无可用于新建项目的已发布流程模板，请先在流程管理中校验并发布。</p>}
        {!catalogLoading && !catalogError && creationWorkflow && !workflowChoices.some(item => item.id === creationWorkflow.id && item.version === creationWorkflow.version) && <p className="rd-muted">目录已更新，保留已选 V{creationWorkflow.version}。可选择其他已发布版本；创建时将再次校验所选版本是否可用。</p>}
        <div className="rd-create-template-link"><a href="/flows" target="_blank" rel="noreferrer">在流程管理中查看模板 ↗</a></div>
      </div>
      {newDialog === 'project' && <details className="rd-create-options">
        <summary>更多编制选项 <span>{coverPhase} · {organizationScope === 'central_research' ? '中央研究院产品' : '非中央研究院产品'}</span></summary>
        <div className="rd-create-profile-grid">
          <div className="rd-field"><label id="rd-create-cover-label">封面研制阶段</label><StyledSelect aria-labelledby="rd-create-cover-label" value={coverPhase} onChange={setCoverPhase} disabled={creationLocked} options={['F', 'C', 'S', 'D'].map(value => ({ value, label: value }))} /></div>
          <div className="rd-field"><label id="rd-create-scope-label">产品归属范围</label><StyledSelect aria-labelledby="rd-create-scope-label" value={organizationScope} onChange={setOrganizationScope} disabled={creationLocked} options={[{ value: 'non_central_research', label: '非中央研究院产品' }, { value: 'central_research', label: '中央研究院产品' }]} /></div>
        </div>
      </details>}
      {createProgress && <p className="rd-notice" role="status">项目“{createProgress.title}”已保存，正在建立业务流程。重试会继续此项目。</p>}
      {createError && <p id="rd-create-error" className="rd-error" role="alert">{newDialog === 'case' && error ? error : createError}</p>}{createConflict && <p className="rd-warning">项目记录已变化。<Button type="link" htmlType="button" className="rd-link-button" disabled={busy} onClick={() => void reconcileCreation()}>读取项目后继续</Button></p>}{createUncertain && <p className="rd-warning">服务端结果尚未确认。可用下方按钮重试同一次请求；请勿重复创建。</p>}
      </div>
      <div className="rd-actions rd-create-footer"><Button type="default" htmlType="button" className="rd-button" disabled={busy} onClick={closeCreate}>{createProgress ? '稍后继续' : '取消'}</Button><Button type="primary" htmlType="submit" className="rd-button primary" disabled={busy || createConflict || !canChooseWorkflow}>{busy ? createProgress ? '正在建立流程…' : '正在创建…' : createProgress ? '继续建立流程' : createUncertain ? '重试并核对' : '创建并开始'}</Button></div>
    </form></FeedbackDialog>}
    {deleteTarget && <ProjectDeleteDialog key={deleteTarget.id} project={deleteTarget} onClose={closeDeletion} onDeleted={projectDeleted} onRefresh={applyProject} onPendingChange={setProjectMutationPending} />}
    {editTarget && <ProjectEditDialog key={editTarget.id} project={editTarget} onClose={closeProjectEdit} onSaved={value => { applyEditedProject(value); setEditTarget(null); setNotice('项目修改已保存。'); }} onRefresh={applyEditedProject} onPendingChange={setProjectMutationPending} />}
    {pendingStepNavigation && <FeedbackConfirmDialog title={`返回${pendingStepNavigation.title}`} confirm="继续返回" cancel="留在当前步骤" confirmDisabled={busy || workspaceBusy} onCancel={() => setPendingStepNavigation(null)} onConfirm={() => {
      if (mutationLock.current || applicationLeaveState().busyMessage) { setNotice('当前操作尚未完成，请等待结果后再切换。'); return; }
      const next = pendingStepNavigation; setPendingStepNavigation(null); next.proceed();
    }}><p>修改并保存前序资料，可能影响后续需求确认、选型及生成结果，需要重新核对。</p><p>仅查看不会改变数据，当前填写和已有成果会保留。</p></FeedbackConfirmDialog>}
    {pendingNavigation && <FeedbackConfirmDialog title="未保存的填写" confirm="放弃填写并切换" cancel="继续编辑" onCancel={() => setPendingNavigation(null)} onConfirm={() => { const next = pendingNavigation; setPendingNavigation(null); setDirty(false); setNewDialog(null); setEditTarget(null); next(); }}><p>当前有未保存的输入、文件选择或计划修改。切换后这些填写会丢失，已保存的项目记录继续保留。</p></FeedbackConfirmDialog>}
    {discardCreate && <FeedbackConfirmDialog title={createProgress ? '稍后建立业务流程' : '关闭当前创建'} confirm={createProgress ? '进入已保存项目' : '关闭创建'} cancel="继续填写" onCancel={() => setDiscardCreate(false)} onConfirm={discardCreation}><p>{createProgress ? '项目已保存。尚未确认建立的业务流程可在项目空间继续添加，项目记录会保留。' : createUncertain ? '请求结果尚未确认。关闭后将重新读取项目核对；首页目标草稿会保留。' : '当前填写尚未保存。首页目标草稿会保留，已保存记录不受影响。'}</p></FeedbackConfirmDialog>}
  </div>;
}

export default RdPlatformPage;
