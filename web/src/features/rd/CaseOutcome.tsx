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
  const currentDecisionId = researchCase.stage === 'planning' || researchCase.stage === 'design' ? lifecycle?.current_taskbook_scope_decision_id : lifecycle?.current_selection_decision_id;
  const businessDecision = researchCase.decisions.find(item => item.id === currentDecisionId && !item.invalidated_at);
  const next = nextCaseAction(researchCase, manifest);
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

  return <section className="rd-outcome-workface" aria-labelledby="rd-current-outcome-title">
    <header className="rd-outcome-heading"><div><p className="rd-eyebrow">当前成果</p><h2 id="rd-current-outcome-title">{stage.outcomeTitle}</h2><p>{stage.guidance}</p></div>{next && <button type="button" className="rd-button primary" onClick={() => onOpen(next.target)}>{next.label}<span aria-hidden="true"> →</span></button>}</header>
    <dl className="rd-outcome-statuses"><div><dt>成果状态</dt><dd>{outcomeLabel}</dd></div><div><dt>执行状态</dt><dd>{state.execution.label}</dd></div><div><dt>质量门禁</dt><dd>{state.verification.label}</dd></div><div><dt>工程决定</dt><dd>{lifecycle?.rd_activation_state === 'historical_unverified' ? '历史未核实' : lifecycle?.policy_version === 'v2' ? businessDecision ? (businessDecision.verdict === 'approved' ? '已确认 · 非正式电子审签' : '已退回') : '待负责人确认' : state.confirmation.label}</dd></div></dl>
    {['input', 'requirements', 'selection', 'planning'].includes(researchCase.stage) && <nav className="rd-business-chain" aria-label="需求到任务书的业务依据"><ol>{([
      { target: 'sources', title: '上传与项目输入', detail: `${sources.length} 份当前来源；六参数逐项保留依据` },
      { target: 'requirements', title: '澄清、采纳与需求确认', detail: `${researchCase.requirements.length} 条需求；${clarifications.length} 条澄清待处理或复核` },
      { target: 'routes', title: '成熟产品与文档逐项比对', detail: `${comparisons.length} 份当前比对；区分满足、差异与缺证据` },
      { target: 'preparation', title: '采用研发流程，固定任务书输入', detail: researchCase.taskbook_binding?.status === 'current' ? '已采用固定版；输入变化后重新复核' : '继承同一项目的需求、差异和来源' },
    ] as const).map(item => <li key={item.target}><button type="button" className="rd-link-button" onClick={() => onOpen(item.target)}>{item.title} →</button><p>{item.detail}</p></li>)}</ol><p className="rd-muted">匹配统计来自逐项证据。直接选用成熟产品、改型研发与全新研发分别判断；任务书编制策略另依据文档比对决定。</p></nav>}
    {!!state.blockedPackages.length && <div className="rd-outcome-blockers" role="status"><strong>当前执行有待处理事项</strong>{state.blockedPackages.map(item => <p key={item.id}><button type="button" className="rd-link-button" onClick={() => onOpenWorkpackage(item.id)}>{item.title} · 查看原因与证据缺口 →</button>{item.obligations.length > 0 && <span> {item.obligations.length} 项补齐义务</span>}</p>)}</div>}
    <div className="rd-outcome-document">
      {!count && <div className="rd-outcome-empty"><h3>尚未形成{stage.outcomeTitle}</h3><p>{stage.outcome === 'artifacts' || stage.outcome === 'verification' ? '工作包登记实际成果后会显示在这里。可以先查看计划、执行进展与缺口。' : '完成本阶段的信息整理后，已保存的内容会显示在这里。'}{next ? '从上方下一步继续办理。' : '可查看项目流程与历史记录。'}</p></div>}
      {stage.outcome === 'sources' && sources.slice(0, 4).map(source => <article className="rd-outcome-record" key={source.id}><div><h3><a href={sourceUrl(project.id, researchCase.id, source.id)} target="_blank" rel="noreferrer">{source.name} ↗</a></h3><span className="rd-badge">{{ tech: '技术资料', spec: '规范标准', reference: '参考资料' }[source.role]}</span></div><p>当前输入 · 来源版 {source.version}</p></article>)}
      {stage.outcome === 'requirements' && <>{researchCase.requirements.slice(0, 4).map(requirement => <article className="rd-outcome-record" key={requirement.id}><h3>{requirement.title}</h3><p className="rd-prewrap">{requirement.content}</p><p className="rd-outcome-meta">{requirement.source_ids.length} 份来源依据{requirement.source_ids.some(id => !sources.some(source => source.id === id)) ? ' · 来源待更新' : ''}</p></article>)}{!!clarifications.length && <p className="rd-outcome-note">{clarifications.length} 条澄清仍需处理或复核。<button type="button" className="rd-link-button" onClick={() => onOpen('requirements')}>查看澄清 →</button></p>}</>}
      {stage.outcome === 'comparisons' && comparisons.slice(0, 4).map(record => <article className="rd-outcome-record" key={record.id}><div><h3>{record.title}</h3><span className="rd-badge">{record.kind === 'product' ? '产品比对' : '文档比对'}</span></div><p>人工逐项记录 · 修订 {record.revision}</p><dl className="rd-outcome-comparison"><div><dt>满足</dt><dd>{record.statistics.matches}</dd></div><div><dt>部分满足</dt><dd>{record.statistics.partial}</dd></div><div><dt>缺口</dt><dd>{record.statistics.gap}</dd></div><div><dt>未知</dt><dd>{record.statistics.unknown}</dd></div></dl><button type="button" className="rd-link-button" onClick={() => onOpen('routes')}>查看逐项依据与决策 →</button></article>)}
      {stage.outcome === 'routes' && <div className="rd-outcome-decisions">{([{ axis: 'product', title: '产品研制分类', record: researchCase.product_route }, { axis: 'composition', title: '任务书编制策略', record: researchCase.composition_route }]).map(item => <article className="rd-outcome-record" key={item.axis}><p className="rd-outcome-meta">{item.title}</p><h3>{item.record ? routeTitle(item.axis, item.record.value) : '尚未记录'}</h3>{item.record && <><p className="rd-prewrap">{item.record.rationale}</p><p className="rd-outcome-meta">{item.record.source_ids.length} 份依据 · {formatTime(item.record.created_at)}</p></>}</article>)}</div>}
      {(stage.outcome === 'artifacts' || stage.outcome === 'verification') && <>{stage.outcome === 'verification' && <p className="rd-outcome-note"><strong>{state.verification.label}</strong><span> · 业务确认另行记录</span></p>}{visibleArtifacts.slice(0, 5).map(({ artifact, workpackage }) => <article className="rd-outcome-record" key={`${workpackage.id}-${artifact.id}`}><div><h3><a href={artifactUrl(project.id, researchCase.id, workpackage.id, artifact.id)} target="_blank" rel="noreferrer">{artifact.name} · {lifecycle?.policy_version === 'v2' && !lifecycle.current_taskbook_scope_decision_id ? '下载复核稿' : '下载'} ↗</a></h3><span className="rd-badge">已登记成果</span></div><p>{workpackage.title} · {statusTitle(workpackage.status)}{workpackage.stage !== researchCase.stage ? ' · 上游成果' : ''}</p><button type="button" className="rd-link-button" onClick={() => onOpenWorkpackage(workpackage.id)}>查看对应执行与固定依据 →</button></article>)}{currentArtifacts.length > visibleArtifacts.length && <p className="rd-outcome-note">另有 {currentArtifacts.length - visibleArtifacts.length} 份执行过程记录。<button type="button" className="rd-link-button" onClick={() => onNavigate('artifacts')}>查看过程记录与依据 →</button></p>}{artifacts.some(item => !item.current || item.workpackage.status === 'cancelled') && <p className="rd-outcome-note">历史输入或已取消工作包的成果仍保留，使用前需核对。<button type="button" className="rd-link-button" onClick={() => onNavigate('artifacts')}>查看历史成果 →</button></p>}</>}
      {stage.outcome === 'delivery' && deliveries.slice(0, 4).map(record => <article className="rd-outcome-record" key={record.id}><div><h3>{record.recipient}</h3><span className="rd-badge">{record.outcome === 'accepted' ? '已登记接收' : '反馈要求修订'}</span></div><p className="rd-prewrap">{record.receipt}</p>{record.feedback && <p className="rd-prewrap">反馈：{record.feedback}</p>}<p className="rd-outcome-meta">人工交付登记 · {record.artifact_ids.length} 份关联成果 · {formatTime(record.created_at)}</p></article>)}
      {stage.outcome === 'reuse' && <>{candidates.slice(0, 4).map(record => <article className="rd-outcome-record" key={record.id}><div><h3>{record.title}</h3><span className="rd-badge">案例内候选 · 尚未发布</span></div><p className="rd-prewrap">{record.content}</p></article>)}{researchCase.reuse_disposition?.kind === 'not_publish' && <p className="rd-outcome-note">已登记不发布处置：{String(researchCase.reuse_disposition.reason ?? '')}</p>}</>}
    </div>
    <footer className="rd-outcome-footer"><div>{count > (['artifacts', 'verification'].includes(stage.outcome) ? 5 : 4) && <span className="rd-muted">当前显示部分记录，共 {count} 条。</span>}{manifest && <button type="button" className="rd-link-button" onClick={() => onOpen(stage.edit)}>{stage.editLabel} →</button>}<button type="button" className="rd-link-button" onClick={() => onNavigate('artifacts')}>查看全部成果与依据 →</button></div>{researchCase.status !== 'completed' && manifest && next?.target !== 'decision' && <button type="button" className="rd-link-button" onClick={() => onOpen('decision')}>本阶段业务确认 →</button>}</footer>
    {manifest && <details className="rd-outcome-tools"><summary>其他办理入口</summary><div>{manifest.surfaces.map(item => <button key={item.id} type="button" className="rd-link-button" onClick={() => onOpen(item.id)}>{item.label}</button>)}</div></details>}
  </section>;
}
