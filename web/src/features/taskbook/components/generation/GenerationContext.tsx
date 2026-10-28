import { useEffect, useMemo, useState } from 'react';
import { useTaskbook } from '../../hooks/useTaskbook';
import { readRdContext, setRdGenerationContext } from '../../model/rdGeneration';
import './generationContext.css';

interface ContextDetail {
  project: { name: string; current_baseline_id: string };
  current_user_id: string;
  tasks: { id: string; title: string; status: string; assignee_id: string; baseline_id: string }[];
  baselines: { id: string; number: number; requirements: { id: string; title: string; content: string }[] }[];
}

export function GenerationContext() {
  const tb = useTaskbook();
  const requested = useMemo(() => { try { return { context: readRdContext(window.location.search), error: '' }; }
    catch (error) { return { context: null, error: (error as Error).message }; } }, []);
  const [detail, setDetail] = useState<ContextDetail | null>(null);
  const [error, setError] = useState(requested.error);
  const [retry, setRetry] = useState(0);
  const [confirmation, setConfirmation] = useState('');
  const inputStamp = JSON.stringify([tb.form, ...Object.values(tb.files).map(file => file && [file.name, file.size, file.lastModified])]);
  const confirmed = confirmation === inputStamp;
  const task = detail?.tasks.find(item => item.id === requested.context?.task_id);
  const baseline = detail?.baselines.find(item => item.id === task?.baseline_id);
  const ready = !!task && task.status === 'in_progress' && task.assignee_id === detail?.current_user_id
    && task.baseline_id === detail?.project.current_baseline_id;

  useEffect(() => {
    if (!requested.context) return;
    const controller = new AbortController(); setDetail(null); setError(''); setConfirmation('');
    setRdGenerationContext(null);
    void fetch(`/api/rd/projects/${encodeURIComponent(requested.context.project_id)}`, { signal: controller.signal, cache: 'no-store' })
      .then(async response => { const data = await response.json(); if (!response.ok) throw new Error(data.detail || '项目读取失败'); return data as ContextDetail; })
      .then(data => { if (!controller.signal.aborted) setDetail(data); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '项目读取失败'); });
    return () => { controller.abort(); setRdGenerationContext(null); };
  }, [requested, retry]);

  useEffect(() => {
    setRdGenerationContext(ready && requested.context && task ? { ...requested.context, baseline_id: task.baseline_id, confirmed } : null);
    return () => setRdGenerationContext(null);
  }, [ready, confirmed, requested, task]);

  if (!requested.context && !error) return null;
  const returnHref = requested.context ? `/rd/${encodeURIComponent(requested.context.project_id)}?tab=tasks` : '/rd';
  return <section className="rd-generation-context" aria-label="当前研发任务">
    <div className="rd-generation-heading"><strong>{detail ? `${detail.project.name} · ${task?.title || '任务不可用'}` : '研发任务上下文'}</strong>
      <a href={returnHref}>返回研发项目</a></div>
    {error ? <div role="alert">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>重新读取</button></div>
      : !detail ? <p role="status">正在核对项目权限与需求基线…</p>
        : !ready ? <p role="alert">请先在项目中接单并开始任务，确认自己是执行人且已采用当前需求基线。</p>
          : <><p>当前采用需求基线 B{baseline?.number}。生成结果将关联本任务，完成后需登记成果并独立送审。</p>
            <details><summary>查看基线要求（{baseline?.requirements.length || 0} 项）</summary>
              <ul>{baseline?.requirements.map(row => <li key={row.id}><b>{row.title}</b>：{row.content}</li>)}</ul></details>
            <label className="rd-generation-confirm"><input type="checkbox" checked={confirmed}
              onChange={event => setConfirmation(event.target.checked ? inputStamp : '')} />
              我已核对本次上传资料和业务选择，确认其对应以上需求基线。</label>
            {tb.currentJid && <p>本次生成作业：{tb.currentJid}。完成文档核验后，返回项目登记成果。</p>}</>}
  </section>;
}
