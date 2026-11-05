import { useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import { Button, Radio } from 'antd';
import { DeleteOutlined, FileOutlined, InboxOutlined } from '@ant-design/icons';
import { PlatformButton } from '../../components/ui/PlatformButton';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { makeRequestKey, rdClassifySources } from './api';
import { formatSize } from './presentation';
import {
  appendSourceFiles, applySourceSuggestions, choosePrimarySource, createSourceBatchAttempt,
  emptySourceQueue, moveSourceFile, reconcileSourcePrimary, removeSourceFile, sourceQueueIssue,
  type ExistingPrimarySources, type SourceBatchAttempt, type SourceCategory, type SourceQueue,
} from './sourceUploadQueue';
import type { ModelSelection, ResearchCase, SourceBatchRunner } from './types';
import './batchSourceUpload.css';

const categories: Array<{ id: SourceCategory; title: string }> = [
  { id: 'tech', title: '需求文件' }, { id: 'spec', title: '产品规范' },
  { id: 'reference', title: '补充资料' }, { id: 'unknown', title: '待分类' },
];
const DRAG_TYPE = 'application/x-rd-source-id';

export function BatchSourceUpload({ projectId, projectVersion, researchCase, modelSelection, busy, onBatchUpload, onQueueChange }: {
  projectId: string; projectVersion: number; researchCase: ResearchCase; modelSelection: ModelSelection;
  busy: boolean; onBatchUpload: SourceBatchRunner; onQueueChange: (pending: boolean) => void;
}) {
  const existing = useMemo<ExistingPrimarySources>(() => Object.fromEntries((['tech', 'spec'] as const).flatMap(role => {
    const id = researchCase.source_selection?.[role];
    return id && researchCase.sources.some(source => source.id === id && source.role === role) ? [[role, id]] : [];
  })), [researchCase.source_selection, researchCase.sources]);
  const existingRef = useRef(existing);
  existingRef.current = existing;
  const [queue, setQueue] = useState(() => emptySourceQueue(existing));
  const queueRef = useRef(queue);
  const [messages, setMessages] = useState<string[]>([]);
  const [failure, setFailure] = useState('');
  const [saving, setSaving] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [confirmation, setConfirmation] = useState<SourceBatchAttempt | null>(null);
  const attempt = useRef<SourceBatchAttempt | null>(null);
  const requestLock = useRef(false);
  const mounted = useRef(true);
  const controllers = useRef(new Set<AbortController>());
  const input = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const locked = busy || saving || uncertain || !!confirmation || researchCase.status === 'completed';
  const pending = queue.items.length > 0 || saving || uncertain;
  const queueIssue = sourceQueueIssue(queue);

  function updateQueue(change: (current: SourceQueue) => SourceQueue) {
    const next = change(queueRef.current);
    queueRef.current = next; setQueue(next);
  }
  function abortClassification() { controllers.current.forEach(controller => controller.abort()); controllers.current.clear(); }
  useEffect(() => { onQueueChange(pending); }, [pending, onQueueChange]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; abortClassification(); onQueueChange(false); };
  }, [onQueueChange]);
  useEffect(() => {
    if (!uncertain && !saving && !confirmation) updateQueue(current => reconcileSourcePrimary(current, existing));
  }, [existing, uncertain, saving, confirmation]);

  function addFiles(files: File[], role: SourceCategory = 'unknown') {
    if (locked) return;
    const result = appendSourceFiles(queueRef.current, files, existingRef.current, makeRequestKey, role);
    updateQueue(() => result.queue);
    setFailure(''); setMessages(current => [...new Set([...current, ...result.issues])]);
    if (!result.accepted.length) return;
    onQueueChange(true);
    if (role !== 'unknown') return;
    const requested = result.queue.items.filter(item => result.accepted.includes(item.id));
    const controller = new AbortController(); controllers.current.add(controller);
    void rdClassifySources(projectId, researchCase.id, requested.map(item => ({ id: item.id, name: item.file.name })), modelSelection, true, controller.signal)
      .then(response => {
        if (!mounted.current || controller.signal.aborted) return;
        updateQueue(current => applySourceSuggestions(current, response.items ?? [], result.accepted, existingRef.current));
        setMessages(current => [...new Set([...current, ...(response.warnings ?? [])])]);
      }).catch(() => {
        if (!mounted.current || controller.signal.aborted) return;
        updateQueue(current => applySourceSuggestions(current, [], result.accepted, existingRef.current));
        setMessages(current => [...new Set([...current, '文件名识别未完成，请手动选择资料用途。'])]);
      }).finally(() => controllers.current.delete(controller));
  }
  function drop(event: DragEvent<HTMLElement>, role?: SourceCategory) {
    event.preventDefault(); event.stopPropagation();
    if (locked) return;
    const id = event.dataTransfer.getData(DRAG_TYPE);
    if (id && role) updateQueue(current => moveSourceFile(current, id, role, existingRef.current));
    else if (event.dataTransfer.files.length) addFiles(Array.from(event.dataTransfer.files), role ?? 'unknown');
  }
  async function submit(snapshot: SourceBatchAttempt) {
    if (requestLock.current || busy || researchCase.status === 'completed') return;
    requestLock.current = true; attempt.current = snapshot; abortClassification();
    setSaving(true); setFailure('');
    try {
      const result = await onBatchUpload(researchCase.id, snapshot.items, snapshot.key, snapshot.expectedVersion);
      if (!mounted.current) return;
      setConfirmation(null);
      if (result.ok) {
        attempt.current = null; setUncertain(false); setMessages([]);
        updateQueue(() => emptySourceQueue(existingRef.current));
        if (input.current) input.current.value = '';
        requestAnimationFrame(() => heading.current?.focus({ preventScroll: true }));
      } else {
        setUncertain(!!result.uncertain);
        if (!result.uncertain) attempt.current = null;
        setFailure(result.message || (result.uncertain ? '上传结果尚未确认，请重试核对同一批资料。' : '上传未完成，文件已保留，请调整或重试。'));
      }
    } catch {
      if (!mounted.current) return;
      setConfirmation(null); setUncertain(true);
      setFailure('上传结果尚未确认，文件与原请求已保留，请重试核对。');
    } finally {
      requestLock.current = false;
      if (mounted.current) setSaving(false);
    }
  }
  function prepareUpload() {
    if (locked || queueIssue) return;
    const snapshot = createSourceBatchAttempt(queueRef.current, makeRequestKey(), projectVersion);
    const replacesPrimary = snapshot.items.some(item => item.primary && item.role !== 'reference' && existingRef.current[item.role]);
    if (replacesPrimary || researchCase.stage !== 'input' || researchCase.decisions.some(item => !item.invalidated_at)) setConfirmation(snapshot);
    else void submit(snapshot);
  }

  return <section className="rd-batch-upload" aria-labelledby="rd-batch-upload-title" aria-busy={saving}>
    <div className="rd-batch-upload-heading"><h4 id="rd-batch-upload-title" ref={heading} tabIndex={-1}>添加编制资料</h4><span>{queue.items.length ? `${queue.items.length} 份待上传` : '每批最多 50 份'}</span></div>
    <div className={`rd-batch-dropzone${locked ? ' is-disabled' : ''}`} onDragOver={event => event.preventDefault()} onDrop={event => drop(event)}>
      <InboxOutlined aria-hidden="true" />
      <p>将文件拖到这里，或选择多份文件</p>
      <PlatformButton disabled={locked} onClick={() => input.current?.click()}>选择资料文件</PlatformButton>
      <input ref={input} id="rd-source-file" className="rd-batch-file-input" type="file" multiple aria-label="选择资料文件" disabled={locked}
        onChange={event => { addFiles(Array.from(event.currentTarget.files ?? [])); event.currentTarget.value = ''; }} />
      <small>自动建议用途，可拖动文件或用下拉调整。需求与规范各采用一份主文件，其余保留为补充资料。</small>
    </div>
    {!!queue.items.length && <div className="rd-batch-groups">
      {categories.map(category => {
        const primaryRole = category.id === 'tech' || category.id === 'spec' ? category.id : undefined;
        const items = queue.items.filter(item => item.role === category.id);
        const existingSource = primaryRole && researchCase.sources.find(source => source.id === existing[primaryRole]);
        return <section key={category.id} className={`rd-batch-group is-${category.id}`} aria-label={`${category.title}分组`}
          onDragOver={event => event.preventDefault()} onDrop={event => drop(event, category.id)}>
          <h5>{category.title}<span>{items.length} 份</span></h5>
          {existingSource && primaryRole && <Radio className="rd-batch-existing" name={`rd-batch-primary-${primaryRole}`} checked={queue.primary[primaryRole] === 'existing'} disabled={locked}
            onChange={() => updateQueue(current => choosePrimarySource(current, primaryRole, 'existing', existingRef.current))}>保留当前主文件：{existingSource.name}</Radio>}
          {!items.length && <p className="rd-batch-group-empty">可将文件拖到此组</p>}
          {items.map(item => <article key={item.id} className="rd-batch-file" draggable={!locked} aria-label={`待上传文件：${item.file.name}`}
            onDragStart={event => { event.dataTransfer.setData(DRAG_TYPE, item.id); event.dataTransfer.effectAllowed = 'move'; }}>
            <div className="rd-batch-file-heading"><FileOutlined aria-hidden="true" /><strong>{item.file.name}</strong><Button type="text" icon={<DeleteOutlined />} disabled={locked} aria-label={`移除待上传文件“${item.file.name}”`}
              onClick={() => { updateQueue(current => removeSourceFile(current, item.id, existingRef.current)); setFailure(''); }} /></div>
            <p className="rd-batch-file-meta">{formatSize(item.file.size)} · {item.classifying ? '正在识别用途…' : primaryRole && queue.primary[primaryRole] === item.id ? '主文件' : category.id === 'unknown' ? '请选择用途' : '补充资料'}</p>
            <StyledSelect aria-label={`调整“${item.file.name}”用途`} value={item.role} disabled={locked}
              options={categories.map(option => ({ value: option.id, label: option.title }))}
              onChange={value => updateQueue(current => moveSourceFile(current, item.id, value as SourceCategory, existingRef.current))} />
            {primaryRole && <Radio name={`rd-batch-primary-${primaryRole}`} checked={queue.primary[primaryRole] === item.id} disabled={locked}
              onChange={() => updateQueue(current => choosePrimarySource(current, primaryRole, item.id, existingRef.current))}>作为主文件</Radio>}
            {!!item.reason && <small className="rd-batch-file-reason">{item.reason}</small>}
          </article>)}
        </section>;
      })}
    </div>}
    {!!messages.length && <div className="rd-batch-notices" role="status">{messages.map(message => <p key={message}>{message}</p>)}</div>}
    {failure && <p className="rd-error" role="alert">{failure}</p>}
    {uncertain && <p className="rd-warning">本批文件已锁定。重试会核对原请求，保持相同文件、版本和主文件选择。</p>}
    {!!queue.items.length && <div className="rd-batch-actions"><p>{!uncertain && queueIssue || (uncertain ? '请先确认本批上传结果。' : '分类与主文件选择已就绪。')}</p><div>
      <PlatformButton disabled={locked} onClick={() => { abortClassification(); updateQueue(() => emptySourceQueue(existingRef.current)); setFailure(''); setMessages([]); }}>清空待上传</PlatformButton>
      <PlatformButton className="rd-button primary" disabled={busy || saving || (!uncertain && !!queueIssue)} onClick={() => uncertain && attempt.current ? void submit(attempt.current) : prepareUpload()}>
        {saving ? '正在上传…' : uncertain ? '重试核对上传' : `上传 ${queue.items.length} 份资料`}
      </PlatformButton>
    </div></div>}
    {confirmation && <FeedbackConfirmDialog title="更新编制资料" confirm="上传并重新确认" pending={saving || busy} onCancel={() => setConfirmation(null)} onConfirm={() => void submit(confirmation)}>
      <p>将保存本批 {confirmation.items.length} 份资料，并采用明确标记的主文件。原主文件与补充资料均保留。</p>
      <p>当前分析及后续业务依据将失效，需要重新核对；已有工作包的固定输入、成果与审计记录保留。</p>
    </FeedbackConfirmDialog>}
  </section>;
}
