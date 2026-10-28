import { notifyAdminAccessFailure } from '../../../shared/auth/adminAccess';

export type FeedbackRating = 'good' | 'average' | 'poor';
export type FeedbackStatus = 'open' | 'in_progress' | 'resolved';

export interface FeedbackIdentity {
  userid?: string;
  name?: string;
  source?: 'smartvision' | 'manual';
  verified?: boolean;
}

export interface FeedbackSnapshot {
  jid: string;
  job_status: string;
  parameters: {
    product_type?: string; product_type_label?: string; product_domain?: string; product_domain_label?: string;
    development_process?: string; cover_phase?: string; product_series?: string; organization_scope?: string;
    model_provider?: string; model_name?: string; model_id?: string; template_name?: string;
  };
  files: { tech?: string; spec?: string; output?: string; report?: string };
  delivery_status?: string;
  qa_ok?: boolean | null;
  error?: string;
}

export interface FeedbackRecord {
  id: number;
  version: number;
  created_at: string;
  updated_at: string;
  username: string;
  identity?: FeedbackIdentity;
  rating: FeedbackRating;
  comment: string;
  status: FeedbackStatus;
  handling_note: string;
  snapshot: FeedbackSnapshot;
}

export interface FeedbackFields {
  username: string;
  rating: FeedbackRating;
  comment: string;
  status: FeedbackStatus;
  handling_note: string;
}

export interface FeedbackFilters {
  q: string;
  rating: '' | FeedbackRating;
  status: '' | FeedbackStatus;
  date_from: string;
  date_to: string;
  page: number;
  page_size: number;
}

export interface FeedbackPage {
  items: FeedbackRecord[];
  total: number;
  page: number;
  page_size: number;
  stats: {
    total: number; good: number; average: number; poor: number; good_rate: number;
    open: number; in_progress: number; resolved: number;
  };
}

/** Preserve HTTP status for version-conflict recovery; the shared JSON helper only preserves a message. */
export class FeedbackApiError extends Error {
  constructor(message: string, public readonly status: number) { super(message); this.name = 'FeedbackApiError'; }
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (init.signal?.aborted) controller.abort();
  else init.signal?.addEventListener('abort', cancel, { once: true });
  let timedOut = false;
  const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 20000);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    const data = await response.json().catch(reason => { if (controller.signal.aborted) throw reason; return null; });
    if (!response.ok) {
      notifyAdminAccessFailure(response.status, data);
      throw new FeedbackApiError(data?.error || `请求未完成（HTTP ${response.status}），请重试。`, response.status);
    }
    return data as T;
  } catch (reason) {
    if (timedOut) throw new FeedbackApiError(init.method && init.method !== 'GET'
      ? '请求超时，操作结果尚未确认。请先核对记录后重试。' : '读取反馈超时，请重试。', 408);
    if (reason instanceof TypeError) throw new FeedbackApiError('无法连接反馈服务，请检查连接后重试。', 0);
    throw reason;
  } finally {
    window.clearTimeout(timeout); init.signal?.removeEventListener('abort', cancel);
  }
}

function jsonRequest(method: string, body: unknown, signal?: AbortSignal): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal };
}

export async function submitGenerationFeedback(
  fields: { jid: string; username?: string; rating: FeedbackRating; comment: string; request_id: string }, signal?: AbortSignal,
): Promise<FeedbackRecord> {
  return (await request<{ record: FeedbackRecord }>('/api/feedback', jsonRequest('POST', fields, signal))).record;
}

export function listFeedback(filters: FeedbackFilters, signal?: AbortSignal): Promise<FeedbackPage> {
  const query = new URLSearchParams();
  if (filters.q) query.set('q', filters.q);
  if (filters.rating) query.set('rating', filters.rating);
  if (filters.status) query.set('status', filters.status);
  // Inputs and URL use China calendar dates. The API accepts absolute boundaries as well as UTC dates.
  if (filters.date_from) query.set('date_from', `${filters.date_from}T00:00:00+08:00`);
  if (filters.date_to) query.set('date_to', `${filters.date_to}T23:59:59.999999+08:00`);
  query.set('page', String(filters.page));
  query.set('page_size', String(filters.page_size));
  return request<FeedbackPage>(`/api/feedback-admin?${query}`, { signal });
}

export async function getFeedback(id: number, signal?: AbortSignal): Promise<FeedbackRecord> {
  return (await request<{ record: FeedbackRecord }>(`/api/feedback-admin/${id}`, { signal })).record;
}

export async function saveFeedback(fields: FeedbackFields, record: FeedbackRecord | null, jid: string, signal?: AbortSignal): Promise<FeedbackRecord> {
  const url = record ? `/api/feedback-admin/${record.id}` : '/api/feedback-admin';
  const body = record ? { ...fields, expected_version: record.version } : { ...fields, jid };
  return (await request<{ record: FeedbackRecord }>(url, jsonRequest(record ? 'PUT' : 'POST', body, signal))).record;
}

export function deleteFeedback(record: FeedbackRecord, signal?: AbortSignal): Promise<{ ok: true }> {
  return request(`/api/feedback-admin/${record.id}?expected_version=${record.version}`, { method: 'DELETE', signal });
}
