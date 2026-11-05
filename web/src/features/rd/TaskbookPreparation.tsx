import { PlatformButton } from '../../components/ui/PlatformButton';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { fixedBusinessTemplate } from './businessWorkflowFacts';
import { formatTime, routeTitle } from './presentation';
import type { Catalog, ResearchCase, TaskbookBinding } from './types';
import type { CommandRunner } from './WorkpackagePanel';

function BindingRecord({ binding }: { binding: TaskbookBinding }) {
  return <article className="rd-record-item rd-taskbook-binding"><h4>已固定的编制输入</h4><p>{binding.status === 'stale' || binding.invalidated_at ? '输入已变化，待重新采用' : '已采用固定版本'} · 输入版 {binding.input_revision} · {formatTime(binding.adopted_at)}</p><p className="rd-prewrap">工作范围：{binding.scope}</p><p className="rd-prewrap">采用依据：{binding.rationale}</p><dl><dt>流程模板</dt><dd>{binding.workflow.title} · V{binding.workflow.version}</dd><dt>DOCX 文档模板</dt><dd>{String(binding.document_template.title ?? '已绑定受控模板')}</dd></dl><details><summary>查看固定版本与指纹</summary><p className="rd-prewrap" style={{ overflowWrap: 'anywhere' }}>输入指纹：{binding.fingerprint}</p><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(binding.document_template, null, 2)}</pre></details>{binding.invalidated_reason && <p className="rd-warning">{binding.invalidated_reason}</p>}</article>;
}

export function TaskbookPreparation({ researchCase, catalog, busy, command, onDirtyChange }: { researchCase: ResearchCase; catalog: Catalog | null; busy: boolean; command: CommandRunner; onDirtyChange: (dirty: boolean) => void; onOpenWorkpackages?: () => void }) {
  const [workflowId, setWorkflowId] = useState('');
  const [scope, setScope] = useState('');
  const [rationale, setRationale] = useState('');
  const [validation, setValidation] = useState('');
  const [saved, setSaved] = useState(false);
  const firstField = useRef<HTMLTextAreaElement>(null);
  const dirty = !saved && !!(workflowId || scope || rationale);
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  const templates = (catalog?.research_workflow_templates ?? []).filter(item => item.status === 'published' && item.product_route === researchCase.product_route?.value);
  const projectTemplate = researchCase.workflow_templates?.project;
  const selected = projectTemplate ?? templates.find(item => item.id === workflowId);
  const binding = researchCase.taskbook_binding;
  const current = binding && binding.status === 'current' && !binding.invalidated_at && binding.input_revision === researchCase.input_revision;
  const projectCompleted = researchCase.project_workflow_status?.status === 'completed';
  const editable = researchCase.stage === 'planning' && researchCase.status !== 'completed' && !projectCompleted;
  async function adopt(event: FormEvent) {
    event.preventDefault();
    if (!selected || !scope.trim() || !rationale.trim()) { setValidation(projectTemplate ? '请填写任务书编制范围和采用依据。' : '请选择适用的已发布研发流程，并填写工作范围和采用依据。'); firstField.current?.focus(); return; }
    setValidation('');
    const fixed = fixedBusinessTemplate(selected);
    await command('adopt_taskbook_flow', { workflow_id: fixed.id, workflow_version: fixed.version, scope: scope.trim(), rationale: rationale.trim() }, () => { setSaved(true); });
  }
  if (researchCase.product_route?.value === 'direct') return <section className="rd-section"><h2>成熟产品直接选用</h2><p>{projectTemplate ? '当前选型为直接选用，不创建研发任务书工作包。请核对已确认需求、逐项产品证据与选型决定；项目流程的实际状态保留在项目流程中。' : '沿已确认需求和逐项产品证据办理供给与接收，无需采用研发流程或编制研发任务书。在本阶段业务确认中填写供给工作范围、依据并关联来源，随后登记实际交付回执。库存价格与补货服务尚未接入。'}</p></section>;
  return <section className="rd-section" aria-labelledby="rd-taskbook-preparation-title"><h3 id="rd-taskbook-preparation-title">编制依据</h3><dl className="rd-outcome-statuses"><div><dt>产品研制分类</dt><dd>{researchCase.product_route ? routeTitle('product', researchCase.product_route.value) : '尚未确认'}</dd></div><div><dt>任务书编制策略</dt><dd>{researchCase.composition_route ? routeTitle('composition', researchCase.composition_route.value) : '尚未确认'}</dd></div><div><dt>确认需求</dt><dd>{researchCase.requirements.length} 条 · 输入版 {researchCase.input_revision ?? 1}</dd></div>{projectTemplate && !binding && <div><dt>流程模板</dt><dd>{projectTemplate.title} · V{fixedBusinessTemplate(projectTemplate).version}</dd></div>}</dl>
    {binding && <BindingRecord binding={binding} />}
    {binding && !current && <p className="rd-warning" role="status">原采用记录继续保留。请核对变化后的需求、比对、六参数与来源，再采用固定版本。</p>}
    {current && <p className="rd-notice" role="status">{projectTemplate ? projectCompleted ? '输入与本流程生成结果已固定。' : '输入已固定，可以编排并提交任务书工作包。' : researchCase.business_lifecycle?.policy_version === 'v2' ? '输入已固定。质量校验通过后，仍需单独批准任务书范围。' : '输入已固定，完成本阶段业务确认后进入任务书编制。'}</p>}
    {!editable && <p className="rd-muted">{projectTemplate ? '项目流程已固定，当前可查阅任务书输入采用记录与历史。' : '研发流程在“采用研发流程与编制任务书”阶段采用。当前可查阅固定记录与历史。'}</p>}
    {editable && <form noValidate onSubmit={adopt}>{!projectTemplate && <><div className="rd-field"><label id="rd-workflow-label">研发流程模板</label><StyledSelect aria-labelledby="rd-workflow-label" value={workflowId} onChange={value => { setWorkflowId(value); setSaved(false); }} disabled={busy} options={[{ value: '', label: '请选择适用流程' }, ...templates.map(item => ({ value: item.id, label: `${item.title} · V${item.version}` }))]} /></div>{!templates.length && <p className="rd-warning">当前产品研制分类没有适用的已发布研发流程。成熟产品直接选用应沿供给路线办理；缺少研发模板请联系流程维护人员。</p>}</>}<div className="rd-field"><label htmlFor="rd-taskbook-scope">{projectTemplate ? '本次任务书编制范围' : '本次研发工作范围'}</label><textarea ref={firstField} id="rd-taskbook-scope" className="resize-none" rows={4} value={scope} onChange={event => { setScope(event.target.value); setSaved(false); }} disabled={busy} aria-invalid={!!validation && !scope.trim()} aria-describedby={validation ? 'rd-binding-error' : undefined} /></div><div className="rd-field"><label htmlFor="rd-taskbook-rationale">采用依据与差异处理边界</label><textarea id="rd-taskbook-rationale" className="resize-none" rows={4} value={rationale} onChange={event => { setRationale(event.target.value); setSaved(false); }} disabled={busy} aria-invalid={!!validation && !rationale.trim()} aria-describedby={validation ? 'rd-binding-error' : undefined} /></div>{validation && <p id="rd-binding-error" className="rd-error" role="alert">{validation}</p>}<p className="rd-muted">采用时由服务端核对当前需求、两类比对、两个决策、六参数与来源版本；缺少受控模板或证据将明确阻塞。</p><PlatformButton className="rd-button primary" type="submit" disabled={busy || !selected || saved}>{projectTemplate ? '固定任务书输入' : '采用流程并固定任务书输入'}</PlatformButton></form>}
    {!!researchCase.taskbook_binding_history?.length && <details><summary>任务书输入采用历史（{researchCase.taskbook_binding_history.length} 版）</summary>{researchCase.taskbook_binding_history.map(item => <BindingRecord key={`${item.id}-${item.revision}`} binding={item} />)}</details>}
  </section>;
}
