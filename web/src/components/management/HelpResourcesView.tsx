import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  addHelpResourceLink, deleteHelpResource, getAdminHelpResources, helpResourceDownloadUrl, uploadHelpResource,
  type HelpResource, type HelpResourceKind,
} from '../../api/helpResources';
import { FeedbackConfirmDialog } from '../feedback/FeedbackDialog';
import { feedbackTime } from '../feedback/feedbackPresentation';
import { StyledSelect } from '../ui/StyledSelect';
import { useAdminUnsavedChanges } from './adminDrafts';
import './helpResources.css';

const kindLabels: Record<HelpResourceKind, string> = { video: '操作视频', manual: '操作手册' };
const kindOptions = [{ value: 'video', label: kindLabels.video }, { value: 'manual', label: kindLabels.manual }];
const fileTypes: Record<HelpResourceKind, { accept: string; limit: number; hint: string }> = {
  video: { accept: '.mp4,.webm,.ogg', limit: 500 * 1024 * 1024, hint: '支持 MP4、WebM、OGG，每个文件不超过 500 MiB。' },
  manual: { accept: '.pdf,.doc,.docx', limit: 50 * 1024 * 1024, hint: '支持 PDF、DOC、DOCX，每个文件不超过 50 MiB。' },
};

function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}

export function HelpResourcesView({ active }: { active: boolean }) {
  const [items, setItems] = useState<HelpResource[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [revision, setRevision] = useState(0);
  const [filter, setFilter] = useState('all');
  const [kind, setKind] = useState<HelpResourceKind>('video');
  const [source, setSource] = useState<'file' | 'link'>('file');
  const [title, setTitle] = useState('');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [progress, setProgress] = useState(0);
  const [formError, setFormError] = useState('');
  const [notice, setNotice] = useState('');
  const [remove, setRemove] = useState<HelpResource | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const alive = useRef(true);
  const pending = useRef(false);
  const mutation = useRef<AbortController>();
  const listRequest = useRef<AbortController>();
  const titleField = useRef<HTMLInputElement>(null);
  const urlField = useRef<HTMLInputElement>(null);
  const fileField = useRef<HTMLInputElement>(null);
  const listTitle = useRef<HTMLHeadingElement>(null);
  useAdminUnsavedChanges(Boolean(title.trim() || url.trim() || file || saving));

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; mutation.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController(); listRequest.current = controller;
    setLoading(true); setLoadError('');
    Promise.all([getAdminHelpResources('video', controller.signal), getAdminHelpResources('manual', controller.signal)]).then(results => {
      if (!controller.signal.aborted) setItems(results.flatMap(result => result.items).sort((a, b) => b.created_at.localeCompare(a.created_at)));
    }).catch(cause => {
      if (!controller.signal.aborted) setLoadError(cause instanceof Error ? cause.message : '资料列表读取失败，请重试。');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); if (listRequest.current === controller) listRequest.current = undefined; };
  }, [active, revision]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (pending.current) return;
    const resourceTitle = title.trim();
    if (!resourceTitle) { setFormError('请填写资料标题，方便用户识别内容。'); titleField.current?.focus(); return; }
    if (source === 'file') {
      if (!file) { setFormError('请选择要上传的原文件。'); fileField.current?.focus(); return; }
      const extension = `.${file.name.split('.').pop()?.toLowerCase()}`;
      if (!fileTypes[kind].accept.split(',').includes(extension)) {
        setFormError(`文件格式不支持。${fileTypes[kind].hint}`); fileField.current?.focus(); return;
      }
      if (file.size === 0 || file.size > fileTypes[kind].limit) {
        setFormError(file.size === 0 ? '该文件为空，请重新选择。' : `文件过大。${fileTypes[kind].hint}`); fileField.current?.focus(); return;
      }
    } else {
      try {
        const parsed = new URL(url.trim());
        if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') throw new Error();
      } catch { setFormError('请填写完整的 HTTP 或 HTTPS 链接。'); urlField.current?.focus(); return; }
    }
    pending.current = true; setSaving(true); setProgress(0); setFormError(''); setNotice('');
    const controller = new AbortController(); mutation.current = controller;
    try {
      const result = source === 'file'
        ? await uploadHelpResource({ kind, title: resourceTitle, file: file! }, { signal: controller.signal, onProgress: setProgress })
        : await addHelpResourceLink({ kind, title: resourceTitle, source_url: url.trim() }, controller.signal);
      if (!alive.current || controller.signal.aborted) return;
      listRequest.current?.abort();
      setItems(current => [result.item, ...current.filter(item => item.id !== result.item.id)]);
      setTitle(''); setUrl(''); setFile(null); if (fileField.current) fileField.current.value = '';
      setNotice(`已添加${kindLabels[kind]}「${result.item.title}」，用户可在主页查看。`);
      setRevision(value => value + 1);
      if (active) requestAnimationFrame(() => titleField.current?.focus());
    } catch (cause) {
      if (alive.current && !controller.signal.aborted) setFormError(cause instanceof Error ? cause.message : '资料保存失败，请重试。');
    } finally {
      if (mutation.current === controller) mutation.current = undefined;
      if (alive.current) { pending.current = false; setSaving(false); }
    }
  }

  async function confirmRemove() {
    if (!remove || pending.current) return;
    const resource = remove;
    pending.current = true; setDeleting(true); setDeleteError(''); setNotice('');
    const controller = new AbortController(); mutation.current = controller;
    try {
      await deleteHelpResource(resource.id, controller.signal);
      if (!alive.current || controller.signal.aborted) return;
      listRequest.current?.abort(); setItems(current => current.filter(item => item.id !== resource.id));
      setRemove(null); setNotice(`已删除「${resource.title}」。`); setRevision(value => value + 1);
      if (active) requestAnimationFrame(() => listTitle.current?.focus());
    } catch (cause) {
      if (alive.current && !controller.signal.aborted) setDeleteError(cause instanceof Error ? cause.message : '资料删除失败，请重试。');
    } finally {
      if (mutation.current === controller) mutation.current = undefined;
      if (alive.current) { pending.current = false; setDeleting(false); }
    }
  }

  const visibleItems = items.filter(item => filter === 'all' || item.kind === filter);
  const busy = saving || deleting;

  return <div className="admin-help-resources">
    <form className="help-resource-form" noValidate onSubmit={event => void save(event)} aria-label="添加操作资料" aria-busy={saving}>
      <div className="help-resource-form-heading"><h3>添加操作资料</h3><p>上传原文件或添加已有链接。每个分类可添加多份资料，所有管理员均可维护。</p></div>
      <div className="help-resource-form-fields">
        <div className="help-resource-field"><label id="help-resource-kind-label" htmlFor="help-resource-kind">资料分类</label>
          <StyledSelect id="help-resource-kind" aria-labelledby="help-resource-kind-label" value={kind} options={kindOptions} disabled={busy}
            onChange={value => { setKind(value as HelpResourceKind); setFormError(''); }} /></div>
        <div className="help-resource-field"><label id="help-resource-source-label" htmlFor="help-resource-source">添加方式</label>
          <StyledSelect id="help-resource-source" aria-labelledby="help-resource-source-label" value={source} disabled={busy}
            options={[{ value: 'file', label: '上传原文件' }, { value: 'link', label: '添加链接' }]}
            onChange={value => { setSource(value as 'file' | 'link'); setFormError(''); }} /></div>
        <div className="help-resource-field help-resource-title-field"><label htmlFor="help-resource-title">资料标题 <span>必填</span></label>
          <input ref={titleField} id="help-resource-title" value={title} maxLength={200} required disabled={busy} placeholder="例如：研制任务书生成操作演示"
            aria-describedby={formError ? 'help-resource-form-error' : undefined} onChange={event => { setTitle(event.target.value); setFormError(''); }} /></div>
        <div className="help-resource-field help-resource-source-field" hidden={source !== 'file'}><label htmlFor="help-resource-file">选择原文件 <span>必填</span></label>
          <input ref={fileField} id="help-resource-file" type="file" accept={fileTypes[kind].accept} required={source === 'file'} disabled={busy} aria-describedby={`help-resource-file-hint${formError ? ' help-resource-form-error' : ''}`}
            onChange={event => { setFile(event.target.files?.[0] || null); setFormError(''); }} />
          <p id="help-resource-file-hint" className="help-resource-hint">{fileTypes[kind].hint}</p>
          {file && <p className="help-resource-selected-file">已选择：{file.name} <span>（{fileSize(file.size)}）</span></p>}
        </div>
        <div className="help-resource-field help-resource-source-field" hidden={source !== 'link'}><label htmlFor="help-resource-url">资料链接 <span>必填</span></label>
          <input ref={urlField} id="help-resource-url" type="url" value={url} maxLength={2048} required={source === 'link'} disabled={busy} placeholder="https://example.com/help"
            autoCapitalize="none" spellCheck={false} aria-describedby={`help-resource-link-hint${formError ? ' help-resource-form-error' : ''}`}
            onChange={event => { setUrl(event.target.value); setFormError(''); }} />
          <p id="help-resource-link-hint" className="help-resource-hint">仅支持 HTTP 或 HTTPS 链接。请确认使用者具有访问权限。</p>
        </div>
      </div>
      {saving && source === 'file' && <div className="help-resource-progress"><label htmlFor="help-resource-upload-progress">{progress < 100 ? `正在上传 ${progress}%` : '上传完成，正在保存资料…'}</label>
        <progress id="help-resource-upload-progress" max={100} value={progress} /></div>}
      {formError && <p id="help-resource-form-error" role="alert" className="feedback-error">{formError}</p>}
      <div className="help-resource-form-actions"><button type="submit" className="feedback-button primary" disabled={busy}>
        {saving ? source === 'file' ? '正在上传…' : '正在保存…' : source === 'file' ? '上传资料' : '保存链接'}</button>
        <p className="help-resource-hint">保存后将显示在主页对应的操作资料入口。</p></div>
    </form>
    {notice && <p role="status" className="feedback-notice help-resource-notice">{notice}</p>}
    <section className="help-resource-list-section" aria-labelledby="help-resource-list-title" aria-busy={loading}>
      <div className="help-resource-list-heading"><div><h3 id="help-resource-list-title" ref={listTitle} tabIndex={-1}>已发布资料</h3>
        <p>查看原文件或链接，删除后用户将无法再从主页访问该条资料。</p></div>
        <div className="help-resource-list-actions"><StyledSelect id="help-resource-filter" aria-label="筛选资料分类" value={filter}
          options={[{ value: 'all', label: '全部资料' }, ...kindOptions]} onChange={setFilter} />
          <button type="button" className="feedback-button" disabled={loading || busy} onClick={() => setRevision(value => value + 1)}>刷新列表</button></div>
      </div>
      {loadError && <div className="feedback-error" role="alert"><p>{loadError}</p><button type="button" className="feedback-link" onClick={() => setRevision(value => value + 1)}>重试加载资料</button></div>}
      {loading && <p className="help-resource-loading" role="status">正在读取资料列表…</p>}
      {!loading && !loadError && visibleItems.length === 0 && <div className="feedback-empty"><p>{filter === 'all' ? '暂无操作资料' : `暂无${kindLabels[filter as HelpResourceKind]}`}</p><p>使用上方表单上传原文件或添加链接。</p></div>}
      {visibleItems.length > 0 && <><ul className="admin-help-resource-list">{visibleItems.map(item => {
        const href = item.source_type === 'file' ? item.content_url : item.source_url;
        const download = item.source_type === 'file' ? helpResourceDownloadUrl(item) : null;
        return <li key={item.id} className="help-resource-row"><div className="help-resource-details"><div className="help-resource-row-title"><h4>{item.title}</h4><span className="help-resource-kind">{kindLabels[item.kind]}</span></div>
          <p className="help-resource-origin">{item.source_type === 'file' ? item.filename : item.source_url}</p>
          <p className="help-resource-meta"><span>{item.source_type === 'file' ? `原文件${item.size_bytes !== null ? ` · ${fileSize(item.size_bytes)}` : ''}` : '外部链接'}</span>
            <span>添加于 <time dateTime={item.created_at}>{feedbackTime(item.created_at)}</time>（北京时间）</span><span>添加人：{item.created_by || '管理员'}</span></p>
        </div><div className="help-resource-row-actions">
          {href && <a className="feedback-button" href={href} target="_blank" rel="noopener noreferrer" aria-label={`查看${item.source_type === 'file' ? '原文件' : '链接'}：${item.title}`}>{item.source_type === 'file' ? '查看原文件' : '打开链接'}</a>}
          {download && <a className="feedback-link" href={download} aria-label={`下载原文件：${item.title}`}>下载</a>}
          <button type="button" className="feedback-link danger-text" disabled={busy} aria-label={`删除资料：${item.title}`}
            onClick={() => { setRemove(item); setDeleteError(''); }}>删除</button>
        </div></li>;
      })}</ul><p className="help-resource-count">共 {visibleItems.length} 份{filter === 'all' ? '资料' : kindLabels[filter as HelpResourceKind]}</p></>}
    </section>
    {remove && <FeedbackConfirmDialog title="删除操作资料" confirm="确认删除" danger visible={active} pending={deleting} error={deleteError}
      onCancel={() => setRemove(null)} onConfirm={() => void confirmRemove()}>
      <p className="help-resource-delete-message">确认删除「{remove.title}」？{remove.source_type === 'file' ? '此操作会删除已上传的原文件，无法撤销。' : '此操作会移除资料入口，不会删除链接指向的内容。'}</p>
    </FeedbackConfirmDialog>}
  </div>;
}
