import { fetchJSON } from '../../../shared/api/client';
import { rdRequest } from '../../rd/api/rd';

export type AssistantMode = 'auto' | 'platform' | 'general';
export interface AssistantAction { id: string; label: string; description: string; href: string; prompt?: string }
export interface AssistantProposal {
  id: string; project_id: string; project_name: string; action: string; label: string; summary: string;
  expected_version: number; payload: Record<string, unknown>; expires_at: string;
  fields: { label: string; value: string }[]; warnings: string[];
}
export interface AssistantContext {
  name: string; model_available: boolean; role_label: string;
  project: { id: string; name: string; code: string; stage_label: string; route_label: string } | null;
  quick_actions: AssistantAction[]; suggested_questions: string[];
}
export interface AssistantHistory { role: 'user' | 'assistant'; content: string }
export interface AssistantReply {
  reply: string; mode: 'platform' | 'general'; intent?: string; source: 'model' | 'platform-guide'; model?: string;
  actions: AssistantAction[]; proposal?: AssistantProposal | null;
}
export interface AssistantOperationResult { status: 'executed'; proposal_id: string; message: string; project_id: string; project_version: number; href: string }
export const getAssistantContext = (projectId: string | undefined, signal: AbortSignal) => rdRequest<AssistantContext>(
  `/api/assistant/context${projectId ? `?${new URLSearchParams({ project_id: projectId })}` : ''}`, { signal },
);
export const confirmAssistantProposal = (id: string) => rdRequest<AssistantOperationResult>(`/api/assistant/operations/${encodeURIComponent(id)}/confirm`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
});

/** The server owns all model credentials. General chat deliberately omits project context. */
export async function askAssistant(body: { mode: AssistantMode; message: string; history: AssistantHistory[]; project_id?: string }, signal: AbortSignal): Promise<AssistantReply> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal.aborted) abort(); else signal.addEventListener('abort', abort, { once: true });
  let timedOut = false;
  const timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, 90000);
  try {
    const { project_id, ...generalBody } = body;
    return await fetchJSON<AssistantReply>('/api/assistant/chat', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body.mode === 'general' ? generalBody : body),
    });
  } catch (reason) {
    if (timedOut) throw new Error('小航回复超时，请重试。问题已保留。');
    if (reason instanceof TypeError) throw new Error('暂时无法连接小航，请检查连接后重试。');
    throw reason;
  } finally { window.clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
