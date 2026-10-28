import { fetchJSON } from '../../../shared/api/client';

export interface RuntimeLogEntry {
  timestamp?: string;
  level?: string;
  logger?: string;
  message?: string;
  correlation_id?: string;
  method?: string;
  path?: string;
  status_code?: number | string;
  duration_ms?: number | string;
  job_id?: string;
  jid?: string;
  stage?: string;
  stage_code?: string;
  event?: string;
  status?: string;
  product_type?: string;
  product_domain?: string;
  development_process?: string;
  process_classification?: string;
  model_provider?: string;
  provider?: string;
  model?: string;
  model_id?: string;
  operation?: string;
  attempt?: number | string;
  max_attempts?: number | string;
  retry_delay_ms?: number | string;
  error_type?: string;
  finish_reason?: string;
  completion_tokens?: number | string;
  reasoning_tokens?: number | string;
  content_chars?: number | string;
  warning_count?: number | string;
  requirement_source_count?: number | string;
  semantic_decision_count?: number | string;
  has_artifact?: boolean | string;
  error_summary?: string;
  submission_kind?: string;
  input_role?: string;
  previous_status?: string;
  parent_jid?: string;
  delivery_status?: string;
  qa_ok?: boolean | string;
  exception?: string;
  type?: string;
  [key: string]: unknown;
}

export interface RuntimeLogSnapshot {
  entries: RuntimeLogEntry[];
  returned: number;
  limit: number;
  source: string;
  updated_at: string | null;
  truncated: boolean;
  filtered_transport?: number;
}

export function loadLatestRuntimeLogs(limit = 200, signal?: AbortSignal) {
  return fetchJSON<RuntimeLogSnapshot>(
    `/api/logs/latest?${new URLSearchParams({ limit: String(limit) })}`,
    {
      headers: { 'X-Log-Viewer': '1' },
      signal,
    },
  );
}
