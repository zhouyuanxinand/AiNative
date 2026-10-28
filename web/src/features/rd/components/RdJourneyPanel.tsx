import { useEffect, useRef, useState } from 'react';
import { RdField, RdOperation, rdTime } from './RdControls';
import { type RdWorkbenchContext } from '../model/context';

/** Route decisions are project facts; shared knowledge and model runs only supply evidence. */
export function RdJourneyPanel({ context }: { context: RdWorkbenchContext }) {
  const { detail, disabled, run } = context;
  const journey = detail.journey;
  const selection = journey?.selection;
  const owner = detail.project.role === 'owner';
  const [editing, setEditing] = useState(false);
  const initial = { route: selection?.route || '', selected_product: selection?.selected_product || detail.project.product, rationale: selection?.rationale || '', evidence_ref: selection?.evidence_ref || '', suitability: selection?.suitability || 'pending', supply_status: selection?.supply_status || 'pending' };
  const [fields, setFields] = useState(initial);
  const snapshot = JSON.stringify(initial), previous = useRef(snapshot);
  useEffect(() => { if (JSON.stringify(fields) === previous.current) setFields(JSON.parse(snapshot)); previous.current = snapshot; }, [snapshot]);
  const change = (name: keyof typeof fields) => (value: string) => setFields(before => ({ ...before, [name]: value }));
  const dirty = JSON.stringify(fields) !== snapshot;
  const [delivery, setDelivery] = useState({ outcome: 'blocked', recipient: '', reference: '', note: '' });
  const changeDelivery = (name: keyof typeof delivery) => (value: string) => setDelivery(before => ({ ...before, [name]: value }));
  return <section className="rd-panel rd-journey-panel" id="route-decision">
    <div className="rd-record-heading"><div><p className="rd-eyebrow">需求确认后的业务决定</p><h2>选型与业务路线</h2></div><span className="rd-route-badge">{journey?.route_label || '路线待决定'}</span></div>
    <p className="rd-muted">核对需求与产品差异，明确直接选用、改型或新研。适用性与供应信息可保留待核实，并记录依据。</p>
    <ol className="rd-route-options"><li><strong>直接选用</strong><span>核对适用性、供货与交付，记录实际接收。</span></li><li><strong>改型</strong><span>交接母型与差异，取得授权后编制任务书。</span></li><li><strong>新研</strong><span>明确目标与技术约束，组织策划、设计和验证。</span></li></ol>
    {selection ? <dl className="rd-metadata"><dt>选用产品 / 母型</dt><dd>{selection.selected_product || '新研，未指定既有产品'}</dd><dt>决定依据</dt><dd>{selection.rationale}</dd><dt>资料引用</dt><dd>{selection.evidence_ref || '尚待补充'}</dd><dt>核实状态</dt><dd>适用性{selection.suitability === 'confirmed' ? '已确认' : '待核实'} · 供货{selection.supply_status === 'confirmed' ? '已确认' : '待核实'}</dd><dt>记录时间</dt><dd>{rdTime(selection.created_at)}</dd></dl> : <p className="rd-empty">{detail.development_adoptions?.length ? '已有启动授权登记，尚无独立选型决定记录；既有工作与历史继续保留。' : '尚未记录选型路线。先确认需求基线，再登记选型依据。'}</p>}
    {owner && <><button className="feedback-button" type="button" aria-expanded={editing} onClick={() => setEditing(value => !value)}>{editing ? '收起路线填写' : selection ? '复核并记录新决定' : '登记选型路线'}</button>
      <div hidden={!editing}><RdOperation label="保存选型决定" disabled={disabled || !detail.project.current_baseline_id} dirty={dirty} fingerprint={JSON.stringify([fields, detail.project.version])} execute={async key => { await run('record_selection', fields, key); setEditing(false); }}>
        {!detail.project.current_baseline_id && <p className="feedback-notice rd-route-notice">请在“资料与画像 → 需求与基线”完善要求并确认基线。</p>}
        <div className="rd-fields"><RdField label="业务路线" required value={fields.route} onChange={change('route')} options={[{value:'',label:'请选择业务路线'},{value:'direct',label:'直接选用'},{value:'modification',label:'改型'},{value:'new',label:'新研'}]} /><RdField label={fields.route === 'new' ? '参考产品（选填）' : '选用产品 / 母型'} required={fields.route !== 'new'} value={fields.selected_product} onChange={change('selected_product')} /><RdField label="选型依据与差异说明" required multiline value={fields.rationale} onChange={change('rationale')} /><RdField label="依据资料引用" value={fields.evidence_ref} onChange={change('evidence_ref')} hint="填写已核对的报告、条款或记录编号。适用性已确认时必填。" /><RdField label="工程适用性" value={fields.suitability} onChange={change('suitability')} options={[{value:'pending',label:'待核实'},{value:'confirmed',label:'已确认'}]} /><RdField label="成本、库存与供货核对" value={fields.supply_status} onChange={change('supply_status')} options={[{value:'pending',label:'待核实'},{value:'confirmed',label:'已确认'}]} /></div>
      </RdOperation></div></>}
    {journey?.route === 'direct' && <div className="rd-direct-delivery" id="direct-delivery"><h3>直接选用交接</h3><p className="rd-muted">记录约定接收方和实际凭据；尚未满足条件时记录阻断及处理说明。</p>
      {journey.delivery && <p className={`feedback-notice ${journey.delivery.outcome === 'blocked' ? 'rd-route-notice' : ''}`}>{journey.delivery.outcome === 'accepted' ? '已记录接收' : '交接存在阻断'} · {journey.delivery.recipient} · {rdTime(journey.delivery.created_at)}<br />{journey.delivery.reference || journey.delivery.note}</p>}
      {owner && selection && <RdOperation label="记录交接结果" disabled={disabled} dirty={JSON.stringify(delivery) !== JSON.stringify({outcome:'blocked',recipient:'',reference:'',note:''})} fingerprint={JSON.stringify([delivery, selection.id, detail.project.version])} execute={async key => { await run('record_delivery', { ...delivery, selection_id: selection.id }, key); setDelivery({outcome:'blocked',recipient:'',reference:'',note:''}); }} confirmation={delivery.outcome === 'accepted' ? <p>确认已核对选型适用性和供应条件，并持有接收方“{delivery.recipient}”的实际接收凭据。此操作记录交付事实。</p> : undefined}>
        <div className="rd-fields"><RdField label="交接结果" value={delivery.outcome} onChange={changeDelivery('outcome')} options={[{value:'blocked',label:'存在阻断 / 尚未接收'},{value:'accepted',label:'已实际接收'}]} /><RdField label="接收方" required value={delivery.recipient} onChange={changeDelivery('recipient')} /><RdField label="实际接收凭据" required={delivery.outcome === 'accepted'} value={delivery.reference} onChange={changeDelivery('reference')} /><RdField label="交接或阻断说明" required={delivery.outcome === 'blocked'} multiline value={delivery.note} onChange={changeDelivery('note')} /></div>
      </RdOperation>}
    </div>}
    {!!detail.selection_decisions?.length && <details className="rd-journey-history"><summary>查看选型与交接历史</summary>{[...detail.selection_decisions].reverse().map(record => <div className="rd-record" key={record.id}><strong>{record.route === 'direct' ? '直接选用' : record.route === 'modification' ? '改型' : '新研'} · {record.selected_product || '新研产品'}</strong><p>{record.rationale}</p><small className="rd-muted">{rdTime(record.created_at)} · {record.evidence_ref || '依据待补充'}</small>{detail.delivery_records?.filter(item => item.selection_id === record.id).map(item => <p key={item.id}>{item.outcome === 'accepted' ? '已接收' : '交接阻断'} · {item.recipient} · {item.reference || item.note}</p>)}</div>)}</details>}
  </section>;
}
