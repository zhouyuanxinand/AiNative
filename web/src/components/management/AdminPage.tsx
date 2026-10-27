import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { FeedbackAdminPage } from '../feedback/FeedbackAdminPage';
import { PlatformAuthSettings } from '../ui/PlatformAuthSettings';
import { RequestLogsView } from './RequestLogsView';
import { ADMIN_ACCESS_EVENT, AdminApiError, getAdminSession, logoutAdmin, type AdminAccessFailure, type AdminSession } from '../../api/adminAccess';
import { FeedbackConfirmDialog } from '../feedback/FeedbackDialog';
import { AdminMembersView } from './AdminMembersView';
import { HelpResourcesView } from './HelpResourcesView';
import { hasAdminUnsavedChanges } from './adminDrafts';
import { urlWithQuery } from '../../lib/url';
import '../../feedback.css';
import './adminPage.css';

type AdminView = 'feedback' | 'logs' | 'resources' | 'admins';
const labels: Record<AdminView, string> = { feedback: '用户反馈', logs: '运行日志', resources: '操作资料上传', admins: '管理员名单' };
const currentView = (): AdminView => {
  const view = new URLSearchParams(window.location.search).get('view');
  return view === 'logs' || view === 'admins' || view === 'resources' ? view : 'feedback';
};

function viewURL(view: AdminView) {
  const params = new URLSearchParams(window.location.search);
  if (view !== 'feedback') params.set('view', view); else params.delete('view');
  return urlWithQuery('/admin', params);
}

function MenuIcon({ view }: { view: AdminView }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {view === 'feedback' ? <><path d="M5 3h14v14H9l-4 4V3Z"/><path d="M9 7h6M9 11h6"/></> : view === 'admins' ? <><path d="M12 3 4 6v5c0 5 8 10 8 10s8-5 8-10V6L12 3Z"/><path d="m8 12 3 3 5-6"/></> : view === 'resources' ? <><path d="M14 3H5v18h14V8l-5-5Z"/><path d="M14 3v5h5m-7 9v-6m-3 3 3-3 3 3"/></> : <><path d="M4 5h16M4 12h16M4 19h10"/><path d="m17 17 2 2 4-4"/></>}
  </svg>;
}

export function AdminPage() {
  const [session, setSession] = useState<AdminSession | null>(null);
  const [checking, setChecking] = useState(true);
  const [failure, setFailure] = useState<AdminAccessFailure | null>(null);
  const [logoutPending, setLogoutPending] = useState(false);
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [logoutError, setLogoutError] = useState('');
  const request = useRef<AbortController>();
  const logoutRequest = useRef<AbortController>();
  const alive = useRef(true);
  const authorized = useRef(false);

  async function check() {
    if (request.current) return;
    const controller = new AbortController(); request.current = controller;
    if (!authorized.current) setChecking(true);
    try {
      const result = await getAdminSession(controller.signal);
      if (!alive.current || controller.signal.aborted) return;
      authorized.current = true; setSession(result); setFailure(null);
    } catch (cause) {
      if (!alive.current || controller.signal.aborted) return;
      authorized.current = false; setSession(null);
      setFailure(cause instanceof AdminApiError ? cause.failure : { status: 0, error: '无法验证管理员身份，请重试。' });
    } finally {
      if (request.current === controller) request.current = undefined;
      if (alive.current && !controller.signal.aborted) setChecking(false);
    }
  }

  useEffect(() => {
    alive.current = true;
    document.body.classList.add('admin-page');
    const title = document.title;
    document.title = '管理员登录 · 研制任务书平台';
    const invalidated = (event: Event) => {
      request.current?.abort(); request.current = undefined;
      authorized.current = false; setSession(null); setConfirmLogout(false); setChecking(false);
      setFailure((event as CustomEvent<AdminAccessFailure>).detail);
    };
    const onVisible = () => { if (document.visibilityState === 'visible' && authorized.current) void check(); };
    window.addEventListener(ADMIN_ACCESS_EVENT, invalidated);
    const beforeLeave = (event: BeforeUnloadEvent) => {
      if (hasAdminUnsavedChanges()) { event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', beforeLeave);
    window.addEventListener('focus', onVisible);
    document.addEventListener('visibilitychange', onVisible);
    const timer = window.setInterval(onVisible, 30000);
    void check();
    return () => {
      alive.current = false; request.current?.abort(); request.current = undefined; logoutRequest.current?.abort();
      window.clearInterval(timer); window.removeEventListener(ADMIN_ACCESS_EVENT, invalidated);
      window.removeEventListener('beforeunload', beforeLeave);
      window.removeEventListener('focus', onVisible); document.removeEventListener('visibilitychange', onVisible);
      document.body.classList.remove('admin-page'); document.title = title;
    };
  }, []);

  async function signOut() {
    if (logoutRequest.current) return;
    const controller = new AbortController(); logoutRequest.current = controller;
    setLogoutPending(true); setLogoutError('');
    try {
      await logoutAdmin(controller.signal);
      if (!alive.current || controller.signal.aborted) return;
      request.current?.abort(); request.current = undefined;
      authorized.current = false; setSession(null); setConfirmLogout(false); setChecking(false);
      setFailure({ status: 401, code: 'AUTH_REQUIRED', error: '已退出管理员页面。再次进入时需要完成 OA 身份验证。' });
    } catch (cause) {
      if (alive.current && !controller.signal.aborted) setLogoutError(cause instanceof Error ? cause.message : '退出失败，请重试。');
    } finally {
      logoutRequest.current = undefined;
      if (alive.current) setLogoutPending(false);
    }
  }

  if (!session) {
    const denied = failure?.status === 403;
    const canLogin = failure?.status === 401 || denied;
    return <main className="admin-access-page"><div className="admin-access-brand"><strong>JONHON</strong><span>研制任务书平台</span></div>
      <section className="admin-access-panel" aria-labelledby="admin-access-title" aria-busy={checking}>
        <h1 id="admin-access-title">{checking ? '正在验证管理员身份' : denied ? '当前账号没有管理员权限' : canLogin ? '登录管理员页面' : '暂时无法验证管理员身份'}</h1>
        {checking ? <p role="status">正在检查 OA 登录状态与管理员名单…</p> : <>
          <p role={canLogin ? 'status' : 'alert'}>{failure?.error || '管理员服务暂不可用，请重试。'}</p>
          {denied && failure?.username && <p className="admin-access-account">当前 OA 账号：<strong>{failure.username}</strong></p>}
          <p className="admin-access-hint">{denied ? '请联系 wangxue 将您的 OA 登录账号加入管理员名单；需要切换账号时，请先在 OA／问学退出当前账号。' : '使用 OA／问学账号登录，通过身份验证且在管理员名单内，才能查看反馈、运行日志和管理操作资料。'}</p>
          <div className="admin-access-actions">{canLogin && <a className="feedback-button primary" href="/admin/auth/login">{denied ? '重新进行 OA 登录' : '使用 OA／问学登录'}</a>}
            <button type="button" className="feedback-button" onClick={() => void check()}>重新验证</button></div>
        </>}
      </section>
    </main>;
  }

  return <><AdminWorkspace key={session.user.username} session={session} logoutPending={logoutPending} logoutError={logoutError}
    onLogout={() => { setLogoutError(''); if (hasAdminUnsavedChanges()) setConfirmLogout(true); else void signOut(); }} />
    {confirmLogout && <FeedbackConfirmDialog title="退出管理员页面" confirm="放弃修改并退出" cancel="继续编辑" pending={logoutPending} error={logoutError}
      onCancel={() => setConfirmLogout(false)} onConfirm={() => void signOut()}><p>存在尚未保存的修改。退出后将清除当前草稿，是否继续？</p></FeedbackConfirmDialog>}
  </>;
}

function AdminWorkspace({ session, logoutPending, logoutError, onLogout }: { session: AdminSession; logoutPending: boolean; logoutError: string; onLogout: () => void }) {
  const [view, setView] = useState<AdminView>(currentView);
  const [menuOpen, setMenuOpen] = useState(false);
  const [logsVisited, setLogsVisited] = useState(view === 'logs');
  const [adminsVisited, setAdminsVisited] = useState(view === 'admins');
  const [resourcesVisited, setResourcesVisited] = useState(view === 'resources');
  const [, updateLinks] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const previousTitle = document.title;
    if (window.location.pathname.replace(/\/+$/, '') === '/feedback') {
      window.history.replaceState(null, '', viewURL(currentView()));
    }
    const onNavigate = () => {
      const next = currentView();
      setView(next); setMenuOpen(false); updateLinks(value => value + 1);
      if (next === 'logs') setLogsVisited(true);
      if (next === 'admins') setAdminsVisited(true);
      if (next === 'resources') setResourcesVisited(true);
    };
    window.addEventListener('popstate', onNavigate);
    window.addEventListener('taskbook:admin-location', onNavigate);
    return () => {
      document.title = previousTitle;
      window.removeEventListener('popstate', onNavigate);
      window.removeEventListener('taskbook:admin-location', onNavigate);
    };
  }, []);

  useEffect(() => {
    document.title = `${labels[view]} · 管理员页面 · 研制任务书平台`;
  }, [view]);

  function navigate(event: MouseEvent<HTMLAnchorElement>, next: AdminView) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (next !== view) {
      window.history.pushState(null, '', viewURL(next));
      window.dispatchEvent(new Event('taskbook:admin-location'));
      requestAnimationFrame(() => heading.current?.focus());
    }
    setMenuOpen(false);
  }

  return <div className="admin-shell">
    <aside className="admin-sidebar" aria-label="管理员侧边栏">
      <div className="admin-brand"><strong>JONHON</strong><span>研制任务书平台</span></div>
      <button type="button" className="admin-menu-toggle" aria-controls="admin-navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen(value => !value)}>
        管理菜单 <span aria-hidden="true">{menuOpen ? '−' : '+'}</span>
      </button>
      <nav id="admin-navigation" className={`admin-navigation ${menuOpen ? 'is-open' : ''}`} aria-label="管理员导航">
        <span className="admin-nav-label">管理工作台</span>
        {(['feedback', 'logs', 'resources', 'admins'] as const).map(item => <a key={item} href={viewURL(item)} aria-current={item === view ? 'page' : undefined} onClick={event => navigate(event, item)}>
          <MenuIcon view={item}/><span>{labels[item]}</span>
        </a>)}
      </nav>
      <p className="admin-sidebar-note">反馈处理、运行排查与资料维护</p>
    </aside>
    <div className="admin-workspace">
      <header className="admin-header">
        <div><h1>管理员页面</h1><p>研制任务书平台 · 反馈、运行与资料管理</p></div>
        <div className="admin-header-actions"><span className="admin-current-user" aria-label="当前管理员">{session.user.display_name || session.user.username}<small>{session.user.username}</small></span>
          {session.can_manage_admins && <PlatformAuthSettings admin disabled={logoutPending} />}
          <a className="feedback-button" href="/admin/home" aria-disabled={logoutPending || undefined}
            onClick={event => { if (logoutPending) event.preventDefault(); }}>返回主页</a>
          <button type="button" className="feedback-button" disabled={logoutPending} onClick={onLogout}>{logoutPending ? '正在退出…' : '退出登录'}</button></div>
      </header>
      <main className="admin-main">
        {logoutError && <p role="alert" className="feedback-error">{logoutError}</p>}
        <div className="admin-section-title"><h2 ref={heading} tabIndex={-1}>{view === 'feedback' ? '问题反馈管理' : labels[view]}</h2>
          <p>{view === 'logs' ? '按用户一次生成请求查看完整过程、执行结果与失败原因。' : view === 'resources' ? '维护主页的操作视频和操作手册，支持原文件与链接。' : view === 'admins' ? '管理可以进入此页面的 OA 登录账号。' : '查看生成效果、核对关联任务，记录问题处理结果。'}</p></div>
        <section hidden={view !== 'feedback'} aria-label="用户反馈"><FeedbackAdminPage embedded visible={view === 'feedback'} /></section>
        {logsVisited && <section hidden={view !== 'logs'} className="admin-logs-panel" aria-label="运行日志"><RequestLogsView active={view === 'logs'} /></section>}
        {adminsVisited && <section hidden={view !== 'admins'} aria-label="管理员名单"><AdminMembersView active={view === 'admins'} canManage={session.can_manage_admins} /></section>}
        {resourcesVisited && <section hidden={view !== 'resources'} aria-label="操作资料上传"><HelpResourcesView active={view === 'resources'} /></section>}
      </main>
    </div>
  </div>;
}
