import { createContext, useContext, useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { RdApiError, rdRequestKey } from '../api/rd';
import { StyledSelect, type StyledSelectOption } from '../../../shared/ui/StyledSelect';
import { FeedbackConfirmDialog } from '../../../shared/ui/FeedbackDialog';

export const RdDraftContext = createContext<(id: string, dirty: boolean) => void>(() => {});
export const rdTime = (value?: string) => value ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '—';
const labels: Record<string, string> = { owner: '负责人', engineer: '工程师', reviewer: '审核人', viewer: '只读成员', todo: '待开始', in_progress: '办理中', in_review: '待审签', done: '已完成', changes_requested: '退回修改', needs_revalidation: '待复核基线', pending: '待审签', approved: '已批准', rejected: '已退回', withdrawn: '已撤回', input_changed: '输入已变化', draft: '工作稿', passed: '自动检查通过', unknown: '未核验', running: '自动检查中', failed: '自动检查未通过', open: '待澄清', resolved: '已澄清', completed: '已完成', accepted: '已接收', superseded: '已被新交接替代' };
export const rdLabel = (value: string) => labels[value] || value;
export function RdStatus({ value, label }: { value: string; label?: string }) { return <span className={`rd-status rd-status-${value}`}>{label || rdLabel(value)}</span>; }
export function RdError({ error, retry }: { error: unknown; retry?: () => void }) {
  const status = error instanceof RdApiError ? error.status : undefined;
  return <div className="feedback-error" role="alert"><strong>{status === 403 ? '无项目操作权限' : status === 401 ? '登录已失效' : status === 404 ? '项目或记录不可用' : status === 409 ? '记录已变化，请核对最新版本' : '操作未完成'}</strong><p>{error instanceof Error ? error.message : String(error)}</p>{status === 401 && <a href="/auth/login" target="_blank" rel="noopener noreferrer">前往统一登录（新标签页）</a>}{retry && <button className="feedback-link" type="button" onClick={retry}>重新读取</button>}</div>;
}
export function RdField({ label, value, onChange, required = false, multiline = false, type = 'text', options, disabled = false, hint }: { label: string; value: string; onChange: (value: string) => void; required?: boolean; multiline?: boolean; type?: string; options?: StyledSelectOption[]; disabled?: boolean; hint?: string }) {
  const id = useId();
  return <label className={`rd-field ${multiline ? 'rd-field-wide' : ''}`} htmlFor={id}><span>{label}{required ? ' *' : ''}</span>{options ? <StyledSelect id={id} aria-label={`${label}${required ? ' *' : ''}`} value={value} onChange={onChange} options={options} required={required} disabled={disabled} /> : multiline ? <textarea id={id} value={value} onChange={e => onChange(e.target.value)} rows={4} required={required} disabled={disabled} className="resize-none" aria-describedby={hint ? `${id}-hint` : undefined} /> : <input id={id} type={type} value={value} onChange={e => onChange(e.target.value)} required={required} disabled={disabled} maxLength={type === 'date' ? undefined : 500} aria-describedby={hint ? `${id}-hint` : undefined} />}{hint && <small id={`${id}-hint`}>{hint}</small>}</label>;
}
export interface RdOperationProps { label: string; children?: ReactNode; execute: (key: string) => Promise<void>; fingerprint: string; disabled?: boolean; submitDisabled?: boolean; dirty?: boolean; confirmation?: ReactNode; danger?: boolean; onSuccess?: () => void; onPendingChange?: (pending: boolean) => void; onUncertainChange?: (uncertain: boolean) => void }
/** A failed attempt retains its exact request key; editing the payload starts a different operation. */
export function RdOperation({ label, children, execute, fingerprint, disabled = false, submitDisabled = false, dirty = false, confirmation, danger = false, onSuccess, onPendingChange, onUncertainChange }: RdOperationProps) {
  const [pending, setPending] = useState(false), [error, setError] = useState<unknown>(null), [success, setSuccess] = useState(false), [confirming, setConfirming] = useState(false), [uncertain, setUncertain] = useState(false);
  const locked = useRef(false), attempt = useRef<{ fingerprint: string; key: string; execute: (key: string) => Promise<void> }>(), form = useRef<HTMLFormElement>(null);
  const reportDraft = useContext(RdDraftContext), id = useId(), composing = useRef(false);
  useEffect(() => { reportDraft(id, dirty || pending || uncertain); return () => reportDraft(id, false); }, [reportDraft, id, dirty, pending, uncertain]);
  async function run() {
    if (locked.current || disabled || submitDisabled) return;
    locked.current = true; setPending(true); onPendingChange?.(true); setError(null); setSuccess(false);
    if (!uncertain && attempt.current?.fingerprint !== fingerprint) attempt.current = { fingerprint, key: rdRequestKey(), execute };
    try { await attempt.current!.execute(attempt.current!.key); attempt.current = undefined; setUncertain(false); onUncertainChange?.(false); setSuccess(true); setConfirming(false); onSuccess?.(); }
    catch (reason) { setError(reason); const ambiguous = reason instanceof RdApiError && (reason.status === 0 || reason.status === 408 || reason.status >= 500); setUncertain(ambiguous); onUncertainChange?.(ambiguous); if (!ambiguous) attempt.current = undefined; }
    finally { locked.current = false; setPending(false); onPendingChange?.(false); }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (composing.current) return;
    const invalid = Array.from(form.current?.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('input[required],textarea[required],select[required]') || []).find(input => !input.disabled && !input.value.trim());
    if (invalid && !uncertain) { const target = invalid instanceof HTMLSelectElement ? invalid.parentElement?.querySelector('button') || invalid : invalid; target.setAttribute('aria-invalid', 'true'); target.setAttribute('aria-describedby', `${id}-error`); target.focus(); setError(new Error('请填写标记 * 的必填内容。')); return; }
    form.current?.querySelectorAll('[aria-invalid=true]').forEach(node => node.removeAttribute('aria-invalid'));
    if (confirmation) setConfirming(true); else void run();
  }
  return <form ref={form} noValidate className="rd-operation" onSubmit={submit} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}><fieldset disabled={pending || disabled}><fieldset disabled={uncertain}>{children}</fieldset><div className="rd-actions"><button className={`feedback-button ${danger ? 'danger' : 'primary'}`} disabled={pending || disabled || submitDisabled} type="submit" aria-busy={pending}>{label}</button>{pending && <span role="status">正在处理…</span>}{success && <span className="rd-success" role="status">已完成</span>}</div></fieldset>{uncertain && <p className="rd-muted">本次结果待确认，输入已暂时锁定。再次点击“{label}”将核对同一次操作，不会重复提交新记录。</p>}{error !== null && <div id={`${id}-error`}><RdError error={error} /></div>}{confirming && <FeedbackConfirmDialog title={label} confirm={label} pending={pending} error={error instanceof Error ? error.message : undefined} danger={danger} onCancel={() => setConfirming(false)} onConfirm={() => void run()}>{confirmation}</FeedbackConfirmDialog>}</form>;
}
export function RdPager({ page, total, size = 10, onChange }: { page: number; total: number; size?: number; onChange: (page: number) => void }) {
  const max = Math.max(1, Math.ceil(total / size));
  return <div className="rd-pagination"><span>共 {total} 条 · 第 {Math.min(page, max)} / {max} 页</span><div className="rd-actions"><button className="feedback-button" type="button" disabled={page <= 1} onClick={() => onChange(page - 1)}>上一页</button><button className="feedback-button" type="button" disabled={page >= max} onClick={() => onChange(page + 1)}>下一页</button></div></div>;
}
export function RdPaged<T>({ items, name, children }: { items: T[]; name: string; children: (items: T[]) => ReactNode }) {
  const param = `rd_${name}_page`, [page, setPage] = useState(() => Math.max(1, Number(new URLSearchParams(location.search).get(param)) || 1));
  const current = Math.min(page, Math.max(1, Math.ceil(items.length / 10)));
  useEffect(() => { const restore = () => setPage(Math.max(1, Number(new URLSearchParams(location.search).get(param)) || 1)); window.addEventListener('popstate', restore); return () => window.removeEventListener('popstate', restore); }, [param]);
  return <>{Array.from({ length: Math.max(1, Math.ceil(items.length / 10)) }, (_, index) => <div key={index} hidden={current !== index + 1}>{children(items.slice(index * 10, (index + 1) * 10))}</div>)}<RdPager page={current} total={items.length} onChange={value => { const url = new URL(location.href); url.searchParams.set(param, String(value)); history.pushState(null, '', url); setPage(value); }} /></>;
}
