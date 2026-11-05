import type { ApplicationGrant, AssistantResponse, Catalog, DirectoryPage, Project, ProjectProfile, ResourceSummary, WorkspaceResource, WorkspaceResponse, WorkspaceSession, ModelSelection, SourceBatchItem, SourceClassification } from './types';
import type { PageReference } from './platformNavigation';

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
    const response = await fetch(`/api/rd${path}`, { cache: 'no-store', credentials: 'same-origin', ...init, signal: controller.signal });
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
export const rdSession = (signal?: AbortSignal) => request<{ actor_id: string; local_mode: boolean }>('/session', { signal });
export const rdWelcomeAssistant = (message: string, history: { role: 'user' | 'assistant'; content: string }[], signal?: AbortSignal) => request<{ content: string; mode: 'model' | 'local_guidance'; actions: { id: 'start_task' | 'open_projects' | 'weather'; label: string }[] }>('/assistant/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message, history }), signal }, 120000);
export interface ChatMessage {
  id: string; seq: number; role: 'user' | 'assistant'; content: string; created_at: string;
  mode?: 'model' | 'local_guidance'; actions?: { id: 'start_task' | 'open_projects' | 'weather'; label: string }[];
}
export interface ChatSummary { id: string; title: string; created_at: string; updated_at: string; message_count: number; source_id: string | null; version: number }
export interface ChatDetail extends ChatSummary { draft: string; messages: ChatMessage[]; has_more: boolean; next_before: number | null }
export interface ChatDirectory { items: ChatSummary[]; total: number; page: number; page_size: number; active_id: string | null }
export const rdChatDirectory = (page = 1, signal?: AbortSignal) => request<ChatDirectory>(`/assistant/conversations?page=${page}`, { signal });
export const rdChatDetail = (id: string, signal?: AbortSignal, before?: number) => request<ChatDetail>(`/assistant/conversations/${encode(id)}${before === undefined ? '' : `?before=${before}`}`, { signal });
export const rdChatCreate = (sourceId: string | undefined, key: string, signal?: AbortSignal) => request<ChatDetail>('/assistant/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(sourceId ? { source_id: sourceId } : {}), signal });
export const rdChatSend = (id: string, body: { message: string; expected_version: number }, key: string, signal?: AbortSignal) => request<ChatDetail>(`/assistant/conversations/${encode(id)}/messages`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(body), signal }, 120000);
export const rdChatClose = (id: string, body: { choice: 'keep' | 'end'; draft: string; expected_version: number }, key: string, signal?: AbortSignal) => request<{ active_id: string | null }>(`/assistant/conversations/${encode(id)}/close`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(body), signal });
export const rdAssistantWeather = (signal?: AbortSignal) => request<import('./assistant/AssistantWeather').AssistantWeatherData>('/assistant/weather', { signal }, 20000);
export const rdCatalog = (signal?: AbortSignal) => request<Catalog>('/catalog', { signal });
export const rdProjects = (signal?: AbortSignal) => request<{ projects: Project[] }>('/projects', { signal });
export const rdProject = async (id: string, signal?: AbortSignal) => unwrap(await request<Project | { project: Project }>(`/projects/${encode(id)}`, { signal }));
export const rdDeleteProject = (project: Project, key: string) => request<{ ok: boolean; project_id: string; version: number; deleted_at: string }>(`/projects/${encode(project.id)}?expected_version=${project.version}`, { method: 'DELETE', headers: { 'Idempotency-Key': key } });
export const rdCreate = async (title: string, context: Record<string, string>, key: string, profile: Partial<ProjectProfile> = {}) => unwrap(await request<Project | { project: Project }>('/projects', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify({ title, context, ...profile }) }));
export const rdCommand = async (project: Project, command: string, data: unknown, key: string) => unwrap(await request<Project | { project: Project }>(`/projects/${encode(project.id)}/commands`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify({ expected_version: project.version, command, data }) }));
export const rdSaveProjectProfile = (project: Project, profile: Partial<ProjectProfile> & { title?: string }, key: string) => rdCommand(project, 'save_project_profile', profile, key);
export const rdAnalyzeSources = async (project: Project, caseId: string, key: string) => unwrap(await request<Project | { project: Project }>(`/projects/${encode(project.id)}/cases/${encode(caseId)}/analysis`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify({ expected_version: project.version }) }, 300000));
export const rdEvidenceLocations = (projectId: string, caseId: string, signal?: AbortSignal) => request<{ items: import('./types').EvidenceLocationResult[] }>(`/projects/${encode(projectId)}/cases/${encode(caseId)}/evidence-locations`, { signal }, 120000);
export function rdEvidencePreview(projectId: string, caseId: string, location: import('./types').EvidenceLocationResult, locationId: string, signal?: AbortSignal) {
  const query = new URLSearchParams({ source_id: location.source_id, quote: location.quote, source_sha256: location.source_sha256 || '', location_id: locationId });
  if (location.analysis_id != null) query.set('analysis_id', location.analysis_id);
  if (location.normalized_sha256) query.set('normalized_sha256', location.normalized_sha256);
  return request<import('./types').EvidencePreview>(`/projects/${encode(projectId)}/cases/${encode(caseId)}/evidence-preview?${query}`, { signal }, 120000);
}
export async function rdUpload(project: Project, caseId: string, file: File, role: string, key: string) {
  const body = new FormData(); body.set('expected_version', String(project.version)); body.set('role', role); body.set('file', file);
  return unwrap(await request<Project | { project: Project }>(`/projects/${encode(project.id)}/cases/${encode(caseId)}/sources`, { method: 'POST', headers: { 'Idempotency-Key': key }, body }));
}
export async function rdUploadBatch(project: Project, caseId: string, items: SourceBatchItem[], key: string, expectedVersion: number) {
  const body = new FormData();
  body.set('expected_version', String(expectedVersion));
  body.set('manifest', JSON.stringify(items.map(item => ({ id: item.id, name: item.file.name, role: item.role, primary: item.primary }))));
  items.forEach(item => body.append('files', item.file));
  return unwrap(await request<Project | { project: Project }>(`/projects/${encode(project.id)}/cases/${encode(caseId)}/sources/batch`, { method: 'POST', headers: { 'Idempotency-Key': key }, body }, 300000));
}
export function rdClassifySources(projectId: string, caseId: string, files: Array<{ id: string; name: string }>, modelSelection?: ModelSelection, useModel = true, signal?: AbortSignal) {
  return request<SourceClassification>(`/projects/${encode(projectId)}/cases/${encode(caseId)}/sources/classify`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal, body: JSON.stringify({ files, model_selection: modelSelection, use_model: useModel }) }, 120000);
}
export const sourceUrl = (pid: string, cid: string, sid: string) => `/api/rd/projects/${encode(pid)}/cases/${encode(cid)}/sources/${encode(sid)}`;
export const artifactUrl = (pid: string, cid: string, wid: string, aid: string) => `/api/rd/projects/${encode(pid)}/cases/${encode(cid)}/workpackages/${encode(wid)}/artifacts/${encode(aid)}`;
export interface DirectoryQuery { q?: string; kind?: string; page?: number }
const directoryQuery = (query: DirectoryQuery = {}) => new URLSearchParams({ q: query.q ?? '', ...(query.kind ? { kind: query.kind } : {}), page: String(query.page ?? 1), page_size: '5' }).toString();
export const rdWorkspaceSession = (signal?: AbortSignal) => request<WorkspaceSession>('/workspace/session', { signal });
export const rdResources = (signal?: AbortSignal, query?: DirectoryQuery) => request<WorkspaceResponse>(`/workspace/resources?${directoryQuery(query)}`, { signal });
export const rdCatalogResources = (query?: DirectoryQuery, signal?: AbortSignal) => request<DirectoryPage<ResourceSummary>>(`/catalog/resources?${directoryQuery(query)}`, { signal });
export const rdResource = (id: string, version: number | string, signal?: AbortSignal) => request<WorkspaceResource>(`/workspace/resources/${encode(id)}/${encode(String(version))}`, { signal });
export const rdCatalogResource = (id: string, version: number | string, signal?: AbortSignal) => request<ResourceSummary>(`/catalog/resources/${encode(id)}/${encode(String(version))}`, { signal });
export const rdCatalogItems = <T,>(category: string, query?: DirectoryQuery, signal?: AbortSignal) => request<DirectoryPage<T>>(`/catalog/items?category=${encode(category)}&${directoryQuery(query)}`, { signal });
export const rdResourceSave = (resource: Partial<WorkspaceResource> & { operation: string; expected_version?: number | string; expected_state_revision?: number; expected_control_revision?: number }, key: string) => request<WorkspaceResource>('/workspace/resources', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(resource) });
export const rdResourceGrant = (grant: { id: string; version: number | string; operation: 'grant' | 'revoke'; expected_revision: number; expires_at?: string | null }, key: string) => request<ApplicationGrant>('/workspace/grants', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(grant) });
export const rdContracts = (signal?: AbortSignal) => request<Record<string, unknown>>('/contracts', { signal });
export const rdAssistant = (pid: string, cid: string, signal?: AbortSignal, before?: number) => request<AssistantResponse>(`/projects/${encode(pid)}/cases/${encode(cid)}/assistant${before === undefined ? '' : `?before=${encode(String(before))}`}`, { signal });
export const rdAskAssistant = (pid: string, cid: string, message: string, topic: string | undefined, key: string, signal?: AbortSignal, pageRef?: PageReference) => request<AssistantResponse>(`/projects/${encode(pid)}/cases/${encode(cid)}/assistant`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify({ message, ...(topic ? { topic } : {}), ...(pageRef ? { page_ref: pageRef } : {}) }), signal });
export interface NavigationContext {
  schema_version: 1;
  page_ref: PageReference;
  context: { project_version?: number; input_revision?: number; stage?: string; counts?: Record<string, number> };
  navigation: PageReference[];
  read_only: true;
}
export const rdNavigationContext = (pageRef: PageReference, signal?: AbortSignal) => request<NavigationContext>('/navigation/context', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pageRef), signal,
});

export const rdGovernanceSession = (signal?: AbortSignal) => request<import('./types').GovernanceSession>('/governance/session', { signal });
export const rdWorkflowTemplates = (category: string, query: DirectoryQuery = {}, management = false, signal?: AbortSignal) => request<DirectoryPage<import('./types').BusinessWorkflowTemplate>>(`/workflow-templates?category=${encode(category)}&management=${management}&${directoryQuery(query)}`, { signal });
export const rdWorkflowTemplate = (id: string, version: string, management = false, signal?: AbortSignal) => request<import('./types').BusinessWorkflowTemplate>(`/workflow-templates/${encode(id)}/${encode(version)}?management=${management}`, { signal });
export const rdWorkflowSave = (payload: Record<string, unknown>, key: string) => request<import('./types').BusinessWorkflowTemplate>('/workflow-templates', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(payload) });
export const rdWorkflowValidate = (payload: Record<string, unknown>) => request<import('./types').WorkflowCheck>('/workflow-templates/validate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
export const rdWorkflowHistory = (id: string, management = false, page = 1, signal?: AbortSignal) => request<import('./types').WorkflowHistory>(`/workflow-templates/${encode(id)}/history?management=${management}&page=${page}&page_size=5`, { signal });
export const rdDerivations = (signal?: AbortSignal, page = 1) => request<{ items: Array<Record<string, unknown>>; total: number; page: number; page_size: number }>(`/template-derivations?page=${page}&page_size=5`, { signal });
export const rdDerivation = (id: string, signal?: AbortSignal) => request<Record<string, unknown>>(`/template-derivations/${encode(id)}`, { signal });
export const rdDerivationAction = (id: string, action: string, payload: Record<string, unknown> | FormData, key: string) => request<Record<string, unknown>>(`/template-derivations/${encode(id)}/${encode(action)}`, { method: 'POST', headers: payload instanceof FormData ? { 'Idempotency-Key': key } : { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: payload instanceof FormData ? payload : JSON.stringify(payload) }, 300000);
export const rdDeriveTemplate = (payload: Record<string, unknown>, key: string) => request<Record<string, unknown>>('/template-derivations', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(payload) }, 300000);
export const rdTemplateRules = (signal?: AbortSignal, page = 1) => request<{ items: Array<Record<string, unknown>>; total: number; page: number; page_size: number }>(`/template-rules?page=${page}&page_size=5`, { signal });
export const rdTemplateRuleSave = (payload: FormData, key: string) => request<Record<string, unknown>>('/template-rules', { method: 'POST', headers: { 'Idempotency-Key': key }, body: payload });
export const rdTemplateRuleReview = (id: string, payload: Record<string, unknown>, key: string) => request<Record<string, unknown>>(`/template-rules/${encode(id)}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(payload) });

export const rdTemplateRulePublish = (id: string, payload: Record<string, unknown>, key: string) => request<Record<string, unknown>>('/template-rules/' + encode(id) + '/publish', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(payload) });
