import { useEffect, useId, useRef, type ReactNode } from 'react';
import { useDialogBackdrop } from '../../hooks/useDialogBackdrop';

/** Native modal lifecycle follows the existing service-settings and document-review dialogs. */
export function FeedbackDialog({ title, children, className = '', visible = true, onCancel }: {
  title: string; children: ReactNode; className?: string; visible?: boolean; onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const titleId = useId();
  const backdrop = useDialogBackdrop(onCancel);
  useEffect(() => {
    if (!visible) return;
    const element = ref.current!;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    element.showModal();
    return () => {
      element.close();
      if (trigger?.isConnected) trigger.focus();
      else document.getElementById('feedback-list-title')?.focus();
    };
  }, [visible]);
  useEffect(() => {
    if (visible) heading.current?.focus();
  }, [title, visible]);
  return <dialog ref={ref} className={`feedback-dialog ${className}`} aria-labelledby={titleId} {...backdrop}
    onCancel={event => { event.preventDefault(); event.stopPropagation(); onCancel(); }}>
    <h2 ref={heading} tabIndex={-1} id={titleId} className="feedback-dialog-title">{title}</h2>{children}
  </dialog>;
}

export function FeedbackConfirmDialog({ title, children, confirm, cancel = '取消', pending = false, error, danger = false, visible = true, onCancel, onConfirm }: {
  title: string; children: ReactNode; confirm: string; cancel?: string; pending?: boolean; error?: string;
  danger?: boolean; visible?: boolean; onCancel: () => void; onConfirm: () => void;
}) {
  return <FeedbackDialog title={title} visible={visible} className="feedback-confirm-dialog" onCancel={() => { if (!pending) onCancel(); }}>
    <div className="feedback-confirm-message">{children}</div>
    {error && <p className="feedback-error" role="alert">{error}</p>}
    <div className="feedback-dialog-actions"><button type="button" className="feedback-button" disabled={pending} onClick={onCancel}>{cancel}</button>
      <button type="button" className={`feedback-button ${danger ? 'danger' : 'primary'}`} disabled={pending} onClick={onConfirm}>{pending ? '正在处理…' : confirm}</button></div>
  </FeedbackDialog>;
}
