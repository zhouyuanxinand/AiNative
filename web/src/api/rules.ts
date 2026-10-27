/** 可编辑业务规则：后端定义可修改字段，前端提交字段级变更。 */
import { fetchJSON, getJSON } from './client';

export type RulePath = (string | number)[];
export type RuleValue = string | number | boolean | string[];

export interface RuleField {
  path: RulePath;
  label: string;
  section: string;
  type: 'string' | 'number' | 'boolean' | 'string_list' | 'enum';
  description?: string;
  options?: string[];
  option_labels?: Record<string, string>;
}

export interface RuleListItem {
  id: string;
  title: string;
  group: string;
  description: string;
  revision: string;
  field_count: number;
}

export interface RuleAvailability {
  can_save: boolean;
  blocking_reason: string;
}

export interface RuleHistoryItem {
  event_id?: string;
  revision: string;
  created_at: string;
  note: string;
  actor: string;
  is_current: boolean;
}

export interface RuleDetail extends RuleListItem, RuleAvailability {
  updated_at: string;
  data: Record<string, unknown>;
  fields: RuleField[];
  history: RuleHistoryItem[];
}

export interface RuleChange { path: RulePath; value: RuleValue }
export interface RuleMutation {
  expected_revision: string;
  changes: RuleChange[];
  note: string;
}
export interface RuleValidation {
  valid: boolean;
  changes: { path: RulePath; label: string; before: RuleValue; after: RuleValue }[];
}

export function loadRules() {
  return getJSON<{ items: RuleListItem[] } & RuleAvailability>('/api/rules');
}

export function loadRule(id: string) {
  return getJSON<RuleDetail>(`/api/rules/${encodeURIComponent(id)}`);
}

function mutate<T>(id: string, suffix: string, method: string, body: unknown) {
  return fetchJSON<T>(`/api/rules/${encodeURIComponent(id)}${suffix}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function validateRule(id: string, body: RuleMutation) {
  return mutate<RuleValidation>(id, '/validate', 'POST', body);
}

export function saveRule(id: string, body: RuleMutation) {
  return mutate<RuleDetail>(id, '', 'PUT', body);
}

export function restoreRule(id: string, expectedRevision: string, revision: string, note: string) {
  return mutate<RuleDetail>(id, '/restore', 'POST', { expected_revision: expectedRevision, revision, note });
}
