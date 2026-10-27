/** 顶栏——导航 + 6 步流程进度条 + LLM 状态点。 */
import { Fragment } from 'react';
import { useTaskbook } from '../../hooks/useTaskbook';
import { FLOW_STEPS } from '../../constants';

export function Header() {
  const {
    currentStep,
    jobStatus,
    backendHealthReady,
    backendHealth,
    currentJid,
    sidebarExpanded,
    toggleSidebar,
    managementKind,
    setManagementKind,
    setWorkspaceView,
    setReviewTab,
    showToast,
  } = useTaskbook();

  const progress = Math.max(0, Math.min(100, Math.round(((currentStep - 1) / 5) * 100)));
  const stopped = jobStatus === 'error' || jobStatus === 'cancelled';
  const healthText =
    backendHealth === null
      ? '无法读取后台语义模型状态'
      : !backendHealth.llm?.configured
        ? '语义模型未连接：受控生成会被后台拒绝'
        : backendHealth.runtime?.semantic_retrieval
          ? backendHealth.runtime?.semantic_rerank
            ? '语义模型已连接；Embedding 与 Rerank 检索增强已启用'
            : '语义模型已连接；Embedding 检索已启用，Rerank 当前未启用'
          : '语义模型已连接；使用实时模板标题树路由';

  const openLatestReport = () => {
    if (currentJid) {
      window.open(`/api/report/${encodeURIComponent(currentJid)}`, '_blank', 'noopener');
      return;
    }
    setManagementKind(null);
    setWorkspaceView('generate');
    setReviewTab('result');
    if (!sidebarExpanded) toggleSidebar();
    showToast('暂无当前任务报告，已定位到历史任务区', 'warn');
    requestAnimationFrame(() =>
      document.getElementById('sidebar-history-list')?.scrollIntoView({ block: 'start' }),
    );
  };

  return (
    <div className="header">
      <div className="header-row">
        <div className="header-brand-slot" aria-label="研制任务书平台" data-platform-slot>
          <div className="brand-copy">
            <h1>研制任务书平台</h1>
            <p>Engineering Taskbook Intelligence</p>
          </div>
        </div>
        <button
          className="sidebar-toggle mobile-sidebar-toggle"
          type="button"
          onClick={toggleSidebar}
          aria-label={sidebarExpanded ? '收起侧栏' : '展开侧栏'}
          title={sidebarExpanded ? '收起侧栏' : '展开侧栏'}
          data-sidebar-state={sidebarExpanded ? 'expanded' : 'collapsed'}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d={sidebarExpanded ? 'm15 18-6-6 6-6' : 'm9 18 6-6-6-6'} />
          </svg>
        </button>
        <div className="top-nav">
          <button
            type="button"
            className={!managementKind ? 'active' : ''}
            data-page="home"
            onClick={() => {
              setManagementKind(null);
              setWorkspaceView('generate');
            }}
          >
            首页
          </button>
          <button
            type="button"
            className={managementKind === 'rules' ? 'active' : ''}
            data-page="rules"
            onClick={() => {
              setManagementKind('rules');
              setWorkspaceView('rules');
            }}
          >
            规则中心
          </button>
          <button
            type="button"
            className={managementKind === 'templates' ? 'active' : ''}
            data-page="templates"
            onClick={() => {
              setManagementKind('templates');
              setWorkspaceView('templates');
            }}
          >
            模板目录
          </button>
          <button
            type="button"
            className={managementKind === 'failures' ? 'active' : ''}
            data-page="failures"
            onClick={() => {
              setManagementKind('failures');
              setWorkspaceView('failures');
            }}
          >
            故障数据库
          </button>
          <button
            type="button"
            onClick={openLatestReport}
          >
            质量报告
          </button>
        </div>
      </div>
      <div className="header-row bottom">
        <div className="flow-bar" aria-label="生成流程与当前进度">
          <div className="flow-sequence">
            <span className="flow-label">生成流程：</span>
            {FLOW_STEPS.map((label, i) => {
              const stepNum = i + 1;
              const isActive = currentStep === stepNum;
              const isDone = currentStep > stepNum;
              return (
                <Fragment key={stepNum}>
                  <span
                    id={`fbs-${stepNum}`}
                    className={`flow-step ${isActive ? (stopped ? 'stopped' : 'active') : ''} ${isDone ? 'done' : ''}`}
                  >
                    <span className="num">{stepNum}</span> {label}
                  </span>
                  {stepNum < 6 && (
                    <span className="flow-arrow" aria-hidden="true">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="m9 18 6-6-6-6" />
                      </svg>
                    </span>
                  )}
                </Fragment>
              );
            })}
          </div>
          <div className="flow-progress">
            <span>{stopped ? '已停止，当前进度：' : '完成进度：'}</span>
            <span className="track" aria-hidden="true">
              <span className="value" id="flow-progress-value" style={{ width: `${progress}%` }} />
            </span>
            <span className="count" id="flow-progress-count">
              {progress}%
            </span>
          </div>
        </div>
        <div className="system-state">
          <i
            className="state-dot"
            style={{
              background:
                backendHealthReady === null
                  ? 'var(--warning)'
                  : backendHealthReady
                    ? 'var(--green)'
                    : 'var(--red)',
            }}
          />
          <span id="llm-gate-status">
            {healthText}
          </span>
        </div>
      </div>
    </div>
  );
}
