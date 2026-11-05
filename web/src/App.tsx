/** Application entry: research platform and retained administration, help and review routes. */
import { useLayoutEffect } from 'react';
import { CurrentUserProvider } from './hooks/useCurrentUser';
import { StandaloneRuntimeLogsPage } from './components/management/StandaloneRuntimeLogsPage';
import { TaskbookReviewPage } from './components/review/TaskbookReviewPage';
import { AdminPage } from './components/management/AdminPage';
import { HelpResourcePage } from './components/help/HelpResourcePage';
import { RdPlatformPage } from './features/rd/RdPlatformPage';

type AppRoute =
  | { page: 'rd'; replaceUrl?: string }
  | { page: 'admin' | 'logs' }
  | { page: 'help'; kind: 'video' | 'manual' }
  | { page: 'review'; jid: string };

const researchQueryKeys = new Set(['rd_view', 'project', 'case', 'case_view', 'step', 'evidence', 'workpackage', 'management_q', 'management_kind', 'management_page', 'knowledge_q', 'knowledge_kind', 'knowledge_page', 'q', 'page', 'flow_tab', 'flow_kind', 'flow_item', 'flow_version', 'flow_detail', 'flow_q', 'flow_page', 'workspace_q', 'workspace_kind', 'workspace_page', 'workspace_item', 'workspace_version']);

export function resolveAppRoute(pathname: string, search = '', hash = ''): AppRoute {
  const path = pathname.replace(/\/+$/, '') || '/';
  if (path === '/admin' || path === '/feedback') return { page: 'admin' };
  if (path === '/help/video' || path === '/help/manual') return { page: 'help', kind: path === '/help/video' ? 'video' : 'manual' };
  if (path === '/log' || path === '/logs') return { page: 'logs' };
  const reviewPath = path.match(/^\/review\/([^/]+)$/);
  if (reviewPath) {
    try { return { page: 'review', jid: decodeURIComponent(reviewPath[1]) }; }
    catch { /* An invalid legacy URL opens the platform without inventing a job. */ }
  }

  const researchPath = path === '/' || path === '/rd' || path.startsWith('/rd/projects/');
  const targetPath = researchPath ? path : '/rd';
  const query = new URLSearchParams();
  for (const [key, value] of new URLSearchParams(search)) {
    if (researchQueryKeys.has(key)) query.append(key, value);
  }
  const encoded = query.toString();
  const target = targetPath + (encoded ? `?${encoded}` : '');
  // The server owns OA callback validation. Only business navigation survives
  // SPA compatibility routing; query credentials never establish an identity.
  return target !== pathname + search || hash ? { page: 'rd', replaceUrl: target } : { page: 'rd' };
}

export default function App() {
  const route = resolveAppRoute(window.location.pathname, window.location.search, window.location.hash);
  const replacement = route.page === 'rd' ? route.replaceUrl : undefined;
  // Clean compatibility URLs before child passive effects read the session or
  // fetch project data. Replace keeps Back from reopening the retired homepage.
  useLayoutEffect(() => {
    if (replacement) window.history.replaceState(window.history.state, '', replacement);
  }, [replacement]);
  if (route.page === 'admin') return <AdminPage />;
  if (route.page === 'help') return <HelpResourcePage kind={route.kind} />;
  if (route.page === 'logs') return <StandaloneRuntimeLogsPage />;
  if (route.page === 'review') return <TaskbookReviewPage jid={route.jid} />;
  return <CurrentUserProvider><RdPlatformPage /></CurrentUserProvider>;
}
