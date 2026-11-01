import type { AssistantMessage, AssistantResponse } from './types';

export function mergeAssistantMessages(previous: AssistantMessage[], incoming: AssistantMessage[]): AssistantMessage[] {
  const byId = new Map(previous.map(message => [message.id, message]));
  for (const message of incoming) byId.set(message.id, message);
  const bySequence = new Map<string, AssistantMessage>();
  for (const message of byId.values()) bySequence.set(Number.isFinite(message.seq) ? `seq:${message.seq}` : `id:${message.id}`, message);
  return [...bySequence.values()].sort((left, right) => left.seq - right.seq || left.created_at.localeCompare(right.created_at));
}

/** Keep the cursor that can fill unread history, including gaps between loaded windows. */
export function mergeAssistantHistory(previous: AssistantResponse | null, incoming: AssistantResponse, older = false): AssistantResponse {
  if (!previous) return incoming;
  const messages = mergeAssistantMessages(previous.messages, incoming.messages);
  const incomingIds = new Set(incoming.messages.map(message => message.id));
  const incomingSequences = new Set(incoming.messages.map(message => message.seq));
  const overlaps = previous.messages.some(message => incomingIds.has(message.id) || incomingSequences.has(message.seq));
  const previousFirst = previous.messages[0]?.seq;
  const incomingFirst = incoming.messages[0]?.seq;
  const previousLast = previous.messages[previous.messages.length - 1]?.seq;
  const incomingLast = incoming.messages[incoming.messages.length - 1]?.seq;
  // A disjoint newer page may have unread messages before it. Fetch from that page,
  // even when an older page was once fully read; seq gaps alone are not evidence.
  const retainsPreviousCursor = !older && previousFirst !== undefined && incomingFirst !== undefined
    && (overlaps ? previousFirst < incomingFirst : incomingLast <= previousLast);
  let history = retainsPreviousCursor && previous.history && incoming.history ? { ...incoming.history, has_more: previous.history.has_more, next_before: previous.history.next_before } : incoming.history ?? previous.history;
  const total = Math.max(messages.length, previous.history?.total ?? 0, incoming.history?.total ?? 0);
  if (history && messages.length >= total) history = { ...history, has_more: false, next_before: null };
  else if (history && !history.has_more && incoming.history?.has_more) history = { ...incoming.history };
  const current = incoming.context.project_version < previous.context.project_version ? previous : incoming;
  return { ...current, messages, history: history ? { ...history, total } : undefined };
}
