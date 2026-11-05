import { PlatformButton } from '../../components/ui/PlatformButton';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useApplicationLeaveGuard } from '../../hooks/useApplicationLeaveGuard';
import { useCurrentUser } from '../../hooks/useCurrentUser';
import { rdSession } from './api';
import { readCaseResume, writeCaseResume } from './caseResume';
import { FloatingAssistant } from './FloatingAssistant';
import { CaseProcessPanel } from './CaseProcessPanel';
import { projectWorkflowStatusTitle } from './ProjectWorkflowOverview';
import { fixedBusinessTemplate } from './businessWorkflowFacts';
import { CaseEvidencePanel } from './CaseEvidencePanel';
import { CaseOutcome } from './CaseOutcome';
import { CaseJourneyNav } from './CaseJourneyNav';
import { caseJourney, caseStepForSurface, successfulCaseDestination } from './caseJourney';
import type { CasePage } from './platformNavigation';
import { ScenarioWorkspace } from './ScenarioWorkspace';
import { scenarioManifest, scenarioStage, type CaseSurface } from './scenarioManifest';
import type { Catalog, Project, ResearchCase, AssistantTarget, CaseWorkspaceView, SourceAnalysisRunner, SourceBatchRunner } from './types';
import type { CommandRunner } from './WorkpackagePanel';
import './caseOutcome.css';
import './caseJourney.css';

export function CaseWorkspace({ project, researchCase, catalog, busy, error, view, route, surfaceRequest, onNavigate, onCommand, onAnalyze, onUpload, onBatchUpload, onDirtyChange, onBusyChange }: { project: Project; researchCase: ResearchCase; catalog: Catalog | null; busy: boolean; error: string; view: CaseWorkspaceView; route: CasePage; surfaceRequest?: { target: 'current' | 'sources'; serial: number }; onNavigate: (page: CasePage, replace?: boolean) => void; onCommand: CommandRunner; onAnalyze: SourceAnalysisRunner; onUpload: (caseId: string, file: File, role: string, success: () => void) => Promise<void>; onBatchUpload: SourceBatchRunner; onDirtyChange: (dirty: boolean) => void; onBusyChange: (busy: boolean) => void }) {
  const allowedSurface = (target: CaseSurface, value = researchCase) => target === 'current' || caseJourney(value).steps.some(step => step.id === caseStepForSurface(target, value) && step.available);
  const [surface, setSurface] = useState<CaseSurface>(() => route.surface && allowedSurface(route.surface) ? route.surface : readCaseResume(null, project.id, researchCase.id, researchCase));
  const lastEditingSurface = useRef<CaseSurface>(surface === 'current' ? readCaseResume(null, project.id, researchCase.id, researchCase) : surface);
  const editingVisited = useRef(false);
  const currentRoute = useRef(route);
  currentRoute.current = route;
  const { state: identityState } = useCurrentUser();
  const resumeActor = useRef('');
  const restoredActor = useRef('');
  const navigated = useRef(false);
  const pendingSurface = useRef<CaseSurface>();
  const currentCase = useRef(researchCase);
  const currentView = useRef(view);
  currentCase.current = researchCase;
  currentView.current = view;
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [evidenceTarget, setEvidenceTarget] = useState<{ target: 'artifacts' | 'history'; serial: number }>();
  const [workpackageFocus, setWorkpackageFocus] = useState<{ id: string; serial: number }>();
  const pendingClarification = useRef<string>();
  const [clarificationFocus, setClarificationFocus] = useState<{ requirementId: string }>();
  const [transition, setTransition] = useState<{ name: string; data: Record<string, unknown>; before: ResearchCase } | null>(null);
  const nativeArea = useRef<HTMLDivElement>(null);
  const [assistantLauncherHost, setAssistantLauncherHost] = useState<HTMLDivElement | null>(null);
  const [childDirty, setChildDirty] = useState<Record<string, boolean>>({});
  const setPartDirty = useCallback((part: string, dirty: boolean) => setChildDirty(current => current[part] === dirty ? current : { ...current, [part]: dirty }), []);
  const setScenarioDirty = useCallback((dirty: boolean) => setPartDirty('scenario', dirty), [setPartDirty]);
  const setAssistantDirty = useCallback((dirty: boolean) => setPartDirty('assistant', dirty), [setPartDirty]);
  const setProcessDirty = useCallback((dirty: boolean) => setPartDirty('process', dirty), [setPartDirty]);
  const dirty = Object.values(childDirty).some(Boolean);
  const resumeInUse = useRef(false);
  resumeInUse.current = dirty || busy || assistantBusy;
  useLayoutEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => { onBusyChange(assistantBusy); }, [assistantBusy, onBusyChange]);
  useApplicationLeaveGuard({ dirty, busyMessage: busy ? '研发操作尚未完成，请等待结果后再离开。' : assistantBusy ? '助手请求尚未完成，请等待回复后再离开。' : undefined });
  const command = useCallback<CommandRunner>(async (name, data, success) => {
    const payload = { ...(data as Record<string, unknown>), case_id: researchCase.id };
    const succeeded = await onCommand(name, payload, success);
    if (succeeded) setTransition({ name, data: payload, before: researchCase });
    return succeeded;
  }, [onCommand, researchCase]);
  useEffect(() => {
    if (!error) return;
    const frame = requestAnimationFrame(() => {
      if (document.querySelector('dialog[open], [role="dialog"][aria-modal="true"]')) return;
      const alert = document.getElementById('rd-project-error');
      alert?.focus({ preventScroll: true }); alert?.scrollIntoView({ block: 'nearest' });
    });
    return () => cancelAnimationFrame(frame);
  }, [error]);
  const focusWorkarea = useCallback(() => {
    requestAnimationFrame(() => { nativeArea.current?.focus({ preventScroll: true }); nativeArea.current?.scrollIntoView({ block: 'start', behavior: 'auto' }); });
  }, []);
  useEffect(() => {
    resumeActor.current = '';
    if (identityState.status !== 'ready' || (identityState.identity.auth_enabled && !identityState.identity.authenticated)) return;
    let controller: AbortController | undefined;
    const restore = () => {
      if (document.visibilityState === 'hidden') return;
      controller?.abort();
      controller = new AbortController();
      const request = controller;
      resumeActor.current = '';
      void rdSession(request.signal).then(session => {
        if (request.signal.aborted) return;
        const actorChanged = !!restoredActor.current && restoredActor.current !== session.actor_id;
        resumeActor.current = session.actor_id;
        if (actorChanged) { navigated.current = false; editingVisited.current = false; pendingSurface.current = undefined; }
        if (restoredActor.current !== session.actor_id) {
          restoredActor.current = session.actor_id;
          if (!resumeInUse.current) {
            const resumed = readCaseResume(session.actor_id, project.id, currentCase.current.id, currentCase.current);
            if (!editingVisited.current && resumed !== 'current') lastEditingSurface.current = resumed;
            if (!navigated.current && currentView.current === 'current' && !currentRoute.current.surface) {
              setSurface(resumed); onNavigate({ caseView: 'current', surface: resumed }, true);
            }
          }
        }
        if (pendingSurface.current) {
          writeCaseResume(session.actor_id, project.id, currentCase.current.id, pendingSurface.current, currentCase.current);
          pendingSurface.current = undefined;
        }
      }).catch(() => {
        if (!request.signal.aborted && currentView.current === 'current' && !currentRoute.current.surface) {
          onNavigate({ caseView: 'current', surface: readCaseResume(null, project.id, currentCase.current.id, currentCase.current) }, true);
        }
      });
    };
    restore();
    window.addEventListener('focus', restore);
    document.addEventListener('visibilitychange', restore);
    return () => {
      controller?.abort(); resumeActor.current = '';
      window.removeEventListener('focus', restore);
      document.removeEventListener('visibilitychange', restore);
    };
  }, [identityState, project.id, onNavigate]);
  const rememberSurface = useCallback((target?: CaseSurface) => {
    navigated.current = true;
    if (!target || target === 'current') return;
    editingVisited.current = true;
    lastEditingSurface.current = target;
    pendingSurface.current = target;
    if (resumeActor.current) {
      writeCaseResume(resumeActor.current, project.id, currentCase.current.id, target, currentCase.current);
      pendingSurface.current = undefined;
    }
  }, [project.id]);
  const openSurface = useCallback((target: CaseSurface) => { rememberSurface(target); onNavigate({ caseView: 'current', surface: target }); setSurface(target); focusWorkarea(); }, [onNavigate, focusWorkarea, rememberSurface]);
  useEffect(() => {
    if (view !== 'current' || !route.surface) return;
    const target = allowedSurface(route.surface) ? route.surface : readCaseResume(resumeActor.current, project.id, researchCase.id, researchCase);
    setSurface(target); rememberSurface(target);
    if (target !== route.surface) onNavigate({ caseView: 'current', surface: target }, true);
    if (target === 'workpackages' && route.workpackageId) setWorkpackageFocus(current => ({ id: route.workpackageId!, serial: (current?.serial ?? 0) + 1 }));
    const requirementId = pendingClarification.current;
    pendingClarification.current = undefined;
    if (target === 'requirements' && requirementId) {
      setClarificationFocus({ requirementId });
    } else {
      setClarificationFocus(undefined);
      focusWorkarea();
    }
  }, [view, route.surface, route.workpackageId, rememberSurface, onNavigate, focusWorkarea]);
  useEffect(() => {
    if (view !== 'evidence' || !route.evidence) return;
    setHistoryOpen(route.evidence === 'history');
    setEvidenceTarget(current => ({ target: route.evidence!, serial: (current?.serial ?? 0) + 1 }));
  }, [view, route.evidence]);
  useEffect(() => {
    if (view === 'process' || view === 'evidence' && !route.evidence) focusWorkarea();
  }, [view, route.evidence, focusWorkarea]);
  useEffect(() => {
    if (!transition) return;
    const target = successfulCaseDestination(transition.name, transition.data, transition.before, researchCase);
    setTransition(null);
    if (target) openSurface(target);
  }, [transition, researchCase, openSurface]);
  const lastSurfaceRequest = useRef<number>();
  useEffect(() => {
    if (!surfaceRequest || surfaceRequest.serial === lastSurfaceRequest.current) return;
    lastSurfaceRequest.current = surfaceRequest.serial;
    openSurface(surfaceRequest.target);
    if (surfaceRequest.target === 'sources') requestAnimationFrame(() => {
      const field = nativeArea.current?.querySelector<HTMLInputElement>('#rd-source-file');
      field?.focus(); field?.scrollIntoView({ block: 'center' });
    });
  }, [surfaceRequest, openSurface]);
  const navigateSurface = useCallback((target: AssistantTarget) => {
    if (target === 'process') { rememberSurface(); onNavigate({ caseView: 'process' }); }
    else if (target === 'artifacts' || target === 'history') { rememberSurface(); onNavigate({ caseView: 'evidence', evidence: target }); setHistoryOpen(target === 'history'); setEvidenceTarget(current => ({ target, serial: (current?.serial ?? 0) + 1 })); }
    else { rememberSurface(target); onNavigate({ caseView: 'current', surface: target }); setSurface(target); }
    focusWorkarea();
  }, [onNavigate, focusWorkarea, rememberSurface]);
  const openWorkpackage = useCallback((id: string) => {
    rememberSurface('workpackages'); setSurface('workpackages');
    setWorkpackageFocus(current => ({ id, serial: (current?.serial ?? 0) + 1 }));
    onNavigate({ caseView: 'current', surface: 'workpackages', workpackageId: id }); focusWorkarea();
  }, [onNavigate, rememberSurface, focusWorkarea]);
  const manifest = scenarioManifest(researchCase.scenario_id);
  const stage = scenarioStage(researchCase, manifest);
  const journey = caseJourney(researchCase, manifest);
  const canReviewClarification = !busy && !journey.completed && researchCase.status !== 'completed' && ['input', 'requirements'].includes(researchCase.stage)
    && journey.steps.some(step => step.id === 'requirements' && step.available);
  function reviewRequirementClarification(requirementId: string) {
    if (!canReviewClarification || !researchCase.requirements.some(row => row.id === requirementId)) return;
    if (surface === 'requirements') {
      setClarificationFocus({ requirementId });
      return;
    }
    pendingClarification.current = requirementId;
    onNavigate({ caseView: 'current', surface: 'requirements' });
  }
  const reviewAnalysisClarification = canReviewClarification && researchCase.source_analysis?.status === 'adopted'
    ? (requirementId: string) => {
      if (researchCase.source_analysis?.requirements.some(row => row.requirement_id === requirementId)) reviewRequirementClarification(requirementId);
    } : undefined;
  const projectTemplate = researchCase.workflow_templates?.project;
  const projectTemplateVersion = projectTemplate ? fixedBusinessTemplate(projectTemplate).version : '';
  const scenarioTitle = projectTemplate?.title ?? catalog?.scenarios.find(item => item.id === researchCase.scenario_id)?.title ?? manifest?.title ?? '研发案例';
  const projectStatus = researchCase.project_workflow_status?.status;
  const editorTitle = surface === 'decision' ? ['input', 'requirements'].includes(researchCase.stage) ? '确认需求' : researchCase.stage === 'selection' ? '选型确认与研发启动' : '阶段确认' : manifest?.surfaces.find(item => item.id === surface)?.label ?? '办理内容';
  const sourcesOpen = view === 'current' && surface === 'sources';
  const editorOpen = view === 'current' && surface !== 'current';
  const continuation = view !== 'current' || surface === 'current' || surface === 'decision' ? null
    : journey.completed ? { target: 'current' as CaseSurface, label: '查看生成成果' }
    : surface === 'sources' && journey.active === 'requirements' ? { target: 'requirements' as CaseSurface, label: '核对需求' }
    : journey.next && journey.next.target !== surface ? journey.next : null;
  const statusBadge = <span className={`rd-badge ${projectTemplate ? projectStatus ?? 'pending' : researchCase.status === 'completed' ? 'completed' : 'running'}`}>{projectTemplate ? projectStatus === 'completed' ? '流程已完成' : projectStatus && projectStatus !== 'pending' ? projectWorkflowStatusTitle(projectStatus) : stage.title : researchCase.status === 'completed' ? '案例已完成' : stage.title}</span>;
  const heading = <div className="rd-case-heading"><div><h1>{editorOpen ? editorTitle : view === 'process' ? '项目流程' : view === 'evidence' ? '资料与依据' : '当前成果'}</h1><p className="rd-case-kind">{researchCase.title} · {scenarioTitle}{projectTemplateVersion ? ` · V${projectTemplateVersion}` : ''}</p></div><div className="rd-journey-heading-actions">{statusBadge}{!editorOpen && <PlatformButton className="rd-link-button" disabled={busy} onClick={() => openSurface(lastEditingSurface.current !== 'current' && allowedSurface(lastEditingSurface.current) ? lastEditingSurface.current : journey.active)}>返回办理</PlatformButton>}{editorOpen && <PlatformButton className="rd-link-button" disabled={busy} onClick={() => openSurface('current')}>成果概览</PlatformButton>}{editorOpen && <div ref={setAssistantLauncherHost} />}</div></div>;
  return <div className={`rd-case-workspace rd-focused-case rd-outcome-case rd-journey-workspace${sourcesOpen ? ' rd-source-workspace' : ''}`}>
    {manifest && <CaseJourneyNav steps={journey.steps} active={journey.active} completed={journey.completed} surface={view === 'current' ? surface : undefined} researchCase={researchCase} busy={busy} onOpen={openSurface} />}
    <div className="rd-case-body"><div id="rd-case-workarea" className="rd-native-workarea" tabIndex={-1} ref={nativeArea}>
      {heading}
      <div hidden={view !== 'current'}>
        {researchCase.stage === 'input' && researchCase.decisions.some(decision => !!decision.invalidated_at) && <p className="rd-warning" role="status">资料或需求已变更，原决定与成果已保留，请重新核对。 <PlatformButton type="button" className="rd-link-button" onClick={() => navigateSurface('history')}>查看历史记录</PlatformButton></p>}
        {researchCase.warnings?.map(warning => <p key={warning.code} className="rd-warning" role="status">{warning.message}</p>)}
        <div hidden={surface !== 'current'}><CaseOutcome project={project} researchCase={researchCase} manifest={manifest} onOpen={openSurface} onNavigate={navigateSurface} onOpenWorkpackage={openWorkpackage} /></div>
        <ScenarioWorkspace project={project} researchCase={researchCase} catalog={catalog} activeSurface={surface} busy={busy} error={error} command={command} onNavigate={openSurface} onAnalyze={onAnalyze} onOpenSources={() => openSurface('sources')} onUpload={onUpload} onBatchUpload={onBatchUpload} onDirtyChange={setScenarioDirty} workpackageFocus={workpackageFocus} clarificationFocus={clarificationFocus} onReviewAnalysisClarification={reviewAnalysisClarification} onReviewRequirementClarification={canReviewClarification ? reviewRequirementClarification : undefined} />
        {continuation && <div className="rd-case-continuation"><PlatformButton className="rd-button primary" disabled={busy} onClick={() => openSurface(continuation.target)}>{continuation.label} <span aria-hidden="true">→</span></PlatformButton></div>}
      </div>
      <div hidden={view !== 'process'}><CaseProcessPanel researchCase={researchCase} catalog={catalog} busy={busy} command={command} onOpenWorkpackage={openWorkpackage} onDirtyChange={setProcessDirty} /></div>
      <div hidden={view !== 'evidence'}><CaseEvidencePanel project={project} researchCase={researchCase} onNavigate={navigateSurface} onOpenWorkpackage={openWorkpackage} historyOpen={historyOpen} focusTarget={view === 'evidence' ? evidenceTarget : undefined} /></div>
    </div></div>
    <FloatingAssistant project={project} researchCase={researchCase} launcherContainer={editorOpen ? assistantLauncherHost : undefined} onNavigate={navigateSurface} onDirtyChange={setAssistantDirty} onBusyChange={setAssistantBusy} />
  </div>;
}
