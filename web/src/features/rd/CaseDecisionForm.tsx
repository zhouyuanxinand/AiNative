import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { SourcePicker } from './CaseFields';
import { STAGES, isCurrentSource, stageTitle } from './presentation';
import type { ModelSelection, Project, ResearchCase } from './types';
import type { CommandRunner } from './WorkpackagePanel';
import { sourceUrl, artifactUrl } from './api';
import { SelectionDecisionPanel } from './SelectionDecisionPanel';
import './businessLifecycle.css';

type DecisionProps = { project: Project; researchCase: ResearchCase; busy: boolean; error: string; command: CommandRunner; onDirtyChange: (dirty: boolean) => void };
export function CaseDecisionForm(props: DecisionProps) {
  return props.researchCase.business_lifecycle?.policy_version === 'v2' && ['input', 'requirements', 'selection', 'planning'].includes(props.researchCase.stage)
    ? <SelectionDecisionPanel {...props} /> : <StageDecisionForm {...props} />;
}
function StageDecisionForm({ project, researchCase, busy, error, command, onDirtyChange }: DecisionProps) {
  const [supplyScope, setSupplyScope] = useState('');
  const [decisionReason, setDecisionReason] = useState('');
  const [decisionVerdict, setDecisionVerdict] = useState('');
  const [decisionSources, setDecisionSources] = useState<string[]>([]);
  const [decisionArtifacts, setDecisionArtifacts] = useState<string[]>([]);
  const [decisionError, setDecisionError] = useState('');
  const [confirmDecision, setConfirmDecision] = useState(false);
  const [notPublish, setNotPublish] = useState(false);
  const [notPublishReason, setNotPublishReason] = useState('');
  const stage = STAGES.find(item => item.id === researchCase.stage)!;
  const currentStage = researchCase.status !== 'completed';
  const restricted = researchCase.business_lifecycle?.policy_version === 'v2' && researchCase.business_lifecycle.can_record_decision !== true;
  const artifacts = researchCase.workpackages.flatMap(workpackage => workpackage.artifacts.map(artifact => ({ ...artifact, workpackage })));
  const isArchivedSource = (id: string) => { const source = researchCase.sources.find(item => item.id === id); return !source || !isCurrentSource(source, researchCase.source_selection); };
  const dirty = !!supplyScope || !!decisionReason || !!decisionVerdict || !!decisionSources.length || !!decisionArtifacts.length || notPublish || !!notPublishReason;
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  function prepareDecision(event: FormEvent) {
    event.preventDefault();
    if (researchCase.stage === 'planning' && researchCase.product_route?.value !== 'direct' && decisionVerdict === 'approved' && (!researchCase.taskbook_binding || researchCase.taskbook_binding.status !== 'current' || researchCase.taskbook_binding.invalidated_at || researchCase.taskbook_binding.input_revision !== researchCase.input_revision)) { setDecisionError('请先在“研发流程与任务书准备”采用适用流程并固定当前任务书输入，再记录通过决定。'); document.getElementById('rd-decision-reason')?.focus(); return; }
    if (researchCase.stage === 'knowledge' && decisionVerdict === 'approved' && notPublish && (!notPublishReason.trim() || !decisionSources.length)) { setDecisionError('不发布处置需要填写理由，并在下方关联来源依据。'); document.getElementById('rd-no-publish-reason')?.focus(); return; }
    if (!decisionVerdict || !decisionReason.trim() || decisionSources.some(isArchivedSource) || (decisionVerdict === 'approved' && !decisionSources.length && !decisionArtifacts.length)) { setDecisionError('请选择决定结果并填写实际说明；通过决定还须关联当前输入或已登记成果。历史资料请先更新来源关联。'); document.getElementById('rd-decision-reason')?.focus(); return; }
    if (researchCase.stage === 'planning' && researchCase.product_route?.value === 'direct' && decisionVerdict === 'approved' && (!supplyScope.trim() || !decisionSources.length)) { setDecisionError('请填写成熟产品供给工作范围，并关联实际来源依据。'); document.getElementById('rd-supply-scope')?.focus(); return; }
    setDecisionError(''); setConfirmDecision(true);
  }
  const decisionPanel = <section className="rd-section rd-stage-decision"><div className="rd-section-head"><div><span className="rd-eyebrow">真实业务决定</span><h3>{stage.title} · 阶段决定</h3><p>由实际负责人核对证据后记录。系统不代签、不根据节点完成情况自动推进。</p></div></div>{restricted && <p className="rd-warning" role="status">当前用户没有本地项目负责人决定资格，或企业正式政策尚未配置。可查阅已登记依据。</p>}{researchCase.business_lifecycle?.policy_version === 'v2' && <p className="rd-notice">本地负责人确认 · 非正式电子审签</p>}{currentStage ? <form noValidate onSubmit={prepareDecision}><div className="rd-form-grid"><div className="rd-field"><label id="rd-decision-verdict-label">决定结果</label><StyledSelect aria-labelledby="rd-decision-verdict-label" value={decisionVerdict} onChange={setDecisionVerdict} disabled={busy || restricted} options={[{ value: '', label: '请选择决定结果' }, { value: 'approved', label: researchCase.stage === 'knowledge' ? '通过本阶段核对' : '通过本阶段并推进' }, { value: 'rejected', label: '未通过，保留在本阶段' }]} /></div><div className="rd-decision-help">{researchCase.stage === 'requirements' ? '需求确认须有非空且有来源的需求记录。' : researchCase.stage === 'selection' ? '通过选型前须分别保存产品研制分类与任务书编制策略。' : researchCase.stage === 'planning' ? '须先采用研发流程并固定任务书输入，才进入任务书编制节点。' : researchCase.stage === 'verification' ? '进入交付前须有验证通过结果和实际成果。' : '阶段门槛由服务端核验，资料不足时保留当前阶段。'}</div></div>{researchCase.stage === 'planning' && researchCase.product_route?.value === 'direct' && <div className="rd-field"><label htmlFor="rd-supply-scope">成熟产品供给工作范围</label><textarea id="rd-supply-scope" className="resize-none" rows={3} value={supplyScope} onChange={event => setSupplyScope(event.target.value)} disabled={busy || restricted} /><small>记录实际供给、交付与接收范围，不模拟库存预留或补货成功。</small></div>}<div className="rd-field"><label htmlFor="rd-decision-reason">实际决定说明</label><textarea id="rd-decision-reason" className="resize-none" rows={3} value={decisionReason} onChange={event => setDecisionReason(event.target.value)} disabled={busy || restricted} placeholder="填写已核对的事项、结论及证据依据" aria-invalid={!!decisionError && !decisionReason.trim()} aria-describedby={decisionError ? 'rd-decision-error' : undefined} /></div>{researchCase.stage === 'knowledge' && <div className="rd-no-publish"><label><input type="checkbox" checked={notPublish} onChange={event => setNotPublish(event.target.checked)} disabled={busy || restricted} />本次不准备复用候选，登记不发布处置</label>{notPublish && <div className="rd-field"><label htmlFor="rd-no-publish-reason">不发布理由</label><textarea id="rd-no-publish-reason" rows={3} className="resize-none" value={notPublishReason} onChange={event => setNotPublishReason(event.target.value)} disabled={busy || restricted} /><small>请在下方关联来源依据；不发布处置与原决定一起保留。</small></div>}</div>}<SourcePicker sources={researchCase.sources} sourceSelection={researchCase.source_selection} value={decisionSources} onChange={setDecisionSources} disabled={busy || restricted} />{!!artifacts.length && <fieldset className="rd-source-picker" disabled={busy || restricted}><legend>关联已登记成果</legend>{artifacts.map(artifact => <label key={`${artifact.workpackage.id}-${artifact.id}`}><input type="checkbox" checked={decisionArtifacts.includes(artifact.id)} onChange={event => setDecisionArtifacts(current => event.target.checked ? [...current, artifact.id] : current.filter(id => id !== artifact.id))} /><a href={artifactUrl(project.id, researchCase.id, artifact.workpackage.id, artifact.id)} target="_blank" rel="noreferrer">{artifact.name} ↗</a></label>)}</fieldset>}{decisionError && <p id="rd-decision-error" className="rd-error" role="alert">{decisionError}</p>}<div className="rd-actions"><p className="rd-muted">决定将记录当前用户、说明、证据和时间。</p><button type="submit" className="rd-button primary" disabled={busy || restricted}>记录阶段决定</button></div></form> : <p className="rd-notice">本阶段仅供查看。可在当前阶段“{stageTitle(researchCase.stage)}”记录决定。</p>}</section>;
  return <><details className="rd-decision-disclosure"><summary>记录本阶段决定 <span>{stage.short} · 由实际负责人核对</span></summary>{decisionPanel}</details>
    {confirmDecision && <FeedbackConfirmDialog title={`记录“${stageTitle(researchCase.stage)}”的实际决定`} confirm="保存阶段决定" pending={busy} error={error} onCancel={() => setConfirmDecision(false)} onConfirm={() => void command(researchCase.business_lifecycle?.policy_version === 'v2' ? 'confirm_engineering_stage' : 'advance_stage', { stage: researchCase.stage, scope: supplyScope, verdict: decisionVerdict, rationale: decisionReason, source_ids: decisionSources, artifact_ids: decisionArtifacts, ...(researchCase.stage === 'knowledge' && notPublish ? { no_publish_reason: notPublishReason, no_publish_source_ids: decisionSources } : {}) }, () => { setSupplyScope(''); setDecisionReason(''); setDecisionVerdict(''); setDecisionSources([]); setDecisionArtifacts([]); setConfirmDecision(false); setNotPublish(false); setNotPublishReason(''); })}><p>将记录“{decisionVerdict === 'approved' ? '通过' : '未通过'}”、当前填写的说明，以及 {decisionSources.length} 份来源和 {decisionArtifacts.length} 份成果证据。通过后按案例流程推进。</p></FeedbackConfirmDialog>}
  </>;
}
