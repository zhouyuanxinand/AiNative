import { useEffect, useRef, useState, type FormEvent } from 'react';
import { deleteFeedback, FeedbackApiError, listFeedback, type FeedbackFilters, type FeedbackPage, type FeedbackRecord } from '../../api/feedback';
import { StyledSelect } from '../ui/StyledSelect';
import { PlatformAuthSettings } from '../ui/PlatformAuthSettings';
import { FeedbackConfirmDialog } from './FeedbackDialog';
import { FeedbackRecordDialog } from './FeedbackRecordDialog';
import { feedbackError, feedbackIdentityLabel, feedbackTime, ratingLabels, ratingOptions, statusLabels, statusOptions } from './feedbackPresentation';
import '../../feedback.css';

const initialFilters: FeedbackFilters = { q: '', rating: '', status: '', date_from: '', date_to: '', page: 1, page_size: 20 };
const validDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;

function filtersFromURL(): FeedbackFilters {
  const params = new URLSearchParams(window.location.search);
  const rating = params.get('rating') || '';
  const status = params.get('status') || '';
  const page = Number(params.get('page') || 1);
  const pageSize = Number(params.get('page_size') || 20);
  return { q: (params.get('q') || '').slice(0, 500),
    rating: rating === 'good' || rating === 'average' || rating === 'poor' ? rating : '',
    status: status === 'open' || status === 'in_progress' || status === 'resolved' ? status : '',
    date_from: validDate(params.get('date_from') || '') ? params.get('date_from')! : '',
    date_to: validDate(params.get('date_to') || '') ? params.get('date_to')! : '',
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    page_size: [10, 20, 50].includes(pageSize) ? pageSize : 20 };
}

function filtersURL(filters: FeedbackFilters): string {
  const params = new URLSearchParams(window.location.search);
  for (const field of Object.keys(initialFilters)) params.delete(field);
  for (const field of ['q', 'rating', 'status', 'date_from', 'date_to'] as const) if (filters[field]) params.set(field, filters[field]);
  if (filters.page > 1) params.set('page', String(filters.page));
  if (filters.page_size !== 20) params.set('page_size', String(filters.page_size));
  return `${window.location.pathname}${params.size ? `?${params}` : ''}`;
}

export function FeedbackAdminPage({ embedded = false, visible = true }: { embedded?: boolean; visible?: boolean }) {
  const [filters, setFilters] = useState<FeedbackFilters>(filtersFromURL);
  const committedFilters = useRef(filters);
  committedFilters.current = filters;
  const [draft, setDraft] = useState<FeedbackFilters>(filtersFromURL);
  const [data, setData] = useState<FeedbackPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filterError, setFilterError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const [selection, setSelection] = useState<{ id: number | null; mode: 'view' | 'edit' | 'create' } | null>(null);
  const [remove, setRemove] = useState<FeedbackRecord | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const listRequest = useRef<AbortController>();
  const mutation = useRef<AbortController>();
  const listHeading = useRef<HTMLHeadingElement>(null);
  const deletionPending = useRef(false);
  const active = useRef(true);

  useEffect(() => {
    active.current = true;
    const title = document.title;
    if (!embedded) document.title = '问题反馈管理 · 研制任务书平台';
    const onPopState = () => {
      const next = filtersFromURL();
      if (JSON.stringify(committedFilters.current) === JSON.stringify(next)) return;
      listRequest.current?.abort(); setFilters(next); setDraft(next); setFilterError('');
    };
    window.addEventListener('popstate', onPopState);
    return () => {
      active.current = false; listRequest.current?.abort(); mutation.current?.abort();
      if (!embedded) document.title = title;
      window.removeEventListener('popstate', onPopState);
    };
  }, []);

  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController(); listRequest.current = controller;
    setLoading(true); setError(''); setData(null);
    listFeedback(filters, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      const pages = Math.max(1, Math.ceil(result.total / result.page_size));
      if (filters.page > pages) {
        const next = { ...filters, page: pages };
        window.history.replaceState(null, '', filtersURL(next)); setFilters(next); setDraft(next);
        window.dispatchEvent(new Event('taskbook:admin-location'));
      } else setData(result);
    }).catch(reason => { if (!controller.signal.aborted) setError(feedbackError(reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [filters, revision, visible]);

  function commit(next: FeedbackFilters) {
    listRequest.current?.abort();
    window.history.pushState(null, '', filtersURL(next));
    window.dispatchEvent(new Event('taskbook:admin-location'));
    setFilters(next); setDraft(next); setFilterError(''); setNotice('');
  }

  function search(event: FormEvent) {
    event.preventDefault();
    if ((draft.date_from && !validDate(draft.date_from)) || (draft.date_to && !validDate(draft.date_to))) {
      setFilterError('请填写有效日期。'); return;
    }
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) {
      setFilterError('开始日期不能晚于结束日期。'); document.getElementById('feedback-date-from')?.focus(); return;
    }
    commit({ ...draft, q: draft.q.trim(), page: 1 });
  }

  async function confirmDelete() {
    if (!remove || deletionPending.current) return;
    deletionPending.current = true; setDeleting(true); setDeleteError('');
    const controller = new AbortController(); mutation.current = controller;
    try {
      await deleteFeedback(remove, controller.signal);
      if (!active.current) return;
      setRemove(null); setSelection(null);
      setNotice(`反馈 #${remove.id} 已删除。`);
      setRevision(value => value + 1);
      requestAnimationFrame(() => listHeading.current?.focus());
    } catch (reason) {
      if (!controller.signal.aborted) setDeleteError(reason instanceof FeedbackApiError && reason.status === 409
        ? `${reason.message} 请取消删除并刷新列表，再查看最新内容。` : feedbackError(reason));
    } finally { if (active.current) { deletionPending.current = false; setDeleting(false); } }
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return <div className={`feedback-admin-page ${embedded ? 'feedback-admin-embedded' : ''}`}>
    {!embedded && <header className="feedback-page-header"><div className="feedback-page-brand">
      <span className="feedback-page-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M5 3h14v14H9l-4 4V3Z"/><path d="M9 7h6M9 11h6"/></svg></span>
      <div><h1>问题反馈管理</h1><p>研制任务书平台 · 生成效果与处理记录</p></div></div>
      <div className="auth-settings-admin-actions"><span className="feedback-timezone">北京时间 · UTC+8</span><PlatformAuthSettings /></div>
    </header>}
    <div className="feedback-page-main">
      <section className="feedback-overview" aria-labelledby="feedback-overview-title">
        <div className="feedback-section-heading"><div><h2 id="feedback-overview-title">反馈概况</h2><p>统计当前筛选范围内的全部记录</p></div>
          <button type="button" className="feedback-button primary" onClick={() => setSelection({ mode: 'create', id: null })}>新增反馈</button></div>
        <div className="feedback-statistics" aria-label="反馈统计" aria-busy={loading}>
          {([
            ['反馈总数', data?.stats.total], ['好', data?.stats.good], ['一般', data?.stats.average], ['差', data?.stats.poor],
            ['好评率', data ? `${(data.stats.good_rate * 100).toFixed(1)}%` : undefined],
          ] as const).map(([label, value]) => <div className="feedback-stat" key={label}><span>{label}</span><strong>{value ?? '—'}</strong></div>)}
        </div>
        <p className="feedback-status-summary">{data ? `待处理 ${data.stats.open} · 处理中 ${data.stats.in_progress} · 已解决 ${data.stats.resolved}` : loading ? '正在读取反馈统计…' : '反馈统计暂不可用，请重试加载。'}</p>
      </section>

      <section className="feedback-list-section" aria-labelledby="feedback-list-title">
        <div className="feedback-section-heading"><div><h2 ref={listHeading} tabIndex={-1} id="feedback-list-title">反馈记录</h2><p>查看反馈用户名、提交时的身份、任务参数与文件名。</p></div>
          <button type="button" className="feedback-button" disabled={loading} onClick={() => setRevision(value => value + 1)}>刷新列表</button></div>
        <form className="feedback-filter-form" noValidate onSubmit={search} aria-label="筛选反馈记录">
          <label className="feedback-filter-query" htmlFor="feedback-search">关键词<input id="feedback-search" type="search" maxLength={500} value={draft.q}
            placeholder="搜索用户名、意见、任务或产品" onChange={event => setDraft({ ...draft, q: event.target.value })} /></label>
          <div className="feedback-filter-field"><label id="feedback-rating-label" htmlFor="feedback-rating-filter">评分</label>
            <StyledSelect id="feedback-rating-filter" value={draft.rating} aria-labelledby="feedback-rating-label" options={[{ value: '', label: '全部评分' }, ...ratingOptions]}
              onChange={value => setDraft({ ...draft, rating: value as FeedbackFilters['rating'] })} /></div>
          <div className="feedback-filter-field"><label id="feedback-status-label" htmlFor="feedback-status-filter">处理状态</label>
            <StyledSelect id="feedback-status-filter" value={draft.status} aria-labelledby="feedback-status-label" options={[{ value: '', label: '全部状态' }, ...statusOptions]}
              onChange={value => setDraft({ ...draft, status: value as FeedbackFilters['status'] })} /></div>
          <label htmlFor="feedback-date-from">开始日期<input id="feedback-date-from" type="date" value={draft.date_from} max={draft.date_to || undefined}
            aria-invalid={Boolean(filterError)} aria-describedby={filterError ? 'feedback-filter-error' : undefined} onChange={event => setDraft({ ...draft, date_from: event.target.value })} /></label>
          <label htmlFor="feedback-date-to">结束日期<input id="feedback-date-to" type="date" value={draft.date_to} min={draft.date_from || undefined}
            onChange={event => setDraft({ ...draft, date_to: event.target.value })} /></label>
          <div className="feedback-filter-actions"><button type="submit" className="feedback-button primary">查询</button>
            <button type="button" className="feedback-button" onClick={() => commit({ ...initialFilters })}>重置</button></div>
          {filterError && <p id="feedback-filter-error" className="feedback-error feedback-filter-error" role="alert">{filterError}</p>}
        </form>
        {notice && <p className="feedback-notice" role="status">{notice}</p>}
        {error && <div className="feedback-error feedback-list-error" role="alert"><p>{error}</p><button type="button" className="feedback-link" onClick={() => setRevision(value => value + 1)}>重试加载</button></div>}
        {loading ? <div className="feedback-empty" role="status">正在读取反馈记录…</div> : !error && !data?.items.length ?
          <div className="feedback-empty"><strong>没有找到反馈记录。</strong><p>可调整筛选条件，或通过“新增反馈”补录已完成任务的意见。</p></div> : data && <>
          <div className="feedback-table-scroll" role="region" aria-label="反馈记录表格，可横向滚动" tabIndex={0}>
            <table className="feedback-table" aria-label="生成效果反馈列表"><thead><tr>
              {['反馈时间 / 用户', '评分与意见', '任务 ID', '产品 / 系列', '文件名', '处理状态', '操作'].map(label => <th scope="col" key={label}>{label}</th>)}
            </tr></thead><tbody>{data.items.map(record => <tr key={record.id}>
              <td><time dateTime={record.created_at}>{feedbackTime(record.created_at)}</time><strong className="feedback-table-user">{record.username}</strong>
                <span className="feedback-cell-meta">{feedbackIdentityLabel(record.identity)}</span>
                {record.identity?.source === 'smartvision' && record.identity.userid && <span className="feedback-cell-meta">平台账号：{record.identity.userid}</span>}
                <span className="feedback-cell-meta">#{record.id}</span></td>
              <td><span className={`feedback-badge rating-${record.rating}`}>{ratingLabels[record.rating]}</span><p className="feedback-excerpt">{record.comment || '未填写意见'}</p></td>
              <td><span className="feedback-jid">{record.snapshot.jid}</span></td>
              <td><strong>{record.snapshot.parameters.product_type_label || record.snapshot.parameters.product_type || '未指定产品'}</strong><span className="feedback-cell-meta">{record.snapshot.parameters.product_series || '未填写系列'}</span></td>
              <td className="feedback-file-cell">{record.snapshot.files.output || record.snapshot.files.tech || '未生成输出文件'}</td>
              <td><span className={`feedback-badge status-${record.status}`}>{statusLabels[record.status]}</span></td>
              <td><div className="feedback-row-actions"><button type="button" className="feedback-link" aria-label={`查看反馈 ${record.id}`} onClick={() => setSelection({ id: record.id, mode: 'view' })}>查看</button>
                <button type="button" className="feedback-link" aria-label={`编辑反馈 ${record.id}`} onClick={() => setSelection({ id: record.id, mode: 'edit' })}>编辑</button>
                <button type="button" className="feedback-link danger-text" aria-label={`删除反馈 ${record.id}`} onClick={() => { setDeleteError(''); setRemove(record); }}>删除</button></div></td>
            </tr>)}</tbody></table>
          </div>
          <nav className="feedback-pagination" aria-label="反馈记录分页"><span>共 {data.total} 条 · 第 {filters.page} / {pages} 页</span>
            <div className="feedback-pagination-controls"><StyledSelect aria-label="每页反馈条数" value={String(filters.page_size)} options={[10, 20, 50].map(value => ({ value: String(value), label: `${value} 条 / 页` }))}
              onChange={value => commit({ ...filters, page: 1, page_size: Number(value) })} />
              <button type="button" className="feedback-button" disabled={filters.page <= 1} onClick={() => commit({ ...filters, page: filters.page - 1 })}>上一页</button>
              <button type="button" className="feedback-button" disabled={filters.page >= pages} onClick={() => commit({ ...filters, page: filters.page + 1 })}>下一页</button></div>
          </nav>
        </>}
      </section>
    </div>
    {selection && <FeedbackRecordDialog key={`${selection.mode}-${selection.id ?? 'new'}`} id={selection.id} initialMode={selection.mode}
      visible={visible}
      onClose={() => setSelection(null)} onSaved={record => { setNotice(`反馈 #${record.id} 已保存。`); setRevision(value => value + 1); }}
      onDelete={record => { setDeleteError(''); setRemove(record); }} />}
    {remove && <FeedbackConfirmDialog title="删除反馈" visible={visible} danger confirm="确认删除" pending={deleting} error={deleteError}
      onCancel={() => setRemove(null)} onConfirm={() => void confirmDelete()}>
      <p>确认删除 {remove.username} 提交的反馈 #{remove.id}？</p><p>评分：{ratingLabels[remove.rating]}。删除后无法恢复。</p>
    </FeedbackConfirmDialog>}
  </div>;
}
