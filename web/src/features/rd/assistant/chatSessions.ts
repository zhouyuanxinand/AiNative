import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { makeRequestKey, rdSession, rdChatDirectory, rdChatDetail, rdChatCreate, rdChatSend, rdChatClose, RD_AUTH_REQUIRED_EVENT, RdApiError, type ChatDetail, type ChatDirectory } from '../api';
import { messageOf } from '../presentation';

type Task = 'load' | 'send' | 'history' | 'preview' | 'earlier' | 'create' | 'close';
type View = 'chat' | 'history' | 'preview';
type Attempt = { fingerprint: string; key: string };
const combine = (older: ChatDetail, newer: ChatDetail) => ({ ...older, messages: [...new Map([...older.messages, ...newer.messages].map(message => [message.id, message])).values()].sort((a, b) => a.seq - b.seq) });

/** The server owns transcripts and active sessions. Only unsent text lives in component state. */
export function useChatSessions(visible: boolean) {
  const [current, setCurrent] = useState<ChatDetail | null>(null);
  const [preview, setPreview] = useState<ChatDetail | null>(null);
  const [directory, setDirectory] = useState<ChatDirectory | null>(null);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState('');
  const [view, setView] = useState<View>('chat');
  const [task, setTask] = useState<Task | null>(null);
  const [verified, setVerified] = useState(false);
  const [error, setError] = useState('');
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const actor = useRef<string | null>(null), epoch = useRef(0), locked = useRef(false);
  const request = useRef<AbortController>(), identityRequest = useRef<AbortController>();
  const attempts = useRef<Record<string, Attempt>>({});
  const latest = useRef({ current, draft, preview, directory, view }); latest.current = { current, draft, preview, directory, view };
  const retryAction = useRef<() => Promise<unknown>>();

  function keyFor(operation: string, payload: unknown) {
    const fingerprint = JSON.stringify(payload);
    if (attempts.current[operation]?.fingerprint !== fingerprint) attempts.current[operation] = { fingerprint, key: makeRequestKey() };
    return attempts.current[operation].key;
  }
  function resetIdentity(next: string | null) {
    actor.current = next; attempts.current = {}; retryAction.current = undefined;
    setCurrent(null); setPreview(null); setDirectory(null); setDraft(''); setPending(''); setView('chat'); setVerified(false);
  }
  async function checkActor(signal: AbortSignal, expected: string | null) {
    const session = await rdSession(signal);
    if (session.actor_id !== expected) {
      resetIdentity(session.actor_id);
      throw new Error('登录身份已变化，请重新读取当前账号的对话。');
    }
  }
  async function perform<T>(kind: Task, action: (signal: AbortSignal) => Promise<T>, success: (result: T) => void, retry: () => Promise<unknown>, force = false) {
    if (locked.current && !force) return false;
    if (force) request.current?.abort();
    const controller = new AbortController(), version = ++epoch.current;
    request.current = controller; locked.current = true;
    setTask(kind); setError(''); setErrorStatus(null); retryAction.current = retry;
    try {
      const value = await action(controller.signal);
      if (version !== epoch.current || controller.signal.aborted) return false;
      success(value); retryAction.current = undefined; return true;
    } catch (reason) {
      if (version === epoch.current && !controller.signal.aborted) { setError(messageOf(reason)); setErrorStatus(reason instanceof RdApiError ? reason.status : null); }
      return false;
    } finally {
      if (version === epoch.current) { request.current = undefined; locked.current = false; setTask(null); setPending(''); }
    }
  }
  async function load(): Promise<boolean> {
    const before = latest.current, previousActor = actor.current;
    setVerified(false);
    return perform('load', async signal => {
      const session = await rdSession(signal);
      if (actor.current !== session.actor_id) resetIdentity(session.actor_id);
      const list = await rdChatDirectory(1, signal);
      const detail = list.active_id ? await rdChatDetail(list.active_id, signal) : null;
      await checkActor(signal, session.actor_id);
      return { list, detail };
    }, ({ list, detail }) => {
      const localDraft = previousActor === actor.current && before.current?.id === detail?.id && before.draft !== (before.current?.draft ?? '');
      setDirectory(list); setCurrent(detail); setDraft(localDraft ? before.draft : detail?.draft ?? ''); setPreview(null); setView('chat'); setVerified(true);
    }, load, true);
  }
  async function revalidateIdentity() {
    identityRequest.current?.abort();
    const controller = new AbortController(); identityRequest.current = controller;
    setVerified(false);
    try {
      const session = await rdSession(controller.signal);
      if (controller.signal.aborted) return;
      if (session.actor_id !== actor.current) {
        epoch.current += 1; request.current?.abort(); locked.current = false;
        resetIdentity(session.actor_id); await load();
      } else setVerified(true);
    } catch (reason) {
      if (!controller.signal.aborted) { setError(messageOf(reason)); retryAction.current = load; }
    }
  }
  // A hidden panel must not paint the previous account before its next identity check.
  useLayoutEffect(() => { if (!visible) setVerified(false); }, [visible]);
  useEffect(() => {
    if (!visible) return;
    void load();
    const focused = () => { if (document.visibilityState !== 'hidden') void revalidateIdentity(); };
    const unauthorized = () => { epoch.current += 1; request.current?.abort(); locked.current = false; setTask(null); resetIdentity(null); setError('登录状态已变化，请登录后重新读取对话。'); retryAction.current = load; };
    window.addEventListener('focus', focused);
    document.addEventListener('visibilitychange', focused);
    window.addEventListener(RD_AUTH_REQUIRED_EVENT, unauthorized);
    return () => { identityRequest.current?.abort(); window.removeEventListener('focus', focused); document.removeEventListener('visibilitychange', focused); window.removeEventListener(RD_AUTH_REQUIRED_EVENT, unauthorized); };
  }, [visible]);
  useEffect(() => () => { epoch.current += 1; request.current?.abort(); identityRequest.current?.abort(); }, []);

  async function history(page = 1): Promise<boolean> {
    const owner = actor.current;
    return perform('history', async signal => { await checkActor(signal, owner); const result = await rdChatDirectory(page, signal); await checkActor(signal, owner); return result; }, result => { setDirectory(result); setView('history'); }, () => history(page));
  }
  async function inspect(id: string): Promise<boolean> {
    const owner = actor.current;
    return perform('preview', async signal => { await checkActor(signal, owner); const result = await rdChatDetail(id, signal); await checkActor(signal, owner); return result; }, result => { setPreview(result); setView('preview'); }, () => inspect(id));
  }
  async function earlier(): Promise<boolean> {
    const target = latest.current.view === 'preview' ? latest.current.preview : latest.current.current;
    if (!target?.has_more || target.next_before === null) return false;
    const owner = actor.current, showingPreview = latest.current.view === 'preview';
    return perform('earlier', async signal => { await checkActor(signal, owner); const result = await rdChatDetail(target.id, signal, target.next_before!); await checkActor(signal, owner); return result; }, result => {
      if (showingPreview) setPreview(combine(result, target)); else setCurrent(combine(result, target));
    }, earlier);
  }
  async function create(sourceId?: string): Promise<boolean> {
    const owner = actor.current, key = keyFor('create', { sourceId });
    return perform('create', async signal => { await checkActor(signal, owner); const result = await rdChatCreate(sourceId, key, signal); await checkActor(signal, owner); return result; }, result => {
      delete attempts.current.create; setCurrent(result); setDraft(result.draft); setPreview(null); setView('chat');
    }, () => create(sourceId));
  }
  async function send(text: string): Promise<boolean> {
    const message = text.trim();
    if (!message || locked.current || !verified) return false;
    if (message.length > 2000) { setError('问题请控制在 2000 字以内。'); return false; }
    setDraft(text); setPending(message);
    const owner = actor.current;
    return perform('send', async signal => {
      await checkActor(signal, owner);
      let conversation = latest.current.current;
      if (!conversation) {
        conversation = await rdChatCreate(undefined, keyFor('create', {}), signal);
        delete attempts.current.create;
        await checkActor(signal, owner); setCurrent(conversation); latest.current.current = conversation;
      }
      const body = { message, expected_version: conversation.version };
      const result = await rdChatSend(conversation.id, body, keyFor('send', { id: conversation.id, ...body }), signal);
      await checkActor(signal, owner); return result;
    }, result => { delete attempts.current.send; setCurrent(result); setDraft(''); setView('chat'); }, () => send(text));
  }
  async function close(choice: 'keep' | 'end'): Promise<boolean> {
    if (locked.current || !verified) return false;
    const owner = actor.current, text = latest.current.draft;
    return perform('close', async signal => {
      await checkActor(signal, owner);
      let conversation = latest.current.current;
      if (!conversation && choice === 'keep' && text) {
        conversation = await rdChatCreate(undefined, keyFor('create', {}), signal);
        delete attempts.current.create;
        await checkActor(signal, owner); setCurrent(conversation); latest.current.current = conversation;
      }
      if (conversation) {
        const body = { choice, draft: text, expected_version: conversation.version };
        await rdChatClose(conversation.id, body, keyFor('close', { id: conversation.id, ...body }), signal);
      }
      await checkActor(signal, owner); return choice;
    }, result => {
      delete attempts.current.close; setError(''); setPreview(null); setView('chat');
      if (result === 'end') { setCurrent(null); setDraft(''); }
      else setCurrent(value => value ? { ...value, draft: text } : value);
    }, () => close(choice));
  }
  return { current, preview, directory, draft, setDraft, pending, view, setView, task, verified, error, errorStatus, busy: task !== null,
    load, history, inspect, earlier, create, send, close, retry: () => retryAction.current?.(), clearError: () => setError('') };
}
