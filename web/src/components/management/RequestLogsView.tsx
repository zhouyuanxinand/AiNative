import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { listRequestLogs, readRequestLogs, RequestLogError, type RequestLogDetail, type RequestLogList, type RequestLogStatus } from '../../api/requestLogs';
import { StyledSelect } from '../ui/StyledSelect';
import { displayLogTime, LogRow, RuntimeLogsView } from './RuntimeLogsView';
import './requestLogs.css';

const statusLabels: Record<RequestLogStatus, string> = { running: '执行中', success: '成功', failed: '失败' };
const statusOptions = [{ value: '', label: '全部状态' }, ...Object.entries(statusLabels).map(([value, label]) => ({ value, label }))];
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : '日志服务暂不可用';

interface LogLocation { status: string; q: string; request: string; source: string }
function readLocation(): LogLocation {
  const params = new URLSearchParams(window.location.search);
  const status = params.get('log_status') || '';
  return {
    status: ['running', 'success', 'failed'].includes(status) ? status : '', q: (params.get('log_q') || '').slice(0, 300),
    request: params.get('log_request') || '', source: params.get('log_source') === 'service' ? 'service' : 'requests',
  };
}

function duration(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '—';
  if (value < 1000) return `${Math.round(value)} ms`;
  if (value < 60000) return `${(value / 1000).toFixed(1)} 秒`;
  const seconds = Math.round(value / 1000);
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

function RequestStatus({ value }: { value: RequestLogStatus }) {
  return <span className={`request-log-status is-${value}`}>{statusLabels[value] || value}</span>;
}

function RequestDetails({ requestId, active, autoRefresh, onBack }: { requestId: string; active: boolean; autoRefresh: boolean; onBack: () => void }) {
  const [data, setData] = useState<RequestLogDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [expired, setExpired] = useState(false);
  const dataRef = useRef(data);
  const requestRef = useRef<AbortController>();
  const title = useRef<HTMLHeadingElement>(null);
  dataRef.current = data;

  const loadNext = useCallback(async () => {
    if (requestRef.current || !active) return;
    const controller = new AbortController(); requestRef.current = controller;
    setBusy(true); setError('');
    try {
      const next = await readRequestLogs(requestId, dataRef.current?.next_cursor || 0, controller.signal);
      if (controller.signal.aborted) return;
      setData(previous => {
        const priorEntries = previous?.entries || [];
        const ids = new Set(priorEntries.map(entry => entry.id));
        return { ...next, entries: [...priorEntries, ...next.entries.filter(entry => !ids.has(entry.id))] };
      });
      setExpired(false);
    } catch (cause) {
      if (controller.signal.aborted) return;
      if (cause instanceof RequestLogError && cause.status === 404) {
        setExpired(true); setData(null);
      } else setError(errorText(cause));
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = undefined;
        setLoading(false); setBusy(false);
      }
    }
  }, [requestId, active]);

  useEffect(() => {
    if (!active) return;
    void loadNext();
    return () => { requestRef.current?.abort(); requestRef.current = undefined; };
  }, [active, loadNext]);
  useEffect(() => {
    if (!active || !autoRefresh || expired || data?.request.status !== 'running') return;
    const timer = window.setInterval(() => { void loadNext(); }, 5000);
    return () => window.clearInterval(timer);
  }, [active, autoRefresh, expired, data?.request.status, loadNext]);
  useEffect(() => { title.current?.focus(); }, [requestId]);

  const record = data?.request;
  const scopeLabels: Record<string, string> = { central_research: '中央研究院产品', non_central_research: '非中央研究院产品' };
  const deliveryLabels: Record<string, string> = { delivered: '已交付', blocked: '交付阻断', review_required: '待复核', cancelled: '已取消', error: '生成失败', failed: '生成失败' };
  return <div className="request-log-detail">
    <div className="request-detail-heading">
      <button type="button" className="request-log-button" onClick={onBack}>← 返回请求列表</button>
      <h3 ref={title} tabIndex={-1}>请求全过程</h3>
      {record && <RequestStatus value={record.status} />}
    </div>
    {expired ? <div className="request-log-state" role="status"><strong>这条请求记录已不存在</strong><p>完成记录超过保留数量后会自动清理最老记录。请返回列表查看现有请求。</p><button type="button" className="request-log-button" onClick={onBack}>返回现有请求</button></div> : <>
      {record && <>
        <dl className="request-log-metadata">
          {([
            ['用户', record.username || '未记录'], ['账号', record.userid || '未记录'],
            ['开始时间', displayLogTime(record.started_at)], ['结束时间', record.finished_at ? displayLogTime(record.finished_at) : '尚未结束'],
            ['耗时', duration(record.duration_ms)], ['产品类型 / 系列', [record.product_type, record.product_series].filter(Boolean).join(' / ') || '未记录'],
            ['模型', record.model || '未记录'], ['任务 ID', record.job_id || '未分配'],
            ['请求 ID', record.request_id], ['需求文件', record.files.tech || '未记录'],
            ['产品规范', record.files.spec || '未记录'], ['输出文件', record.files.output || '未生成'],
            ...([
              ['质量管理体系', record.product_domain], ['研制流程', record.development_process || record.process_classification],
              ['产品归属范围', scopeLabels[record.product_scope || ''] || record.product_scope], ['封面研制阶段', record.cover_stage],
              ['模型服务', record.model_provider], ['原任务 ID', record.parent_jid], ['交付状态', deliveryLabels[record.delivery_status || ''] || record.delivery_status],
            ] as Array<[string, string | undefined]>).filter((item): item is [string, string] => Boolean(item[1])),
          ] as Array<[string, string]>).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
        {record.error_summary && <div className="request-log-failure"><strong>失败原因</strong><p>{record.error_summary}</p></div>}
      </>}
      {error && <div className="runtime-log-error" role="alert"><div><strong>请求详情读取失败</strong><span>{error}。已读取的日志仍保留。</span></div><button type="button" onClick={() => void loadNext()}>重试读取</button></div>}
      {loading ? <div className="request-log-state" role="status">正在读取请求全过程…</div> : data && <>
        <div className="request-detail-progress"><p role="status">已显示 {data.entries.length} / {record!.event_count} 条日志{data.has_more ? ' · 还有后续记录' : record!.status === 'running' ? ' · 请求仍在执行' : ' · 已显示全部记录'}</p><button type="button" className="request-log-button" disabled={busy} onClick={() => void loadNext()}>{busy ? '正在读取…' : '刷新请求日志'}</button></div>
        {data.entries.length ? <div className="runtime-log-stream request-log-stream" tabIndex={0} aria-label="请求全过程日志"><div className="runtime-log-columns" aria-hidden="true"><span>时间</span><span>级别</span><span>日志内容</span></div><ol>{data.entries.map((entry, index) => <LogRow key={entry.id} entry={entry} index={index} />)}</ol></div> : <div className="request-log-state"><strong>本次请求暂无过程日志</strong><p>执行期间的新日志将在刷新后显示。</p></div>}
        {data.has_more && <div className="request-load-more"><button type="button" className="request-log-button is-primary" disabled={busy} onClick={() => void loadNext()}>{busy ? '正在读取…' : '加载后续日志'}</button><span>按时间顺序读取，不截断后续记录。</span></div>}
      </>}
    </>}
  </div>;
}

export function RequestLogsView({ active = true }: { active?: boolean }) {
  const [location, setLocation] = useState<LogLocation>(readLocation);
  const locationRef = useRef(location); locationRef.current = location;
  const [draft, setDraft] = useState({ status: location.status, q: location.q });
  const [data, setData] = useState<RequestLogList | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const requestRef = useRef<AbortController>();
  const searchInput = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [serviceVisited, setServiceVisited] = useState(location.source === 'service');
  const archivesActive = active && location.source === 'requests';
  const composing = useRef(false);

  function navigate(next: LogLocation) {
    const params = new URLSearchParams(window.location.search);
    for (const key of ['log_status', 'log_q', 'log_request', 'log_source']) params.delete(key);
    if (next.status) params.set('log_status', next.status);
    if (next.q) params.set('log_q', next.q);
    if (next.request) params.set('log_request', next.request);
    if (next.source === 'service') params.set('log_source', 'service');
    window.history.pushState(null, '', `${window.location.pathname}${params.size ? `?${params}` : ''}`);
    window.dispatchEvent(new Event('taskbook:admin-location'));
  }

  useEffect(() => {
    const onNavigate = () => {
      const next = readLocation();
      if (next.status !== locationRef.current.status || next.q !== locationRef.current.q) {
        setDraft({ status: next.status, q: next.q });
        setData(null); setLoading(true);
      }
      setLocation(next);
      if (next.source === 'service') setServiceVisited(true);
    };
    window.addEventListener('popstate', onNavigate);
    window.addEventListener('taskbook:admin-location', onNavigate);
    return () => {
      window.removeEventListener('popstate', onNavigate);
      window.removeEventListener('taskbook:admin-location', onNavigate);
    };
  }, []);

  const refresh = useCallback(async () => {
    if (requestRef.current || !archivesActive) return;
    const controller = new AbortController(); requestRef.current = controller;
    setBusy(true); setError('');
    try {
      const next = await listRequestLogs({ status: location.status, q: location.q }, controller.signal);
      if (!controller.signal.aborted) setData(next);
    } catch (cause) {
      if (!controller.signal.aborted) setError(errorText(cause));
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = undefined; setLoading(false); setBusy(false);
      }
    }
  }, [archivesActive, location.status, location.q]);

  useEffect(() => {
    if (!archivesActive) return;
    void refresh();
    return () => { requestRef.current?.abort(); requestRef.current = undefined; };
  }, [archivesActive, refresh]);
  useEffect(() => {
    if (!archivesActive || !autoRefresh) return;
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    return () => window.clearInterval(timer);
  }, [archivesActive, autoRefresh, refresh]);

  function search(event: FormEvent) {
    event.preventDefault();
    if (composing.current) return;
    navigate({ ...location, status: draft.status, q: draft.q.trim(), request: '' });
    if (draft.status === location.status && draft.q.trim() === location.q) void refresh();
  }
  function back() {
    const id = location.request;
    navigate({ ...location, request: '' });
    requestAnimationFrame(() => {
      const button = document.getElementById(`request-log-${id}`);
      if (button) button.focus(); else heading.current?.focus();
    });
  }

  return <div className="request-logs-view">
    <div className="request-log-modes" aria-label="日志来源"><button type="button" aria-pressed={location.source === 'requests'} onClick={() => navigate({ ...location, source: 'requests' })}>生成请求记录</button><button type="button" aria-pressed={location.source === 'service'} onClick={() => navigate({ ...location, source: 'service' })}>服务实时日志</button></div>
    <div hidden={location.source !== 'requests'}>
      <div className="request-log-overview"><div><h3 ref={heading} tabIndex={-1}>按完整生成请求归档</h3><p>最多保留 {data?.retention ?? 50} 条已完成请求，超过后自动删除最老记录及其过程日志；执行中的请求继续保留。</p></div><label className="runtime-auto-refresh"><input type="checkbox" role="switch" checked={autoRefresh} onChange={event => setAutoRefresh(event.target.checked)} /><span aria-hidden="true" />每 5 秒自动刷新</label></div>
      {location.request ? <RequestDetails key={location.request} requestId={location.request} active={archivesActive} autoRefresh={autoRefresh} onBack={back} /> : <>
        {data && <div className="request-log-counts" aria-label="当前留存请求统计"><span>全部 <strong>{data.stats.total}</strong></span><span>执行中 <strong>{data.stats.running}</strong></span><span>成功 <strong>{data.stats.success}</strong></span><span>失败 <strong>{data.stats.failed}</strong></span></div>}
        <form className="request-log-filters" noValidate onSubmit={search}>
          <div className="request-log-search"><label htmlFor="request-log-query">日志关键词</label><div><input id="request-log-query" ref={searchInput} value={draft.q} maxLength={300} placeholder="用户名、任务 ID、文件名或错误信息" onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} onChange={event => setDraft(previous => ({ ...previous, q: event.target.value }))} />{draft.q && <button type="button" aria-label="清除日志关键词" onClick={() => { setDraft(previous => ({ ...previous, q: '' })); navigate({ ...location, q: '', request: '' }); searchInput.current?.focus(); }}>×</button>}</div></div>
          <div><label id="request-log-status-label">请求状态</label><StyledSelect id="request-log-status" aria-labelledby="request-log-status-label" options={statusOptions} value={draft.status} onChange={status => setDraft(previous => ({ ...previous, status }))} /></div>
          <button type="submit" className="request-log-button is-primary">查询请求</button><button type="button" className="request-log-button" disabled={busy} onClick={() => void refresh()}>{busy ? '正在刷新…' : '刷新请求列表'}</button>
        </form>
        {error && <div className="runtime-log-error" role="alert"><div><strong>请求记录读取失败</strong><span>{error}{data ? '。当前显示上一次读取的记录。' : '。请检查服务状态后重试。'}</span></div><button type="button" onClick={() => void refresh()}>重试请求列表</button></div>}
        {loading ? <div className="request-log-state" role="status">正在读取请求记录…</div> : data && (data.items.length ? <>
          <p className="request-log-result-count" role="status">找到 {data.items.length} 条请求 · 时间为北京时间</p>
          <div className="request-log-table-wrap" tabIndex={0} role="region" aria-label="生成请求记录表格"><table className="request-log-table" aria-label="生成请求记录"><thead><tr><th>开始时间 / 耗时</th><th>用户</th><th>任务 / 文件</th><th>模型</th><th>结果</th><th>操作</th></tr></thead><tbody>{data.items.map(record => <tr key={record.request_id}>
            <td><time dateTime={record.started_at}>{displayLogTime(record.started_at)}</time><small>{duration(record.duration_ms)}</small></td><td>{record.username || '未记录'}<small>{record.userid || '账号未记录'}</small></td>
            <td className="request-log-task"><strong>{[record.product_type, record.product_series].filter(Boolean).join(' / ') || '研制任务书生成'}</strong><span>{record.files.tech || record.files.output || '文件未记录'}</span><small>{record.job_id || record.request_id}</small>{record.error_summary && <span className="request-log-error-summary" title={record.error_summary}>{record.error_summary}</span>}</td><td className="request-log-model">{record.model || '未记录'}</td><td><RequestStatus value={record.status} /></td><td><button id={`request-log-${record.request_id}`} type="button" className="request-log-button" aria-label={`查看请求 ${record.job_id || record.request_id}`} onClick={() => navigate({ ...location, request: record.request_id })}>查看全过程</button></td>
          </tr>)}</tbody></table></div>
        </> : <div className="request-log-state"><strong>{location.q || location.status ? '没有符合条件的请求' : '暂无生成请求记录'}</strong><p>{location.q || location.status ? '请调整关键词或状态后重新查询。' : '启用请求归档后，新提交的生成任务将在这里显示，包含各阶段日志与最终结果。'}</p>{(location.q || location.status) && <button type="button" className="request-log-button" onClick={() => navigate({ ...location, q: '', status: '' })}>清除筛选</button>}</div>)}
      </>}
    </div>
    {serviceVisited && <div hidden={location.source !== 'service'}><RuntimeLogsView active={active && location.source === 'service'} /></div>}
  </div>;
}
