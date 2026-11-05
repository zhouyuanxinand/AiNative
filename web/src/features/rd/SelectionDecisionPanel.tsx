import { PlatformButton } from '../../components/ui/PlatformButton';
import { useEffect, useState } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { artifactUrl } from './api';
import { caseArtifactRecords, latestTaskbookPackage, summarizeCaseOutcome } from './caseOutcomeModel';
import { formatTime, isCurrentSource, routeTitle } from './presentation';
import type { Project, ResearchCase, ReviewBundle } from './types';
import type { CommandRunner } from './WorkpackagePanel';

function FixedReport({ bundle, researchCase }: { bundle: ReviewBundle; researchCase: ResearchCase }) {
  const report = bundle.report;
  const statistics = report?.statistics;
  return <article className="rd-section" aria-label="固定核对包">
    <div className="rd-section-head"><div><h3>{report?.title ?? '任务书范围核对包'}</h3><p>输入版 {bundle.input_revision} · {formatTime(bundle.created_at)}</p></div><span className="rd-badge">固定版本</span></div>
    {statistics && <dl className="rd-outcome-statuses"><div><dt>满足 / 总项数</dt><dd>{String(statistics.matches ?? 0)} / {String(statistics.total ?? 0)}</dd></div><div><dt>部分满足</dt><dd>{String(statistics.partial ?? 0)}</dd></div><div><dt>缺口 / 未知</dt><dd>{String(statistics.gap ?? 0)} / {String(statistics.unknown ?? 0)}</dd></div></dl>}
    {report && <p>产品研制分类：{routeTitle('product', String(report.product_route?.value ?? ''))}；任务书编制策略：{routeTitle('composition', String(report.composition_route?.value ?? ''))}</p>}
    {!!report?.rows?.length && <div className="rd-review-table" tabIndex={0} role="region" aria-label="选型逐项依据"><table><thead><tr><th>需求</th><th>产品证据</th><th className="rd-review-assessment">判断</th><th>依据</th></tr></thead><tbody>{report.rows.map((row, index) => <tr key={index}><td>{researchCase.requirements.find(item => item.id === row.requirement_id)?.title ?? String(row.requirement_id ?? '')}</td><td>{String(row.candidate_value ?? '')}</td><td className="rd-review-assessment">{{ match: '满足', partial: '部分满足', gap: '缺口', unknown: '未知' }[String(row.assessment)] ?? '待核对'}</td><td>{String(row.reason ?? '')}</td></tr>)}</tbody></table></div>}
    <details><summary>查看固定内容与来源版本</summary><pre className="rd-prewrap" style={{ overflowWrap: 'anywhere' }}>{JSON.stringify(bundle.fixed_objects ?? bundle.report, null, 2)}</pre></details>
    <p className="rd-muted rd-review-digest">核对包摘要：{bundle.digest}</p>
  </article>;
}

/** Business confirmation stays separate from autonomous package execution. */
export function SelectionDecisionPanel({ project, researchCase, busy, error, command, onDirtyChange }: {
  project: Project; researchCase: ResearchCase; busy: boolean; error: string;
  command: CommandRunner; onDirtyChange: (dirty: boolean) => void;
}) {
  const [scope, setScope] = useState('');
  const [reason, setReason] = useState('');
  const [validation, setValidation] = useState('');
  const [confirmation, setConfirmation] = useState<{ title: string; command: string; data: Record<string, unknown> } | null>(null);
  useEffect(() => { onDirtyChange(!!scope || !!reason); }, [scope, reason, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);
  const lifecycle = researchCase.business_lifecycle!;
  const requirements = ['input', 'requirements'].includes(researchCase.stage);
  const planning = researchCase.stage === 'planning';
  const bundle = [...(researchCase.review_bundles ?? [])].reverse().find(item => item.kind === (planning ? 'taskbook_scope' : 'selection') && !item.invalidated_at && item.input_revision === researchCase.input_revision);
  const decision = researchCase.decisions.find(item => item.id === lifecycle.current_selection_decision_id && item.verdict === 'approved' && !item.invalidated_at);
  const starting = !planning && !requirements && !!decision && researchCase.product_route?.value !== 'direct';
  const quality = summarizeCaseOutcome(researchCase);
  const latestPackage = latestTaskbookPackage(researchCase);
  const completedPackage = latestPackage?.status === 'completed' ? latestPackage : undefined;
  const canReview = lifecycle.can_record_decision === true;
  const canConfirmRequirements = lifecycle.can_confirm_requirements === true;
  const allowed = requirements ? canConfirmRequirements : canReview;
  const sources = researchCase.sources.filter(item => isCurrentSource(item, researchCase.source_selection));
  const readyForScope = !!completedPackage && quality.verification.kind === 'passed';
  function ask(name: string, title: string, data: Record<string, unknown>) {
    if (!scope.trim() || (!requirements && !reason.trim())) {
      setValidation(requirements ? '请填写此次确认的需求范围。' : '请填写本次决定范围与说明。');
      document.getElementById('rd-business-scope')?.focus(); return;
    }
    setValidation(''); setConfirmation({ title, command: name, data: { ...data, scope: scope.trim(), ...(!requirements ? { rationale: reason.trim() } : {}) } });
  }
  const act = (verdict: 'approved' | 'rejected') => {
    if (!bundle) return;
    ask(planning ? 'record_taskbook_scope_decision' : 'record_selection_decision', planning ? '确认任务书范围决定' : '确认选型报告决定', { bundle_id: bundle.id, bundle_digest: bundle.digest, verdict });
  };
  return <section className="rd-section rd-business-decision" aria-labelledby="rd-business-decision-title">
    <div className="rd-section-head"><div><span className="rd-eyebrow">业务关口</span><h3 id="rd-business-decision-title">{requirements ? '确认需求' : planning ? '任务书范围批准' : starting ? '研发启动' : '选型报告决定'}</h3><p>{requirements ? '固定当前采用的需求与来源，确认后进入选型。' : starting ? '选型报告已批准。本次单独记录研发启动范围，批准后进入策划。' : planning ? '核对本次任务书和质量结果；范围批准后才进入工程设计。' : '核对逐项证据和路线，保存具名决定。保存路线建议不会自动启动研发。'}</p></div></div>
    <p className="rd-notice">{lifecycle.local_review_enabled ? '本地负责人确认 · 非正式电子审签' : '企业正式审签政策尚未配置'} · 项目负责人：{project.owner_id}</p>
    {!allowed && <p className="rd-warning" role="status">{requirements ? '需求确认仅由项目负责人办理。' : lifecycle.local_review_enabled ? '当前用户没有项目负责人决定资格，可查阅证据。' : '正式决定政策尚未配置，当前不能办理批准或研发启动。'}</p>}
    {requirements ? <p>当前 {researchCase.requirements.length} 条需求，{sources.length} 份来源，输入版 {researchCase.input_revision}。来源变化后需重新确认。</p> : <>
      {bundle && <FixedReport bundle={bundle} researchCase={researchCase} />}
      {decision && !planning && <p className="rd-notice">已记录选型批准 · {decision.actor ?? decision.actor_id} · {formatTime(decision.created_at)}。{starting ? '研发启动仍待单独确认。' : '直接选用路线不创建研发工作包。'}</p>}
      {planning && <><ul>{caseArtifactRecords(researchCase).filter(item => item.current && item.workpackage.id === completedPackage?.id).map(({ artifact, workpackage }) => <li key={artifact.id}><a href={artifactUrl(project.id, researchCase.id, workpackage.id, artifact.id)} target="_blank" rel="noreferrer">{artifact.name} · 查看复核稿 ↗</a></li>)}</ul>{!readyForScope && <p className="rd-warning" role="status">任务书尚未完成或质量门禁未通过，请先在工作包中处理。现有文件可复核，不能据此批准范围。</p>}</>}
      {!starting && <PlatformButton type="button" className="rd-button" disabled={busy || (planning && !readyForScope)} onClick={() => void command(planning ? 'prepare_taskbook_scope_review' : 'prepare_selection_review', planning ? { workpackage_id: completedPackage?.id } : { expected_input_revision: researchCase.input_revision })}>{planning ? '形成任务书范围核对包' : bundle ? '重新生成固定选型报告' : '生成固定选型报告'}</PlatformButton>}
    </>}
    {(requirements || starting || !!bundle) && <div className="rd-review-fields">
      <div className="rd-field"><label htmlFor="rd-business-scope">{requirements ? '确认范围' : '决定范围'}</label><textarea id="rd-business-scope" rows={3} className="resize-none" value={scope} disabled={busy || !allowed} onChange={event => setScope(event.target.value)} /></div>
      {!requirements && <div className="rd-field"><label htmlFor="rd-business-reason">决定说明</label><textarea id="rd-business-reason" rows={3} className="resize-none" value={reason} disabled={busy || !allowed} onChange={event => setReason(event.target.value)} /></div>}
      {validation && <p className="rd-error" role="alert">{validation}</p>}
      <div className="rd-actions">
        {requirements ? <PlatformButton type="button" className="rd-button primary" disabled={busy || !allowed || !researchCase.requirements.length} onClick={() => ask('confirm_requirements', '确认当前需求基线', { expected_input_revision: researchCase.input_revision, source_ids: sources.map(item => item.id) })}>确认需求并进入选型</PlatformButton>
          : starting ? <PlatformButton type="button" className="rd-button primary" disabled={busy || !allowed} onClick={() => ask('authorize_rd_start', '确认研发启动范围', { selection_decision_id: decision?.id })}>确认研发启动</PlatformButton>
            : <><PlatformButton type="button" className="rd-button" disabled={busy || !allowed} onClick={() => act('rejected')}>{planning ? '退回任务书范围' : '退回选型报告'}</PlatformButton><PlatformButton type="button" className="rd-button primary" disabled={busy || !allowed || (planning && !readyForScope)} onClick={() => act('approved')}>{planning ? '批准任务书范围' : '批准选型报告'}</PlatformButton></>}
      </div>
    </div>}
    {confirmation && <FeedbackConfirmDialog title={confirmation.title} confirm="保存本地决定" pending={busy} error={error} onCancel={() => setConfirmation(null)} onConfirm={() => void command(confirmation.command, confirmation.data, () => { setConfirmation(null); setScope(''); setReason(''); })}><p>将按当前固定依据保存本次范围、说明、负责人和时间。本地确认不构成企业正式电子审签。</p><p className="rd-prewrap">{confirmation.data.scope as string}</p></FeedbackConfirmDialog>}
  </section>;
}
