/** 任务生命周期接口：提交、取消、状态轮询、预检。 */
import type { JobStatusResponse, PrecheckResponse } from '../types';
import { postForm, getJSON } from './client';

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
