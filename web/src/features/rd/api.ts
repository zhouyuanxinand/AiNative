import type { AssistantResponse, Catalog, Project, ProjectProfile, WorkspaceResource, WorkspaceResponse } from './types';

export class RdApiError extends Error {
  constructor(message: string, public readonly status: number) { super(message); this.name = 'RdApiError'; }
}

let sessionInitialization: Promise<void> | null = null;

// Carry no identity in this event: a 401 only asks the shared account UI to log in again.
export const RD_AUTH_REQUIRED_EVENT = 'rd:authentication-required';
function reportUnauthorized(response: Response) {
  if (response.status === 401) window.dispatchEvent(new Event(RD_AUTH_REQUIRED_EVENT));
}

/** Share one independent bootstrap: component cancellation must not mint competing local sessions. */
function initializeSession(): Promise<void> {
  if (sessionInitialization) return sessionInitialization;
  const pending = (async () => {
    const controller = new AbortController();
    let timedOut = false;
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 30000);
    try {
      const response = await fetch('/api/rd/session', { credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
      reportUnauthorized(response);
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        const detail = data?.detail ?? data?.error;
        throw new RdApiError(`研发会话初始化失败：${typeof detail === 'string' ? detail : `HTTP ${response.status}`}。请重试读取。`, response.status);
      }
    } catch (error) {
      if (timedOut) throw new RdApiError('研发会话初始化超时，请重试读取。', 408);
      if (error instanceof TypeError) throw new RdApiError('无法建立研发会话，请检查连接后重试读取。', 0);
      throw error;
    } finally { window.clearTimeout(timeout); }
  })();
  sessionInitialization = pending;
  void pending.catch(() => { if (sessionInitialization === pending) sessionInitialization = null; });
  return pending;
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 30000): Promise<T> {
  if (init.signal?.aborted) throw new DOMException('读取已取消', 'AbortError');
  await initializeSession();
  if (init.signal?.aborted) throw new DOMException('读取已取消', 'AbortError');
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (init.signal?.aborted) controller.abort();
  else init.signal?.addEventListener('abort', cancel, { once: true });
  let timedOut = false;
  const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  try {
    const response = await fetch(`/api/rd${path}`, { ...init, signal: controller.signal });
    reportUnauthorized(response);
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = data?.detail ?? data?.error;
      throw new RdApiError(typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : `请求未完成（HTTP ${response.status}）`, response.status);
    }
    return data as T;
  } catch (error) {
    if (timedOut) throw new RdApiError('请求超时，操作结果尚未确认。请刷新核对后重试；填写内容已保留。', 408);
    if (error instanceof TypeError) throw new RdApiError('无法连接研发服务，请检查连接后重试。填写内容已保留。', 0);
    throw error;
  } finally {
    window.clearTimeout(timeout);
    init.signal?.removeEventListener('abort', cancel);
  }
}

const encode = encodeURIComponent;
const unwrap = (value: Project | { project: Project }) => 'project' in value ? value.project : value;
export const makeRequestKey = () => typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `rd-${Date.now()}-${Math.random().toString(36).slice(2)}`;
export const rdCatalog = (signal?: AbortSignal) => request<Catalog>('/catalog', { signal });
export const rdProjects = (signal?: AbortSignal) => request<{ projects: Project[] }>('/projects', { signal });
export const rdProject = async (id: string, signal?: AbortSignal) => unwrap(await request<Project | { project: Project }>(`/projects/${encode(id)}`, { signal }));
export const rdCreate = async (title: string, context: Record<string, string>, key: string, profile: Partial<ProjectProfile> = {}) => unwrap(await request<Project | { project: Project }>('/projects', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify({ title, context, ...profile }) }));
export const rdCommand = async (project: Project, command: string, data: unknown, key: string) => unwrap(await request<Project | { project: Project }>(`/projects/${encode(project.id)}/commands`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify({ expected_version: project.version, command, data }) }));
export const rdSaveProjectProfile = (project: Project, profile: Partial<ProjectProfile> & { title?: string }, key: string) => rdCommand(project, 'save_project_profile', profile, key);
export const rdAnalyzeSources = async (project: Project, caseId: string, key: string) => unwrap(await request<Project | { project: Project }>(`/projects/${encode(project.id)}/cases/${encode(caseId)}/analysis`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify({ expected_version: project.version }) }, 300000));
export async function rdUpload(project: Project, caseId: string, file: File, role: string, key: string) {
  const body = new FormData(); body.set('expected_version', String(project.version)); body.set('role', role); body.set('file', file);
  return unwrap(await request<Project | { project: Project }>(`/projects/${encode(project.id)}/cases/${encode(caseId)}/sources`, { method: 'POST', headers: { 'Idempotency-Key': key }, body }));
}
export const sourceUrl = (pid: string, cid: string, sid: string) => `/api/rd/projects/${encode(pid)}/cases/${encode(cid)}/sources/${encode(sid)}`;
export const artifactUrl = (pid: string, cid: string, wid: string, aid: string) => `/api/rd/projects/${encode(pid)}/cases/${encode(cid)}/workpackages/${encode(wid)}/artifacts/${encode(aid)}`;
export const rdResources = (signal?: AbortSignal) => request<WorkspaceResponse>('/workspace/resources', { signal });
export const rdResourceSave = (resource: Partial<WorkspaceResource> & { operation: string; expected_version?: number | string }, key: string) => request<WorkspaceResource | WorkspaceResponse>('/workspace/resources', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(resource) });
export const rdContracts = (signal?: AbortSignal) => request<Record<string, unknown>>('/contracts', { signal });
export const rdAssistant = (pid: string, cid: string, signal?: AbortSignal, before?: number) => request<AssistantResponse>(`/projects/${encode(pid)}/cases/${encode(cid)}/assistant${before === undefined ? '' : `?before=${encode(String(before))}`}`, { signal });
export const rdAskAssistant = (pid: string, cid: string, message: string, topic: string | undefined, key: string, signal?: AbortSignal) => request<AssistantResponse>(`/projects/${encode(pid)}/cases/${encode(cid)}/assistant`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify({ message, ...(topic ? { topic } : {}) }), signal });
