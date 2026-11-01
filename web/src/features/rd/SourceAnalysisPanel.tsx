import { useEffect, useRef, useState } from 'react';
import { loadProductCatalog } from '../../api/catalog';
import type { ProductCatalog } from '../../types';
import { CONTEXT_FIELDS, formatTime, isCurrentSource } from './presentation';
import { sourceUrl } from './api';
import { contextValueLabel } from './contextLabels';
import type { ContextKey, Project, ResearchCase, SourceEvidence } from './types';
import type { CommandRunner } from './WorkpackagePanel';
import './sourceAnalysis.css';

const PAGE_SIZE = 5;
const unresolvedHelp: Record<ContextKey, string> = {
  product_type: '等待来源资料明确产品分类。',
  product_domain: '等待需求或企业资料明确适用的质量体系。',
  product_series: '等待来源资料明确产品型号或系列。',
  organization_scope: '等待企业资料明确产品归属范围。',
  development_process: '由成熟产品比对及研发流程选择形成。',
  cover_phase: '等待研发流程或受控资料明确研制阶段。',
};

export function SourceAnalysisPanel({ project, researchCase, busy, blockedByDraft, command, onAnalyze }: {
  project: Project; researchCase: ResearchCase; busy: boolean; blockedByDraft: boolean;
  command: CommandRunner; onAnalyze: (caseId: string) => Promise<boolean>;
}) {
  const [catalog, setCatalog] = useState<ProductCatalog | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [adopting, setAdopting] = useState(false);
  const [page, setPage] = useState(1);
  const requestLock = useRef(false);
  const adoptedStatus = useRef<HTMLParagraphElement>(null);
  const analysis = researchCase.source_analysis;
  const adopted = analysis?.status === 'adopted';
  const analysisRevision = adopted ? analysis.adopted_input_revision : analysis?.input_revision;
  const stale = !!analysis && (analysis.status === 'stale' || analysisRevision !== researchCase.input_revision);
  const currentSources = researchCase.sources.filter(source => isCurrentSource(source, researchCase.source_selection));
  const canAnalyze = currentSources.some(source => source.role === 'tech');
  const locked = busy || analyzing || adopting || researchCase.status === 'completed';
  const requirements = analysis?.requirements ?? [];
  const hasProposedField = Object.values(analysis?.context ?? {}).some(item => item.status === 'proposed' && !!item.value);
  const lastPage = Math.max(1, Math.ceil(requirements.length / PAGE_SIZE));
  const visiblePage = Math.min(page, lastPage);
  const unresolved = CONTEXT_FIELDS.filter(field => !researchCase.context[field.key]?.trim() && (!analysis || stale || !analysis.context[field.key]?.value));
  useEffect(() => { setPage(1); }, [analysis?.id]);
  useEffect(() => {
    let active = true;
    void loadProductCatalog().then(value => { if (active) setCatalog(value); }).catch(() => { /* Existing values remain readable; a later refresh reloads the catalog. */ });
    return () => { active = false; };
  }, []);
  function evidenceList(evidence: SourceEvidence[]) {
    return <ul className="rd-analysis-evidence">{evidence.map((item, index) => {
      const source = researchCase.sources.find(source => source.id === item.source_id);
      return <li key={index}>{source ? <a href={sourceUrl(project.id, researchCase.id, source.id)} target="_blank" rel="noreferrer">{source.name} ↗</a> : <span>{item.source_id === 'project_brief' ? '项目研发目标' : item.source_id === 'project_product_name' ? '项目产品名称' : '来源记录'}</span>}<blockquote>{item.quote}</blockquote></li>;
    })}</ul>;
  }
  async function analyze() {
    if (requestLock.current || locked || blockedByDraft || !canAnalyze) return;
    requestLock.current = true; setAnalyzing(true);
    try { await onAnalyze(researchCase.id); } finally { requestLock.current = false; setAnalyzing(false); }
  }
  async function adopt() {
    if (requestLock.current || locked || blockedByDraft || !analysis || stale || adopted) return;
    requestLock.current = true; setAdopting(true);
    try {
      if (await command('adopt_source_analysis', { analysis_id: analysis.id })) requestAnimationFrame(() => adoptedStatus.current?.focus({ preventScroll: true }));
    } finally { requestLock.current = false; setAdopting(false); }
  }
  return <section className="rd-section rd-source-analysis" aria-labelledby="rd-analysis-title" aria-busy={analyzing || adopting}>
    <div className="rd-section-head"><div><span className="rd-eyebrow">资料识别与确认</span><h3 id="rd-analysis-title">从资料形成项目信息与需求</h3><p>识别结果先供核对；确认采用后进入需求主账，再按流程澄清、确认需求与选型。</p></div><button type="button" className="rd-button primary" disabled={locked || blockedByDraft || !canAnalyze} onClick={() => void analyze()}>{analyzing ? '正在分析资料…' : analysis ? '重新分析资料' : '分析上传资料'}</button></div>
    {analyzing && <p className="rd-notice" role="status">正在读取当前资料并核对原文依据，可能需要数分钟。结果返回后可在下方预览。</p>}
    {!canAnalyze && <p className="rd-muted">请先上传需求文件，选择“技术资料”作为用途。</p>}
    {blockedByDraft && <p className="rd-warning">请先上传已选文件或保存模型设置，再分析与采用。</p>}
    {stale && <p className="rd-warning" role="status">这份识别结果已过期。资料或项目信息已变化，请重新分析后再采用。</p>}
    {analysis && <div className="rd-analysis-meta"><span className={`rd-badge ${stale ? 'blocked' : adopted ? 'completed' : 'draft'}`}>{stale ? '待重新分析' : adopted ? '已采用' : '待核对采用'}</span><span>{formatTime(analysis.created_at)}</span><span>分析模型：{analysis.model_selection.name || '未记录'}</span></div>}
    <dl className="rd-analysis-context">{CONTEXT_FIELDS.map(field => {
      const confirmed = researchCase.context[field.key]?.trim() ?? '';
      const proposed = !stale ? analysis?.context[field.key] : undefined;
      const value = confirmed || proposed?.value || '';
      const provenance = researchCase.context_provenance?.[field.key];
      const fact = researchCase.parameter_facts?.[field.key];
      const refreshing = !adopted && proposed?.adoption_kind === 'refresh_source_refs' && proposed.status === 'proposed';
      const evidence = refreshing ? proposed.evidence : confirmed ? provenance?.evidence ?? (proposed?.status === 'already_confirmed' || adopted ? proposed?.evidence ?? [] : []) : proposed?.evidence ?? [];
      const reason = refreshing ? proposed.reason : confirmed ? provenance?.reason || (proposed?.status === 'already_confirmed' ? proposed.reason : '沿用当前已采用信息。') : proposed?.reason || unresolvedHelp[field.key];
      return <div key={field.key} className="rd-analysis-context-item"><dt>{field.label}</dt><dd><strong>{contextValueLabel(field.key, value, catalog)}</strong><span className="rd-analysis-field-state">{refreshing ? '同值新来源，待确认采用' : fact?.status === 'conflict' ? '存在冲突，待核对' : fact?.evidence_status === 'stale' ? '来源已变化，待复核' : confirmed ? '已采用信息' : value ? '识别建议' : '资料未明确'}</span><p>{refreshing ? reason : fact?.reason || reason}</p>{fact?.evidence_status === 'unverified' && confirmed && <p className="rd-warning">当前值缺少有效来源引用，采用模板前需核对。</p>}{evidence.length > 0 && <details><summary>查看原文依据</summary>{evidenceList(evidence)}</details>}</dd></div>;
    })}</dl>
    {unresolved.length > 0 && <p className="rd-analysis-unresolved">未确定事项：{unresolved.map(field => field.label).join('、')}。后续依据补充资料和流程决定继续形成。</p>}
    {!!analysis?.warnings.length && <details className="rd-analysis-warnings"><summary>资料处理提示（{analysis.warnings.length}）</summary><ul>{analysis.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
    {analysis && <div className="rd-analysis-requirements"><div className="rd-section-head"><div><h4>原文需求预览</h4><p>共 {requirements.length} 条，保留引用原文；不会因识别完成自动审签。</p></div></div>
      {requirements.slice((visiblePage - 1) * PAGE_SIZE, visiblePage * PAGE_SIZE).map((requirement, index) => <article key={`${analysis.id}-${visiblePage}-${index}`}><h5>{(visiblePage - 1) * PAGE_SIZE + index + 1}. {requirement.title}</h5><p className="rd-prewrap">{requirement.content}</p><details><summary>核对来源原文</summary>{evidenceList(requirement.evidence)}</details></article>)}
      {!requirements.length && <p className="rd-quiet-state">本次尚未提取到可引用的原文需求，请核对文件内容后重新分析。</p>}
      {lastPage > 1 && <nav className="rd-analysis-pagination" aria-label="原文需求预览分页"><button type="button" className="rd-button compact" disabled={visiblePage === 1} onClick={() => setPage(visiblePage - 1)}>上一页</button><span>第 {visiblePage} / {lastPage} 页</span><button type="button" className="rd-button compact" disabled={visiblePage === lastPage} onClick={() => setPage(visiblePage + 1)}>下一页</button></nav>}
    </div>}
    {analysis && !adopted && <div className="rd-analysis-adopt"><p>核对后采用有依据的信息与需求。未确定项继续保留，已有确认记录保持原样。</p><button type="button" className="rd-button primary" disabled={locked || stale || blockedByDraft || (!requirements.length && !hasProposedField)} onClick={() => void adopt()}>{adopting ? '正在采用…' : '确认采用'}</button></div>}
    {adopted && !stale && <p ref={adoptedStatus} tabIndex={-1} className="rd-notice" role="status">识别结果已采用。可返回当前成果，按需求澄清与确认流程继续办理。</p>}
  </section>;
}
