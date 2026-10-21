import { useEffect, useRef, useState } from 'react';
import { logoutCurrentUser } from '../../api/currentUser';
import { applicationLeaveState, navigateAfterLogout } from '../../hooks/useApplicationLeaveGuard';
import { FeedbackConfirmDialog, FeedbackDialog } from '../feedback/FeedbackDialog';
import './sidebarLogout.css';

export function SidebarLogout({ onFailure }: { onFailure: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState(false);
  const request = useRef<AbortController>();
  useEffect(() => () => request.current?.abort(), []);

  async function logout(confirmed = false) {
    if (request.current) return;
    const leaveState = applicationLeaveState();
    if (leaveState.busyMessage) { setError(leaveState.busyMessage); onFailure(); return; }
    if (leaveState.dirty && !confirmed) { setError(''); setConfirm(true); return; }
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError('');
    try {
      await logoutCurrentUser(controller.signal);
      if (!controller.signal.aborted) navigateAfterLogout();
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : '退出登录失败，请重试。');
        onFailure();
      }
    } finally {
      if (request.current === controller) request.current = undefined;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <div className="sidebar-session-actions" data-application-logout>
      <button className="sidebar-logout" type="button" onClick={() => void logout()}
        disabled={busy} aria-busy={busy} aria-label={busy ? '正在退出登录' : '退出登录'}
        title="退出当前应用登录" aria-describedby={error && !confirm ? 'sidebar-logout-error' : undefined}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M9 4H5v16h4M14 8l4 4-4 4M9 12h9" />
        </svg>
        <span>{busy ? '正在退出…' : '退出登录'}</span>
      </button>
      {error && !confirm && <p id="sidebar-logout-error" className="sidebar-logout-error" role="alert">{error}</p>}
      {busy && !confirm && <FeedbackDialog title="正在退出登录" className="feedback-confirm-dialog" onCancel={() => {}}>
        <p className="feedback-confirm-message" role="status">正在结束当前应用会话，请稍候。</p>
      </FeedbackDialog>}
      {confirm && <FeedbackConfirmDialog title="退出登录前确认" confirm="放弃修改并退出" cancel="继续编辑"
        pending={busy} error={error} onCancel={() => setConfirm(false)} onConfirm={() => void logout(true)}>
        <p>当前页面有填写内容或修改。退出后，未保存的修改与未提交的反馈将丢失；已保存的任务和文件不受影响。</p>
      </FeedbackConfirmDialog>}
    </div>
  );
}
