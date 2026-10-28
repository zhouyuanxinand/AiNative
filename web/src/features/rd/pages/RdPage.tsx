import { useCallback, useEffect, useRef, useState } from 'react';
import { useCurrentUser } from '../../../shared/auth/useCurrentUser';
import { navigateAfterConfirmedLeave, useApplicationLeaveGuard } from '../../../shared/hooks/useApplicationLeaveGuard';
import { createRdProject, getRdProject, listRdProjects, type RdDetail, type RdProjectPage } from '../api/rd';
import { FeedbackConfirmDialog } from '../../../shared/ui/FeedbackDialog';
import { RdDraftContext, RdError, RdField, RdOperation, RdPager, rdLabel, rdTime } from '../components/RdControls';
import { RdWorkbench } from '../components/RdWorkbench';
import '../../../shared/styles/feedback.css';
import '../components/rd.css';

export function RdPage({ projectId }: { projectId?: string }) { return <RdIdentityGate projectId={projectId} />; }
function RdIdentityGate({ projectId }: { projectId?: string }) {
  const { state, retry } = useCurrentUser();
  useEffect(() => { document.title = '研发项目 · 研发管理平台'; }, []);
  if (state.status === 'ready' && state.identity.authenticated) return <RdWorkspace key={state.identity.user.userid} projectId={projectId} />;
  return <div className="rd-page"><div className="rd-main"><section className="rd-panel rd-gate"><h1>项目空间</h1>{state.status === 'loading' ? <p role="status">正在验证登录身份…</p> : state.status === 'error' ? <RdError error={new Error(state.error)} retry={retry} /> : !state.identity.auth_enabled ? <><h2>请先启用统一登录</h2><p>项目、任务与审签需要服务端验证的企业身份。请由管理员配置统一登录并重启服务，再返回此页面。</p><a className="feedback-button" href="/">返回研发总览</a></> : <><h2>请登录后进入研发项目</h2><p>登录完成后，点击“重新验证身份”继续。</p><div className="rd-actions"><a className="feedback-button primary" href="/auth/login" target="_blank" rel="noopener noreferrer">前往统一登录</a><button type="button" className="feedback-button" onClick={retry}>重新验证身份</button></div></>}</section></div></div>;
}
function RdWorkspace({ projectId }: { projectId?: string }) {
  const [drafts, setDrafts] = useState<Record<string, boolean>>({}), [destination, setDestination] = useState<string | null>(null);
  const reportDraft = useCallback((id: string, dirty: boolean) => setDrafts(previous => previous[id] === dirty ? previous : { ...previous, [id]: dirty }), []);
  const dirty = Object.values(drafts).some(Boolean);
  useApplicationLeaveGuard({ dirty });
  useEffect(() => {
    const intercept = (event: MouseEvent) => {
      if (!dirty || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      const link = (event.target as Element).closest<HTMLAnchorElement>('a[href]');
      if (!link || link.target === '_blank' || link.hasAttribute('download') || link.pathname === location.pathname && link.search === location.search) return;
      event.preventDefault(); setDestination(link.href);
    };
    document.addEventListener('click', intercept); return () => document.removeEventListener('click', intercept);
  }, [dirty]);
  return <RdDraftContext.Provider value={reportDraft}><div className="rd-page"><div className="rd-main">{projectId ? <RdProjectDetail key={projectId} projectId={projectId} /> : <RdProjectList />}</div></div>{destination && <FeedbackConfirmDialog title="离开当前项目？" confirm="放弃修改并离开" cancel="继续编辑" onCancel={() => setDestination(null)} onConfirm={() => navigateAfterConfirmedLeave(destination)}><p>当前有未保存的输入或正在处理的操作。离开后未保存的输入会丢失，请先核对操作结果。</p></FeedbackConfirmDialog>}</RdDraftContext.Provider>;
}
function readListState() { const params = new URLSearchParams(location.search); return { q: params.get('q') || '', page: Math.max(1, Number(params.get('page')) || 1), size: [10, 20, 50].includes(Number(params.get('page_size'))) ? Number(params.get('page_size')) : 20 }; }
function RdProjectList() {
  const [filters, setFilters] = useState(readListState), [query, setQuery] = useState(filters.q), [data, setData] = useState<RdProjectPage | null>(null), [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [reload, setReload] = useState(0), [creating, setCreating] = useState(false);
  const input = useRef<HTMLInputElement>(null), composing = useRef(false);
  const [fields, setFields] = useState({ name: '', code: '', customer: '', product: '' });
  const [createdProject, setCreatedProject] = useState<{ id: string; name: string } | null>(null);
  const change = (name: keyof typeof fields) => (value: string) => setFields(previous => ({ ...previous, [name]: value }));
  const navigate = (next: typeof filters) => { const url = new URL(location.href); for (const [key, value] of Object.entries({ q: next.q, page: next.page, page_size: next.size })) url.searchParams.set(key, String(value)); history.pushState(null, '', url); setFilters(next); };
  useEffect(() => { const restore = () => { const next = readListState(); setFilters(next); setQuery(next.q); }; window.addEventListener('popstate', restore); return () => window.removeEventListener('popstate', restore); }, []);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(null);
    void listRdProjects(filters.q, filters.page, filters.size, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      const max = Math.max(1, Math.ceil(result.total / filters.size));
      if (filters.page > max) { navigate({ ...filters, page: max }); return; }
      setData(result);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [filters.q, filters.page, filters.size, reload]);
  return <><div className="rd-title-row"><div><p className="rd-eyebrow">需求 / 选型 / 研发 / 验证 / 交付</p><h1>项目空间</h1><p className="rd-muted">从需求与选型开始，持续跟踪改型、新研及直接选用的责任与成果。</p></div><button className="feedback-button primary" type="button" onClick={() => setCreating(value => !value)} aria-expanded={creating}>{creating ? '收起建档' : '新建业务空间'}</button></div>
    <section className="rd-panel" hidden={!creating}><h2>业务空间建档</h2><p className="rd-muted">先登记客户与产品，随后确认需求和选型路线。改型或新研另行记录启动授权。</p><RdOperation label="创建业务空间" dirty={Object.values(fields).some(Boolean)} fingerprint={JSON.stringify(fields)} execute={async key => { const result = await createRdProject(fields, key); setFields({ name: '', code: '', customer: '', product: '' }); setCreating(false); setReload(value => value + 1); setQuery(''); navigate({ q: '', page: 1, size: filters.size }); setCreated(result); }}><div className="rd-fields"><RdField label="项目名称" required value={fields.name} onChange={change('name')} /><RdField label="项目编号（选填）" value={fields.code} onChange={change('code')} /><RdField label="客户" required value={fields.customer} onChange={change('customer')} /><RdField label="产品" required value={fields.product} onChange={change('product')} /></div></RdOperation></section>
    {createdProject && <p className="feedback-notice" role="status">项目“{createdProject.name}”已创建。<a href={`/rd/${encodeURIComponent(createdProject.id)}`}>进入项目空间</a></p>}
    <section className="rd-panel"><form noValidate className="rd-list-filter" onSubmit={event => { event.preventDefault(); if (!composing.current) navigate({ ...filters, q: query.trim(), page: 1 }); }}><label htmlFor="rd-project-query">项目名称 / 编号</label><div className="rd-search"><input id="rd-project-query" ref={input} value={query} onChange={event => setQuery(event.target.value)} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} />{query && <button type="button" className="feedback-link" aria-label="清除项目关键词" onClick={() => { setQuery(''); navigate({ ...filters, q: '', page: 1 }); input.current?.focus(); }}>清除</button>}</div><button type="submit" className="feedback-button">查询</button><RdField label="每页条数" value={String(filters.size)} options={[10, 20, 50].map(value => ({ value: String(value), label: `${value} 条` }))} onChange={value => navigate({ ...filters, size: Number(value), page: 1 })} /></form>
      {error !== null && <RdError error={error} retry={() => setReload(value => value + 1)} />}<div className="rd-table-region" role="region" aria-label="项目空间列表" tabIndex={0} aria-busy={loading}><table><thead><tr><th>项目</th><th>客户 / 产品</th><th>当前职责</th><th>需求基线</th><th>建档时间</th></tr></thead><tbody>{loading ? <tr><td colSpan={5} className="rd-empty" role="status">正在读取项目…</td></tr> : data?.items.length ? data.items.map(project => <tr key={project.id}><td><a className="rd-project-name" href={`/rd/${encodeURIComponent(project.id)}`}>{project.name}</a><small className="rd-mono">{project.code || project.id}</small></td><td>{project.customer}<small>{project.product}</small></td><td>{rdLabel(project.role)}</td><td>{project.current_baseline_id ? '已确认基线' : '待确认'}</td><td>{rdTime(project.created_at)}</td></tr>) : <tr><td colSpan={5} className="rd-empty">{filters.q ? '没有匹配的项目。清除关键词后重试。' : '暂无可访问的项目。创建项目后登记需求与成员。'}</td></tr>}</tbody></table></div><RdPager page={filters.page} total={data?.total || 0} size={filters.size} onChange={page => navigate({ ...filters, page })} /></section></>;
  // The receipt stays on the owning list, keeping navigation explicit.
  function setCreated(result: RdDetail) { setCreatedProject({ id: result.project.id, name: result.project.name }); }
}

function RdProjectDetail({ projectId }: { projectId: string }) {
  const [detail, setDetail] = useState<RdDetail | null>(null), [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [reload, setReload] = useState(0);
  useEffect(() => { const controller = new AbortController(); setLoading(true); setError(null); void getRdProject(projectId, controller.signal).then(result => { if (!controller.signal.aborted) setDetail(result); }).catch(reason => { if (!controller.signal.aborted) setError(reason); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); return () => controller.abort(); }, [projectId, reload]);
  useEffect(() => { document.title = `${detail?.project.name || '项目工作区'} · 研发项目`; }, [detail?.project.name]);
  const fatal = error instanceof Error && 'status' in error && [401, 403, 404].includes(Number(error.status));
  return <><a className="rd-back" href="/rd">← 项目列表</a>{error !== null && <RdError error={error} retry={() => setReload(value => value + 1)} />}{loading && <div className="rd-loading" role="status">正在读取项目最新版本…</div>}{detail && !fatal && <RdWorkbench detail={detail} onChange={setDetail} onReload={() => setReload(value => value + 1)} loading={loading} />}{!detail && !loading && error === null && <p>项目不可用。</p>}</>;
}
