import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { EngineeringProgress } from './EngineeringProgress';
import { EvidenceLocationsProvider } from './EvidenceLocations';
import { TaskbookPreparation } from './TaskbookPreparation';
import { CaseInputForm } from './CaseInputForm';
import { ProductSeriesConfirmation } from './ProductSeriesConfirmation';
import { CaseRequirementsForm } from './CaseRequirementsForm';
import { CaseDecisionForm } from './CaseDecisionForm';
import { CaseRecords } from './CaseRecords';
import { RouteEditor } from './CaseFields';
import { WorkpackagePanel, type CommandRunner } from './WorkpackagePanel';
import type { CaseSurface } from './scenarioManifest';
import type { Catalog, Project, ResearchCase, SourceAnalysisRunner, SourceBatchRunner } from './types';

interface ScenarioWorkspaceProps {
  project: Project; actorId: string; researchCase: ResearchCase; catalog: Catalog | null; activeSurface: CaseSurface;
  busy: boolean; error: string; command: CommandRunner;
  onNavigate: (surface: CaseSurface) => void; onAnalyze: SourceAnalysisRunner; onOpenSources: () => void;
  onUpload: (caseId: string, file: File, role: string, success: () => void) => Promise<void>; onBatchUpload: SourceBatchRunner;
  onDirtyChange: (dirty: boolean) => void; workpackageFocus?: { id: string; serial: number };
  clarificationFocus?: { requirementId: string };
  onReviewAnalysisClarification?: (requirementId: string) => void; onReviewRequirementClarification?: (requirementId: string) => void;
}

function TaskbookWorkspace({ project, actorId, researchCase, catalog, activeSurface, busy, error, command, onNavigate, onAnalyze, onOpenSources, onUpload, onBatchUpload, onDirtyChange, workpackageFocus, clarificationFocus, onReviewAnalysisClarification, onReviewRequirementClarification }: ScenarioWorkspaceProps) {
  const [parts, setParts] = useState<Record<string, boolean>>({});
  const setPart = useCallback((part: string, dirty: boolean) => setParts(current => current[part] === dirty ? current : { ...current, [part]: dirty }), []);
  const inputDirty = useCallback((value: boolean) => setPart('input', value), [setPart]);
  const seriesDirty = useCallback((value: boolean) => setPart('series', value), [setPart]);
  const requirementDirty = useCallback((value: boolean) => setPart('requirement', value), [setPart]);
  const clarificationDirty = useCallback((value: boolean) => setPart('clarification', value), [setPart]);
  const comparisonDirty = useCallback((value: boolean) => setPart('comparison', value), [setPart]);
  const productDirty = useCallback((value: boolean) => setPart('product', value), [setPart]);
  const compositionDirty = useCallback((value: boolean) => setPart('composition', value), [setPart]);
  const preparationDirty = useCallback((value: boolean) => setPart('preparation', value), [setPart]);
  const engineeringDirty = useCallback((value: boolean) => setPart('engineering', value), [setPart]);
  const packageDirty = useCallback((value: boolean) => setPart('package', value), [setPart]);
  const deliveryDirty = useCallback((value: boolean) => setPart('delivery', value), [setPart]);
  const reuseDirty = useCallback((value: boolean) => setPart('reuse', value), [setPart]);
  const decisionDirty = useCallback((value: boolean) => setPart('decision', value), [setPart]);
  const dirty = Object.values(parts).some(Boolean);
  useLayoutEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  const decisionPanel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (activeSurface === 'decision') {
      const details = decisionPanel.current?.querySelector<HTMLDetailsElement>('.rd-decision-disclosure');
      if (details) details.open = true;
    }
  }, [activeSurface]);

  return <EvidenceLocationsProvider actorId={actorId} project={project} researchCase={researchCase}><div className="rd-scenario-editors">
    <div hidden={activeSurface !== 'sources'}><CaseInputForm project={project} researchCase={researchCase} busy={busy} error={error} command={command} onAnalyze={onAnalyze} onUpload={onUpload} onBatchUpload={onBatchUpload} onDirtyChange={inputDirty} onReviewClarification={onReviewAnalysisClarification} /></div>
    <div hidden={activeSurface !== 'requirements'}><ProductSeriesConfirmation researchCase={researchCase} busy={busy} command={command} onDirtyChange={seriesDirty} /><CaseRequirementsForm key={JSON.stringify([actorId, project.owner_id === actorId])} actorId={actorId} project={project} researchCase={researchCase} busy={busy} command={command} onOpenSources={onOpenSources} onDirtyChange={requirementDirty} onReviewClarification={onReviewRequirementClarification} /><CaseRecords kind="clarifications" project={project} researchCase={researchCase} busy={busy} error={error} command={command} onDirtyChange={clarificationDirty} focusRequest={activeSurface === 'requirements' ? clarificationFocus : undefined} /></div>
    <div hidden={activeSurface !== 'routes'}><CaseRecords kind="comparisons" project={project} researchCase={researchCase} busy={busy} error={error} command={command} onDirtyChange={comparisonDirty} /><section className="rd-section"><h3>产品研制分类与任务书编制策略</h3><p className="rd-muted">同一业务流程中的两个独立决策项，分别保留理由与证据。</p><div className="rd-route-grid"><RouteEditor axis="product" researchCase={researchCase} busy={busy} command={command} onDirtyChange={productDirty} /><RouteEditor axis="composition" researchCase={researchCase} busy={busy} command={command} onDirtyChange={compositionDirty} /></div></section></div>
    <div hidden={activeSurface !== 'preparation'}>{!researchCase.context.product_series?.trim() && <p className="rd-warning">产品系列尚未确认。<button type="button" className="rd-link-button" onClick={() => onNavigate('requirements')}>前往确认产品系列 →</button></p>}<TaskbookPreparation researchCase={researchCase} catalog={catalog} busy={busy} command={command} onDirtyChange={preparationDirty} onOpenWorkpackages={() => onNavigate('workpackages')} /></div>
    <div hidden={activeSurface !== 'workpackages'}><p className="rd-notice">{researchCase.workflow_templates?.project ? '本流程以研制任务书生成为终点。工作包提交后按固定流程执行，并保留质量校验和运行记录。' : '任务书是本项目研发流程中的成果节点。工作包提交后包内动作自主执行；完成编制不会自动完成后续专业设计、业务审签或交付。'}</p><WorkpackagePanel project={project} researchCase={researchCase} catalog={catalog} busy={busy} error={error} command={command} onDirtyChange={packageDirty} focusRequest={workpackageFocus} />{(researchCase.business_lifecycle?.policy_version !== 'v2' || ['design', 'verification', 'delivery', 'knowledge'].includes(researchCase.stage)) && <EngineeringProgress project={project} researchCase={researchCase} busy={busy} command={command} onUpload={onUpload} onDirtyChange={engineeringDirty} />}</div>
    <div hidden={activeSurface !== 'delivery'}><div className="rd-field"><label htmlFor="rd-receipt-upload">上传实际交付回执或反馈资料</label><input id="rd-receipt-upload" type="file" disabled={busy || researchCase.stage !== 'delivery'} onChange={event => { const field = event.currentTarget; const file = field.files?.[0]; if (file) void onUpload(researchCase.id, file, 'reference', () => { field.value = ''; }); }} /></div><CaseRecords kind="delivery" project={project} researchCase={researchCase} busy={busy} error={error} command={command} onDirtyChange={deliveryDirty} /></div>
    <div hidden={activeSurface !== 'reuse'}><CaseRecords kind="reuse" project={project} researchCase={researchCase} busy={busy} error={error} command={command} onDirtyChange={reuseDirty} /></div>
    <div hidden={activeSurface !== 'decision'} ref={decisionPanel}>{researchCase.workflow_templates?.project && researchCase.stage === 'planning' ? <p className="rd-notice">本流程以任务书生成为终点，请查看工作包的编制和质量校验记录。</p> : <><p hidden={!parts.requirement || !['input', 'requirements'].includes(researchCase.stage)} className="rd-warning">需求清单有未保存的更改，请先保存或放弃草稿，再确认需求。</p><CaseDecisionForm project={project} researchCase={researchCase} busy={busy || (parts.requirement && ['input', 'requirements'].includes(researchCase.stage))} error={error} command={command} onDirtyChange={decisionDirty} /></>}</div>
  </div></EvidenceLocationsProvider>;
}

const scenarioWorkspaces = { taskbook: TaskbookWorkspace };
export function ScenarioWorkspace(props: ScenarioWorkspaceProps) {
  const Component = scenarioWorkspaces[props.researchCase.scenario_id as keyof typeof scenarioWorkspaces];
  return Component ? <Component {...props} /> : <p className="rd-notice">此场景尚未配置可办理的原生工作面。已登记资料、成果与历史仍可查看。</p>;
}
