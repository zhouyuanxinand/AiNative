import { forwardRef, useEffect, useId, useImperativeHandle, useRef, useState, type FormEvent } from 'react';
import { PlatformButton } from '../../../components/ui/PlatformButton';
import { FeedbackDialog } from '../../../components/feedback/FeedbackDialog';
import { useApplicationLeaveGuard } from '../../../hooks/useApplicationLeaveGuard';
import { useChatSessions } from './chatSessions';
import type { ChatMessage } from '../api';
import './welcomeAssistant.css';

export interface WelcomeAssistantHandle { requestClose: () => void }
interface WelcomeAssistantProps {
  visible: boolean; onClose: () => void; onStartTask?: () => void; onOpenProjects?: () => void;
  onWeather: () => void; onDirtyChange: (dirty: boolean) => void; onBusyChange: (busy: boolean) => void;
}
const SUGGESTIONS = [
  { label: '怎么开始任务', question: '我想开始一项新任务，应该怎么操作？' },
  { label: '如何上传资料', question: '如何上传技术要求和产品规范资料？' },
  { label: '涧西天气', question: '帮我看看洛阳涧西区的天气。' },
];
const displayTime = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
};

export const WelcomeAssistant = forwardRef<WelcomeAssistantHandle, WelcomeAssistantProps>(function WelcomeAssistant(
  { visible, onClose, onStartTask, onOpenProjects, onWeather, onDirtyChange, onBusyChange }, ref,
) {
  const chat = useChatSessions(visible);
  const [confirmation, setConfirmation] = useState<'close' | { sourceId?: string } | null>(null);
  const inputId = useId();
  const input = useRef<HTMLTextAreaElement>(null), log = useRef<HTMLDivElement>(null);
  const composing = useRef(false), stickToLatest = useRef(true);
  const displayed = chat.view === 'preview' ? chat.preview : chat.current;
  const messages = displayed?.messages ?? [];
  const dirty = chat.draft !== (chat.current?.draft ?? '');
  const sending = chat.task === 'send';
  const canInteract = chat.verified && !chat.busy;

  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => { onBusyChange(chat.busy); }, [chat.busy, onBusyChange]);
  useEffect(() => () => { onBusyChange(false); onDirtyChange(false); }, [onBusyChange, onDirtyChange]);
  useApplicationLeaveGuard({ dirty, busyMessage: chat.busy ? '小航正在处理对话，请完成后再离开。' : undefined });
  useEffect(() => {
    if (visible && chat.view === 'chat' && log.current && stickToLatest.current) log.current.scrollTop = log.current.scrollHeight;
  }, [messages.length, chat.pending, sending, chat.error, visible, chat.view]);
  useEffect(() => {
    if (visible && chat.verified && !chat.busy && chat.view === 'chat' && document.activeElement === document.body) input.current?.focus({ preventScroll: true });
  }, [visible, chat.verified, chat.busy, chat.view]);

  function requestClose() {
    if (chat.busy) return;
    if (!(chat.current?.message_count || chat.draft)) { onClose(); return; }
    chat.clearError(); setConfirmation('close');
  }
  useImperativeHandle(ref, () => ({ requestClose }));
  async function closeWith(choice: 'keep' | 'end') {
    if (await chat.close(choice)) { setConfirmation(null); onClose(); }
  }
  async function create(sourceId?: string) {
    if (await chat.create(sourceId)) { setConfirmation(null); stickToLatest.current = true; input.current?.focus({ preventScroll: true }); }
  }
  function requestCreate(sourceId?: string) {
    if (!canInteract) return;
    chat.clearError();
    if (chat.draft) setConfirmation({ sourceId }); else void create(sourceId);
  }
  async function ask(text: string) {
    stickToLatest.current = true;
    if (await chat.send(text)) input.current?.focus({ preventScroll: true });
  }
  function submit(event: FormEvent) { event.preventDefault(); void ask(chat.draft); }
  async function earlier() {
    const height = log.current?.scrollHeight ?? 0, top = log.current?.scrollTop ?? 0;
    stickToLatest.current = false;
    if (await chat.earlier()) window.requestAnimationFrame(() => { if (log.current) log.current.scrollTop = top + log.current.scrollHeight - height; });
  }
  function showCurrent() { chat.setView('chat'); chat.clearError(); }
  function renderMessage(message: ChatMessage) {
    // Task navigation belongs to the welcome screen, not every chat reply.
    const actions = message.actions?.filter(action => action.id === 'weather') ?? [];
    return <article key={message.id} className={`rd-welcome-message ${message.role}`}>
      <div className="rd-welcome-message-meta"><strong>{message.role === 'user' ? '我' : '小航'}</strong>{message.role === 'assistant' && <span>{message.mode === 'model' ? '模型回复' : '操作指引'}</span>}</div>
      <p>{message.content}</p>
      {!!actions.length && <div className="rd-welcome-message-actions">{actions.map(action => <PlatformButton key={action.id} type="button" className="rd-welcome-action" disabled={chat.busy} onClick={onWeather}>{action.label}<span aria-hidden="true">↗</span></PlatformButton>)}</div>}
    </article>;
  }

  return <aside className="rd-welcome-assistant" hidden={!visible} aria-label="小航操作助手">
    <header className="rd-welcome-header">
      <span className="rd-welcome-avatar" aria-hidden="true"><img src="/assets/xiaohang-3d-portrait.png" alt="" draggable={false} onError={event => { event.currentTarget.hidden = true; }} /><span>航</span></span>
      <div><strong>小航<span>研发助手</span></strong><p>从一个问题，找到下一步</p></div>
      <button type="button" className="rd-floating-close" aria-label="收起小航助手" title="收起（Esc）" disabled={chat.busy} onClick={requestClose}>×</button>
    </header>
    <div className="rd-chat-toolbar">
      <span title={chat.verified ? chat.current?.title : undefined}>{!chat.verified ? '正在核对对话' : chat.view === 'history' ? '历史记录' : chat.view === 'preview' ? '查看历史对话' : chat.current?.title || '新对话'}</span>
      {chat.view !== 'chat' && <button type="button" disabled={!canInteract} onClick={showCurrent}>返回当前对话</button>}
      {chat.view === 'chat' && <button type="button" disabled={!canInteract} onClick={() => void chat.history()}>历史记录</button>}
      <button type="button" disabled={!canInteract} onClick={() => requestCreate()}>新对话</button>
    </div>
    <div ref={log} className="rd-welcome-log" role={chat.view === 'history' ? 'region' : 'log'} aria-label={chat.view === 'history' ? '小航历史记录' : '与小航的对话'} aria-live="polite" aria-relevant="additions text"
      onScroll={() => { if (log.current) stickToLatest.current = log.current.scrollHeight - log.current.scrollTop - log.current.clientHeight < 48; }}>
      {!chat.verified && !chat.error && <p className="rd-chat-notice" role="status">正在读取你的对话…</p>}
      {chat.verified && chat.view === 'history' && <>
        <p className="rd-chat-notice">对话保存在当前账号下。查看记录后，可以带着上下文另开新对话。</p>
        {!chat.directory?.items.length && <p className="rd-chat-empty">还没有历史对话。</p>}
        <ul className="rd-chat-history-list">{chat.directory?.items.map(item => <li key={item.id}>
          <button type="button" disabled={chat.busy} onClick={() => void chat.inspect(item.id)}>
            <strong>{item.title}</strong><span><time dateTime={item.updated_at}>{displayTime(item.updated_at)}</time><span>{item.message_count} 条消息{item.id === chat.current?.id ? ' · 当前对话' : ''}</span></span>
          </button>
        </li>)}</ul>
        {chat.directory && chat.directory.total > chat.directory.page_size && <nav className="rd-chat-pagination" aria-label="历史记录分页">
          <button type="button" disabled={chat.busy || chat.directory.page <= 1} onClick={() => void chat.history(chat.directory!.page - 1)}>上一页</button>
          <span>{chat.directory.page} / {Math.ceil(chat.directory.total / chat.directory.page_size)}</span>
          <button type="button" disabled={chat.busy || chat.directory.page * chat.directory.page_size >= chat.directory.total} onClick={() => void chat.history(chat.directory!.page + 1)}>下一页</button>
        </nav>}
      </>}
      {chat.verified && chat.view !== 'history' && <>
        {chat.view === 'preview' && <div className="rd-chat-preview-note"><strong>{chat.preview?.title}</strong><p>此记录只读。继续交流会复制为新对话，原记录保持不变。</p><button type="button" disabled={chat.busy} onClick={() => void chat.history(chat.directory?.page)}>返回历史列表</button></div>}
        {displayed?.has_more && <button type="button" className="rd-chat-earlier" disabled={chat.busy} onClick={() => void earlier()}>{chat.task === 'earlier' ? '正在读取…' : '查看更早消息'}</button>}
        {chat.view === 'chat' && !messages.length && !chat.pending && <section className="rd-welcome-intro" aria-label="小航可以帮你">
          <span className="rd-welcome-eyebrow">你的研发工作伙伴</span><h2>你好，我是小航</h2>
          <p>不确定从哪里开始？告诉我你想做什么，我可以帮你理清操作、找到入口。</p>
          <div className="rd-welcome-entry-actions">
            {onStartTask && <PlatformButton type="button" className="rd-welcome-entry" disabled={!canInteract || Boolean(chat.draft)} onClick={() => { onClose(); onStartTask(); }}>开始任务<span aria-hidden="true">↗</span></PlatformButton>}
            {onOpenProjects && <PlatformButton type="button" className="rd-welcome-entry" disabled={!canInteract || Boolean(chat.draft)} onClick={() => { onClose(); onOpenProjects(); }}>查看项目<span aria-hidden="true">→</span></PlatformButton>}
          </div>
          <div className="rd-welcome-suggestions" aria-label="试着问小航"><p>也可以这样问</p>{SUGGESTIONS.map(suggestion => <PlatformButton key={suggestion.label} type="button" className="rd-welcome-suggestion" disabled={!canInteract || Boolean(chat.draft.trim())} onClick={() => void ask(suggestion.question)}>{suggestion.label}</PlatformButton>)}</div>
        </section>}
        {messages.map(renderMessage)}
        {chat.pending && <article className="rd-welcome-message user"><div className="rd-welcome-message-meta"><strong>我</strong></div><p>{chat.pending}</p></article>}
        {sending && <p className="rd-welcome-pending" role="status"><span aria-hidden="true">◌</span>小航正在整理回复…</p>}
      </>}
      {chat.busy && !sending && chat.task !== 'load' && <p className="rd-chat-notice" role="status">正在处理…</p>}
      {chat.error && !confirmation && <div className="rd-welcome-error" role="alert"><p>{chat.error}</p>
        {chat.verified && chat.errorStatus !== 409 && <PlatformButton type="button" className="rd-link-button" disabled={chat.busy} onClick={() => void chat.retry()}>{chat.view === 'chat' && chat.draft.trim() ? '重试发送' : '重试'}</PlatformButton>}
        <PlatformButton type="button" className="rd-link-button" disabled={chat.busy} onClick={() => void chat.load()}>重新读取对话</PlatformButton>
        {chat.draft && <small>未发送的问题已保留。</small>}
      </div>}
    </div>
    {chat.view === 'chat' && <form className="rd-welcome-composer" noValidate onSubmit={submit}>
      <label htmlFor={inputId}>问问小航</label>
      <div className="rd-welcome-input-shell"><textarea ref={input} id={inputId} className="resize-none" rows={2} maxLength={2000} value={chat.verified ? chat.draft : ''} disabled={!canInteract} placeholder="例如：技术要求应该在哪里上传？"
        onChange={event => chat.setDraft(event.target.value)} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
        onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !composing.current && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
        <div className="rd-welcome-compose-actions"><small>{chat.draft.length > 1800 ? `${chat.draft.length} / 2000` : 'Enter 发送 · Shift + Enter 换行'}</small><PlatformButton type="submit" className="primary rd-welcome-send" disabled={!canInteract || !chat.draft.trim()} aria-label="发送给小航">{sending ? '回复中' : '发送'}<span aria-hidden="true">↑</span></PlatformButton></div>
      </div><p className="rd-welcome-scope-note">对话自动保存 · 在历史记录中继续交流</p>
    </form>}
    {chat.view === 'preview' && <div className="rd-chat-history-footer"><PlatformButton type="button" className="primary" disabled={!canInteract || !chat.preview} onClick={() => requestCreate(chat.preview?.id)}>基于此记录新对话</PlatformButton></div>}
    {confirmation && <FeedbackDialog title={confirmation === 'close' ? '收起还是结束本次对话？' : '另开新对话？'} className="feedback-confirm-dialog rd-chat-confirm" onCancel={() => { if (!chat.busy) setConfirmation(null); }}>
      <div className="feedback-confirm-message">{confirmation === 'close' ? <><p>两种方式都会保留已完成的对话。</p><p>保留并收起：下次继续当前对话，未发送内容也会保存。</p><p>结束并退出：下次开始新对话，当前未发送内容会丢弃。</p></> : <p>当前有未发送内容。另开新对话会丢弃这段草稿，已完成的对话仍保留在历史记录中。</p>}</div>
      {chat.error && <div className="feedback-error" role="alert">{chat.error}{(chat.errorStatus === 409 || !chat.verified) && <PlatformButton type="button" disabled={chat.busy} onClick={() => void chat.load()}>重新读取对话</PlatformButton>}</div>}
      <div className="feedback-dialog-actions rd-chat-confirm-actions">
        <PlatformButton type="button" disabled={chat.busy} onClick={() => setConfirmation(null)}>{confirmation === 'close' ? '继续聊天' : '继续编辑'}</PlatformButton>
        {confirmation === 'close' ? <><PlatformButton type="button" disabled={chat.busy || !chat.verified} onClick={() => void closeWith('end')}>结束并退出</PlatformButton><PlatformButton type="button" className="primary" disabled={chat.busy || !chat.verified} onClick={() => void closeWith('keep')}>{chat.task === 'close' ? '正在保存…' : '保留并收起'}</PlatformButton></> : <PlatformButton type="button" className="primary" disabled={chat.busy || !chat.verified} onClick={() => void create(confirmation.sourceId)}>放弃草稿并新建</PlatformButton>}
      </div>
    </FeedbackDialog>}
  </aside>;
});
