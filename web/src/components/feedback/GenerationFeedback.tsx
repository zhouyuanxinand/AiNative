import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { FeedbackApiError, submitGenerationFeedback, type FeedbackRating, type FeedbackRecord } from '../../api/feedback';
import { useCurrentUser } from '../../hooks/useCurrentUser';
import { newFeedbackRequestId, ratingLabels } from './feedbackPresentation';
import '../../feedback.css';

export function GenerationFeedback({ jid }: { jid: string }) {
  return <FeedbackForm key={jid} jid={jid} />;
}

function FeedbackForm({ jid }: { jid: string }) {
  const { state: identity, retry: retryIdentity, requireLogin } = useCurrentUser();
  const isLocal = identity.status === 'ready' && !identity.identity.auth_enabled;
  const user = identity.status === 'ready' && identity.identity.authenticated ? identity.identity.user : null;
  const canSubmit = isLocal || !!user;
  const owner = isLocal ? 'local' : user ? `smartvision:${user.userid}` : null;
  const id = useId().replaceAll(':', '');
  const [username, setUsername] = useState('');
  const [rating, setRating] = useState<FeedbackRating | ''>('');
  const [comment, setComment] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [invalid, setInvalid] = useState(false);
  const [receipt, setReceipt] = useState<FeedbackRecord | null>(null);
  const [identityChanged, setIdentityChanged] = useState(false);
  const request = useRef<AbortController>();
  const active = useRef(true);
  const submitting = useRef(false);
  const usernameInput = useRef<HTMLInputElement>(null);
  const firstRating = useRef<HTMLInputElement>(null);
  const attempt = useRef<{ draft: string; requestId: string }>();
  const previousOwner = useRef<string>();
  const sessionExpired = useRef(false);

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; request.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!owner) return;
    if (sessionExpired.current) { setError(''); sessionExpired.current = false; }
    if (previousOwner.current && previousOwner.current !== owner) {
      request.current?.abort();
      submitting.current = false;
      setPending(false); setReceipt(null); setError(''); setInvalid(false);
      attempt.current = undefined;
      setIdentityChanged(true);
    }
    previousOwner.current = owner;
  }, [owner]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting.current || !canSubmit) return;
    if ((isLocal && !username.trim()) || !rating) {
      setInvalid(true);
      setError(isLocal && !username.trim() ? '请填写反馈用户名。' : '请选择生成效果评分。');
      if (isLocal && !username.trim()) usernameInput.current?.focus(); else firstRating.current?.focus();
      return;
    }
    const fields = { jid, ...(isLocal ? { username: username.trim() } : {}), rating, comment: comment.trim() };
    const draft = JSON.stringify({ owner, ...fields });
    if (attempt.current?.draft !== draft) attempt.current = { draft, requestId: newFeedbackRequestId() };
    const controller = new AbortController();
    request.current = controller;
    submitting.current = true;
    setPending(true); setError(''); setInvalid(false);
    try {
      const record = await submitGenerationFeedback({ ...fields, request_id: attempt.current.requestId }, controller.signal);
      if (active.current && !controller.signal.aborted && request.current === controller) setReceipt(record);
    } catch (reason) {
      if (active.current && !controller.signal.aborted && request.current === controller) {
        if (reason instanceof FeedbackApiError && reason.status === 401) {
          sessionExpired.current = true;
          requireLogin();
        }
        setError(reason instanceof Error ? reason.message : '提交结果未确认，请重试。');
      }
    } finally {
      if (active.current && request.current === controller) { submitting.current = false; setPending(false); }
    }
  }

  return <section className="generation-feedback" aria-labelledby={`${id}-title`}>
    <div className="feedback-inline-heading"><h3 id={`${id}-title`}>生成效果反馈</h3><span>帮助改进后续任务书</span></div>
    {receipt ? <div className="feedback-receipt" role="status">
      <div><strong>反馈已提交</strong><p>{receipt.username} · 评分：{ratingLabels[receipt.rating]} · 编号 #{receipt.id}</p></div>
      <button type="button" className="feedback-button" onClick={() => {
        setReceipt(null); setComment(''); setRating(''); setInvalid(false); setError(''); setIdentityChanged(false); attempt.current = undefined;
        requestAnimationFrame(() => { if (isLocal) usernameInput.current?.focus(); else firstRating.current?.focus(); });
      }}>再写一条反馈</button>
    </div> : <form className="feedback-inline-form" onSubmit={submit} noValidate aria-label="提交生成效果反馈">
      <div className="feedback-inline-controls">
        {isLocal ? <label className="feedback-user-label" htmlFor={`${id}-username`}>反馈用户名 <span className="feedback-required">*</span>
          <input ref={usernameInput} id={`${id}-username`} autoComplete="username" value={username} maxLength={80} required
            disabled={pending} aria-invalid={invalid && !username.trim()} aria-describedby={invalid && !username.trim() ? `${id}-error` : `${id}-local-mode`}
            placeholder="请输入您的姓名或工作昵称" onChange={event => setUsername(event.target.value)} />
          <span className="feedback-hint" id={`${id}-local-mode`}>本地模式，用户名由您填写</span>
        </label> : user ? <label className="feedback-user-label" htmlFor={`${id}-username`}>反馈用户名 <span className="feedback-optional">（统一登录）</span>
          <input id={`${id}-username`} value={user.display_name} readOnly title={user.display_name} aria-describedby={`${id}-account`} />
          <span className="feedback-identity-account" id={`${id}-account`}>账号：{user.userid}</span>
        </label> : <div className="feedback-identity-state" aria-live="polite">
          {identity.status === 'loading' ? <p role="status">正在读取登录身份…</p>
            : identity.status === 'error' ? <><p role="alert">{identity.error}</p><button className="feedback-link" type="button" onClick={retryIdentity}>重试读取身份</button></>
            : <><p>请先登录统一账号，再提交反馈。当前评分和意见会保留。</p><div className="feedback-identity-actions">
              <a className="feedback-link" href="/auth/login" target="_blank" rel="noopener noreferrer">前往统一登录</a>
              <button className="feedback-link" type="button" onClick={retryIdentity}>重新读取登录状态</button>
            </div><span className="feedback-hint">登录页在新标签页打开，完成后可回到这里继续。</span></>}
        </div>}
        <fieldset className="feedback-rating-field" disabled={pending} aria-describedby={invalid && !rating ? `${id}-error` : undefined}>
          <legend>生成效果评分 <span className="feedback-required">*</span></legend>
          <div className="feedback-ratings">{(Object.keys(ratingLabels) as FeedbackRating[]).map((value, index) =>
            <label key={value} className={`feedback-rating ${rating === value ? 'selected' : ''}`}>
              <input ref={index === 0 ? firstRating : undefined} type="radio" name={`${id}-rating`} value={value} checked={rating === value}
                required aria-invalid={invalid && !rating} onChange={() => setRating(value)} />
              <span>{ratingLabels[value]}</span>
            </label>)}</div>
        </fieldset>
      </div>
      {identityChanged && <p className="feedback-identity-notice" role="status">登录账号已更换，请确认后再提交当前意见。</p>}
      <label className="feedback-comment-label" htmlFor={`${id}-comment`}>意见与建议 <span className="feedback-optional">（选填）</span>
        <textarea className="feedback-textarea resize-none" id={`${id}-comment`} rows={2} value={comment} maxLength={4000} disabled={pending}
          placeholder="例如：内容准确性、缺失章节、格式问题或改进建议" onChange={event => setComment(event.target.value)} />
      </label>
      <div className="feedback-inline-footer"><span className="feedback-hint">{comment.length}/4000 字</span>
        <button className="feedback-button primary" type="submit" disabled={pending || !canSubmit}>{pending ? '正在提交…' : '提交反馈'}</button></div>
      {error && <p className="feedback-error" id={`${id}-error`} role="alert">{error}</p>}
    </form>}
  </section>;
}
