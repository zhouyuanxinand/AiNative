import { PlatformButton } from '../../components/ui/PlatformButton';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useApplicationLeaveGuard } from '../../hooks/useApplicationLeaveGuard';
import { makeRequestKey, rdAskAssistant, rdAssistant } from './api';
import { mergeAssistantHistory } from './assistantHistory';
import { formatTime, messageOf, stageTitle } from './presentation';
import type { AssistantResponse, AssistantTarget, Project, ResearchCase } from './types';
import './FloatingAssistant.css';

export function CaseAssistant({ project, researchCase, visible, onClose, onNavigate, onDirtyChange, onBusyChange }: {
  project: Project; researchCase: ResearchCase; visible: boolean; onClose: () => void; onNavigate: (target: AssistantTarget) => void; onDirtyChange: (dirty: boolean) => void; onBusyChange: (busy: boolean) => void;
}) {
  const [data, setData] = useState<AssistantResponse | null>(null);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [olderError, setOlderError] = useState('');
  const [error, setError] = useState('');
  const [sendError, setSendError] = useState('');
  const [revision, setRevision] = useState(0);
  const reading = useRef<AbortController>();
  const writing = useRef<AbortController>();
  const olderReading = useRef<AbortController>();
  const scrollToLatest = useRef(true);
  const preserveScroll = useRef<{ height: number; top: number } | null>(null);
  const scope = useRef(`${project.id}/${researchCase.id}`);
  scope.current = `${project.id}/${researchCase.id}`;
  const retry = useRef({ text: '', key: '' });
  const locked = useRef(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const composing = useRef(false);
  useEffect(() => { onDirtyChange(!!draft); }, [draft, onDirtyChange]);
  useEffect(() => { onBusyChange(sending); }, [sending, onBusyChange]);
  useEffect(() => () => { onBusyChange(false); }, [onBusyChange]);
  useApplicationLeaveGuard({ dirty: !!draft, busyMessage: sending ? '助手请求尚未完成，请等待回复后再离开。' : undefined });
  useEffect(() => {
    if (sending) return;
    const requestScope = `${project.id}/${researchCase.id}`;
    const controller = new AbortController(); reading.current?.abort(); reading.current = controller;
    olderReading.current?.abort(); setLoadingOlder(false);
    setLoading(true);
    void rdAssistant(project.id, researchCase.id, controller.signal).then(response => {
      if (!controller.signal.aborted && scope.current === requestScope) { if (log.current && log.current.scrollHeight - log.current.scrollTop - log.current.clientHeight < 50) scrollToLatest.current = true; setData(current => mergeAssistantHistory(current, response)); setError(''); setLoading(false); }
    }).catch(reason => { if (!controller.signal.aborted) { setError(messageOf(reason)); setLoading(false); } });
    return () => controller.abort();
  }, [project.id, project.version, researchCase.id, researchCase.stage, researchCase.input_revision, revision, sending]);
  useEffect(() => () => { reading.current?.abort(); writing.current?.abort(); olderReading.current?.abort(); }, []);
  useEffect(() => {
    if (!visible || !log.current) return;
    if (preserveScroll.current) { log.current.scrollTop = log.current.scrollHeight - preserveScroll.current.height + preserveScroll.current.top; preserveScroll.current = null; }
    else if (scrollToLatest.current) { log.current.scrollTop = log.current.scrollHeight; scrollToLatest.current = false; }
  }, [data?.messages.length, visible]);
  async function loadEarlier() {
    const before = data?.history?.next_before;
    if (before === null || before === undefined || loadingOlder || loading || sending) return;
    const requestScope = `${project.id}/${researchCase.id}`;
    const controller = new AbortController(); olderReading.current?.abort(); olderReading.current = controller;
    setLoadingOlder(true); setOlderError('');
    try {
      const response = await rdAssistant(project.id, researchCase.id, controller.signal, before);
      if (!controller.signal.aborted && scope.current === requestScope) {
        if (log.current) preserveScroll.current = { height: log.current.scrollHeight, top: log.current.scrollTop };
        setData(current => mergeAssistantHistory(current, response, true));
      }
    } catch (reason) { if (!controller.signal.aborted) setOlderError(messageOf(reason)); }
    finally { if (!controller.signal.aborted) setLoadingOlder(false); }
  }
  async function send(event: FormEvent) {
    event.preventDefault();
    if (locked.current) return;
    const message = draft.trim();
    if (!message) { setSendError('请先填写要询问的问题。'); input.current?.focus(); return; }
    if (retry.current.text !== message) retry.current = { text: message, key: makeRequestKey() };
    locked.current = true; setSending(true); setLoading(false); setSendError(''); reading.current?.abort(); olderReading.current?.abort(); setLoadingOlder(false);
    const controller = new AbortController(); writing.current = controller;
    try {
      const response = await rdAskAssistant(project.id, researchCase.id, message, undefined, retry.current.key, controller.signal);
      if (!controller.signal.aborted) {
        scrollToLatest.current = true; setData(current => mergeAssistantHistory(current, response)); setDraft(''); retry.current = { text: '', key: '' };
        if (response.navigation) onNavigate(response.navigation.target);
        input.current?.focus();
      }
    } catch (reason) { if (!controller.signal.aborted) setSendError(messageOf(reason)); }
    finally { locked.current = false; if (!controller.signal.aborted) setSending(false); }
  }
  const stale = data && (data.context.project_version !== project.version || data.context.input_revision !== undefined && data.context.input_revision !== researchCase.input_revision);
  return <aside className="rd-case-assistant rd-assistant-floating-content" hidden={!visible} aria-label="当前案例研发助手">
    <header><span className="rd-assistant-mini-avatar" aria-hidden="true">航</span><div><strong>小航<span className="rd-assistant-title-note">研发助手</span></strong><small title={researchCase.title}>{researchCase.title}</small></div><button type="button" className="rd-floating-close" aria-label="收起小航助手" title="收起（Esc）" onClick={onClose}>×</button></header>
    <details className="rd-assistant-context-details"><summary><span>{stageTitle(researchCase.stage)}</span><span>记录说明</span></summary><div><p>可查询当前案例、定位办理事项。业务修改仍在工作面完成。</p><p>输入修订 {researchCase.input_revision ?? '—'} · 项目版本 {project.version}</p>{data?.history?.notice && <p>{data.history.notice}</p>}</div></details>
    <div className="rd-assistant-log" ref={log} role="log" aria-live="polite" aria-relevant="additions text">
      {data?.history?.has_more && <PlatformButton type="button" className="rd-assistant-earlier rd-link-button" disabled={loadingOlder || loading || sending} onClick={() => void loadEarlier()}>{loadingOlder ? '正在加载…' : '加载更早记录'}</PlatformButton>}
      {data?.history && data.history.total > 0 && <p className="rd-assistant-history-note">已载入 {data.messages.length} / {data.history.total} 条</p>}
      {olderError && <p className="rd-error" role="alert">{olderError} <PlatformButton type="button" className="rd-link-button" onClick={() => void loadEarlier()} disabled={loadingOlder}>重试加载</PlatformButton></p>}
      {loading && !data && <p className="rd-muted" role="status">正在读取助手记录…</p>}
      {data && !data.messages.length && <div className="rd-assistant-empty"><h3>这项工作，我们从哪里开始？</h3><p>可以问我缺少哪些资料，或查看当前进度。</p></div>}
      {data?.messages.map(message => {
        const historical = message.stale || message.answered_version !== project.version || message.input_revision !== researchCase.input_revision;
        return <article key={message.id} className={`rd-assistant-message ${message.role} ${historical ? 'historical' : ''}`}><div><strong>{message.role === 'user' ? '我' : '小航'}</strong>{message.role === 'assistant' && <span className="rd-assistant-mode">{message.mode === 'model' ? '模型' : '指引'}</span>}<time dateTime={message.created_at}>{formatTime(message.created_at)}</time></div>{historical && <details className="rd-assistant-message-version"><summary>历史回复</summary><p>输入修订 {message.input_revision} · 项目版本 {message.answered_version}，仅供追溯。</p></details>}<p>{message.content}</p></article>;
      })}
      {sending && <p className="rd-assistant-pending" role="status"><span aria-hidden="true"><i /><i /><i /></span>小航正在回复…</p>}
    </div>
    {stale && <p className="rd-assistant-hint">案例已更新，旧回复仅供追溯。</p>}
    {(sendError || error) && <div className="rd-error rd-assistant-error" role="alert"><p>{sendError || error}</p>{sendError ? <p>填写内容已保留，可再次发送重试。</p> : <PlatformButton type="button" className="rd-link-button" disabled={sending || loading} onClick={() => setRevision(value => value + 1)}>重试读取记录</PlatformButton>}</div>}
    {!!data?.suggestions.length && <div className="rd-assistant-suggestions" aria-label="当前案例建议">{data.suggestions.slice(0, 3).map(suggestion => <button type="button" key={suggestion.id} onClick={() => onNavigate(suggestion.target)}>{suggestion.label}<span aria-hidden="true">↗</span></button>)}</div>}
    <form noValidate onSubmit={event => void send(event)}><label className="rd-assistant-input-label" htmlFor={`rd-assistant-message-${researchCase.id}`}>询问当前案例</label><textarea ref={input} id={`rd-assistant-message-${researchCase.id}`} className="resize-none" rows={2} maxLength={2000} value={draft} onChange={event => setDraft(event.target.value)} placeholder="问问小航…" disabled={sending} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !composing.current && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} /><div><small>{draft.length > 1800 ? `${draft.length} / 2000` : 'Enter 发送 · Shift + Enter 换行'}</small><button type="submit" className="rd-floating-primary" disabled={sending || !draft.trim()} aria-label="发送给小航">{sending ? '回复中…' : '发送'}<span aria-hidden="true">↑</span></button></div></form>
  </aside>;
}
