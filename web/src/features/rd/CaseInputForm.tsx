import { useEffect, useRef, useState, type FormEvent } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { formatTime, formatSize, isCurrentSource } from './presentation';
import type { ModelSelection, Project, ResearchCase, Source } from './types';
import type { CommandRunner } from './WorkpackagePanel';
import { sourceUrl } from './api';
import { loadModelCatalog } from '../../api/catalog';
import { SourceAnalysisPanel } from './SourceAnalysisPanel';

export function CaseInputForm({ project, researchCase, busy, error, command, onAnalyze, onUpload, onDirtyChange }: { project: Project; researchCase: ResearchCase; busy: boolean; error: string; command: CommandRunner; onAnalyze: (caseId: string) => Promise<boolean>; onUpload: (caseId: string, file: File, role: string, success: () => void) => Promise<void>; onDirtyChange: (dirty: boolean) => void }) {
  const [model, setModel] = useState<ModelSelection>(researchCase.model_selection ?? { provider: '', name: '', id: '' });
  const [modelBase, setModelBase] = useState(JSON.stringify(model));
  const [models, setModels] = useState<ModelSelection[]>([]);
  const [modelError, setModelError] = useState('');
  const [modelRevision, setModelRevision] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [role, setRole] = useState('tech');
  const fileInput = useRef<HTMLInputElement>(null);
  const modelSection = useRef<HTMLDetailsElement>(null);
  const [sourceError, setSourceError] = useState('');
  const [sourceChange, setSourceChange] = useState<{ kind: 'select'; source: Source } | { kind: 'upload'; file: File; role: string } | null>(null);
  const modelDirty = JSON.stringify(model) !== modelBase;
  const activeSources = researchCase.sources.filter(source => isCurrentSource(source, researchCase.source_selection));
  const historicalSources = researchCase.sources.filter(source => !isCurrentSource(source, researchCase.source_selection));
  const hasDecisions = researchCase.decisions.some(decision => !decision.invalidated_at);
  useEffect(() => { onDirtyChange(modelDirty || !!file); }, [modelDirty, file, onDirtyChange]);
  useEffect(() => {
    if (modelDirty) return;
    const nextModel = researchCase.model_selection ?? { provider: '', name: '', id: '' };
    setModel(nextModel); setModelBase(JSON.stringify(nextModel));
  }, [researchCase.model_selection, modelDirty]);
  useEffect(() => {
    let active = true;
    void loadModelCatalog().then(response => {
      if (!active) return;
      setModels((response.models ?? []).map(item => ({ provider: item.provider ?? '', name: item.name ?? item.model ?? '', id: item.id ?? '' })));
      setModelError(response.success === false ? response.error ?? '模型列表暂时不可用' : '');
    }).catch(reason => { if (active) setModelError(reason instanceof Error ? reason.message : '模型列表暂时不可用'); });
    return () => { active = false; };
  }, [modelRevision]);
  const modelKey = JSON.stringify(model);
  const modelOptions = [{ value: JSON.stringify({ provider: '', name: '', id: '' }), label: '使用平台默认模型' }, ...models.map(item => ({ value: JSON.stringify(item), label: `${item.provider} · ${item.name}` }))];
  if (model.provider && !modelOptions.some(option => option.value === modelKey)) modelOptions.push({ value: modelKey, label: `${model.provider} · ${model.name}（已保存）` });
  function uploadSource(event: FormEvent) {
    event.preventDefault();
    if (!file || !file.size) { setSourceError('请选择一份非空的资料文件。'); fileInput.current?.focus(); return; }
    setSourceError('');
    if (role !== 'reference' && (researchCase.source_selection?.[role as 'tech' | 'spec'] || researchCase.stage !== 'input' || hasDecisions)) setSourceChange({ kind: 'upload', file, role });
    else void saveUploadedSource(file, role);
  }
  async function saveUploadedSource(selectedFile: File, selectedRole: string) {
    setUploading(true);
    try { await onUpload(researchCase.id, selectedFile, selectedRole, () => { setFile(null); if (fileInput.current) fileInput.current.value = ''; setSourceChange(null); }); }
    finally { setUploading(false); }
  }
  function focusModel() {
    if (modelSection.current) modelSection.current.open = true;
    requestAnimationFrame(() => { const field = document.getElementById('rd-model'); field?.focus(); field?.scrollIntoView({ block: 'center', behavior: 'auto' }); });
  }
  function renderSource(source: Source) {
    const current = isCurrentSource(source, researchCase.source_selection);
    return <div key={source.id} className="rd-source-row">
      <div className="rd-source-description"><div className="rd-source-heading"><a href={sourceUrl(project.id, researchCase.id, source.id)} target="_blank" rel="noreferrer">{source.name} ↗</a><span className={`rd-badge ${current ? 'completed' : 'draft'}`}>{current ? '当前输入' : '历史版本'}</span></div>
        <p>{{ tech: '技术资料', spec: '规范标准', reference: '参考资料' }[source.role]} · {formatSize(source.size)}</p>
        <details className="rd-source-record"><summary>资料记录</summary><p>版本 {source.version} · {formatTime(source.created_at)}</p><code>{source.id}<br />SHA-256 {source.sha256}</code></details>
      </div>
      {!current && source.role !== 'reference' && <button type="button" className="rd-button compact" disabled={busy || researchCase.status === 'completed'} onClick={() => setSourceChange({ kind: 'select', source })}>采用此版本</button>}
    </div>;
  }
  return <div className="rd-input-workface">
    <section className="rd-section rd-input-sources" aria-labelledby="rd-input-sources-title">
      <div className="rd-section-head"><div><h3 id="rd-input-sources-title">编制资料</h3><p>添加本次任务书使用的技术资料、规范标准或参考文件。</p></div></div>
      <form noValidate className="rd-upload-form" onSubmit={uploadSource}>
        <div className="rd-field"><label id="rd-source-role-label">资料用途</label><StyledSelect aria-labelledby="rd-source-role-label" value={role} options={[{ value: 'tech', label: '技术资料' }, { value: 'spec', label: '规范标准' }, { value: 'reference', label: '参考资料' }]} onChange={setRole} disabled={busy} /></div>
        <div className="rd-field rd-file-picker"><label htmlFor="rd-source-file">选择资料文件</label><input ref={fileInput} id="rd-source-file" type="file" disabled={busy || researchCase.status === 'completed'} onChange={event => { setFile(event.target.files?.[0] ?? null); setSourceError(''); }} aria-describedby="rd-upload-help" /><small id="rd-upload-help">{file ? '已选择，上传后保存到本案例。' : role === 'reference' ? '参考资料可添加多份。' : '新文件会成为当前采用的资料。'}</small></div>
        <button type="submit" className="rd-button primary" disabled={busy || uploading || !file || researchCase.status === 'completed'}>{uploading ? '正在上传…' : role === 'reference' ? '上传资料' : '上传并采用'}</button>
        {sourceError && <p className="rd-error" role="alert">{sourceError}</p>}
      </form>
      <div className="rd-current-files"><h4>当前资料{activeSources.length > 0 && <span>{activeSources.length} 份</span>}</h4>{activeSources.length ? activeSources.map(renderSource) : <p className="rd-quiet-state">尚未添加资料。选择文件并上传后，会显示在这里。</p>}</div>
      {historicalSources.length > 0 && <details className="rd-source-history"><summary>历史资料 <span>{historicalSources.length} 份</span></summary><div>{historicalSources.map(renderSource)}</div></details>}
    </section>
    <SourceAnalysisPanel project={project} researchCase={researchCase} busy={busy} blockedByDraft={modelDirty || !!file} command={command} onAnalyze={onAnalyze} />
    <form noValidate className="rd-context-form rd-progressive-settings" onSubmit={event => { event.preventDefault(); void command('save_context', { context: researchCase.context, model_selection: model }, () => setModelBase(JSON.stringify(model))); }}>
      <details className="rd-input-disclosure" ref={modelSection}>
        <summary><span><strong>生成设置</strong><small>平台默认模型用于资料识别与任务书编制，可按需切换</small></span><span className={`rd-input-summary-state ${modelError ? 'rd-model-list-error' : ''}`}>{modelError ? '模型列表暂不可用' : model.name || '使用平台默认模型'}</span></summary>
        <div className="rd-input-disclosure-content"><div className="rd-field"><label id="rd-model-label" htmlFor="rd-model">编制模型</label><StyledSelect id="rd-model" aria-labelledby="rd-model-label" value={modelKey} options={modelOptions} onChange={value => setModel(JSON.parse(value) as ModelSelection)} disabled={busy} /><small>保存后用于后续资料分析与编制，实际调用模型会随结果记录。</small>{modelError && <p className="rd-error" role="alert">{modelError} <button className="rd-link-button" type="button" onClick={() => setModelRevision(value => value + 1)}>重新获取</button></p>}</div></div>
      </details>
      {(!!modelError) && <div className="rd-input-follow-up"><button type="button" className="rd-link-button" onClick={focusModel}>查看生成设置与重试 <span aria-hidden="true">→</span></button></div>}
      <div className="rd-settings-save" hidden={!modelDirty}><p className={hasDecisions ? 'rd-warning' : 'rd-muted'}>{hasDecisions ? '保存改动后，需要重新确认资料与原有决定。已有成果和历史记录保留。' : '模型设置尚未保存。'}</p><button type="submit" className="rd-button primary" disabled={busy}>{busy ? '正在保存…' : '保存模型设置'}</button></div>
    </form>
    {sourceChange && <FeedbackConfirmDialog title={sourceChange.kind === 'select' ? '采用历史资料' : '替换当前资料'} confirm="采用并重新确认" pending={busy} error={error} onCancel={() => setSourceChange(null)} onConfirm={() => {
      if (sourceChange.kind === 'select') void command('select_source', { role: sourceChange.source.role, source_id: sourceChange.source.id }, () => setSourceChange(null));
      else void saveUploadedSource(sourceChange.file, sourceChange.role);
    }}>
      <p>将采用“{sourceChange.kind === 'select' ? `${sourceChange.source.name} · v${sourceChange.source.version}` : sourceChange.file.name}”作为当前{(sourceChange.kind === 'select' ? sourceChange.source.role : sourceChange.role) === 'tech' ? '技术资料' : '规范标准'}。</p>
      <p>案例将回到资料输入，原阶段决定失效，产品研制分类与任务书编制策略需要重新确认。历史资料保留，已有工作包的输入快照与成果保持原样。</p>
      <p>引用旧资料的需求需要更新来源后再确认；未保存的填写继续保留。</p>
    </FeedbackConfirmDialog>}
  </div>;
}
