import { useEffect, useRef, useState, type FormEvent } from 'react';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { formatTime, routeTitle } from './presentation';
import type { Catalog, ResearchCase, TaskbookBinding } from './types';
import type { CommandRunner } from './WorkpackagePanel';

function BindingRecord({ binding }: { binding: TaskbookBinding }) {
  return <article className="rd-record-item"><h3>{binding.workflow.title} · V{binding.workflow.version}</h3><p>{binding.status === 'stale' || binding.invalidated_at ? '输入已变化，待重新采用' : '已采用固定版本'} · 需求输入版 {binding.input_revision} · {formatTime(binding.adopted_at)}</p><p className="rd-prewrap">工作范围：{binding.scope}</p><p className="rd-prewrap">采用依据：{binding.rationale}</p><dl><dt>DOCX 文档模板</dt><dd>{String(binding.document_template.title ?? '已绑定受控模板')}</dd><dt>固定输入指纹</dt><dd className="rd-prewrap" style={{ overflowWrap: 'anywhere' }}>{binding.fingerprint}</dd></dl><details><summary>查看文档模板版本与指纹</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(binding.document_template, null, 2)}</pre></details>{binding.invalidated_reason && <p className="rd-warning">{binding.invalidated_reason}</p>}</article>;
}

export function TaskbookPreparation({ researchCase, catalog, busy, command, onDirtyChange, onOpenWorkpackages }: { researchCase: ResearchCase; catalog: Catalog | null; busy: boolean; command: CommandRunner; onDirtyChange: (dirty: boolean) => void; onOpenWorkpackages?: () => void }) {
  const [workflowId, setWorkflowId] = useState('');
  const [scope, setScope] = useState('');
  const [rationale, setRationale] = useState('');
  const [validation, setValidation] = useState('');
  const [saved, setSaved] = useState(false);
  const firstField = useRef<HTMLTextAreaElement>(null);
  const dirty = !saved && !!(workflowId || scope || rationale);
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  const templates = (catalog?.research_workflow_templates ?? []).filter(item => item.status === 'published' && item.product_route === researchCase.product_route?.value);
  const selected = templates.find(item => item.id === workflowId);
  const binding = researchCase.taskbook_binding;
  const current = binding && binding.status === 'current' && !binding.invalidated_at && binding.input_revision === researchCase.input_revision;
  const editable = researchCase.stage === 'planning' && researchCase.status !== 'completed';
  async function adopt(event: FormEvent) {
    event.preventDefault();
    if (!selected || !scope.trim() || !rationale.trim()) { setValidation('请选择适用的已发布研发流程，并填写工作范围和采用依据。'); firstField.current?.focus(); return; }
    setValidation('');
    await command('adopt_taskbook_flow', { workflow_id: selected.id, workflow_version: selected.version, scope: scope.trim(), rationale: rationale.trim() }, () => { setSaved(true); });
  }
  if (researchCase.product_route?.value === 'direct') return <section className="rd-section"><h2>成熟产品直接选用</h2><p>沿已确认需求和逐项产品证据办理供给与接收，无需采用研发流程或编制研发任务书。在本阶段业务确认中填写供给工作范围、依据并关联来源，随后登记实际交付回执。库存价格与补货服务尚未接入。</p></section>;
  return <section className="rd-section" aria-labelledby="rd-taskbook-preparation-title"><h2 id="rd-taskbook-preparation-title">将任务书纳入本项目研发流程</h2><p>沿用已确认需求、逐项比对与选型差异。研发流程模板决定后续办理节点；DOCX 文档模板决定任务书章节与字段，由六参数和编制策略解析，两者分别固定版本。</p><dl className="rd-outcome-statuses"><div><dt>产品研制分类</dt><dd>{researchCase.product_route ? routeTitle('product', researchCase.product_route.value) : '尚未确认'}</dd></div><div><dt>任务书编制策略</dt><dd>{researchCase.composition_route ? routeTitle('composition', researchCase.composition_route.value) : '尚未确认'}</dd></div><div><dt>确认需求</dt><dd>{researchCase.requirements.length} 条 · 输入版 {researchCase.input_revision ?? 1}</dd></div></dl>
    {binding && <BindingRecord binding={binding} />}
    {binding && !current && <p className="rd-warning" role="status">原采用记录继续保留。请核对变化后的需求、比对、六参数与来源，再采用固定版本。</p>}
    {current && <p className="rd-notice" role="status">{researchCase.business_lifecycle?.policy_version === 'v2' ? '输入已固定。请在本策划阶段编排任务书工作包，整包提交后自动执行。质量通过后仍需单独批准任务书范围。' : '输入已固定。记录本阶段业务确认后，进入任务书编制节点拉取工作包。'}{onOpenWorkpackages && researchCase.business_lifecycle?.policy_version === 'v2' && <button type="button" className="rd-link-button" onClick={onOpenWorkpackages}>编排任务书工作包 →</button>}</p>}
    {!editable && <p className="rd-muted">研发流程在“采用研发流程与编制任务书”阶段采用。当前可查阅固定记录与历史。</p>}
    {editable && <form noValidate onSubmit={adopt}><div className="rd-field"><label id="rd-workflow-label">研发流程模板</label><StyledSelect aria-labelledby="rd-workflow-label" value={workflowId} onChange={value => { setWorkflowId(value); setSaved(false); }} disabled={busy} options={[{ value: '', label: '请选择适用流程' }, ...templates.map(item => ({ value: item.id, label: `${item.title} · V${item.version}` }))]} /></div>{!templates.length && <p className="rd-warning">当前产品研制分类没有适用的已发布研发流程。成熟产品直接选用应沿供给路线办理；缺少研发模板请联系流程维护人员。</p>}{selected && <p className="rd-notice">流程：任务书 → 方案设计 → 详细设计 → 整合 → 验证 → 交付。后续专业设计按实际工程记录办理。</p>}<div className="rd-field"><label htmlFor="rd-taskbook-scope">本次研发工作范围</label><textarea ref={firstField} id="rd-taskbook-scope" className="resize-none" rows={4} value={scope} onChange={event => { setScope(event.target.value); setSaved(false); }} disabled={busy} aria-invalid={!!validation && !scope.trim()} aria-describedby={validation ? 'rd-binding-error' : undefined} /></div><div className="rd-field"><label htmlFor="rd-taskbook-rationale">采用依据与差异处理边界</label><textarea id="rd-taskbook-rationale" className="resize-none" rows={4} value={rationale} onChange={event => { setRationale(event.target.value); setSaved(false); }} disabled={busy} aria-invalid={!!validation && !rationale.trim()} aria-describedby={validation ? 'rd-binding-error' : undefined} /></div>{validation && <p id="rd-binding-error" className="rd-error" role="alert">{validation}</p>}<p className="rd-muted">采用时由服务端核对当前需求、两类比对、两个决策、六参数与来源版本；缺少受控模板或证据将明确阻塞。</p><button className="rd-button primary" type="submit" disabled={busy || !selected || saved}>采用流程并固定任务书输入</button></form>}
    {!!researchCase.taskbook_binding_history?.length && <details><summary>任务书输入采用历史（{researchCase.taskbook_binding_history.length} 版）</summary>{researchCase.taskbook_binding_history.map(item => <BindingRecord key={`${item.id}-${item.revision}`} binding={item} />)}</details>}
  </section>;
}
