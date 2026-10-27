import { useEffect, useState } from 'react';
import { clarifyIndicators, getIndicatorReview } from '../../api/jobs';
import type { IndicatorCandidate, IndicatorReview } from '../../types';
import { useApplicationLeaveGuard } from '../../hooks/useApplicationLeaveGuard';

const comparisonLabels: Record<string, string> = {
  STANDARD_STRICTER: '规范值更严格', USER_STRICTER: '用户值更严格',
  EQUIVALENT: '数值等效', EQUAL: '数值相同', USER_ONLY: '仅用户指标',
  STANDARD_ONLY: '仅规范指标', MANUAL_REVIEW_REQUIRED: '数值待复核',
  INCOMPARABLE: '不可直接比较',
  stricter_standard: '规范值更严格', stricter_user: '用户值更严格',
  equal: '数值等效', user_only: '仅用户指标', standard_only: '仅规范指标',
  empty: '未给出指标值', manual_review: '数值待复核',
};

function Candidate({ item }: { item: IndicatorCandidate }) {
  const scope = [item.scope, ...Object.entries(item.qualifiers || {}).map(([key, value]) => `${key}：${value}`), item.condition].filter(Boolean).join('；');
  return (
    <li>
      <div>{item.display_value || item.value || '未识别到规范数值'}</div>
      {scope && <div className="indicator-review-note">{scope}</div>}
      <div className="indicator-review-note">
        {item.value_kind === 'typ' ? '典型值，仅供参考' : comparisonLabels[item.comparison_status || ''] || item.comparison_status || '待比对'}
        {item.comparison_note ? ` · ${item.comparison_note}` : ''}
      </div>
    </li>
  );
}

export function IndicatorReviewPanel({ jid }: { jid: string }) {
  const [review, setReview] = useState<IndicatorReview | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [reload, setReload] = useState(0);
  useApplicationLeaveGuard({ dirty: Object.values(values).some(value => value.trim()),
    busyMessage: submitting ? '复核任务正在创建，请完成后再退出登录。' : undefined });
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    setReview(null);
    setValues({});
    getIndicatorReview(jid).then((data) => {
      if (active) setReview(data);
    }).catch((cause: Error) => active && setError(cause.message)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [jid, reload]);

  async function submit() {
    const clarifications = Object.fromEntries(Object.entries(values).filter(([, value]) => value.trim()));
    if (!Object.keys(clarifications).length) return;
    setSubmitting(true);
    setError('');
    try {
      const result = await clarifyIndicators(jid, clarifications);
      window.dispatchEvent(new CustomEvent('taskbook:replay-started', { detail: { jid: result.jid } }));
    } catch (cause) {
      setError((cause as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <section className="indicator-review" aria-labelledby="indicator-review-title">
      <h3 id="indicator-review-title">指标比对与澄清</h3>
      {loading && <p role="status">正在读取指标比对记录…</p>}
      {error && <p role="alert" className="indicator-review-error">{error} {!review && <button type="button" onClick={() => setReload((count) => count + 1)}>重新读取</button>}</p>}
      {review && <>
        {review.parent_jid && <p className="indicator-review-note">根据任务 {review.parent_jid} 的补充信息重新比对，原任务仍保留。</p>}
        {review.manual_review_required.length > 0 ? <>
          <p>以下 {review.manual_review_required.length} 项仍待澄清。补充适用信息后，将使用原文件创建新任务并重新比对。</p>
          {review.manual_review_required.map((decision, index) => (
            <div className="indicator-review-item" key={decision.indicator_name}>
              <h4>{decision.indicator_name} <span className="indicator-review-pending">待澄清</span></h4>
              <dl>
                <dt>用户原指标</dt><dd>{decision.user_requirement || '原文未明确指标值'}</dd>
                <dt>待澄清原因</dt><dd>{decision.reason || decision.status}</dd>
                <dt>规范各档指标</dt><dd><ul>{(decision.candidate_comparisons || []).map((candidate, candidateIndex) => <Candidate key={candidateIndex} item={candidate} />)}</ul>{!decision.candidate_comparisons?.length && '未找到可用规范候选'}</dd>
              </dl>
              {review.indicator_clarifications[decision.indicator_name] && <p className="indicator-review-note">上次补充：{review.indicator_clarifications[decision.indicator_name]}（仍未解决）</p>}
              <label htmlFor={`indicator-clarification-${index}`}>补充适用规格、档位、型号或测试条件</label>
              <textarea id={`indicator-clarification-${index}`} rows={2} maxLength={500} disabled={submitting || !review.can_clarify} value={values[decision.indicator_name] || ''} onChange={(event) => setValues((current) => ({ ...current, [decision.indicator_name]: event.target.value }))} placeholder="例如：规格：#22D；条件：常温" aria-describedby="indicator-clarification-help" />
            </div>
          ))}
          <p id="indicator-clarification-help" className="indicator-review-note">格式为“字段：适用信息”，多项用分号分隔。指标数值沿用原文件，重新生成后仍需完成结果审核。</p>
          {review.unavailable_reason && <p className="indicator-review-note">{review.unavailable_reason}</p>}
          <button type="button" className="btn-progress-reset" disabled={submitting || !review.can_clarify || !Object.values(values).some((value) => value.trim())} onClick={submit}>{submitting ? '正在创建复核任务…' : '提交补充信息并重新生成'}</button>
        </> : <p>本次指标比对没有待澄清项。其他检查结果请查看交付状态。</p>}
        {review.comparison_decisions.some((item) => !item.manual_review_required) && <details className="indicator-review-resolved"><summary>查看其他指标比对（{review.comparison_decisions.filter((item) => !item.manual_review_required).length} 项）</summary>{review.comparison_decisions.filter((item) => !item.manual_review_required).map((item) => <div key={item.indicator_name}><strong>{item.indicator_name}</strong><p>用户原指标：{item.user_requirement || '未明确'}；拟采用：{item.adopted_requirement || '未填写'}</p><ul>{(item.candidate_comparisons || []).map((candidate, index) => <Candidate item={candidate} key={index} />)}</ul></div>)}</details>}
      </>}
    </section>
  );
}
