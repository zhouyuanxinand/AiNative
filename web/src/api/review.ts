/** Revisioned taskbook review; source documents are immutable task snapshots. */
export interface ReviewImage { id: string; src: string; mime: string; alt?: string; available?: boolean; reason?: string }
export interface ReviewParagraph {
  id: string; kind: 'paragraph'; text: string; heading_level: number; style?: string;
  section_id?: string; parent_section_id?: string; source_body_index?: number;
  editable: boolean; edit_reason?: string; can_delete: boolean; delete_reason?: string; images?: ReviewImage[];
}
export interface ReviewTable {
  id: string; kind: 'table'; section_id?: string;
  rows: { cells: { id: string; blocks: ReviewBlock[]; colspan?: number; rowspan?: number }[] }[];
}
export type ReviewBlock = ReviewParagraph | ReviewTable;
export interface ReviewDocument {
  document_id: string; sha256: string; format: string; view_mode: string;
  blocks: ReviewBlock[]; outline: { id: string; text: string; level: number; parent_id?: string }[];
  sections: { id: string; title: string; level: number; parent_id?: string; block_ids: string[] }[];
  warnings: string[];
}
export interface ReviewAsset {
  id: string; role: string; label: string; name: string; format: string; available: boolean; sha256?: string; url: string;
}
export interface ReviewAnnotation { element_id: string; status: 'checked' | 'pending'; note?: string; updated_at?: string }
export interface ReviewIssue { code?: string; message: string; severity?: string; element_id?: string }
export interface ReviewChecks { status: string; checked_at?: string; issues?: ReviewIssue[]; message?: string }
export interface ReviewRevision {
  id: string; parent_id?: string; created_at: string; actor?: string; reason?: string; sha256: string;
  checks?: ReviewChecks; annotations?: ReviewAnnotation[];
}
export interface ReviewBundle {
  jid: string; title: string; selection: Record<string, unknown>; assets: ReviewAsset[];
  baseline_revision_id: string; current_revision_id: string; revisions: ReviewRevision[]; warnings: string[];
}
export interface ReviewLink {
  output_element_ids: string[]; source_asset_id: string; source_element_ids: string[];
  status: 'verified' | 'candidate' | 'unmapped'; label: string; reason?: string;
  rule_excluded?: boolean; rule_reason?: string;
}
export interface ReviewOperation { op: 'replace_text' | 'insert_paragraph' | 'delete_paragraph'; element_id: string; text?: string; position?: 'before' | 'after' }
export class ReviewRequestError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = 'ReviewRequestError'; }
}
const root = (jid: string) => `/api/review/${encodeURIComponent(jid)}`;
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', ...init });
  if (!response.ok) {
    let message = '';
    try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : body.error || ''; } catch { /* A proxy may return HTML. */ }
    throw new ReviewRequestError(message || `请求失败（HTTP ${response.status}），请重试。`, response.status);
  }
  return response.json();
}
const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
export const getReview = (jid: string, signal?: AbortSignal) => request<ReviewBundle>(root(jid), { signal });
export const getReviewDocument = (jid: string, selector: { asset_id: string } | { revision_id: string }, signal?: AbortSignal) =>
  request<ReviewDocument>(`${root(jid)}/document?${new URLSearchParams(selector)}`, { signal });
export const getReviewLinks = (jid: string, revision: string, signal?: AbortSignal) =>
  request<{ links: ReviewLink[]; warnings: string[] }>(`${root(jid)}/links?${new URLSearchParams({ revision_id: revision })}`, { signal });
export const saveReviewRevision = (jid: string, revision: string, operations: ReviewOperation[]) =>
  request<ReviewBundle>(`${root(jid)}/revisions`, json({ expected_revision_id: revision, operations }));
export const checkReviewRevision = (jid: string, revision: string) =>
  request<ReviewChecks>(`${root(jid)}/revisions/${encodeURIComponent(revision)}/check`, json({}));
export const restoreReviewRevision = (jid: string, revision: string, expected: string) =>
  request<ReviewBundle>(`${root(jid)}/revisions/${encodeURIComponent(revision)}/restore`, json({ expected_revision_id: expected }));
export const annotateReviewRevision = (jid: string, revision: string, annotation: ReviewAnnotation) =>
  request<{ annotations: ReviewAnnotation[] }>(`${root(jid)}/revisions/${encodeURIComponent(revision)}/annotations`, json(annotation));
export const reviewDownload = (jid: string, revision: string) => `${root(jid)}/revisions/${encodeURIComponent(revision)}/download`;
export function uploadReviewRevision(jid: string, revision: string, file: File) {
  const form = new FormData(); form.append('expected_revision_id', revision); form.append('file', file);
  return request<ReviewBundle>(`${root(jid)}/revisions/upload`, { method: 'POST', body: form });
}
export interface OfficeStatus { configured: boolean; script_url?: string; message: string }
export interface OfficeSession { session_id: string; script_url: string; config: Record<string, unknown> }
export const getReviewEditorStatus = () => request<OfficeStatus>('/api/review/editor/status');
export const openReviewEditor = (jid: string, revision: string) => request<OfficeSession>(`${root(jid)}/editor`, json({ revision_id: revision, mode: 'edit' }));
export const getReviewEditorSession = (jid: string, session: string) =>
  request<{ status: string; revision_id?: string; message?: string; saved_at?: string | number; saved_request_id?: string }>(`${root(jid)}/editor/${encodeURIComponent(session)}`);
export const saveReviewEditor = (jid: string, session: string) =>
  request<{ status: string; message: string; save_request_id?: string }>(`${root(jid)}/editor/${encodeURIComponent(session)}/save`, json({}));
