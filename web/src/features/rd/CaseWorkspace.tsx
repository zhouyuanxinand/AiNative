import { useCallback, useEffect, useRef, useState } from 'react';
import { useApplicationLeaveGuard } from '../../hooks/useApplicationLeaveGuard';
import { FloatingAssistant } from './FloatingAssistant';
import { CaseProcessPanel } from './CaseProcessPanel';
import { CaseEvidencePanel } from './CaseEvidencePanel';
import { CaseOutcome } from './CaseOutcome';
import { ScenarioWorkspace } from './ScenarioWorkspace';
import { scenarioManifest, scenarioStage, type CaseSurface } from './scenarioManifest';
import type { Catalog, Project, ResearchCase, AssistantTarget, CaseWorkspaceView } from './types';
import type { CommandRunner } from './WorkpackagePanel';
import './caseOutcome.css';

export function CaseWorkspace({ project, researchCase, catalog, busy, error, view, surfaceRequest, onViewChange, onCommand, onAnalyze, onUpload, onDirtyChange, onBusyChange }: { project: Project; researchCase: ResearchCase; catalog: Catalog | null; busy: boolean; error: string; view: CaseWorkspaceView; surfaceRequest?: { target: 'current' | 'sources'; serial: number }; onViewChange: (view: CaseWorkspaceView) => void; onCommand: CommandRunner; onAnalyze: (caseId: string) => Promise<boolean>; onUpload: (caseId: string, file: File, role: string, success: () => void) => Promise<void>; onDirtyChange: (dirty: boolean) => void; onBusyChange: (busy: boolean) => void }) {
  const [surface, setSurface] = useState<CaseSurface>('current');
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [evidenceTarget, setEvidenceTarget] = useState<'artifacts' | 'history'>();
  const [workpackageFocus, setWorkpackageFocus] = useState<{ id: string; serial: number }>();
  const nativeArea = useRef<HTMLDivElement>(null);
  const nativeError = useRef<HTMLDivElement>(null);
  const [childDirty, setChildDirty] = useState<Record<string, boolean>>({});
  const setPartDirty = useCallback((part: string, dirty: boolean) => setChildDirty(current => current[part] === dirty ? current : { ...current, [part]: dirty }), []);
  const setScenarioDirty = useCallback((dirty: boolean) => setPartDirty('scenario', dirty), [setPartDirty]);
  const setAssistantDirty = useCallback((dirty: boolean) => setPartDirty('assistant', dirty), [setPartDirty]);
  const setProcessDirty = useCallback((dirty: boolean) => setPartDirty('process', dirty), [setPartDirty]);
  const dirty = Object.values(childDirty).some(Boolean);
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => { onBusyChange(assistantBusy); }, [assistantBusy, onBusyChange]);
  useApplicationLeaveGuard({ dirty, busyMessage: busy ? '研发操作尚未完成，请等待结果后再离开。' : assistantBusy ? '助手请求尚未完成，请等待回复后再离开。' : undefined });
  const command = useCallback<CommandRunner>((name, data, success) => onCommand(name, { ...(data as Record<string, unknown>), case_id: researchCase.id }, success), [onCommand, researchCase.id]);
  useEffect(() => { setSurface('current'); }, [researchCase.stage]);
  useEffect(() => { if (error && !document.querySelector('dialog[open]')) requestAnimationFrame(() => { nativeError.current?.focus(); nativeError.current?.scrollIntoView({ block: 'nearest' }); }); }, [error]);
  const focusWorkarea = useCallback(() => {
    requestAnimationFrame(() => { nativeArea.current?.focus({ preventScroll: true }); nativeArea.current?.scrollIntoView({ block: 'start', behavior: 'auto' }); });
  }, []);
  const openSurface = useCallback((target: CaseSurface) => { onViewChange('current'); setSurface(target); focusWorkarea(); }, [onViewChange, focusWorkarea]);
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
    if (target === 'process') onViewChange('process');
    else if (target === 'artifacts' || target === 'history') { onViewChange('evidence'); setHistoryOpen(target === 'history'); setEvidenceTarget(target); }
    else { onViewChange('current'); setSurface(target); }
    focusWorkarea();
  }, [onViewChange, focusWorkarea]);
  const openWorkpackage = useCallback((id: string) => { setWorkpackageFocus(current => ({ id, serial: (current?.serial ?? 0) + 1 })); openSurface('workpackages'); }, [openSurface]);
  const manifest = scenarioManifest(researchCase.scenario_id);
  const stage = scenarioStage(researchCase, manifest);
  const scenarioTitle = catalog?.scenarios.find(item => item.id === researchCase.scenario_id)?.title ?? manifest?.title ?? '研发案例';
  const editorTitle = manifest?.surfaces.find(item => item.id === surface)?.label ?? '办理内容';
  return <div className="rd-case-workspace rd-focused-case rd-outcome-case">
    <div className="rd-case-heading"><div><p className="rd-case-kind">{scenarioTitle}</p><h1>{researchCase.title}</h1></div><span className={`rd-badge ${researchCase.status === 'completed' ? 'completed' : 'running'}`}>{researchCase.status === 'completed' ? '案例已完成' : stage.title}</span></div>
    <div className="rd-case-body"><div id="rd-case-workarea" className="rd-native-workarea" tabIndex={-1} ref={nativeArea}>
      {error && <div className="rd-error rd-banner" tabIndex={-1} ref={nativeError} role="alert"><p>{error}</p><p>填写内容继续保留。请核对后重试；版本冲突可通过页面上方刷新项目。</p></div>}
      <div hidden={view !== 'current'}>
        {researchCase.stage === 'input' && researchCase.decisions.some(decision => !!decision.invalidated_at) && <p className="rd-warning" role="status">资料或需求已变更，原决定与成果已保留，请重新核对。 <button type="button" className="rd-link-button" onClick={() => navigateSurface('history')}>查看历史记录</button></p>}
        {researchCase.warnings?.map(warning => <p key={warning.code} className="rd-warning" role="status">{warning.message}</p>)}
        <div hidden={surface !== 'current'}><CaseOutcome project={project} researchCase={researchCase} manifest={manifest} onOpen={openSurface} onNavigate={navigateSurface} onOpenWorkpackage={openWorkpackage} /></div>
        <div hidden={surface === 'current'} className="rd-outcome-editor-header"><button type="button" className="rd-link-button" onClick={() => openSurface('current')}>← 返回当前成果</button><h2>{editorTitle}</h2><p>{stage.title} · {stage.guidance}</p></div>
        <ScenarioWorkspace project={project} researchCase={researchCase} catalog={catalog} activeSurface={surface} busy={busy} error={error} command={command} onAnalyze={onAnalyze} onOpenSources={() => openSurface('sources')} onUpload={onUpload} onDirtyChange={setScenarioDirty} workpackageFocus={workpackageFocus} />
      </div>
      <div hidden={view !== 'process'}><CaseProcessPanel researchCase={researchCase} catalog={catalog} busy={busy} command={command} onOpenWorkpackage={openWorkpackage} onDirtyChange={setProcessDirty} /></div>
      <div hidden={view !== 'evidence'}><CaseEvidencePanel project={project} researchCase={researchCase} onNavigate={navigateSurface} onOpenWorkpackage={openWorkpackage} historyOpen={historyOpen} focusTarget={evidenceTarget} /></div>
    </div></div>
    <FloatingAssistant project={project} researchCase={researchCase} onNavigate={navigateSurface} onDirtyChange={setAssistantDirty} onBusyChange={setAssistantBusy} />
  </div>;
}
