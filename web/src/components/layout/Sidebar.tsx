/** 左侧边栏——品牌 logo、新建任务、历史列表、用户行、拖拽手柄、服务凭证设置。 */
import { useTaskbook } from '../../hooks/useTaskbook';
import { usePanelResize } from '../../hooks/usePanelResize';
import { useCurrentUser } from '../../hooks/useCurrentUser';
import { ServiceCredentialsSettings } from '../ui/ServiceCredentialsSettings';
import { HELP_RESOURCES } from '../help/helpResources';
import { HelpResourceIcon } from '../help/HelpResourceIcon';
import { SidebarLogout } from './SidebarLogout';
import '../help/helpResources.css';
import '../../feedback.css';
import type { HistoryItem } from '../../types';

export function Sidebar({ onCredentialsSaved }: { onCredentialsSaved: () => Promise<void> }) {
  const { toggleSidebar, sidebarExpanded, history } = useTaskbook();
  const { beginResize, resetPanelWidth } = usePanelResize();
  const { state: identity, retry } = useCurrentUser();
  const user = identity.status === 'ready' && identity.identity.authenticated ? identity.identity.user : null;
  const userLabel = user?.display_name || (identity.status === 'loading' ? '正在读取身份…'
    : identity.status === 'error' ? '身份读取失败' : identity.identity.auth_enabled ? '未登录' : '本地模式');

  return (
    <aside className="sidebar" id="sidebar">
      <div className="sidebar-top">
        <div className="brand">
          <div
            className="brand-mark brand-logo"
            title="中航光电 JONHON"
            aria-label="中航光电 JONHON"
          >
            <img
              src="data:image/png;base64,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"
              alt="中航光电 JONHON"
            />
          </div>
          <div className="brand-copy">
            <h1>研制任务书平台</h1>
            <p>Engineering Taskbook Intelligence</p>
          </div>
        </div>
        <button
          className="sidebar-toggle"
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
      </div>
      <button
        className="new-task-btn"
        type="button"
        onClick={() => window.dispatchEvent(new CustomEvent('taskbook:reset'))}
      >
        <span className="icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </span>
        <span className="txt">新建任务</span>
      </button>
      <div className="sidebar-section-label">历史任务</div>
      <div className="sidebar-history">
        <div className="sidebar-history-list" id="sidebar-history-list">
          {history.length === 0 ? (
            <div className="sidebar-empty">暂无历史任务</div>
          ) : (
            history.map((item, i) => (
              <SidebarHistoryItem key={item.jid || i} item={item} />
            ))
          )}
        </div>
      </div>
      <nav className="sidebar-help-links" aria-label="使用帮助">
        {HELP_RESOURCES.map(resource => (
          <a
            key={resource.kind}
            className="sidebar-help-link"
            href={resource.path}
            target="_blank"
            rel="noopener noreferrer"
            title={`${resource.title}（在新标签页打开）`}
            aria-label={`${resource.title}（在新标签页打开）`}
          >
            <HelpResourceIcon kind={resource.kind} />
            <span>{resource.title}</span>
          </a>
        ))}
      </nav>
      <div className="sidebar-user-row">
        <span className="user-face" aria-hidden="true">{user ? Array.from(user.display_name)[0] : '用'}</span>
        <div className="user-info current-user-info" aria-live="polite">
          <b title={userLabel}>{userLabel}</b>
          {user ? <span title={user.userid}>{user.userid}</span>
            : identity.status === 'error' ? <button className="current-user-retry" type="button" onClick={retry} title={identity.error}>重试读取身份</button>
            : identity.status === 'ready' && identity.identity.auth_enabled ? <a className="current-user-login" href="/auth/login" target="_blank" rel="noopener noreferrer" title="前往统一登录（在新标签页打开）">前往统一登录</a>
            : <span>{identity.status === 'loading' ? '请稍候' : '未启用统一登录'}</span>}
        </div>
        {user && <SidebarLogout onFailure={() => { if (!sidebarExpanded) toggleSidebar(); }} />}
        <ServiceCredentialsSettings onSaved={onCredentialsSaved} />
      </div>
      <button
        className="resize-handle resize-handle-left"
        id="left-resizer"
        type="button"
        aria-label="拖动调整左侧任务栏宽度"
        title="拖动调整左侧任务栏宽度，双击恢复默认宽度"
        aria-valuemin={220}
        aria-valuemax={320}
        onPointerDown={(e) => beginResize('left', e)}
        onDoubleClick={() => resetPanelWidth('left')}
      />
    </aside>
  );
}

function SidebarHistoryItem({ item }: { item: HistoryItem }) {
  const label = (item.product || item.output_name || '历史任务').substring(0, 18);
  return (
    <div className="sidebar-item-wrap">
      <button
        className="sidebar-item"
        type="button"
        title={item.product || item.output_name || '历史任务'}
        onClick={() =>
          window.dispatchEvent(
            new CustomEvent('taskbook:apply-history', {
              detail: { item, autoPrecheck: false },
            }),
          )
        }
      >
        <span>{label}</span>
      </button>
      {item.jid && (item.status === 'done' || item.status === 'blocked' || item.output_name) && <a className="sidebar-review-link" href={`/review/${encodeURIComponent(item.jid)}`} aria-label={`审阅 ${item.product || item.output_name || '历史任务'}`}>审阅</a>}
    </div>
  );
}
