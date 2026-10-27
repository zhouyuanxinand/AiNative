import { useEffect, useRef, useState } from 'react';
import { getReviewEditorSession, openReviewEditor, saveReviewEditor } from '../../api/review';

interface OfficeInstance { destroyEditor: () => void }
declare global { interface Window { DocsAPI?: { DocEditor: new (id: string, config: Record<string, unknown>) => OfficeInstance } } }
async function loadOfficeScript(url: string) {
  if (window.DocsAPI) return;
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement('script'); script.src = url; script.async = true;
    script.onload = () => window.DocsAPI ? resolve() : reject(new Error('版式编辑组件未加载，请检查文档服务配置。'));
    script.onerror = () => { script.remove(); reject(new Error('无法连接文档编辑服务，请检查服务地址与网络。')); };
    document.head.appendChild(script);
  });
}
export function ReviewOfficeEditor({ jid, revision, onDirty, onBusy, onSaved }: {
  jid: string; revision: string; onDirty: (dirty: boolean) => void; onBusy: (busy: boolean) => void; onSaved: (revision: string) => void;
}) {
  const [session, setSession] = useState('');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('正在打开版式编辑…');
  const [saving, setSaving] = useState(false);
  const [ready, setReady] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const editorSurface = useRef<HTMLDivElement>(null);
  const savedVersion = useRef('');
  const editSequence = useRef(0);
  const pendingSave = useRef<{ sequence: number; requestId?: string } | null>(null);
  const callbacks = useRef({ onDirty, onBusy, onSaved }); callbacks.current = { onDirty, onBusy, onSaved };
  useEffect(() => { if (editorSurface.current) editorSurface.current.inert = saving; }, [saving]);
  useEffect(() => {
    let disposed = false; let editor: OfficeInstance | undefined; let timer: ReturnType<typeof setTimeout>;
    async function poll(id: string) {
      try {
        const result = await getReviewEditorSession(jid, id);
        if (disposed) return;
        if (result.status === 'saved' && result.revision_id && savedVersion.current !== result.revision_id) {
          savedVersion.current = result.revision_id;
          callbacks.current.onSaved(result.revision_id);
          setStatus('文档服务已回传一个修订。未确认保存的编辑仍会保留提醒。');
        }
        if (result.status === 'saved' && pendingSave.current?.requestId && result.saved_request_id === pendingSave.current.requestId) {
          if (editSequence.current === pendingSave.current.sequence) callbacks.current.onDirty(false);
          pendingSave.current = null; setSaving(false); callbacks.current.onBusy(false);
          setStatus('版式修改已由服务端保存为新修订。');
        } else if (result.status === 'error') {
          setError(result.message || '文档服务未能保存修改，请重试。'); pendingSave.current = null;
          setSaving(false); callbacks.current.onBusy(false);
        }
      } catch (reason) {
        if (!disposed) {
          setError(`未能确认平台保存结果：${(reason as Error).message}。修改状态仍保留，可重试保存。`);
          pendingSave.current = null; setSaving(false); callbacks.current.onBusy(false);
        }
      }
      if (!disposed) timer = setTimeout(() => void poll(id), 3000);
    }
    const openTimer = setTimeout(() => { void (async () => {
      try {
        const result = await openReviewEditor(jid, revision);
        await loadOfficeScript(result.script_url);
        if (disposed) return;
        setSession(result.session_id);
        editor = new window.DocsAPI!.DocEditor('review-office-host', { ...result.config, events: {
          ...((result.config.events || {}) as Record<string, unknown>),
          onDocumentReady: () => { if (!disposed) { setReady(true); setStatus('可在文档中修改版式，保存后等待服务端确认。'); } },
          onDocumentStateChange: (event: { data?: boolean }) => {
            if (disposed) return;
            setSyncing(Boolean(event.data));
            if (event.data) { editSequence.current += 1; callbacks.current.onDirty(true); }
          },
          onError: (event: { data?: { errorDescription?: string } }) => {
            if (!disposed) {
              setError(event.data?.errorDescription || '版式编辑服务发生错误。');
              pendingSave.current = null; setSaving(false); callbacks.current.onBusy(false);
            }
          },
        } });
        void poll(result.session_id);
      } catch (reason) { if (!disposed) setError((reason as Error).message); }
    })(); }, 0);
    return () => { disposed = true; clearTimeout(openTimer); clearTimeout(timer); editor?.destroyEditor(); };
  }, [jid, revision]);
  async function save() {
    if (!session || saving || syncing) return;
    pendingSave.current = { sequence: editSequence.current };
    setSaving(true); callbacks.current.onBusy(true); setError('');
    try {
      const result = await saveReviewEditor(jid, session);
      setStatus(result.message || '已请求保存，正在等待文档服务回传…');
      if (result.status === 'unchanged') {
        if (editSequence.current === pendingSave.current?.sequence) callbacks.current.onDirty(false);
        pendingSave.current = null; setSaving(false); callbacks.current.onBusy(false);
      } else if (pendingSave.current) pendingSave.current.requestId = result.save_request_id;
    } catch (reason) { setError((reason as Error).message); pendingSave.current = null; setSaving(false); callbacks.current.onBusy(false); }
  }
  return <section className="review-office" aria-label="版式编辑">
    <div className="review-office-toolbar"><p role="status">{syncing ? '正在同步编辑内容，同步完成后可保存。' : status}</p><button className="review-primary" type="button" disabled={!ready || saving || syncing} onClick={() => void save()}>{saving ? '等待保存确认…' : '保存版式修改'}</button></div>
    {error && <p className="review-feedback error" role="alert">{error}</p>}
    <div className="review-office-frame" aria-busy={saving}><div ref={editorSurface} className="review-office-surface"><div id="review-office-host" /></div>{saving && <div className="review-office-saving" role="status" tabIndex={-1}>正在保存到平台，请等待回传确认…</div>}</div>
  </section>;
}
