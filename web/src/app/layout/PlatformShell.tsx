import { useEffect, useState, type ReactNode } from 'react';
import { CurrentUserProvider, useCurrentUser } from '../../shared/auth/useCurrentUser';
import { applicationLeaveState, navigateAfterConfirmedLeave } from '../../shared/hooks/useApplicationLeaveGuard';
import { getRdDemoStatus, getRdWorkspace, switchRdDemoIdentity, type RdDemoStatus, type RdRole } from '../../features/rd/api/rd';
import { roleLabel, projectRole } from '../../features/rd/model/rdWorkbench';
import { PlatformIcon } from '../../shared/ui/PlatformIcon';
import { StyledSelect } from '../../shared/ui/StyledSelect';
import { FeedbackConfirmDialog } from '../../shared/ui/FeedbackDialog';
import { SidebarLogout } from '../../shared/auth/components/SidebarLogout';
import { ServiceCredentialsSettings } from '../../features/settings/components/ServiceCredentialsSettings';
import { SERVICE_CREDENTIALS_CHANGED } from '../../features/settings/api/serviceCredentials';
import { HELP_RESOURCES } from '../../features/help/model/helpResources';
import { XiaohangAssistant } from '../../features/assistant/components/XiaohangAssistant';
import '../../shared/styles/feedback.css';
import './platform.css';

const navigation = [
  { href: '/', name: '我的工作', icon: 'overview' },
  { href: '/rd', name: '项目空间', icon: 'projects' },
  { href: '/requirements', name: '需求中心', icon: 'requirements' },
  { href: '/tasks', name: '研发任务', icon: 'tasks' },
  { href: '/artifacts', name: '成果中心', icon: 'artifacts' },
  { href: '/approvals', name: '审签待办', icon: 'approvals' },
];
/** Canonical shell owns the shared identity provider for all R&D routes and tools. */
export function PlatformShell({ children, active = '/', title }: { children: ReactNode; active?: string; title?: string }) {
  return <CurrentUserProvider><PlatformFrame active={active} title={title}>{children}</PlatformFrame></CurrentUserProvider>;
}
function PlatformFrame({ children, active, title }: { children: ReactNode; active: string; title?: string }) {
  const { state } = useCurrentUser();
  const [menu, setMenu] = useState(false), [demo, setDemo] = useState<RdDemoStatus | null>(null), [switching, setSwitching] = useState(false), [error, setError] = useState(''), [nextUser, setNextUser] = useState('');
  const [duties, setDuties] = useState<RdRole[]>([]);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const user = state.status === 'ready' && state.identity.authenticated ? state.identity.user : null;
  const name = title || navigation.find(item => item.href === active)?.name || '研发工作区';
  useEffect(() => {
    if (!user?.userid) { setDuties([]); return; }
    const controller = new AbortController();
    void getRdWorkspace(controller.signal).then(result => { if (!controller.signal.aborted) setDuties([...new Set(result.projects.map(projectRole))]); }).catch(() => { /* The owning page provides read errors and retry. */ });
    return () => controller.abort();
  }, [user?.userid]);
  const queryNavigation = navigation.slice(2).filter(item => item.href === active || !duties.length || duties.some(duty => {
    if (['owner', 'viewer'].includes(duty)) return true;
    if (duty === 'reviewer') return ['/approvals', '/artifacts', '/requirements'].includes(item.href);
    return ['/tasks', '/requirements', '/artifacts', '/approvals'].includes(item.href);
  }));
  const navLink = (item: typeof navigation[number]) => <a key={item.href} href={item.href} className={`platform-nav-link ${active === item.href ? 'is-active' : ''}`} aria-current={active === item.href ? 'page' : undefined}><PlatformIcon kind={item.icon} /><span>{item.name}</span>{active === item.href && <i className="platform-current-dot" />}</a>;
  useEffect(() => { const controller = new AbortController(); void getRdDemoStatus(controller.signal).then(setDemo).catch(() => { /* The deployment may omit demo endpoints. Enterprise identity remains authoritative. */ }); return () => controller.abort(); }, []);
  useEffect(() => { document.title = `${name} · 研发管理平台`; }, [name]);
  async function switchRole(userId: string) {
    if (switching || !userId || userId === user?.userid) return;
    setSwitching(true); setError('');
    try { await switchRdDemoIdentity(userId); navigateAfterConfirmedLeave(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '演示身份切换失败，请重试。'); setSwitching(false); setNextUser(''); }
  }
  function selectRole(userId: string) {
    const leave = applicationLeaveState();
    if (leave.busyMessage) { setError(leave.busyMessage); return; }
    if (leave.dirty) setNextUser(userId); else void switchRole(userId);
  }
  return <div className={`platform-shell ${assistantOpen ? 'has-assistant-open' : ''}`}>
    {menu && <button type="button" className="platform-nav-scrim" aria-label="收起导航" onClick={() => setMenu(false)} />}
    <aside className={`platform-sidebar ${menu ? 'is-open' : ''}`} aria-label="平台导航">
      <a href="/" className="platform-brand"><span className="platform-brand-mark" aria-hidden="true"><i /><i /><i /><i /></span><span><strong>研发管理平台</strong><small>JONHON · R&D WORKSPACE</small></span></a>
      <div className="platform-nav-section">研发协作</div>
      <nav aria-label="研发业务">{navigation.slice(0, 2).map(navLink)}</nav>
      <div className="platform-nav-section platform-nav-query-label">跨项目查询</div>
      <nav aria-label="跨项目查询">{queryNavigation.map(navLink)}</nav>
      <div className="platform-nav-section platform-nav-divider">研发工具</div>
      <nav aria-label="研发工具"><a href="/taskbook" className={`platform-nav-link ${active === '/taskbook' ? 'is-active' : ''}`} aria-current={active === '/taskbook' ? 'page' : undefined}><PlatformIcon kind="generator" /><span>任务书生成</span></a></nav>
      <nav aria-label="使用帮助" className="platform-help-links">{HELP_RESOURCES.map(item => <a key={item.kind} className="platform-nav-link" href={item.path} target="_blank" rel="noopener noreferrer" title={`${item.title}（新标签页）`}><PlatformIcon kind={item.kind === 'manual' ? 'requirements' : 'generator'} /><span>{item.title}</span></a>)}</nav>
      <div className="platform-sidebar-spacer" />
      <div className="platform-sidebar-note"><span className="platform-live-dot" />{duties.length === 1 ? roleLabel(duties[0]) : '需求驱动 · 过程可追溯'}</div>
      <div className="platform-account"><span className="platform-avatar">{user ? Array.from(user.display_name)[0] : '研'}</span><div><strong>{user?.display_name || (state.status === 'loading' ? '正在读取身份…' : '未登录')}</strong><small>{user?.userid || '研发协同工作区'}</small></div>{user && <><SidebarLogout onFailure={() => setMenu(true)} /><ServiceCredentialsSettings onSaved={async () => { window.dispatchEvent(new Event(SERVICE_CREDENTIALS_CHANGED)); }} /></>}</div>
    </aside>
    <div className="platform-main-column"><header className="platform-topbar"><div className="platform-topbar-path"><button type="button" className="platform-menu-toggle" aria-label="展开平台导航" aria-expanded={menu} onClick={() => setMenu(value => !value)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg></button><span>研发工作台</span><span className="platform-path-divider">/</span><strong>{name}</strong></div><div className="platform-topbar-meta"><span className="platform-environment">{demo?.enabled ? '演示环境' : '研发工作区'}</span><time dateTime={new Date().toISOString().slice(0, 10)}>{new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'short', timeZone: 'Asia/Shanghai' }).format(new Date())}</time></div></header>
      {demo?.enabled && <div className="platform-demo-strip"><span><b>演示环境</b><span>按项目负责人、工程师与评审的实际分工办理工作</span></span><div className="platform-demo-switch"><StyledSelect aria-label="切换演示角色" value={user?.userid || demo.current_user_id || ''} options={demo.users.map(item => ({ value: item.userid, label: `${item.display_name} · ${roleLabel(item.role)}` }))} onChange={selectRole} disabled={switching} />{switching && <span role="status">正在切换…</span>}</div></div>}
      {error && <p className="feedback-error platform-shell-error" role="alert">{error}</p>}
      <main className="platform-content" id="platform-content">{children}</main>
    </div>
    {user && <XiaohangAssistant key={user.userid} onOpenChange={setAssistantOpen} />}
    {nextUser && <FeedbackConfirmDialog title="切换演示角色？" confirm="放弃修改并切换" cancel="继续编辑" pending={switching} onCancel={() => setNextUser('')} onConfirm={() => void switchRole(nextUser)}><p>当前有未保存的输入。切换身份后会重新读取该角色可访问的项目，未保存的输入将丢失。</p></FeedbackConfirmDialog>}
  </div>;
}
