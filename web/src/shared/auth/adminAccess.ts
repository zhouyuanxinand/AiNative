export interface AdminSession {
  authenticated: true;
  user: { username: string; display_name: string; userid: string };
  can_manage_admins: boolean;
}
export interface AdminMember { username: string; created_at: string; created_by: string; is_owner: boolean }
export interface AdminMembers { items: AdminMember[]; can_manage_admins: boolean }
export interface AdminAccessFailure { status: number; error: string; code?: string; username?: string }
export const ADMIN_ACCESS_EVENT = 'taskbook:admin-access-failure';

export class AdminApiError extends Error {
  constructor(public readonly failure: AdminAccessFailure) { super(failure.error); }
}

/** Invalidate the administrative UI immediately when its session or membership is revoked. */
export function notifyAdminAccessFailure(status: number, data: unknown) {
  if (!['/admin', '/feedback'].includes(window.location.pathname.replace(/\/+$/, ''))) return;
  const body = data && typeof data === 'object' ? data as Partial<AdminAccessFailure> : {};
  if (status !== 401 && !(status === 403 && body.code === 'ADMIN_FORBIDDEN')) return;
  window.dispatchEvent(new CustomEvent<AdminAccessFailure>(ADMIN_ACCESS_EVENT, { detail: {
    status, code: body.code, username: body.username,
    error: typeof body.error === 'string' ? body.error : status === 401 ? '管理员登录已失效，请重新登录。' : '当前账号没有管理员权限。',
  } }));
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (init.signal?.aborted) controller.abort(); else init.signal?.addEventListener('abort', abort, { once: true });
  let timedOut = false;
  const timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, 20000);
  try {
    const response = await fetch(url, { ...init, credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
    const data = await response.json().catch(cause => { if (controller.signal.aborted) throw cause; return null; });
    if (!response.ok) {
      notifyAdminAccessFailure(response.status, data);
      throw new AdminApiError({ status: response.status, error: data?.error || `请求失败（HTTP ${response.status}），请重试。`, code: data?.code, username: data?.username });
    }
    if (data === null) throw new AdminApiError({ status: 502, error: '管理员服务返回了无法读取的内容，请重试。' });
    return data as T;
  } catch (cause) {
    if (timedOut) throw new AdminApiError({ status: 408, error: init.method ? '请求超时，请先核对操作结果后重试。' : '管理员身份验证超时，请重试。' });
    if (cause instanceof TypeError) throw new AdminApiError({ status: 0, error: '无法连接管理员服务，请检查连接后重试。' });
    throw cause;
  } finally { window.clearTimeout(timer); init.signal?.removeEventListener('abort', abort); }
}

export const getAdminSession = (signal?: AbortSignal) => request<AdminSession>('/api/admin/session', { signal });
export const getAdminMembers = (signal?: AbortSignal) => request<AdminMembers>('/api/admin/members', { signal });
export const addAdminMember = (username: string, signal?: AbortSignal) => request<{ member: AdminMember }>('/api/admin/members', {
  method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Admin-Action': '1' }, body: JSON.stringify({ username }), signal,
});
export const removeAdminMember = (username: string, signal?: AbortSignal) => request<{ success: boolean }>(`/api/admin/members/${encodeURIComponent(username)}`, {
  method: 'DELETE', headers: { 'X-Admin-Action': '1' }, signal,
});
export const logoutAdmin = (signal?: AbortSignal) => request<{ success: boolean }>('/api/admin/logout', { method: 'POST', headers: { 'X-Admin-Action': '1' }, signal });
