import { useEffect, useRef, useState } from 'react';
import { getJobStatus } from '../../api/jobs';
import { getIndicatorReview } from '../../api/jobs';
import { displayedNativeRun, nextNativeRunView } from '../../model/nativeRuns';
import { runId, type NativeRun } from '../../api/workspace';
import type { TaskbookWorkspaceController } from '../../hooks/useTaskbookWorkspace';
import { TaskbookReviewPage } from '../review/TaskbookReviewPage';
import { RdError, RdField, RdOperation, RdStatus } from '../../../rd/components/RdControls';

export function TaskbookDocumentPanel({ controller: c, onEditorDirty, onSelectedAnchor }: { controller: TaskbookWorkspaceController; onEditorDirty: (dirty: boolean) => void; onSelectedAnchor: (anchor: { id: string; text: string }) => void }) {
  const w = c.workspace!, selected = w.runs.find(item => runId(item) === w.work_unit.selected_run_id), run = selected || w.runs[0];
  const [viewRun, setViewRun] = useState(''), [revision, setRevision] = useState(w.work_unit.selected_revision_id || ''), [status, setStatus] = useState<Awaited<ReturnType<typeof getJobStatus>> | null>(null), [error, setError] = useState<unknown>(null), [reload, setReload] = useState(0), [editorDirty, setEditorDirty] = useState(false);
  const latestRunId = w.runs.length ? runId(w.runs[0]) : '';
  const previousNewestId = useRef(latestRunId);
  useEffect(() => { const next = nextNativeRunView(w.runs, viewRun, previousNewestId.current, editorDirty); if (next !== viewRun) { setViewRun(next); setRevision(''); } if (!editorDirty) previousNewestId.current = latestRunId; }, [latestRunId, editorDirty]);
  const shown = displayedNativeRun(w.runs, viewRun, w.work_unit.selected_run_id);
  const [clarifications, setClarifications] = useState<Record<string, string>>({}), [questions, setQuestions] = useState<{ indicator_name: string; reason?: string }[]>([]);
  const editable = w.task.assignee_id === w.current_user_id && ['owner', 'engineer'].includes(w.project.role);
  const refreshRef = useRef(c.refresh); refreshRef.current = c.refresh;
  useEffect(() => { if (!shown?.jid || shown.status === 'demo_sample') return; let active = true; setStatus(null); setError(null); const update = async () => { try { const result = await getJobStatus(shown.jid); if (!active) return; setStatus(result); setError(null); if (['done', 'blocked', 'error', 'cancelled'].includes(result.status) && !['done', 'blocked', 'error', 'cancelled', 'interrupted'].includes(shown.status)) await refreshRef.current(); } catch (reason) { if (active) setError(reason); } }; void update(); const timer = setInterval(() => void update(), 3000); return () => { active = false; clearInterval(timer); }; }, [shown?.jid, reload]);
  useEffect(() => { if (!shown?.jid || status?.status !== 'blocked') return; let active = true; void getIndicatorReview(shown.jid).then(result => active && setQuestions(result.manual_review_required || [])).catch(() => {}); return () => { active = false; }; }, [shown?.jid, status?.status]);
  if (!shown) return <section className="rd-panel"><h2>工作稿与核验</h2><p className="rd-empty">确认输入包后开始编制，生成结果将直接显示在当前任务。</p></section>;
  const activeStatus = status?.status || shown.status, running = ['pending', 'running', 'intent', 'dispatching', 'queued', 'cancelling'].includes(activeStatus);
  const currentView = runId(shown) === w.work_unit.selected_run_id;
  const ready = ['done', 'blocked', 'demo_sample'].includes(activeStatus);
  return <section className="rd-panel native-document"><div className="rd-record-heading"><h2>工作稿与核验</h2><RdStatus value={activeStatus} /></div>
    {shown.status === 'demo_sample' && <p className="feedback-notice">演示预置文档 · 未调用模型。可核对文档与业务流程，不代表真实模型运行成功。</p>}<RdField label="编制历史" value={runId(shown)} disabled={editorDirty} options={w.runs.map((item, index) => ({ value: runId(item), label: `编制记录 ${w.runs.length - index} · ${item.status}${runId(item) === w.work_unit.selected_run_id ? ' · 当前工作稿' : ''}` }))} onChange={value => { setViewRun(value); setRevision(''); }} />
    <p className="rd-muted">{currentView ? '正在查看当前采用的工作稿。' : '正在查看候选或历史编制记录；采用这版工作稿后才改变当前稿。'}{!currentView && w.work_unit.selected_run_id && <button type="button" className="feedback-link" disabled={editorDirty} onClick={() => setViewRun(w.work_unit.selected_run_id!)}>查看当前采用稿</button>}</p>
    {error !== null && <RdError error={error} retry={() => setReload(value => value + 1)} />}{(status?.error || shown.error) && <p role="alert" className="feedback-error">{status?.error || shown.error}</p>}
    {running && <><p role="status">正在按固定输入包编制；可离开后返回查看进度。</p>{editable && <RdOperation label="停止本次编制" fingerprint={`cancel:${runId(shown)}:${w.project.version}`} confirmation={<p>停止请求将在当前外部模型调用返回后生效，已产生的记录继续保留。</p>} execute={key => c.mutate(`runs/${encodeURIComponent(runId(shown))}/cancel`, {}, key)} />}</>}
    <details><summary>编制参数与过程日志</summary><p className="rd-mono">输入包 {shown.package_id}</p><pre className="rd-json">{(status?.log || []).join('\n') || '当前没有过程日志。'}</pre></details>
    {questions.length > 0 && editable && <RdOperation label="提交指标澄清并重新编制" disabled={c.dirty || !!c.saveError} fingerprint={JSON.stringify([runId(shown), clarifications, w.project.version])} execute={key => c.mutate(`runs/${encodeURIComponent(runId(shown))}/clarifications`, { answers: clarifications }, key)}>{questions.map(question => <RdField key={question.indicator_name} label={question.indicator_name} hint={question.reason} required value={clarifications[question.indicator_name] || ''} onChange={value => setClarifications(previous => ({ ...previous, [question.indicator_name]: value }))} />)}</RdOperation>}
    {ready && <><div className="native-review-embed"><TaskbookReviewPage key={shown.jid} jid={shown.jid} taskContext={{ projectId: w.project.id, taskId: w.task.id }} initialRevisionId={currentView ? w.work_unit.selected_revision_id : undefined} readOnly={!editable || !['in_progress', 'changes_requested'].includes(w.task.status)} initialOperations={c.operations} onSelectedAnchor={onSelectedAnchor} onRevisionChanged={setRevision} onDirtyChanged={value => { setEditorDirty(value); onEditorDirty(value); }} onPendingOperations={c.setOperations} /></div>
    {editable && <div className="rd-actions"><RdOperation label="采用这版工作稿" disabled={!revision || editorDirty || c.dirty || !!c.saveError} fingerprint={`select:${runId(shown)}:${revision}:${w.project.version}`} execute={key => c.mutate('revisions/select', { run_id: runId(shown), revision_id: revision }, key)} /><RdOperation label="检查当前工作稿与内容覆盖" disabled={!currentView || revision !== w.work_unit.selected_revision_id || editorDirty || c.dirty || !!c.saveError} fingerprint={`check:${runId(shown)}:${revision}:${w.project.version}`} execute={key => c.mutate('checks', { run_id: runId(shown), revision_id: revision, decisions: [...w.coverages].reverse().find(item => item.revision_id === revision)?.findings.filter(item => ['evidenced', 'not_applicable'].includes(item.status)).map(item => ({ section_key: item.section_key, status: item.status, output_anchor: item.output_anchor || '', evidence_ref: item.evidence_ref || '', requirement_ref: item.requirement_ref || '', reason: item.finding || item.reason || '' })) || [] }, key)} /></div>}</>}
    {!ready && !running && <p className="rd-muted">本次编制未形成可审阅文档。核对失败原因后，在输入区明确发起新一次编制。</p>}
  </section>;
}
