import type { RdProjectPlan as Plan } from '../api/rd';
import { nativeTaskHref } from '../../taskbook/api/workspace';
import { RdStatus } from './RdControls';

export function RdProjectPlan({ projectId, plan }: { projectId: string; plan?: Plan }) {
  const items = plan?.items || [];
  const dates = items.flatMap(item => [item.planned_start, item.planned_end, item.actual_start, item.actual_end]).filter(Boolean).map(value => Date.parse(value!)).filter(Number.isFinite);
  const min = dates.length ? Math.min(...dates) : 0, max = dates.length ? Math.max(...dates) : 0;
  const day = 86400000, span = Math.max(day, max - min + day);
  const position = (start: string, end: string) => ({ marginLeft: (Date.parse(start) - min) / span * 100 + '%', width: Math.max(2, (Date.parse(end) - Date.parse(start) + day) / span * 100) + '%' });
  return <section className="rd-panel">
    <h2>项目流程与正式计划</h2>
    <p className="rd-muted">上方流程与下方甘特读取同一份正式计划。蓝色表示计划，绿色表示实际记录；未开工不会自动填入实际日期。</p>
    <h3>办理流程</h3>
    {plan?.work_units.map(unit => <article className="rd-record" key={unit.id}>
      <a href={nativeTaskHref(projectId, unit.task_id)}>打开研制任务书</a>
      <ol className="native-project-stages">{unit.stages.map(stage => <li key={stage.instance_id}><strong>{stage.node_code} · {stage.label}</strong><RdStatus value={stage.status === 'completed' ? 'done' : stage.status === 'pending' ? 'todo' : stage.status} /></li>)}</ol>
    </article>)}
    <div className="rd-table-region" role="region" aria-label="正式计划依赖流程" tabIndex={0}><table>
      <thead><tr><th>正式工作</th><th>前置工作</th><th>固定输入修订</th><th>接收与执行</th></tr></thead>
      <tbody>{items.map(item => <tr key={item.id}>
        <td><a href={'/rd/' + encodeURIComponent(projectId) + '?tab=tasks#task-' + encodeURIComponent(item.id)}>{item.title}</a></td>
        <td>{item.predecessor_task_ids?.map(id => items.find(row => row.id === id)?.title || id).join(' → ') || '无前置工作'}</td>
        <td>{item.source_revision_id === 'baseline' ? '初始工作稿' : item.source_revision_id}</td>
        <td>{item.accepted_handoff_id ? '交接已接收' : '待接收交接'} · <RdStatus value={item.status} /></td>
      </tr>)}</tbody>
    </table></div>
    <h3>计划与实际甘特</h3>
    <div className="rd-table-region" role="region" aria-label="正式计划甘特" tabIndex={0}><table>
      <thead><tr><th>工作条目</th><th>计划日期</th><th>计划与实际位置</th><th>实际开始 / 结束</th></tr></thead>
      <tbody>{items.map(item => <tr key={item.id}>
        <td>{item.title}</td><td>{item.planned_start || '待排期'} — {item.planned_end || '待排期'}</td>
        <td><div className="native-gantt-track">{item.planned_start && item.planned_end && <span aria-label="计划" title={item.planned_start + ' 至 ' + item.planned_end} style={position(item.planned_start, item.planned_end)} />}</div>
          {item.actual_start && <div className="native-gantt-track"><span aria-label={item.actual_end ? '实际起止' : '实际开工'} title={item.actual_end ? item.actual_start + ' 至 ' + item.actual_end : '已于 ' + item.actual_start + ' 开工，尚未结束'} style={{ ...position(item.actual_start, item.actual_end || item.actual_start), background: 'var(--color-success)' }} /></div>}</td>
        <td>{item.actual_start || '尚未开工'} / {item.actual_end || '尚未结束'}</td>
      </tr>)}</tbody>
    </table></div>
    {!items.length && <p className="rd-empty">暂无正式计划条目。完成任务书批准并发布后，流程与甘特将显示同一份计划。</p>}
  </section>;
}
