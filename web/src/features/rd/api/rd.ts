export type RdRole = 'owner' | 'engineer' | 'reviewer' | 'viewer';
export interface RdSelection { id: string; route: 'direct' | 'modification' | 'new'; selected_product: string; rationale: string; evidence_ref: string; suitability: 'pending' | 'confirmed'; supply_status: 'pending' | 'confirmed'; baseline_id: string; created_by: string; created_at: string }
export interface RdDelivery { id: string; selection_id: string; outcome: 'blocked' | 'accepted'; recipient: string; reference: string; note: string; baseline_id: string; created_by: string; created_at: string }
export interface RdJourney { route: 'undecided' | 'direct' | 'modification' | 'new'; route_label: string; stage: string; stage_label: string; selection: RdSelection | null; delivery: RdDelivery | null; blockers: string[] }
export interface RdProject { id: string; code: string; name: string; customer: string; product: string; owner_id: string; version: number; current_baseline_id: string | null; created_at: string; role: RdRole }
export interface RdMember { user_id: string; display_name: string; role: RdRole }
export interface RdRequirement { id: string; title: string; content: string; source: string; acceptance: string; clarification: 'open' | 'resolved'; required: boolean; revision: number; history: Record<string, unknown>[] }
export interface RdBaseline { id: string; number: number; requirements: RdRequirement[]; confirmed_by: string; created_at: string }
export interface RdTask { kind?: 'taskbook' | 'plan_item'; required_handoff_id?: string; source_task_id?: string; id: string; title: string; description: string; assignee_id: string; reviewer_id: string; due_date?: string; baseline_id: string; status: string; previous_status?: string; created_at: string }
export interface RdQualityEvidence { revision_id: string; sha256: string; checks: { status: string; checked_at?: string; message?: string; issues?: { message: string; severity?: string; code?: string }[]; [key: string]: unknown }; rules_fingerprint: string; generation_summary?: Record<string, unknown>; generation_status?: string; selection?: Record<string, unknown>; archived_assets?: Record<string, unknown>[] }
export interface RdArtifact { id: string; task_id: string; baseline_id: string; jid: string; source_revision_id: string; filename: string; sha256: string; file_ref: string; quality_status: string; quality_evidence?: RdQualityEvidence; author_id: string; status: string; created_at: string }
export interface RdReview { id: string; task_id: string; artifact_id: string; baseline_id: string; submitter_id: string; reviewer_id: string; status: string; comment: string; decided_by?: string; created_at: string; decided_at?: string }
export interface RdEvent { id: string; action: string; actor_id: string; created_at: string; detail: Record<string, unknown> }
export interface RdGeneration { jid: string; task_id: string; baseline_id: string; actor_id: string; created_at: string; inputs?: Record<string, unknown> }
export interface RdDetail { journey?: RdJourney; selection_decisions?: RdSelection[]; delivery_records?: RdDelivery[]; taskbook_releases?: {id: string;task_id: string;revision_id: string;version: number;artifact_id?: string}[]; project_sources?: {source_id: string;version: number;name?: string;provenance?: string}[]; taskbook_work_units?: {task_id: string;current_stage?: string;release_id?: string|null;input_package_id?: string|null;selected_revision_id?: string|null}[]; change_impacts?: { id: string; task_id: string; status: string; downstream_task_ids?: string[] }[]; development_adoptions?: { id: string; route: string; approval_ref: string; scope: string; requirements_baseline_id: string; provenance: string; process_template_ref: { id: string; version: string } }[]; project_plan?: RdProjectPlan; handoffs?: { id: string; task_id: string; assignee_id: string; status: string; source_revision_id: string; source_release_id?: string; release_id?: string }[]; project: RdProject; current_user_id: string; members: RdMember[]; requirements: RdRequirement[]; baselines: RdBaseline[]; tasks: RdTask[]; artifacts: RdArtifact[]; reviews: RdReview[]; events: RdEvent[]; generations: RdGeneration[] }
export interface RdProjectPage { items: RdProject[]; total: number; page: number; page_size: number }
export class RdApiError extends Error {
  constructor(message: string, public readonly status: number) { super(message); this.name = 'RdApiError'; }
}
export function rdRequestKey() { return crypto.randomUUID?.() || `rd-${Date.now()}-${Math.random().toString(36).slice(2)}`; }
export async function rdRequest<T>(url: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (init.signal?.aborted) abort();
  else init.signal?.addEventListener('abort', abort, { once: true });
  let timedOut = false;
  const timer = window.setTimeout(() => { timedOut = true; abort(); }, 20000);
  try {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', ...init, signal: controller.signal });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new RdApiError(typeof data?.detail === 'string' ? data.detail : `请求未完成（HTTP ${response.status}），请重试。`, response.status);
    if (data === null) throw new RdApiError('服务响应不完整，请重试以确认操作结果。', 0);
    return data as T;
  } catch (error) {
    if (timedOut) throw new RdApiError('连接超时，操作结果尚未确认。请使用原表单重试，系统会沿用本次请求编号。', 408);
    if (error instanceof TypeError) throw new RdApiError('无法连接研发服务。请检查连接后使用原表单重试。', 0);
    throw error;
  } finally { clearTimeout(timer); init.signal?.removeEventListener('abort', abort); }
}
const request = rdRequest;
const root = '/api/rd/projects';
const json = (body: unknown, key: string): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(body) });
export const listRdProjects = (q: string, page: number, pageSize: number, signal?: AbortSignal) => request<RdProjectPage>(`${root}?${new URLSearchParams({ q, page: String(page), page_size: String(pageSize) })}`, { signal });
export const getRdProject = (pid: string, signal?: AbortSignal) => request<RdDetail>(`${root}/${encodeURIComponent(pid)}`, { signal });
export const createRdProject = (payload: Record<string, unknown>, key: string) => request<RdDetail>(root, json(payload, key));
export const commandRdProject = (pid: string, action: string, payload: Record<string, unknown>, version: number, key: string) => request<RdDetail>(`${root}/${encodeURIComponent(pid)}/commands`, json({ action, expected_version: version, payload }, key));
export const captureRdArtifact = (pid: string, tid: string, jid: string, revisionId: string, version: number, key: string) => request<RdDetail>(`${root}/${encodeURIComponent(pid)}/tasks/${encodeURIComponent(tid)}/artifacts`, json({ jid, revision_id: revisionId, expected_version: version }, key));
export const rdArtifactDownload = (pid: string, aid: string, approved = false) => `${root}/${encodeURIComponent(pid)}/artifacts/${encodeURIComponent(aid)}/download?approved=${approved}`;
export interface RdDemoStatus { enabled: boolean; users: { userid: string; display_name: string; role: RdRole }[]; current_user_id: string | null }
export const getRdWorkspace = (signal?: AbortSignal) => request<{ projects: RdDetail[] }>('/api/rd/workspace', { signal });
export const getRdDemoStatus = (signal?: AbortSignal) => request<RdDemoStatus>('/api/demo/status', { signal });
export const switchRdDemoIdentity = (userId: string) => request<unknown>('/api/demo/identity', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId }) });

export interface RdProjectPlan { pending_releases?: {task_id: string;release_id: string;source_revision_id?: string}[]; versions: { id: string; release_id: string; plan_version: number; item_task_map: Record<string,string> }[]; items: { id: string; title: string; status: string; assignee_id: string; reviewer_id: string; source_task_id: string; source_release_id: string; source_revision_id: string; requirement_ids: string[]; planned_start?: string; planned_end?: string; actual_start?: string; actual_end?: string; predecessor_task_ids: string[]; required_handoff_id?: string; accepted_handoff_id?: string }[]; work_units: { id: string; task_id: string; current_stage: string; stages: { instance_id: string; node_code: string; label: string; status: string }[] }[] }
