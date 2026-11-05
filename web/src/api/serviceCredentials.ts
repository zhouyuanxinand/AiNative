/** Same request/response contract as mail, intelligence and defense settings. */
export type CredentialGroup = 'model';
export type CredentialValues = Record<CredentialGroup, Record<string, string>>;
export type CredentialOverrides = Record<CredentialGroup, Record<string, string> | null>;
export interface CredentialHistoryEntry {
  id: string;
  name: string;
  base_url: string;
  app_id: string;
  tenant_id: string;
  created_at: string;
  last_used_at: string | null;
  active: boolean;
  source: string;
}
export interface ServiceCredentialsResponse {
  defaults: CredentialValues;
  effective: CredentialValues;
  overridden: CredentialGroup[];
  history: CredentialHistoryEntry[];
}

export interface TestableModel {
  model: string;
  id: string;
  provider: string;
  vendor: string;
  configured: boolean;
}
export interface ModelConnectionResult {
  success: boolean;
  model: string;
  response_time_ms: number;
  checked_at: string;
  message: string;
  error_code?: string;
}
export interface ModelCatalogResult extends Omit<ModelConnectionResult, 'model'> {
  models: TestableModel[];
}

export interface DefaultModelSelection { provider: string; name: string; id: string }
export interface DefaultModelResponse {
  selection: DefaultModelSelection | null;
  source: 'settings' | 'deployment';
  requires_selection: boolean;
}

export async function requestDefaultModel(selection?: DefaultModelSelection, signal?: AbortSignal): Promise<DefaultModelResponse> {
  const response = await fetch('/api/settings/credentials/default-model', {
    method: selection ? 'PUT' : 'GET',
    headers: { 'X-Credential-Settings': '1', ...(selection ? { 'Content-Type': 'application/json' } : {}) },
    credentials: 'same-origin', cache: 'no-store', signal,
    ...(selection ? { body: JSON.stringify(selection) } : {}),
  });
  if (!response.ok) {
    let message = '';
    try { const body = await response.json(); message = body.error || body.detail || ''; } catch { /* Proxy response may be text. */ }
    throw new Error(typeof message === 'string' && message ? message : `默认模型${selection ? '未保存' : '读取失败'}（HTTP ${response.status}），请重试。`);
  }
  return response.json();
}

export async function requestDefaultModelCatalog(signal: AbortSignal): Promise<TestableModel[]> {
  const response = await fetch('/api/models', { credentials: 'same-origin', cache: 'no-store', signal });
  const body = await response.json();
  if (!response.ok || body.success !== true || !Array.isArray(body.models)) {
    throw new Error(typeof body.error === 'string' ? body.error : '模型目录读取失败，请重试。');
  }
  return body.models;
}

async function requestModelProbe<T>(path: string, payload: object, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'X-Credential-Settings': '1', 'Content-Type': 'application/json' },
    cache: 'no-store',
    credentials: 'same-origin',
    signal,
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let message = '';
    try {
      const body = await response.json();
      message = typeof body.message === 'string' ? body.message
        : typeof body.error === 'string' ? body.error : typeof body.detail === 'string' ? body.detail : '';
    } catch { /* A proxy may return a non-JSON response. */ }
    throw new Error(message || `测试请求失败（HTTP ${response.status}），请检查服务状态后重试。`);
  }
  return response.json();
}

export function requestTestableModels(credentials: CredentialOverrides, signal: AbortSignal): Promise<ModelCatalogResult> {
  return requestModelProbe('/api/settings/credentials/test/models', { credentials }, signal);
}

export function testModelConnection(
  credentials: CredentialOverrides,
  model: string,
  modelId: string | undefined,
  signal: AbortSignal,
): Promise<ModelConnectionResult> {
  return requestModelProbe('/api/settings/credentials/test', {
    credentials, model, ...(modelId ? { model_id: modelId } : {}),
  }, signal);
}

async function readCredentialsResponse(response: Response): Promise<ServiceCredentialsResponse> {
  if (!response.ok) {
    let message = '';
    try {
      const body = await response.json();
      message = typeof body.error === 'string' ? body.error : typeof body.detail === 'string' ? body.detail : '';
    } catch { /* Proxy errors may not be JSON. */ }
    throw new Error(message || `凭证请求失败（HTTP ${response.status}），请稍后重试。`);
  }
  return response.json();
}

export async function requestServiceCredentials(
  payload?: CredentialOverrides,
  signal?: AbortSignal,
): Promise<ServiceCredentialsResponse> {
  const response = await fetch('/api/settings/credentials', {
    method: payload ? 'PUT' : 'GET',
    headers: { 'X-Credential-Settings': '1', ...(payload ? { 'Content-Type': 'application/json' } : {}) },
    cache: 'no-store',
    credentials: 'same-origin',
    signal,
    ...(payload ? { body: JSON.stringify(payload) } : {}),
  });
  return readCredentialsResponse(response);
}

export async function changeCredentialHistory(
  id: string,
  action: 'activate' | 'delete',
  signal?: AbortSignal,
): Promise<ServiceCredentialsResponse> {
  const response = await fetch(`/api/settings/credentials/history/${encodeURIComponent(id)}${action === 'activate' ? '/activate' : ''}`, {
    method: action === 'activate' ? 'POST' : 'DELETE',
    headers: { 'X-Credential-Settings': '1' },
    cache: 'no-store',
    credentials: 'same-origin',
    signal,
  });
  return readCredentialsResponse(response);
}
