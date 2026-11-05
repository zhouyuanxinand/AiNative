import { readable } from './presentation';
import './flowDesigner.css';
import './derivationExperience.css';
const STOP: Record<string, string> = { converged:'已收敛',no_new_evidence:'没有新证据',conflict:'证据冲突',max_rounds:'达到轮次上限',budget_exhausted:'预算耗尽',deadline_exceeded:'达到执行时限',cancelled:'已取消',permission_revoked:'授权已撤销',source_invalid:'来源失效' };
type Obligation = { obligation_key?: string; query?: unknown; accepted?: unknown[]; rejected?: Array<{ candidate?: unknown; fingerprint?: string; reason?: string }> };
type Round = { round?: number; obligations?: Obligation[]; eliminated?: unknown; remaining?: string[] };
function obligationTitle(item: Obligation | undefined, index: number) {
  const query = item?.query;
  if (query && typeof query === 'object' && 'title' in query && typeof query.title === 'string' && query.title.trim()) return query.title;
  return `待补项 ${index + 1}`;
}
export function CompletionEvidence({ session, title = '有限补缺 · 证据与停止原因' }: { session: Record<string, unknown>; title?: string }) {
  const usage = session.usage as Record<string, number> | undefined;
  const rounds = session.rounds as Round[] | undefined;
  const remaining = session.remaining as string[] | undefined;
  const obligations = rounds?.flatMap(round => round.obligations ?? []);
  const recordedCount = (key: 'accepted' | 'rejected') => rounds && rounds.every(round => Array.isArray(round.obligations) && round.obligations.every(item => Array.isArray(item[key]))) ? obligations?.reduce((sum, item) => sum + (item[key]?.length ?? 0), 0) ?? 0 : '未记录';
  const remainingTitle = (key: string, index: number) => obligationTitle(obligations?.slice().reverse().find(item => item.obligation_key === key), index);
  return <section className="rd-designer-review rd-completion-evidence" aria-label={title}>
    <div className="rd-section-head"><h4>{title}</h4><span className="rd-badge">{STOP[String(session.stop_reason)] || (session.stop_reason ? String(session.stop_reason) : '停止原因未记录')}</span></div>
    <div className="rd-completion-outcome">
      <p><strong>{remaining ? `本次待补项：${remaining.length} 项` : '本次待补项：未记录'}</strong></p>
      {!!remaining?.length && <ul>{remaining.slice(0, 3).map((key, index) => <li key={`${key}-${index}`}>{remainingTitle(key, index)}</li>)}</ul>}
      {remaining && remaining.length > 3 && <details className="rd-disclosure"><summary>查看全部待补项（{remaining.length} 项）</summary><ol className="rd-evidence-list" tabIndex={0} aria-label="全部待补项">{remaining.map((key, index) => <li key={`${key}-${index}`}>{remainingTitle(key, index)}</li>)}</ol></details>}
      <p className="rd-muted">来源缺失或冲突不会自动填入正式成果。下方可核对每轮接受与拒绝的依据。</p>
      <dl className="rd-completion-metrics" aria-label="补缺记录摘要"><div><dt>已保存轮次</dt><dd>{rounds?.length ?? '未记录'}</dd></div><div><dt>已接受记录</dt><dd>{recordedCount('accepted')}</dd></div><div><dt>已拒绝记录</dt><dd>{recordedCount('rejected')}</dd></div></dl>
    </div>
    <dl className="rd-completion-metrics" aria-label="补缺执行用量"><div><dt>查询</dt><dd>{usage?.queries ?? '未记录'}</dd></div>{usage?.local_checks !== undefined && <div><dt>本地核查</dt><dd>{usage.local_checks}</dd></div>}<div><dt>候选</dt><dd>{usage?.candidates ?? '未记录'}</dd></div><div><dt>模型调用</dt><dd>{usage?.model_calls ?? '未记录'}</dd></div><div><dt>耗时</dt><dd>{usage?.elapsed_seconds !== undefined ? `${usage.elapsed_seconds} 秒` : '未记录'}</dd></div></dl>
    {!rounds?.length && <p className="rd-empty-inline">尚无已保存轮次。</p>}
    {rounds?.map((round, index) => <details className="rd-completion-round" key={round.round ?? index}>
      <summary>第 {round.round ?? index + 1} 轮 · 剩余 {round.remaining?.length ?? '未记录'} 项待补</summary>
      <div className="rd-completion-records" tabIndex={0} role="region" aria-label={`第 ${round.round ?? index + 1} 轮核查记录`}>{round.obligations?.map((item, i) => <article key={item.obligation_key ?? i}>
        <h5>{obligationTitle(item, i)}</h5>
        <details className="rd-disclosure"><summary>查询、适用规则与原始标识</summary><pre>{readable({ obligation_key: item.obligation_key, query: item.query })}</pre></details>
        <details className="rd-disclosure"><summary>已接受引用 · {item.accepted?.length ?? '未记录'} 项</summary><pre>{readable(item.accepted)}</pre></details>
        <details className="rd-disclosure"><summary>已拒绝候选 · {item.rejected?.length ?? '未记录'} 项</summary>{item.rejected?.map((rejected, ri) => <div key={ri}><p className="rd-notice">拒绝原因：{rejected.reason || '见证据记录'}</p><pre>{readable(rejected.candidate)}</pre></div>)}</details>
      </article>)}</div>
      <p>本轮待补项：{round.remaining ? round.remaining.length ? `${round.remaining.length} 项` : '无' : '未记录'}</p>
      {!!round.remaining?.length && <details className="rd-disclosure"><summary>查看本轮待补项名称</summary><ol className="rd-evidence-list" tabIndex={0} aria-label="本轮待补项">{round.remaining.map((key, index) => <li key={`${key}-${index}`}>{remainingTitle(key, index)}</li>)}</ol></details>}
      <details className="rd-disclosure"><summary>本轮完整记录</summary><pre>{readable(round)}</pre></details>
    </details>)}
    <details className="rd-disclosure"><summary>固定来源、政策与提供者</summary><pre>{readable({ input_digest: session.input_digest, sources: session.sources, policy: session.policy, rule: session.rule, provider: session.provider, remaining: session.remaining })}</pre></details>
  </section>;
}
