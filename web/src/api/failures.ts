import { fetchJSON, getJSON } from './client';

export interface FailureFields {
  product_type: string;
  product_name: string;
  product_series: string;
  product_model: string;
  failure_location: string;
  failure_mode: string;
  failure_analysis: string;
  improvement: string;
}

export interface FailureRecord extends FailureFields {
  id: number;
  version: number;
  created_at: string;
  updated_at: string;
  source_file: string;
  source_sheet: string;
  source_row: number | null;
  source_data?: Record<string, string>;
}

export interface FailureOptions {
  products: { id: string; label: string; count: number }[];
  unclassified_count: number;
  total: number;
  source_file: string;
  imported_count: number;
}

export interface FailurePage {
  items: FailureRecord[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export function listFailures(filters: { q: string; product_type: string; series: string }, page: number) {
  return getJSON<FailurePage>('/api/failures?' + new URLSearchParams({ ...filters, page: String(page) }));
}

export function failureOptions() { return getJSON<FailureOptions>('/api/failures/options'); }
export function getFailure(id: number) { return getJSON<FailureRecord>('/api/failures/' + id); }

export function saveFailure(fields: FailureFields, record?: FailureRecord | null) {
  return fetchJSON<FailureRecord>('/api/failures' + (record ? '/' + record.id : ''), {
    method: record ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...fields, ...(record ? { expected_version: record.version } : {}) }),
  });
}

export function deleteFailure(record: FailureRecord) {
  return fetchJSON<{ deleted: boolean }>('/api/failures/' + record.id + '?expected_version=' + record.version, { method: 'DELETE' });
}
