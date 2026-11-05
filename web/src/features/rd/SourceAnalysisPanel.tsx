import { PlatformButton } from '../../components/ui/PlatformButton';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { loadProductCatalog } from '../../api/catalog';
import type { ProductCatalog } from '../../types';
import { CONTEXT_FIELDS, isCurrentSource } from './presentation';
import { RequirementEvidence } from './RequirementEvidence';
import { ProjectProfileLinks } from './ProjectProfileLinks';
import { contextValueLabel } from './contextLabels';
import { SourceRequirementList } from './SourceRequirementList';
import type { ContextKey, Project, ResearchCase, SourceEvidence } from './types';
import type { CommandRunner } from './WorkpackagePanel';
import './sourceAnalysis.css';

const PROJECT_FIELDS = CONTEXT_FIELDS.filter(field => ['product_type', 'product_domain', 'cover_phase', 'organization_scope'].includes(field.key));
const ANALYSIS_FIELDS = CONTEXT_FIELDS.filter(field => field.key === 'development_process' || field.key === 'product_series');
const unresolvedHelp: Record<ContextKey, string> = {
  product_type: '等待来源资料明确产品分类。',
  product_domain: '等待需求或企业资料明确适用的质量体系。',
  product_series: '等待来源资料明确产品型号或系列。',
  organization_scope: '等待企业资料明确产品归属范围。',
  development_process: '由成熟产品比对及研发流程选择形成。',
  cover_phase: '等待研发流程或受控资料明确研制阶段。',
};

export function SourceAnalysisPanel({ project, researchCase, busy, blockedByDraft, pendingUpload, command, onAnalyze, renderModelControls, onReviewClarification, error = '' }: {
  project: Project; researchCase: ResearchCase; busy: boolean; blockedByDraft: boolean; pendingUpload: boolean;
  command: CommandRunner; onAnalyze: (caseId: string) => Promise<boolean>;
  renderModelControls: (analyzeButton: ReactNode) => ReactNode;
  onReviewClarification?: (requirementId: string) => void;
  error?: string;
}) {
  const [catalog, setCatalog] = useState<ProductCatalog | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [adopting, setAdopting] = useState(false);
  const [analysisFailed, setAnalysisFailed] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [selection, setSelection] = useState<{ analysisId: string; rows: number[] } | null>(null);
  const requestLock = useRef(false);
  const analysis = researchCase.source_analysis;
  const selectedRows = selection && selection.analysisId === analysis?.id ? selection.rows : [];
  const adopted = analysis?.status === 'adopted';
  const analysisRevision = adopted ? analysis.adopted_input_revision : analysis?.input_revision;
  const stale = !!analysis && (analysis.status === 'stale' || analysisRevision !== researchCase.input_revision);
  const currentSources = researchCase.sources.filter(source => isCurrentSource(source, researchCase.source_selection));
  const canAnalyze = currentSources.some(source => source.role === 'tech');
  const locked = busy || analyzing || adopting || researchCase.status === 'completed';
  const requirements = analysis?.requirements ?? [];
  const hasProposedField = Object.values(analysis?.context ?? {}).some(item => item.status === 'proposed' && !!item.value);
  const adoptDisabled = locked || stale || blockedByDraft || pendingUpload || (!requirements.length && !hasProposedField);
  const classificationConflicts = PROJECT_FIELDS.filter(field => researchCase.parameter_facts?.[field.key]?.status === 'conflict' || !stale && analysis?.context[field.key]?.status === 'conflict');
  useEffect(() => {
    let active = true;
    void loadProductCatalog().then(value => { if (active) setCatalog(value); }).catch(() => { /* Existing values remain readable; a later refresh reloads the catalog. */ });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!analyzing) return;
    const started = Date.now(); setElapsed(0);
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [analyzing]);
  function evidenceList(evidence: SourceEvidence[], analysisId: string | null = analysis?.id ?? null) {
    return <RequirementEvidence project={project} researchCase={researchCase} evidence={evidence} analysisId={analysisId} />;
  }
  async function analyze() {
    if (requestLock.current || locked || pendingUpload || !canAnalyze) return;
    requestLock.current = true; setAnalyzing(true); setAnalysisFailed(false); setElapsed(0);
    try { setAnalysisFailed(!await onAnalyze(researchCase.id)); } finally { requestLock.current = false; setAnalyzing(false); }
  }
  async function adopt() {
    if (requestLock.current || adoptDisabled || !analysis || adopted) return false;
    requestLock.current = true; setAdopting(true);
    try {
      return await command('adopt_source_analysis', { analysis_id: analysis.id, ...(selectedRows.length ? { accept_recommendations: selectedRows } : {}) });
    } finally { requestLock.current = false; setAdopting(false); }
  }
  return <section className="rd-section rd-source-analysis" aria-labelledby="rd-analysis-title" aria-busy={analyzing || adopting}>
    <div className="rd-section-head"><h3 id="rd-analysis-title">资料分析</h3><ProjectProfileLinks project={project} researchCase={researchCase} /></div>
    {renderModelControls(<div className="rd-analysis-actions">
      <PlatformButton type="button" className={`rd-button${analysis && !adopted ? '' : ' primary'}`} disabled={locked || pendingUpload || !canAnalyze} onClick={() => void analyze()}>{analyzing ? blockedByDraft && !pendingUpload ? '正在保存模型…' : '正在分析资料…' : analysis ? '重新分析资料' : '分析上传资料'}</PlatformButton>
      {analysis && !adopted && <PlatformButton type="button" className="rd-button primary" disabled={adoptDisabled} onClick={() => void adopt()}>{adopting ? '正在采用…' : '确认采用'}</PlatformButton>}
    </div>)}
    {analyzing && <div className="rd-notice rd-analysis-wait"><p role="status">{blockedByDraft && !pendingUpload ? '正在保存模型设置，尚未开始分析。' : '已提交分析，正在等待分析结果。服务尚未返回可细分的处理阶段，可能需要数分钟。'}</p><p role="timer" aria-label="本次等待时长">已等待 {Math.floor(elapsed / 60)} 分 {elapsed % 60} 秒</p></div>}
    {analysisFailed && !analyzing && <p className="rd-warning" role="status">本次未取得新的分析结果，资料与模型选择已保留。请根据上方错误检查模型设置或连接，再点击“{analysis ? '重新分析资料' : '分析上传资料'}”重试；已有结果仍需核对当前版本后才能采用。</p>}
    {!canAnalyze && <p className="rd-muted">请先上传并采用一份主需求文件。</p>}
    {pendingUpload && <p className="rd-warning">请先上传已选文件，再分析与采用。</p>}
    {!pendingUpload && blockedByDraft && analysis && !analyzing && <p className="rd-warning">模型已更改，请重新分析后再采用。</p>}
    {stale && <p className="rd-warning" role="status">这份识别结果已过期。资料或项目信息已变化，请重新分析后再采用。</p>}
    {classificationConflicts.map(field => {
      const proposed = !stale ? analysis?.context[field.key] : undefined;
      const fact = researchCase.parameter_facts?.[field.key];
      return <div key={field.key} className="rd-warning" role="alert"><strong>{field.label}与上传资料存在冲突</strong><p>项目已选：{contextValueLabel(field.key, researchCase.context[field.key] ?? '', catalog)}。{fact?.reason || proposed?.reason || '请核对项目分类与资料，解决冲突后再继续。'}</p>{!!proposed?.evidence.length && <details><summary>查看冲突依据</summary>{evidenceList(proposed.evidence)}</details>}</div>;
    })}
    {analysis && <SourceRequirementList key={analysis.id} analysis={analysis} requirements={researchCase.requirements} clarifications={researchCase.clarifications ?? []}
      inputRevision={researchCase.input_revision} stale={stale} evidenceList={evidenceList} onReviewClarification={onReviewClarification}
      selectedRows={selectedRows} selectionDisabled={locked || stale || blockedByDraft}
      adoption={!adopted ? { disabled: adoptDisabled, pending: adopting, error, submit: adopt } : undefined}
      onSelectSuggestion={index => { if (locked || stale || blockedByDraft || adopted || pendingUpload) return; setSelection(previous => {
        const rows = previous?.analysisId === analysis.id ? previous.rows : [];
        return { analysisId: analysis.id, rows: rows.includes(index) ? rows.filter(row => row !== index) : [...rows, index] };
      }); }} />}
    <dl className="rd-analysis-context">{ANALYSIS_FIELDS.map(field => {
      const confirmed = researchCase.context[field.key]?.trim() ?? '';
      const proposed = !stale ? analysis?.context[field.key] : undefined;
      const value = confirmed || proposed?.value || '';
      const provenance = researchCase.context_provenance?.[field.key];
      const fact = researchCase.parameter_facts?.[field.key];
      const refreshing = !adopted && proposed?.adoption_kind === 'refresh_source_refs' && proposed.status === 'proposed';
      const evidence = refreshing ? proposed.evidence : confirmed ? provenance?.evidence ?? (proposed?.status === 'already_confirmed' || adopted ? proposed?.evidence ?? [] : []) : proposed?.evidence ?? [];
      const reason = refreshing ? proposed.reason : confirmed ? provenance?.reason || (proposed?.status === 'already_confirmed' ? proposed.reason : '沿用当前已采用信息。') : proposed?.reason || unresolvedHelp[field.key];
      return <div key={field.key} className="rd-analysis-context-item"><dt>{field.label}</dt><dd><strong>{contextValueLabel(field.key, value, catalog)}</strong><span className="rd-analysis-field-state">{refreshing ? '同值新来源，待确认采用' : fact?.status === 'conflict' ? '存在冲突，待核对' : fact?.evidence_status === 'stale' ? '来源已变化，待复核' : confirmed ? '已采用信息' : value ? '识别建议' : '资料未明确'}</span><p>{refreshing ? reason : fact?.reason || reason}</p>{fact?.evidence_status === 'unverified' && confirmed && <p className="rd-warning">当前值缺少有效来源引用，采用模板前需核对。</p>}{evidence.length > 0 && <details><summary>查看原文依据</summary>{evidenceList(evidence, confirmed && !refreshing && provenance?.evidence ? provenance.analysis_id ?? null : analysis?.id ?? null)}</details>}</dd></div>;
    })}</dl>
    {adopted && !stale && <p className="rd-notice" role="status">识别结果已采用，可继续核对并确认需求。</p>}
  </section>;
}
