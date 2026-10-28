import { useState } from 'react';
import { taskbookProjectHref } from '../../model/taskbookNavigation';
import type { TaskbookWorkspaceController } from '../../hooks/useTaskbookWorkspace';
import { RdField, RdOperation, RdStatus } from '../../../rd/components/RdControls';

export function TaskbookHandoffPanel({ controller: c, disabled }: { controller: TaskbookWorkspaceController; disabled: boolean }) {
  const w = c.workspace!, release = w.releases.find(item => item.id === w.work_unit.release_id), [reason, setReason] = useState('');
  const published = !!release && w.plan_releases.some(plan => plan.release_id === release.id);
  return <section className="rd-panel"><h2>发布与交接</h2><p className="rd-muted">批准包由负责人发布为正式计划。接受责任人接收交接包后，下游执行人才可开始工作；实际开始时间按真实开工记录。</p>
    {w.project.owner_id === w.current_user_id && !published && <RdOperation label="发布正式计划" disabled={disabled || !release || w.task.status !== 'done' || w.change_impacts.some(impact => impact.status === 'pending')} fingerprint={`publish:${release?.id}:${w.project.version}`} confirmation={<p>按批准包生成正式计划及下游任务，保留工作条目与任务编号的对应关系。重复请求不会重复派工。</p>} execute={key => c.command('publish_plan', { task_id: w.task.id, release_id: release!.id }, key)} />}
    {published && <p role="status">当前批准包已发布正式计划，可继续核对下游接收情况。</p>}
    {w.plan_releases.map(plan => <p key={plan.id}>已发布计划：<span className="rd-mono">{plan.id}</span></p>)}
    {w.handoffs.map(handoff => <article className="rd-record" key={handoff.id}><div className="rd-record-heading"><strong>{handoff.title || '下游交接包'}</strong><RdStatus value={handoff.status} label={handoff.status === 'pending' ? '待接收' : undefined} /></div><p className="rd-mono">{handoff.id}</p>{handoff.task_id && <a href={taskbookProjectHref(w.project.id, handoff.task_id)}>查看下游任务</a>}<p>采用发布包：{handoff.release_id || release?.id || '见交接记录'}</p>{handoff.status === 'pending' && handoff.assignee_id === w.current_user_id && <RdOperation label="接收交接包" disabled={disabled} fingerprint={`accept:${handoff.id}:${w.project.version}`} confirmation={<p>确认已核对技术输入、交付物、验收判据与接受责任，按此固定版本执行。</p>} execute={key => c.command('accept_handoff', { handoff_id: handoff.id }, key)} />}</article>)}
    {!w.handoffs.length && <p className="rd-empty">尚未下发交接包。批准固定包后由负责人发布计划。</p>}
    {w.change_impacts.length > 0 && <><h3>输入变化影响</h3>{w.change_impacts.map(impact => <article className="rd-record" key={impact.id}><RdStatus value={impact.status} label={impact.status === 'pending' ? '待复核' : impact.status === 'resolved' ? '已处理' : undefined} /><p>{impact.reason || '资料或需求发生变化，需要核对受影响用途。'}</p>{w.project.owner_id === w.current_user_id && impact.status !== 'resolved' && <><RdField label="影响核对依据" required multiline value={reason} onChange={setReason} /><div className="rd-actions">{[{ value: 'unaffected', label: '确认不受影响' }, { value: 'revalidate', label: '要求重新核验' }].map(decision => <RdOperation key={decision.value} label={decision.label} disabled={disabled || !reason.trim()} fingerprint={JSON.stringify([impact.id, decision.value, reason, w.project.version])} execute={key => c.command('resolve_change_impact', { impact_id: impact.id, decision: decision.value, reason }, key)} />)}</div></>}</article>)}</>}
  </section>;
}
