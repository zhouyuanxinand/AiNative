import type { RuntimeLogEntry } from './runtimeLogs';
import { notifyAdminAccessFailure } from './adminAccess';

export type RequestLogStatus = 'running' | 'success' | 'failed';
export interface RequestLogSummary {
  request_id: string;
  job_id: string | null;
  status: RequestLogStatus;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  username: string | null;
  userid: string | null;
  request_kind: string;
  product_type: string | null;
  product_series: string | null;
  product_domain?: string;
  development_process?: string;
  process_classification?: string;
  product_scope?: string;
  cover_stage?: string;
  model_provider?: string;
  parent_jid?: string;
  delivery_status?: string;
  model: string | null;
  files: { tech?: string | null; spec?: string | null; output?: string | null };
  error_summary: string | null;
  event_count: number;
}
export interface RequestLogList {
  items: RequestLogSummary[];
  retention: number;
  stats: { running: number; success: number; failed: number; total: number };
}
export interface RequestLogDetail {
  request: RequestLogSummary;
  entries: Array<RuntimeLogEntry & { id: number }>;
  next_cursor: number;
  has_more: boolean;
}

export class RequestLogError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function getRequestLogs<T>(path: string, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener('abort', cancel, { once: true });
  let timedOut = false;
  const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 20000);
  try {
    const response = await fetch(path, { headers: { 'X-Log-Viewer': '1' }, signal: controller.signal });
    const data = await response.json().catch(cause => { if (controller.signal.aborted) throw cause; return null; });
    if (!response.ok) {
      notifyAdminAccessFailure(response.status, data);
      throw new RequestLogError(data?.error || `日志读取未完成（HTTP ${response.status}）`, response.status);
    }
    if (data === null) throw new RequestLogError('日志服务返回了无法读取的内容', 502);
    return data as T;
  } catch (cause) {
    if (timedOut) throw new RequestLogError('日志读取超时，请重试', 408);
    if (cause instanceof TypeError) throw new RequestLogError('无法连接日志服务，请检查连接后重试', 0);
    throw cause;
  } finally {
    window.clearTimeout(timeout); signal?.removeEventListener('abort', cancel);
  }
}

export function listRequestLogs(filters: { status: string; q: string }, signal?: AbortSignal) {
  const query = new URLSearchParams();
  if (filters.status) query.set('status', filters.status);
  if (filters.q) query.set('q', filters.q);
  return getRequestLogs<RequestLogList>(`/api/logs/requests${query.size ? `?${query}` : ''}`, signal);
}

export function readRequestLogs(requestId: string, after: number, signal?: AbortSignal) {
  return getRequestLogs<RequestLogDetail>(`/api/logs/requests/${encodeURIComponent(requestId)}?${new URLSearchParams({ after: String(after), limit: '500' })}`, signal);
}
