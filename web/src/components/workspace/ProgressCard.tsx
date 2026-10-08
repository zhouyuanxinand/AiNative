/** 进度卡片——进度条 + 实时状态 + 取消/重置按钮 + 日志终端。 */
import { useTaskbook } from '../../hooks/useTaskbook';

export function ProgressCard() {
  const {
    showProgressCard,
    progressPercent,
    progressLiveText,
    progressLiveClass,
    isRunning,
    isCancelled,
    jobStatus,
    logs,
  } = useTaskbook();

  if (!showProgressCard) return null;

  return (
    <div className="card progress-wrap" id="progress-card">
      <h2>
        {jobStatus === 'error' ? '受控工作流失败'
          : jobStatus === 'cancelled' ? '本次任务已停止'
            : '正在执行受控工作流'}
      </h2>
      <div className="prog-bar-bg">
        <div className="prog-bar" id="prog-bar" style={{ width: `${progressPercent}%` }} />
      </div>
      <div className={progressLiveClass} id="progress-live">
        {progressLiveText}
      </div>
      <div className="progress-actions">
        {isRunning && (
          <button
            type="button"
            className="btn-stop"
            id="btn-cancel"
            onClick={() => window.dispatchEvent(new CustomEvent('taskbook:cancel'))}
          >
            停止本次任务
          </button>
        )}
        {isCancelled && (
          <button
            type="button"
            className="btn-progress-reset"
            id="btn-progress-reset"
            onClick={() => window.dispatchEvent(new CustomEvent('taskbook:reset'))}
          >
            返回重新选择
          </button>
        )}
      </div>
      <div className="log-box" id="log-box">
        {logs.map((entry, i) => (
          <div key={i} className={entry.cls || autoLogClass(entry.text)}>
            {entry.text}
          </div>
        ))}
      </div>
    </div>
  );
}

function autoLogClass(msg: string): string {
  if (msg.includes('✅') || msg.includes('完成') || msg.includes('通过')) return 'ok';
  if (msg.includes('⚠') || msg.includes('警告')) return 'warn';
  if (msg.includes('❌') || msg.includes('失败') || msg.includes('错误')) return 'err';
  if (msg.includes('🤖') || msg.includes('LLM') || msg.includes('🔍') || msg.includes('📝')) return 'info';
  return '';
}
