import { TaskbookProvider } from '../features/taskbook/hooks/useTaskbook';
import { PlatformShell } from './layout/PlatformShell';
import { PlatformPage } from '../features/rd/pages/PlatformPage';
import { platformViews, type PlatformView } from '../features/rd/model/platformViews';
// Keep the established stylesheet cascade when composing independently owned pages.
import '../features/rd/components/rdJourney.css';
import { TaskbookReviewPage } from '../features/taskbook/components/review/TaskbookReviewPage';
import { AdminPage } from '../features/admin/components/AdminPage';
import { HelpResourcePage } from '../features/help/components/HelpResourcePage';
import { StandaloneRuntimeLogsPage } from '../features/admin/components/StandaloneRuntimeLogsPage';
import { RdPage } from '../features/rd/pages/RdPage';
import { TaskbookGenerationPanel } from '../features/taskbook/components/generation/TaskbookGenerationPanel';
import { RdTaskbookWorkspace } from '../features/taskbook/components/workspace/RdTaskbookWorkspace';
function WorkspaceRoute({ view }: { view: PlatformView }) {
  return <PlatformShell active={platformViews[view].path} title={platformViews[view].title}><PlatformPage view={view} /></PlatformShell>;
}

export default function App() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/';
  const nativePath = path.match(/^\/rd\/([^/]+)\/tasks\/([^/]+)$/);
  if (nativePath) return <PlatformShell active="/tasks" title="任务书工作台"><RdTaskbookWorkspace projectId={decodeURIComponent(nativePath[1])} taskId={decodeURIComponent(nativePath[2])} /></PlatformShell>;
  const rdPath = path.match(/^\/rd(?:\/([^/]+))?$/);
  if (rdPath) return <PlatformShell active="/rd" title="项目空间"><RdPage projectId={rdPath[1] ? decodeURIComponent(rdPath[1]) : undefined} /></PlatformShell>;
  const centers = { '/requirements': 'requirements', '/tasks': 'tasks', '/artifacts': 'artifacts', '/approvals': 'approvals' } as const;
  if (path in centers) return <WorkspaceRoute view={centers[path as keyof typeof centers]} />;
  const legacyProjectEntry = path === '/' && new URLSearchParams(window.location.search).has('rd_project');
  if (path === '/' && !legacyProjectEntry) return <WorkspaceRoute view="overview" />;
  if (path === '/admin' || path === '/feedback') return <AdminPage />;
  if (path === '/help/video' || path === '/help/manual') {
    return <PlatformShell active={path} title="使用帮助"><HelpResourcePage kind={path === '/help/video' ? 'video' : 'manual'} /></PlatformShell>;
  }
  if (path === '/log' || path === '/logs') {
    return <StandaloneRuntimeLogsPage />;
  }
  const reviewPath = path.match(/^\/review\/([^/]+)$/);
  if (reviewPath) return <PlatformShell active="/artifacts" title="成果文档审阅"><TaskbookReviewPage jid={decodeURIComponent(reviewPath[1])} /></PlatformShell>;

  return (
    <PlatformShell active="/taskbook" title="任务书生成">
      <TaskbookProvider>
        <TaskbookGenerationPanel />
      </TaskbookProvider>
    </PlatformShell>
  );
}
