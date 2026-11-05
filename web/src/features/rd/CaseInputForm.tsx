import { PlatformButton } from '../../components/ui/PlatformButton';
import { Button, Tooltip } from 'antd';
import { DownOutlined, RightOutlined, DeleteOutlined, FileWordOutlined, FilePdfOutlined, FileExcelOutlined, FilePptOutlined, FileImageOutlined, FileTextOutlined, FileOutlined } from '@ant-design/icons';
import { useEffect, useRef, useState } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { formatSize, isCurrentSource } from './presentation';
import type { ModelSelection, Project, ResearchCase, Source, SourceAnalysisRunner, SourceBatchRunner } from './types';
import type { CommandRunner } from './WorkpackagePanel';
import { rdSession, sourceUrl } from './api';
import { loadModelCatalog } from '../../api/catalog';
import { SourceAnalysisPanel } from './SourceAnalysisPanel';
import { BatchSourceUpload } from './BatchSourceUpload';
import { useCurrentUser } from '../../hooks/useCurrentUser';
import { modelSelectionKey } from '../../lib/model';
import type { ModelItem } from '../../types';
import { browserRecentStorage, buildModelOptions, normalizeModelCatalog, normalizeModelSelection, readRecentModels, rememberRecentModel } from './modelSelection';
import './sourceFiles.css';

function fileAppearance(name: string) {
  const extension = name.split('.').pop()?.toLowerCase() ?? '';
  if (['doc', 'docx'].includes(extension)) return { Icon: FileWordOutlined, kind: 'word' };
  if (extension === 'pdf') return { Icon: FilePdfOutlined, kind: 'pdf' };
  if (['xls', 'xlsx', 'csv'].includes(extension)) return { Icon: FileExcelOutlined, kind: 'sheet' };
  if (['ppt', 'pptx'].includes(extension)) return { Icon: FilePptOutlined, kind: 'slides' };
  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'].includes(extension)) return { Icon: FileImageOutlined, kind: 'image' };
  if (['txt', 'md'].includes(extension)) return { Icon: FileTextOutlined, kind: 'text' };
  return { Icon: FileOutlined, kind: 'file' };
}

function shortFileName(name: string) {
  const characters = Array.from(name);
  return characters.length > 30 ? characters.slice(0, 21).join('') + '…' + characters.slice(-8).join('') : name;
}

export function CaseInputForm({ project, researchCase, busy, error, command, onAnalyze, onBatchUpload, onDirtyChange, onReviewClarification }: { project: Project; researchCase: ResearchCase; busy: boolean; error: string; command: CommandRunner; onAnalyze: SourceAnalysisRunner; onBatchUpload: SourceBatchRunner; onUpload: (caseId: string, file: File, role: string, success: () => void) => Promise<void>; onDirtyChange: (dirty: boolean) => void; onReviewClarification?: (requirementId: string) => void }) {
  const { state: identityState } = useCurrentUser();
  const [model, setModel] = useState<ModelSelection>(() => normalizeModelSelection(researchCase.model_selection));
  const [modelBase, setModelBase] = useState(modelSelectionKey(model));
  const [models, setModels] = useState<ModelItem[]>([]);
  const [recentModels, setRecentModels] = useState<ModelSelection[]>([]);
  const recentActorRef = useRef('');
  const recentIdentityEpoch = useRef(0);
  const recentSaveQueue = useRef(Promise.resolve());
  const [modelError, setModelError] = useState('');
  const [modelRevision, setModelRevision] = useState(0);
  const [queuePending, setQueuePending] = useState(false);
  const analysis = researchCase.source_analysis;
  const analysisRevision = analysis?.status === 'adopted' ? analysis.adopted_input_revision : analysis?.input_revision;
  const currentAnalysisKey = analysis && analysis.status !== 'stale' && analysisRevision === researchCase.input_revision
    ? `${analysis.id}:${analysisRevision}` : '';
  const [sourcesExpanded, setSourcesExpanded] = useState(() => !currentAnalysisKey);
  const sourcesOpen = sourcesExpanded || queuePending;
  const [deleteTarget, setDeleteTarget] = useState<Source | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteFailed, setDeleteFailed] = useState(false);
  const deleteLock = useRef(false);
  const fileListHeading = useRef<HTMLHeadingElement>(null);
  const [sourceChange, setSourceChange] = useState<Source | null>(null);
  const modelDirty = modelSelectionKey(model) !== modelBase;
  const activeSources = researchCase.sources.filter(source => isCurrentSource(source, researchCase.source_selection));
  const historicalSources = researchCase.sources.filter(source => !isCurrentSource(source, researchCase.source_selection));
  const hasDecisions = researchCase.decisions.some(decision => !decision.invalidated_at);
  const deleteReason = researchCase.status === 'completed' ? '流程已完成，不能删除资料'
    : researchCase.workpackages.some(item => ['submitted', 'running'].includes(item.status)) ? '工作包执行中，请完成后再删除资料' : '';
  useEffect(() => { onDirtyChange(modelDirty || queuePending); }, [modelDirty, queuePending, onDirtyChange]);
  useEffect(() => { setSourcesExpanded(!currentAnalysisKey); }, [researchCase.id, currentAnalysisKey]);
  useEffect(() => { if (queuePending) setSourcesExpanded(true); }, [queuePending]);
  useEffect(() => {
    if (modelDirty) return;
    const nextModel = normalizeModelSelection(researchCase.model_selection);
    setModel(nextModel); setModelBase(modelSelectionKey(nextModel));
  }, [researchCase.model_selection, modelDirty]);
  useEffect(() => {
    recentIdentityEpoch.current += 1;
    recentActorRef.current = '';
    setRecentModels([]);
    if (identityState.status !== 'ready' || (identityState.identity.auth_enabled && !identityState.identity.authenticated)) return;
    let controller: AbortController | undefined;
    function refreshRecentModels() {
      if (document.visibilityState === 'hidden') return;
      controller?.abort();
      const request = new AbortController();
      controller = request;
      recentIdentityEpoch.current += 1;
      recentActorRef.current = '';
      setRecentModels([]);
      void rdSession(request.signal).then(session => {
        if (request.signal.aborted) return;
        recentActorRef.current = session.actor_id;
        setRecentModels(readRecentModels(browserRecentStorage(), session.actor_id));
      }).catch(() => { /* Personal shortcuts are optional; model selection remains available. */ });
    }
    refreshRecentModels();
    window.addEventListener('focus', refreshRecentModels);
    document.addEventListener('visibilitychange', refreshRecentModels);
    return () => {
      controller?.abort(); recentActorRef.current = ''; recentIdentityEpoch.current += 1;
      window.removeEventListener('focus', refreshRecentModels);
      document.removeEventListener('visibilitychange', refreshRecentModels);
    };
  }, [identityState]);
  useEffect(() => {
    let active = true;
    void loadModelCatalog().then(response => {
      if (!active) return;
      setModels(normalizeModelCatalog(response.models ?? []));
      setModelError(response.success === false ? response.error ?? '模型列表暂时不可用' : '');
    }).catch(reason => { if (active) setModelError(reason instanceof Error ? reason.message : '模型列表暂时不可用'); });
    return () => { active = false; };
  }, [modelRevision]);
  const modelKey = modelSelectionKey(model);
  const modelOptions = buildModelOptions(models, model, recentModels);
  function selectModel(key: string) {
    if (key === modelSelectionKey(normalizeModelSelection())) setModel(normalizeModelSelection());
    else {
      const selected = models.find(item => item.configured && modelSelectionKey(item) === key);
      if (selected) setModel(normalizeModelSelection(selected));
    }
  }
  function analyzeWithModel(caseId: string) {
    const finish = (success: boolean) => {
      if (success) setSourcesExpanded(false);
      return success;
    };
    if (!modelDirty) return onAnalyze(caseId).then(finish);
    const selected = normalizeModelSelection(model);
    const actor = recentActorRef.current;
    const epoch = recentIdentityEpoch.current;
    const sameIdentity = () => actor === recentActorRef.current && epoch === recentIdentityEpoch.current;
    return onAnalyze(caseId, { selection: selected, onSaved: () => {
      setModelBase(modelSelectionKey(selected));
      if (!actor || !sameIdentity()) return;
      // Keep successful saves in order without blocking the form; stale identity checks cannot restore an old account.
      recentSaveQueue.current = recentSaveQueue.current.then(async () => {
        if (!sameIdentity()) return;
        try {
          const session = await rdSession();
          if (!sameIdentity()) return;
          if (session.actor_id !== actor) recentIdentityEpoch.current += 1;
          recentActorRef.current = session.actor_id;
          setRecentModels(session.actor_id === actor
            ? rememberRecentModel(browserRecentStorage(), actor, selected)
            : readRecentModels(browserRecentStorage(), session.actor_id));
        } catch {
          if (!sameIdentity()) return;
          recentIdentityEpoch.current += 1;
          recentActorRef.current = '';
          setRecentModels([]);
        }
      });
    } }).then(finish);
  }
  function renderSource(source: Source) {
    const current = isCurrentSource(source, researchCase.source_selection);
    const { Icon, kind } = fileAppearance(source.name);
    const label = shortFileName(source.name);
    return <article key={source.id} className="rd-source-card">
      <span className={`rd-source-file-icon is-${kind}`} aria-hidden="true"><Icon /></span>
      <div className="rd-source-card-content">
        <Tooltip title={label !== source.name ? source.name : undefined} trigger={['hover', 'focus']}><a className="rd-source-file-name" aria-label={source.name} href={sourceUrl(project.id, researchCase.id, source.id)} target="_blank" rel="noreferrer">{label}</a></Tooltip>
        <div className="rd-source-file-meta"><span>{{ tech: '需求文件', spec: '产品规范', reference: '补充资料' }[source.document_category ?? source.role]} · {formatSize(source.size)}</span><span className={`rd-badge ${current ? 'completed' : 'draft'}`}>{source.role === 'reference' ? '补充资料' : current ? '主文件' : '历史版本'}</span></div>
        {!current && source.role !== 'reference' && <PlatformButton type="button" className="rd-link-button" disabled={busy || queuePending || researchCase.status === 'completed'} onClick={() => setSourceChange(source)}>采用此版本</PlatformButton>}
      </div>
      <Tooltip title={deleteReason || (queuePending ? '请先处理待上传资料' : '删除资料')}><span className="rd-source-delete-anchor"><Button type="text" danger icon={<DeleteOutlined />} aria-label={`删除资料“${source.name}”`} disabled={busy || deleting || queuePending || !!deleteReason} onClick={() => { setDeleteFailed(false); setDeleteTarget(source); }} /></span></Tooltip>
    </article>;
  }
  async function deleteSource() {
    if (!deleteTarget || deleteLock.current || busy || deleteReason) return;
    deleteLock.current = true; setDeleting(true); setDeleteFailed(false);
    try {
      const removed = await command('delete_source', { source_id: deleteTarget.id }, () => {
        setDeleteTarget(null);
        requestAnimationFrame(() => fileListHeading.current?.focus({ preventScroll: true }));
      });
      if (!removed) setDeleteFailed(true);
    } finally { deleteLock.current = false; setDeleting(false); }
  }
  return <div className="rd-input-workface">
    <section className={`rd-section rd-input-sources${sourcesOpen ? '' : ' is-collapsed'}`} aria-labelledby="rd-input-sources-title">
      <div className="rd-section-head rd-input-sources-heading">
        <div className="rd-input-sources-summary"><h3 id="rd-input-sources-title">编制资料</h3><span>{activeSources.length} 份</span></div>
        <Button type="text" icon={sourcesOpen ? <DownOutlined /> : <RightOutlined />} aria-label={sourcesOpen ? '收起编制资料' : '展开编制资料'} aria-expanded={sourcesOpen} aria-controls="rd-input-sources-content" disabled={queuePending} onClick={() => setSourcesExpanded(value => !value)}>{sourcesOpen ? '收起' : '展开'}</Button>
      </div>
      {/* Keep upload files, classification and retry state mounted when collapsed. */}
      <div id="rd-input-sources-content" hidden={!sourcesOpen}>
      <BatchSourceUpload projectId={project.id} projectVersion={project.version} researchCase={researchCase} modelSelection={model} busy={busy} onBatchUpload={onBatchUpload} onQueueChange={setQueuePending} />
      <div className="rd-current-files"><h4 ref={fileListHeading} tabIndex={-1}>当前资料{activeSources.length > 0 && <span>{activeSources.length} 份</span>}</h4>{activeSources.length ? <div className="rd-source-file-grid">{activeSources.map(renderSource)}</div> : <p className="rd-quiet-state">尚未添加资料。选择文件并上传后，会显示在这里。</p>}</div>
      {historicalSources.length > 0 && <details className="rd-source-history"><summary>历史资料 <span>{historicalSources.length} 份</span></summary><div className="rd-source-file-grid">{historicalSources.map(renderSource)}</div></details>}
      </div>
    </section>
    <SourceAnalysisPanel project={project} researchCase={researchCase} busy={busy} error={error} blockedByDraft={modelDirty || queuePending} pendingUpload={queuePending} command={command} onAnalyze={analyzeWithModel} onReviewClarification={onReviewClarification} renderModelControls={analyzeButton => <div className="rd-context-form rd-analysis-model-settings">
      <div className="rd-analysis-controls"><div className="rd-field rd-analysis-model-field">
        <label id="rd-model-label" htmlFor="rd-model">编制模型</label>
        <StyledSelect id="rd-model" aria-labelledby="rd-model-label" aria-describedby={modelError ? 'rd-model-error' : undefined} value={modelKey} options={modelOptions} onChange={selectModel} disabled={busy} />
      </div>{analyzeButton}</div>
      {modelError && <p id="rd-model-error" className="rd-error" role="alert">{modelError} <PlatformButton className="rd-link-button" type="button" onClick={() => setModelRevision(value => value + 1)}>重新获取</PlatformButton></p>}
      {modelDirty && hasDecisions && <p className="rd-warning">使用新模型分析后，需要重新确认资料与原有决定。已有成果和历史记录保留。</p>}
    </div>} />
    {deleteTarget && <FeedbackConfirmDialog title="删除资料" confirm="删除资料" danger pending={busy || deleting} error={deleteFailed ? error || '删除未完成，请重试。' : undefined} onCancel={() => setDeleteTarget(null)} onConfirm={() => void deleteSource()}>
      <p className="rd-source-delete-name">删除“{deleteTarget.name}”？</p>
      <p>{isCurrentSource(deleteTarget, researchCase.source_selection) ? '该文件将不再用于本次分析，需重新分析并确认资料。' : '该文件将从历史资料列表中移除。'}已有成果和审计记录保留。</p>
    </FeedbackConfirmDialog>}
    {sourceChange && <FeedbackConfirmDialog title="采用历史资料" confirm="采用并重新确认" pending={busy} error={error} onCancel={() => setSourceChange(null)} onConfirm={() => {
      void command('select_source', { role: sourceChange.role, source_id: sourceChange.id }, () => setSourceChange(null));
    }}>
      <p>将采用“{sourceChange.name} · v{sourceChange.version}”作为当前{sourceChange.role === 'tech' ? '技术资料' : '规范标准'}。</p>
      <p>案例将回到资料输入，原阶段决定失效，产品研制分类与任务书编制策略需要重新确认。历史资料保留，已有工作包的输入快照与成果保持原样。</p>
      <p>引用旧资料的需求需要更新来源后再确认；未保存的填写继续保留。</p>
    </FeedbackConfirmDialog>}
  </div>;
}
