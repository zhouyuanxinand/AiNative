import { useCallback, useEffect, useRef, useState } from 'react';
import {
  loadLatestRuntimeLogs,
  type RuntimeLogEntry,
  type RuntimeLogSnapshot,
} from '../api/runtimeLogs';
import './runtimeLogs.css';

const LOG_LIMIT = 200;
const REFRESH_INTERVAL_MS = 5000;
const CONTEXT_LABELS: Partial<Record<keyof RuntimeLogEntry, string>> = {
  event: '事件', job_id: '任务 ID', jid: '任务 ID', stage: '阶段', stage_code: '阶段代码', status: '状态',
  product_type: '产品类型', product_domain: '产品领域', development_process: '研制流程',
  process_classification: '研制流程', model_provider: '模型服务', provider: '模型服务',
  model: '模型', model_id: '模型 ID', operation: '操作',
  attempt: '尝试次数', max_attempts: '最大尝试', retry_delay_ms: '重试等待',
  error_type: '错误类型', finish_reason: '结束原因', completion_tokens: '输出 Token',
  reasoning_tokens: '推理 Token', content_chars: '响应字符数', warning_count: '警告数',
  requirement_source_count: '需求来源数', semantic_decision_count: '语义决策数',
  has_artifact: '已有产物', error_summary: '错误摘要', submission_kind: '提交方式',
  input_role: '输入角色', previous_status: '原状态', parent_jid: '父任务 ID',
  delivery_status: '交付状态', qa_ok: '质量门禁', method: '方法', path: '路径',
  status_code: '状态码', duration_ms: '耗时', type: '类型',
};
const CONTEXT_ORDER = Object.keys(CONTEXT_LABELS) as Array<keyof RuntimeLogEntry>;
const RESERVED_FIELDS = new Set([
  'timestamp', 'level', 'logger', 'message', 'correlation_id', 'exception',
]);

function displayContextValue(key: string, value: unknown) {
  let text: string;
  if (typeof value === 'string') text = value;
  else if (value === null || value === undefined) text = '';
  else if (typeof value === 'object') {
    try { text = JSON.stringify(value); } catch { text = String(value); }
  } else text = String(value);
  if (key === 'duration_ms' || key === 'retry_delay_ms') return `${text} ms`;
  return text;
}

export function displayLogTime(value?: string | null) {
  if (!value) return '时间未记录';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function levelName(value?: string) {
  return (value || 'INFO').trim().toUpperCase();
}

function levelClass(value?: string) {
  const level = levelName(value).toLowerCase();
  if (level.includes('error') || level.includes('fatal') || level.includes('critical')) return 'error';
  if (level.includes('warn')) return 'warning';
  if (level.includes('debug') || level.includes('trace')) return 'debug';
  return 'info';
}

function entryKey(entry: RuntimeLogEntry, index: number) {
  return [entry.timestamp, entry.correlation_id, entry.logger, entry.message, index].join('/');
}

export function LogRow({ entry, index }: { entry: RuntimeLogEntry; index: number }) {
  const ordered = new Set(CONTEXT_ORDER);
  const contextKeys = [
    ...CONTEXT_ORDER,
    ...Object.keys(entry).filter((key) => !ordered.has(key) && !RESERVED_FIELDS.has(key)),
  ];
  const context = contextKeys
    .map((key) => ({
      key,
      label: CONTEXT_LABELS[key] || key,
      value: entry[key],
    }))
    .filter(({ value }) => value !== undefined && value !== null && value !== '');

  return (
    <li className="runtime-log-row" data-level={levelClass(entry.level)}>
      <time dateTime={entry.timestamp || undefined}>{displayLogTime(entry.timestamp)}</time>
      <span className={`runtime-log-level ${levelClass(entry.level)}`}>
        {levelName(entry.level)}
      </span>
      <div className="runtime-log-content">
        <div className="runtime-log-origin">
          <strong>{entry.logger || 'application'}</strong>
          {entry.correlation_id && (
            <span title={entry.correlation_id}>关联 ID：{entry.correlation_id}</span>
          )}
        </div>
        <p>{entry.message || '该条日志没有消息正文'}</p>
        {entry.exception && <pre className="runtime-log-exception">{entry.exception}</pre>}
        {context.length > 0 && (
          <dl className="runtime-log-context" aria-label={`第 ${index + 1} 条日志的请求上下文`}>
            {context.map(({ key, label, value }) => (
              <div key={String(key)}>
                <dt>{label}</dt>
                <dd>
                  {displayContextValue(String(key), value)}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </li>
  );
}

export function RuntimeLogsView({ active = true }: { active?: boolean }) {
  const [snapshot, setSnapshot] = useState<RuntimeLogSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const requestRef = useRef<{
    controller: AbortController;
    promise: Promise<void>;
  } | null>(null);
  const mountedRef = useRef(false);
  const streamRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(() => {
    if (requestRef.current) return requestRef.current.promise;

    const controller = new AbortController();
    setError('');
    setRefreshing(true);
    const promise = (async () => {
      try {
        const next = await loadLatestRuntimeLogs(LOG_LIMIT, controller.signal);
        if (!mountedRef.current || requestRef.current?.controller !== controller) return;
        setSnapshot({
          ...next,
          entries: Array.isArray(next.entries) ? next.entries : [],
        });
        requestAnimationFrame(() => {
          const stream = streamRef.current;
          if (stream) stream.scrollTop = stream.scrollHeight;
        });
      } catch (cause) {
        if (mountedRef.current && (cause as Error).name !== 'AbortError') {
          setError((cause as Error).message || '最新日志读取失败');
        }
      } finally {
        if (requestRef.current?.controller === controller) {
          requestRef.current = null;
          if (mountedRef.current) {
            setLoading(false);
            setRefreshing(false);
          }
        }
      }
    })();
    requestRef.current = { controller, promise };
    return promise;
  }, []);

  useEffect(() => {
    if (!active) return;
    mountedRef.current = true;
    void refresh();
    return () => {
      mountedRef.current = false;
      requestRef.current?.controller.abort();
      requestRef.current = null;
    };
  }, [refresh, active]);

  useEffect(() => {
    if (!active || !autoRefresh) return undefined;
    let cancelled = false;
    let timer: number | undefined;
    const scheduleNext = () => {
      if (cancelled) return;
      timer = window.setTimeout(async () => {
        await refresh();
        scheduleNext();
      }, REFRESH_INTERVAL_MS);
    };
    void refresh().finally(scheduleNext);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [active, autoRefresh, refresh]);

  const entries = snapshot?.entries || [];
  const returned = snapshot?.returned ?? entries.length;

  return (
    <div className="management-view active runtime-logs-view" id="management-runtime-logs">
      <div className="runtime-log-toolbar">
        <div>
          <p className="runtime-log-intro">
            查看服务当前日志源的最新记录。每次刷新都会替换当前内容，不会在页面中累积旧批次。
          </p>
          <p className="runtime-log-meta" aria-live="polite">
            {snapshot
              ? `${returned} 条记录${snapshot.truncated ? ` · 最多显示最新 ${snapshot.limit} 条` : ''}${snapshot.filtered_transport ? ` · 已过滤 ${snapshot.filtered_transport} 条底层网络调试记录` : ''} · 刷新于 ${displayLogTime(snapshot.updated_at)}`
              : '正在连接日志服务…'}
          </p>
        </div>
        <div className="runtime-log-actions">
          <label className="runtime-auto-refresh">
            <input
              type="checkbox"
              role="switch"
              checked={autoRefresh}
              onChange={(event) => setAutoRefresh(event.target.checked)}
            />
            <span aria-hidden="true" />
            每 5 秒自动刷新
          </label>
          <button className="runtime-refresh-button" type="button" onClick={() => void refresh()} disabled={refreshing}>
            <svg className={refreshing ? 'spinning' : ''} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M20 11a8 8 0 1 0-2.34 5.66" />
              <path d="M20 4v7h-7" />
            </svg>
            {refreshing ? '正在刷新…' : '刷新最新日志'}
          </button>
        </div>
      </div>

      {error && (
        <div className="runtime-log-error" role="alert">
          <div>
            <strong>日志读取失败</strong>
            <span>{error}。请检查服务状态后重试。</span>
          </div>
          <button type="button" onClick={() => void refresh()}>重新加载</button>
        </div>
      )}

      {loading ? (
        <div className="runtime-log-skeleton" role="status" aria-label="正在读取最新日志">
          {Array.from({ length: 6 }, (_, index) => <span key={index} />)}
        </div>
      ) : !snapshot && error ? null : entries.length === 0 ? (
        <div className="runtime-log-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M4 5h16M4 12h16M4 19h10" />
          </svg>
          <strong>当前没有可显示的日志</strong>
          <span>服务产生新日志后将自动显示，也可以点击“刷新最新日志”立即检查。</span>
        </div>
      ) : (
        <div className="runtime-log-stream" ref={streamRef} tabIndex={0} aria-label="最新运行日志">
          <div className="runtime-log-columns" aria-hidden="true">
            <span>时间</span><span>级别</span><span>日志内容</span>
          </div>
          <ol>
            {entries.map((entry, index) => <LogRow key={entryKey(entry, index)} entry={entry} index={index} />)}
          </ol>
        </div>
      )}

      {snapshot?.source && (
        <p className="runtime-log-source" title={snapshot.source}>日志来源：{snapshot.source}</p>
      )}
    </div>
  );
}
