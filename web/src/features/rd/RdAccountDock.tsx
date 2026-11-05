import { useCurrentUser } from '../../hooks/useCurrentUser';
import { SidebarLogout } from '../../components/layout/SidebarLogout';
import { RdNavigationIcon } from './RdNavigationIcon';
import './RdAccountDock.css';

interface Props { onExpand: () => void; onOpenSettings: () => void; settingsActive: boolean; settingsDisabled: boolean }

/** One shared, server-verified identity; never turn a failed lookup into a local user. */
export function RdAccountDock({ onExpand, onOpenSettings, settingsActive, settingsDisabled }: Props) {
  const { state, retry } = useCurrentUser();
  const user = state.status === 'ready' && state.identity.authenticated ? state.identity.user : null;
  const local = state.status === 'ready' && !state.identity.auth_enabled;
  const label = user?.display_name || (state.status === 'loading' ? '正在读取身份…'
    : state.status === 'error' ? '身份读取失败' : local ? '本地模式' : '未登录');

  const avatar = user ? Array.from(user.display_name)[0] : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><circle cx="12" cy="8" r="3.3" /><path d="M5 21v-2a7 7 0 0 1 14 0v2" /></svg>;
  return <div className="rd-account-dock" role="region" aria-label="当前账号与设置" data-identity-state={user ? 'authenticated' : local ? 'local' : state.status}>
    <span className="rd-account-dock-avatar" aria-hidden="true">{avatar}</span>
    <button type="button" className="rd-account-dock-avatar rd-account-dock-expand" onClick={onExpand} aria-label={`展开侧栏查看账号：${label}`} title={state.status === 'error' ? state.error : label}>{avatar}</button>
    <div className="rd-account-dock-identity" aria-live="polite">
      <div className="rd-account-dock-heading"><strong title={label}>{label}</strong>{user && <span className="rd-account-dock-verified" title="身份已通过 OA／问学校验">OA</span>}</div>
      {user ? <span className="rd-account-dock-account" title={user.userid}>{user.userid}</span>
        : state.status === 'loading' ? <span role="status">请稍候</span>
        : state.status === 'error' ? <button type="button" className="rd-account-dock-link" onClick={retry}>重试读取身份</button>
        : local ? <span>未启用统一登录</span>
        : <span className="rd-account-dock-login-actions"><a className="rd-account-dock-link" href="/auth/login" target="_blank" rel="noopener noreferrer" title="前往 OA／问学登录（新标签页）">前往统一登录 ↗</a><button type="button" className="rd-account-dock-refresh" onClick={retry} aria-label="刷新登录状态" title="登录后刷新状态"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.4 6M20 4v7h-7" /></svg></button></span>}
    </div>
    <div className="rd-account-dock-actions">
      {(user || local) && <SidebarLogout onFailure={onExpand} local={local} />}
      <button type="button" className="rd-account-settings" title="系统管理" aria-label="系统管理" aria-current={settingsActive ? 'page' : undefined} disabled={settingsDisabled} onClick={onOpenSettings}><RdNavigationIcon name="settings" /></button>
    </div>
    {state.status === 'error' && <p className="rd-account-dock-error" role="alert">{state.error}</p>}
  </div>;
}
