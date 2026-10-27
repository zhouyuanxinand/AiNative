/** 任务生命周期接口：提交、取消、状态轮询、预检。 */
import type { IndicatorReview, JobStatusResponse, PrecheckResponse } from '../types';
import { postForm, getJSON, fetchJSON } from './client';

export function getIndicatorReview(jid: string): Promise<IndicatorReview> {
  return getJSON(`/api/indicator_review/${encodeURIComponent(jid)}`);
}

export function clarifyIndicators(jid: string, clarifications: Record<string, string>): Promise<{ jid: string; parent_jid: string }> {
  return fetchJSON(`/api/indicator_review/${encodeURIComponent(jid)}/clarify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ clarifications }),
  });
}

export function submitJob(fd: FormData): Promise<{ jid: string }> {
  return postForm('/api/submit', fd);
}

export function submitLocal(fd: FormData): Promise<{ jid: string }> {
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
