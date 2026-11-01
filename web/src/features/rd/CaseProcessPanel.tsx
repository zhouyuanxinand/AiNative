import { useCallback, useEffect, useState, type CSSProperties, type FormEvent } from 'react';
import { STAGES, formatTime, readable, stageTitle, statusTitle } from './presentation';
import type { Catalog, ResearchCase, Workpackage } from './types';
import type { CommandRunner } from './WorkpackagePanel';
import { scheduleTime as dateTime, workpackageActualRange as actualRange } from './schedule';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { WorkflowCanvas } from './WorkflowCanvas';

function ExecutionPreview({ packages, catalog, onOpenWorkpackage }: { packages: Workpackage[]; catalog: Catalog | null; onOpenWorkpackage: (id: string) => void }) {
  const [selectedId, setSelectedId] = useState('');
  const [nodeId, setNodeId] = useState('');
  const selected = packages.find(item => item.id === selectedId) ?? packages[packages.length - 1];
  if (!selected) return null;
  const node = selected.nodes.find(item => item.id === nodeId) ?? selected.nodes[0];
  return <section className="rd-section"><div className="rd-section-head"><div><h3>工作包执行图</h3><p>选择工作包查看真实依赖与状态，草稿可进入编排调整节点。</p></div><button type="button" className="rd-button" onClick={() => onOpenWorkpackage(selected.id)}>{selected.status === 'draft' ? '编辑工作包计划 →' : '查看执行记录 →'}</button></div><div className="rd-field"><label id="rd-process-package-label">查看工作包</label><StyledSelect aria-labelledby="rd-process-package-label" value={selected.id} options={packages.map(item => ({ value: item.id, label: `${item.title} · ${statusTitle(item.status)} · ${item.id.slice(-8)}` }))} onChange={id => { setSelectedId(id); setNodeId(''); }} /></div><WorkflowCanvas key={selected.id} nodes={selected.nodes} actions={catalog?.actions ?? []} selectedId={node?.id} onSelectNode={setNodeId} title="工作包执行图" />{node && <p className="rd-muted">已选：{catalog?.actions.find(action => action.id === node.action_id)?.title ?? node.action_id} · {statusTitle(node.status)} · 开始 {formatTime(node.started_at ?? undefined)} · 结束 {formatTime(node.completed_at ?? node.ended_at ?? undefined)}</p>}</section>;
}

function ScheduleEditor({ workpackage, busy, command, onDirtyChange }: { workpackage: Workpackage; busy: boolean; command: CommandRunner; onDirtyChange: (id: string, dirty: boolean) => void }) {
  const [start, setStart] = useState(workpackage.planned_start ?? '');
  const [end, setEnd] = useState(workpackage.planned_end ?? '');
  const [note, setNote] = useState(workpackage.plan_note ?? '');
  const [base, setBase] = useState(JSON.stringify([start, end, note]));
  const [validation, setValidation] = useState('');
  const dirty = JSON.stringify([start, end, note]) !== base;
  useEffect(() => { onDirtyChange(workpackage.id, dirty); }, [workpackage.id, dirty, onDirtyChange]);
  useEffect(() => {
    if (dirty) return;
    setStart(workpackage.planned_start ?? ''); setEnd(workpackage.planned_end ?? ''); setNote(workpackage.plan_note ?? '');
    setBase(JSON.stringify([workpackage.planned_start ?? '', workpackage.planned_end ?? '', workpackage.plan_note ?? '']));
  }, [workpackage, dirty]);
  function save(event: FormEvent) {
    event.preventDefault();
    if (start && end && end < start) { setValidation('计划完成日期不能早于开始日期。'); document.getElementById(`rd-schedule-end-${workpackage.id}`)?.focus(); return; }
    setValidation('');
    void command('save_schedule', { workpackage_id: workpackage.id, planned_start: start || null, planned_end: end || null, plan_note: note }, () => setBase(JSON.stringify([start, end, note])));
  }
  return <form noValidate className="rd-schedule-form" onSubmit={save}><p className="rd-muted">仅草稿可改计划。实际时间取运行记录；提交时固定的计划快照继续保留。</p><div className="rd-schedule-fields"><div className="rd-field"><label htmlFor={`rd-schedule-start-${workpackage.id}`}>计划开始</label><input id={`rd-schedule-start-${workpackage.id}`} type="date" value={start} onChange={event => setStart(event.target.value)} disabled={busy || workpackage.status !== 'draft'} /></div><div className="rd-field"><label htmlFor={`rd-schedule-end-${workpackage.id}`}>计划完成</label><input id={`rd-schedule-end-${workpackage.id}`} type="date" value={end} min={start || undefined} onChange={event => setEnd(event.target.value)} disabled={busy || workpackage.status !== 'draft'} aria-invalid={!!validation} aria-describedby={validation ? `rd-schedule-error-${workpackage.id}` : undefined} /></div><div className="rd-field"><label htmlFor={`rd-schedule-note-${workpackage.id}`}>计划说明</label><textarea id={`rd-schedule-note-${workpackage.id}`} rows={2} className="resize-none" value={note} onChange={event => setNote(event.target.value)} disabled={busy || workpackage.status !== 'draft'} /></div></div>{validation && <p id={`rd-schedule-error-${workpackage.id}`} className="rd-error" role="alert">{validation}</p>}<div className="rd-actions"><span className="rd-muted">计划版 {workpackage.schedule_revision ?? 0}</span><button type="submit" className="rd-button" disabled={busy || !dirty || workpackage.status !== 'draft'}>保存日期计划</button></div></form>;
}

export function CaseProcessPanel({ researchCase, catalog, busy, command, onOpenWorkpackage, onDirtyChange }: { researchCase: ResearchCase; catalog: Catalog | null; busy: boolean; command: CommandRunner; onOpenWorkpackage: (id: string) => void; onDirtyChange: (dirty: boolean) => void }) {
  const actionTitle = (id: string) => { const action = catalog?.actions.find(item => item.id === id); return action?.title ?? action?.name ?? id; };
  const [dirtyRows, setDirtyRows] = useState<Record<string, boolean>>({});
  const setRowDirty = useCallback((id: string, dirty: boolean) => setDirtyRows(current => current[id] === dirty ? current : { ...current, [id]: dirty }), []);
  useEffect(() => { onDirtyChange(Object.values(dirtyRows).some(Boolean)); }, [dirtyRows, onDirtyChange]);
  const packages = researchCase.workpackages;
  const times = packages.flatMap(workpackage => {
    const actual = actualRange(workpackage);
    return [dateTime(workpackage.planned_start, true), dateTime(workpackage.planned_end, true), actual?.start ?? null, actual?.end ?? null].filter((value): value is number => value !== null);
  });
  const low = times.length ? Math.min(...times) : null;
  const high = times.length ? Math.max(...times) + 86400000 : null;
  const bar = (start: number, end: number): CSSProperties => ({ left: `${(start - low!) / (high! - low!) * 100}%`, width: `${Math.max(0.7, (Math.max(start, end) - start + 3600000) / (high! - low!) * 100)}%` });
  const tick = (time: number) => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' }).format(time);
  return <section className="rd-process-panel"><div className="rd-surface-title"><div><h3>项目流程</h3><p>业务阶段与工作包进展分别显示。需求确认、选型决定、研发启动和任务书范围批准各自保留依据。</p></div></div>
    <ol className="rd-process-stages" aria-label="案例八阶段业务流程">{STAGES.map((stage, index) => {
      const lifecycle = researchCase.business_lifecycle;
      const approved = lifecycle?.policy_version === 'v2' && lifecycle.rd_activation_state !== 'historical_unverified' && ['input', 'requirements', 'selection', 'planning'].includes(stage.id)
        ? stage.id === 'input' || stage.id === 'requirements' ? !!lifecycle.current_requirement_baseline_id : stage.id === 'selection' ? lifecycle.rd_activation_state === 'active' || researchCase.product_route?.value === 'direct' && !!lifecycle.current_selection_decision_id : researchCase.decisions.some(item => item.id === lifecycle.current_taskbook_scope_decision_id && item.verdict === 'approved' && !item.invalidated_at)
        : researchCase.decisions.some(decision => decision.kind !== 'route' && decision.stage === stage.id && decision.verdict === 'approved' && !decision.invalidated_at);
      const count = packages.filter(workpackage => workpackage.stage === stage.id).length;
      return <li key={stage.id} className={stage.id === researchCase.stage ? 'current' : approved ? 'done' : ''} aria-current={stage.id === researchCase.stage ? 'step' : undefined}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{researchCase.business_lifecycle?.policy_version === 'v2' ? ({ input: '资料与需求', requirements: '需求确认', selection: '选型与启动', planning: '策划任务书', design: '工程设计', verification: '成果核验', delivery: '交付反馈', knowledge: '知识整理' }[stage.id]) : stage.short}</strong><small>{stage.id === researchCase.stage ? researchCase.status === 'completed' ? '已完成阶段决定' : '当前阶段' : approved ? '已记录通过' : '尚无有效通过'}{count ? ` · ${count} 个工作包` : ''}</small></div></li>;
    })}</ol>
    <ExecutionPreview packages={packages} catalog={catalog} onOpenWorkpackage={onOpenWorkpackage} />
    <section className="rd-section"><div className="rd-section-head"><div><h3>计划与实际</h3><p>蓝色为日期计划；实际仅按已登记的开始、完成或结束时间显示。未登记的时间保持空白。</p></div><div className="rd-plan-legend"><span>计划</span><span>实际完成</span><span>受阻 / 取消</span></div></div>
      {!packages.length ? <p className="rd-empty-inline">尚无工作包计划。可在当前办理中拉取本阶段工作包。</p> : <div className="rd-schedule-scroll" tabIndex={0} role="region" aria-label="工作包计划与实际时间表"><div className="rd-schedule-table"><div className="rd-schedule-axis"><strong>阶段 / 工作包</strong><div>{low !== null && high !== null ? [0, 0.5, 1].map(ratio => <span key={ratio}>{tick(low + (high - low) * ratio)}</span>) : <span>尚无已登记日期</span>}</div><strong>状态与记录</strong></div>{packages.map(workpackage => {
        const plannedStart = dateTime(workpackage.planned_start, true), plannedEnd = dateTime(workpackage.planned_end, true), actual = actualRange(workpackage);
        return <div key={workpackage.id} className="rd-schedule-row"><div><small>{stageTitle(workpackage.stage)}</small><button className="rd-link-button" onClick={() => onOpenWorkpackage(workpackage.id)}>{workpackage.title}</button><code>{workpackage.id.slice(-8)}</code></div><div className="rd-schedule-bars"><div className="rd-schedule-lane"><small>计划</small><div>{plannedStart !== null && plannedEnd !== null ? <span className="rd-date-bar planned" style={bar(plannedStart, plannedEnd + 82800000)} title={`${workpackage.planned_start} 至 ${workpackage.planned_end}`} /> : <span className="rd-date-unknown">{workpackage.planned_start || workpackage.planned_end ? '仅登记部分计划日期' : '未设置计划'}</span>}</div></div><div className="rd-schedule-lane"><small>实际</small><div>{actual ? <span className={`rd-date-bar actual ${workpackage.status}`} style={bar(actual.start, actual.end)} title={`开始 ${formatTime(workpackage.started_at ?? undefined)}；${actual.recordedEnd === null ? '结束未登记' : `结束 ${formatTime(workpackage.completed_at ?? workpackage.ended_at ?? undefined)}`}`} /> : <span className="rd-date-unknown">未开始 / 缺记录</span>}</div></div></div><div><span className={`rd-badge ${workpackage.status}`}>{statusTitle(workpackage.status)}</span><small>开始 {formatTime(workpackage.started_at ?? undefined)}</small><small>结束 {formatTime(workpackage.completed_at ?? workpackage.ended_at ?? undefined)}</small></div></div>;
      })}</div></div>}
    </section>
    {packages.map(workpackage => <details className="rd-process-workpackage rd-section" key={workpackage.id}><summary><span><strong>{workpackage.title}</strong><small>{stageTitle(workpackage.stage)} · {statusTitle(workpackage.status)} · {workpackage.nodes.length} 个动作</small></span><span>依赖与日期计划</span></summary><div className="rd-process-details"><ol className="rd-dependency-list">{workpackage.nodes.map(node => <li key={node.id}><div><strong>{actionTitle(node.action_id)}</strong><span className={`rd-badge ${node.status ?? 'draft'}`}>{statusTitle(node.status)}</span></div><p>前置依赖：{node.depends_on.map(id => actionTitle(workpackage.nodes.find(item => item.id === id)?.action_id ?? id)).join('、') || '无'} · {node.required ? '必需' : '可选'} · 版本 {node.action_version}</p><small>开始 {formatTime(node.started_at ?? undefined)} · 结束 {formatTime(node.completed_at ?? node.ended_at ?? undefined)}</small></li>)}</ol><button className="rd-button" onClick={() => onOpenWorkpackage(workpackage.id)}>定位工作包办理</button><ScheduleEditor workpackage={workpackage} busy={busy} command={command} onDirtyChange={setRowDirty} />{!!workpackage.schedule_history?.length && <details className="rd-disclosure"><summary>日期计划历史 · {workpackage.schedule_history.length} 条</summary><pre>{readable(workpackage.schedule_history)}</pre></details>}</div></details>)}
  </section>;
}
