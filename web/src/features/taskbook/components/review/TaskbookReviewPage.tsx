import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent } from 'react';
import {
  annotateReviewRevision, checkReviewRevision, getReview, getReviewDocument, getReviewEditorStatus,
  getReviewLinks, restoreReviewRevision, reviewDownload, ReviewRequestError, saveReviewRevision,
  uploadReviewRevision, type ReviewAnnotation, type ReviewBundle, type ReviewChecks,
  type ReviewDocument, type ReviewLink, type ReviewOperation,
} from '../../api/review';
import { allElementIds, allParagraphs, elementPath, emptyReviewDraft, ReviewDocumentPane, type ReviewDraft } from './ReviewDocumentPane';
import { ReviewOfficeEditor } from './ReviewOfficeEditor';
import { StyledSelect } from '../../../../shared/ui/StyledSelect';
import './taskbookReview.css';

const sourceTabs = [{ role: 'tech', label: '需求文件' }, { role: 'template', label: '本次模板' }, { role: 'spec', label: '产品规范' }];
const time = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '时间未记录';
const checkLabel = (checks?: ReviewChecks) => ({ passed: '基础检查通过', failed: '检查未通过', blocked: '检查未通过', error: '检查失败', unchecked: '未检查', pending: '待重新检查', needs_review: '需人工核对' }[checks?.status || 'unchecked'] || '未检查');
const errorText = (reason: unknown) => reason instanceof Error ? reason.message : '请求失败，请重试。';

function scrollReviewTarget(container: HTMLDivElement | null, targetId: string, block: 'start' | 'center') {
  const target = document.getElementById(targetId);
  if (!container || !target || !container.contains(target) || !container.clientHeight) return false;
  const revealHorizontal = (scroller: HTMLElement) => {
    const rect = target.getBoundingClientRect();
    const left = scroller.getBoundingClientRect().left + scroller.clientLeft;
    const right = left + scroller.clientWidth;
    const delta = rect.left < left ? rect.left - left : rect.right > right ? Math.min(rect.left - left, rect.right - right) : 0;
    return scroller.scrollLeft + delta;
  };
  // A cell may be inside one or more wide tables, each with its own scrollbar.
  for (let parent = target.parentElement; parent && parent !== container; parent = parent.parentElement) {
    if (parent.classList.contains('review-table-scroll')) parent.scrollLeft = revealHorizontal(parent);
  }
  const targetRect = target.getBoundingClientRect();
  const margin = parseFloat(getComputedStyle(target).scrollMarginTop) || 0;
  const offset = block === 'center' ? Math.max(margin, (container.clientHeight - targetRect.height) / 2) : margin;
  // Scroll only the document, leaving the page, outline and toolbar in place.
  // CSS owns smooth scrolling and the reduced-motion preference.
  container.scrollTo({ top: container.scrollTop + targetRect.top - container.getBoundingClientRect().top - container.clientTop - offset,
    left: revealHorizontal(container), behavior: 'auto' });
  return true;
}

export function TaskbookReviewPage({ jid, taskContext, initialRevisionId, initialOperations = [], readOnly = false, onSelectedAnchor, onRevisionChanged, onPendingOperations, onDirtyChanged }: { jid: string; taskContext?: { projectId: string; taskId: string }; initialRevisionId?: string; initialOperations?: Record<string, unknown>[]; readOnly?: boolean; onSelectedAnchor?: (anchor: { id: string; text: string }) => void; onRevisionChanged?: (revisionId: string) => void; onPendingOperations?: (operations: Record<string, unknown>[]) => void; onDirtyChanged?: (dirty: boolean) => void }) {
  const rdProject = new URLSearchParams(window.location.search).get('rd_project');
  const returnPath = taskContext ? `/rd/${encodeURIComponent(taskContext.projectId)}/tasks/${encodeURIComponent(taskContext.taskId)}` : rdProject ? `/rd/${encodeURIComponent(rdProject)}?tab=artifacts` : '/taskbook';
  const returnLabel = taskContext ? '返回当前任务' : rdProject ? '返回研发项目' : '返回任务书工具';
  const [bundle, setBundle] = useState<ReviewBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [revisionId, setRevisionId] = useState('');
  const [output, setOutput] = useState<ReviewDocument | null>(null);
  const [outputError, setOutputError] = useState('');
  const [outputLoading, setOutputLoading] = useState(false);
  const [outputRetry, setOutputRetry] = useState(0);
  const [sourceRole, setSourceRole] = useState('tech');
  const [sourceAssetOverride, setSourceAssetOverride] = useState('');
  const [source, setSource] = useState<ReviewDocument | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError] = useState('');
  const [sourceRetry, setSourceRetry] = useState(0);
  const [links, setLinks] = useState<ReviewLink[]>([]);
  const [linkError, setLinkError] = useState('');
  const [selectedOutput, setSelectedOutput] = useState('');
  const [selectedSource, setSelectedSource] = useState('');
  const [activeLink, setActiveLink] = useState<ReviewLink | null>(null);
  const [linkNotice, setLinkNotice] = useState('点击任务书段落，可查看对应的来源证据。');
  const [rightTab, setRightTab] = useState<'review' | 'edit' | 'history' | 'office'>('review');
  const [treeTab, setTreeTab] = useState<'chapters' | 'pending'>('chapters');
  const [mobilePane, setMobilePane] = useState<'output' | 'source' | 'tree'>('output');
  const [split, setSplit] = useState(45);
  const panelArea = useRef<HTMLDivElement>(null);
  const sourceScroll = useRef<HTMLDivElement>(null);
  const positionedSourceLink = useRef<ReviewLink | null>(null);
  const outputScroll = useRef<HTMLDivElement>(null);
  const [outputScrollTarget, setOutputScrollTarget] = useState<{ id: string; block: 'start' | 'center' } | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState<ReviewDraft>(() => { const restored = emptyReviewDraft(); for (const op of initialOperations) { if (op.revision_id !== initialRevisionId || typeof op.element_id !== 'string') continue; if (op.op === 'replace_text') restored.replacements[op.element_id] = String(op.text || ''); if (op.op === 'insert_paragraph') restored.insertions[op.element_id] = String(op.text || ''); if (op.op === 'delete_paragraph') restored.deletions.push(op.element_id); } return restored; });
  const undo = useRef<ReviewDraft[]>([]);
  const [undoCount, setUndoCount] = useState(0);
  const [busy, setBusy] = useState('');
  const mutation = useRef(false);
  const [feedback, setFeedback] = useState<{ error: boolean; message: string; conflict?: boolean } | null>(null);
  const [note, setNote] = useState('');
  const [leaveAction, setLeaveAction] = useState<(() => void) | null>(null);
  const [restoreId, setRestoreId] = useState('');
  const [officeAvailable, setOfficeAvailable] = useState(false);
  const [officeDirty, setOfficeDirty] = useState(false);
  const [officeRevision, setOfficeRevision] = useState('');
  const officeContext = useRef({ tab: rightTab, revision: officeRevision });
  officeContext.current = { tab: rightTab, revision: officeRevision };
  const revision = bundle?.revisions.find(item => item.id === revisionId);
  const annotations = revision?.annotations || [];
  const annotation = annotations.find(item => item.element_id === selectedOutput);
  const noteDirty = Boolean(selectedOutput && note !== (annotation?.note || ''));
  const draftCount = Object.keys(draft.replacements).length + Object.keys(draft.insertions).length + draft.deletions.length;
  const dirty = draftCount > 0 || officeDirty || noteDirty;
  const nativeCallbacks = useRef({ onRevisionChanged, onPendingOperations, onDirtyChanged, onSelectedAnchor }); nativeCallbacks.current = { onRevisionChanged, onPendingOperations, onDirtyChanged, onSelectedAnchor };
  useEffect(() => { if (revisionId) nativeCallbacks.current.onRevisionChanged?.(revisionId); }, [revisionId]);
  useEffect(() => { nativeCallbacks.current.onDirtyChanged?.(dirty); return () => nativeCallbacks.current.onDirtyChanged?.(false); }, [dirty]);
  useEffect(() => { if (!revisionId) return; nativeCallbacks.current.onPendingOperations?.([
    ...Object.entries(draft.replacements).map(([element_id, text]) => ({ op: 'replace_text', element_id, text, revision_id: revisionId })),
    ...Object.entries(draft.insertions).map(([element_id, text]) => ({ op: 'insert_paragraph', element_id, text, position: 'after', revision_id: revisionId })),
    ...draft.deletions.map(element_id => ({ op: 'delete_paragraph', element_id, revision_id: revisionId })),
  ]); }, [draft, revisionId]);
  useEffect(() => { nativeCallbacks.current.onSelectedAnchor?.({ id: selectedOutput, text: allParagraphs(output?.blocks || []).find(item => item.id === selectedOutput)?.text || '' }); }, [selectedOutput, output]);
  useEffect(() => { const locate = (event: Event) => { const detail = (event as CustomEvent<{ jid: string; revisionId: string; anchor: string }>).detail; if (detail.jid !== jid || detail.revisionId !== revisionId) return; guard(() => { setRightTab('review'); setMobilePane('output'); setSelectedOutput(detail.anchor); setOutputScrollTarget({ id: detail.anchor, block: 'center' }); }); }; window.addEventListener('taskbook:locate-native-anchor', locate); return () => window.removeEventListener('taskbook:locate-native-anchor', locate); }, [jid, revisionId, dirty, busy]);
  const current = !readOnly && revisionId === bundle?.current_revision_id;
  const sourceAsset = bundle?.assets.find(item => item.id === sourceAssetOverride) || bundle?.assets.find(item => item.role === sourceRole);
  const outputParagraphs = useMemo(() => allParagraphs(output?.blocks || []), [output]);
  const outputIds = useMemo(() => allElementIds(output?.blocks || []), [output]);
  const sourceIds = useMemo(() => allElementIds(source?.blocks || []), [source]);
  const selectedParagraph = outputParagraphs.find(item => item.id === selectedOutput);
  const pendingParagraphs = outputParagraphs.filter(item => {
    const status = annotations.find(entry => entry.element_id === item.id)?.status;
    const excluded = links.some(link => link.rule_excluded && link.output_element_ids.includes(item.id));
    return !excluded && status !== 'checked' && (status === 'pending' || /待补充|待填写|人工填写|需核对|待确认/.test(item.text) || revision?.checks?.issues?.some(issue => issue.element_id === item.id));
  });
  const verifiedLink = activeLink?.status === 'verified' && sourceAsset?.id === activeLink.source_asset_id
    && activeLink.source_element_ids.length > 0 && activeLink.output_element_ids.length > 0
    && activeLink.source_element_ids.every(id => sourceIds.includes(id))
    && activeLink.output_element_ids.every(id => outputIds.includes(id));

  const reload = useCallback(async () => {
    setLoading(true); setLoadError('');
    try { const result = await getReview(jid); setBundle(result); setRevisionId(initialRevisionId && result.revisions.some(item => item.id === initialRevisionId) ? initialRevisionId : result.current_revision_id); }
    catch (reason) { setLoadError(errorText(reason)); }
    finally { setLoading(false); }
  }, [jid]);
  useEffect(() => { void reload(); void getReviewEditorStatus().then(result => setOfficeAvailable(result.configured)).catch(() => setOfficeAvailable(false)); }, [reload]);
  useEffect(() => {
    const old = document.title; document.title = `${bundle?.title || '任务书'} · 审阅模式`;
    return () => { document.title = old; };
  }, [bundle?.title]);
  useEffect(() => {
    if (!revisionId) return;
    const controller = new AbortController();
    setOutputLoading(true); setOutput(null); setOutputError(''); setLinks([]); setLinkError(''); setSelectedOutput(''); setActiveLink(null); setOutputScrollTarget(null);
    getReviewDocument(jid, { revision_id: revisionId }, controller.signal)
      .then(result => setOutput(result)).catch(reason => { if (!controller.signal.aborted) setOutputError(errorText(reason)); })
      .finally(() => { if (!controller.signal.aborted) setOutputLoading(false); });
    getReviewLinks(jid, revisionId, controller.signal).then(result => {
      setLinks(result.links); if (result.warnings?.length) setLinkError(result.warnings.join('；'));
    }).catch(reason => { if (!controller.signal.aborted) setLinkError(errorText(reason)); });
    return () => controller.abort();
  }, [jid, revisionId, outputRetry]);
  useEffect(() => {
    setSource(null); setSourceError(''); setSelectedSource('');
    if (!sourceAsset?.available) { setSourceLoading(false); return; }
    if (!['docx', 'doc'].includes(sourceAsset.format.toLowerCase())) { setSourceLoading(false); return; }
    const controller = new AbortController(); setSourceLoading(true);
    getReviewDocument(jid, { asset_id: sourceAsset.id }, controller.signal).then(setSource)
      .catch(reason => { if (!controller.signal.aborted) setSourceError(errorText(reason)); })
      .finally(() => { if (!controller.signal.aborted) setSourceLoading(false); });
    return () => controller.abort();
  }, [jid, sourceAsset?.id, sourceAsset?.available, sourceAsset?.format, sourceRetry]);
  useEffect(() => { setNote(annotation?.note || ''); }, [selectedOutput, annotation?.note, revisionId]);
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', handler); return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);
  useEffect(() => {
    if (!verifiedLink || !activeLink) { positionedSourceLink.current = null; return; }
    if (positionedSourceLink.current !== activeLink && scrollReviewTarget(sourceScroll.current, `review-source-${activeLink.source_element_ids[0]}`, 'center')) {
      positionedSourceLink.current = activeLink;
    }
  }, [verifiedLink, activeLink, mobilePane]);
  useEffect(() => {
    if (outputScrollTarget && !outputLoading && scrollReviewTarget(outputScroll.current, `review-output-${outputScrollTarget.id}`, outputScrollTarget.block)) {
      setOutputScrollTarget(null);
    }
  }, [outputScrollTarget, mobilePane, rightTab, outputLoading]);
  function clearDraft() { setDraft(emptyReviewDraft()); undo.current = []; setUndoCount(0); setNote(annotation?.note || ''); }
  function guard(action: () => void) {
    if (busy) return;
    if (dirty) setLeaveAction(() => action); else action();
  }
  function changeDraft(next: ReviewDraft) { undo.current.push(draft); setUndoCount(undo.current.length); setDraft(next); setFeedback(null); }
  function replaceText(id: string, value: string) {
    const replacements = { ...draft.replacements };
    if (outputParagraphs.find(item => item.id === id)?.text === value) delete replacements[id]; else replacements[id] = value;
    changeDraft({ ...draft, replacements });
  }
  function deleteParagraph(id: string) {
    const deletions = draft.deletions.includes(id) ? draft.deletions.filter(item => item !== id) : [...draft.deletions, id];
    changeDraft({ ...draft, deletions });
  }
  function chooseOutput(id: string) {
    if (noteDirty) guard(() => selectOutput(id)); else selectOutput(id);
  }
  function selectOutput(id: string) {
      setOutputScrollTarget(null);
      setSelectedOutput(id);
      const path = elementPath(output?.blocks || [], id);
      const link = links.find(item => item.output_element_ids.some(element => path.includes(element)) && item.status === 'verified') || links.find(item => item.output_element_ids.some(element => path.includes(element)));
      if (link) showLink(link); else { setActiveLink(null); setLinkNotice('此段未建立可靠来源定位，请结合原文人工核对。'); }
  }
  function showLink(link: ReviewLink) {
    setActiveLink(link);
    const asset = bundle?.assets.find(item => item.id === link.source_asset_id);
    if (asset) { setSourceAssetOverride(asset.id); if (sourceTabs.some(item => item.role === asset.role)) setSourceRole(asset.role); }
    setLinkNotice(link.rule_excluded ? `按规则省略：${link.rule_reason || link.reason || '此内容不适用于本次业务选择。'}` : link.status === 'verified' ? `${link.label || '来源证据'}：正在核对两侧定位。` : `${link.label || '来源定位未确认'}：${link.reason || '证据不足，仅供人工核对，不作自动高亮。'}`);
  }
  function chooseSource(id: string) {
    if (noteDirty) { guard(() => selectSource(id)); return; }
    selectSource(id);
  }
  function selectSource(id: string) {
    setSelectedSource(id);
    const path = elementPath(source?.blocks || [], id);
    const sourceLinks = links.filter(item => item.source_asset_id === sourceAsset?.id && item.source_element_ids.some(element => path.includes(element)));
    const link = sourceLinks.find(item => item.status === 'verified');
    if (link && link.output_element_ids.every(item => outputIds.includes(item))) {
      setActiveLink(link); setSelectedOutput(link.output_element_ids[0]);
      setLinkNotice(`${link.label || '来源证据'}：已找到任务书中的对应内容。`);
      setOutputScrollTarget({ id: link.output_element_ids[0], block: 'center' });
    } else if (sourceLinks.length) { showLink(sourceLinks[0]); }
    else { setActiveLink(null); setLinkNotice('此来源段落未建立可靠的任务书对应位置。'); }
  }
  function navigateParagraph(id: string) {
    guard(() => {
      setRightTab('review'); setMobilePane('output'); selectOutput(id);
      setOutputScrollTarget({ id, block: 'start' });
    });
  }
  async function runAction(name: string, action: () => Promise<void>) {
    if (mutation.current) return;
    mutation.current = true; setBusy(name); setFeedback(null);
    try { await action(); }
    catch (reason) { setFeedback({ error: true, message: errorText(reason), conflict: reason instanceof ReviewRequestError && reason.status === 409 }); }
    finally { mutation.current = false; setBusy(''); }
  }
  function acceptRevision(result: ReviewBundle) { clearDraft(); setBundle(result); setRevisionId(result.current_revision_id); setSelectedOutput(''); setNote(''); setRestoreId(''); }
  async function save() {
    if (!draftCount || !current) return;
    const operations: ReviewOperation[] = [
      ...Object.entries(draft.replacements).filter(([id]) => !draft.deletions.includes(id)).map(([element_id, text]) => ({ op: 'replace_text' as const, element_id, text })),
      ...Object.entries(draft.insertions).filter(([id]) => !draft.deletions.includes(id)).map(([element_id, text]) => ({ op: 'insert_paragraph' as const, element_id, text, position: 'after' as const })),
      ...draft.deletions.map(element_id => ({ op: 'delete_paragraph' as const, element_id })),
    ];
    await runAction('save', async () => { const result = await saveReviewRevision(jid, revisionId, operations); acceptRevision(result); setFeedback({ error: false, message: '已保存为新修订。机器检查尚未执行，请点击“重新检查”。' }); });
  }
  async function check() {
    await runAction('check', async () => {
      const checks = await checkReviewRevision(jid, revisionId);
      setBundle(previous => previous && ({ ...previous, revisions: previous.revisions.map(item => item.id === revisionId ? { ...item, checks } : item) }));
      setFeedback({ error: checks.status !== 'passed', message: checks.message || checkLabel(checks) });
    });
  }
  async function mark(status: 'checked' | 'pending') {
    if (!selectedOutput) return;
    await runAction('annotation', async () => {
      const result = await annotateReviewRevision(jid, revisionId, { element_id: selectedOutput, status, note });
      setBundle(previous => previous && ({ ...previous, revisions: previous.revisions.map(item => item.id === revisionId ? { ...item, annotations: result.annotations } : item) }));
      setFeedback({ error: false, message: '人工核对记录已保存，不改变机器检查结果。' });
    });
  }
  async function restore() {
    await runAction('restore', async () => { const result = await restoreReviewRevision(jid, restoreId, bundle!.current_revision_id); acceptRevision(result); setRightTab('review'); setFeedback({ error: false, message: '已恢复为新修订，原有版本继续保留。请重新检查。' }); });
  }
  async function upload(file: File) {
    await runAction('upload', async () => { const result = await uploadReviewRevision(jid, bundle!.current_revision_id, file); acceptRevision(result); setRightTab('review'); setFeedback({ error: false, message: '已导入 DOCX 为新修订，请重新检查。' }); });
  }
  function resize(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId);
    const move = (moveEvent: globalThis.PointerEvent) => { const rect = panelArea.current?.getBoundingClientRect(); if (rect) setSplit(Math.max(25, Math.min(70, (moveEvent.clientX - rect.left) / rect.width * 100))); };
    const end = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', end); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', end, { once: true });
  }

  if (loading || !bundle) return <main className="review-initial"><a href={returnPath}>{returnLabel}</a><h1>任务书审阅</h1>
    {loading ? <p role="status">正在读取任务文档与修订记录…</p> : <div role="alert"><p>{loadError || '任务暂不可审阅。'}</p><button type="button" onClick={() => void reload()}>重新加载</button></div>}</main>;

  return <div className="taskbook-review" data-mobile-pane={mobilePane}>
    <header className="review-header"><button className="review-home" type="button" onClick={() => guard(() => { window.location.href = returnPath; })}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m14 6-6 6 6 6" /></svg>{returnLabel}</button>
      <div className="review-heading"><h1>{bundle.title || '研制任务书'}</h1><p>审阅模式 · 内容对照<span className="review-task-id"> · {jid}</span></p></div>
      <div className="review-header-actions"><span className="review-machine-status" data-state={revision?.checks?.status || 'unchecked'}>机器检查：{checkLabel(revision?.checks)}</span>
        <button type="button" disabled={readOnly || Boolean(busy) || dirty || !output} onClick={() => void check()}>{busy === 'check' ? '正在检查…' : '重新检查'}</button>
        <a className="review-primary" href={reviewDownload(jid, revisionId)} download>{dirty ? '下载已保存版本' : '下载当前版本'}</a></div>
    </header>
    <div className="review-version-bar"><label htmlFor="review-revision">当前文档</label><StyledSelect id="review-revision" aria-label="当前文档修订" value={revisionId} disabled={Boolean(busy)} onChange={id => guard(() => { clearDraft(); setRevisionId(id); setRightTab('review'); })} options={bundle.revisions.map(item => ({ value: item.id, label: `${item.id === bundle.baseline_revision_id ? '生成原稿 · 归档于' : '修订稿 ·'} ${time(item.created_at)}${item.id === bundle.current_revision_id ? '（当前）' : ''}` }))} />
      <span>人工核对：已核对 {annotations.filter(item => item.status === 'checked').length} 处</span><span className="review-save-state" aria-live="polite">{dirty ? `${draftCount ? `${draftCount} 处正文修改` : '有修改'}未保存` : '所有修改已保存'}</span>
      <div className="review-mobile-switch" aria-label="审阅面板"><button type="button" aria-pressed={mobilePane === 'tree'} onClick={() => setMobilePane('tree')}>目录</button><button type="button" aria-pressed={mobilePane === 'source'} onClick={() => setMobilePane('source')}>来源</button><button type="button" aria-pressed={mobilePane === 'output'} onClick={() => setMobilePane('output')}>任务书</button></div>
    </div>
    {feedback && <div className={`review-feedback ${feedback.error ? 'error' : 'success'}`} role={feedback.error ? 'alert' : 'status'}>{feedback.message}
      {feedback.conflict && <><span> 当前版本已更新，你的草稿仍保留。</span><button type="button" onClick={() => guard(() => { clearDraft(); void reload(); })}>加载最新版本</button></>}</div>}
    {(bundle.warnings?.length > 0 || !current) && <div className="review-context-notice">{!current && <span>{readOnly ? '当前为只读审阅；修改由任务执行人在可编辑阶段办理。' : '正在查看历史版本；恢复为当前修订后可继续编辑。'} </span>}{bundle.warnings?.join('；')}</div>}
    <main className="review-workspace">
      <aside className="review-outline" aria-label="任务书章节与待核对项"><div className="review-small-tabs"><button type="button" aria-pressed={treeTab === 'chapters'} onClick={() => setTreeTab('chapters')}>章节</button><button type="button" aria-pressed={treeTab === 'pending'} onClick={() => setTreeTab('pending')}>待核对 {pendingParagraphs.length}</button></div>
        <nav>{treeTab === 'chapters' ? output?.outline.map(item => <button key={item.id} type="button" title={item.text} style={{ paddingInlineStart: `${12 + Math.min(Math.max(item.level - 1, 0), 3) * 10}px` }} className={selectedOutput === item.id ? 'is-active' : ''} onClick={() => navigateParagraph(item.id)}>{item.text}</button>)
          : pendingParagraphs.map(item => <button key={item.id} type="button" onClick={() => navigateParagraph(item.id)}>{item.text.slice(0, 75) || '空白段落待核对'}</button>)}
          {treeTab === 'pending' && pendingParagraphs.length === 0 && <p>未列出待核对项。仍需人工通读，机器检查单独显示。</p>}
          {treeTab === 'chapters' && output && !output.outline.length && <p>此文档没有可识别的章节标题，请在正文中核对。</p>}</nav>
        <p className="review-outline-foot">内容视图保留段落、表格及图片；分页与完整样式请以 DOCX 为准。</p>
      </aside>
      <div className="review-panels" ref={panelArea} style={{ '--review-source-width': `${split}%` } as CSSProperties}>
        <section className="review-source-panel" aria-label="来源文档"><div className="review-panel-tabs" role="tablist" aria-label="来源文件">{sourceTabs.map(tab => <button key={tab.role} type="button" role="tab" aria-selected={sourceRole === tab.role} onClick={() => { setSourceRole(tab.role); setSourceAssetOverride(''); setActiveLink(null); }}>{tab.label}</button>)}</div>
          <div className="review-document-toolbar"><span title={sourceAsset?.name}>{sourceAsset?.name || '未留存来源文件'}</span>{sourceAsset?.available && <a href={sourceAsset.url} download>下载原件</a>}</div>
          <div className="review-document-scroll" ref={sourceScroll}>
            {sourceLoading ? <p className="review-empty" role="status">正在读取来源文档…</p> : sourceError ? <div className="review-feedback error" role="alert">{sourceError}<button type="button" onClick={() => setSourceRetry(value => value + 1)}>重试读取来源</button></div>
              : source ? <ReviewDocumentPane document={source} side="source" selected={selectedSource} highlighted={verifiedLink ? activeLink!.source_element_ids : []} onSelect={chooseSource} />
                : sourceAsset?.available && sourceAsset.format.toLowerCase() === 'pdf' ? <div className="review-original-preview"><p>PDF 原件预览：没有段落索引，无法自动精确定位。</p><iframe src={sourceAsset.url} title={`${sourceAsset.label} PDF 原件预览`} /></div>
                  : sourceAsset?.available && ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(sourceAsset.format.toLowerCase()) ? <div className="review-original-preview"><p>图片原件预览：没有段落索引，无法自动精确定位。</p><img src={sourceAsset.url} alt={`${sourceAsset.label}原件`} /></div>
                : <div className="review-empty"><h3>{sourceAsset?.available ? '此格式需下载查看' : '本次任务未留存该来源'}</h3><p>{sourceAsset?.available ? '下载原件进行核对；系统不会用当前模板冒充本次生成所用的模板。' : '无法还原这份来源内容。可继续审阅任务书，来源对应关系需人工核对。'}</p></div>}
            {source?.warnings?.length ? <p className="review-context-notice">{source.warnings.join('；')}</p> : null}
          </div>
          <div className="review-link-status" role="status">{verifiedLink ? `${activeLink!.label || '来源证据'} · 已定位两侧原文` : activeLink?.status === 'verified' && !sourceLoading ? '来源位置尚未核实，不作自动高亮。' : linkNotice}{linkError && <p>{linkError}</p>}</div>
        </section>
        <div className="review-splitter" role="separator" tabIndex={0} aria-label="调整左右文档宽度" aria-orientation="vertical" aria-valuemin={25} aria-valuemax={70} aria-valuenow={Math.round(split)} onPointerDown={resize}
          onKeyDown={event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); setSplit(value => Math.max(25, Math.min(70, value + (event.key === 'ArrowLeft' ? -3 : 3)))); } }} />
        <section className="review-output-panel" aria-label="任务书审阅与编辑"><div className="review-panel-tabs" role="tablist" aria-label="任务书操作">
          <button type="button" role="tab" aria-selected={rightTab === 'review'} onClick={() => guard(() => setRightTab('review'))}>对照审阅</button>
          <button type="button" role="tab" aria-selected={rightTab === 'edit'} disabled={!current || !output} onClick={() => guard(() => setRightTab('edit'))}>编辑正文</button>
          <button type="button" role="tab" aria-selected={rightTab === 'history'} onClick={() => guard(() => setRightTab('history'))}>修订历史</button>
          {officeAvailable && <button type="button" role="tab" aria-selected={rightTab === 'office'} disabled={!current} onClick={() => { if (rightTab !== 'office') guard(() => { clearDraft(); setOfficeRevision(revisionId); setRightTab('office'); }); }}>版式编辑</button>}
        </div>
        {rightTab === 'office' ? <ReviewOfficeEditor key={officeRevision} jid={jid} revision={officeRevision} onDirty={setOfficeDirty} onBusy={value => setBusy(value ? 'office' : '')} onSaved={() => {
          void getReview(jid).then(result => {
            if (officeContext.current.tab === 'office' && officeContext.current.revision === officeRevision) { setBundle(result); setRevisionId(result.current_revision_id); }
          }).catch(reason => { if (officeContext.current.tab === 'office') setFeedback({ error: true, message: errorText(reason) }); });
        }} />
          : rightTab === 'history' ? <div className="review-history"><h2>修订记录</h2><p>生成原稿始终保留。恢复历史内容会创建新的修订，不覆盖已有版本。</p><ol>{bundle.revisions.map(item => <li key={item.id}>
            <div><strong>{item.id === bundle.baseline_revision_id ? '生成原稿' : '修订稿'}{item.id === bundle.current_revision_id ? ' · 当前' : ''}</strong><time>{item.id === bundle.baseline_revision_id ? '归档时间：' : ''}{time(item.created_at)}</time><p>{item.reason || '正文修订'}{item.actor ? ` · ${item.actor}` : ''}</p><span>机器检查：{checkLabel(item.checks)}</span></div>
            <div className="review-history-actions"><button type="button" onClick={() => { setRevisionId(item.id); setRightTab('review'); }}>查看</button><a href={reviewDownload(jid, item.id)} download>下载</a><button type="button" disabled={readOnly || Boolean(busy) || item.id === bundle.current_revision_id} onClick={() => setRestoreId(item.id)}>恢复此版本</button></div>
          </li>)}</ol></div>
            : <>
              <div className="review-document-toolbar"><span>{rightTab === 'edit' ? '直接修改段落与单元格，保存时生成 DOCX 新修订' : '内容对照 · 选择段落查看来源与人工核对记录'}</span>
                {rightTab === 'edit' && <div><button type="button" disabled={!undoCount || Boolean(busy)} onClick={() => { setDraft(undo.current.pop()!); setUndoCount(undo.current.length); }}>撤销</button><button type="button" disabled={!draftCount || Boolean(busy)} onClick={() => guard(clearDraft)}>放弃修改</button><button className="review-primary" type="button" disabled={!draftCount || Boolean(busy)} onClick={() => void save()}>{busy === 'save' ? '正在保存…' : '保存修订'}</button></div>}
                {rightTab === 'review' && current && <button type="button" disabled={Boolean(busy)} onClick={() => guard(() => uploadInput.current?.click())}>导入修订 DOCX</button>}
              </div>
              <div className="review-document-scroll" ref={outputScroll}>
                {outputLoading ? <p className="review-empty" role="status">正在读取任务书内容…</p> : outputError ? <div className="review-feedback error" role="alert">{outputError}<button type="button" onClick={() => setOutputRetry(value => value + 1)}>重试读取任务书</button></div>
                  : output ? <ReviewDocumentPane document={output} side="output" selected={selectedOutput} highlighted={verifiedLink ? activeLink!.output_element_ids : []} onSelect={chooseOutput}
                    editing={rightTab === 'edit'} draft={draft} busy={Boolean(busy)} onText={replaceText} onDelete={deleteParagraph}
                    onInsert={(id, text) => changeDraft({ ...draft, insertions: { ...draft.insertions, [id]: text } })}
                    onCancelInsert={id => { const insertions = { ...draft.insertions }; delete insertions[id]; changeDraft({ ...draft, insertions }); }} /> : <p className="review-empty">此版本没有可读取的任务书。</p>}
                {output?.warnings?.length ? <p className="review-context-notice">{output.warnings.join('；')}</p> : null}
              </div>
              {rightTab === 'review' && selectedParagraph && <section className="review-annotation" aria-label="人工核对记录"><div><strong>人工核对</strong>{taskContext && <span>已选中当前正文，可在下方覆盖核对中采用</span>}<span>{annotation?.status === 'checked' ? '已核对' : '待核对'}</span><span title={selectedParagraph.text}>{selectedParagraph.text.slice(0, 64) || '空白段落'}</span></div>
                <label htmlFor="review-note">核对备注</label><textarea className="resize-none" id="review-note" rows={2} value={note} disabled={readOnly || Boolean(busy)} onChange={event => setNote(event.target.value)} placeholder="记录需要补充的内容或核对结论" />
                <div className="review-annotation-actions"><button type="button" disabled={readOnly || Boolean(busy) || draftCount > 0} onClick={() => void mark('pending')}>保存为待核对</button><button type="button" disabled={readOnly || Boolean(busy) || draftCount > 0} onClick={() => void mark('checked')}>标为已核对</button><span>人工核对不替代机器检查</span></div>
              </section>}
            </>}
        </section>
      </div>
    </main>
    {revision?.checks?.issues?.length ? <details className="review-check-issues"><summary>机器检查发现 {revision.checks.issues.length} 项问题</summary><ul>{revision.checks.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{issue.message}{issue.element_id && <button type="button" onClick={() => navigateParagraph(issue.element_id!)}>定位</button>}</li>)}</ul></details> : null}
    <input ref={uploadInput} type="file" hidden accept=".docx" aria-label="上传修订 DOCX" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void upload(file); }} />
    {leaveAction && <ConfirmDialog title="有未保存的修改" message="离开当前编辑会放弃尚未保存的正文或核对备注。已保存的版本不受影响。" cancel="继续编辑" confirm="放弃修改并继续" onCancel={() => setLeaveAction(null)} onConfirm={() => { const action = leaveAction; setLeaveAction(null); clearDraft(); setOfficeDirty(false); action(); }} />}
    {restoreId && <ConfirmDialog title="恢复历史版本" message="将以此版本创建新的当前修订，已有修订仍然保留；恢复后需重新检查。" cancel="取消" confirm={busy === 'restore' ? '正在恢复…' : '确认恢复'} disabled={Boolean(busy)} onCancel={() => setRestoreId('')} onConfirm={() => void restore()} />}
  </div>;
}

function ConfirmDialog({ title, message, cancel, confirm, disabled, onCancel, onConfirm }: {
  title: string; message: string; cancel: string; confirm: string; disabled?: boolean; onCancel: () => void; onConfirm: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const element = ref.current!; element.showModal(); return () => element.close(); }, []);
  return <dialog ref={ref} className="review-confirm" aria-labelledby="review-confirm-title" onCancel={event => { event.preventDefault(); if (!disabled) onCancel(); }}><h2 id="review-confirm-title">{title}</h2><p>{message}</p><div><button type="button" disabled={disabled} onClick={onCancel}>{cancel}</button><button type="button" className="review-primary" disabled={disabled} onClick={onConfirm}>{confirm}</button></div></dialog>;
}
