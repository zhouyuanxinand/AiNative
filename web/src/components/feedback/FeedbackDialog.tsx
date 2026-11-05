import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { Button, Modal } from 'antd';
import '../ui/antdControls.css';

export function FeedbackDialog({ title, children, className = '', visible = true, onCancel, shouldRestoreFocus }: {
  title: string; children: ReactNode; className?: string; visible?: boolean; onCancel: () => void;
  shouldRestoreFocus?: () => boolean;
}) {
  const anchor = useRef<HTMLSpanElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [container, setContainer] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => {
    setContainer(anchor.current?.closest('dialog') ?? document.body);
  }, []);
  useLayoutEffect(() => {
    if (!visible) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    // Callers unmount these dialogs on close. rc-dialog's animated afterClose cannot run then.
    // Restore here once; Ant Design remains the sole owner of focus trapping and keyboard handling.
    return () => queueMicrotask(() => {
      if (shouldRestoreFocus && !shouldRestoreFocus()) return;
      if (trigger?.isConnected && !trigger.closest('[hidden], [inert]') && trigger.getClientRects().length) trigger.focus({ preventScroll: true });
      else if (!document.activeElement || document.activeElement === document.body) document.getElementById('feedback-list-title')?.focus({ preventScroll: true });
    });
  }, [visible]);
  useEffect(() => {
    if (visible) heading.current?.focus({ preventScroll: true });
  }, [title, visible, container]);
  const width = className.includes('feedback-confirm-dialog') ? 460 : className.includes('rd-create-dialog') ? 620 : 860;
  return <><span ref={anchor} hidden />{container && <Modal
    open={visible}
    title={<h2 ref={heading} tabIndex={-1} className="feedback-dialog-title">{title}</h2>}
    className={`feedback-dialog platform-feedback-modal ${className}`.trim()}
    rootClassName="platform-feedback-modal-root"
    getContainer={container}
    width={width}
    centered
    footer={null}
    closable={false}
    maskClosable
    keyboard
    focusTriggerAfterClose={false}
    onCancel={event => { event.stopPropagation(); onCancel(); }}
  >{children}</Modal>}</>;
}

export function FeedbackConfirmDialog({ title, children, confirm, cancel = '取消', pending = false, confirmDisabled = false, error, danger = false, visible = true, onCancel, onConfirm, saveAction }: {
  title: string; children: ReactNode; confirm: string; cancel?: string; pending?: boolean; error?: string;
  danger?: boolean; visible?: boolean; confirmDisabled?: boolean; onCancel: () => void; onConfirm: () => void;
  saveAction?: { label: string; disabled?: boolean; onClick: () => void };
}) {
  return <FeedbackDialog title={title} visible={visible} className="feedback-confirm-dialog" onCancel={() => { if (!pending) onCancel(); }}>
    <div className="feedback-confirm-message">{children}</div>
    {error && <p className="feedback-error" role="alert">{error}</p>}
    <div className="feedback-dialog-actions">
      <Button autoInsertSpace={false} disabled={pending} onClick={onCancel}>{cancel}</Button>
      <Button type={saveAction ? 'default' : 'primary'} autoInsertSpace={false} aria-label={pending ? '正在处理…' : confirm} danger={danger} disabled={pending || confirmDisabled} loading={pending} onClick={onConfirm}>{pending ? '正在处理…' : confirm}</Button>
      {saveAction && <Button type="primary" autoInsertSpace={false} disabled={pending || saveAction.disabled} onClick={saveAction.onClick}>{saveAction.label}</Button>}
    </div>
  </FeedbackDialog>;
}
