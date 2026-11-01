import { useCallback, useEffect, useRef, useState } from 'react';
import { EngineeringProgress } from './EngineeringProgress';
import { TaskbookPreparation } from './TaskbookPreparation';
import { CaseInputForm } from './CaseInputForm';
import { CaseRequirementsForm } from './CaseRequirementsForm';
import { CaseDecisionForm } from './CaseDecisionForm';
import { CaseRecords } from './CaseRecords';
import { RouteEditor } from './CaseFields';
import { WorkpackagePanel, type CommandRunner } from './WorkpackagePanel';
import type { CaseSurface } from './scenarioManifest';
import type { Catalog, Project, ResearchCase } from './types';

interface ScenarioWorkspaceProps {
  project: Project; researchCase: ResearchCase; catalog: Catalog | null; activeSurface: CaseSurface;
  busy: boolean; error: string; command: CommandRunner;
  onAnalyze: (caseId: string) => Promise<boolean>; onOpenSources: () => void;
  onUpload: (caseId: string, file: File, role: string, success: () => void) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void; workpackageFocus?: { id: string; serial: number };
}

function TaskbookWorkspace({ project, researchCase, catalog, activeSurface, busy, error, command, onAnalyze, onOpenSources, onUpload, onDirtyChange, workpackageFocus }: ScenarioWorkspaceProps) {
  const [parts, setParts] = useState<Record<string, boolean>>({});
  const setPart = useCallback((part: string, dirty: boolean) => setParts(current => current[part] === dirty ? current : { ...current, [part]: dirty }), []);
  const inputDirty = useCallback((value: boolean) => setPart('input', value), [setPart]);
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
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  const decisionPanel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (activeSurface === 'decision') {
      const details = decisionPanel.current?.querySelector('details');
      if (details) details.open = true;
    }
  }, [activeSurface]);

  return <div className="rd-scenario-editors">
    <div hidden={activeSurface !== 'sources'}><p className="rd-scenario-scope">上传资料后分析产品信息和原文需求，核对并采用识别结果；研制分类与模板由后续流程形成。</p><CaseInputForm project={project} researchCase={researchCase} busy={busy} error={error} command={command} onAnalyze={onAnalyze} onUpload={onUpload} onDirtyChange={inputDirty} /></div>
    <div hidden={activeSurface !== 'requirements'}><CaseRequirementsForm researchCase={researchCase} busy={busy} command={command} onOpenSources={onOpenSources} onDirtyChange={requirementDirty} /><CaseRecords kind="clarifications" project={project} researchCase={researchCase} busy={busy} error={error} command={command} onDirtyChange={clarificationDirty} /></div>
    <div hidden={activeSurface !== 'routes'}><CaseRecords kind="comparisons" project={project} researchCase={researchCase} busy={busy} error={error} command={command} onDirtyChange={comparisonDirty} /><section className="rd-section"><h3>产品研制分类与任务书编制策略</h3><p className="rd-muted">同一业务流程中的两个独立决策项，分别保留理由与证据。</p><div className="rd-route-grid"><RouteEditor axis="product" researchCase={researchCase} busy={busy} command={command} onDirtyChange={productDirty} /><RouteEditor axis="composition" researchCase={researchCase} busy={busy} command={command} onDirtyChange={compositionDirty} /></div></section></div>
    <div hidden={activeSurface !== 'preparation'}><TaskbookPreparation researchCase={researchCase} catalog={catalog} busy={busy} command={command} onDirtyChange={preparationDirty} /></div>
    <div hidden={activeSurface !== 'workpackages'}><p className="rd-notice">任务书是本项目研发流程中的成果节点。工作包提交后包内动作自主执行；完成编制不会自动完成后续专业设计、业务审签或交付。</p><WorkpackagePanel project={project} researchCase={researchCase} catalog={catalog} busy={busy} error={error} command={command} onDirtyChange={packageDirty} focusRequest={workpackageFocus} /><EngineeringProgress project={project} researchCase={researchCase} busy={busy} command={command} onUpload={onUpload} onDirtyChange={engineeringDirty} /></div>
    <div hidden={activeSurface !== 'delivery'}><div className="rd-field"><label htmlFor="rd-receipt-upload">上传实际交付回执或反馈资料</label><input id="rd-receipt-upload" type="file" disabled={busy || researchCase.stage !== 'delivery'} onChange={event => { const field = event.currentTarget; const file = field.files?.[0]; if (file) void onUpload(researchCase.id, file, 'reference', () => { field.value = ''; }); }} /></div><CaseRecords kind="delivery" project={project} researchCase={researchCase} busy={busy} error={error} command={command} onDirtyChange={deliveryDirty} /></div>
    <div hidden={activeSurface !== 'reuse'}><CaseRecords kind="reuse" project={project} researchCase={researchCase} busy={busy} error={error} command={command} onDirtyChange={reuseDirty} /></div>
    <div hidden={activeSurface !== 'decision'} ref={decisionPanel}><CaseDecisionForm project={project} researchCase={researchCase} busy={busy} error={error} command={command} onDirtyChange={decisionDirty} /></div>
  </div>;
}

const scenarioWorkspaces = { taskbook: TaskbookWorkspace };
export function ScenarioWorkspace(props: ScenarioWorkspaceProps) {
  const Component = scenarioWorkspaces[props.researchCase.scenario_id as keyof typeof scenarioWorkspaces];
  return Component ? <Component {...props} /> : <p className="rd-notice">此场景尚未配置可办理的原生工作面。已登记资料、成果与历史仍可查看。</p>;
}
