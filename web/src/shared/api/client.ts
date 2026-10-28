/** fetch 封装——统一 JSON 解析与错误处理。 */
import { notifyAdminAccessFailure } from '../auth/adminAccess';

export async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const data = await res.json();
  if (!res.ok) {
    notifyAdminAccessFailure(res.status, data);
    const body = data as { error?: string; detail?: unknown };
    const msg = body?.error || (typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`);
    throw new Error(msg);
  }
  return data as T;
}

export async function postForm<T>(url: string, body: FormData): Promise<T> {
  return fetchJSON<T>(url, { method: 'POST', body });
}

export async function getJSON<T>(url: string): Promise<T> {
  return fetchJSON<T>(url);
}

/** 安全编码 jid，拼接 API 路径。 */
export function apiUrl(path: string): string {
  return path;
}
