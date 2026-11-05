import { PlatformButton } from '../ui/PlatformButton';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { FeedbackApiError, getFeedback, saveFeedback, type FeedbackFields, type FeedbackIdentity, type FeedbackRating, type FeedbackRecord, type FeedbackSnapshot, type FeedbackStatus } from '../../api/feedback';
import { StyledSelect } from '../ui/StyledSelect';
import { FeedbackConfirmDialog, FeedbackDialog } from './FeedbackDialog';
import { feedbackError, feedbackIdentityLabel, feedbackTime, ratingLabels, ratingOptions, statusLabels, statusOptions } from './feedbackPresentation';
import { useAdminUnsavedChanges } from '../management/adminDrafts';

type Mode = 'view' | 'edit' | 'create';
type Draft = Omit<FeedbackFields, 'rating'> & { rating: FeedbackRating | ''; jid: string };
type LeaveAction = 'close' | 'view' | 'reload';
const emptyDraft = (): Draft => ({ username: '', rating: '', comment: '', status: 'open', handling_note: '', jid: '' });
const draftFor = (record: FeedbackRecord): Draft => ({ username: record.username, rating: record.rating, comment: record.comment,
  status: record.status, handling_note: record.handling_note, jid: record.snapshot.jid });

export function FeedbackRecordDialog({ id, initialMode, visible = true, onClose, onSaved, onDelete }: {
  id: number | null; initialMode: Mode; visible?: boolean; onClose: () => void;
  onSaved: (record: FeedbackRecord) => void; onDelete: (record: FeedbackRecord) => void;
}) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [record, setRecord] = useState<FeedbackRecord | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [baseline, setBaseline] = useState(() => JSON.stringify(emptyDraft()));
  const [loading, setLoading] = useState(id !== null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const [leave, setLeave] = useState<LeaveAction | null>(null);
  const request = useRef<AbortController>();
  const active = useRef(true);
  const mutationPending = useRef(false);
  const errorPanel = useRef<HTMLDivElement>(null);
  const dirty = mode !== 'view' && baseline !== JSON.stringify(draft);
  useAdminUnsavedChanges(dirty);

  function accept(result: FeedbackRecord) {
    const fields = draftFor(result);
    setRecord(result); setDraft(fields); setBaseline(JSON.stringify(fields)); setConflict(false); setInvalid(false);
  }

  async function load() {
    if (id === null && !record) return;
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setError('');
    try {
      const result = await getFeedback(record?.id ?? id!, controller.signal);
      if (active.current && !controller.signal.aborted) accept(result);
    } catch (reason) {
      if (active.current && !controller.signal.aborted) setError(feedbackError(reason));
    } finally { if (active.current && !controller.signal.aborted) setLoading(false); }
  }

  useEffect(() => {
    active.current = true;
    void load();
    return () => { active.current = false; request.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (error && visible) errorPanel.current?.focus();
  }, [error, visible]);

  function perform(action: LeaveAction) {
    setLeave(null);
    if (action === 'close') onClose();
    if (action === 'view' && record) { accept(record); setError(''); setMode('view'); }
    if (action === 'reload') void load();
  }

  function requestLeave(action: LeaveAction) {
    if (saving) return;
    if (dirty) setLeave(action); else perform(action);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (mutationPending.current) return;
    const missing = !draft.username.trim() ? 'feedback-editor-username' : !draft.rating ? 'feedback-editor-rating' : !draft.jid.trim() ? 'feedback-editor-jid' : '';
    if (missing) {
      setInvalid(true); setError('请补全反馈用户名、生成效果评分和关联任务 ID。');
      document.getElementById(missing)?.focus(); return;
    }
    mutationPending.current = true;
    const controller = new AbortController(); request.current = controller;
    setSaving(true); setError(''); setInvalid(false);
    const fields: FeedbackFields = { username: draft.username.trim(), rating: draft.rating as FeedbackRating, comment: draft.comment.trim(), status: draft.status, handling_note: draft.handling_note.trim() };
    try {
      const result = await saveFeedback(fields, record, draft.jid.trim(), controller.signal);
      if (active.current && !controller.signal.aborted) { accept(result); setMode('view'); onSaved(result); }
    } catch (reason) {
      if (active.current && !controller.signal.aborted) {
        setError(feedbackError(reason)); setConflict(reason instanceof FeedbackApiError && reason.status === 409);
      }
    } finally { if (active.current) { mutationPending.current = false; setSaving(false); } }
  }

  const change = <K extends keyof Draft>(name: K, value: Draft[K]) => { setDraft(previous => ({ ...previous, [name]: value })); setLeave(null); };
  const title = mode === 'create' ? '新增反馈' : mode === 'edit' ? '编辑反馈' : '反馈详情';
  return <>
    <FeedbackDialog title={title} visible={visible} className="feedback-record-dialog" onCancel={() => requestLeave('close')}>
      <button type="button" className="feedback-dialog-close" aria-label="关闭详情" disabled={saving} onClick={() => requestLeave('close')}>
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="m6 6 12 12M18 6 6 18"/></svg>
      </button>
      {record && <p className="feedback-record-meta">反馈 #{record.id} · 版本 {record.version} · 更新时间 {feedbackTime(record.updated_at)}</p>}
      {loading ? <div className="feedback-empty" role="status">正在读取反馈详情…</div> : <>
        {error && <div ref={errorPanel} tabIndex={-1} className="feedback-error" id="feedback-editor-error" role="alert"><p>{error}</p>
          {conflict ? <><p>您的修改已保留。请复制需要保留的内容，再读取最新版本后重新编辑。</p>
            <PlatformButton type="button" className="feedback-link" disabled={saving} onClick={() => requestLeave('reload')}>读取最新版本</PlatformButton></>
            : id !== null && !record && <PlatformButton type="button" className="feedback-link" onClick={() => void load()}>重试加载</PlatformButton>}
        </div>}
        {mode === 'view' && record ? <>
          <dl className="feedback-detail-grid"><div><dt>反馈用户名</dt><dd>{record.username}</dd></div>
            <div><dt>生成效果评分</dt><dd><span className={`feedback-badge rating-${record.rating}`}>{ratingLabels[record.rating]}</span></dd></div>
            <div><dt>提交时间（北京时间）</dt><dd>{feedbackTime(record.created_at)}</dd></div>
            <div><dt>处理状态</dt><dd><span className={`feedback-badge status-${record.status}`}>{statusLabels[record.status]}</span></dd></div>
          </dl>
          <FeedbackIdentityDetail identity={record.identity} />
          <section className="feedback-detail-section"><h3>意见与建议</h3><p className="feedback-full-text">{record.comment || '未填写意见。'}</p></section>
          <section className="feedback-detail-section"><h3>处理说明</h3><p className="feedback-full-text">{record.handling_note || '尚未填写处理说明。'}</p></section>
          <FeedbackSnapshotDetail snapshot={record.snapshot} />
          <div className="feedback-dialog-actions"><PlatformButton type="button" className="feedback-button danger" onClick={() => onDelete(record)}>删除反馈</PlatformButton>
            <PlatformButton type="button" className="feedback-button primary" onClick={() => { setMode('edit'); setError(''); }}>编辑反馈</PlatformButton></div>
        </> : (mode === 'create' || record) && <form className="feedback-editor" noValidate onSubmit={submit} aria-label="维护反馈记录">
          <fieldset disabled={saving}>
            {mode === 'create' ? <label className="feedback-editor-wide" htmlFor="feedback-editor-jid">关联任务 ID <span className="feedback-required">*</span>
              <input id="feedback-editor-jid" value={draft.jid} maxLength={200} required aria-invalid={invalid && !draft.jid.trim()}
                aria-describedby="feedback-editor-jid-hint" placeholder="填写现有生成任务的 ID" onChange={event => change('jid', event.target.value)} />
              <span id="feedback-editor-jid-hint" className="feedback-hint">保存时将关联该任务并保留提交时的任务信息。</span></label> :
              <p className="feedback-editor-wide feedback-immutable-note">关联任务：<span className="feedback-jid">{draft.jid}</span> · 提交时的任务信息保持只读。</p>}
            <label htmlFor="feedback-editor-username">反馈用户名 <span className="feedback-required">*</span>
              <input id="feedback-editor-username" required maxLength={80} value={draft.username} autoComplete="off"
                aria-invalid={invalid && !draft.username.trim()} aria-describedby={invalid && !draft.username.trim() ? 'feedback-editor-error' : undefined}
                onChange={event => change('username', event.target.value)} /></label>
            <div className="feedback-editor-field"><label id="feedback-editor-rating-label" htmlFor="feedback-editor-rating">生成效果评分 <span className="feedback-required">*</span></label>
              <StyledSelect id="feedback-editor-rating" aria-labelledby="feedback-editor-rating-label" required invalid={invalid && !draft.rating} value={draft.rating}
                options={[{ value: '', label: '请选择评分', disabled: true }, ...ratingOptions]} onChange={value => change('rating', value as FeedbackRating)} /></div>
            <label className="feedback-editor-wide" htmlFor="feedback-editor-comment">意见与建议 <span className="feedback-optional">（选填）</span>
              <textarea className="feedback-textarea resize-none" id="feedback-editor-comment" rows={5} maxLength={4000} value={draft.comment} onChange={event => change('comment', event.target.value)} />
              <span className="feedback-hint">{draft.comment.length}/4000 字</span></label>
            <div className="feedback-editor-field"><label id="feedback-editor-status-label" htmlFor="feedback-editor-status">处理状态</label>
              <StyledSelect id="feedback-editor-status" aria-labelledby="feedback-editor-status-label" value={draft.status} options={statusOptions}
                onChange={value => change('status', value as FeedbackStatus)} /></div>
            <label className="feedback-editor-wide" htmlFor="feedback-editor-note">处理说明 <span className="feedback-optional">（选填）</span>
              <textarea className="feedback-textarea resize-none" id="feedback-editor-note" rows={3} maxLength={4000} value={draft.handling_note} placeholder="记录问题核查情况与处理结果" onChange={event => change('handling_note', event.target.value)} /></label>
          </fieldset>
          {record && <><FeedbackIdentityDetail identity={record.identity} /><FeedbackSnapshotDetail snapshot={record.snapshot} /></>}
          <div className="feedback-dialog-actions"><PlatformButton type="button" className="feedback-button" disabled={saving} onClick={() => requestLeave(record ? 'view' : 'close')}>{record ? '取消编辑' : '取消'}</PlatformButton>
            <PlatformButton type="submit" className="feedback-button primary" disabled={saving}>{saving ? '正在保存…' : '保存反馈'}</PlatformButton></div>
        </form>}
      </>}
    </FeedbackDialog>
    {leave && <FeedbackConfirmDialog title={leave === 'reload' ? '读取最新版本' : '放弃未保存的修改'}
      visible={visible}
      confirm={leave === 'reload' ? '放弃修改并读取' : '放弃修改'} cancel="继续编辑" onCancel={() => setLeave(null)} onConfirm={() => perform(leave)}>
      <p>{leave === 'reload' ? '读取最新版本会替换当前表单中的修改。请先复制需要保留的内容。' : '当前修改尚未保存，放弃后无法恢复。'}</p>
    </FeedbackConfirmDialog>}
  </>;
}

function FeedbackIdentityDetail({ identity }: { identity?: FeedbackIdentity }) {
  return <section className="feedback-detail-section" aria-labelledby="feedback-original-identity-title">
    <div className="feedback-snapshot-heading"><h3 id="feedback-original-identity-title">提交时的身份</h3><span>只读</span></div>
    <dl className="feedback-detail-grid">
      <div><dt>身份来源</dt><dd>{feedbackIdentityLabel(identity)}</dd></div>
      <div><dt>原平台账号</dt><dd>{identity?.source === 'manual' ? '不适用（本地手填）' : identity?.userid || '未记录'}</dd></div>
      <div><dt>原姓名</dt><dd>{identity?.name || '未记录'}</dd></div>
    </dl>
    <p className="feedback-hint">原始身份保持只读；维护反馈用户名不会改变提交时的身份或验证状态。</p>
  </section>;
}

function FeedbackSnapshotDetail({ snapshot }: { snapshot: FeedbackSnapshot }) {
  const parameters = snapshot.parameters;
  const scope = parameters.organization_scope === 'central_research' ? '中央研究院产品' : parameters.organization_scope === 'non_central_research' ? '非中央研究院产品' : parameters.organization_scope;
  const jobStates: Record<string, string> = { done: '生成完成', blocked: '交付阻断', error: '生成失败', cancelled: '已取消', running: '生成中', pending: '等待中' };
  const deliveryStates: Record<string, string> = { delivered: '已交付', blocked: '交付阻断', review_required: '待复核', cancelled: '已取消', error: '生成失败' };
  const values: [string, string | undefined][] = [
    ['任务 ID', snapshot.jid], ['生成状态', jobStates[snapshot.job_status] || snapshot.job_status],
    ['产品类型', parameters.product_type_label || parameters.product_type], ['产品领域', parameters.product_domain_label || parameters.product_domain],
    ['开发流程', parameters.development_process], ['封面阶段', parameters.cover_phase], ['产品系列', parameters.product_series],
    ['组织范围', scope], ['模型提供方', parameters.model_provider], ['模型名称', parameters.model_name],
    ['模型 ID', parameters.model_id], ['使用模板', parameters.template_name],
    ['交付状态', deliveryStates[snapshot.delivery_status || ''] || snapshot.delivery_status],
    ['QA 结果', snapshot.qa_ok === true ? '通过' : snapshot.qa_ok === false ? '未通过' : '未提供'],
  ];
  return <section className="feedback-detail-section feedback-snapshot"><div className="feedback-snapshot-heading"><h3>提交时的任务信息</h3><span>只读</span></div>
    <dl className="feedback-detail-grid">{values.map(([label, value]) => <div key={label}><dt>{label}</dt><dd className={label === '任务 ID' || label === '模型 ID' ? 'feedback-jid' : undefined}>{value || '未填写'}</dd></div>)}</dl>
    <h4>关联文件</h4><dl className="feedback-snapshot-files">{([
      ['技术要求文件', snapshot.files.tech], ['产品规范文件', snapshot.files.spec], ['输出任务书', snapshot.files.output], ['质量报告', snapshot.files.report],
    ] as const).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || '无'}</dd></div>)}</dl>
    {snapshot.error && <div className="feedback-snapshot-error"><h4>生成错误信息</h4><p className="feedback-full-text">{snapshot.error}</p></div>}
  </section>;
}
