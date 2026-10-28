import { useCallback, useEffect, useState } from 'react';
import { useCurrentUser } from '../../../../shared/auth/useCurrentUser';
import { nativeContextKey } from '../../api/workspace';
import type { NativeDraft } from '../../api/workspace';
import { taskbookView, taskbookProjectHref, validTaskbookView, type TaskbookView } from '../../model/taskbookNavigation';
import { useTaskbookWorkspace } from '../../hooks/useTaskbookWorkspace';
import { navigateAfterConfirmedLeave, useApplicationLeaveGuard } from '../../../../shared/hooks/useApplicationLeaveGuard';
import { FeedbackConfirmDialog } from '../../../../shared/ui/FeedbackDialog';
import { TaskbookGenerationPanel } from '../generation/TaskbookGenerationPanel';
import { RdError, RdStatus } from '../../../rd/components/RdControls';
import { TaskbookDocumentPanel } from './TaskbookDocumentPanel';
import { TaskbookStagePanel } from './TaskbookStagePanel';
import { TaskbookWbsPanel } from './TaskbookWbsPanel';
import { TaskbookReviewPanel } from './TaskbookReviewPanel';
import { TaskbookHandoffPanel } from './TaskbookHandoffPanel';
import '../../../../shared/styles/feedback.css';
import '../../../rd/components/rd.css';
import './taskbookWorkspace.css';

export function RdTaskbookWorkspace({ projectId, taskId }: { projectId: string; taskId: string }) {
  const { state, retry } = useCurrentUser();
  if (state.status === 'loading') return <div className="rd-page" role="status">正在验证身份与任务权限…</div>;
  if (state.status === 'error') return <div className="rd-page"><RdError error={new Error(state.error)} retry={retry} /></div>;
  if (!state.identity.authenticated) return <div className="rd-page"><h1>任务书工作台</h1><p>请登录后继续本任务。</p><a href="/auth/login">前往统一登录</a></div>;
  return <NativeWorkspace key={nativeContextKey(projectId, taskId, state.identity.user.userid)} projectId={projectId} taskId={taskId} />;
}
function NativeWorkspace({ projectId, taskId }: { projectId: string; taskId: string }) {
  const c = useTaskbookWorkspace(projectId, taskId), w = c.workspace;
  const [composing, setComposing] = useState(false);
  const [tab, setTab] = useState<TaskbookView | null>(() => validTaskbookView(new URLSearchParams(location.search).get('view'))), [editorDirty, setEditorDirty] = useState(false), [wbsDirty, setWbsDirty] = useState(false), [destination, setDestination] = useState('');
  const currentView = tab ?? (w ? taskbookView(null, w) : 'inputs');
  const [selectedAnchor, setSelectedAnchor] = useState({ id: '', text: '' });
  const reportWbsDirty = useCallback((dirty: boolean) => setWbsDirty(dirty), []);
  const [comparison, setComparison] = useState<{ remote: NativeDraft | null } | null>(null), [comparingError, setComparingError] = useState<unknown>(null);
  const dirty = c.dirty || editorDirty || wbsDirty;
  useApplicationLeaveGuard({ dirty });
  useEffect(() => { const navigate = (event: MouseEvent) => { if (!dirty || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return; const link = (event.target as Element).closest<HTMLAnchorElement>('a[href]'); if (!link || link.target === '_blank' || link.hasAttribute('download') || link.href === location.href) return; event.preventDefault(); setDestination(link.href); }; document.addEventListener('click', navigate); return () => document.removeEventListener('click', navigate); }, [dirty]);
  useEffect(() => { if (composing || !c.dirty || c.saveError || c.saving || c.mutating) return; const timer = setTimeout(() => { void c.save().catch(() => {}); }, 900); return () => clearTimeout(timer); }, [composing, c.mutating, c.dirty, c.form, c.operations, c.saveError, c.saving, c.save]);
  useEffect(() => { if (w && tab === null) setTab(taskbookView(new URLSearchParams(location.search).get('view'), w)); }, [w, tab]);
  useEffect(() => { const restore = () => setTab(w ? taskbookView(new URLSearchParams(location.search).get('view'), w) : validTaskbookView(new URLSearchParams(location.search).get('view'))); window.addEventListener('popstate', restore); return () => window.removeEventListener('popstate', restore); }, [w]);
  useEffect(() => { if (!w || !location.hash) return; const frame = requestAnimationFrame(() => document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView({ block: 'start' })); return () => cancelAnimationFrame(frame); }, [!!w, currentView]);
  const tabs: { id: TaskbookView; label: string }[] = [{ id: 'inputs', label: '输入与编制' }, { id: 'document', label: '文档与核验' }, { id: 'planning', label: 'WBS与验证' }, { id: 'review', label: '工程审签' }, { id: 'handoff', label: '发布与交接' }];
  const disabled = c.mutating || c.loading || c.saving || c.dirty || !!c.saveError || editorDirty || wbsDirty;
  return <div className="rd-page native-taskbook" onCompositionStart={() => setComposing(true)} onCompositionEnd={() => setComposing(false)}><div className="rd-main"><a className="rd-back" href={taskbookProjectHref(projectId, taskId)}>← 返回项目流程</a>{c.error !== null && <RdError error={c.error} retry={() => void c.refresh().catch(() => {})} />}{c.loading && <p role="status">正在恢复任务输入、工作稿与私有草稿…</p>}{w && <><div className="rd-title-row"><div><p className="rd-eyebrow">{w.project.name} / 原生任务书工作包</p><h1>{w.task.title}</h1><p className="rd-muted">{w.task.description}</p></div><div className="rd-actions"><RdStatus value={w.task.status} /><button type="button" className="feedback-button" onClick={() => void c.refresh().catch(() => {})} disabled={c.loading}>读取最新记录</button></div></div>
    {!!w.blockers?.length && <aside className="feedback-notice" aria-label="任务阻断原因"><strong>待处理事项</strong><ul>{w.blockers.map((item, index) => <li key={index}>{typeof item === 'string' ? item : item.message || item.reason || item.code}</li>)}</ul></aside>}
    <nav className="rd-tabs" aria-label="任务工作面">{tabs.map(item => <button key={item.id} type="button" aria-current={currentView === item.id ? 'page' : undefined} className={currentView === item.id ? 'selected' : ''} onClick={() => { const url = new URL(location.href); url.searchParams.set('view', item.id); history.pushState(null, '', url); setTab(item.id); }}>{item.label}</button>)}</nav>
    {c.saveError !== null && <div className="native-save-error"><RdError error={c.saveError} /><p>当前编辑仍保留，相关操作已暂停。可比较服务器草稿后，确认以当前编辑保存合并。</p><div className="rd-actions"><button className="feedback-button" type="button" onClick={() => void c.save().catch(() => {})}>重试保存原草稿</button><button className="feedback-button" type="button" onClick={() => { setComparingError(null); void c.compareDraft().then(remote => setComparison({ remote })).catch(setComparingError); }}>比较服务器草稿</button></div>{comparingError !== null && <RdError error={comparingError} />}</div>}
    <div hidden={currentView !== 'inputs'}><TaskbookGenerationPanel binding={c} /></div><div hidden={currentView !== 'document'}><TaskbookDocumentPanel onSelectedAnchor={setSelectedAnchor} controller={c} onEditorDirty={setEditorDirty} /><TaskbookStagePanel selectedAnchor={selectedAnchor} controller={c} disabled={disabled} /></div><div hidden={currentView !== 'planning'}><TaskbookWbsPanel selectedAnchor={selectedAnchor} controller={c} disabled={c.mutating || c.loading || c.saving || c.dirty || !!c.saveError || editorDirty} onDirty={reportWbsDirty} /></div><div hidden={currentView !== 'review'}><TaskbookReviewPanel controller={c} disabled={disabled} /></div><div hidden={currentView !== 'handoff'}><TaskbookHandoffPanel controller={c} disabled={disabled} /></div>
    <details className="native-auxiliary"><summary>辅助工具与历史兼容入口</summary><a href="/taskbook" target="_blank" rel="noopener noreferrer">打开独立任务书工具</a><p className="rd-muted">独立工具的结果不会自动替换当前任务的固定输入或工作稿。</p></details></>}{destination && <FeedbackConfirmDialog title="离开当前任务？" confirm="放弃未保存修改并离开" cancel="继续编辑" onCancel={() => setDestination('')} onConfirm={() => navigateAfterConfirmedLeave(destination)}><p>当前有未保存的正文、安排或输入。已保存的私有草稿与文档修订会保留。</p></FeedbackConfirmDialog>}{comparison && <FeedbackConfirmDialog title="比较私有草稿冲突" confirm="以当前编辑保存合并" cancel="返回核对" pending={c.saving} onCancel={() => setComparison(null)} onConfirm={() => void c.saveMergedDraft(comparison.remote?.draft_revision || 0).then(() => setComparison(null)).catch(setComparingError)}><p>服务器修订 {comparison.remote?.draft_revision || 0} 与当前编辑分别列出。请核对后保留所需内容；确认将以当前编辑保存新草稿，不覆盖正文修订。</p><details><summary>服务器草稿</summary><pre className="rd-json">{JSON.stringify(comparison.remote, null, 2)}</pre></details><details open><summary>当前编辑</summary><pre className="rd-json">{JSON.stringify({ form: c.form, pending_operations: c.operations }, null, 2)}</pre></details>{comparingError !== null && <RdError error={comparingError} />}</FeedbackConfirmDialog>}</div></div>;
}
