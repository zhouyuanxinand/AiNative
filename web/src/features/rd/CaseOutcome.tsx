import { PlatformButton } from '../../components/ui/PlatformButton';
import { artifactUrl, sourceUrl } from './api';
import { caseArtifactRecords, summarizeCaseOutcome } from './caseOutcomeModel';
import { formatTime, isCurrentSource, routeTitle, statusTitle } from './presentation';
import { nextCaseAction, scenarioStage, type CaseSurface, type ScenarioManifest } from './scenarioManifest';
import type { AssistantTarget, Project, ResearchCase } from './types';

interface Props {
  project: Project; researchCase: ResearchCase; manifest?: ScenarioManifest;
  onOpen: (surface: CaseSurface) => void; onNavigate: (target: AssistantTarget) => void;
  onOpenWorkpackage: (id: string) => void;
}

export function CaseOutcome({ project, researchCase, manifest, onOpen, onNavigate, onOpenWorkpackage }: Props) {
  const stage = scenarioStage(researchCase, manifest);
  const state = summarizeCaseOutcome(researchCase);
  const lifecycle = researchCase.business_lifecycle;
  const projectWorkflow = researchCase.workflow_templates?.project;
  const projectFlowStatus = researchCase.project_workflow_status;
  const currentDecisionId = researchCase.stage === 'planning' || researchCase.stage === 'design' ? lifecycle?.current_taskbook_scope_decision_id : lifecycle?.current_selection_decision_id;
  const businessDecision = researchCase.decisions.find(item => item.id === currentDecisionId && !item.invalidated_at);
  const nextAction = nextCaseAction(researchCase, manifest);
  const next = nextAction?.target === 'decision' && ['input', 'requirements'].includes(researchCase.stage)
    ? { target: 'requirements' as const, label: '核对需求并确认' } : nextAction;
  const sources = researchCase.sources.filter(source => isCurrentSource(source, researchCase.source_selection));
  const comparisons = (researchCase.comparisons ?? []).filter(item => !item.invalidated_at && item.input_revision === researchCase.input_revision);
  const artifacts = caseArtifactRecords(researchCase);
  const currentArtifacts = artifacts.filter(item => item.current && item.workpackage.status !== 'cancelled' && (['verification', 'delivery'].includes(researchCase.stage) || item.workpackage.stage === researchCase.stage));
  const visibleArtifacts = currentArtifacts.filter(item => !stage.primaryArtifactKinds || stage.primaryArtifactKinds.includes(item.artifact.kind ?? ''))
    .sort((a, b) => (stage.primaryArtifactKinds?.indexOf(a.artifact.kind ?? '') ?? 0) - (stage.primaryArtifactKinds?.indexOf(b.artifact.kind ?? '') ?? 0));
  const deliveries = (researchCase.deliveries ?? []).filter(item => item.input_revision === researchCase.input_revision);
  const candidates = (researchCase.reuse_candidates ?? []).filter(item => item.input_revision === researchCase.input_revision);
  const clarifications = (researchCase.clarifications ?? []).filter(item => item.status !== 'adopted' || item.invalidated_at);
  const count = stage.outcome === 'sources' ? sources.length : stage.outcome === 'requirements' ? researchCase.requirements.length
    : stage.outcome === 'comparisons' ? comparisons.length : stage.outcome === 'routes' ? Number(!!researchCase.product_route) + Number(!!researchCase.composition_route)
      : stage.outcome === 'delivery' ? deliveries.length : stage.outcome === 'reuse' ? candidates.length : visibleArtifacts.length;
  const outcomeLabel = count ? `已有 ${count} ${['requirements', 'routes', 'delivery'].includes(stage.outcome) ? '条' : '份'}记录` : '尚未形成当前成果';
  const showDecision = researchCase.stage !== 'input' || !!businessDecision || state.confirmation.kind !== 'unrecorded';
  const decisionLabel = businessDecision ? (businessDecision.verdict === 'approved' ? '已确认 · 非正式电子审签' : '已退回')
    : state.confirmation.kind !== 'unrecorded' ? state.confirmation.label
      : projectWorkflow && researchCase.stage === 'planning' ? (lifecycle?.rd_activation_state === 'active' ? '研发启动依据已记录' : '研发启动待确认')
        : lifecycle?.rd_activation_state === 'historical_unverified' ? '历史未核实'
          : lifecycle?.policy_version === 'v2' ? '待负责人确认' : state.confirmation.label;

  return <section className="rd-outcome-workface" aria-labelledby="rd-current-outcome-title">
    <header className="rd-outcome-heading"><h2 id="rd-current-outcome-title">{stage.outcomeTitle}</h2>{next && <PlatformButton type="button" className="rd-button primary" onClick={() => onOpen(next.target)}>{next.label}<span aria-hidden="true"> →</span></PlatformButton>}</header>
    <dl className="rd-outcome-statuses">{count > 0 && <div><dt>成果状态</dt><dd>{outcomeLabel}</dd></div>}{state.execution.kind !== 'unrecorded' && <div><dt>执行状态</dt><dd>{state.execution.label}</dd></div>}{state.verification.kind !== 'unrecorded' && <div><dt>质量门禁</dt><dd>{state.verification.label}</dd></div>}{showDecision && <div><dt>工程决定</dt><dd>{decisionLabel}</dd></div>}</dl>
    {projectFlowStatus?.reason && <p className="rd-notice" role="status">{projectFlowStatus.reason}</p>}
    {!!state.blockedPackages.length && <div className="rd-outcome-blockers" role="status"><strong>当前执行有待处理事项</strong>{state.blockedPackages.map(item => <p key={item.id}><PlatformButton type="button" className="rd-link-button" onClick={() => onOpenWorkpackage(item.id)}>{item.title} · 查看原因与证据缺口 →</PlatformButton>{item.obligations.length > 0 && <span> {item.obligations.length} 项补齐义务</span>}</p>)}</div>}
    <div className="rd-outcome-document">
      {!count && <div className="rd-outcome-empty"><h3>尚未形成{stage.outcomeTitle}</h3><p>{stage.outcome === 'artifacts' || stage.outcome === 'verification' ? '工作包完成后，可在此查看成果与校验记录。' : '完成当前步骤后在此查看已保存结果。'}</p></div>}
      {stage.outcome === 'sources' && sources.slice(0, 4).map(source => <article className="rd-outcome-record" key={source.id}><div><h3><a href={sourceUrl(project.id, researchCase.id, source.id)} target="_blank" rel="noreferrer">{source.name} ↗</a></h3><span className="rd-badge">{{ tech: '技术资料', spec: '规范标准', reference: '参考资料' }[source.role]}</span></div><p>当前输入 · 来源版 {source.version}</p></article>)}
      {stage.outcome === 'requirements' && <>{researchCase.requirements.slice(0, 4).map(requirement => <article className="rd-outcome-record" key={requirement.id}><h3>{requirement.title}</h3><p className="rd-prewrap">{requirement.content}</p><p className="rd-outcome-meta">{requirement.source_ids.length} 份来源依据{requirement.source_ids.some(id => !sources.some(source => source.id === id)) ? ' · 来源待更新' : ''}</p></article>)}{!!clarifications.length && <p className="rd-outcome-note">{clarifications.length} 条澄清仍需处理或复核。</p>}</>}
      {stage.outcome === 'comparisons' && comparisons.slice(0, 4).map(record => <article className="rd-outcome-record" key={record.id}><div><h3>{record.title}</h3><span className="rd-badge">{record.kind === 'product' ? '产品比对' : '文档比对'}</span></div><p>人工逐项记录 · 修订 {record.revision}</p><dl className="rd-outcome-comparison"><div><dt>满足</dt><dd>{record.statistics.matches}</dd></div><div><dt>部分满足</dt><dd>{record.statistics.partial}</dd></div><div><dt>缺口</dt><dd>{record.statistics.gap}</dd></div><div><dt>未知</dt><dd>{record.statistics.unknown}</dd></div></dl></article>)}
      {stage.outcome === 'routes' && <div className="rd-outcome-decisions">{([{ axis: 'product', title: '产品研制分类', record: researchCase.product_route }, { axis: 'composition', title: '任务书编制策略', record: researchCase.composition_route }]).map(item => <article className="rd-outcome-record" key={item.axis}><p className="rd-outcome-meta">{item.title}</p><h3>{item.record ? routeTitle(item.axis, item.record.value) : '尚未记录'}</h3>{item.record && <><p className="rd-prewrap">{item.record.rationale}</p><p className="rd-outcome-meta">{item.record.source_ids.length} 份依据 · {formatTime(item.record.created_at)}</p></>}</article>)}</div>}
      {(stage.outcome === 'artifacts' || stage.outcome === 'verification') && <>{stage.outcome === 'verification' && <p className="rd-outcome-note"><strong>{state.verification.label}</strong><span> · 业务确认另行记录</span></p>}{visibleArtifacts.slice(0, 5).map(({ artifact, workpackage }) => <article className="rd-outcome-record" key={`${workpackage.id}-${artifact.id}`}><div><h3><a href={artifactUrl(project.id, researchCase.id, workpackage.id, artifact.id)} target="_blank" rel="noreferrer">{artifact.name} · {lifecycle?.policy_version === 'v2' && !lifecycle.current_taskbook_scope_decision_id ? '下载复核稿' : '下载'} ↗</a></h3><span className="rd-badge">已登记成果</span></div><p>{workpackage.title} · {statusTitle(workpackage.status)}{workpackage.stage !== researchCase.stage ? ' · 上游成果' : ''}</p><PlatformButton type="button" className="rd-link-button" onClick={() => onOpenWorkpackage(workpackage.id)}>查看对应执行与固定依据 →</PlatformButton></article>)}{currentArtifacts.length > visibleArtifacts.length && <p className="rd-outcome-note">另有 {currentArtifacts.length - visibleArtifacts.length} 份执行过程记录。</p>}{artifacts.some(item => !item.current || item.workpackage.status === 'cancelled') && <p className="rd-outcome-note">历史输入或已取消工作包的成果仍保留，使用前需核对。</p>}</>}
      {stage.outcome === 'delivery' && deliveries.slice(0, 4).map(record => <article className="rd-outcome-record" key={record.id}><div><h3>{record.recipient}</h3><span className="rd-badge">{record.outcome === 'accepted' ? '已登记接收' : '反馈要求修订'}</span></div><p className="rd-prewrap">{record.receipt}</p>{record.feedback && <p className="rd-prewrap">反馈：{record.feedback}</p>}<p className="rd-outcome-meta">人工交付登记 · {record.artifact_ids.length} 份关联成果 · {formatTime(record.created_at)}</p></article>)}
      {stage.outcome === 'reuse' && <>{candidates.slice(0, 4).map(record => <article className="rd-outcome-record" key={record.id}><div><h3>{record.title}</h3><span className="rd-badge">案例内候选 · 尚未发布</span></div><p className="rd-prewrap">{record.content}</p></article>)}{researchCase.reuse_disposition?.kind === 'not_publish' && <p className="rd-outcome-note">已登记不发布处置：{String(researchCase.reuse_disposition.reason ?? '')}</p>}</>}
    </div>
    <footer className="rd-outcome-footer">{count > (['artifacts', 'verification'].includes(stage.outcome) ? 5 : 4) && <span className="rd-muted">当前显示部分记录，共 {count} 条。</span>}<PlatformButton type="button" className="rd-link-button" onClick={() => onNavigate('artifacts')}>查看全部成果与依据 →</PlatformButton></footer>
  </section>;
}
