/** 任务生命周期接口：提交、取消、状态轮询、预检。 */
import type { IndicatorReview, JobStatusResponse, PrecheckResponse } from '../model/types';
import { postForm, getJSON, fetchJSON } from '../../../shared/api/client';
import { completeRdGeneration, prepareRdGeneration, readRdContext } from '../model/rdGeneration';

export function getIndicatorReview(jid: string): Promise<IndicatorReview> {
  return getJSON(`/api/indicator_review/${encodeURIComponent(jid)}`);
}

const clarificationIntents = new Map<string, string>();

export async function clarifyIndicators(jid: string, clarifications: Record<string, string>): Promise<{ jid: string; parent_jid: string }> {
  const intent = JSON.stringify([jid, Object.entries(clarifications).sort(([a], [b]) => a.localeCompare(b))]);
  let key = clarificationIntents.get(intent);
  if (!key) {
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
    key = `indicator-clarification-${Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')}`;
    clarificationIntents.set(intent, key);
  }
  const result = await fetchJSON<{ jid: string; parent_jid: string }>(`/api/indicator_review/${encodeURIComponent(jid)}/clarify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify({ clarifications }),
  });
  clarificationIntents.delete(intent);
  return result;
}

export async function submitJob(fd: FormData): Promise<{ jid: string }> {
  const key = prepareRdGeneration(fd, window.location.search);
  const result = await fetchJSON<{ jid: string }>('/api/submit', { method: 'POST', body: fd,
    headers: key ? { 'Idempotency-Key': key } : undefined });
  completeRdGeneration(key);
  return result;
}

export function submitLocal(fd: FormData): Promise<{ jid: string }> {
  if (readRdContext(window.location.search)) return Promise.reject(new Error('项目任务请上传当前基线对应的资料，不能使用独立演示样例。'));
  return postForm('/api/submit_local', fd);
}

export function cancelJob(jid: string): Promise<{ jid: string; status: string; message?: string }> {
  return postForm(`/api/cancel/${encodeURIComponent(jid)}`, new FormData());
}

export function getJobStatus(jid: string, after = 0): Promise<JobStatusResponse> {
  return getJSON<JobStatusResponse>(
    `/api/status/${encodeURIComponent(jid)}?after=${after}`,
  );
}

export function runPrecheck(fd: FormData): Promise<PrecheckResponse> {
  return postForm('/api/precheck', fd);
}

export function runPrecheckLocal(fd: FormData): Promise<PrecheckResponse> {
  return postForm('/api/precheck_local', fd);
}
