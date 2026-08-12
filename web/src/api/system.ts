/** 系统状态、历史记录与本机样例接口。 */
import type { HealthResponse, HistoryItem, LocalDefaultItem } from '../types';
import { getJSON } from './client';

export function loadBackendStatus(): Promise<HealthResponse> {
  return getJSON<HealthResponse>('/api/health');
}

export function loadHistory(): Promise<HistoryItem[]> {
  return getJSON<HistoryItem[]>('/api/history?include_legacy=true');
}

export function checkLocalFiles(): Promise<LocalDefaultItem[]> {
  return getJSON<LocalDefaultItem[]>('/api/local_defaults');
}
