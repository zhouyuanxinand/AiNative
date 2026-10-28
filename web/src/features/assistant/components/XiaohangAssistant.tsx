import { useEffect, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent, type PointerEvent } from 'react';
import { askAssistant, confirmAssistantProposal, getAssistantContext, type AssistantAction, type AssistantContext, type AssistantHistory, type AssistantOperationResult, type AssistantProposal, type AssistantReply } from '../api/assistant';
import { applicationLeaveState, useApplicationLeaveGuard } from '../../../shared/hooks/useApplicationLeaveGuard';
import { useAssistantLauncherDrag } from '../hooks/useAssistantLauncherDrag';
import { assistantEnterSubmits, assistantHistory, assistantHref, assistantPanelWidth, assistantProjectId } from '../model/assistant';
import { FeedbackConfirmDialog } from '../../../shared/ui/FeedbackDialog';
import { XiaohangSprite } from './XiaohangSprite';
import './xiaohang.css';

type Message = AssistantHistory & { id: string; actions?: AssistantAction[]; source?: AssistantReply['source']; proposal?: AssistantProposal | null };
type Turn = { question: string; status: 'pending' | 'error' | 'stopped'; error?: string };
interface Conversation { messages: Message[]; draft: string; turn: Turn | null }

function AssistantGlyph({ kind }: { kind: 'close' | 'send' | 'arrow' }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{kind === 'close' ? <path d="m6 6 12 12M18 6 6 18" /> : kind === 'send' ? <path d="m4 11 16-7-7 16-2-7zM11 13l9-9" /> : <path d="M5 12h14m-5-5 5 5-5 5" />}</svg>;
}

/** One conversation. The server identifies intent before loading project context or preparing operations. */
export function XiaohangAssistant({ onOpenChange }: { onOpenChange?: (open: boolean) => void }) {
  const [open, setOpen] = useState(false), [panelWidth, setPanelWidth] = useState(() => assistantPanelWidth(420, window.innerWidth)), [viewportWidth, setViewportWidth] = useState(window.innerWidth);
  const [context, setContext] = useState<AssistantContext | null>(null), [contextError, setContextError] = useState(''), [contextVersion, setContextVersion] = useState(0);
  const [conversation, setConversation] = useState<Conversation>({ messages: [], draft: '', turn: null });
  const [imageFailed, setImageFailed] = useState(false), [confirmation, setConfirmation] = useState<AssistantProposal | null>(null), [executing, setExecuting] = useState(false), [operationError, setOperationError] = useState('');
  const [operations, setOperations] = useState<Record<string, AssistantOperationResult | 'dismissed'>>({});
  const launcher = useRef<HTMLButtonElement>(null), input = useRef<HTMLTextAreaElement>(null), transcript = useRef<HTMLDivElement>(null);
  const { position: launcherPosition, launcherDragging, launcherEvents } = useAssistantLauncherDrag(launcher, !open, () => setOpen(true));
  const request = useRef<AbortController | null>(null), composing = useRef(false), stickToBottom = useRef(true), executeLock = useRef(false), wasOpen = useRef(false);
  const drag = useRef<{ id: number; x: number; width: number } | null>(null);
  const projectId = assistantProjectId(window.location.pathname);
  const pending = conversation.turn?.status === 'pending';
  const maximumWidth = assistantPanelWidth(640, viewportWidth);
  useApplicationLeaveGuard({ dirty: false, busyMessage: executing ? '小航正在执行已确认的业务操作，请等待结果后再离开。' : undefined });

  useEffect(() => { onOpenChange?.(open); }, [open, onOpenChange]);
  useEffect(() => () => { onOpenChange?.(false); }, [onOpenChange]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setContextError('');
    void getAssistantContext(projectId, controller.signal).then(value => {
      if (!controller.signal.aborted) setContext(value);
    }).catch(reason => { if (!controller.signal.aborted) setContextError(reason instanceof Error ? reason.message : '平台入口读取失败，请重试。'); });
    return () => controller.abort();
  }, [open, projectId, contextVersion]);
  useEffect(() => () => { request.current?.abort(); request.current = null; }, []);
  useEffect(() => {
    const resize = () => { setViewportWidth(window.innerWidth); setPanelWidth(previous => assistantPanelWidth(previous, window.innerWidth)); };
    window.addEventListener('resize', resize); return () => window.removeEventListener('resize', resize);
  }, []);
  useEffect(() => {
    if (open) input.current?.focus();
    else if (wasOpen.current) launcher.current?.focus();
    wasOpen.current = open;
  }, [open]);
  useEffect(() => {
    const node = transcript.current;
    if (node && open && stickToBottom.current) node.scrollTop = node.scrollHeight;
  }, [open, conversation.messages.length, conversation.turn?.status, operations]);

  function close() { if (!executing) setOpen(false); }
  function resizeBy(amount: number) { setPanelWidth(previous => assistantPanelWidth(previous + amount, window.innerWidth)); }
  function startResize(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault(); drag.current = { id: event.pointerId, x: event.clientX, width: panelWidth }; event.currentTarget.setPointerCapture(event.pointerId);
  }
  function moveResize(event: PointerEvent<HTMLDivElement>) {
    const start = drag.current;
    if (start?.id === event.pointerId) setPanelWidth(assistantPanelWidth(start.width + start.x - event.clientX, window.innerWidth));
  }
  function finishResize(event: PointerEvent<HTMLDivElement>) {
    if (drag.current?.id !== event.pointerId) return;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }
  function keyboardResize(event: KeyboardEvent<HTMLDivElement>) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'Home') setPanelWidth(320);
    else if (event.key === 'End') setPanelWidth(maximumWidth);
    else resizeBy(event.key === 'ArrowLeft' ? 32 : -32);
  }
  function stop() {
    request.current?.abort(); request.current = null;
    setConversation(current => ({ ...current, draft: current.turn?.question || current.draft, turn: current.turn ? { ...current.turn, status: 'stopped' } : null }));
  }
  async function send(question: string) {
    const message = question.trim();
    if (!message || message.length > 4000 || request.current || executing) return;
    const controller = new AbortController(); request.current = controller; stickToBottom.current = true;
    const history = assistantHistory(conversation.messages);
    setConversation(current => ({ ...current, draft: '', turn: { question: message, status: 'pending' } }));
    try {
      const response = await askAssistant({ mode: 'auto', message, history, ...(projectId ? { project_id: projectId } : {}) }, controller.signal);
      if (controller.signal.aborted || request.current !== controller) return;
      setConversation(current => ({ ...current, turn: null, messages: [...current.messages,
        { id: `${Date.now()}-u`, role: 'user', content: message },
        { id: `${Date.now()}-a`, role: 'assistant', content: response.reply, actions: response.actions, source: response.source, proposal: response.mode === 'platform' ? response.proposal : null },
      ] }));
    } catch (reason) {
      if (controller.signal.aborted || request.current !== controller) return;
      setConversation(current => ({ ...current, draft: message, turn: { question: message, status: 'error', error: reason instanceof Error ? reason.message : '小航暂时无法回复，请重试。' } }));
    } finally { if (request.current === controller) request.current = null; }
  }
  async function executeProposal() {
    if (!confirmation || executeLock.current) return;
    const leave = applicationLeaveState();
    if (leave.busyMessage || leave.dirty) { setOperationError(leave.busyMessage || '当前业务页面有未保存输入。请先保存或放弃这些输入，再执行小航的操作。'); return; }
    executeLock.current = true; setExecuting(true); setOperationError('');
    try {
      const result = await confirmAssistantProposal(confirmation.id);
      setOperations(previous => ({ ...previous, [confirmation.id]: result })); setConfirmation(null); setContextVersion(value => value + 1);
    } catch (reason) { setOperationError(reason instanceof Error ? reason.message : '操作未完成，请核对后重试。'); }
    finally { executeLock.current = false; setExecuting(false); }
  }
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); void send(conversation.draft); }
  function keydown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (assistantEnterSubmits({ key: event.key, shiftKey: event.shiftKey, isComposing: composing.current || event.nativeEvent.isComposing, keyCode: event.nativeEvent.keyCode })) {
      event.preventDefault(); if (!pending) void send(conversation.draft);
    }
  }
  function actions(items: AssistantAction[], variant: 'quick' | 'reply') {
    return <div className={`xiaohang-actions xiaohang-actions-${variant}`}>{items.map(action => {
      const href = assistantHref(action.href);
      return href && <a key={action.id} href={href} className="xiaohang-action"><span><strong>{action.label}</strong>{variant === 'quick' && <small>{action.description}</small>}</span><AssistantGlyph kind="arrow" /></a>;
    })}</div>;
  }
  function proposalCard(proposal: AssistantProposal) {
    const result = operations[proposal.id];
    return <div className="xiaohang-proposal"><span className="xiaohang-proposal-kicker">{result === 'dismissed' ? '已取消草案' : result ? '操作已完成' : '待你确认的操作'}</span><h4>{proposal.label}</h4><p className="xiaohang-proposal-project">{proposal.project_name} · 版本 {proposal.expected_version}</p><p>{proposal.summary}</p><dl>{proposal.fields.map((field, index) => <div key={`${index}-${field.label}`}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl>{proposal.warnings.length > 0 && <ul className="xiaohang-proposal-warnings">{proposal.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}{!result ? <div className="xiaohang-proposal-buttons"><button type="button" className="feedback-button" disabled={executing} onClick={() => setOperations(previous => ({ ...previous, [proposal.id]: 'dismissed' }))}>取消草案</button><button type="button" className="feedback-button primary" disabled={executing || pending} onClick={() => { setOperationError(''); setConfirmation(proposal); }}>确认执行</button></div> : result !== 'dismissed' && <div className="xiaohang-operation-success" role="status"><p>{result.message}</p>{assistantHref(result.href) && <a href={assistantHref(result.href)!}>查看最新项目记录 →</a>}</div>}</div>;
  }
  const questions = context?.suggested_questions || ['研发管理平台怎么使用？', '研制任务书怎样进入项目流程？', '帮我梳理一个技术问题的分析思路'];
  return <div className={`xiaohang-assistant ${open ? 'is-open' : ''} ${launcherDragging ? 'is-launcher-dragging' : ''}`} style={{ '--xiaohang-pane-width': `${panelWidth}px`, ...(!open && launcherPosition ? { left: launcherPosition.x, top: launcherPosition.y, right: 'auto', bottom: 'auto' } : {}) } as CSSProperties}>
    {open ? <>
      <div className="xiaohang-resizer" role="separator" tabIndex={0} aria-label="调整小航侧栏宽度" aria-orientation="vertical" aria-valuemin={320} aria-valuemax={maximumWidth} aria-valuenow={panelWidth} aria-controls="xiaohang-panel" onPointerDown={startResize} onPointerMove={moveResize} onPointerUp={finishResize} onPointerCancel={finishResize} onKeyDown={keyboardResize}><span /></div>
      <section id="xiaohang-panel" className="xiaohang-panel" role="dialog" aria-modal="false" aria-labelledby="xiaohang-title" onKeyDown={event => { if (event.key === 'Escape' && !confirmation) { event.stopPropagation(); close(); } }}>
        <header className="xiaohang-header"><div className="xiaohang-avatar" aria-hidden="true">{imageFailed ? '航' : <img src="/assets/xiaohang.png" alt="" onError={() => setImageFailed(true)} />}</div><div><h2 id="xiaohang-title">小航 <span>AI 助手</span></h2><p>懂研发，也能陪你聊聊</p></div><div className="xiaohang-header-actions"><button type="button" className="xiaohang-icon-button" aria-label="收起小航对话" title="收起对话（Esc）" disabled={executing} onClick={close}><AssistantGlyph kind="close" /></button></div></header>
        {context?.project && <div className="xiaohang-context"><span className="xiaohang-context-dot" /><span title={context.project.name}>{context.project.code} · {context.project.stage_label}<small>{context.role_label}</small></span></div>}
        <div className="xiaohang-transcript" ref={transcript} role="log" aria-label="小航对话记录" aria-live="polite" aria-relevant="additions text" tabIndex={0} onScroll={event => { const node = event.currentTarget; stickToBottom.current = node.scrollHeight - node.scrollTop - node.clientHeight < 64; }}>
          {!conversation.messages.length && !conversation.turn && <div className="xiaohang-welcome"><span className="xiaohang-eyebrow">你好，我是小航</span><h3>有问题，随时问我</h3><p>研发流程、项目进展、任务办理，或技术和日常问题，都可以直接说。我会理解你想做的事。</p>{context?.quick_actions && actions(context.quick_actions.slice(0, 4), 'quick')}<div className="xiaohang-suggestions" aria-label="试着问小航">{questions.slice(0, 3).map(question => <button key={question} type="button" onClick={() => void send(question)}>{question}<span aria-hidden="true">↗</span></button>)}</div></div>}
          {conversation.messages.map(message => <div key={message.id} className={`xiaohang-message is-${message.role}`}><span className="xiaohang-speaker">{message.role === 'user' ? '我' : '小航'}</span><div className="xiaohang-bubble"><p>{message.content}</p>{message.actions && actions(message.actions, 'reply')}{message.proposal && proposalCard(message.proposal)}{message.source === 'platform-guide' && <small className="xiaohang-source">平台流程指引</small>}</div></div>)}
          {conversation.turn && <><div className="xiaohang-message is-user"><span className="xiaohang-speaker">我</span><div className="xiaohang-bubble"><p>{conversation.turn.question}</p></div></div>{pending ? <div className="xiaohang-pending" role="status"><span className="xiaohang-thinking" aria-hidden="true"><i /><i /><i /></span>小航正在思考…</div> : <div className={`xiaohang-request-note ${conversation.turn.status === 'error' ? 'is-error' : ''}`} role={conversation.turn.status === 'error' ? 'alert' : 'status'}><p>{conversation.turn.error || '已停止等待回复，问题已保留。'}</p>{conversation.turn.status === 'error' && <button type="button" onClick={() => void send(conversation.turn!.question)}>重试这个问题</button>}</div>}</>}
        </div>
        {contextError && <div className="xiaohang-context-error" role="alert"><span>{contextError}</span><button type="button" onClick={() => setContextVersion(value => value + 1)}>重试入口</button></div>}
        <form className="xiaohang-composer" noValidate onSubmit={submit}><label className="xiaohang-input-label" htmlFor="xiaohang-input">向小航发送问题</label><div className="xiaohang-input-wrap"><textarea id="xiaohang-input" ref={input} className="resize-none" rows={3} maxLength={4000} value={conversation.draft} disabled={pending || executing} placeholder="问个问题，或告诉我你想做的事…" onChange={event => setConversation(current => ({ ...current, draft: event.target.value }))} onKeyDown={keydown} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} aria-describedby="xiaohang-composer-hint" /><div className="xiaohang-compose-toolbar"><span>{conversation.draft.length > 3500 ? `${conversation.draft.length}/4000` : 'Enter 发送 · Shift + Enter 换行'}</span>{pending ? <button key="stop" type="button" className="xiaohang-stop" onClick={event => { event.preventDefault(); stop(); }}>停止等待</button> : <button key="send" type="submit" className="xiaohang-send" aria-label="发送给小航" title="发送" disabled={!conversation.draft.trim() || executing}><AssistantGlyph kind="send" /></button>}</div></div><p id="xiaohang-composer-hint">业务操作先预览，确认后按你的项目权限执行。</p></form>
      </section>
    </> : <button ref={launcher} type="button" className="xiaohang-launcher" aria-label="打开小航 AI 助手" aria-description="可拖动到屏幕两侧；方向键调整位置，Home 恢复默认位置，Enter 打开对话" aria-expanded={false} title="点击打开；拖动改变位置，方向键移动，Home 复位" style={{ touchAction: 'none', userSelect: 'none' }} {...launcherEvents}><span className="xiaohang-figure" aria-hidden="true"><XiaohangSprite paused={launcherDragging} /></span><span className="xiaohang-launcher-label">小航<span className="xiaohang-launcher-help">有事问小航</span></span></button>}
    {confirmation && <FeedbackConfirmDialog title={`确认${confirmation.label}？`} confirm="确认执行" cancel="返回核对" pending={executing} error={operationError} onCancel={() => { setConfirmation(null); setOperationError(''); }} onConfirm={() => void executeProposal()}><p><strong>{confirmation.project_name}</strong> · 项目版本 {confirmation.expected_version}</p><p>{confirmation.summary}</p><dl className="xiaohang-confirm-fields">{confirmation.fields.map((field, index) => <div key={index}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl>{confirmation.warnings.length > 0 && <ul>{confirmation.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}<p>确认后将以当前身份执行。项目已更新、权限变化或草案过期时，需要重新生成操作草案。</p></FeedbackConfirmDialog>}
  </div>;
}
