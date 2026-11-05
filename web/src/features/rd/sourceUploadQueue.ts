import type { SourceBatchItem } from './types';

export type SourceCategory = SourceBatchItem['role'] | 'unknown';
export type PrimarySourceRole = 'tech' | 'spec';
export type ExistingPrimarySources = Partial<Record<PrimarySourceRole, string>>;
export interface QueuedSource {
  id: string;
  file: File;
  role: SourceCategory;
  manual: boolean;
  classifying: boolean;
  reason: string;
  method: string;
}
export interface SourceQueue {
  items: QueuedSource[];
  primary: Record<PrimarySourceRole, string>;
}
export interface SourceSuggestion { id: string; role: SourceCategory; reason?: string; method?: string }
export const MAX_BATCH_FILES = 50;

export function emptySourceQueue(existing: ExistingPrimarySources = {}): SourceQueue {
  return { items: [], primary: { tech: existing.tech ? 'existing' : '', spec: existing.spec ? 'existing' : '' } };
}

export function reconcileSourcePrimary(queue: SourceQueue, existing: ExistingPrimarySources): SourceQueue {
  const primary = { ...queue.primary };
  for (const role of ['tech', 'spec'] as const) {
    if (primary[role] === 'existing' && existing[role] || queue.items.some(item => item.id === primary[role] && item.role === role)) continue;
    primary[role] = existing[role] ? 'existing' : queue.items.find(item => item.role === role)?.id ?? '';
  }
  return primary.tech === queue.primary.tech && primary.spec === queue.primary.spec ? queue : { ...queue, primary };
}

const fileIdentity = (file: File) => JSON.stringify([file.name, file.size, file.lastModified, file.type]);

export function appendSourceFiles(queue: SourceQueue, files: File[], existing: ExistingPrimarySources, nextId: () => string, role: SourceCategory = 'unknown') {
  const identities = new Set(queue.items.map(item => fileIdentity(item.file)));
  const items = [...queue.items];
  const accepted: string[] = [];
  const issues: string[] = [];
  for (const file of files) {
    if (!file.size) { issues.push(`已跳过空文件“${file.name}”。`); continue; }
    if (identities.has(fileIdentity(file))) { issues.push(`已跳过重复文件“${file.name}”。`); continue; }
    if (items.length >= MAX_BATCH_FILES) { issues.push(`每批最多 ${MAX_BATCH_FILES} 份文件，其余文件尚未加入。`); break; }
    const id = nextId();
    identities.add(fileIdentity(file)); accepted.push(id);
    items.push({ id, file, role, manual: role !== 'unknown', classifying: role === 'unknown', reason: '', method: '' });
  }
  return { queue: reconcileSourcePrimary({ ...queue, items }, existing), accepted, issues };
}

export function applySourceSuggestions(queue: SourceQueue, suggestions: SourceSuggestion[], requestedIds: string[], existing: ExistingPrimarySources): SourceQueue {
  const requested = new Set(requestedIds);
  const results = new Map(suggestions.map(item => [item.id, item]));
  const items = queue.items.map(item => {
    if (!requested.has(item.id)) return item;
    if (item.manual) return item.classifying ? { ...item, classifying: false } : item;
    const suggestion = results.get(item.id);
    const role = suggestion && ['tech', 'spec', 'reference', 'unknown'].includes(suggestion.role) ? suggestion.role : 'unknown';
    return { ...item, role, classifying: false, reason: suggestion?.reason ?? '', method: suggestion?.method ?? '' };
  });
  return reconcileSourcePrimary({ ...queue, items }, existing);
}

export function moveSourceFile(queue: SourceQueue, id: string, role: SourceCategory, existing: ExistingPrimarySources): SourceQueue {
  return reconcileSourcePrimary({ ...queue, items: queue.items.map(item => item.id === id ? { ...item, role, manual: true, classifying: false, reason: '已手动调整', method: 'manual' } : item) }, existing);
}

export function choosePrimarySource(queue: SourceQueue, role: PrimarySourceRole, id: string, existing: ExistingPrimarySources): SourceQueue {
  if (id === 'existing' ? !existing[role] : !queue.items.some(item => item.id === id && item.role === role)) return queue;
  return { ...queue, primary: { ...queue.primary, [role]: id } };
}

export function removeSourceFile(queue: SourceQueue, id: string, existing: ExistingPrimarySources): SourceQueue {
  return reconcileSourcePrimary({ ...queue, items: queue.items.filter(item => item.id !== id) }, existing);
}

export function sourceQueueIssue(queue: SourceQueue): string {
  if (!queue.items.length) return '请先选择文件。';
  if (queue.items.some(item => item.classifying && !item.manual)) return '正在识别文件分类，可手动调整后上传。';
  const unknown = queue.items.filter(item => item.role === 'unknown').length;
  if (unknown) return `还有 ${unknown} 份文件待分类，请选择用途。`;
  return '';
}

export function sourceBatchItems(queue: SourceQueue): SourceBatchItem[] {
  const issue = sourceQueueIssue(queue);
  if (issue) throw new Error(issue);
  return queue.items.map(item => {
    if (item.role === 'unknown') throw new Error('请先完成文件分类。');
    return { id: item.id, file: item.file, role: item.role, primary: item.role !== 'reference' && queue.primary[item.role] === item.id };
  });
}

export interface SourceBatchAttempt { items: SourceBatchItem[]; key: string; expectedVersion: number }
export function createSourceBatchAttempt(queue: SourceQueue, key: string, expectedVersion: number): SourceBatchAttempt {
  return { items: sourceBatchItems(queue), key, expectedVersion };
}
